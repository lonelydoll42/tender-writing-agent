"""Assemble the stable tender analysis protocol from upstream Skills."""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import (
    Skill,
    SkillManifest,
    SkillRequest,
    SkillResult,
)
from qiaowenshu_agent.domain.analysis_protocol import (
    ANALYSIS_PROTOCOL_VERSION,
    build_machine_json,
    render_human_report,
)


MANIFEST = SkillManifest(
    name="analysis-report",
    version="0.1.0",
    description=(
        "Combine tender feasibility, evidence, scoring and compliance results "
        "into a stable machine JSON and a traceable human report."
    ),
    input_schema={
        "type": "object",
        "required": ["project_id"],
        "properties": {
            "project_id": {"type": "string"},
            "project": {"type": "object"},
            "tender_profile": {"type": "object"},
            "feasibility": {"type": "object"},
            "scoring": {"type": "object"},
            "ledger": {"type": "object"},
            "compliance": {"type": "object"},
            "evidence_gaps": {"type": "array"},
            "fatal_risks": {"type": "array"},
            "writing_status": {"type": "string"},
        },
    },
    output_schema={
        "type": "object",
        "required": ["protocol_version", "machine_json", "human_report"],
    },
    capabilities=("tender.analysis_report", "tender.machine_json"),
    required_permissions=("document.read",),
)


class AnalysisReportSkill(Skill):
    """Build the protocol without making unsupported business assertions."""

    manifest = MANIFEST

    async def execute(
        self,
        request: SkillRequest,
        _context: SkillContext,
    ) -> SkillResult:
        if not isinstance(request.input, Mapping):
            return SkillResult.failure(
                message="analysis report input must be an object",
                error_code="INVALID_ANALYSIS_REPORT_INPUT",
            )
        data = {str(key): value for key, value in request.input.items()}
        project_id = str(data.get("project_id") or "").strip()
        if not project_id:
            return SkillResult.failure(
                message="project_id is required",
                error_code="INVALID_ANALYSIS_REPORT_INPUT",
            )
        try:
            machine_json = build_machine_json(
                data,
                project=_object(data.get("project") or data.get("tender_profile")),
                feasibility=_object(data.get("feasibility")),
                scoring=_object(data.get("scoring")),
                evidence_gaps=_sequence(data.get("evidence_gaps")),
                fatal_risks=_sequence(data.get("fatal_risks")),
            )
            human_report = render_human_report(machine_json)
        except (TypeError, ValueError) as exc:
            return SkillResult.failure(
                message=str(exc),
                error_code="INVALID_ANALYSIS_REPORT_INPUT",
            )
        compliance = _object(data.get("compliance")) or {}
        compliance_summary = _object(compliance.get("summary")) or {}
        compliance_follow_up = bool(
            compliance.get("needs_human_review")
            or not compliance_summary.get("passed", True)
        )
        output = {
            "protocol_version": ANALYSIS_PROTOCOL_VERSION,
            "machine_json": machine_json,
            "human_report": human_report,
            "summary": compliance_summary,
        }
        if (
            machine_json["bid_decision"] != "bid"
            or machine_json["fatal_risks"]
            or compliance_follow_up
        ):
            return SkillResult.partial(
                output,
                message="analysis report completed with follow-up items",
                warnings=[
                    "机器报告已生成，但资格结论或风险仍需后续处理"
                ],
            )
        return SkillResult.success(output, message="analysis report completed")


def _object(value: Any) -> dict[str, Any] | None:
    if value is None:
        return None
    if hasattr(value, "data") and isinstance(value.data, Mapping):
        value = value.data
    elif hasattr(value, "to_dict"):
        value = value.to_dict()
    if not isinstance(value, Mapping):
        return None
    return {str(key): item for key, item in value.items()}


def _sequence(value: Any) -> list[Any] | None:
    if value is None:
        return None
    if isinstance(value, Mapping):
        return [value]
    if isinstance(value, (list, tuple, set)):
        return list(value)
    return None
