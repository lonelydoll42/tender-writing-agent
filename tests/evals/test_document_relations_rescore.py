from __future__ import annotations

import hashlib
import json
from copy import deepcopy
from typing import Any

import pytest

from scripts import run_document_relations_rescore as rescore


DOCUMENT_ID = "synthetic-rescore-document"
SOURCE_VERSION = "synthetic-rescore-v1"


def _oracle_ref(line: int, quote: str) -> dict[str, Any]:
    return {"page": 1, "line": line, "quote": quote}


def _product_ref(
    page_text: str,
    line_number: int,
    quote: str,
    *,
    document_id: str = DOCUMENT_ID,
    source_version: str = SOURCE_VERSION,
) -> dict[str, Any]:
    lines = page_text.split("\n")
    line_start = sum(len(line) + 1 for line in lines[: line_number - 1])
    start = line_start + lines[line_number - 1].index(quote)
    return {
        "document_id": document_id,
        "source_version": source_version,
        "page": 1,
        "line_number": line_number,
        "quote": quote,
        "char_start": start,
        "char_end": start + len(quote),
    }


def _source_context(page_text: str) -> dict[str, Any]:
    return {
        "document_id": DOCUMENT_ID,
        "source_version": SOURCE_VERSION,
        "pages": [page_text],
        "raw_input_sha256": "synthetic-only",
    }


def _case(
    conditions: list[dict[str, Any]],
    *,
    groups: list[dict[str, Any]] | None = None,
    needs_review: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    groups = groups or []
    confirmed_ids = [
        str(condition["id"])
        for condition in conditions
        if condition.get("certainty", "confirmed") == "confirmed"
    ]
    confirmed_groups = [
        group for group in groups if group.get("status") == "confirmed"
    ]
    confirmed_count = len(confirmed_ids)
    return {
        "case_id": "synthetic-rescore-contract",
        "conditions": conditions,
        "expect_confirmed": {"conditions": confirmed_ids, "relations": []},
        "groups": groups,
        "forbidden": [],
        "needs_review": needs_review or [],
        "denominators": {
            "confirmed_atom_count": confirmed_count,
            "condition_omission": confirmed_count,
            "wrong_merge_pairs": confirmed_count * (confirmed_count - 1) // 2,
            "wrong_split_atom_units": confirmed_count,
            "confirmed_scope_count": len(confirmed_groups),
            "scope_membership_decisions": confirmed_count * len(confirmed_groups),
        },
    }


def _atom(
    node_id: str,
    text: str,
    source: dict[str, Any],
    *,
    status: str = "confirmed",
) -> dict[str, Any]:
    return {
        "node_id": node_id,
        "op": "ATOM",
        "status": status,
        "text": text,
        "children": [],
        "source_references": [source],
    }


def _single_atom_fixture(
    *,
    page_text: str,
    expected_text: str,
    expected_quote: str,
    actual_text: str | None = None,
    actual_quote: str | None = None,
    actual_status: str = "confirmed",
    certainty: str = "confirmed",
) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any]]:
    lines = page_text.split("\n")
    expected = {
        "id": "A1",
        "text": expected_text,
        "certainty": certainty,
        "source": [_oracle_ref(1, expected_quote)],
    }
    case = _case(
        [expected],
        needs_review=(
            [
                {
                    "type": "condition",
                    "condition_id": "A1",
                    "status": "candidate",
                    "source": [_oracle_ref(1, expected_quote)],
                }
            ]
            if certainty == "candidate"
            else []
        ),
    )
    actual_quote = actual_quote if actual_quote is not None else expected_quote
    graph = {
        "schema": "document-relations-v1",
        "document_id": DOCUMENT_ID,
        "source_version": SOURCE_VERSION,
        "block_relations": [],
        "condition_nodes": [
            _atom(
                "node-A1",
                actual_text if actual_text is not None else actual_quote,
                _product_ref(lines[0], 1, actual_quote),
                status=actual_status,
            )
        ],
        "roots": ["node-A1"],
        "references": [],
    }
    return case, graph, _source_context(page_text)


def _score(
    case: dict[str, Any],
    graph: dict[str, Any],
    source_context: dict[str, Any] | None,
) -> dict[str, Any]:
    return rescore.score_case(
        case, graph, source_context, version="1.0.4"
    )


