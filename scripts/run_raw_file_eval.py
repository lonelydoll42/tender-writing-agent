"""Evaluate raw tender files through the local registry and analysis workflow."""

from __future__ import annotations

import argparse
import asyncio
import json
import re
import shutil
from datetime import datetime, timedelta, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping

from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.files import ProjectFileRegistry
from qiaowenshu_agent.core.runtime import AgentRuntime
from qiaowenshu_agent.skills import build_default_registry


ROOT = Path(__file__).resolve().parents[1]
BENCHMARK_ROOT = ROOT / "benchmarks" / "raw_file"
TEXT_CASES_PATH = BENCHMARK_ROOT / "cases.json"
PDF_ROOT = ROOT / "tests" / "标书Agent全流程模拟测试包_v1"
GROUND_TRUTH_PATH = PDF_ROOT / "13_ground_truth_预期规则与结果.json"
PAGE_BREAK_MARKER = "[[PAGE_BREAK]]"
EXPECTED_WORKFLOW = [
    "document-preprocess",
    "tender-intake",
    "consistency-review",
    "tender-decomposition",
    "bidder-material-intake",
    "evidence-matching",
    "bid-feasibility",
    "requirement-ledger",
    "compliance-review",
    "scoring-strategy",
    "analysis-report",
]

PDF_INPUTS: dict[str, tuple[str, str]] = {
    "tender": ("01_招标文件", "tender"),
    "correction": ("02_更正公告", "clarification"),
    "license": ("03_营业执照", "bidder_material"),
    "company_profile": ("03B_企业基本情况", "bidder_material"),
    "iso_valid": ("04A_ISO27001", "bidder_material"),
    "iso_expired": ("04B_ISO27001", "bidder_material"),
    "iso9001": ("05_ISO9001", "bidder_material"),
    "contract_135wan": ("06_类似项目合同_A", "bidder_material"),
    "contract_90wan": ("07_类似项目合同_B", "bidder_material"),
    "project_manager": ("08_项目经理", "bidder_material"),
    "social_complete": ("09A_项目经理社保", "bidder_material"),
    "social_missing": ("09B_项目经理社保", "bidder_material"),
    "bond_40000": ("10A_投标保证金", "bidder_material"),
    "bond_30000": ("10B_投标保证金", "bidder_material"),
    "authorization": ("11_法定代表人授权", "bidder_material"),
    "audit": ("12_2025年度审计报告", "bidder_material"),
}
PDF_SCENARIO_FILES = {
    "pdf_primary": [
        "tender",
        "correction",
        "license",
        "company_profile",
        "iso_valid",
        "iso9001",
        "contract_135wan",
        "contract_90wan",
        "project_manager",
        "social_complete",
        "bond_40000",
        "authorization",
        "audit",
    ],
    "pdf_hard_negative_no_ocr": [
        "tender",
        "correction",
        "license",
        "company_profile",
        "iso_expired",
        "iso9001",
        "contract_135wan",
        "contract_90wan",
        "project_manager",
        "social_complete",
        "bond_30000",
        "authorization",
        "audit",
    ],
    "pdf_human_review": [
        "tender",
        "correction",
        "license",
        "company_profile",
        "iso_valid",
        "iso9001",
        "contract_135wan",
        "contract_90wan",
        "project_manager",
        "social_missing",
        "bond_40000",
        "authorization",
        "audit",
    ],
}
MUST_NOT_PASS = {
    "pdf_hard_negative_no_ocr",
    "pdf_human_review",
    "pdf_low_confidence_ocr_simulation",
    "conflicting_scores",
    "amount_boundaries",
    "correction_conflict",
    "iso_standard_mismatch",
}
AMOUNT_EXPECTATIONS = {
    "06_类似项目合同_A": "1350000",
    "07_类似项目合同_B": "900000",
    "10A_投标保证金": "40000",
    "10B_投标保证金": "30000",
    "contract_135wan.txt": "1350000",
    "bond_40000.txt": "40000",
}
UNKNOWN_AMOUNT_FILES = {
    "contract_unprovided_next_bond.txt",
    "contract_negative_amount.txt",
}
REQUIREMENT_MATCHERS: dict[str, tuple[tuple[str, ...], ...]] = {
    "Q1": (("营业执照", "法人登记证明"),),
    "Q2": (("审计报告", "审计关键页", "年度审计", "银行资信证明"),),
    "Q3": (
        ("2023年以来", "2023年起", "2023-01-01以来"),
        ("至少1个", "不少于1个", "1个以上", "一个及以上"),
        ("数据治理", "政务信息化", "政务信息"),
        ("合同额", "合同金额", "项目金额"),
        (">=100万元", "≥100万元", "100万元以上", "不低于100万元", "1000000元"),
    ),
    "Q4": (
        ("ISO/IEC 27001", "ISO27001"),
        ("截止日", "投标截止", "截止日期"),
        ("有效", "在有效期"),
    ),
    "Q5": (
        ("项目经理", "项目负责人"),
        ("信息系统项目管理师", "系统项目管理师"),
        ("2026-03", "2026年3月", "2026/03"),
        ("2026-08", "2026年8月", "2026/08"),
        ("社保", "社会保险", "社会保障"),
        ("连续", "不间断", "无中断"),
    ),
    "Q6": (
        ("投标保证金", "保证金"),
        ("40000元", "40,000元", "4万元"),
        ("足额", "全额", "不少于"),
        ("按时", "及时", "到账"),
    ),
    "T1": (
        ("OAuth2.0", "OIDC"),
        ("对接", "接入", "集成"),
        ("统一身份平台", "统一身份"),
    ),
    "T2": (
        ("日志", "审计日志"),
        ("180天", "180 日", "180日"),
        ("不少于", "至少", "以上"),
    ),
    "T3": (
        ("TLS1.2", "TLS 1.2"),
        ("敏感字段", "敏感信息"),
        ("加密", "加密传输"),
    ),
    "T4": (
        ("国产Linux", "国产 Linux", "国产化 Linux"),
        ("PostgreSQL", "PostgreSQL兼容数据库"),
        ("不绑定单一公有云", "不依赖单一公有云", "不锁定单一公有云"),
    ),
}


