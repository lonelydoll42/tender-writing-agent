from __future__ import annotations

from copy import deepcopy

import pytest

from qiaowenshu_agent.domain.document_relations import build_document_relations
from qiaowenshu_agent.domain.document_structure import build_document_structure


def _structure(
    text: str,
    *,
    version: str = "v1",
) -> dict:
    return _pages_structure([{"page_number": 1, "text": text}], version=version)


def _pages_structure(pages: list[dict], *, version: str = "v1") -> dict:
    return build_document_structure(
        pages,
        document_id="public-probe",
        source_version=version,
        source_checksum="public-test",
    )


def _groups(result: dict, op: str | None = None) -> list[dict]:
    return [
        node
        for node in result["condition_nodes"]
        if node["op"] in {"AND", "OR"} and (op is None or node["op"] == op)
    ]


def _relation_for_block(structure: dict, result: dict, raw_text: str) -> dict:
    block = next(item for item in structure["blocks"] if item["raw_text"] == raw_text)
    return next(
        relation
        for relation in result["block_relations"]
        if relation["block_id"] == block["block_id"]
    )


def _node_for_block(result: dict, block_id: str, *, op: str = "ATOM") -> dict:
    return next(
        node
        for node in result["condition_nodes"]
        if node["op"] == op and block_id in node["source_block_ids"]
    )


def _source_references(value):
    if isinstance(value, dict):
        if {"page", "char_start", "char_end", "quote", "locator"} <= value.keys():
            yield value
        for child in value.values():
            yield from _source_references(child)
    elif isinstance(value, list):
        for child in value:
            yield from _source_references(child)


def test_legacy_numbering_hints_do_not_invent_scope_groups() -> None:
    examples = [
        "第一章\n一、主体材料\n1.营业执照",
        "1.资格要求\n1.9营业执照\n1.10财务报表",
    ]
    for text in examples:
        result = build_document_relations(_structure(text))
        assert not [node for node in _groups(result) if node["status"] == "confirmed"]


@pytest.mark.parametrize(
    ("count", "marker"),
    [("两", "（"), ("2", "(")],
)
def test_inline_or_count_confirms_exact_members_and_leaves_following_item(
    count: str,
    marker: str,
) -> None:
    close = "）" if marker == "（" else ")"
    text = (
        f"以下{count}项任选一项："
        f"{marker}1{close}营业执照 "
        f"{marker}2{close}法人登记证明 "
        f"{marker}3{close}审计报告"
    )
    structure = _structure(text)
    result = build_document_relations(structure)

    group = next(
        node for node in _groups(result, "OR") if node["status"] == "confirmed"
    )
    assert len(group["children"]) == 2
    children = {node["node_id"]: node for node in result["condition_nodes"]}
    assert all(
        children[node_id]["status"] == "confirmed" for node_id in group["children"]
    )
    assert any(
        node["op"] == "ATOM"
        and "审计报告" in node["text"]
        and node["node_id"] in result["roots"]
        for node in result["condition_nodes"]
    )

    relation = _relation_for_block(structure, result, text)["scope_relations"][0]
    assert relation["status"] == "confirmed"
    assert "任选一项" in " ".join(
        reference["quote"] for reference in relation["operator_source_references"]
    )
    assert relation["boundary_source_references"]
    assert relation["trigger_text"] == text


@pytest.mark.parametrize("count", ["两", "2"])
def test_physical_or_with_chinese_or_arabic_quantity_confirms(count: str) -> None:
    text = f"以下{count}项任选一项：\n（1）营业执照。\n（2）法人登记证明。"
    result = build_document_relations(_structure(text))
    group = next(
        node for node in _groups(result, "OR") if node["status"] == "confirmed"
    )
    assert len(group["children"]) == 2


@pytest.mark.parametrize(
    "phrase",
    ["以下一至三项任选一项：", "以下1至3项任选一项：", "以下至少两项任选一项："],
)
def test_ambiguous_quantities_remain_candidates(phrase: str) -> None:
    text = f"{phrase}\n（1）营业执照。\n（2）法人登记证明。"
    result = build_document_relations(_structure(text))
    groups = _groups(result, "OR")
    assert groups
    assert all(group["status"] != "confirmed" for group in groups)
    assert any(
        relation["status"] == "candidate"
        for block in result["block_relations"]
        for relation in block["scope_relations"]
    )


def test_explicit_physical_and_promotes_only_scoped_bare_items() -> None:
    text = "以下两项均须满足：\n1.营业执照。\n2.法人登记证明。"
    structure = _structure(text)
    result = build_document_relations(structure)

    group = next(
        node for node in _groups(result, "AND") if node["status"] == "confirmed"
    )
    assert len(group["children"]) == 2
    nodes = {node["node_id"]: node for node in result["condition_nodes"]}
    assert all(nodes[node_id]["status"] == "confirmed" for node_id in group["children"])
    assert group["operator_relation"]["source_references"]
    assert group["scope_relation"]["source_references"]
    assert group["scope_relation"]["boundary_source_references"]