def _synthetic_offline_fixture(
    tmp_path,
) -> tuple[Any, dict[str, Any], dict[str, Any]]:
    legacy = rescore.load_evaluator("1.0.3")
    bundle = tmp_path / "synthetic-bundle"
    bundle.mkdir()
    oracle_cases: list[dict[str, Any]] = []
    product_cases: list[dict[str, Any]] = []

    for index in range(1, 15):
        case_id = f"case-{index:02d}"
        input_text = (
            "合成条款：必须提交项目经理执业资格证明"
            if index == 1
            else f"纯合成输入：{case_id}"
        )
        raw_input = input_text.encode("utf-8")
        (bundle / f"{case_id}.txt").write_bytes(raw_input)
        input_sha256 = hashlib.sha256(raw_input).hexdigest()

        if index == 1:
            oracle_case = _case(
                [
                    {
                        "id": "A1",
                        "text": input_text,
                        "certainty": "confirmed",
                        "source": [_oracle_ref(1, input_text)],
                    }
                ]
            )
        else:
            oracle_case = _case([])
        oracle_case["case_id"] = case_id
        oracle_case["input"] = f"{case_id}.txt"
        oracle_cases.append(oracle_case)

        runtime = {
            "registered_input_sha256": input_sha256,
            "intake_status": "success",
            "decomposition_status": "success",
        }
        product_case: dict[str, Any] = {
            "case_id": case_id,
            "runtime": runtime,
            "metrics": {
                "condition_omission": {"numerator": 0, "denominator": 1000}
            },
            "errors": [],
        }
        if index == 1:
            product_case.update(
                {
                    "status": "passed",
                    "execution_state": "executed",
                    "actual_graph": {
                        "schema": "document-relations-v1",
                        "document_id": DOCUMENT_ID,
                        "source_version": SOURCE_VERSION,
                        "block_relations": [],
                        "condition_nodes": [
                            _atom(
                                "node-A1",
                                input_text,
                                _product_ref(input_text, 1, input_text),
                            )
                        ],
                        "roots": ["node-A1"],
                        "references": [],
                    },
                    "source_context": {
                        **_source_context(input_text),
                        "page_separator": "\f",
                        "raw_input_sha256": input_sha256,
                        "registered_input_sha256": input_sha256,
                    },
                }
            )
        elif index == 2:
            product_case.update(
                {
                    "status": "failed",
                    "execution_state": "failed",
                    "reason": "synthetic runtime failure",
                }
            )
        else:
            product_case.update(
                {
                    "status": "not_run",
                    "execution_state": "not_run",
                    "reason": f"synthetic not-run case {case_id}",
                }
            )
        product_cases.append(product_case)

    freeze = {
        "bundle": bundle.resolve(),
        "oracle": {"cases": oracle_cases},
        "manifest_sha256": legacy.EXPECTED_V2_MANIFEST_SHA256,
        "bundle_fingerprint": legacy.EXPECTED_V2_FINGERPRINT,
        "checked_files": [{} for _ in range(legacy.EXPECTED_PAYLOAD_COUNT)],
    }
    report = {
        "schema": legacy.REPORT_SCHEMA,
        "base_commit": legacy.EXPECTED_BASE_COMMIT,
        "source_tree_sha256": "a" * 64,
        "source_tree_sha256_algorithm": rescore.LEGACY_SOURCE_TREE_ALGORITHM,
        "evaluator": {
            "version": "1.0.3",
            "path": "scripts/run_document_relations_eval.py",
            "sha256": rescore.LEGACY_EVALUATOR_SHA256,
        },
        "freeze": {
            "v2_manifest_sha256": legacy.EXPECTED_V2_MANIFEST_SHA256,
            "v2_bundle_fingerprint": legacy.EXPECTED_V2_FINGERPRINT,
            "payload_files": legacy.EXPECTED_PAYLOAD_COUNT,
        },
        "summary": {"case_count": 14},
        "cases": product_cases,
    }
    return bundle, freeze, report


def _save_synthetic_report(path, report: dict[str, Any]) -> str:
    raw = json.dumps(
        report, ensure_ascii=False, separators=(",", ":"), allow_nan=False
    ).encode("utf-8")
    path.write_bytes(raw)
    return hashlib.sha256(raw).hexdigest()


def _guard_offline_loader(monkeypatch, freeze: dict[str, Any]) -> dict[str, Any]:
    load_evaluator = rescore.load_evaluator
    calls: dict[str, list[Any]] = {"verify_bundle": [], "runtime": []}

    def forbidden_runtime(*args, **kwargs):
        calls["runtime"].append((args, kwargs))
        raise AssertionError("offline rescore must not invoke runtime components")

    def guarded_loader(version: str):
        evaluator = load_evaluator(version)

        def fake_verify_bundle(bundle):
            calls["verify_bundle"].append(bundle)
            return deepcopy(freeze)

        evaluator.verify_bundle = fake_verify_bundle
        for name in (
            "_run_input",
            "ProjectFileRegistry",
            "AgentRuntime",
            "build_default_registry",
        ):
            if hasattr(evaluator, name):
                setattr(evaluator, name, forbidden_runtime)
        return evaluator

    monkeypatch.setattr(rescore, "load_evaluator", guarded_loader)
    return calls


