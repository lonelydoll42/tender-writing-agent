from __future__ import annotations

from qiaowenshu_agent.skills.local_requirement_groups import (
    group_requirement_records,
)
from qiaowenshu_agent.skills.local_backends import _candidate_records
from qiaowenshu_agent.skills.local_requirement_logic import (
    build_local_requirement_rule,
)


def _ref(
    quote: str,
    line: int,
    *,
    document: str = "tender.pdf",
    version: str = "v1",
    page: int = 1,
) -> dict:
    return {
        "document_id": document,
        "source_version": version,
        "page": page,
        "locator": f"{document}:p{page}:l{line}",
        "quote": quote,
    }


def _run(lines: list[str], *, section: dict | None = None):
    records = [
        (line, [_ref(line, index)])
        for index, line in enumerate(lines, start=1)
    ]
    default_section = {
        "source_references": [ref for _, refs in records for ref in refs]
    }
    sections = [section or default_section]
    return group_requirement_records(sections, records)


def test_unpunctuated_any_frame_groups_only_numbered_obligations() -> None:
    result = _run(
        [
            "投标人须提供以下两项任选一项",
            "（1）有效营业执照",
            "（2）法人登记证明",
        ]
    )

    assert len(result) == 1
    description, refs, rule = result[0]
    assert "以下两项任选一项" in description
    assert rule["condition_logic"]["op"] == "any"
    assert rule["rule_ast"]["op"] == "manual_review"
    assert rule["coverage_status"] == "partial"
    assert rule["evaluation_capability"]["automatic"] == "unsupported"
    assert [ref["quote"] for ref in refs] == [
        "投标人须提供以下两项任选一项",
        "（1）有效营业执照",
        "（2）法人登记证明",
    ]


def test_sibling_levels_group_only_under_explicit_same_scope_frames() -> None:
    result = _run(
        [
            "投标人应满足以下全部条件",
            "1.1 具有有效营业执照",
            "1.2 具有法人登记证明",
            "投标人须满足以下条件同时满足",
            "2.1 提供2025年度审计报告关键页",
            "2.2 提供银行资信证明",
        ]
    )

    assert len(result) == 2
    assert result[0][2]["condition_logic"]["op"] == "all"
    assert result[1][2]["condition_logic"]["op"] == "all"
    assert result[0][1][0]["quote"] == "投标人应满足以下全部条件"
    assert result[1][1][0]["quote"] == "投标人须满足以下条件同时满足"


def test_same_person_and_date_semantics_are_kept_when_explicitly_framed() -> None:
    result = _run(
        [
            "拟任项目经理须同时满足以下条件",
            "1.1 具有信息系统项目管理师证书",
            "1.2 为投标人连续缴纳2026年3月至8月社会保险",
        ]
    )

    assert len(result) == 1
    logic = result[0][2]["condition_logic"]
    assert logic["op"] == "all"
    sameperson = logic["conditions"][0]
    assert sameperson["op"] == "sameperson"
    leaves = sameperson["conditions"][0]["conditions"]
    assert any(
        leaf.get("op") == "date_range"
        and leaf["start"] == "2026-03"
        and leaf["end"] == "2026-08"
        for leaf in leaves
    )
    assert any(
        leaf.get("material_type") == "bidder_employer_relationship"
        for leaf in leaves
    )


def test_no_group_for_ambiguous_scope_materials_or_product_choices() -> None:
    lines = [
        "投标人应提供相关材料",
        "1.1 有效营业执照",
        "1.2 法人登记证明",
        "材料清单（非资格条件）",
        "2.1 技术方案支持品牌甲",
        "2.2 技术方案支持品牌乙",
        "可采用以下产品方案",
        "3.1 支持产品甲",
        "3.2 支持产品乙",
    ]
    result = _run(lines)

    assert [item[0] for item in result] == lines
    assert all(item[2] is None for item in result)


def test_section_version_person_and_employer_boundaries_never_merge() -> None:
    lines = [
        "投标人须提供以下全部材料",
        "1.1 拟任甲经理具有证书",
        "1.2 拟任乙经理具有证书",
    ]
    refs = [
        _ref(lines[0], 1),
        _ref(lines[1], 2, version="v1"),
        _ref(lines[2], 3, version="v2"),
    ]
    sections = [
        {"source_references": refs[:2]},
        {"source_references": refs[2:]},
    ]
    records = list(zip(lines, [[ref] for ref in refs]))

    result = group_requirement_records(sections, records)

    assert len(result) == 3
    assert all(item[2] is None for item in result)