def _which(name: str) -> str | None:
    return shutil.which(name) or shutil.which(f"{name}.exe")


def poppler_status() -> dict[str, Any]:
    required = ("pdftotext", "pdfinfo")
    missing = [name for name in required if _which(name) is None]
    ocr_missing = "pdftoppm" if _which("pdftoppm") is None else None
    return {
        "available": not missing,
        "missing": missing,
        "ocr_render_available": ocr_missing is None and not missing,
        "ocr_missing": [ocr_missing] if ocr_missing else [],
    }


class SimulatedLowConfidenceOCR:
    """Deterministic test double; its confidence is not measured OCR accuracy."""

    def __init__(self) -> None:
        self.calls: list[dict[str, Any]] = []

    def run(self, payload: Mapping[str, Any]) -> Mapping[str, Any]:
        self.calls.append(dict(payload))
        file_name = str(payload.get("file_name") or "")
        if "04A_ISO27001" not in file_name:
            return {
                "text": "",
                "confidence": 0.0,
                "warnings": ["non-target page ignored by OCR simulation"],
            }
        return {
            "text": "ISO/IEC 27001证书状态：有效",
            "confidence": 0.61,
            "warnings": ["scripted low-confidence OCR simulation"],
        }


def _load_text_case_manifest() -> dict[str, Any]:
    return json.loads(TEXT_CASES_PATH.read_text(encoding="utf-8"))


def _run_text_case(case_id: str, files: list[Mapping[str, str]]) -> dict[str, Any]:
    project_id = f"raw-text-{case_id}"
    registry = ProjectFileRegistry()
    file_ids: list[str] = []
    bidder_file_ids: list[str] = []
    registered_names: list[str] = []
    for item in files:
        path = BENCHMARK_ROOT / str(item["path"])
        source = path.read_text(encoding="utf-8")
        content = source.replace(PAGE_BREAK_MARKER, "\f").encode("utf-8")
        registration = registry.register(
            project_id=project_id,
            file_name=path.name,
            file_role=str(item["role"]),
            content=content,
        )
        registered_names.append(path.name)
        if item["role"] == "bidder_material":
            bidder_file_ids.append(registration.file.file_id)
        else:
            file_ids.append(registration.file.file_id)
    return _execute_case(
        case_id=case_id,
        project_id=project_id,
        registry=registry,
        file_ids=file_ids,
        bidder_file_ids=bidder_file_ids,
        source_files=registered_names,
    )


def _find_pdf_source(prefix: str) -> Path:
    matches = sorted(PDF_ROOT.glob(f"{prefix}*.pdf"))
    if not matches:
        raise FileNotFoundError(f"raw PDF fixture not found for prefix: {prefix}")
    return matches[0]