def _rescore_synthetic_report(
    bundle,
    report_path,
    report_sha256: str,
    *,
    version: str = "1.0.4",
) -> dict[str, Any]:
    return rescore.rescore_report(
        bundle,
        report_path,
        version=version,
        expected_report_sha256=report_sha256,
        main_reviewer_authorized=True,
    )


def test_evaluator_versions_are_isolated_and_keep_the_frozen_old_matcher() -> None:
    old = rescore.load_evaluator("1.0.3")
    new = rescore.load_evaluator("1.0.4")

    assert old is not new
    assert old.EVALUATOR_VERSION == "1.0.3"
    assert new.EVALUATOR_VERSION == "1.0.4"
    assert rescore.EVALUATOR_VERSION == "1.0.4"


def test_valid_full_literal_recovers_a_low_similarity_human_rewrite() -> None:
    raw_quote = "本项目要求提交项目经理注册执业证书复印件作为资格审查材料"
    case, graph, context = _single_atom_fixture(
        page_text=raw_quote,
        expected_text="投标人须提供拟派负责人的有效执业资格证明文件",
        expected_quote=raw_quote,
    )
    old = rescore.load_evaluator("1.0.3")
    new = rescore.load_evaluator("1.0.4")
    node = graph["condition_nodes"][0]

    assert old._text_similarity(case["conditions"][0]["text"], node["text"]) < 0.35
    assert old._atom_candidates(case["conditions"][0], [node]) == []

    result = _score(case, graph, context)

    assert result["status"] == "passed"
    assert result["matched_atom_ids"] == ["A1"]
    assert result["actual_source_validation"]["invalid_references"] == 0
    normalized = new._validate_graph_source_references(graph, context)[
        "normalized_graph"
    ]
    assert [
        node_id
        for _, node_id in new._atom_candidates(
            case["conditions"][0], normalized["condition_nodes"]
        )
    ] == ["node-A1"]


def test_legacy_high_similarity_atom_mapping_remains_compatible() -> None:
    quote = "必须提交完整的纳税证明材料"
    case, graph, context = _single_atom_fixture(
        page_text=quote,
        expected_text=quote,
        expected_quote=quote,
    )
    old = rescore.load_evaluator("1.0.3")
    node = graph["condition_nodes"][0]

    assert old._atom_candidates(case["conditions"][0], [node])
    result = _score(case, graph, context)

    assert result["status"] == "passed"
    assert result["matched_atom_ids"] == ["A1"]


@pytest.mark.parametrize(
    "tampering",
    [
        {"quote": "伪造的来源引文"},
        {"char_start": 1},
        {"document_id": "other-document"},
        {"source_version": "other-version"},
        {"line_number": 2},
    ],
)
def test_unverified_raw_source_cannot_authorize_literal_mapping(
    tampering: dict[str, Any],
) -> None:
    raw_quote = "本项目要求提交项目经理注册执业证书复印件作为资格审查材料"
    case, graph, context = _single_atom_fixture(
        page_text=raw_quote,
        expected_text="投标人须提供拟派负责人的有效执业资格证明文件",
        expected_quote=raw_quote,
    )
    reference = graph["condition_nodes"][0]["source_references"][0]
    reference.update(tampering)
    reference["_raw_coordinate_valid"] = True

    result = _score(case, graph, context)

    assert result["status"] == "failed"
    assert result["matched_atom_ids"] == []
    assert result["actual_source_validation"]["invalid_references"] >= 1
    assert result["metrics"]["source_invalid"]["numerator"] >= 1


def test_valid_reference_on_another_line_does_not_map() -> None:
    page_text = "本项目要求提交项目经理注册执业证书复印件作为资格审查材料\n" \
        "本项目要求提交项目经理注册执业证书复印件作为资格审查材料"
    quote = page_text.split("\n")[1]
    case, graph, context = _single_atom_fixture(
        page_text=page_text,
        expected_text="投标人须提供拟派负责人的有效执业资格证明文件",
        expected_quote=quote,
    )
    graph["condition_nodes"][0]["source_references"] = [
        _product_ref(page_text, 2, quote)
    ]

    result = _score(case, graph, context)

    assert result["actual_source_validation"]["invalid_references"] == 0
    assert result["matched_atom_ids"] == []
    assert result["status"] == "failed"


