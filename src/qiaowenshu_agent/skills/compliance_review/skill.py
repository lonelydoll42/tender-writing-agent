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
    description=(
        "Review supplied tender compliance evidence and report a scoped business "
        "status without certifying overall final-submission readiness."
    ),
    input_schema={
        "type": "object",
        "properties": {
            "project_id": {"type": "string"},
            "ledger": {
                "type": "object",
                "properties": {
                    "entries": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "requirement_id": {"type": "string"},
                                "id": {"type": "string"},
                                "status": {"type": "string"},
                                "mandatory": {"type": "boolean"},
                                "not_applicable_reason": {"type": "string"},
                            },
                        },
                    }
                },
            },
            "ledger_entries": {"type": "array"},
            "requirements": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "requirement_id": {"type": "string"},
                        "id": {"type": "string"},
                        "mandatory": {"type": "boolean"},
                        "required": {"type": "boolean"},
                    },
                },
            },
            "consistency_result": {"type": "object"},
            "quotation_result": {"type": "object"},
            "required_attachments": {"type": "array"},
            "present_attachments": {"type": "array"},
            "signatures": {"type": "object"},
            "draft": {"type": ["object", "string"]},
        },
    },
    output_schema={
        "type": "object",
        "required": [
            "findings",
            "summary",
            "needs_human_review",
            "business_status",
            "checked",
            "submission_allowed",
            "scoped_gate_passed",
            "check_coverage",
        ],
        "properties": {
            "business_status": {
                "type": "string",
                "enum": ["passed", "failed", "needs_review", "not_checked"],
            },
            "checked": {"type": "boolean"},
            "submission_allowed": {"type": "boolean", "const": False},
            "scoped_gate_passed": {"type": "boolean"},
            "needs_human_review": {"type": "boolean"},
            "findings": {"type": "array"},
            "summary": {
                "type": "object",
                "required": ["passed", "severity_counts"],
                "properties": {
                    "passed": {"type": "boolean"},
                    "severity_counts": {"type": "object"},
                },
            },
            "check_coverage": {
                "type": "object",
                "required": [
                    "requested_checks",
                    "completed_checks",
                    "pending_checks",
                    "requirement_coverage_complete",
                    "scope_limited",
                    "final_submission_readiness_certified",
                ],
                "properties": {
                    "requested_checks": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "completed_checks": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "pending_checks": {
                        "type": "array",
                        "items": {"type": "string"},
                    },
                    "requirement_coverage_complete": {
                        "type": ["boolean", "null"]
                    },
                    "scope_limited": {"type": "boolean", "const": True},
                    "final_submission_readiness_certified": {
                        "type": "boolean",
                        "const": False,
                    },
                },
            },
        },
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
        if data["business_status"] == "not_checked":
            warnings.append("未提供可实际审查的范围，不能据此放行")
        if data["business_status"] != "passed":
            return SkillResult.partial(
                data,
                message=f"compliance review status: {data['business_status']}",
                warnings=warnings,
            )
        return SkillResult.success(
            data,
            message="compliance review passed within the supplied scope",
        )


def _review(data: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise TypeError("compliance review input must be an object")
    findings: list[dict[str, Any]] = []
    requested_checks: list[str] = []
    completed_checks: list[str] = []

    def issue(
        finding_id: str,
        message: str,
        *,
        affected: list[str] | None = None,
    ) -> None:
        findings.append(
            _finding(
                finding_id,
                "high_risk",
                "input_integrity",
                message,
                affected=affected,
            )
        )

    def request_check(name: str) -> None:
        if name not in requested_checks:
            requested_checks.append(name)

    def complete_check(name: str) -> None:
        if name not in completed_checks:
            completed_checks.append(name)

    # Keep the supplied requirement catalog separate from the ledger: it is
    # the only way to detect requirements that were omitted from review.
    requirements_by_id: dict[str, dict[str, Any]] = {}
    requirements_supplied = (
        "requirements" in data and data.get("requirements") is not None
    )
    raw_requirements = data.get("requirements")
    if "requirements" in data:
        request_check("requirement_coverage")
    if raw_requirements is not None:
        if not isinstance(raw_requirements, (list, tuple)):
            issue(
                "INPUT-REQUIREMENTS-SHAPE",
                "requirements 必须是对象列表，无法可靠核对要求覆盖范围",
            )
        else:
            for index, requirement in enumerate(raw_requirements, start=1):
                if not isinstance(requirement, Mapping):
                    issue(
                        f"INPUT-REQUIREMENT-{index:03d}",
                        f"第 {index} 条 requirement 不是对象",
                    )
                    continue
                identifier = _identifier(requirement)
                if not identifier:
                    issue(
                        f"INPUT-REQUIREMENT-{index:03d}-ID",
                        f"第 {index} 条 requirement 缺少 requirement_id",
                    )
                    continue
                if identifier in requirements_by_id:
                    issue(
                        f"INPUT-REQUIREMENT-DUPLICATE-{index:03d}",
                        f"requirement ID {identifier} 重复，无法确定唯一审查记录",
                        affected=[identifier],
                    )
                    continue
                mandatory = _mandatory_value(
                    requirement,
                    finding_id=f"INPUT-REQUIREMENT-MANDATORY-{index:03d}",
                    source="requirement",
                    identifier=identifier,
                    issue=issue,
                )
                requirements_by_id[identifier] = {
                    "mandatory": mandatory,
                    "raw": requirement,
                }

    ledger_rows: list[tuple[int, Mapping[str, Any]]] = []
    ledger_record_ids: set[str] = set()
    unknown_ledger_ids: set[str] = set()
    unresolved_ids: set[str] = set()
    unreviewed_ids: set[str] = set()
    raw_entries: Any = None
    ledger_value = data.get("ledger")
    ledger_declared = "ledger" in data
    legacy_entries_declared = "ledger_entries" in data
    if ledger_declared:
        request_check("requirement_ledger")
    if ledger_declared and ledger_value is not None:
        if not isinstance(ledger_value, Mapping):
            issue(
                "INPUT-LEDGER-SHAPE",
                "ledger 必须是对象，无法读取其中的审查记录",
            )
        elif "entries" in ledger_value:
            raw_entries = ledger_value.get("entries")
        elif legacy_entries_declared:
            raw_entries = data.get("ledger_entries")
    elif legacy_entries_declared:
        request_check("requirement_ledger")
        raw_entries = data.get("ledger_entries")

    entries_declared = (
        isinstance(ledger_value, Mapping) and "entries" in ledger_value
    ) or legacy_entries_declared
    if entries_declared and raw_entries is None:
        issue("INPUT-LEDGER-ENTRIES", "ledger.entries 必须是对象列表")
    elif raw_entries is not None:
        if not isinstance(raw_entries, (list, tuple)):
            issue("INPUT-LEDGER-ENTRIES", "ledger.entries 必须是对象列表")
        else:
            for index, entry in enumerate(raw_entries, start=1):
                if not isinstance(entry, Mapping):
                    issue(
                        f"INPUT-LEDGER-ENTRY-{index:03d}",
                        f"第 {index} 条 ledger entry 不是对象",
                    )
                    continue
                ledger_rows.append((index, entry))

    valid_statuses = {
        "matched",
        "pass",
        "missing",
        "invalid",
        "fail",
        "unknown",
        "partial",
        "conflict",
        "human_review",
        "unreviewed",
        "not_applicable",
    }
    unresolved_statuses = {
        "unknown",
        "partial",
        "conflict",
        "human_review",
        "unreviewed",
    }
    seen_entry_ids: set[str] = set()
    for index, entry in ledger_rows:
        identifier = _identifier(entry)
        if not identifier:
            issue(
                f"INPUT-LEDGER-ENTRY-ID-{index:03d}",
                f"第 {index} 条 ledger entry 缺少 requirement_id",
            )
            continue
        if identifier in seen_entry_ids:
            issue(
                f"INPUT-LEDGER-DUPLICATE-{index:03d}",
                f"ledger 中 requirement ID {identifier} 重复",
                affected=[identifier],
            )
        seen_entry_ids.add(identifier)
        ledger_record_ids.add(identifier)
        if requirements_supplied and identifier not in requirements_by_id:
            unknown_ledger_ids.add(identifier)
            issue(
                f"INPUT-LEDGER-UNKNOWN-ID-{index:03d}",
                f"ledger 引用了 requirements 中不存在的 ID：{identifier}",
                affected=[identifier],
            )

        requirement = requirements_by_id.get(identifier)
        declared_mandatory = _mandatory_value(
            entry,
            finding_id=f"INPUT-LEDGER-MANDATORY-{index:03d}",
            source="ledger entry",
            identifier=identifier,
            issue=issue,
        )
        catalog_mandatory = requirement["mandatory"] if requirement else None
        if (
            declared_mandatory is not None
            and catalog_mandatory is not None
            and declared_mandatory != catalog_mandatory
        ):
            issue(
                f"INPUT-LEDGER-MANDATORY-MISMATCH-{index:03d}",
                f"ledger 与 requirement 对 {identifier} 的 mandatory 标记不一致",
                affected=[identifier],
            )
        mandatory = (
            catalog_mandatory
            if catalog_mandatory is not None
            else declared_mandatory
        )

        raw_status = entry.get("status")
        status = (
            str(raw_status).strip().lower()
            if isinstance(raw_status, str) and raw_status.strip()
            else "unreviewed"
        )
        if status not in valid_statuses:
            issue(
                f"INPUT-LEDGER-STATUS-{index:03d}",
                f"要求 {identifier} 的 ledger status 无法识别：{raw_status!r}",
                affected=[identifier],
            )
            status = "unknown"

        if status in {"missing", "invalid", "fail"}:
            severity = "blocker" if mandatory is True else (
                "high_risk" if mandatory is None else "warning"
            )
            finding_type = (
                "mandatory_requirement"
                if mandatory is True
                else "requirement_coverage"
            )
            findings.append(
                _finding(
                    f"LEDGER-{identifier}",
                    severity,
                    finding_type,
                    f"要求 {identifier} 尚未满足，状态为 {status}",
                    affected=[identifier],
                )
            )
        elif status == "not_applicable":
            reason = entry.get("not_applicable_reason")
            has_reviewable_reason = (
                isinstance(reason, str)
                and bool(reason.strip())
                and reason.strip().lower()
                not in {
                    "n/a",
                    "na",
                    "not applicable",
                    "not_applicable",
                    "不适用",
                }
            )
            if not has_reviewable_reason:
                severity = "warning" if mandatory is False else "high_risk"
                findings.append(
                    _finding(
                        f"LEDGER-{identifier}-NOT-APPLICABLE",
                        severity,
                        "requirement_coverage",
                        (
                            f"要求 {identifier} 标记为 not_applicable，"
                            "但缺少可审查的不适用理由"
                        ),
                        affected=[identifier],
                    )
                )
                unresolved_ids.add(identifier)
        elif status in unresolved_statuses:
            severity = "high_risk" if mandatory is not False else "warning"
            finding_type = (
                "mandatory_requirement"
                if mandatory is not False
                else "requirement_coverage"
            )
            findings.append(
                _finding(
                    f"LEDGER-{identifier}",
                    severity,
                    finding_type,
                    f"要求 {identifier} 的证据状态为 {status}，不能直接放行",
                    affected=[identifier],
                )
            )
            unresolved_ids.add(identifier)

    if requirements_by_id:
        complete_check("requirement_coverage")
        for identifier, requirement in requirements_by_id.items():
            if identifier in ledger_record_ids:
                continue
            unreviewed_ids.add(identifier)
            mandatory = requirement["mandatory"]
            severity = "blocker" if mandatory is True else (
                "high_risk" if mandatory is None else "warning"
            )
            findings.append(
                _finding(
                    f"REQUIREMENT-UNREVIEWED-{identifier}",
                    severity,
                    "requirement_coverage",
                    f"要求 {identifier} 没有对应的 ledger 审查记录",
                    affected=[identifier],
                )
            )

    if ledger_record_ids:
        complete_check("requirement_ledger")

    ledger_summary = (
        ledger_value.get("summary")
        if isinstance(ledger_value, Mapping)
        else None
    )
    if isinstance(ledger_summary, Mapping) and "mandatory_gap_ids" in ledger_summary:
        gap_ids = ledger_summary.get("mandatory_gap_ids")
        if not isinstance(gap_ids, (list, tuple)):
            issue(
                "INPUT-LEDGER-GAP-REFERENCES",
                "ledger.summary.mandatory_gap_ids 必须是 ID 列表",
            )
        else:
            for index, raw_identifier in enumerate(gap_ids, start=1):
                identifier = str(raw_identifier or "").strip()
                if not identifier or identifier not in ledger_record_ids:
                    reference = identifier or f"index-{index}"
                    unknown_ledger_ids.add(reference)
                    issue(
                        f"INPUT-LEDGER-UNKNOWN-GAP-{index:03d}",
                        f"mandatory_gap_ids 引用了不存在的 ledger entry：{reference}",
                        affected=[reference],
                    )

    consistency_key = (
        "consistency_result"
        if "consistency_result" in data
        else "consistency"
        if "consistency" in data
        else None
    )
    if consistency_key is not None:
        request_check("consistency")
    consistency = data.get(consistency_key) if consistency_key else None
    if consistency is not None:
        if not isinstance(consistency, Mapping):
            issue("INPUT-CONSISTENCY-SHAPE", "consistency result 必须是对象")
        elif "conflicts" in consistency:
            conflicts = consistency.get("conflicts")
            if not isinstance(conflicts, (list, tuple)):
                issue(
                    "INPUT-CONSISTENCY-CONFLICTS",
                    "consistency.conflicts 必须是对象列表",
                )
            else:
                checked_documents = 0
                summary = consistency.get("summary")
                if isinstance(summary, Mapping):
                    checked_documents = _nonnegative_int(
                        summary.get("documents_checked")
                    )
                if conflicts or checked_documents:
                    complete_check("consistency")
                for index, conflict in enumerate(conflicts, start=1):
                    if not isinstance(conflict, Mapping):
                        issue(
                            f"INPUT-CONSISTENCY-CONFLICT-{index:03d}",
                            f"第 {index} 条 consistency conflict 不是对象",
                        )
                        continue
                    severity = (
                        "blocker"
                        if conflict.get("severity") == "high"
                        else "high_risk"
                    )
                    conflict_label = (
                        conflict.get("label") or conflict.get("field") or "字段"
                    )
                    findings.append(
                        _finding(
                            str(
                                conflict.get("conflict_id")
                                or f"CONSISTENCY-{index:03d}"
                            ),
                            severity,
                            "cross_document_conflict",
                            f"{conflict_label} 存在跨文档冲突",
                            affected=[str(conflict.get("field") or "")],
                            references=conflict.get("occurrences") or [],
                        )
                    )
        elif consistency:
            issue(
                "INPUT-CONSISTENCY-CONFLICTS",
                "consistency result 缺少 conflicts，无法确认是否完成一致性检查",
            )

    quotation_key = (
        "quotation_result"
        if "quotation_result" in data
        else "quotation"
        if "quotation" in data
        else None
    )
    if quotation_key is not None:
        request_check("quotation")
    quotation = data.get(quotation_key) if quotation_key else None
    if quotation is not None:
        if not isinstance(quotation, Mapping):
            issue("INPUT-QUOTATION-SHAPE", "quotation result 必须是对象")
        elif "checks" in quotation:
            checks = quotation.get("checks")
            if not isinstance(checks, (list, tuple)):
                issue("INPUT-QUOTATION-CHECKS", "quotation.checks 必须是对象列表")
            else:
                quotation_summary = quotation.get("summary")
                declared_count = (
                    _nonnegative_int(quotation_summary.get("check_count"))
                    if isinstance(quotation_summary, Mapping)
                    else None
                )
                if checks:
                    complete_check("quotation")
                elif declared_count:
                    issue(
                        "INPUT-QUOTATION-CHECK-COVERAGE",
                        "quotation summary 声明有检查项，但 checks 为空",
                    )
                for index, check in enumerate(checks, start=1):
                    if not isinstance(check, Mapping):
                        issue(
                            f"INPUT-QUOTATION-CHECK-{index:03d}",
                            f"第 {index} 条 quotation check 不是对象",
                        )
                        continue
                    raw_status = check.get("status")
                    status = (
                        str(raw_status).strip().lower()
                        if isinstance(raw_status, str)
                        else ""
                    )
                    check_id = str(
                        check.get("check_id") or f"QUOTATION-{index:03d}"
                    )
                    if status in {"failed", "fail"}:
                        findings.append(
                            _finding(
                                check_id,
                                "blocker",
                                "quotation",
                                str(check.get("reason") or "报价规则校验失败"),
                            )
                        )
                    elif status == "unknown":
                        findings.append(
                            _finding(
                                check_id,
                                "high_risk",
                                "quotation",
                                str(check.get("reason") or "报价规则缺少输入"),
                            )
                        )
                    elif status not in {"passed", "pass"}:
                        issue(
                            f"INPUT-QUOTATION-STATUS-{index:03d}",
                            f"报价检查 {check_id} 的 status 无法识别：{raw_status!r}",
                            affected=[check_id],
                        )
                if declared_count is not None and declared_count != len(checks):
                    issue(
                        "INPUT-QUOTATION-CHECK-COUNT",
                        "quotation summary.check_count 与 checks 实际数量不一致",
                    )
        elif quotation:
            issue(
                "INPUT-QUOTATION-CHECKS",
                "quotation result 缺少 checks，无法确认是否完成报价检查",
            )

    attachment_keys_supplied = (
        "required_attachments" in data or "present_attachments" in data
    )
    if attachment_keys_supplied:
        request_check("attachments")
    required: set[str] = set()
    present: set[str] = set()
    attachment_inputs_valid = True
    for key, target in (
        ("required_attachments", required),
        ("present_attachments", present),
    ):
        if key not in data:
            continue
        try:
            target.update(_string_set(data.get(key)))
        except ValueError:
            attachment_inputs_valid = False
            issue(
                f"INPUT-{key.upper().replace('-', '_')}",
                f"{key} 必须是字符串或字符串列表",
            )
    if required:
        complete_check("attachments")
    if attachment_inputs_valid:
        for attachment in sorted(required - present):
            findings.append(
                _finding(
                    f"ATTACHMENT-{len(findings) + 1:03d}",
                    "blocker",
                    "required_attachment",
                    f"缺少必需附件：{attachment}",
                )
            )

    if "signatures" in data:
        request_check("signatures")
    signatures = data.get("signatures")
    if signatures is not None:
        if not isinstance(signatures, Mapping):
            issue("INPUT-SIGNATURES-SHAPE", "signatures 必须是对象")
        else:
            if signatures:
                complete_check("signatures")
            for name, valid in signatures.items():
                normalized = (
                    valid.strip().lower() if isinstance(valid, str) else ""
                )
                if valid is True or normalized in {"pass", "passed"}:
                    continue
                if valid is False or normalized in {
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
                else:
                    findings.append(
                        _finding(
                            f"SIGNATURE-{len(findings) + 1:03d}",
                            "high_risk",
                            "signature_status",
                            f"签章要求 {name} 的状态不明确，需人工核验",
                        )
                    )

    if "draft" in data:
        request_check("draft")
    draft = data.get("draft")
    draft_text = (
        str(draft.get("markdown") or draft.get("text") or "")
        if isinstance(draft, Mapping)
        else str(draft or "")
    )
    if draft_text.strip():
        complete_check("draft")
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

    pending_checks = [
        check for check in requested_checks if check not in completed_checks
    ]
    if completed_checks:
        for check in pending_checks:
            finding_id = (
                "PENDING-CHECK-"
                + "".join(
                    character if character.isalnum() else "-"
                    for character in check.upper()
                )
            )
            findings.append(
                _finding(
                    finding_id,
                    "warning",
                    "check_coverage",
                    f"已声明的 {check} 检查没有可审查内容或未能完成",
                )
            )

    counts = Counter(item["severity"] for item in findings)
    checked = bool(completed_checks)
    if not findings and checked:
        findings.append(
            _finding(
                "COMPLIANCE-PASSED",
                "passed",
                "gate",
                "当前明确输入范围内未发现阻断项或待确认项",
            )
        )
        counts["passed"] = 1
    else:
        counts["passed"] = 0
    blocker_count = counts.get("blocker", 0)
    needs_review = bool(
        blocker_count or counts.get("high_risk", 0) or counts.get("warning", 0)
    )
    if blocker_count:
        business_status = "failed"
    elif needs_review:
        business_status = "needs_review"
    elif checked:
        business_status = "passed"
    else:
        business_status = "not_checked"

    missing_record_ids = sorted(
        identifier
        for identifier in requirements_by_id
        if identifier not in ledger_record_ids
    )
    requirement_coverage_complete = (
        bool(requirements_by_id) and not missing_record_ids
        if requirements_supplied
        else None
    )
    return {
        "project_id": str(data.get("project_id") or "").strip(),
        "findings": findings,
        "business_status": business_status,
        "checked": checked,
        "submission_allowed": False,
        "scoped_gate_passed": business_status == "passed",
        "check_coverage": {
            "requested_checks": requested_checks,
            "completed_checks": completed_checks,
            "pending_checks": pending_checks,
            "requirement_count": (
                len(requirements_by_id) if requirements_supplied else None
            ),
            "ledger_entry_count": len(ledger_rows),
            "recorded_requirement_ids": sorted(ledger_record_ids),
            "missing_record_requirement_ids": missing_record_ids,
            "unreviewed_requirement_ids": sorted(unreviewed_ids),
            "unresolved_requirement_ids": sorted(unresolved_ids),
            "unknown_ledger_requirement_ids": sorted(unknown_ledger_ids),
            "requirement_coverage_complete": requirement_coverage_complete,
            "scope_limited": True,
            "final_submission_readiness_certified": False,
            "scope_note": (
                "business_status 仅反映本次明确输入并完成的审查范围；"
                "不代表未提供的材料、要求或最终投标文件均已就绪。"
            ),
        },
        "summary": {
            "finding_count": len(findings),
            "severity_counts": dict(counts),
            "blocker_count": blocker_count,
            "high_risk_count": counts.get("high_risk", 0),
            "warning_count": counts.get("warning", 0),
            "passed": business_status == "passed",
        },
        "needs_human_review": business_status != "passed",
    }


def _identifier(item: Mapping[str, Any]) -> str:
    value = item.get("requirement_id") or item.get("id")
    return str(value).strip() if value is not None else ""


def _mandatory_value(
    item: Mapping[str, Any],
    *,
    finding_id: str,
    source: str,
    identifier: str,
    issue: Any,
) -> bool | None:
    key = (
        "mandatory"
        if "mandatory" in item
        else "required"
        if "required" in item
        else None
    )
    if key is None:
        return None
    value = item.get(key)
    if isinstance(value, bool):
        return value
    issue(
        finding_id,
        f"{source} {identifier} 的 {key} 必须是 JSON boolean，不能使用字符串或其他类型",
        affected=[identifier],
    )
    return None


def _nonnegative_int(value: Any) -> int | None:
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


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