def test_short_bare_line_is_candidate_with_explicit_unknown_scope_record() -> None:
    text = "服务联系人清单一份"
    structure = _structure(text)
    result = build_document_relations(structure)
    block = structure["blocks"][0]
    atom = _node_for_block(result, block["block_id"])
    relation = _relation_for_block(structure, result, text)["scope_relations"][0]

    assert atom["status"] == "candidate"
    assert "completeness" in atom["reason"]
    assert relation["operator"] == "UNKNOWN"
    assert relation["status"] == "candidate"
    assert relation["trigger_text"] == text
    assert relation["source_references"][0]["quote"] == text


def test_explicit_submission_atom_confirms_without_group() -> None:
    text = "投标人应提交营业执照。"
    result = build_document_relations(_structure(text))
    assert result["condition_nodes"][0]["op"] == "ATOM"
    assert result["condition_nodes"][0]["status"] == "confirmed"
    assert result["condition_nodes"][0]["source_references"]


def test_missing_items_before_heading_and_number_gaps_are_not_confirmed() -> None:
    examples = [
        "以下两项任选一项：\n（1）营业执照。\n第二章 其他材料\n（2）审计报告。",
        "以下两项任选一项：\n（1）营业执照。\n（3）审计报告。",
    ]
    for text in examples:
        result = build_document_relations(_structure(text))
        assert _groups(result, "OR")
        assert all(group["status"] != "confirmed" for group in _groups(result, "OR"))
        assert any(
            relation["status"] == "candidate"
            for block in result["block_relations"]
            for relation in block["scope_relations"]
        )


def test_gap_after_explicit_count_is_not_treated_as_an_independent_next_item() -> None:
    text = "以下两项任选一项：\n（1）营业执照。\n（2）法人登记证明。\n（4）审计报告。"
    result = build_document_relations(_structure(text))
    group = next(
        node for node in _groups(result, "OR") if node["status"] != "confirmed"
    )
    assert "gap or duplicate" in group["scope_relation"]["reason"]


def test_adjacent_scope_frames_retain_multiple_antecedent_reason() -> None:
    text = (
        "以下两项任选一项：\n以下两项任选一项：\n（1）营业执照。\n（2）法人登记证明。"
    )
    result = build_document_relations(_structure(text))
    assert all(group["status"] != "confirmed" for group in _groups(result, "OR"))
    assert any(
        "multiple_scope_antecedents" in relation["reason"]
        for block in result["block_relations"]
        for relation in block["scope_relations"]
    )


def test_backward_reference_confirms_counted_and_scope_with_evidence() -> None:
    for count in ("两", "2"):
        text = (
            f"1. 提交营业执照。\n2. 提交法人登记证明。\n上述{count}项材料均须加盖公章。"
        )
        structure = _structure(text)
        result = build_document_relations(structure)
        group = next(
            node for node in _groups(result, "AND") if node["status"] == "confirmed"
        )
        assert len(group["children"]) == 2
        reference = next(
            item
            for item in result["references"]
            if item["source_block_id"] == structure["blocks"][-1]["block_id"]
        )
        assert reference["status"] == "confirmed"
        assert len(reference["target_block_ids"]) == 2
        assert any(
            "上述" in item["quote"] and "材料" in item["quote"]
            for item in reference["source_references"]
        )
        assert reference["candidate_source_references"] == []
        assert group["scope_relation"]["member_source_references"]


def test_unbounded_backward_reference_keeps_candidate_antecedents_and_scope() -> None:
    text = "1. 提交营业执照。\n2. 提交法人登记证明。\n上述材料均须加盖公章。"
    structure = _structure(text)
    result = build_document_relations(structure)
    reference = next(
        item
        for item in result["references"]
        if item["source_block_id"] == structure["blocks"][-1]["block_id"]
    )
    relation = _relation_for_block(
        structure,
        result,
        "上述材料均须加盖公章。",
    )["scope_relations"][0]

    assert reference["status"] == "candidate"
    assert any("上述材料" in ref["quote"] for ref in reference["source_references"])
    assert len(reference["candidate_source_references"]) >= 2
    assert relation["status"] == "candidate"
    assert relation["trigger_text"] == "上述材料均须加盖公章。"
    assert relation["target_block_ids"]


def test_ambiguous_anaphora_downgrades_atom_and_keeps_candidate_sources() -> None:
    text = "1. 提交营业执照。\n2. 提交法人登记证明。\n该材料应满足资格要求。"
    structure = _structure(text)
    result = build_document_relations(structure)
    source = structure["blocks"][-1]
    atom = _node_for_block(result, source["block_id"])
    reference = next(
        item
        for item in result["references"]
        if item["source_block_id"] == source["block_id"]
    )
    scope = _relation_for_block(
        structure,
        result,
        source["raw_text"],
    )["scope_relations"][0]

    assert atom["status"] == "candidate"
    assert reference["status"] == "candidate"
    assert any("该材料" in item["quote"] for item in reference["source_references"])
    assert reference["candidate_source_references"]
    assert scope["status"] == "candidate"
    assert scope["trigger_text"] == source["raw_text"]