def _register_pdf_corpus(
    *, ocr_backend: SimulatedLowConfidenceOCR | None = None
) -> tuple[ProjectFileRegistry, dict[str, str]]:
    project_id = "raw-pdf-corpus-simulated-ocr" if ocr_backend else "raw-pdf-corpus"
    registry = ProjectFileRegistry(ocr_backend=ocr_backend)
    file_ids: dict[str, str] = {}
    for key, (prefix, role) in PDF_INPUTS.items():
        path = _find_pdf_source(prefix)
        registration = registry.register_path(
            project_id=project_id,
            path=path,
            file_role=role,
        )
        file_ids[key] = registration.file.file_id
    return registry, file_ids


def _run_pdf_case(
    case_id: str,
    registry: ProjectFileRegistry,
    file_ids_by_key: Mapping[str, str],
    source_keys: list[str],
    *,
    project_id: str = "raw-pdf-corpus",
) -> dict[str, Any]:
    selected = [file_ids_by_key[key] for key in source_keys]
    file_ids = [
        file_ids_by_key[key]
        for key in source_keys
        if PDF_INPUTS[key][1] != "bidder_material"
    ]
    bidder_file_ids = [
        file_ids_by_key[key]
        for key in source_keys
        if PDF_INPUTS[key][1] == "bidder_material"
    ]
    names = [_find_pdf_source(PDF_INPUTS[key][0]).name for key in source_keys]
    return _execute_case(
        case_id=case_id,
        project_id=project_id,
        registry=registry,
        file_ids=file_ids,
        bidder_file_ids=bidder_file_ids,
        source_files=names,
        parse_file_ids=selected,
    )


