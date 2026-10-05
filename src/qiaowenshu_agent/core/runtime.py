"""Minimal composable Agent Runtime.

The runtime owns planning, budgets, events, and trace. Skills own business logic
and may be replaced independently through their injected backend ports.
"""

from __future__ import annotations

import copy
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping, Protocol
from uuid import uuid4

from qiaowenshu_agent.core.budget import BudgetLedger
from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest, SkillResult
from qiaowenshu_agent.core.events import InMemoryEventSink
from qiaowenshu_agent.core.registry import SkillRegistry
from qiaowenshu_agent.core.store import AgentRun, InMemoryStore


@dataclass(frozen=True)
class PlanStep:
    """One sequential Skill invocation.

    An input value may contain ``{"$ref": "$state/<skill>/<path>"}`` or
    ``{"$ref": "$request/<path>"}`` to make data flow explicit.
    """

    skill_name: str
    input: dict[str, Any] | None = None

    def to_dict(self) -> dict[str, Any]:
        return {"skill_name": self.skill_name, "input": dict(self.input or {})}


class StepInputReferenceError(ValueError):
    """Raised when a declared step input references unavailable state."""


class Planner(Protocol):
    def plan(
        self, request: SkillRequest, registry: SkillRegistry
    ) -> list[PlanStep]: ...


class DeterministicPlanner:
    """Safe baseline planner; an LLM planner can implement the same protocol."""

    def __init__(self, *, default_skill: str | None = "knowledge-retrieval") -> None:
        self.default_skill = default_skill

    def plan(self, request: SkillRequest, registry: SkillRegistry) -> list[PlanStep]:
        if request.skill_name:
            return [PlanStep(request.skill_name)]

        declared_plan = request.input.get("plan")
        if isinstance(declared_plan, list):
            steps: list[PlanStep] = []
            for item in declared_plan:
                if not isinstance(item, dict):
                    continue
                skill_name = str(item.get("skill_name") or "").strip()
                if skill_name:
                    step_input = item.get("input")
                    steps.append(
                        PlanStep(
                            skill_name=skill_name,
                            input=(
                                dict(step_input)
                                if isinstance(step_input, dict)
                                else None
                            ),
                        )
                    )
            if steps:
                return steps

        requested_skill = request.input.get("skill")
        if isinstance(requested_skill, str) and requested_skill.strip():
            return [PlanStep(requested_skill.strip())]

        text = " ".join(
            str(request.input.get(key, "")) for key in ("query", "task", "instruction")
        ).lower()
        if _has_file_backed_tender_input(request.input):
            if any(
                term in text
                for term in (
                    "能不能投",
                    "是否投标",
                    "投标可行",
                    "值得投",
                    "bid feasibility",
                    "feasibility",
                )
            ):
                return _file_backed_feasibility_plan(request.input)
            if any(
                term in text
                for term in (
                    "分析招标文件",
                    "分析这份招标文件",
                    "读取招标文件",
                    "阅读招标文件",
                    "读标",
                    "招标文件解析",
                    "生成投标方案",
                    "准备投标文件",
                    "tender intake",
                )
            ):
                return _file_backed_intake_plan()
        keyword_routes = (
            (("预处理", "preprocess", "转换", "标准化"), "document-preprocess"),
            (
                (
                    "分析招标文件",
                    "分析这份招标文件",
                    "读取招标文件",
                    "阅读招标文件",
                    "阅读这份招标文件",
                    "读标",
                    "招标文件解析",
                    "生成投标方案",
                    "准备投标文件",
                    "tender intake",
                ),
                "tender-intake",
            ),
            (
                (
                    "撰写投标文件",
                    "生成投标文件",
                    "标书撰写",
                    "标书智写",
                    "投标文件正文",
                    "document writing",
                    "bid intelligent write",
                ),
                "document-writing",
            ),
            (
                (
                    "废标风险",
                    "无效投标",
                    "资格审查风险",
                    "符合性审查风险",
                    "bid risk",
                ),
                "bid-feasibility",
            ),
            (
                (
                    "拆解资格",
                    "资格条件",
                    "识别废标项",
                    "一票否决项",
                    "tender decomposition",
                ),
                "tender-decomposition",
            ),
            (
                ("投标可行", "是否投标", "bid feasibility", "feasibility"),
                "bid-feasibility",
            ),
            (
                ("评分标准", "评分策略", "得分策略", "scoring strategy"),
                "scoring-strategy",
            ),
            (
                ("证明材料", "材料匹配", "证据匹配", "evidence matching"),
                "evidence-matching",
            ),
            (("画像", "profile", "文档结构", "pdf"), "document-profile"),
            (
                ("检索", "搜索", "知识库", "retrieve", "search"),
                "knowledge-retrieval",
            ),
        )
        for keywords, skill_name in keyword_routes:
            if any(keyword.lower() in text for keyword in keywords):
                return [PlanStep(skill_name)]

        if self.default_skill and registry.get(self.default_skill) is not None:
            return [PlanStep(self.default_skill)]
        return []


def _has_file_backed_tender_input(input_data: Mapping[str, Any]) -> bool:
    file_ids = input_data.get("file_ids")
    return (
        bool(str(input_data.get("project_id") or "").strip())
        and isinstance(file_ids, (list, tuple))
        and bool(file_ids)
    )


def _file_backed_intake_plan(*, include_analysis: bool = True) -> list[PlanStep]:
    plan = [
        PlanStep(
            "document-preprocess",
            {
                "file_id": {"$ref": "$request/file_ids/0"},
                "business_scene": "tender_parse",
                "file_role": "tender",
            },
        ),
        PlanStep(
            "tender-intake",
            {
                "project_id": {"$ref": "$request/project_id"},
                "file_ids": {"$ref": "$request/file_ids"},
            },
        ),
        PlanStep(
            "consistency-review",
            {
                "project_id": {"$ref": "$request/project_id"},
                "documents": {"$ref": "$state/tender-intake/pages"},
            },
        ),
        PlanStep(
            "tender-decomposition",
            {
                "project_id": {"$ref": "$request/project_id"},
                "profile": {"$ref": "$state/tender-intake/profile"},
                "sections": {"$ref": "$state/tender-intake/sections"},
            },
        ),
    ]
    if include_analysis:
        plan.extend(
            [
                PlanStep(
                    "scoring-strategy",
                    {
                        "project_id": {"$ref": "$request/project_id"},
                        "requirements": {
                            "$ref": "$state/tender-decomposition/requirements"
                        },
                        "scoring_items": {
                            "$ref": "$state/tender-decomposition/scoring_items"
                        },
                    },
                ),
                PlanStep(
                    "analysis-report",
                    {
                        "project_id": {"$ref": "$request/project_id"},
                        "project": {"$ref": "$state/tender-intake/profile"},
                        "scoring": {"$ref": "$state/scoring-strategy"},
                    },
                ),
            ]
        )
    return plan


