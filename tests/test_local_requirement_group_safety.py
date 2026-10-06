from __future__ import annotations

import pytest

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.skills.evidence_matching import EvidenceMatchingSkill
from qiaowenshu_agent.skills.local_backends import (
    RegistryTenderDecompositionBackend,
)
from qiaowenshu_agent.skills.local_requirement_logic import (
    build_local_requirement_rule,
)


def _context() -> SkillContext:
    return SkillContext(
        run_id="local-requirement-group-safety",
        request=SkillRequest.create(),
    )


def _reference(
    document_id: str,
    version: str,
    page: int,
    quote: str,
    locator: str,
) -> dict[str, object]:
    return {
        "document_id": document_id,
        "source_version": version,
        "page": page,
        "quote": quote,
        "locator": locator,
    }


def _extract(*sections: dict[str, object]) -> dict[str, object]:
    return RegistryTenderDecompositionBackend().run(
        {"sections": list(sections)},
        _context(),
    )


def _requirements(result: dict[str, object]) -> list[dict[str, object]]:
    return result["requirements"]  # type: ignore[return-value]


def _conditions(node: dict[str, object]) -> list[dict[str, object]]:
    return node["conditions"]  # type: ignore[return-value]


def test_chinese_numbered_unpunctuated_requirement_is_not_dropped() -> None:
    text = "一 投标人须提供有效营业执照"
    result = _extract(
        {
            "title": "资格要求",
            "content": text,
            "source_references": [
                _reference("tender.pdf", "v1", 3, text, "tender.pdf:p3")
            ],
        }
    )

    requirements = _requirements(result)
    assert len(requirements) == 1
    assert "提供有效营业执照" in requirements[0]["description"]
    assert requirements[0]["mandatory"] is True


def test_heading_alone_does_not_become_a_mandatory_requirement() -> None:
    result = _extract({"title": "资格要求", "content": "一、资格要求"})

    assert _requirements(result) == []


def test_numbered_eligibility_clause_survives_but_material_heading_does_not() -> None:
    result = _extract(
        {
            "title": "资格要求",
            "content": (
                "一、投标人具有独立承担民事责任的能力\n"
                "二、营业执照提供要求"
            ),
        }
    )

    descriptions = [item["description"] for item in _requirements(result)]
    assert any(
        "投标人具有独立承担民事责任的能力" in text for text in descriptions
    )
    assert not any("营业执照提供要求" in text for text in descriptions)


def test_two_explicit_alternatives_remain_one_or_not_independent_hard_ands() -> None:
    text = (
        "资格要求：以下两项任选一项：\n"
        "1. 提供有效营业执照\n"
        "2. 提供有效法人登记证明"
    )
    result = _extract(
        {
            "title": "资格要求",
            "content": text,
            "source_references": [
                _reference("tender.pdf", "v1", 1, text, "tender.pdf:p1")
            ],
        }
    )

    requirements = _requirements(result)
    assert len(requirements) == 1
    requirement = requirements[0]
    assert requirement["mandatory"] is True
    assert "以下两项任选一项" in requirement["description"]
    assert "营业执照" in requirement["description"]
    assert "法人登记证明" in requirement["description"]
    logic = requirement["check_rule"]["condition_logic"]  # type: ignore[index]
    assert logic["op"] == "any"
    assert {
        condition["material_type"] for condition in _conditions(logic)
    } == {"business_license", "legal_entity_registration"}


def test_same_clause_in_distinct_documents_and_versions_is_not_deduplicated() -> None:
    clause = "投标人应提供有效营业执照。"
    result = _extract(
        {
            "title": "文件甲",
            "content": clause,
            "source_references": [
                _reference("doc-a", "v1", 1, clause, "doc-a:p1")
            ],
        },
        {
            "title": "文件乙",
            "content": clause,
            "source_references": [
                _reference("doc-b", "v1", 1, clause, "doc-b:p1")
            ],
        },
        {
            "title": "文件甲修订版",
            "content": clause,
            "source_references": [
                _reference("doc-a", "v2", 1, clause, "doc-a:p1")
            ],
        },
    )

    requirements = _requirements(result)
    assert len(requirements) == 3
    assert {
        (
            item["source_references"][0]["document_id"],
            item["source_references"][0]["source_version"],
        )
        for item in requirements
    } == {("doc-a", "v1"), ("doc-b", "v1"), ("doc-a", "v2")}