def _execute_case(
    *,
    case_id: str,
    project_id: str,
    registry: ProjectFileRegistry,
    file_ids: list[str],
    bidder_file_ids: list[str],
    source_files: list[str],
    parse_file_ids: list[str] | None = None,
) -> dict[str, Any]:
    runtime = AgentRuntime(
        build_default_registry(file_registry=registry),
        services={"file_registry": registry},
    )
    result = asyncio.run(
        runtime.run(
            SkillRequest.create(
                {
                    "project_id": project_id,
                    "file_ids": file_ids,
                    "bidder_file_ids": bidder_file_ids,
                    "bidder_id": "raw-file-benchmark-bidder",
                    "bidder_name": "华辰数科有限公司",
                    "as_of": "2026-09-01T00:00:00+08:00",
                    "task": "这个项目能不能投？",
                }
            )
        )
    )
    step_data = {
        step.skill_name: step.result.data
        for step in result.steps
        if isinstance(step.result.data, Mapping)
    }
    decomposition = step_data.get("tender-decomposition", {})
    materials_data = step_data.get("bidder-material-intake", {})
    material_profile = materials_data.get("bidder_profile") or {}
    materials = (
        material_profile.get("materials")
        or materials_data.get("materials")
        or []
    )
    consistency = step_data.get("consistency-review", {})
    consistency_summary = consistency.get("summary", {})
    evidence_matching = step_data.get("evidence-matching", {})
    bid_feasibility = step_data.get("bid-feasibility", {})
    ledger = step_data.get("requirement-ledger", {})
    compliance = step_data.get("compliance-review", {})
    pages = []
    for file_id in parse_file_ids or (file_ids + bidder_file_ids):
        try:
            artifact = registry.parse(file_id)
        except Exception as exc:
            pages.append(
                {
                    "file_id": file_id,
                    "error": str(exc),
                    "pages": [],
                }
            )
            continue
        record = registry.require(file_id)
        pages.append(
            {
                "file_name": record.file_name,
                "pages": [
                    {
                        "page_number": page.get("page_number"),
                        "page_type": page.get("page_type"),
                        "extraction_method": page.get("extraction_method"),
                        "confidence": page.get("confidence"),
                        "warnings": list(page.get("warnings") or []),
                        "text_excerpt": str(page.get("text") or "")[:180],
                    }
                    for page in artifact.get("pages") or []
                ],
                "warnings": list(artifact.get("warnings") or []),
            }
        )

    conflicts = [
        {
            "field": item.get("field"),
            "baseline_value": item.get("baseline_value"),
            "conflicting_values": list(item.get("conflicting_values") or []),
        }
        for item in consistency.get("conflicts") or []
    ]
    correction_descriptions = [
        str(item.get("description") or "")
        for item in decomposition.get("requirements") or []
        if any(
            token in str(item.get("description") or "")
            for token in ("90天", "180天")
        )
    ]
    simulated_confidence = sorted(
        {
            page["confidence"]
            for source in pages
            for page in source["pages"]
            if page.get("extraction_method") == "ocr"
            and isinstance(page.get("confidence"), (int, float))
        }
    )
    warnings = list(result.to_dict().get("warnings") or [])
    return {
        "case_id": case_id,
        "execution_status": result.execution_status,
        "execution_message": result.message,
        "business_status": result.business_status,
        "needs_human_review": result.needs_human_review,
        "submission_allowed": result.submission_allowed,
        "scoped_gate_passed": result.scoped_gate_passed,
        "source_files": source_files,
        "workflow_steps": [step.skill_name for step in result.steps],
        "step_results": [
            {
                "skill_name": step.skill_name,
                "status": step.result.status,
                "error_code": step.result.error_code,
                "message": step.result.message,
            }
            for step in result.steps
        ],
        "requirements": [
            {
                "requirement_id": item.get("requirement_id"),
                "category": item.get("category"),
                "description": item.get("description"),
                "evidence_required": list(item.get("evidence_required") or []),
                "check_rule": dict(item.get("check_rule") or {}),
                "source_references": list(item.get("source_references") or []),
            }
            for item in decomposition.get("requirements") or []
        ],
        "decomposition_extraction_complete": decomposition.get(
            "extraction_complete"
        ),
        "decomposition_needs_human_review": decomposition.get(
            "needs_human_review"
        ),
        "decomposition_business_status": decomposition.get("business_status"),
        "scoring_items": [
            {
                "item_id": item.get("item_id"),
                "title": item.get("title"),
                "max_score": item.get("max_score"),
                "criteria": item.get("criteria"),
                "source_references": list(item.get("source_references") or []),
            }
            for item in decomposition.get("scoring_items") or []
        ],
        "decomposition_warnings": list(decomposition.get("warnings") or []),
        "evidence_matches": [
            {
                "requirement_id": item.get("requirement_id"),
                "material_id": item.get("material_id"),
                "status": item.get("status"),
                "reason": item.get("reason"),
            }
            for item in evidence_matching.get("matches") or []
        ],
        "bid_feasibility": {
            "decision": bid_feasibility.get("decision"),
            "checks": list(bid_feasibility.get("checks") or []),
            "warnings": list(bid_feasibility.get("warnings") or []),
        },
        "clarification_detected": any(
            "更正" in str(item) or "澄清" in str(item)
            for item in decomposition.get("warnings") or []
        ),
        "correction_values_preserved": correction_descriptions,
        "correction_handling": {
            "automatic_override_resolution": "not_attempted",
            "human_review_requested": bool(
                any(
                    "更正" in str(item) or "澄清" in str(item)
                    for item in decomposition.get("warnings") or []
                )
                and result.needs_human_review
            ),
            "source_values_preserved": bool(
                any("90天" in item for item in correction_descriptions)
                and any("180天" in item for item in correction_descriptions)
            ),
        },
        "consistency": {
            "summary": dict(consistency_summary),
            "conflicts": conflicts,
        },
        "materials": [
            {
                "title": item.get("title"),
                "material_type": item.get("material_type"),
                "metadata": dict(item.get("metadata") or {}),
            }
            for item in materials
            if isinstance(item, Mapping)
        ],
        "ledger_summary": dict(ledger.get("summary") or {}),
        "compliance": {
            "business_status": compliance.get("business_status"),
            "needs_human_review": compliance.get("needs_human_review"),
            "submission_allowed": compliance.get("submission_allowed"),
            "summary": dict(compliance.get("summary") or {}),
        },
        "parse_provenance": pages,
        "simulated_ocr_confidences": simulated_confidence,
        "warnings": warnings,
    }