def _file_backed_feasibility_plan(input_data: Mapping[str, Any]) -> list[PlanStep]:
    plan = _file_backed_intake_plan(include_analysis=False)
    bidder_file_ids = input_data.get("bidder_file_ids")
    if isinstance(bidder_file_ids, (list, tuple)) and bidder_file_ids:
        plan.append(
            PlanStep(
                "bidder-material-intake",
                {
                    "project_id": {"$ref": "$request/project_id"},
                    "bidder_id": str(input_data.get("bidder_id") or "unknown"),
                    "bidder_name": str(input_data.get("bidder_name") or ""),
                    "file_ids": {"$ref": "$request/bidder_file_ids"},
                    "as_of": input_data.get("as_of"),
                },
            )
        )
        bidder_ref: Any = {"$ref": "$state/bidder-material-intake/bidder_profile"}
        material_ref: Any = {"$ref": "$state/bidder-material-intake/materials"}
    else:
        bidder_ref = (
            {"$ref": "$request/bidder_profile"}
            if "bidder_profile" in input_data
            else {"bidder_id": "unknown"}
        )
        material_ref = (
            {"$ref": "$request/materials"} if "materials" in input_data else []
        )
    plan.extend(
        [
            PlanStep(
                "evidence-matching",
                {
                    "project_id": {"$ref": "$request/project_id"},
                    "requirements": {
                        "$ref": "$state/tender-decomposition/requirements"
                    },
                    "scoring_items": {
                        "$ref": "$state/tender-decomposition/scoring_items"
                    },
                    "materials": material_ref,
                    "as_of": input_data.get("as_of"),
                },
            ),
            PlanStep(
                "bid-feasibility",
                {
                    "project_id": {"$ref": "$request/project_id"},
                    "requirements": {
                        "$ref": "$state/tender-decomposition/requirements"
                    },
                    "bidder_profile": bidder_ref,
                    "as_of": input_data.get("as_of"),
                },
            ),
            PlanStep(
                "requirement-ledger",
                {
                    "project_id": {"$ref": "$request/project_id"},
                    "requirements": {
                        "$ref": "$state/tender-decomposition/requirements"
                    },
                    "scoring_items": {
                        "$ref": "$state/tender-decomposition/scoring_items"
                    },
                    "evidence_matches": {"$ref": "$state/evidence-matching/matches"},
                    "feasibility_checks": {"$ref": "$state/bid-feasibility/checks"},
                },
            ),
            PlanStep(
                "compliance-review",
                {
                    "project_id": {"$ref": "$request/project_id"},
                    "ledger": {"$ref": "$state/requirement-ledger"},
                    "consistency_result": {"$ref": "$state/consistency-review"},
                },
            ),
            PlanStep(
                "scoring-strategy",
                {
                    "project_id": {"$ref": "$request/project_id"},
                    "requirements": {
                        "$ref": "$state/tender-decomposition/requirements"
                    },
                    "scoring_items": {
                        "$ref": "$state/tender-decomposition/scoring_items"
                    },
                    "evidence_materials": material_ref,
                    "evidence_matches": {
                        "$ref": "$state/evidence-matching/matches"
                    },
                    "as_of": input_data.get("as_of"),
                },
            ),
            PlanStep(
                "analysis-report",
                {
                    "project_id": {"$ref": "$request/project_id"},
                    "project": {"$ref": "$state/tender-intake/profile"},
                    "feasibility": {"$ref": "$state/bid-feasibility"},
                    "scoring": {"$ref": "$state/scoring-strategy"},
                    "ledger": {"$ref": "$state/requirement-ledger"},
                    "compliance": {"$ref": "$state/compliance-review"},
                },
            ),
        ]
    )
    return plan


@dataclass
class AgentStepResult:
    skill_name: str
    result: SkillResult

    def to_dict(self) -> dict[str, Any]:
        return {"skill_name": self.skill_name, "result": self.result.to_dict()}


@dataclass
class AgentRunResult:
    run_id: str
    status: str
    output: dict[str, Any] = field(default_factory=dict)
    message: str = ""
    steps: list[AgentStepResult] = field(default_factory=list)
    trace: list[dict[str, Any]] = field(default_factory=list)
    events: list[dict[str, Any]] = field(default_factory=list)
    budget: dict[str, int] = field(default_factory=dict)
    elapsed_ms: int = 0

    @property
    def execution_status(self) -> str:
        return _execution_status(self.status)

    @property
    def business_status(self) -> str:
        return _result_business_assessment(self.steps, self.output)[
            "business_status"
        ]

    @property
    def needs_human_review(self) -> bool:
        return _result_business_assessment(self.steps, self.output)[
            "needs_human_review"
        ]

    @property
    def submission_allowed(self) -> bool:
        return False

    @property
    def scoped_gate_passed(self) -> bool:
        return _result_business_assessment(self.steps, self.output)[
            "scoped_gate_passed"
        ]

    def to_dict(self) -> dict[str, Any]:
        assessment = _result_business_assessment(self.steps, self.output)
        return {
            "run_id": self.run_id,
            "status": self.status,
            "execution_status": self.execution_status,
            "business_status": assessment["business_status"],
            "needs_human_review": (
                assessment["needs_human_review"]
                or self.execution_status == "running"
            ),
            "submission_allowed": False,
            "scoped_gate_passed": assessment["scoped_gate_passed"],
            "output": self.output,
            "message": self.message,
            "steps": [step.to_dict() for step in self.steps],
            "warnings": assessment["warnings"],
            "risks": assessment["risks"],
            "trace": list(self.trace),
            "events": list(self.events),
            "budget": dict(self.budget),
            "elapsed_ms": self.elapsed_ms,
        }