@pytest.mark.parametrize(
    ("first_document", "first_version", "second_document", "second_version"),
    [
        ("file-a", "v1", "file-b", "v1"),
        ("same-file", "v1", "same-file", "v2"),
    ],
)
def test_or_header_and_branches_are_not_joined_across_source_scopes(
    first_document: str,
    first_version: str,
    second_document: str,
    second_version: str,
) -> None:
    header = "以下两项任选一项："
    first_branch = "1. 投标人须提供有效营业执照"
    second_branch = "2. 投标人须提供银行资信证明"
    result = _extract(
        {
            "title": "资格要求",
            "content": f"{header}\n{first_branch}",
            "source_references": [
                _reference(
                    first_document,
                    first_version,
                    1,
                    header,
                    f"{first_document}:p1:l1",
                ),
                _reference(
                    first_document,
                    first_version,
                    1,
                    first_branch,
                    f"{first_document}:p1:l2",
                ),
            ],
        },
        {
            "title": "补充资格要求",
            "content": second_branch,
            "source_references": [
                _reference(
                    second_document,
                    second_version,
                    1,
                    second_branch,
                    f"{second_document}:p1:l1",
                )
            ],
        },
    )

    requirements = _requirements(result)
    assert requirements
    assert not any(
        "营业执照" in item["description"]
        and "银行资信证明" in item["description"]
        for item in requirements
    )
    assert not any(
        {
            (
                reference["document_id"],
                reference["source_version"],
            )
            for reference in item["source_references"]
        }
        >= {
            (first_document, first_version),
            (second_document, second_version),
        }
        for item in requirements
    )


@pytest.mark.parametrize(
    ("blank_lines", "table_noise_length"),
    [
        (0, 0),
        (100, 0),
        (0, 9),
        (0, 257),
        (100, 257),
    ],
)
def test_dropped_section_heading_still_separates_neighboring_or_branches(
    blank_lines: int,
    table_noise_length: int,
) -> None:
    table_noise = f"\n{'-' * table_noise_length}" if table_noise_length else ""
    content = (
        "一、主体资格\n"
        + "\n" * blank_lines
        + "以下两项任选一项：\n"
        "（1）提供有效营业执照"
        + table_noise
        + "\n二、财务资格\n"
        "（2）投标人须提供2025年度审计报告"
    )
    result = _extract(
        {
            "title": "资格要求",
            "content": content,
            "source_references": [
                _reference(
                    "tender.pdf",
                    "v1",
                    1,
                    content,
                    "tender.pdf:p1",
                )
            ],
        }
    )

    requirements = _requirements(result)
    license_requirement = next(
        item for item in requirements if "营业执照" in item["description"]
    )
    audit_requirement = next(
        item for item in requirements if "审计报告" in item["description"]
    )
    assert len(requirements) == 2
    assert "审计报告" not in license_requirement["description"]
    assert "营业执照" not in audit_requirement["description"]
    assert (
        license_requirement["check_rule"]["rule_ast"]["op"]  # type: ignore[index]
        == "manual_review"
    )
    assert (
        audit_requirement["check_rule"]["rule_ast"]["op"]  # type: ignore[index]
        == "manual_review"
    )


def test_bare_or_frame_groups_two_hard_clauses_under_a_generic_filename() -> None:
    content = (
        "以下两项任选一项：\n"
        "（1）投标人须提供有效营业执照\n"
        "（2）投标人须提供有效法人登记证明"
    )
    result = _extract(
        {
            "title": "采购文件.txt",
            "content": content,
            "source_references": [
                _reference("generic-doc", "v1", 1, content, "generic-doc:p1")
            ],
        }
    )

    requirements = _requirements(result)
    assert len(requirements) == 1
    requirement = requirements[0]
    logic = requirement["check_rule"]["condition_logic"]  # type: ignore[index]
    assert logic["op"] == "any"
    assert {
        condition["material_type"] for condition in _conditions(logic)
    } == {"business_license", "legal_entity_registration"}


def test_requirement_after_a_list_is_not_absorbed_into_the_list() -> None:
    result = _extract(
        {
            "title": "资格要求",
            "content": (
                "以下两项任选一项：\n"
                "（1）提供有效营业执照\n"
                "（2）提供有效法人登记证明\n"
                "二、投标人须依法缴纳税收。"
            ),
        }
    )

    descriptions = [item["description"] for item in _requirements(result)]
    tax = next(text for text in descriptions if "依法缴纳税收" in text)
    assert "法人登记证明" not in tax
    assert "投标人须依法缴纳税收" in tax


def test_incomplete_list_is_not_reported_complete_or_given_a_fake_leaf() -> None:
    text = "以下两项均须满足：\n（1）投标人须提供有效营业执照"
    result = _extract({"title": "资格要求", "content": text})

    requirements = _requirements(result)
    assert result["extraction_complete"] is False
    assert result["needs_human_review"] is True
    assert all("（2）" not in item["description"] for item in requirements)
    assert all("假设的第二项" not in item["description"] for item in requirements)


def test_dates_versions_and_clause_numbers_do_not_become_requirement_leaves() -> None:
    text = (
        "1.1 投标人须提供2025年审计报告。\n"
        "系统接口协议版本为1.2。\n"
        "递交截止日期为2026年10月1日。"
    )
    result = _extract({"title": "资格要求", "content": text})

    requirements = _requirements(result)
    assert len(requirements) == 1
    assert "2025年审计报告" in requirements[0]["description"]
    assert "接口协议版本为1.2" not in requirements[0]["description"]
    assert "递交截止日期" not in requirements[0]["description"]