def test_short_numbers_and_unreferenced_records_are_not_lists() -> None:
    lines = ["最低TLS1.2", "提供3份证明", "PostgreSQL 16", "普通条款"]
    records = [(line, []) for line in lines]
    result = group_requirement_records(
        [{"content": "\n".join(lines)}],
        records,
    )

    assert [item[0] for item in result] == lines
    assert all(item[2] is None for item in result)


def test_duplicate_text_at_distinct_physical_lines_keeps_exact_citations() -> None:
    lines = [
        "投标人应提供以下全部材料",
        "1.1 有效营业执照",
        "1.2 有效营业执照",
    ]
    result = _run(lines)

    assert len(result) == 1
    citations = result[0][1]
    assert [item["quote"] for item in citations[1:]] == [
        "1.1 有效营业执照",
        "1.2 有效营业执照",
    ]
    assert [item["locator"] for item in citations[1:]] == [
        "tender.pdf:p1:l2",
        "tender.pdf:p1:l3",
    ]


def test_or_frame_without_obligation_does_not_promote_optional_choices() -> None:
    result = _run(
        [
            "以下两项任选一项",
            "1.1 支持产品甲",
            "1.2 支持产品乙",
        ]
    )

    assert len(result) == 3
    assert all(item[2] is None for item in result)


def test_no_reference_records_need_one_uniquely_positioned_section() -> None:
    records = [
        ("以下两项任选一项：", []),
        ("1. 提供有效营业执照", []),
        ("2. 提供有效法人登记证明", []),
    ]
    section = {
        "title": "generic.txt",
        "content": "\n".join(text for text, _ in records),
    }

    result = group_requirement_records([section], records)

    assert len(result) == 1
    assert result[0][2]["condition_logic"]["op"] == "any"
    assert result[0][1] == []

    ambiguous = group_requirement_records(
        [section, {"title": "另一章", "content": section["content"]}],
        records,
    )
    assert len(ambiguous) == 3
    assert all(item[2] is None for item in ambiguous)


def test_long_blank_section_boundary_uses_exact_raw_line_references() -> None:
    content = (
        "一、主体资格\n"
        + "\n" * 100
        + "以下两项任选一项：\n"
        + "（1）提供有效营业执照\n"
        + "二、财务资格\n"
        + "（2）投标人须提供2025年度审计报告"
    )
    section = {
        "title": "generic.txt",
        "content": content,
        "source_references": [
            _ref(content, 1, page=1),
        ],
    }
    records = _candidate_records([section])

    result = group_requirement_records([section], records)

    assert len(result) == 3
    assert not any(
        "营业执照" in item[0] and "审计报告" in item[0] for item in result
    )
    assert all(
        ref["quote"] in content
        for _text, refs, _rule in result
        for ref in refs
    )


def test_mixed_document_version_reference_sets_are_not_grouped() -> None:
    lines = [
        "投标人须提供以下全部材料",
        "1.1 有效营业执照",
        "1.2 法人登记证明",
    ]
    mixed_refs = [
        [
            _ref(lines[0], 1),
            _ref(lines[0], 1, document="other.pdf", version="v2"),
        ],
        [
            _ref(lines[1], 2),
            _ref(lines[1], 2, document="other.pdf", version="v2"),
        ],
        [
            _ref(lines[2], 3),
            _ref(lines[2], 3, document="other.pdf", version="v2"),
        ],
    ]
    section_refs = [ref for refs in mixed_refs for ref in refs]
    records = list(zip(lines, mixed_refs))

    result = group_requirement_records(
        [{"source_references": section_refs}], records
    )

    assert len(result) == 3
    assert all(item[2] is None for item in result)