class AgentRuntime:
    def __init__(
        self,
        registry: SkillRegistry,
        *,
        planner: Planner | None = None,
        services: dict[str, Any] | None = None,
        token_budget: int = 40_000,
        step_budget: int = 12,
    ) -> None:
        self.registry = registry
        self.planner = planner or DeterministicPlanner()
        self.services = dict(services or {})
        configured_store = self.services.get("store")
        file_registry = self.services.get("file_registry")
        if configured_store is None and hasattr(file_registry, "store"):
            configured_store = file_registry.store
        if configured_store is None:
            configured_store = InMemoryStore()
        self.store = configured_store
        self.services["store"] = configured_store
        self.token_budget = token_budget
        self.step_budget = step_budget

    async def run(
        self,
        request: SkillRequest,
        *,
        run_id: str | None = None,
    ) -> AgentRunResult:
        return await self._execute(
            request,
            run_id=run_id or f"run_{uuid4().hex[:16]}",
        )

    async def resume(self, run_id: str) -> AgentRunResult:
        """Resume a persisted run from its last completed step."""

        record = self.store.get_run(run_id)
        if record is None:
            raise KeyError(f"run not found: {run_id}")
        request = _request_from_dict(record.request)
        plan = [
            PlanStep(
                str(item.get("skill_name") or ""),
                (
                    dict(item.get("input"))
                    if isinstance(item.get("input"), dict)
                    else None
                ),
            )
            for item in record.plan
            if str(item.get("skill_name") or "").strip()
        ]
        completed_count = (
            len(record.artifact_ids)
            if record.status in {"success", "partial"}
            else max(0, record.next_step_index)
        )
        dependency_issues = self._run_dependency_issues(
            request,
            plan,
            record.artifact_ids[:completed_count],
        )
        if dependency_issues:
            return _blocked_stale_run_result(record, dependency_issues)
        if record.status in {"success", "partial"}:
            return _agent_result_from_record(record)
        return await self._execute(
            request,
            run_id=record.run_id,
            resume_record=record,
            plan=plan,
        )

    def inspect_run(self, run_id: str) -> dict[str, Any] | None:
        """Return a read-only run snapshot with current runtime assessments."""

        record = self.store.get_run(run_id)
        if record is None:
            return None
        request = _request_from_dict(record.request)
        plan = [
            PlanStep(
                str(item.get("skill_name") or ""),
                dict(item.get("input"))
                if isinstance(item.get("input"), dict)
                else None,
            )
            for item in record.plan
            if str(item.get("skill_name") or "").strip()
        ]
        completed_count = (
            len(record.artifact_ids)
            if record.status in {"success", "partial"}
            else max(0, record.next_step_index)
        )
        issues = self._run_dependency_issues(
            request,
            plan,
            record.artifact_ids[:completed_count],
        )
        result = (
            _blocked_stale_run_result(record, issues)
            if issues
            else _agent_result_from_record(record)
        )
        snapshot = record.to_dict()
        snapshot.update(result.to_dict())
        snapshot["persisted_status"] = record.status
        snapshot["dependency_status"] = "stale" if issues else "valid"
        snapshot["dependency_issues"] = issues
        return snapshot

    async def _execute(
        self,
        request: SkillRequest,
        *,
        run_id: str,
        resume_record: AgentRun | None = None,
        plan: list[PlanStep] | None = None,
    ) -> AgentRunResult:
        started = time.monotonic()
        previous_events = list(resume_record.events) if resume_record else []
        previous_trace = list(resume_record.trace) if resume_record else []
        previous_elapsed = resume_record.elapsed_ms if resume_record else 0
        event_sink = InMemoryEventSink()
        context = SkillContext(
            run_id=run_id,
            request=request,
            services=dict(self.services),
            state=copy.deepcopy(resume_record.state) if resume_record else {},
            budget=BudgetLedger(
                token_capacity=(
                    _budget_capacity(resume_record, "token_capacity", self.token_budget)
                ),
                step_capacity=(
                    _budget_capacity(resume_record, "step_capacity", self.step_budget)
                ),
                tokens_used=(
                    _budget_value(resume_record, "tokens_used") if resume_record else 0
                ),
                steps_used=(
                    _budget_value(resume_record, "steps_used") if resume_record else 0
                ),
            ),
            event_sink=event_sink,
        )
        context.emit(
            "run_started",
            payload={
                "request_id": request.request_id,
                "resumed": resume_record is not None,
            },
        )

        if plan is None:
            try:
                plan = self.planner.plan(request, self.registry)
            except Exception as exc:
                context.emit("run_failed", payload={"error": str(exc)})
                result = self._result(
                    context,
                    started,
                    status="error",
                    message=f"planner failed: {exc}",
                    previous_events=previous_events,
                    previous_trace=previous_trace,
                    elapsed_base=previous_elapsed,
                )
                self._persist_run(
                    request=request,
                    plan=[],
                    context=context,
                    steps=[],
                    status=result.status,
                    output=result.output,
                    message=result.message,
                    artifact_ids=[],
                    next_step_index=0,
                    created_at=_record_created_at(resume_record),
                    previous_events=previous_events,
                    previous_trace=previous_trace,
                    elapsed_ms=result.elapsed_ms,
                )
                return result

        context.emit(
            "plan_created",
            payload={"steps": [step.to_dict() for step in plan]},
        )
        steps = _steps_from_record(resume_record) if resume_record else []
        artifact_ids = list(resume_record.artifact_ids) if resume_record else []
        start_index = (
            max(0, resume_record.next_step_index) if resume_record else 0
        )
        created_at = _record_created_at(resume_record)
        dependency_issues = self._run_dependency_issues(
            request,
            plan,
            artifact_ids[:start_index],
        )
        if dependency_issues:
            context.emit(
                "run_failed",
                payload={
                    "error_code": "STALE_RUN_DEPENDENCIES",
                    "dependency_issues": dependency_issues,
                },
            )
            result = self._result(
                context,
                started,
                status="blocked",
                output={
                    "error_code": "STALE_RUN_DEPENDENCIES",
                    "dependency_issues": dependency_issues,
                },
                message="run dependencies are stale or missing; start a new run",
                steps=steps,
                previous_events=previous_events,
                previous_trace=previous_trace,
                elapsed_base=previous_elapsed,
            )
            self._persist_run(
                request=request,
                plan=plan,
                context=context,
                steps=steps,
                status=result.status,
                output=result.output,
                message=result.message,
                artifact_ids=artifact_ids,
                next_step_index=start_index,
                created_at=created_at,
                previous_events=previous_events,
                previous_trace=previous_trace,
                elapsed_ms=result.elapsed_ms,
            )
            return result
        self._persist_run(
            request=request,
            plan=plan,
            context=context,
            steps=steps,
            status="running",
            output={},
            message="",
            artifact_ids=artifact_ids,
            next_step_index=start_index,
            created_at=created_at,
            previous_events=previous_events,
            previous_trace=previous_trace,
            elapsed_ms=previous_elapsed,
        )
        if not plan:
            context.emit("run_failed", payload={"error": "no skill matched"})
            result = self._result(
                context,
                started,
                status="blocked",
                message="no skill matched the request",
                previous_events=previous_events,
                previous_trace=previous_trace,
                elapsed_base=previous_elapsed,
            )
            self._persist_run(
                request=request,
                plan=plan,
                context=context,
                steps=steps,
                status=result.status,
                output=result.output,
                message=result.message,
                artifact_ids=artifact_ids,
                next_step_index=0,
                created_at=created_at,
                previous_events=previous_events,
                previous_trace=previous_trace,
                elapsed_ms=result.elapsed_ms,
            )
            return result

        final_result: SkillResult | None = None
        next_step_index = start_index
        completed_artifacts: dict[str, list[str]] = {}
        for index, step in enumerate(plan):
            if index < start_index:
                if index < len(steps):
                    final_result = steps[index].result
                if index < len(artifact_ids) and artifact_ids[index]:
                    completed_artifacts.setdefault(step.skill_name, []).append(
                        artifact_ids[index]
                    )
                continue

            gate_kind = _capability_gate_kind(step.skill_name, self.registry)
            if gate_kind is not None:
                assessment = _business_assessment(steps)
                if gate_kind == "submission":
                    reason = (
                        "final submission is not authorized by the scoped review; "
                        "submission_allowed remains false"
                    )
                elif not assessment["scoped_gate_passed"]:
                    reason = (
                        "writing/export requires a checked scoped compliance pass "
                        "with no blockers; current business_status is "
                        f"{assessment['business_status']}"
                    )
                else:
                    reason = ""
                if reason:
                    final_result = SkillResult(
                        status="blocked",
                        data={
                            "error_code": "COMPLIANCE_GATE_BLOCKED",
                            "gate_reason": reason,
                            "business_status": assessment["business_status"],
                            "scoped_gate_passed": assessment[
                                "scoped_gate_passed"
                            ],
                        },
                        message=reason,
                        error_code="COMPLIANCE_GATE_BLOCKED",
                    )
                    _set_step(
                        steps,
                        index,
                        AgentStepResult(step.skill_name, final_result),
                    )
                    context.emit(
                        "run_failed",
                        payload={
                            "error_code": "COMPLIANCE_GATE_BLOCKED",
                            "skill_name": step.skill_name,
                            "gate_reason": reason,
                            "business_status": assessment["business_status"],
                        },
                    )
                    next_step_index = index
                    break

            if not context.budget.reserve_step():
                final_result = SkillResult.blocked(
                    message="agent step budget exhausted",
                    error_code="STEP_BUDGET_EXHAUSTED",
                )
                next_step_index = index
                break

            skill = self.registry.get(step.skill_name)
            if skill is None:
                final_result = SkillResult.failure(
                    message=f"skill not found: {step.skill_name}",
                    error_code="SKILL_NOT_FOUND",
                )
                _set_step(steps, index, AgentStepResult(step.skill_name, final_result))
                next_step_index = index
                break

            try:
                raw_input = step.input if step.input is not None else request.input
                resolved_input = resolve_step_input(
                    raw_input,
                    state=context.state,
                    request_input=request.input,
                )
                if not isinstance(resolved_input, dict):
                    raise StepInputReferenceError(
                        "resolved step input must be an object"
                    )
            except StepInputReferenceError as exc:
                result = SkillResult.failure(
                    message=str(exc),
                    error_code="INVALID_STEP_INPUT_REFERENCE",
                )
                result.trace_id = run_id
                context.state[step.skill_name] = result.data
                _set_step(steps, index, AgentStepResult(step.skill_name, result))
                final_result = result
                context.emit(
                    "skill_finished",
                    skill_name=step.skill_name,
                    payload={
                        "status": result.status,
                        "error_code": result.error_code,
                    },
                )
                next_step_index = index
                self._persist_run(
                    request=request,
                    plan=plan,
                    context=context,
                    steps=steps,
                    status=result.status,
                    output=result.data,
                    message=result.message,
                    artifact_ids=artifact_ids,
                    next_step_index=next_step_index,
                    created_at=created_at,
                    previous_events=previous_events,
                    previous_trace=previous_trace,
                    elapsed_ms=previous_elapsed,
                )
                break

            dependency_issues = self._artifact_dependency_issues(
                _dependency_artifact_ids(step.input, completed_artifacts)
            )
            dependency_issues.extend(
                _validate_file_references(
                    resolved_input,
                    self.services.get("file_registry"),
                    str(request.input.get("project_id") or "").strip(),
                )
            )
            dependency_issues.extend(
                _validate_file_references(
                    request.input,
                    self.services.get("file_registry"),
                    str(request.input.get("project_id") or "").strip(),
                )
            )
            dependency_issues = _unique_issue_dicts(dependency_issues)
            if dependency_issues:
                final_result = SkillResult(
                    status="blocked",
                    data={
                        "error_code": "STALE_RUN_DEPENDENCIES",
                        "dependency_issues": dependency_issues,
                    },
                    message=(
                        "step dependencies are stale or missing; start a new run"
                    ),
                    error_code="STALE_RUN_DEPENDENCIES",
                )
                _set_step(
                    steps,
                    index,
                    AgentStepResult(step.skill_name, final_result),
                )
                context.emit(
                    "run_failed",
                    payload={
                        "error_code": "STALE_RUN_DEPENDENCIES",
                        "skill_name": step.skill_name,
                        "dependency_issues": dependency_issues,
                    },
                )
                next_step_index = index
                break

            skill_request = SkillRequest(
                request_id=request.request_id,
                input=resolved_input,
                skill_name=step.skill_name,
                user_id=request.user_id,
                tenant_id=request.tenant_id,
                metadata=dict(request.metadata),
            )
            context.emit(
                "skill_started",
                skill_name=step.skill_name,
                payload={"input_keys": sorted(skill_request.input)},
            )
            try:
                result = await skill.execute(skill_request, context)
            except Exception as exc:
                result = SkillResult.failure(
                    message=f"skill execution failed: {exc}",
                    error_code="SKILL_EXECUTION_FAILED",
                    retryable=True,
                )
            if step.skill_name == "compliance-review":
                _normalize_compliance_result(result)
            result.trace_id = run_id
            context.state[step.skill_name] = result.data
            _set_step(steps, index, AgentStepResult(step.skill_name, result))
            artifact_id = self._persist_step_artifact(
                request=request,
                run_id=run_id,
                index=index,
                step=step,
                resolved_input=resolved_input,
                result=result,
                completed_artifacts=completed_artifacts,
            )
            _set_artifact_id(artifact_ids, index, artifact_id)
            if artifact_id:
                completed_artifacts.setdefault(step.skill_name, []).append(artifact_id)
            final_result = result
            context.emit(
                "skill_finished",
                skill_name=step.skill_name,
                payload={
                    "status": result.status,
                    "error_code": result.error_code,
                },
            )
            next_step_index = index + 1 if result.ok else index
            self._persist_run(
                request=request,
                plan=plan,
                context=context,
                steps=steps,
                status="running" if result.ok else result.status,
                output=result.data,
                message=result.message,
                artifact_ids=artifact_ids,
                next_step_index=next_step_index,
                created_at=created_at,
                previous_events=previous_events,
                previous_trace=previous_trace,
                elapsed_ms=previous_elapsed,
            )
            if not result.ok:
                break

        if final_result is None:
            final_result = SkillResult.failure(
                message="agent produced no result",
                error_code="EMPTY_AGENT_RESULT",
            )
        final_dependency_issues: list[dict[str, Any]] = []
        if _execution_status(final_result.status) == "completed":
            final_dependency_issues = self._run_dependency_issues(
                request,
                plan,
                artifact_ids,
            )
        if final_dependency_issues:
            final_result = SkillResult.blocked(
                message="run dependencies changed during execution; start a new run",
                error_code="STALE_RUN_DEPENDENCIES",
            )
            final_result.data = {
                "error_code": "STALE_RUN_DEPENDENCIES",
                "dependency_issues": final_dependency_issues,
            }
        final_status = _aggregate_run_status(final_result.status, steps)
        terminal_payload = {
            "status": final_status,
            "execution_status": _execution_status(final_status),
        }
        if final_result.error_code == "STALE_RUN_DEPENDENCIES":
            terminal_payload.update(final_result.data)
        context.emit(
            "run_finished"
            if _execution_status(final_status) == "completed"
            else "run_failed",
            payload=terminal_payload,
        )
        result = self._result(
            context,
            started,
            status=final_status,
            output=final_result.data,
            message=final_result.message,
            steps=steps,
            previous_events=previous_events,
            previous_trace=previous_trace,
            elapsed_base=previous_elapsed,
        )
        final_next_index = (
            len(plan)
            if result.execution_status == "completed"
            else next_step_index
        )
        self._persist_run(
            request=request,
            plan=plan,
            context=context,
            steps=steps,
            status=result.status,
            output=result.output,
            message=result.message,
            artifact_ids=artifact_ids,
            next_step_index=final_next_index,
            created_at=created_at,
            previous_events=previous_events,
            previous_trace=previous_trace,
            elapsed_ms=result.elapsed_ms,
        )
        return result

    def _persist_step_artifact(
        self,
        *,
        request: SkillRequest,
        run_id: str,
        index: int,
        step: PlanStep,
        resolved_input: Mapping[str, Any],
        result: SkillResult,
        completed_artifacts: Mapping[str, list[str]],
    ) -> str | None:
        file_registry = self.services.get("file_registry")
        if not hasattr(file_registry, "save_artifact"):
            return None
        project_id = str(request.input.get("project_id") or "").strip()
        if not project_id:
            return None
        dependencies = _dependency_artifact_ids(step.input, completed_artifacts)
        source_versions = _unique_strings(
            _source_file_versions(resolved_input, file_registry)
            + _source_file_versions(request.input, file_registry)
        )
        stale_issues = self._artifact_dependency_issues(dependencies)
        stale_issues.extend(
            _validate_file_references(
                resolved_input,
                file_registry,
                project_id,
            )
        )
        stale_issues.extend(
            _validate_file_references(
                request.input,
                file_registry,
                project_id,
            )
        )
        stale_issues.extend(
            _validate_file_references(
                result.data,
                file_registry,
                project_id,
            )
        )
        stale_issues = _unique_issue_dicts(stale_issues)
        artifact = file_registry.save_artifact(
            result.data,
            project_id=project_id,
            artifact_type=f"skill_output:{step.skill_name}",
            artifact_id=f"artifact_{run_id}_{index}",
            schema_version="1.0",
            source_file_versions=source_versions,
            dependencies=dependencies,
            created_by_run=run_id,
            status=(
                "stale"
                if stale_issues
                else "valid" if result.ok else "error"
            ),
        )
        return str(artifact["artifact_id"])

    def _run_dependency_issues(
        self,
        request: SkillRequest,
        plan: list[PlanStep],
        completed_artifact_ids: list[str],
    ) -> list[dict[str, Any]]:
        file_registry = self.services.get("file_registry")
        project_id = str(request.input.get("project_id") or "").strip()
        issues = _validate_file_references(
            request.input,
            file_registry,
            project_id,
        )
        for step in plan:
            issues.extend(
                _validate_file_references(
                    step.input or {},
                    file_registry,
                    project_id,
                )
            )
        issues.extend(self._artifact_dependency_issues(completed_artifact_ids))
        return _unique_issue_dicts(issues)

    def _artifact_dependency_issues(
        self,
        artifact_ids: list[str],
    ) -> list[dict[str, Any]]:
        file_registry = self.services.get("file_registry")
        visited: set[str] = set()
        visiting: set[str] = set()
        issues: list[dict[str, Any]] = []

        def visit(artifact_id: str) -> None:
            if artifact_id in visited:
                return
            if artifact_id in visiting:
                issues.append(
                    {
                        "type": "artifact_dependency_cycle",
                        "artifact_id": artifact_id,
                    }
                )
                return
            getter = getattr(self.store, "get_artifact", None)
            artifact = getter(artifact_id) if callable(getter) else None
            if artifact is None:
                issues.append(
                    {"type": "artifact_missing", "artifact_id": artifact_id}
                )
                visited.add(artifact_id)
                return
            visiting.add(artifact_id)
            if artifact.status != "valid":
                issues.append(
                    {
                        "type": "artifact_not_valid",
                        "artifact_id": artifact_id,
                        "status": artifact.status,
                    }
                )
            for source_version in artifact.source_file_versions:
                file_id, version = _parse_source_file_version(source_version)
                if file_id is None:
                    issues.append(
                        {
                            "type": "invalid_source_file_version",
                            "artifact_id": artifact_id,
                            "source_file_version": source_version,
                        }
                    )
                    continue
                issues.extend(
                    _validate_file_id_version(
                        file_id,
                        version,
                        file_registry,
                        artifact.project_id,
                        artifact_id=artifact_id,
                    )
                )
            issues.extend(
                _validate_file_references(
                    artifact.content,
                    file_registry,
                    artifact.project_id,
                )
            )
            for dependency_id in artifact.dependencies:
                visit(str(dependency_id))
            visiting.remove(artifact_id)
            visited.add(artifact_id)

        for artifact_id in _unique_strings(artifact_ids):
            if artifact_id:
                visit(artifact_id)
        return _unique_issue_dicts(issues)

    def _persist_run(
        self,
        *,
        request: SkillRequest,
        plan: list[PlanStep],
        context: SkillContext,
        steps: list[AgentStepResult],
        status: str,
        output: Mapping[str, Any],
        message: str,
        artifact_ids: list[str],
        next_step_index: int,
        created_at: str,
        previous_events: list[dict[str, Any]],
        previous_trace: list[dict[str, Any]],
        elapsed_ms: int,
    ) -> None:
        current_events = (
            context.event_sink.snapshot()
            if isinstance(context.event_sink, InMemoryEventSink)
            else []
        )
        current_trace = context.trace.snapshot()
        self.store.save_run(
            AgentRun(
                run_id=context.run_id,
                project_id=str(request.input.get("project_id") or ""),
                request=_request_to_dict(request),
                plan=[step.to_dict() for step in plan],
                status=status,
                steps=[step.to_dict() for step in steps],
                state=copy.deepcopy(context.state),
                output=dict(output),
                message=message,
                trace=previous_trace + current_trace,
                events=previous_events + current_events,
                budget=context.budget.snapshot(),
                artifact_ids=list(artifact_ids),
                next_step_index=next_step_index,
                elapsed_ms=elapsed_ms,
                created_at=created_at,
                updated_at=_timestamp(),
            )
        )

    def _result(
        self,
        context: SkillContext,
        started: float,
        *,
        status: str,
        output: dict[str, Any] | None = None,
        message: str = "",
        steps: list[AgentStepResult] | None = None,
        previous_events: list[dict[str, Any]] | None = None,
        previous_trace: list[dict[str, Any]] | None = None,
        elapsed_base: int = 0,
    ) -> AgentRunResult:
        current_events = (
            context.event_sink.snapshot()
            if isinstance(context.event_sink, InMemoryEventSink)
            else []
        )
        return AgentRunResult(
            run_id=context.run_id,
            status=status,
            output=dict(output or {}),
            message=message,
            steps=list(steps or []),
            trace=list(previous_trace or []) + context.trace.snapshot(),
            events=list(previous_events or []) + current_events,
            budget=context.budget.snapshot(),
            elapsed_ms=elapsed_base + int((time.monotonic() - started) * 1000),
        )


