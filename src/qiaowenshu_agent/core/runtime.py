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

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "status": self.status,
            "output": self.output,
            "message": self.message,
            "steps": [step.to_dict() for step in self.steps],
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
        if record.status in {"success", "partial"}:
            return _agent_result_from_record(record)
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
        return await self._execute(
            request,
            run_id=record.run_id,
            resume_record=record,
            plan=plan,
        )

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
        context.emit(
            "run_finished" if final_result.ok else "run_failed",
            payload={"status": final_result.status},
        )
        result = self._result(
            context,
            started,
            status=final_result.status,
            output=final_result.data,
            message=final_result.message,
            steps=steps,
            previous_events=previous_events,
            previous_trace=previous_trace,
            elapsed_base=previous_elapsed,
        )
        final_next_index = len(plan) if final_result.ok else next_step_index
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
        source_versions = _source_file_versions(resolved_input, file_registry)
        artifact = file_registry.save_artifact(
            result.data,
            project_id=project_id,
            artifact_type=f"skill_output:{step.skill_name}",
            artifact_id=f"artifact_{run_id}_{index}",
            schema_version="1.0",
            source_file_versions=source_versions,
            dependencies=dependencies,
            created_by_run=run_id,
            status="valid" if result.ok else "error",
        )
        return str(artifact["artifact_id"])

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
    return AgentRunResult(
        run_id=record.run_id,
        status=record.status,
        output=dict(record.output),
        message=record.message,
        steps=_steps_from_record(record),
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
            if isinstance(reference, str) and reference.startswith("$state/"):
                path = reference[len("$state/") :].split("/")
                if path:
                    found.extend(completed_artifacts.get(path[0], []))
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