def test_inline_and_splits_atoms_and_preserves_nested_direct_children() -> None:
    text = "须同时提交营业执照及（法人登记证明或审计报告）。"
    result = build_document_relations(_structure(text))
    groups = _groups(result)
    outer = next(node for node in groups if node["op"] == "AND")
    inner = next(node for node in groups if node["op"] == "OR")

    assert outer["status"] == "confirmed"
    assert len(outer["children"]) == 2
    child_nodes = {node["node_id"]: node for node in result["condition_nodes"]}
    assert child_nodes[outer["children"][1]]["op"] == "OR"
    assert child_nodes[outer["children"][1]]["node_id"] == inner["node_id"]
    assert inner["status"] == "confirmed"
    assert len(inner["children"]) == 2
    assert outer["operator_relation"]["source_references"]
    assert outer["scope_relation"]["boundary_source_references"]


def test_inline_simultaneous_submission_splits_two_material_atoms() -> None:
    text = "须同时提交营业执照及审计报告。"
    result = build_document_relations(_structure(text))
    group = next(
        node for node in _groups(result, "AND") if node["status"] == "confirmed"
    )
    children = {node["node_id"]: node for node in result["condition_nodes"]}

    assert len(group["children"]) == 2
    assert all(children[node_id]["op"] == "ATOM" for node_id in group["children"])
    assert {"营业执照", "审计报告"} <= {
        children[node_id]["text"].rstrip("。") for node_id in group["children"]
    }
    assert group["operator_relation"]["source_references"]
    assert group["scope_relation"]["boundary_source_references"]


@pytest.mark.parametrize("prefix", ["一、", "2. ", "A. "])
def test_numbered_title_is_not_promoted_to_an_inline_and_member(prefix: str) -> None:
    text = f"{prefix}必交资格材料：须同时提交营业执照及财务报表。"
    result = build_document_relations(_structure(text))
    group = next(
        node for node in _groups(result, "AND") if node["status"] == "confirmed"
    )
    nodes = {node["node_id"]: node for node in result["condition_nodes"]}
    children = [nodes[node_id] for node_id in group["children"]]

    assert len(children) == 2
    assert all(node["status"] == "confirmed" for node in children)
    assert {"营业执照", "财务报表"} <= {
        node["text"].rstrip("。") for node in children
    }
    assert not any(
        node["text"].strip() in {"一", "必交资格材料"}
        for node in nodes.values()
    )
    assert any(
        reference["quote"].endswith("必交资格材料：")
        for reference in group["scope_relation"]["scope_source_references"]
    )
    assert any(
        reference["quote"] == text
        for reference in group["scope_relation"]["boundary_source_references"]
    )


def test_alpha_or_scope_closes_before_a_separate_ambiguous_reference() -> None:
    text = (
        "满足下列任一条件即可：\n"
        "A. 提交营业执照复印件；\n"
        "B. 提交等效资质证明。\n"
        "该材料应加盖公章。"
    )
    structure = _structure(text)
    result = build_document_relations(structure)
    group = next(node for node in _groups(result, "OR"))
    following_block = structure["blocks"][-1]
    reference = next(
        item
        for item in result["references"]
        if item["source_block_id"] == following_block["block_id"]
    )

    assert group["status"] == "confirmed"
    assert len(group["children"]) == 2
    assert following_block["block_id"] not in group["source_block_ids"]
    assert "该材料" not in group["text"]
    scope = group["scope_relation"]
    assert any(
        item["quote"] == "。"
        for item in scope["terminal_boundary_source_references"]
    )
    assert any(
        item["quote"] == following_block["raw_text"]
        for item in scope["following_nonlist_boundary_source_references"]
    )
    assert reference["status"] == "candidate"
    reference_scope = next(
        relation
        for relation in _relation_for_block(
            structure,
            result,
            following_block["raw_text"],
        )["scope_relations"]
        if relation.get("relation_type") == "anaphoric_attribute_scope"
    )
    assert reference_scope["status"] == "candidate"
    assert reference_scope["target_node_ids"] == reference["target_node_ids"]
    assert {
        "该材料应加盖公章。",
        "满足下列任一条件即可：",
        "A. 提交营业执照复印件；",
        "B. 提交等效资质证明。",
    } <= {item["quote"] for item in reference_scope["source_references"]}
    attribute = _node_for_block(result, following_block["block_id"])
    assert any(
        parent["basis"] == "unresolved_anaphoric_attribute"
        and parent["status"] == "candidate"
        for parent in attribute["parent_relations"]
    )