def _timestamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _record_created_at(record: AgentRun | None) -> str:
    return record.created_at if record and record.created_at else _timestamp()


def _budget_capacity(
    record: AgentRun | None,
    key: str,
    default: int,
) -> int:
    if record is None:
        return default
    try:
        return int(record.budget.get(key, default))
    except (TypeError, ValueError):
        return default


def _budget_value(record: AgentRun | None, key: str) -> int:
    if record is None:
        return 0
    try:
        return int(record.budget.get(key, 0))
    except (TypeError, ValueError):
        return 0


def _execution_status(status: str) -> str:
    if status in {"success", "partial"}:
        return "completed"
    if status == "running":
        return "running"
    if status == "blocked":
        return "blocked"
    return "failed"


def _aggregate_run_status(
    status: str,
    steps: list[AgentStepResult],
) -> str:
    if status != "success":
        return status
    assessment = _business_assessment(steps)
    has_compliance_review = any(
        step.skill_name == "compliance-review" for step in steps
    )
    if (
        any(step.result.status == "partial" for step in steps)
        or assessment["business_status"] in {"failed", "needs_review"}
        or (
            has_compliance_review
            and assessment["business_status"] == "not_checked"
        )
    ):
        return "partial"
    return status


def _compliance_assessment(
    data: Mapping[str, Any],
    *,
    execution_status: str | None = None,
) -> dict[str, Any]:
    summary = data.get("summary")
    summary = summary if isinstance(summary, Mapping) else {}
    raw_business_status = str(data.get("business_status") or "").strip().lower()
    explicit_checked = data.get("checked")
    summary_passed = summary.get("passed")
    blocker_count = _nonnegative_int(summary.get("blocker_count"))
    if explicit_checked is None:
        checked = (
            raw_business_status in {"passed", "failed", "needs_review"}
            or isinstance(summary_passed, bool)
            or "blocker_count" in summary
        )
    else:
        checked = explicit_checked is True

    if raw_business_status == "failed" or blocker_count > 0:
        business_status = "failed"
    elif raw_business_status == "not_checked":
        business_status = "not_checked"
    elif (
        raw_business_status == "needs_review"
        or data.get("needs_human_review") is True
        or summary_passed is False
        or execution_status == "partial"
    ):
        business_status = "needs_review"
    elif (
        raw_business_status == "not_checked"
        or (
            raw_business_status
            and raw_business_status
            not in {"passed", "failed", "needs_review", "not_checked"}
        )
        or not checked
        or summary_passed is not True
        or execution_status in {"error", "retryable_error", "blocked"}
    ):
        business_status = "not_checked"
    else:
        business_status = "passed"

    scoped_gate_passed = bool(
        checked
        and business_status == "passed"
        and summary_passed is True
        and blocker_count == 0
        and data.get("needs_human_review") is not True
        and data.get("scoped_gate_passed") is not False
    )
    return {
        "business_status": business_status,
        "checked": checked,
        "needs_human_review": business_status in {"failed", "needs_review"},
        "scoped_gate_passed": scoped_gate_passed,
        "blocker_count": blocker_count,
        "summary_passed": summary_passed is True,
    }