def _amount_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    observed_by_name: dict[str, str | None] = {}
    for case in cases:
        for material in case.get("materials") or []:
            title = str(material.get("title") or "")
            selector = next(
                (
                    candidate
                    for candidate in AMOUNT_EXPECTATIONS
                    if title == candidate or title.startswith(candidate)
                ),
                None,
            )
            if selector and selector not in observed_by_name:
                amount = (material.get("metadata") or {}).get("amount")
                observed_by_name[selector] = (
                    str(amount) if amount is not None else None
                )
    expected_names = list(AMOUNT_EXPECTATIONS)
    samples = [
        {
            "file_selector": name,
            "expected_yuan": AMOUNT_EXPECTATIONS[name],
            "actual_yuan": observed_by_name.get(name),
            "status": (
                "correct"
                if observed_by_name.get(name) == AMOUNT_EXPECTATIONS[name]
                and name in observed_by_name
                else "missing"
                if name in observed_by_name
                and observed_by_name.get(name) is None
                else "not_run"
                if name not in observed_by_name
                else "incorrect"
            ),
        }
        for name in expected_names
    ]
    conversion_errors = [
        item for item in samples if item["status"] == "incorrect"
    ]
    extraction_errors = [item for item in samples if item["status"] == "missing"]
    executed_amounts = len(observed_by_name)

    unknown_samples = []
    for case in cases:
        for material in case.get("materials") or []:
            title = Path(str(material.get("title") or "")).name
            if title in UNKNOWN_AMOUNT_FILES:
                metadata = material.get("metadata") or {}
                unknown_samples.append(
                    {
                        "file": title,
                        "amount_emitted": metadata.get("amount"),
                        "verification_status": metadata.get(
                            "verification_status", "unknown"
                        ),
                    }
                )
    unknown_failures = [
        item
        for item in unknown_samples
        if item["amount_emitted"] is not None
        or item["verification_status"] != "unknown"
    ]
    return {
        "known_amounts": {
            "status": "measured" if executed_amounts else "not_run",
            "correct_count": sum(
                item["status"] == "correct" for item in samples
            ),
            "conversion_error_count": len(conversion_errors),
            "unit_error_count": len(conversion_errors),
            "unparsed_count": len(extraction_errors),
            "not_run_count": sum(item["status"] == "not_run" for item in samples),
            "denominator": executed_amounts,
            "expected_source_count": len(expected_names),
            "samples": samples,
            "error_samples": conversion_errors + extraction_errors,
        },
        "unknown_amount_safety": {
            "status": "measured" if unknown_samples else "not_run",
            "safe_unknown_count": len(unknown_samples) - len(unknown_failures),
            "unsafe_extraction_count": len(unknown_failures),
            "denominator": len(unknown_samples),
            "samples": unknown_samples,
            "error_samples": unknown_failures,
        },
    }


def _score_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    expected_scores = {
        "minimal_repro": 10,
        "cross_page_score": 10,
    }
    by_id = {case["case_id"]: case for case in cases}
    score_samples: list[dict[str, Any]] = []
    for case_id, expected in expected_scores.items():
        case = by_id.get(case_id)
        observed = [
            float(item["max_score"])
            for item in (case or {}).get("scoring_items") or []
            if item.get("max_score") is not None
        ]
        correct = expected in observed
        score_samples.append(
            {
                "case_id": case_id,
                "expected_max_score": expected,
                "actual_max_scores": observed,
                "status": "correct" if correct else "incorrect_or_missing",
            }
        )
    errors = [item for item in score_samples if item["status"] != "correct"]

    conflict_cases = [
        case for case in cases if case["case_id"] == "conflicting_scores"
    ]
    conflict_denominator = 2
    conflict_items = (
        conflict_cases[0].get("scoring_items") if conflict_cases else None
    )
    conflict_warnings = (
        conflict_cases[0].get("decomposition_warnings") if conflict_cases else None
    )
    conflict_safe = bool(
        conflict_cases
        and not conflict_items
        and len(conflict_warnings or []) >= conflict_denominator
    )
    return {
        "max_score": {
            "status": (
                "measured"
                if any(item["case_id"] in by_id for item in score_samples)
                else "not_run"
            ),
            "correct_count": len(score_samples) - len(errors),
            "error_count": len(errors),
            "denominator": sum(item["case_id"] in by_id for item in score_samples),
            "expected_case_count": len(score_samples),
            "samples": score_samples,
            "error_samples": errors,
        },
        "conflicting_caps": {
            "status": "measured" if conflict_cases else "not_run",
            "safe_count": conflict_denominator if conflict_safe else 0,
            "unsafe_score_emissions": 0 if conflict_safe else conflict_denominator,
            "denominator": conflict_denominator if conflict_cases else 0,
            "samples": [
                {
                    "case_id": "conflicting_scores",
                    "score_items_emitted": conflict_items or [],
                    "warnings": conflict_warnings or [],
                }
            ]
            if conflict_cases
            else [],
        },
    }