def test_anaphoric_attribute_keeps_full_clause_and_candidate_and_context() -> None:
    text = (
        "须提交营业执照复印件及开户许可证复印件。\n"
        "该复印件必须加盖公章。"
    )
    structure = _structure(text)
    result = build_document_relations(structure)
    blocks = structure["blocks"]
    group = next(
        node for node in _groups(result, "AND") if node["status"] == "confirmed"
    )
    attribute_block = blocks[-1]
    reference = next(
        item
        for item in result["references"]
        if item["source_block_id"] == attribute_block["block_id"]
    )
    relation = next(
        item
        for item in _relation_for_block(
            structure,
            result,
            attribute_block["raw_text"],
        )["scope_relations"]
        if item.get("relation_type") == "anaphoric_attribute_scope"
    )
    attribute = _node_for_block(result, attribute_block["block_id"])

    assert group["status"] == "confirmed"
    assert reference["status"] == "candidate"
    assert any(
        item["quote"] == attribute_block["raw_text"]
        for item in reference["source_references"]
    )
    assert {
        block["raw_text"] for block in blocks
    } <= {item["quote"] for item in relation["source_references"]}
    assert relation["status"] == "candidate"
    assert len(relation["target_node_ids"]) == 2
    assert any(
        parent["basis"] == "unresolved_anaphoric_attribute"
        and parent["status"] == "candidate"
        and len(parent["target_node_ids"]) == 2
        for parent in attribute["parent_relations"]
    )


@pytest.mark.parametrize(
    "text",
    [
        "满足下列任一条件即可：\nA. 提交营业执照复印件；\nC. 提交等效资质证明。",
        (
            "满足下列任一条件即可：\nA. 提交营业执照复印件；\n"
            "B. 提交等效资质证明\n该材料应加盖公章。"
        ),
    ],
)
def test_incomplete_alpha_or_list_remains_reviewable(text: str) -> None:
    result = build_document_relations(_structure(text))

    assert _groups(result, "OR")
    assert all(group["status"] != "confirmed" for group in _groups(result, "OR"))
    assert any(
        relation["status"] == "candidate"
        for block in result["block_relations"]
        for relation in block["scope_relations"]
    )


@pytest.mark.parametrize(
    ("text", "operator_quote"),
    [
        ("须同时提交营业执照、审计报告。", "须同时提交"),
        ("须提交营业执照及审计报告。", "及"),
    ],
)
def test_operator_references_cite_only_explicit_and_evidence(
    text: str,
    operator_quote: str,
) -> None:
    result = build_document_relations(_structure(text))
    group = next(
        node for node in _groups(result, "AND") if node["status"] == "confirmed"
    )
    operator_quotes = [
        item["quote"] for item in group["operator_relation"]["source_references"]
    ]

    assert operator_quote in operator_quotes
    assert "、" not in operator_quotes
    if operator_quote == "及":
        assert "须提交" not in operator_quotes
        assert any(
            item["quote"] == "须提交"
            for item in group["scope_relation"]["requirement_source_references"]
        )


def test_dunhao_and_unary_modality_do_not_confirm_and() -> None:
    text = "须提交营业执照、审计报告。"
    structure = _structure(text)
    result = build_document_relations(structure)
    group = next(node for node in _groups(result, "AND"))
    scope = _relation_for_block(structure, result, text)["scope_relations"][0]

    assert group["status"] != "confirmed"
    assert group["operator_relation"]["status"] == "unresolved"
    assert group["operator_relation"]["source_references"] == []
    assert scope["operator"] == "UNRESOLVED"
    assert scope["operator_status"] == "unresolved"
    assert scope["scope_status"] == "confirmed"
    assert scope["operator_source_references"] == []
    assert group["source_references"]

    separate = build_document_relations(
        _structure("投标人须提交营业执照。\n投标人须提交审计报告。")
    )
    assert not _groups(separate, "AND")


def test_multiline_numbered_scope_with_operator_before_colon_does_not_raise() -> None:
    text = (
        "2.1 供应商应同时满足以下两项：\n"
        "（1）通过 OAuth2.0 或 OpenID Connect（OIDC）与现有身份系统完成身份对接；\n"
        "（2）不得以新建登录中心、迁移账号或其他方式替换采购人现有身份系统。"
    )
    result = build_document_relations(_structure(text))
    group = next(node for node in _groups(result, "AND"))
    nested_or = next(
        node
        for node in _groups(result, "OR")
        if "OAuth2.0 或 OpenID Connect" in node["text"]
    )

    assert group["operator_relation"]["status"] == "confirmed"
    assert group["scope_relation"]["status"] == "confirmed"
    assert len(group["children"]) == 2
    assert nested_or["node_id"] in group["children"]