def _normalize_compliance_result(result: SkillResult) -> None:
    data = dict(result.data)
    assessment = _compliance_assessment(data, execution_status=result.status)
    data.update(
        {
            "business_status": assessment["business_status"],
            "checked": assessment["checked"],
            "needs_human_review": (
                data.get("needs_human_review") is True
                or assessment["business_status"] in {"failed", "needs_review"}
            ),
            "submission_allowed": False,
            "scoped_gate_passed": assessment["scoped_gate_passed"],
        }
    )
    result.data = data
    if result.ok and assessment["business_status"] != "passed":
        result.status = "partial"  # type: ignore[assignment]


def _business_assessment(steps: list[AgentStepResult]) -> dict[str, Any]:
    warnings: list[str] = []
    risks: list[str] = []
    compliance_results: list[dict[str, Any]] = []
    other_statuses: list[str] = []
    has_partial = False
    has_review_signal = False

    for step in steps:
        result = step.result
        data = result.data if isinstance(result.data, Mapping) else {}
        compliance_assessment = (
            _compliance_assessment(data, execution_status=result.status)
            if step.skill_name == "compliance-review"
            else None
        )
        unchecked_compliance = bool(
            compliance_assessment
            and compliance_assessment["business_status"] == "not_checked"
        )
        step_warnings = _collect_warning_messages(data) + [
            str(item) for item in result.warnings if str(item).strip()
        ]
        step_risks = _collect_risk_messages(data)
        warnings.extend(step_warnings)
        risks.extend(step_risks)
        if compliance_assessment is not None:
            compliance_results.append(compliance_assessment)
        else:
            other_statuses.extend(_explicit_business_statuses(data))
        if result.status == "partial" and not unchecked_compliance:
            has_partial = True
            risks.append(f"{step.skill_name} returned a partial result")
        if data.get("needs_human_review") is True and not unchecked_compliance:
            has_review_signal = True
        if not unchecked_compliance and (step_warnings or step_risks):
            has_review_signal = True

    warnings = _unique_strings(warnings)
    risks = _unique_strings(risks)
    compliance_statuses = [
        item["business_status"] for item in compliance_results
    ]
    statuses = compliance_statuses + other_statuses
    if "failed" in statuses:
        business_status = "failed"
    elif (
        "needs_review" in statuses
        or has_partial
        or has_review_signal
    ):
        business_status = "needs_review"
    elif "not_checked" in statuses:
        business_status = "not_checked"
    elif compliance_results and all(
        item["scoped_gate_passed"] for item in compliance_results
    ):
        business_status = "passed"
    else:
        business_status = "not_checked"

    scoped_gate_passed = bool(
        business_status == "passed"
        and compliance_results
        and all(item["scoped_gate_passed"] for item in compliance_results)
    )
    return {
        "business_status": business_status,
        "needs_human_review": business_status != "passed",
        "submission_allowed": False,
        "scoped_gate_passed": scoped_gate_passed,
        "warnings": warnings,
        "risks": risks,
    }