def _requirement_metrics(
    primary_pdf_case: dict[str, Any] | None,
    ground_truth: Mapping[str, Any],
    *,
    unavailable_status: str = "not_run",
) -> dict[str, Any]:
    expected = list(ground_truth.get("mandatory_requirements") or [])
    if primary_pdf_case is None:
        return {
            "status": unavailable_status,
            "expected_count": len(expected),
            "matched_count": None,
            "omission_count": None,
            "denominator": 0,
            "omission_rate": None,
            "omissions": [],
            "items": [],
            "interpretation": (
                "文本约束覆盖指标；不验证条款是否已转成完整、可执行的业务规则。"
            ),
            "executable_rule_completeness": {
                "status": "not_measured",
                "value": None,
            },
        }
    observed = [
        {
            "requirement_id": str(item.get("requirement_id") or f"R-{index + 1:03d}"),
            "description": str(item.get("description") or ""),
            "source_references": list(item.get("source_references") or []),
        }
        for index, item in enumerate(primary_pdf_case.get("requirements") or [])
    ]
    omissions = []
    item_results = []
    for index, requirement in enumerate(expected):
        requirement_id = str(requirement.get("id") or f"GT-{index + 1}")
        required_groups = REQUIREMENT_MATCHERS.get(requirement_id, ())
        matched_groups = []
        missing_groups = []
        candidate_evidence: dict[str, dict[str, Any]] = {}
        for group_index, alternatives in enumerate(required_groups, start=1):
            group_requirement_ids = []
            group_hits = []
            for extracted in observed:
                folded_description = re.sub(
                    r"\s+", "", extracted["description"]
                ).casefold()
                hits = [
                    term
                    for term in alternatives
                    if re.sub(r"\s+", "", term).casefold() in folded_description
                ]
                if hits:
                    group_requirement_ids.append(extracted["requirement_id"])
                    group_hits.extend(hits)
                    candidate = candidate_evidence.setdefault(
                        extracted["requirement_id"],
                        {
                            "requirement_id": extracted["requirement_id"],
                            "description": extracted["description"],
                            "matched_group_ids": [],
                            "matched_terms": [],
                        },
                    )
                    candidate["matched_group_ids"].append(group_index)
                    candidate["matched_terms"].extend(hits)
            if group_requirement_ids:
                matched_groups.append(
                    {
                        "group_id": group_index,
                        "synonyms": list(alternatives),
                        "matched_terms": sorted(set(group_hits)),
                        "extracted_requirement_ids": sorted(
                            set(group_requirement_ids)
                        ),
                    }
                )
            else:
                missing_groups.append(
                    {
                        "group_id": group_index,
                        "synonyms": list(alternatives),
                    }
                )
        matched = bool(required_groups) and not missing_groups
        candidates = (
            [
                {
                    **candidate,
                    "missing_group_ids": [
                        group_index
                        for group_index in range(1, len(required_groups) + 1)
                        if group_index not in candidate["matched_group_ids"]
                    ],
                    "counted_as_success": False,
                }
                for candidate in candidate_evidence.values()
            ]
            if not matched
            else []
        )
        result = {
            "requirement_id": requirement_id,
            "requirement": requirement.get("requirement"),
            "status": "matched" if matched else "missing",
            "matched_groups": matched_groups,
            "missing_groups": missing_groups,
            "matched_extracted_requirement_ids": sorted(
                {
                    extracted_id
                    for group in matched_groups
                    for extracted_id in group["extracted_requirement_ids"]
                }
            ),
            "ambiguous_candidates": candidates,
        }
        item_results.append(result)
        if not matched:
            omissions.append(
                {
                    "requirement_id": requirement_id,
                    "requirement": requirement.get("requirement"),
                    "missing_groups": missing_groups,
                    "ambiguous_candidates": candidates,
                }
            )
    matched_count = len(expected) - len(omissions)
    return {
        "status": "measured",
        "expected_count": len(expected),
        "matched_count": matched_count,
        "omission_count": len(omissions),
        "denominator": len(expected),
        "omission_rate": len(omissions) / len(expected) if expected else None,
        "omissions": omissions,
        "items": item_results,
        "interpretation": (
            "原文约束文本覆盖：同一必要约束组内同义词按 OR 匹配，"
            "各约束组按 AND 匹配，并关联命中的抽取 requirement_id。"
            "局部词语重叠仅记为 ambiguous_candidates，不算要求命中。"
            "该指标不验证已抽取条款是否完整转成可执行业务规则。"
        ),
        "executable_rule_completeness": {
            "status": "not_measured",
            "value": None,
        },
    }