@pytest.mark.parametrize(
    ("phrase", "negative_cue"),
    [
        ("无须同时满足以下两项", "无须"),
        ("无需同时满足以下两项", "无需"),
        ("不必同时满足以下两项", "不必"),
        ("均不须同时满足以下两项", "不须"),
        ("不得同时满足以下两项", "不得"),
    ],
)
def test_unsupported_negative_scope_never_confirms_positive_operator(
    phrase: str,
    negative_cue: str,
) -> None:
    text = f"{phrase}：\n（1）营业执照。\n（2）审计报告。"
    structure = _structure(text)
    result = build_document_relations(structure)
    relations = [
        relation
        for block in result["block_relations"]
        for relation in block["scope_relations"]
        if negative_cue in relation.get("trigger_text", "")
    ]

    assert relations
    assert not [
        group
        for group in _groups(result)
        if group["status"] == "confirmed"
    ]
    negative_blocks = [
        block
        for block in structure["blocks"]
        if negative_cue in block["raw_text"]
    ]
    assert negative_blocks
    assert all(
        _node_for_block(result, block["block_id"])["status"]
        in {"candidate", "unresolved"}
        for block in negative_blocks
    )
    for relation in relations:
        assert relation["status"] in {"candidate", "unresolved"}
        assert relation.get("operator") not in {"AND", "OR"}
        assert relation.get("operator_status") in {"candidate", "unresolved"}
        assert relation.get("scope_status") in {"candidate", "unresolved"}
        assert relation["operator_relation"]["status"] in {
            "candidate",
            "unresolved",
        }
        assert any(
            negative_cue in reference["quote"]
            for reference in relation["operator_source_references"]
        )
        assert "NOT" in relation["reason"] or "negative" in relation["reason"]


def test_numbered_reference_requires_matching_item_namespace() -> None:
    text = "1. 投标人应提交营业执照。\n依据第1条的要求办理。"
    structure = _structure(text)
    result = build_document_relations(structure)
    source_block = structure["blocks"][-1]
    atom = _node_for_block(result, source_block["block_id"])
    reference = next(
        relation
        for relation in result["references"]
        if relation["source_block_id"] == source_block["block_id"]
    )

    assert reference["status"] == "candidate"
    assert "namespace" in reference["reason"]
    assert any("第1条" in item["quote"] for item in reference["source_references"])
    assert any(
        item["quote"] == structure["blocks"][0]["raw_text"]
        for item in reference["candidate_source_references"]
    )
    assert atom["status"] == "candidate"


def test_explicit_local_item_reference_confirms_only_unique_target() -> None:
    unique_text = "1. 投标人应提交营业执照。\n根据本清单第1项办理。"
    unique_structure = _structure(unique_text)
    unique_result = build_document_relations(unique_structure)
    unique_source = unique_structure["blocks"][-1]
    unique_reference = next(
        relation
        for relation in unique_result["references"]
        if relation["source_block_id"] == unique_source["block_id"]
    )
    assert unique_reference["status"] == "confirmed"
    assert len(unique_reference["target_block_ids"]) == 1

    duplicate_text = (
        "第一章\n1. 投标人应提交营业执照。\n"
        "第二章\n1. 投标人应提交审计报告。\n"
        "根据本清单第1项办理。"
    )
    duplicate_structure = _structure(duplicate_text)
    duplicate_result = build_document_relations(duplicate_structure)
    duplicate_source = duplicate_structure["blocks"][-1]
    duplicate_reference = next(
        relation
        for relation in duplicate_result["references"]
        if relation["source_block_id"] == duplicate_source["block_id"]
    )
    assert duplicate_reference["status"] == "candidate"
    assert len(duplicate_reference["target_block_ids"]) == 2


@pytest.mark.parametrize(
    ("level", "metadata"),
    [
        ("root", False),
        ("root", True),
        ("page", False),
        ("page", True),
        ("block", False),
        ("block", True),
    ],
)
@pytest.mark.parametrize(
    "coordinate_status",
    ["section_relative_unverified", "unknown"],
)
def test_unverified_coordinate_status_at_every_source_layer_prevents_confirmation(
    level: str,
    metadata: bool,
    coordinate_status: str,
) -> None:
    structure = _structure("须同时提交营业执照及审计报告。")
    target = {
        "root": structure,
        "page": structure["pages"][0],
        "block": structure["blocks"][0],
    }[level]
    if metadata:
        existing = target.get("metadata")
        metadata_value = dict(existing) if isinstance(existing, dict) else {}
        metadata_value["source_coordinate_status"] = coordinate_status
        target["metadata"] = metadata_value
    else:
        target["source_coordinate_status"] = coordinate_status

    result = build_document_relations(structure)

    assert result["condition_nodes"]
    assert all(node["status"] == "unresolved" for node in result["condition_nodes"])
    assert not any(group["status"] == "confirmed" for group in _groups(result))


@pytest.mark.parametrize(
    "coordinate_status",
    [
        "unverified",
        "unmarked",
        "unresolved",
        "not_set",
        "not_available",
        "partial",
        "relative",
        "not-set",
        "NOT_AVAILABLE",
    ],
)
def test_coordinate_status_markers_match_pipeline_normalization(
    coordinate_status: str,
) -> None:
    structure = _structure("须同时提交营业执照及审计报告。")
    structure.setdefault("metadata", {})["source_coordinate_status"] = (
        coordinate_status
    )

    result = build_document_relations(structure)

    assert result["condition_nodes"]
    assert all(node["status"] == "unresolved" for node in result["condition_nodes"])
    assert not any(group["status"] == "confirmed" for group in _groups(result))