@pytest.mark.parametrize(
    ("oracle_quote", "product_quote"),
    [
        ("项目预算为1.9万元", "项目预算为1.10万元"),
        ("服务年份为2025年", "服务年份为2026年"),
        ("须提交3份材料", "须提交4份材料"),
        ("必须提交安全证明", "无需提交安全证明"),
    ],
)
def test_similar_literals_with_different_numbers_years_or_negation_do_not_map(
    oracle_quote: str, product_quote: str
) -> None:
    page_text = f"{oracle_quote}；{product_quote}"
    expected_start = page_text.index(oracle_quote)
    actual_start = page_text.index(product_quote)
    condition = {
        "id": "A1",
        "text": oracle_quote,
        "certainty": "confirmed",
        "source": [_oracle_ref(1, oracle_quote)],
    }
    case = _case([condition])
    graph = {
        "schema": "document-relations-v1",
        "document_id": DOCUMENT_ID,
        "source_version": SOURCE_VERSION,
        "block_relations": [],
        "condition_nodes": [
            _atom(
                "node-A1",
                product_quote,
                {
                    **_product_ref(page_text, 1, product_quote),
                    "char_start": actual_start,
                    "char_end": actual_start + len(product_quote),
                },
            )
        ],
        "roots": ["node-A1"],
        "references": [],
    }

    assert expected_start != actual_start
    result = _score(case, graph, _source_context(page_text))

    assert result["actual_source_validation"]["invalid_references"] == 0
    assert result["matched_atom_ids"] == []
    assert result["status"] == "failed"


def test_four_similar_atoms_on_one_line_do_not_cross_map_by_containment() -> None:
    page_text = "编号1.1对应甲项目；编号1.10对应乙项目；截至2025年；截至2025年后"
    oracle_texts = [
        "首个项目的报价编号必须符合要求",
        "第十个项目的报价编号必须符合要求",
        "审查截止日期落在二〇二五年度",
        "审查截止日期晚于二〇二五年度",
    ]
    quotes = ["编号1.1", "编号1.10", "截至2025年", "截至2025年后"]
    conditions = [
        {
            "id": f"A{index}",
            "text": oracle_text,
            "certainty": "confirmed",
            "source": [_oracle_ref(1, quote)],
        }
        for index, (oracle_text, quote) in enumerate(
            zip(oracle_texts, quotes, strict=True), start=1
        )
    ]
    nodes = [
        _atom(
            f"n{index}",
            quote,
            _product_ref(page_text, 1, quote),
        )
        for index, quote in enumerate(quotes, start=1)
    ]
    case = _case(conditions)
    graph = {"condition_nodes": nodes, "block_relations": [], "references": []}
    context = _source_context(page_text)
    old = rescore.load_evaluator("1.0.3")
    new = rescore.load_evaluator("1.0.4")
    normalized = new._validate_graph_source_references(graph, context)
    assert normalized["invalid_references"] == 0
    normalized_nodes = normalized["normalized_graph"]["condition_nodes"]

    assert all(
        old._text_similarity(condition["text"], node["text"]) < 0.35
        for condition in conditions
        for node in nodes
    )
    expected_node_ids = ["n1", "n2", "n3", "n4"]
    for condition, expected_node_id in zip(
        conditions, expected_node_ids, strict=True
    ):
        assert [
            node_id
            for _, node_id in new._atom_candidates(condition, normalized_nodes)
        ] == [expected_node_id]

    result = _score(case, graph, context)

    assert result["status"] == "passed"
    assert result["matched_atom_ids"] == ["A1", "A2", "A3", "A4"]
    assert result["metrics"]["wrong_merge_pairs"]["numerator"] == 0
    assert result["metrics"]["wrong_split_atom_units"]["numerator"] == 0


def test_oracle_quote_rejects_product_quote_with_extra_modifiers() -> None:
    oracle_quote = "项目联系人表"
    product_quote = "项目联系人表（须由法定代表人签字并注明日期）"
    page_text = f"应提交{product_quote}"
    case, graph, context = _single_atom_fixture(
        page_text=page_text,
        expected_text="投标方须按清单提交联系人信息用于资格审查",
        expected_quote=oracle_quote,
        actual_text=product_quote,
        actual_quote=product_quote,
    )
    old = rescore.load_evaluator("1.0.3")
    node = graph["condition_nodes"][0]

    assert old._text_similarity(case["conditions"][0]["text"], node["text"]) < 0.35
    assert old._atom_candidates(case["conditions"][0], [node]) == []

    result = _score(case, graph, context)

    assert result["actual_source_validation"]["invalid_references"] == 0
    assert result["matched_atom_ids"] == []
    assert result["status"] == "failed"