def _false_release_metrics(cases: list[dict[str, Any]]) -> dict[str, Any]:
    by_id = {case["case_id"]: case for case in cases}
    evaluated: list[dict[str, Any]] = []
    inconclusive: list[dict[str, Any]] = []
    for case_id in sorted(MUST_NOT_PASS):
        case = by_id.get(case_id)
        if case is None:
            inconclusive.append({"case_id": case_id, "reason": "not executed"})
            continue
        status = case.get("business_status")
        has_compliance = "compliance-review" in (case.get("workflow_steps") or [])
        if not has_compliance or status not in {"passed", "failed", "needs_review"}:
            inconclusive.append(
                {
                    "case_id": case_id,
                    "reason": "workflow did not produce an assessed compliance status",
                    "business_status": status,
                    "execution_status": case.get("execution_status"),
                }
            )
            continue
        evaluated.append(
            {
                "case_id": case_id,
                "business_status": status,
                "scoped_gate_passed": bool(case.get("scoped_gate_passed")),
                "false_release": status == "passed"
                or bool(case.get("scoped_gate_passed")),
            }
        )
    failures = [item for item in evaluated if item["false_release"]]
    return {
        "status": "measured" if evaluated else "not_run",
        "false_release_count": len(failures),
        "safe_count": len(evaluated) - len(failures),
        "denominator": len(evaluated),
        "inconclusive_count": len(inconclusive),
        "inconclusive_cases": inconclusive,
        "error_samples": failures,
        "evaluated_cases": evaluated,
        "interpretation": (
            "0误放行仅表示本组门禁策略未放行标记为不得通过的样本；"
            "由于默认本地全文抽取统一标记 needs_review，该数值不证明资格"
            "识别准确率。请结合要求文本覆盖、评分上限和金额单位样本分别判断。"
        ),
    }


def _decimal_equal(left: Any, right: Any) -> bool:
    try:
        return Decimal(str(left)) == Decimal(str(right))
    except (InvalidOperation, ValueError):
        return False


def _assemble_report(
    *,
    cases: list[dict[str, Any]],
    pdf_status: Mapping[str, Any],
    simulated_ocr: Mapping[str, Any],
) -> dict[str, Any]:
    # Oracle data is read only after every raw source has passed through runtime.
    ground_truth = json.loads(GROUND_TRUTH_PATH.read_text(encoding="utf-8"))
    by_id = {case["case_id"]: case for case in cases}
    pdf_candidate = by_id.get("pdf_primary") if pdf_status["available"] else None
    decomposition_succeeded = bool(
        pdf_candidate
        and any(
            item.get("skill_name") == "tender-decomposition"
            and item.get("status") == "success"
            for item in pdf_candidate.get("step_results") or []
        )
    )
    pdf_primary = pdf_candidate if decomposition_succeeded else None
    score_metrics = _score_metrics(cases)
    amount_metrics = _amount_metrics(cases)
    requirement_metrics = _requirement_metrics(
        pdf_primary,
        ground_truth,
        unavailable_status=(
            "not_run" if not pdf_status["available"] else "inconclusive"
        ),
    )
    false_release = _false_release_metrics(cases)

    amount_metrics["known_amounts"]["samples"] = [
        {
            **item,
            "numeric_match": _decimal_equal(
                item["actual_yuan"], item["expected_yuan"]
            ),
        }
        for item in amount_metrics["known_amounts"]["samples"]
    ]
    run_status = (
        "completed_with_unrun_pdf_cases"
        if not pdf_status["available"] or not pdf_status["ocr_render_available"]
        else "completed"
    )
    return {
        "benchmark": "raw-file-reliability",
        "version": 1,
        "generated_at": datetime.now(
            timezone(timedelta(hours=8), "Asia/Shanghai")
        ).isoformat(),
        "timezone": "Asia/Shanghai",
        "run_status": run_status,
        "input_policy": {
            "raw_pdf_directory": str(PDF_ROOT.relative_to(ROOT)),
            "ground_truth_loaded_after_runtime": True,
            "ground_truth_registered_as_input": False,
            "excluded_inputs": [
                "00_使用说明_请勿输入待测Agent.pdf",
                GROUND_TRUTH_PATH.name,
            ],
            "structured_requirement_or_material_inputs": False,
        },
        "poppler": dict(pdf_status),
        "simulated_ocr": dict(simulated_ocr),
        "metrics": {
            "requirement_omission": requirement_metrics,
            "amount_normalization": amount_metrics["known_amounts"],
            "amount_unknown_safety": amount_metrics["unknown_amount_safety"],
            "score_maximum": score_metrics["max_score"],
            "conflicting_score_caps": score_metrics["conflicting_caps"],
            "hard_false_release": false_release,
        },
        "raw_local_extraction_policy": {
            "extraction_complete": False,
            "business_status": "needs_review",
            "interpretation": (
                "原始全文经本地正则解析仅为候选抽取，统一要求人工复核；"
                "门禁未放行只说明策略保守，不代表资格判断准确。"
            ),
        },
        "workflow_coverage": {
            "expected_steps": EXPECTED_WORKFLOW,
            "cases": [
                {
                    "case_id": case["case_id"],
                    "execution_status": case["execution_status"],
                    "workflow_steps": case["workflow_steps"],
                    "missing_expected_steps": [
                        step
                        for step in EXPECTED_WORKFLOW
                        if step not in case["workflow_steps"]
                    ],
                }
                for case in cases
            ],
        },
        "cases": cases,
    }