def test_explicit_unary_mandatory_branch_is_preserved() -> None:
    text = "必须提供以下材料：营业执照。"
    for value in (text, "必须提供以下材料：\n1.营业执照。"):
        structure = _structure(value)
        result = build_document_relations(structure)
        group = next(
            node
            for node in _groups(result, "AND")
            if node["status"] == "confirmed"
        )

        assert len(group["children"]) == 1
        assert group["operator_relation"]["kind"] == "unary_required_normalization"
        assert group["operator_relation"]["basis"] == "single_item_requirement"
        assert group["operator_source_references"] == []
        assert all(
            reference["source_role"] == "requirement"
            for reference in group["operator_relation"]["source_references"]
        )
        assert any(
            "必须提供" in reference["quote"]
            for reference in group["scope_relation"]["requirement_source_references"]
        )
        child = next(
            node
            for node in result["condition_nodes"]
            if node["node_id"] == group["children"][0]
        )
        assert child["op"] == "ATOM"
        assert child["status"] == "confirmed"


def test_unsupported_group_directive_is_an_opaque_candidate() -> None:
    text = "以下两组材料均须提交，但每组只需择一："
    structure = _structure(text)
    result = build_document_relations(structure)
    atom = result["condition_nodes"][0]
    relation = _relation_for_block(structure, result, text)["scope_relations"][0]

    assert atom["op"] == "ATOM"
    assert atom["role"] == "opaque"
    assert atom["status"] == "candidate"
    assert atom["text"] == text
    assert atom["source_references"][0]["quote"] == text
    assert not _groups(result)
    assert relation["status"] == "candidate"
    assert relation["trigger_text"] == text
    assert relation["source_references"]
    assert result["needs_human_review"] is True


def test_numbering_explanation_is_opaque_but_material_number_requirement_is_not(
) -> None:
    meta_text = "本条仅按材料编号理解，编号1.9至1.10表示相应资格要求。"
    meta_structure = _structure(meta_text)
    meta_result = build_document_relations(meta_structure)
    meta_atom = meta_result["condition_nodes"][0]

    assert meta_atom["role"] == "opaque"
    assert meta_atom["status"] == "candidate"
    assert meta_atom["text"] == meta_text
    assert meta_atom["source_references"][0]["quote"] == meta_text
    assert _relation_for_block(
        meta_structure,
        meta_result,
        meta_text,
    )["scope_relations"][0]["status"] == "candidate"

    requirement = build_document_relations(
        _structure("投标人应提交材料编号清单。")
    )
    assert requirement["condition_nodes"][0]["status"] == "confirmed"
    assert "role" not in requirement["condition_nodes"][0]


def test_visible_list_membership_is_typed_structural_not_logical_and() -> None:
    text = "材料项如下：\n1.须提交营业执照。\n2.须提交审计报告。"
    structure = _structure(text)
    result = build_document_relations(structure)
    header = structure["blocks"][0]
    header_node = _node_for_block(result, header["block_id"])

    relation = _relation_for_block(structure, result, header["raw_text"])
    membership = relation["list_membership_relations"][0]
    assert membership["status"] == "confirmed"
    assert membership["layer"] == "structural_list"
    assert membership["basis"] == "structural_list_membership"
    assert not _groups(result)

    for block in structure["blocks"][1:]:
        child = _node_for_block(result, block["block_id"])
        structural_parent = next(
            parent
            for parent in child["parent_relations"]
            if parent.get("layer") == "structural_list"
        )
        assert structural_parent["status"] == "confirmed"
        assert structural_parent["basis"] == "structural_list_membership"
        assert header_node["node_id"] in structural_parent["target_node_ids"]
        assert any(
            "材料项如下" in reference["quote"]
            for reference in structural_parent["source_references"]
        )


def test_structural_list_keeps_nested_members_without_confirming_logic() -> None:
    text = (
        "材料项如下：\n"
        "1. 须提交营业执照。\n"
        "2. 须提交财务报表。\n"
        "2.1 须提交审计报告。"
    )
    structure = _structure(text)
    result = build_document_relations(structure)
    header = structure["blocks"][0]
    members = structure["blocks"][1:]
    nested = structure["blocks"][3]

    membership = _relation_for_block(
        structure,
        result,
        header["raw_text"],
    )["list_membership_relations"][0]
    assert membership["status"] == "confirmed"
    assert membership["target_block_ids"] == [
        member["block_id"] for member in members
    ]
    scope = _relation_for_block(
        structure,
        result,
        header["raw_text"],
    )["scope_relations"][0]
    assert scope["operator"] == "UNRESOLVED"
    assert scope["status"] == "unresolved"
    assert scope["operator_status"] == "unresolved"
    assert scope["scope_status"] == "unresolved"
    assert scope["operator_source_references"] == []
    assert {
        header["raw_text"],
        *(member["raw_text"] for member in members),
    } <= {item["quote"] for item in scope["source_references"]}
    nested_node = _node_for_block(result, nested["block_id"])
    assert nested_node["status"] == "confirmed"
    assert any(
        relation["basis"] == "nested_numbering_parent_candidate"
        and relation["status"] == "candidate"
        and relation["target_block_ids"] == [members[1]["block_id"]]
        and {item["quote"] for item in relation["source_references"]}
        >= {members[1]["raw_text"], nested["raw_text"]}
        for relation in nested_node["parent_relations"]
    )
    assert not _groups(result)