def _result_business_assessment(
    steps: list[AgentStepResult],
    output: Mapping[str, Any],
) -> dict[str, Any]:
    assessment = _business_assessment(steps)
    if output.get("error_code") == "STALE_RUN_DEPENDENCIES":
        assessment["business_status"] = "not_checked"
        assessment["needs_human_review"] = True
        assessment["submission_allowed"] = False
        assessment["scoped_gate_passed"] = False
        assessment["risks"] = _unique_strings(
            list(assessment["risks"])
            + ["run dependencies are stale or missing"]
        )
    return assessment


def _explicit_business_statuses(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        if "business_status" in value:
            raw = value.get("business_status")
            if isinstance(raw, str) and raw in {
                "failed",
                "needs_review",
                "not_checked",
            }:
                found.append(raw)
            elif not isinstance(raw, str) or raw not in {
                "passed",
                "failed",
                "needs_review",
                "not_checked",
            }:
                found.append("not_checked")
        for child in value.values():
            found.extend(_explicit_business_statuses(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_explicit_business_statuses(child))
    return found


def _collect_warning_messages(value: Any) -> list[str]:
    found: list[str] = []
    if isinstance(value, Mapping):
        for key, child in value.items():
            if str(key).lower() == "warnings":
                found.extend(_warning_values(child))
            else:
                found.extend(_collect_warning_messages(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_collect_warning_messages(child))
    return found


def _warning_values(value: Any) -> list[str]:
    if isinstance(value, str):
        return [value.strip()] if value.strip() else []
    if isinstance(value, Mapping):
        return [
            str(value.get("message") or value.get("warning") or value).strip()
        ]
    if isinstance(value, list):
        return [item for child in value for item in _warning_values(child)]
    return []


def _collect_risk_messages(value: Any) -> list[str]:
    found: list[str] = []
    severe_levels = {"blocker", "critical", "high", "high_risk", "failed"}
    if isinstance(value, Mapping):
        business_status = value.get("business_status")
        if isinstance(business_status, str) and business_status in {
            "failed",
            "needs_review",
        }:
            found.append(f"business_status={business_status}")
        if (
            value.get("needs_human_review") is True
            and business_status != "not_checked"
        ):
            found.append("step requires human review")
        if _nonnegative_int(value.get("blocker_count")):
            found.append(
                f"blocking findings: {_nonnegative_int(value.get('blocker_count'))}"
            )
        for key in ("risk_level", "risk_status", "severity"):
            level = str(value.get(key) or "").strip().lower()
            if level in severe_levels:
                detail = str(value.get("message") or value.get("reason") or level)
                found.append(detail)
        fatal_risks = value.get("fatal_risks")
        if isinstance(fatal_risks, list):
            found.extend(str(item).strip() for item in fatal_risks if str(item).strip())
        findings = value.get("findings")
        if isinstance(findings, list):
            for finding in findings:
                if not isinstance(finding, Mapping):
                    continue
                severity = str(finding.get("severity") or "").lower()
                if severity in severe_levels:
                    found.append(
                        str(
                            finding.get("message")
                            or finding.get("finding_id")
                            or severity
                        ).strip()
                    )
        for key, child in value.items():
            if key not in {"fatal_risks", "findings"}:
                found.extend(_collect_risk_messages(child))
    elif isinstance(value, list):
        for child in value:
            found.extend(_collect_risk_messages(child))
    return _unique_strings([item for item in found if item])


def _nonnegative_int(value: Any) -> int:
    try:
        return max(0, int(value))
    except (TypeError, ValueError):
        return 0


def _capability_gate_kind(
    skill_name: str,
    registry: SkillRegistry,
) -> str | None:
    normalized_name = skill_name.lower().replace("_", "-")
    if normalized_name == "compliance-review":
        return None
    if any(token in normalized_name for token in ("submit", "submission")):
        return "submission"
    if any(
        token in normalized_name
        for token in ("document-writing", "writer", "writing", "draft", "export")
    ):
        return "scoped"
    skill = registry.get(skill_name)
    capabilities = getattr(getattr(skill, "manifest", None), "capabilities", ())
    for capability in capabilities:
        value = str(capability).lower()
        if value.endswith("submission_gate"):
            continue
        if any(token in value for token in ("submit", "submission")):
            return "submission"
        if any(
            token in value
            for token in (
                "document.write",
                "technical_writing",
                "commercial_writing",
                ".draft",
                ".export",
            )
        ):
            return "scoped"
    return None


def _is_restricted_capability(skill_name: str, registry: SkillRegistry) -> bool:
    return _capability_gate_kind(skill_name, registry) is not None


def _blocked_stale_run_result(
    record: AgentRun,
    dependency_issues: list[dict[str, Any]],
) -> AgentRunResult:
    payload = {
        "error_code": "STALE_RUN_DEPENDENCIES",
        "dependency_issues": dependency_issues,
    }
    events = list(record.events) + [
        {
            "event_type": "run_failed",
            "run_id": record.run_id,
            "skill_name": None,
            "payload": payload,
            "created_at": _timestamp(),
        }
    ]
    return AgentRunResult(
        run_id=record.run_id,
        status="blocked",
        output=payload,
        message="run dependencies are stale or missing; start a new run",
        steps=_steps_from_record(record),
        trace=list(record.trace),
        events=events,
        budget={
            str(key): int(value)
            for key, value in record.budget.items()
            if _is_int(value)
        },
        elapsed_ms=record.elapsed_ms,
    )


def _validate_file_references(
    value: Any,
    file_registry: Any,
    project_id: str,
) -> list[dict[str, Any]]:
    file_ids = _explicit_file_ids(value)
    issues: list[dict[str, Any]] = []
    getter = getattr(file_registry, "get", None)
    for file_id in file_ids:
        if not project_id:
            if not callable(getter) or getter(file_id) is None:
                continue
        issues.extend(
            _validate_file_id_version(
                file_id,
                None,
                file_registry,
                project_id,
            )
        )
    issues.extend(
        _validate_structured_source_references(
            value,
            file_registry,
            project_id,
        )
    )
    return _unique_issue_dicts(issues)


def _validate_structured_source_references(
    value: Any,
    file_registry: Any,
    project_id: str,
) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            source_version = item.get("source_version")
            if isinstance(source_version, str) and ":v" in source_version:
                file_id, version = _parse_source_file_version(source_version)
                if file_id is None or version is None:
                    issues.append(
                        {
                            "type": "invalid_source_file_version",
                            "source_file_version": source_version,
                        }
                    )
                else:
                    issues.extend(
                        _validate_file_id_version(
                            file_id,
                            version,
                            file_registry,
                            project_id,
                        )
                    )
            document_id = item.get("document_id")
            getter = getattr(file_registry, "get", None)
            if isinstance(document_id, str) and callable(getter):
                try:
                    registered_document = getter(document_id)
                except Exception:
                    registered_document = None
                if registered_document is not None:
                    issues.extend(
                        _validate_file_id_version(
                            document_id,
                            None,
                            file_registry,
                            project_id,
                        )
                    )
            for child in item.values():
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return _unique_issue_dicts(issues)


def _explicit_file_ids(value: Any) -> list[str]:
    file_keys = {"file_id", "file_ids", "bidder_file_ids"}
    found: list[str] = []

    def append_ids(item: Any) -> None:
        if isinstance(item, str) and item.strip():
            found.append(item.strip())
        elif isinstance(item, (list, tuple)):
            for child in item:
                append_ids(child)

    def visit(item: Any) -> None:
        if isinstance(item, Mapping):
            for key, child in item.items():
                if str(key) in file_keys:
                    append_ids(child)
                visit(child)
        elif isinstance(item, list):
            for child in item:
                visit(child)

    visit(value)
    return _unique_strings(found)


def _parse_source_file_version(value: Any) -> tuple[str | None, int | None]:
    text = str(value or "")
    if ":v" not in text:
        return (text, None) if text else (None, None)
    file_id, raw_version = text.rsplit(":v", 1)
    try:
        version = int(raw_version)
    except ValueError:
        return None, None
    return (file_id, version) if file_id else (None, None)


def _validate_file_id_version(
    file_id: str,
    version: int | None,
    file_registry: Any,
    project_id: str,
    *,
    artifact_id: str | None = None,
) -> list[dict[str, Any]]:
    context = {"artifact_id": artifact_id} if artifact_id else {}
    if file_registry is None or not callable(getattr(file_registry, "get", None)):
        return [
            {
                "type": "file_registry_unavailable",
                "file_id": file_id,
                **context,
            }
        ]
    record = file_registry.get(file_id)
    if record is None:
        return [{"type": "file_missing", "file_id": file_id, **context}]
    issues: list[dict[str, Any]] = []
    if project_id and record.project_id != project_id:
        issues.append(
            {
                "type": "file_project_mismatch",
                "file_id": file_id,
                "expected_project_id": project_id,
                "actual_project_id": record.project_id,
                **context,
            }
        )
    if version is not None and record.version != version:
        issues.append(
            {
                "type": "source_file_version_changed",
                "file_id": file_id,
                "expected_version": version,
                "actual_version": record.version,
                **context,
            }
        )

    try:
        project_files = file_registry.list(record.project_id)
    except Exception:
        project_files = []
    by_id = {item.file_id: item for item in project_files}
    for candidate in project_files:
        cursor = candidate
        seen: set[str] = set()
        while cursor.supersedes:
            previous_id = str(cursor.supersedes)
            if previous_id == file_id:
                issues.append(
                    {
                        "type": "file_superseded",
                        "file_id": file_id,
                        "superseded_by": candidate.file_id,
                        **context,
                    }
                )
                break
            if previous_id in seen or previous_id not in by_id:
                break
            seen.add(previous_id)
            cursor = by_id[previous_id]
        if any(
            issue.get("type") == "file_superseded"
            and issue.get("superseded_by") == candidate.file_id
            for issue in issues
        ):
            break
    return _unique_issue_dicts(issues)


def _unique_issue_dicts(
    issues: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    seen: set[tuple[tuple[str, str], ...]] = set()
    for issue in issues:
        key = tuple(sorted((str(name), repr(value)) for name, value in issue.items()))
        if key not in seen:
            seen.add(key)
            result.append(issue)
    return result


def _request_to_dict(request: SkillRequest) -> dict[str, Any]:
    return {
        "request_id": request.request_id,
        "input": copy.deepcopy(request.input),
        "skill_name": request.skill_name,
        "user_id": request.user_id,
        "tenant_id": request.tenant_id,
        "metadata": copy.deepcopy(request.metadata),
    }


def _request_from_dict(payload: Mapping[str, Any]) -> SkillRequest:
    return SkillRequest(
        request_id=str(payload.get("request_id") or f"req_{uuid4().hex[:16]}"),
        input=dict(payload.get("input") or {}),
        skill_name=(
            str(payload["skill_name"])
            if payload.get("skill_name") not in (None, "")
            else None
        ),
        user_id=(
            str(payload["user_id"])
            if payload.get("user_id") not in (None, "")
            else None
        ),
        tenant_id=(
            str(payload["tenant_id"])
            if payload.get("tenant_id") not in (None, "")
            else None
        ),
        metadata=dict(payload.get("metadata") or {}),
    )


def _skill_result_from_dict(payload: Mapping[str, Any]) -> SkillResult:
    return SkillResult(
        status=str(payload.get("status") or "error"),  # type: ignore[arg-type]
        data=dict(payload.get("data") or {}),
        message=str(payload.get("message") or ""),
        error_code=(
            str(payload["error_code"])
            if payload.get("error_code") not in (None, "")
            else None
        ),
        warnings=list(payload.get("warnings") or []),
        artifacts=list(payload.get("artifacts") or []),
        usage=dict(payload.get("usage") or {}),
        trace_id=(
            str(payload["trace_id"])
            if payload.get("trace_id") not in (None, "")
            else None
        ),
    )


def _steps_from_record(record: AgentRun | None) -> list[AgentStepResult]:
    if record is None:
        return []
    result: list[AgentStepResult] = []
    for item in record.steps:
        if not isinstance(item, Mapping):
            continue
        raw_result = item.get("result")
        if not isinstance(raw_result, Mapping):
            continue
        result.append(
            AgentStepResult(
                skill_name=str(item.get("skill_name") or ""),
                result=_skill_result_from_dict(raw_result),
            )
        )
    return result


def _agent_result_from_record(record: AgentRun) -> AgentRunResult:
    steps = _steps_from_record(record)
    return AgentRunResult(
        run_id=record.run_id,
        status=_aggregate_run_status(record.status, steps),
        output=dict(record.output),
        message=record.message,
        steps=steps,
        trace=list(record.trace),
        events=list(record.events),
        budget={
            str(key): int(value)
            for key, value in record.budget.items()
            if _is_int(value)
        },
        elapsed_ms=record.elapsed_ms,
    )


def _is_int(value: Any) -> bool:
    return isinstance(value, int) and not isinstance(value, bool)


def _set_step(
    steps: list[AgentStepResult], index: int, value: AgentStepResult
) -> None:
    if index < len(steps):
        steps[index] = value
    else:
        steps.append(value)


def _set_artifact_id(artifact_ids: list[str], index: int, value: str | None) -> None:
    while len(artifact_ids) <= index:
        artifact_ids.append("")
    if value:
        artifact_ids[index] = value


def _dependency_artifact_ids(
    step_input: Mapping[str, Any] | None,
    completed_artifacts: Mapping[str, list[str]],
) -> list[str]:
    found: list[str] = []

    def visit(value: Any) -> None:
        if isinstance(value, Mapping):
            reference = value.get("$ref")
            if reference == "$state":
                found.extend(
                    artifact_ids[-1]
                    for artifact_ids in completed_artifacts.values()
                    if artifact_ids
                )
            elif isinstance(reference, str) and reference.startswith("$state/"):
                path = reference[len("$state/") :].split("/")
                if path:
                    artifact_ids = completed_artifacts.get(path[0], [])
                    if artifact_ids:
                        found.append(artifact_ids[-1])
            for item in value.values():
                visit(item)
        elif isinstance(value, list):
            for item in value:
                visit(item)

    visit(step_input or {})
    return _unique_strings(found)


def _source_file_versions(value: Any, file_registry: Any) -> list[str]:
    file_ids: list[str] = []

    def visit(item: Any, key: str = "") -> None:
        if isinstance(item, Mapping):
            for raw_key, child in item.items():
                child_key = str(raw_key)
                if child_key == "file_id" and isinstance(child, str):
                    file_ids.append(child)
                elif child_key in {"file_ids", "bidder_file_ids"}:
                    if isinstance(child, (list, tuple)):
                        file_ids.extend(str(value) for value in child)
                    elif isinstance(child, str):
                        file_ids.append(child)
                visit(child, child_key)
        elif isinstance(item, list):
            for child in item:
                visit(child, key)

    visit(value)
    tokens: list[str] = []
    for file_id in file_ids:
        try:
            token = file_registry.file_version_token(file_id)
        except Exception:
            continue
        if token not in tokens:
            tokens.append(token)
    return tokens


def _unique_strings(values: list[str]) -> list[str]:
    result: list[str] = []
    for value in values:
        if value not in result:
            result.append(value)
    return result


def resolve_step_input(
    value: Any,
    *,
    state: dict[str, Any],
    request_input: dict[str, Any],
) -> Any:
    """Resolve explicit state/request references without evaluating code."""

    if isinstance(value, Mapping):
        if "$ref" in value:
            if set(value) != {"$ref"}:
                raise StepInputReferenceError(
                    "$ref objects cannot contain sibling keys"
                )
            reference = value.get("$ref")
            if not isinstance(reference, str):
                raise StepInputReferenceError("$ref must be a string")
            return copy.deepcopy(
                _read_reference(reference, state=state, request_input=request_input)
            )
        return {
            str(key): resolve_step_input(
                item,
                state=state,
                request_input=request_input,
            )
            for key, item in value.items()
        }
    if isinstance(value, list):
        return [
            resolve_step_input(item, state=state, request_input=request_input)
            for item in value
        ]
    return value


def _read_reference(
    reference: str,
    *,
    state: dict[str, Any],
    request_input: dict[str, Any],
) -> Any:
    if reference == "$state":
        return state
    if reference == "$request":
        return request_input
    if reference.startswith("$state/"):
        root: Any = state
        path = reference[len("$state/") :].split("/")
    elif reference.startswith("$request/"):
        root = request_input
        path = reference[len("$request/") :].split("/")
    else:
        raise StepInputReferenceError("reference must start with $state/ or $request/")
    if not path or any(not segment for segment in path):
        raise StepInputReferenceError(f"reference path is empty: {reference}")
    for segment in path:
        if isinstance(root, Mapping) and segment in root:
            root = root[segment]
        elif isinstance(root, list) and segment.isdigit():
            index = int(segment)
            if index < len(root):
                root = root[index]
            else:
                raise StepInputReferenceError(
                    f"reference path is unavailable: {reference}"
                )
        else:
            raise StepInputReferenceError(f"reference path is unavailable: {reference}")
    return root