def run_raw_file_eval() -> dict[str, Any]:
    manifest = _load_text_case_manifest()
    cases = [
        _run_text_case(case_id, files)
        for case_id, files in manifest["text_cases"].items()
    ]
    pdf_status = poppler_status()
    simulated_ocr_summary: dict[str, Any] = {
        "mode": "not_run",
        "is_real_ocr_accuracy_measurement": False,
        "note": (
            "Scripted OCR output and confidence exercise provenance/review flow only; "
            "they do not measure real OCR accuracy."
        ),
        "confidence_values": [],
        "calls": 0,
    }
    if pdf_status["available"]:
        registry, pdf_file_ids = _register_pdf_corpus()
        for case_id, keys in PDF_SCENARIO_FILES.items():
            cases.append(_run_pdf_case(case_id, registry, pdf_file_ids, keys))

        if pdf_status["ocr_render_available"]:
            backend = SimulatedLowConfidenceOCR()
            simulation_registry, simulation_ids = _register_pdf_corpus(
                ocr_backend=backend
            )
            simulated_case = _run_pdf_case(
                "pdf_low_confidence_ocr_simulation",
                simulation_registry,
                simulation_ids,
                PDF_SCENARIO_FILES["pdf_primary"],
                project_id="raw-pdf-corpus-simulated-ocr",
            )
            cases.append(simulated_case)
            simulated_ocr_summary = {
                "mode": "scripted_simulation",
                "is_real_ocr_accuracy_measurement": False,
                "note": (
                    "The backend returns fixed text at confidence 0.61. This tests "
                    "warning/provenance propagation, not recognition accuracy."
                ),
                "confidence_values": simulated_case[
                    "simulated_ocr_confidences"
                ],
                "calls": len(backend.calls),
            }
        else:
            cases.append(
                {
                    "case_id": "pdf_low_confidence_ocr_simulation",
                    "execution_status": "not_run",
                    "business_status": "not_checked",
                    "workflow_steps": [],
                    "source_files": [],
                    "warnings": [
                        "Poppler pdftoppm is unavailable; "
                        "simulated OCR workflow not run"
                    ],
                }
            )
            simulated_ocr_summary["reason"] = "pdftoppm unavailable"
    else:
        reason = "missing Poppler tools: " + ", ".join(pdf_status["missing"])
        for case_id in (
            *PDF_SCENARIO_FILES,
            "pdf_low_confidence_ocr_simulation",
        ):
            cases.append(
                {
                    "case_id": case_id,
                    "execution_status": "not_run",
                    "business_status": "not_checked",
                    "workflow_steps": [],
                    "source_files": [],
                    "warnings": [reason],
                }
            )
        simulated_ocr_summary["reason"] = reason
    return _assemble_report(
        cases=cases,
        pdf_status=pdf_status,
        simulated_ocr=simulated_ocr_summary,
    )


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--output",
        type=Path,
        help="Write this run's JSON report here; by default print to stdout.",
    )
    args = parser.parse_args()
    report = run_raw_file_eval()
    rendered = json.dumps(report, ensure_ascii=False, indent=2, default=str)
    if args.output:
        output = args.output if args.output.is_absolute() else ROOT / args.output
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(rendered + "\n", encoding="utf-8")
        print(
            json.dumps(
                {
                    "report": str(output),
                    "run_status": report["run_status"],
                    "metrics": report["metrics"],
                },
                ensure_ascii=False,
                indent=2,
            )
        )
    else:
        print(rendered)


if __name__ == "__main__":
    main()