@pytest.mark.parametrize(
    ("member_lines", "expected_missing"),
    [
        (["1. 营业执照。", "2. 财务报表。"], 1),
        (
            [
                "1. 营业执照。",
                "2. 财务报表。",
                "3. 服务联系人表。",
            ],
            0,
        ),
    ],
)
def test_k_of_n_keeps_scope_candidate_but_operator_unresolved(
    member_lines: list[str],
    expected_missing: int,
) -> None:
    text = "\n".join(
        ["以下三类中任取两类提交：", *member_lines]
    )
    structure = _structure(text)
    result = build_document_relations(structure)
    blocks = structure["blocks"]
    scope = _relation_for_block(
        structure,
        result,
        blocks[0]["raw_text"],
    )["scope_relations"][0]

    assert scope["operator"] == "UNRESOLVED"
    assert scope["status"] == "candidate"
    assert scope["operator_status"] == "unresolved"
    assert scope["scope_status"] == "candidate"
    assert scope["missing_member_count"] == expected_missing
    assert scope["operator_relation"]["status"] == "unresolved"
    assert (
        scope["operator_relation"]["cue_source_references"]
        == scope["operator_source_references"]
    )
    assert {
        block["raw_text"] for block in blocks
    } <= {item["quote"] for item in scope["source_references"]}
    assert {
        block["raw_text"] for block in blocks
    } <= {
        item["quote"]
        for item in scope["operator_relation"]["context_source_references"]
    }
    membership = _relation_for_block(
        structure,
        result,
        blocks[0]["raw_text"],
    )["list_membership_relations"][0]
    assert membership["status"] == "confirmed"
    assert membership["target_block_ids"] == [
        block["block_id"] for block in blocks[1:]
    ]
    first_member_node = _node_for_block(result, blocks[1]["block_id"])
    assert any(
        relation["basis"] == "unsupported_k_of_n_selection"
        and relation["status"] == "unresolved"
        and {item["quote"] for item in relation["source_references"]}
        >= {block["raw_text"] for block in blocks}
        for relation in first_member_node["parent_relations"]
    )


def test_page_crossing_needs_explicit_continuation_sentence() -> None:
    pages_without_note = [
        {"page_number": 1, "text": "以下两项任选一项：\n（1）营业执照。\n"},
        {"page_number": 2, "text": "（2）法人登记证明。\n"},
    ]
    pages_with_note = [
        {"page_number": 1, "text": "以下两项任选一项：\n（1）营业执照。\n"},
        {"page_number": 2, "text": "（续上页）\n（2）法人登记证明。\n"},
    ]
    without_note = build_document_relations(_pages_structure(pages_without_note))
    with_note = build_document_relations(_pages_structure(pages_with_note))

    assert all(group["status"] != "confirmed" for group in _groups(without_note, "OR"))
    assert any(group["status"] == "confirmed" for group in _groups(with_note, "OR"))


def test_unmarked_cross_page_candidate_is_recorded_without_extending_scope() -> None:
    pages = [
        {
            "page_number": 1,
            "text": "本页基本材料须同时提交：营业执照、审计报告。\n",
        },
        {"page_number": 2, "text": "项目联系人表一份。\n"},
    ]
    structure = _pages_structure(pages)
    result = build_document_relations(structure)
    group = next(
        node for node in _groups(result, "AND") if node["status"] == "confirmed"
    )
    following = structure["blocks"][-1]
    relation = next(
        item
        for item in _relation_for_block(
            structure,
            result,
            following["raw_text"],
        )["scope_relations"]
        if item.get("relation_type") == "cross_page_continuation_candidate"
    )
    candidate = _node_for_block(result, following["block_id"])

    assert following["block_id"] not in group["source_block_ids"]
    assert relation["status"] == "candidate"
    assert relation["target_node_ids"] == [group["node_id"]]
    assert {
        pages[0]["text"].strip(),
        following["raw_text"],
    } <= {item["quote"] for item in relation["source_references"]}
    assert any(
        parent["basis"] == "cross_page_continuation_candidate"
        and parent["status"] == "candidate"
        for parent in candidate["parent_relations"]
    )


def test_invalid_source_bounds_line_and_duplicate_ids_never_confirm() -> None:
    text = "投标人应提交营业执照。\n投标人应提供审计报告。"
    original = _structure(text)

    forged_end = deepcopy(original)
    first = forged_end["blocks"][0]
    first["source_references"][0]["char_end"] = 999
    first["source_span"]["end"] = 999
    assert (
        _node_for_block(
            build_document_relations(forged_end),
            first["block_id"],
        )["status"]
        == "unresolved"
    )

    wrong_line = deepcopy(original)
    wrong_line["blocks"][1]["line_number"] = 1
    assert (
        _node_for_block(
            build_document_relations(wrong_line),
            wrong_line["blocks"][1]["block_id"],
        )["status"]
        == "unresolved"
    )

    duplicate_id = deepcopy(original)
    duplicate_id["blocks"][1]["block_id"] = duplicate_id["blocks"][0]["block_id"]
    duplicate_result = build_document_relations(duplicate_id)
    assert all(
        node["status"] == "unresolved" for node in duplicate_result["condition_nodes"]
    )