def test_vague_following_conditions_does_not_invent_complete_and_tree() -> None:
    rule = build_local_requirement_rule(
        "投标人须满足以下条件：提供有效营业执照或法人登记证明。"
    )

    assert rule
    logic = rule["condition_logic"]
    assert logic["op"] == "any"
    assert rule["coverage_status"] == "partial"
    assert rule["rule_ast"]["op"] == "manual_review"


def test_outer_all_keeps_inner_or_as_a_nested_boolean_boundary() -> None:
    rule = build_local_requirement_rule(
        "投标人须提供有效营业执照或法人登记证明，并提供2025年度审计报告。"
    )

    assert rule
    logic = rule["condition_logic"]
    assert logic["op"] == "all"
    nested_or = next(
        condition for condition in _conditions(logic) if condition["op"] == "any"
    )
    assert {
        condition["material_type"] for condition in _conditions(nested_or)
    } == {"business_license", "legal_entity_registration"}
    audit_group = next(
        condition for condition in _conditions(logic) if condition is not nested_or
    )
    assert audit_group["op"] == "evidence"
    assert audit_group["material_type"] == "audit_report_key_pages"
    assert audit_group["year"] == 2025
    assert rule["rule_ast"]["op"] == "manual_review"


def test_cross_page_join_references_reconstruct_the_exact_source_fragments() -> None:
    first_fragment = "投标人须提供有效营业执照及"
    second_fragment = "相关登记证明。"
    result = _extract(
        {
            "title": "招标文件",
            "content": f"项目概况\n{first_fragment}\f{second_fragment}",
            "source_references": [
                _reference(
                    "tender.pdf",
                    "v7",
                    1,
                    first_fragment,
                    "tender.pdf:p1",
                ),
                _reference(
                    "tender.pdf",
                    "v7",
                    2,
                    second_fragment,
                    "tender.pdf:p2",
                ),
            ],
        }
    )

    requirement = next(
        item
        for item in _requirements(result)
        if "营业执照" in item["description"]
    )
    references = requirement["source_references"]
    assert requirement["description"] == f"{first_fragment} {second_fragment}"
    assert {
        (reference["page"], reference["quote"], reference["locator"])
        for reference in references
    } == {
        (1, first_fragment, "tender.pdf:p1:l2"),
        (2, second_fragment, "tender.pdf:p2:l1"),
    }
    assert all(
        reference["document_id"] == "tender.pdf"
        and reference["source_version"] == "v7"
        for reference in references
    )


@pytest.mark.asyncio
async def test_evidence_matching_keeps_different_people_in_human_review() -> None:
    source = (
        "拟任项目经理须具有信息系统项目管理师证书，且为投标人连续缴纳"
        "2026年3月至8月社会保险。"
    )
    requirement = _requirements(
        _extract(
            {
                "title": "资格要求",
                "content": source,
                "source_references": [
                    _reference(
                        "tender.pdf",
                        "v1",
                        1,
                        source,
                        "tender.pdf:p1:l1",
                    )
                ],
            }
        )
    )[0]
    rule = requirement["check_rule"]  # type: ignore[index]
    logic = rule["condition_logic"]
    assert logic["op"] == "all"
    same_person = _conditions(logic)[0]
    assert same_person["op"] == "sameperson"
    person_conditions = _conditions(_conditions(same_person)[0])
    date_range = next(
        condition for condition in person_conditions if condition["op"] == "date_range"
    )
    assert (date_range["start"], date_range["end"]) == ("2026-03", "2026-08")
    assert date_range["continuous"] is True

    request = SkillRequest.create(
        {
            "requirements": [requirement],
            "materials": [
                {
                    "material_id": "manager-certificate-a",
                    "material_type": "personnel_certificate",
                    "title": "甲的信息系统项目管理师证书",
                    "content": "持证人：甲",
                    "metadata": {"person_id": "person-a"},
                },
                {
                    "material_id": "social-security-b",
                    "material_type": "social_security_record",
                    "title": "乙的2026年3月至8月社保记录",
                    "content": "参保人：乙；月份：2026-03至2026-08",
                    "metadata": {
                        "person_id": "person-b",
                        "months": [
                            "2026-03",
                            "2026-04",
                            "2026-05",
                            "2026-06",
                            "2026-07",
                            "2026-08",
                        ],
                    },
                },
            ],
            "as_of": "2026-10-06",
        },
        skill_name="evidence-matching",
    )
    matching = await EvidenceMatchingSkill().execute(
        request,
        SkillContext(run_id="different-person-evidence", request=request),
    )

    assert matching.status == "success"
    match = matching.data["matches"][0]
    assert match["status"] == "human_review"
    assert match["status"] != "matched"