def test_literal_mapping_does_not_promote_a_candidate_to_confirmed() -> None:
    raw_quote = "本项目要求提交项目经理注册执业证书复印件作为资格审查材料"
    case, graph, context = _single_atom_fixture(
        page_text=raw_quote,
        expected_text="投标人须提供拟派负责人的有效执业资格证明文件",
        expected_quote=raw_quote,
        certainty="candidate",
        actual_status="confirmed",
    )
    original_graph = deepcopy(graph)

    result = _score(case, graph, context)

    assert result["status"] == "failed"
    assert result["metrics"]["review_handling"]["numerator"] == 1
    assert graph == original_graph


def test_low_similarity_literal_mapping_requires_source_context() -> None:
    raw_quote = "本项目要求提交项目经理注册执业证书复印件作为资格审查材料"
    case, graph, _ = _single_atom_fixture(
        page_text=raw_quote,
        expected_text="投标人须提供拟派负责人的有效执业资格证明文件",
        expected_quote=raw_quote,
    )

    result = _score(case, graph, None)

    assert result["matched_atom_ids"] == []
    assert result["status"] == "failed"


def test_one_node_cannot_cover_two_oracle_atoms_or_hide_a_split() -> None:
    quote = "本项目要求提交项目经理注册执业证书复印件作为资格审查材料"
    page_text = quote
    shared_ref = _product_ref(page_text, 1, quote)
    shared_source = [_oracle_ref(1, quote)]
    merged_case = _case(
        [
            {
                "id": "A1",
                "text": "提交负责人的职业资格证明文件",
                "certainty": "confirmed",
                "source": shared_source,
            },
            {
                "id": "A2",
                "text": "提供项目经理执业注册材料",
                "certainty": "confirmed",
                "source": shared_source,
            },
        ]
    )
    merged_graph = {
        "condition_nodes": [_atom("merged", quote, shared_ref)],
        "block_relations": [],
        "references": [],
    }

    merged = _score(merged_case, merged_graph, _source_context(page_text))

    assert merged["status"] == "failed"
    assert merged["metrics"]["wrong_merge_pairs"]["numerator"] == 1

    split_case = _case(
        [
            {
                "id": "A1",
                "text": "投标人须提供拟派负责人的有效执业资格证明文件",
                "certainty": "confirmed",
                "source": shared_source,
            }
        ]
    )
    split_graph = {
        "condition_nodes": [
            _atom("copy-1", quote, deepcopy(shared_ref)),
            _atom("copy-2", quote, deepcopy(shared_ref)),
        ],
        "block_relations": [],
        "references": [],
    }

    split = _score(split_case, split_graph, _source_context(page_text))

    assert split["status"] == "failed"
    assert split["metrics"]["wrong_split_atom_units"]["numerator"] == 1


def test_atom_literal_match_does_not_satisfy_a_wrong_or_group_operator() -> None:
    page_text = "提交甲类证书或乙类证书"
    ref_a = _product_ref(page_text, 1, "甲类证书")
    ref_b = _product_ref(page_text, 1, "乙类证书")
    cue_ref = _product_ref(page_text, 1, "或")
    case = _case(
        [
            {
                "id": "A1",
                "text": "参与方提交类别甲的资格证明文件",
                "certainty": "confirmed",
                "source": [_oracle_ref(1, "甲类证书")],
            },
            {
                "id": "A2",
                "text": "递交类别乙的专业资质材料",
                "certainty": "confirmed",
                "source": [_oracle_ref(1, "乙类证书")],
            },
        ],
        groups=[
            {
                "id": "S1",
                "status": "confirmed",
                "operator": "OR",
                "members": ["A1", "A2"],
                "boundary_basis": [_oracle_ref(1, "或")],
            }
        ],
    )
    graph = {
        "condition_nodes": [
            _atom("n1", "甲类证书", ref_a),
            _atom("n2", "乙类证书", ref_b),
            {
                "node_id": "g1",
                "op": "AND",
                "status": "confirmed",
                "text": "提交甲类证书或乙类证书",
                "children": ["n1", "n2"],
                "source_references": [cue_ref],
                "operator_relation": {
                    "status": "confirmed",
                    "source_references": [cue_ref],
                },
                "scope_relation": {
                    "status": "confirmed",
                    "target_node_ids": ["n1", "n2"],
                    "source_references": [cue_ref],
                    "boundary_source_references": [cue_ref],
                },
            },
        ],
        "block_relations": [],
        "references": [],
    }

    result = _score(case, graph, _source_context(page_text))

    assert result["matched_atom_ids"] == ["A1", "A2"]
    assert result["status"] == "failed"
    assert result["metrics"]["operator_group_structure"]["numerator"] == 1