def test_invalid_quote_duplicate_references_and_relative_coordinates() -> None:
    original = _structure("投标人应提交营业执照。")

    bad_quote = deepcopy(original)
    bad_quote["blocks"][0]["source_references"][0]["quote"] = "伪造原文"
    assert (
        build_document_relations(bad_quote)["condition_nodes"][0]["status"]
        == "unresolved"
    )

    duplicate_reference = deepcopy(original)
    references = duplicate_reference["blocks"][0]["source_references"]
    references.append(dict(references[0]))
    assert (
        build_document_relations(duplicate_reference)["condition_nodes"][0]["status"]
        == "unresolved"
    )

    wrong_locator = deepcopy(original)
    wrong_locator["blocks"][0]["source_references"][0]["locator"] = "p1:c0-999"
    assert (
        build_document_relations(wrong_locator)["condition_nodes"][0]["status"]
        == "unresolved"
    )

    relative = deepcopy(original)
    relative["blocks"][0]["source_span_scope"] = "section_relative"
    assert (
        build_document_relations(relative)["condition_nodes"][0]["status"]
        == "unresolved"
    )


def test_clipped_citations_keep_locator_offsets_page_and_quote_consistent() -> None:
    text = "前置说明。\n须同时提交营业执照及审计报告。"
    structure = _pages_structure([{"page_number": 3, "text": text}])
    result = build_document_relations(structure)
    page_text = {page["page_number"]: page["raw_text"] for page in structure["pages"]}
    references = list(_source_references(result))

    assert any(
        reference["char_start"] > structure["blocks"][1]["source_span"]["start"]
        for reference in references
    )
    for reference in references:
        start = reference["char_start"]
        end = reference["char_end"]
        assert reference["locator"] == f"p{reference['page']}:c{start}-{end}"
        assert page_text[reference["page"]][start:end] == reference["quote"]


def test_unknown_and_empty_inputs_remain_partial() -> None:
    result = build_document_relations(_structure("不得提交未经许可的材料。"))
    atom = result["condition_nodes"][0]
    assert atom["status"] == "candidate"
    assert "NOT" in atom["reason"]
    assert result["coverage_status"] == "partial"
    assert result["needs_human_review"] is True

    empty = build_document_relations(
        {
            "schema_version": "document-structure-v1",
            "document_id": "doc",
            "source_version": "v1",
            "pages": [],
            "blocks": [],
        }
    )
    assert empty["condition_nodes"] == []
    assert empty["roots"] == []
    assert empty["coverage_status"] == "partial"
    assert empty["needs_human_review"] is True


def test_parent_candidate_cites_both_blocks_and_cannot_change_scope() -> None:
    text = "以下两项均须满足：\n1.营业执照。\n2.审计报告。"
    structure = _structure(text)
    changed_parent = deepcopy(structure)
    first, second = changed_parent["blocks"][1:3]
    second["parent_block_id"] = first["block_id"]

    baseline = build_document_relations(structure)
    changed = build_document_relations(changed_parent)
    assert [
        relation["scope_relations"] for relation in baseline["block_relations"]
    ] == [relation["scope_relations"] for relation in changed["block_relations"]]
    parent = changed["block_relations"][2]["parent_relation"]
    assert parent["status"] == "candidate"
    assert {reference["quote"] for reference in parent["source_references"]} >= {
        first["raw_text"],
        second["raw_text"],
    }


def test_stable_ids_bind_source_version_and_amount_is_not_a_list_marker() -> None:
    text = "投标人应提交营业执照，金额1.50万元；表1.2仅作说明。"
    first = build_document_relations(_structure(text, version="v1"))
    rerun = build_document_relations(_structure(text, version="v1"))
    changed_version = build_document_relations(_structure(text, version="v2"))

    assert [node["node_id"] for node in first["condition_nodes"]] == [
        node["node_id"] for node in rerun["condition_nodes"]
    ]
    assert (
        first["condition_nodes"][0]["node_id"]
        != changed_version["condition_nodes"][0]["node_id"]
    )
    assert not _groups(first)


def test_amount_after_explicit_list_is_an_independent_candidate() -> None:
    text = (
        "以下两项均须提交：\n"
        "1.营业执照。\n"
        "2.审计报告。\n"
        "金额1.50万元。"
    )
    structure = _structure(text)
    result = build_document_relations(structure)
    group = next(
        node for node in _groups(result, "AND") if node["status"] == "confirmed"
    )
    amount_block = structure["blocks"][-1]
    amount_atom = _node_for_block(result, amount_block["block_id"])

    assert amount_block["raw_text"] == "金额1.50万元。"
    assert amount_atom["status"] == "candidate"
    assert amount_atom["node_id"] not in group["children"]
    assert amount_block["block_id"] not in group["source_block_ids"]
    assert len(group["children"]) == 2