def test_missing_raw_section_text_requires_consecutive_physical_locators() -> None:
    lines = [
        "投标人须提供以下全部材料",
        "1.1 有效营业执照",
        "1.2 法人登记证明",
    ]
    line_numbers = [1, 3, 4]
    records = [
        (line, [_ref(line, line_number)])
        for line, line_number in zip(lines, line_numbers)
    ]
    section = {"source_references": [ref for _, refs in records for ref in refs]}

    result = group_requirement_records([section], records)

    assert len(result) == 3
    assert all(item[2] is None for item in result)


def test_optional_brand_or_does_not_become_qualification_requirement() -> None:
    result = _run(
        [
            "投标人可选以下任意一种方案",
            "1. 支持品牌甲",
            "2. 支持品牌乙",
        ],
        section={
            "title": "资格要求",
            "source_references": [
                _ref("投标人可选以下任意一种方案", 1),
                _ref("1. 支持品牌甲", 2),
                _ref("2. 支持品牌乙", 3),
            ],
        },
    )

    assert len(result) == 3
    assert all(item[2] is None for item in result)


def test_sameperson_semantics_are_never_imposed_on_an_any_group() -> None:
    result = _run(
        [
            "拟任项目经理须从以下两项任选一项",
            "1.1 具有信息系统项目管理师证书",
            "1.2 为投标人连续缴纳2026年3月至8月社会保险",
        ]
    )

    assert len(result) == 1
    logic = result[0][2]["condition_logic"]
    assert logic["op"] == "any"
    assert not any(_has_operator(child, "sameperson") for child in logic["conditions"])


def _has_operator(node: dict, operation: str) -> bool:
    if node.get("op") == operation:
        return True
    return any(
        _has_operator(child, operation)
        for child in node.get("conditions", [])
        if isinstance(child, dict)
    )


def test_explicit_outer_and_keeps_license_or_audit_branch_semantics() -> None:
    source = (
        "投标人须提供有效营业执照或法人登记证明，"
        "并提供2025年度审计报告。"
    )
    rule = build_local_requirement_rule(source)
    logic = rule["condition_logic"]

    assert logic["op"] == "all"
    license_options, audit = logic["conditions"]
    assert license_options["op"] == "any"
    assert {
        item["material_type"] for item in license_options["conditions"]
    } == {"business_license", "legal_entity_registration"}
    assert audit["material_type"] == "audit_report_key_pages"
    assert audit["year"] == 2025
    assert audit["source_text"] != source
    assert rule["rule_ast"]["op"] == "manual_review"
    assert rule["evaluation_capability"]["automatic"] == "unsupported"


def test_tls_and_postgresql_gte_need_explicit_minimum_language() -> None:
    tls = build_local_requirement_rule("敏感传输最低为 TLS1.2。")
    tls_threshold = next(
        item
        for item in tls["condition_logic"]["conditions"]
        if item.get("field") == "tls_version"
    )
    assert tls_threshold["operator"] == "gte"
    assert tls_threshold["value"] == "1.2"

    exact_pg = build_local_requirement_rule(
        "环境支持国产Linux及PostgreSQL 14兼容数据库。"
    )
    assert not any(
        item.get("field") == "postgresql_version"
        for item in exact_pg["condition_logic"]["conditions"]
    )

    minimum_pg = build_local_requirement_rule(
        "环境支持国产Linux及PostgreSQL 14及以上兼容数据库。"
    )
    pg_threshold = next(
        item
        for item in minimum_pg["condition_logic"]["conditions"]
        if item.get("field") == "postgresql_version"
    )
    assert pg_threshold["operator"] == "gte"
    assert pg_threshold["value"] == "14"


def test_existing_project_manager_and_identity_trees_survive_semicolon() -> None:
    manager = build_local_requirement_rule(
        "拟任项目经理须具有信息系统项目管理师证书，且为投标人连续缴纳"
        "2026年3月至8月社会保险。"
    )
    assert manager["condition_logic"]["conditions"][0]["op"] == "sameperson"
    assert any(
        item["op"] == "date_range"
        for item in manager["condition_logic"]["conditions"][0]["conditions"][0][
            "conditions"
        ]
    )

    identity = build_local_requirement_rule(
        "支持通过OAuth2.0/OIDC对接现有身份系统；"
        "不得要求更换现有身份系统。"
    )
    assert any(
        item["op"] == "not"
        for item in identity["condition_logic"]["conditions"]
    )