def test_flattening_an_and_of_two_or_groups_fails_direct_child_structure() -> None:
    page_text = "甲证书或乙证书\n丙证明或丁证明\n上述两组均须分别满足"
    atom_specs = [
        ("A1", "甲证书", 1),
        ("A2", "乙证书", 1),
        ("A3", "丙证明", 2),
        ("A4", "丁证明", 2),
    ]
    conditions = [
        {
            "id": atom_id,
            "text": quote,
            "certainty": "confirmed",
            "source": [_oracle_ref(line, quote)],
        }
        for atom_id, quote, line in atom_specs
    ]
    groups = [
        {
            "id": "S1",
            "status": "confirmed",
            "operator": "OR",
            "members": ["A1", "A2"],
            "boundary_basis": [_oracle_ref(1, "或")],
        },
        {
            "id": "S2",
            "status": "confirmed",
            "operator": "OR",
            "members": ["A3", "A4"],
            "boundary_basis": [_oracle_ref(2, "或")],
        },
        {
            "id": "S0",
            "status": "confirmed",
            "operator": "AND",
            "members": ["S1", "S2"],
            "boundary_basis": [_oracle_ref(3, "均须")],
        },
    ]
    case = _case(conditions, groups=groups)
    nodes = [
        _atom(
            f"n{index}",
            quote,
            _product_ref(page_text, line, quote),
        )
        for index, (_, quote, line) in enumerate(atom_specs, start=1)
    ]

    def group_node(
        node_id: str, operator: str, children: list[str], line: int, cue: str
    ) -> dict[str, Any]:
        cue_ref = _product_ref(page_text, line, cue)
        return {
            "node_id": node_id,
            "op": operator,
            "status": "confirmed",
            "text": cue,
            "children": list(children),
            "source_references": [cue_ref],
            "operator_relation": {
                "status": "confirmed",
                "source_references": [cue_ref],
            },
            "scope_relation": {
                "status": "confirmed",
                "target_node_ids": list(children),
                "source_references": [cue_ref],
                "boundary_source_references": [cue_ref],
            },
        }

    group_or_1 = group_node("g1", "OR", ["n1", "n2"], 1, "或")
    group_or_2 = group_node("g2", "OR", ["n3", "n4"], 2, "或")
    root = group_node("g0", "AND", ["g1", "g2"], 3, "均须")
    graph = {
        "condition_nodes": [root, group_or_1, group_or_2, *nodes],
        "block_relations": [],
        "references": [],
    }
    context = _source_context(page_text)

    assert _score(case, graph, context)["status"] == "passed"

    flattened = deepcopy(graph)
    flat_root = next(
        node for node in flattened["condition_nodes"] if node["node_id"] == "g0"
    )
    flat_root["children"] = ["n1", "n2", "n3", "n4"]
    flat_root["scope_relation"]["target_node_ids"] = ["n1", "n2", "n3", "n4"]

    result = _score(case, flattened, context)

    assert result["matched_atom_ids"] == ["A1", "A2", "A3", "A4"]
    assert result["matched_group_ids"] == ["S1", "S2"]
    assert result["status"] == "failed"
    assert result["metrics"]["operator_group_structure"] == {
        "numerator": 1,
        "denominator": 3,
    }
    assert any(
        error["metric"] == "group_structure"
        and error["expected_group_id"] == "S0"
        for error in result["errors"]
    )


