"""Final deterministic compliance gate for a reviewable tender draft."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import (
    Skill,
    SkillManifest,
    SkillRequest,
    SkillResult,
)


MANIFEST = SkillManifest(
    name="compliance-review",
    version="0.1.0",
    description="Run a deterministic submission-readiness compliance gate.",
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "ledger": {"type": "object"},
            "requirements": {"type": "array"},
            "consistency_result": {"type": "object"},
            "quotation_result": {"type": "object"},
            "required_attachments": {"type": "array"},
            "present_attachments": {"type": "array"},
            "signatures": {"type": "object"},
            "draft": {"type": "object"},
        },
    },
    output_schema={
        "type": "object",
        "required": ["findings", "summary", "needs_human_review"],
    },
    capabilities=("tender.compliance_review", "tender.submission_gate"),
    required_permissions=("document.read",),
)


class ComplianceReviewSkill(Skill):
    manifest = MANIFEST

    async def execute(
        self,
        request: SkillRequest,
        _context: SkillContext,
    ) -> SkillResult:
        try:
            data = _review(request.input)
        except (TypeError, ValueError) as exc:
            return SkillResult.failure(
                message=str(exc),
                error_code="INVALID_COMPLIANCE_REVIEW_INPUT",
            )
        counts = data["summary"]["severity_counts"]
        warnings = []
        if counts.get("blocker", 0):
            warnings.append(f"存在 {counts['blocker']} 个阻断项")
        if data["needs_human_review"]:
            warnings.append("存在需要人工确认的合规风险")
        if counts.get("blocker", 0) or data["needs_human_review"]:
            return SkillResult.partial(
                data,
                message="compliance review requires follow-up",
                warnings=warnings,
            )
        return SkillResult.success(data, message="compliance review passed")


def _review(data: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise TypeError("compliance review input must be an object")
    findings: list[dict[str, Any]] = []
    ledger = data.get("ledger") or {}
    entries = ledger.get("entries") if isinstance(ledger, Mapping) else None
    if entries is None:
        entries = data.get("ledger_entries") or []
    if not isinstance(entries, (list, tuple)):
        raise ValueError("ledger entries must be a list")
    for entry in entries:
        if not isinstance(entry, Mapping):
            continue
        identifier = str(entry.get("requirement_id") or "unknown")
        status = str(entry.get("status") or "unreviewed")
        mandatory = bool(entry.get("mandatory"))
        if mandatory and status in {"missing", "invalid", "fail"}:
            findings.append(
                _finding(
                    f"LEDGER-{identifier}",
                    "blocker",
                    "mandatory_requirement",
                    f"硬性要求 {identifier} 尚未满足，状态为 {status}",
                    affected=[identifier],
                )
            )
        elif mandatory and status in {
            "unknown",
            "partial",
            "conflict",
            "human_review",
            "unreviewed",
        }:
            findings.append(
                _finding(
                    f"LEDGER-{identifier}",
                    "high_risk",
                    "mandatory_requirement",
                    f"硬性要求 {identifier} 的证据状态为 {status}，不能直接放行",
                    affected=[identifier],
                )
            )
        elif status in {
            "missing",
            "invalid",
            "unknown",
            "partial",
            "conflict",
            "human_review",
            "unreviewed",
        }:
            findings.append(
                _finding(
                    f"LEDGER-{identifier}",
                    "warning",
                    "requirement_coverage",
                    f"要求 {identifier} 尚未形成完整响应，状态为 {status}",
                    affected=[identifier],
                )
            )

    consistency = data.get("consistency_result") or data.get("consistency") or {}
    if isinstance(consistency, Mapping):
        for conflict in consistency.get("conflicts") or []:
            if not isinstance(conflict, Mapping):
                continue
            severity = "blocker" if conflict.get("severity") == "high" else "high_risk"
            findings.append(
                _finding(
                    str(conflict.get("conflict_id") or "CONSISTENCY-UNKNOWN"),
                    severity,
                    "cross_document_conflict",
                    f"{conflict.get('label') or conflict.get('field')} 存在跨文档冲突",
                    affected=[str(conflict.get("field") or "")],
                    references=conflict.get("occurrences") or [],
                )
            )

    quotation = data.get("quotation_result") or data.get("quotation") or {}
    if isinstance(quotation, Mapping):
        for check in quotation.get("checks") or []:
            if not isinstance(check, Mapping):
                continue
            status = str(check.get("status") or "")
            if status == "failed":
                findings.append(
                    _finding(
                        str(check.get("check_id") or "QUOTATION-UNKNOWN"),
                        "blocker",
                        "quotation",
                        str(check.get("reason") or "报价规则校验失败"),
                    )
                )
            elif status == "unknown":
                findings.append(
                    _finding(
                        str(check.get("check_id") or "QUOTATION-UNKNOWN"),
                        "high_risk",
                        "quotation",
                        str(check.get("reason") or "报价规则缺少输入"),
                    )
                )

    required = _string_set(data.get("required_attachments"))
    present = _string_set(data.get("present_attachments"))
    for attachment in sorted(required - present):
        findings.append(
            _finding(
                f"ATTACHMENT-{len(findings) + 1:03d}",
                "blocker",
                "required_attachment",
                f"缺少必需附件：{attachment}",
            )
        )

    signatures = data.get("signatures") or {}
    if not isinstance(signatures, Mapping):
        raise ValueError("signatures must be an object")
    for name, valid in signatures.items():
        if valid is False or str(valid).lower() in {
            "false",
            "missing",
            "invalid",
            "未完成",
        }:
            findings.append(
                _finding(
                    f"SIGNATURE-{len(findings) + 1:03d}",
                    "blocker",
                    "signature",
                    f"签章要求未完成：{name}",
                )
            )

    draft = data.get("draft") or {}
    draft_text = (
        str(draft.get("markdown") or draft.get("text") or "")
        if isinstance(draft, Mapping)
        else str(draft)
    )
    for marker in ("[待补材料]", "[待确认]", "[待核验]"):
        if marker in draft_text:
            findings.append(
                _finding(
                    f"DRAFT-{len(findings) + 1:03d}",
                    "high_risk",
                    "draft_placeholder",
                    f"草案仍包含占位标记：{marker}",
                )
            )

    counts = Counter(item["severity"] for item in findings)
    if not findings:
        findings.append(
            _finding(
                "COMPLIANCE-PASSED",
                "passed",
                "gate",
                "当前输入范围内未发现阻断项或待确认项",
            )
        )
        counts["passed"] = 1
    else:
        counts["passed"] = 0
    needs_review = bool(
        counts.get("blocker") or counts.get("high_risk") or counts.get("warning")
    )
    return {
        "project_id": str(data.get("project_id") or "").strip(),
        "findings": findings,
        "summary": {
            "finding_count": len(findings),
            "severity_counts": dict(counts),
            "blocker_count": counts.get("blocker", 0),
            "high_risk_count": counts.get("high_risk", 0),
            "warning_count": counts.get("warning", 0),
            "passed": not needs_review,
        },
        "needs_human_review": needs_review,
    }


def _finding(
    finding_id: str,
    severity: str,
    finding_type: str,
    message: str,
    *,
    affected: list[str] | None = None,
    references: list[Any] | None = None,
) -> dict[str, Any]:
    return {
        "finding_id": finding_id,
        "severity": severity,
        "type": finding_type,
        "message": message,
        "affected_ids": [item for item in (affected or []) if item],
        "source_references": list(references or []),
    }


def _string_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {item.strip() for item in value.split(",") if item.strip()}
    if not isinstance(value, (list, tuple, set)):
        raise ValueError("attachment collections must be lists")
    return {str(item).strip() for item in value if str(item).strip()}