def test_rescore_requires_explicit_reviewer_authorization(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, _, _ = _synthetic_offline_fixture(tmp_path)

    def forbidden_loader(version: str):
        pytest.fail(f"evaluator loaded before authorization: {version}")

    monkeypatch.setattr(rescore, "load_evaluator", forbidden_loader)

    with pytest.raises(PermissionError, match="requires authorization"):
        rescore.rescore_report(
            bundle,
            tmp_path / "missing-report.json",
            version="1.0.4",
            expected_report_sha256="0" * 64,
            main_reviewer_authorized=False,
        )


def test_cli_requires_authorization_before_reading_inputs(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    def forbidden_rescore(*args, **kwargs):
        pytest.fail("CLI attempted rescore without reviewer authorization")

    monkeypatch.setattr(rescore, "rescore_report", forbidden_rescore)

    with pytest.raises(SystemExit) as error:
        rescore.main(
            [
                "--bundle",
                str(tmp_path / "missing-bundle"),
                "--product-report",
                str(tmp_path / "missing-report.json"),
                "--expected-report-sha256",
                "0" * 64,
                "--version",
                "1.0.4",
                "--output",
                str(tmp_path / "output.json"),
            ]
        )

    assert error.value.code == 2


def test_product_report_sha_mismatch_is_rejected_before_bundle_verification(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, freeze, report = _synthetic_offline_fixture(tmp_path)
    report_path = tmp_path / "synthetic-product-report.json"
    actual_sha256 = _save_synthetic_report(report_path, report)
    calls = _guard_offline_loader(monkeypatch, freeze)

    assert actual_sha256 != "0" * 64
    with pytest.raises(ValueError, match="SHA-256 does not match"):
        _rescore_synthetic_report(bundle, report_path, "0" * 64)

    assert calls["verify_bundle"] == []
    assert calls["runtime"] == []


@pytest.mark.parametrize(
    ("section", "key", "value"),
    [
        (None, "schema", "unknown-product-report-schema"),
        ("freeze", "v2_manifest_sha256", "b" * 64),
        ("freeze", "v2_bundle_fingerprint", "c" * 64),
        ("evaluator", "sha256", "d" * 64),
    ],
)
def test_frozen_report_identity_mismatches_are_rejected(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    section: str | None,
    key: str,
    value: str,
) -> None:
    bundle, freeze, report = _synthetic_offline_fixture(tmp_path)
    if section is None:
        report[key] = value
    else:
        report[section][key] = value
    report_path = tmp_path / "synthetic-product-report.json"
    report_sha256 = _save_synthetic_report(report_path, report)
    calls = _guard_offline_loader(monkeypatch, freeze)

    with pytest.raises(ValueError):
        _rescore_synthetic_report(bundle, report_path, report_sha256)

    assert calls["verify_bundle"] == []
    assert calls["runtime"] == []


@pytest.mark.parametrize("case_id_change", ["duplicate", "missing"])
def test_duplicate_or_missing_product_cases_are_rejected(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    case_id_change: str,
) -> None:
    bundle, freeze, report = _synthetic_offline_fixture(tmp_path)
    if case_id_change == "duplicate":
        report["cases"][-1]["case_id"] = report["cases"][0]["case_id"]
    else:
        report["cases"][-1]["case_id"] = "case-99"
    report_path = tmp_path / "synthetic-product-report.json"
    report_sha256 = _save_synthetic_report(report_path, report)
    calls = _guard_offline_loader(monkeypatch, freeze)

    with pytest.raises(ValueError):
        _rescore_synthetic_report(bundle, report_path, report_sha256)

    assert calls["verify_bundle"] == []
    assert calls["runtime"] == []


@pytest.mark.parametrize(
    ("tampering", "expected_error"),
    [
        ("graph_document_id", "identity mismatch"),
        ("graph_source_version", "identity mismatch"),
        ("graph_schema", "unsupported actual graph schema"),
        ("context_document_id", "identity mismatch"),
        ("context_source_version", "identity mismatch"),
        ("context_pages", "pages do not match"),
        ("context_raw_checksum", "input checksum mismatch"),
        ("context_registered_checksum", "input checksum mismatch"),
        ("runtime_checksum", "runtime input checksum mismatch"),
    ],
)
def test_replay_graph_context_and_runtime_identity_are_validated(
    tmp_path,
    monkeypatch: pytest.MonkeyPatch,
    tampering: str,
    expected_error: str,
) -> None:
    bundle, freeze, report = _synthetic_offline_fixture(tmp_path)
    executed = report["cases"][0]
    if tampering == "graph_document_id":
        executed["actual_graph"]["document_id"] = "other-document"
    elif tampering == "graph_source_version":
        executed["actual_graph"]["source_version"] = "other-source-version"
    elif tampering == "graph_schema":
        executed["actual_graph"]["schema"] = "unknown-graph-schema"
    elif tampering == "context_document_id":
        executed["source_context"]["document_id"] = "other-document"
    elif tampering == "context_source_version":
        executed["source_context"]["source_version"] = "other-source-version"
    elif tampering == "context_pages":
        executed["source_context"]["pages"] = ["different synthetic page"]
    elif tampering == "context_raw_checksum":
        executed["source_context"]["raw_input_sha256"] = "e" * 64
    elif tampering == "context_registered_checksum":
        executed["source_context"]["registered_input_sha256"] = "f" * 64
    else:
        executed["runtime"]["registered_input_sha256"] = "0" * 64

    report_path = tmp_path / "synthetic-product-report.json"
    report_sha256 = _save_synthetic_report(report_path, report)
    calls = _guard_offline_loader(monkeypatch, freeze)

    with pytest.raises(ValueError, match=expected_error):
        _rescore_synthetic_report(bundle, report_path, report_sha256)

    assert len(calls["verify_bundle"]) == 1
    assert calls["runtime"] == []


def test_duplicate_actual_node_ids_are_rejected(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, freeze, report = _synthetic_offline_fixture(tmp_path)
    nodes = report["cases"][0]["actual_graph"]["condition_nodes"]
    nodes.append(deepcopy(nodes[0]))
    report_path = tmp_path / "synthetic-product-report.json"
    report_sha256 = _save_synthetic_report(report_path, report)
    calls = _guard_offline_loader(monkeypatch, freeze)

    with pytest.raises(ValueError, match="duplicate actual graph node_id"):
        _rescore_synthetic_report(bundle, report_path, report_sha256)

    assert len(calls["verify_bundle"]) == 1
    assert calls["runtime"] == []


def test_both_versions_preserve_synthetic_inputs_and_count_only_executions(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    bundle, freeze, report = _synthetic_offline_fixture(tmp_path)
    report_path = tmp_path / "synthetic-product-report.json"
    report_sha256 = _save_synthetic_report(report_path, report)
    original_report_bytes = report_path.read_bytes()
    original_graph = deepcopy(report["cases"][0]["actual_graph"])
    original_context = deepcopy(report["cases"][0]["source_context"])
    calls = _guard_offline_loader(monkeypatch, freeze)

    results = {
        version: _rescore_synthetic_report(
            bundle, report_path, report_sha256, version=version
        )
        for version in ("1.0.3", "1.0.4")
    }

    for result in results.values():
        by_id = {case["case_id"]: case for case in result["cases"]}
        assert result["summary"]["case_count"] == 14
        assert result["summary"]["passed"] == 1
        assert result["summary"]["failed"] == 1
        assert result["summary"]["not_run"] == 12
        assert result["summary"]["metrics"]["condition_omission"] == {
            "numerator": 0,
            "denominator": 1,
            "status": "measured",
        }
        assert by_id["case-01"]["actual_graph"] == original_graph
        assert by_id["case-01"]["source_context"] == original_context
        assert by_id["case-01"]["actual_graph_canonical_json_sha256"] == (
            rescore._canonical_sha256(original_graph)
        )
        assert by_id["case-01"]["source_context_canonical_json_sha256"] == (
            rescore._canonical_sha256(original_context)
        )
        assert by_id["case-02"]["status"] == "failed"
        assert by_id["case-02"]["execution_state"] == "failed"
        assert by_id["case-02"]["reason"] == "synthetic runtime failure"
        assert by_id["case-02"]["metrics"] == {}
        assert "actual_graph" not in by_id["case-02"]
        assert "source_context" not in by_id["case-02"]
        assert by_id["case-03"]["status"] == "not_run"
        assert by_id["case-03"]["execution_state"] == "not_run"
        assert by_id["case-03"]["reason"] == "synthetic not-run case case-03"
        assert by_id["case-03"]["metrics"] == {}
        assert "actual_graph" not in by_id["case-03"]
        assert "source_context" not in by_id["case-03"]

    old_case = results["1.0.3"]["cases"][0]
    new_case = results["1.0.4"]["cases"][0]
    assert old_case["actual_graph_canonical_json_sha256"] == (
        new_case["actual_graph_canonical_json_sha256"]
    )
    assert old_case["source_context_canonical_json_sha256"] == (
        new_case["source_context_canonical_json_sha256"]
    )
    assert report_path.read_bytes() == original_report_bytes
    assert report["cases"][0]["actual_graph"] == original_graph
    assert report["cases"][0]["source_context"] == original_context
    assert len(calls["verify_bundle"]) == 2
    assert calls["runtime"] == []


def test_cli_refuses_to_overwrite_an_existing_report(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    output_path = tmp_path / "existing-report.json"
    original_bytes = b"synthetic existing report must remain untouched\n"
    output_path.write_bytes(original_bytes)

    def forbidden_rescore(*args, **kwargs):
        pytest.fail("CLI attempted to rescore before checking output existence")

    monkeypatch.setattr(rescore, "rescore_report", forbidden_rescore)

    with pytest.raises(SystemExit) as error:
        rescore.main(
            [
                "--bundle",
                str(tmp_path / "synthetic-bundle"),
                "--product-report",
                str(tmp_path / "synthetic-product-report.json"),
                "--expected-report-sha256",
                "0" * 64,
                "--version",
                "1.0.4",
                "--output",
                str(output_path),
                "--main-reviewer-authorized",
            ]
        )

    assert error.value.code == 2
    assert output_path.read_bytes() == original_bytes
