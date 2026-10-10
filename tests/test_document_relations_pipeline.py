from __future__ import annotations

import asyncio
from copy import deepcopy
from typing import Any, Mapping

import pytest

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.files import ProjectFileRegistry
from qiaowenshu_agent.core.runtime import AgentRuntime
from qiaowenshu_agent.domain.document_structure import build_document_structure
from qiaowenshu_agent.skills import build_default_registry
from qiaowenshu_agent.skills import local_backends
from qiaowenshu_agent.skills.local_backends import (
    RegistryTenderDecompositionBackend,
)
from qiaowenshu_agent.skills.tender_decomposition.skill import (
    TenderDecompositionSkill,
    _normalize_output,
    _registry_verified_document_structures,
)
from scripts.run_document_relations_negation_eval import FIXED_CASES, execute_case


def _structure(document_id: str, source_version: str, text: str) -> dict[str, Any]:
    return build_document_structure(
        [{"page_number": 1, "text": text}],
        document_id=document_id,
        source_version=source_version,
        source_checksum=f"checksum-{source_version}",
    )


def _context() -> SkillContext:
    request = SkillRequest.create()
    return SkillContext(run_id="document-relations-pipeline", request=request)


def _execute_with_registry_structure(
    registry: ProjectFileRegistry,
    *,
    project_id: str,
    structure: Mapping[str, Any],
) -> Any:
    request = SkillRequest.create(
        {
            "project_id": project_id,
            "document_structures": [structure],
            "requirements": [
                {
                    "requirement_id": "R-REGISTRY-1",
                    "category": "qualification",
                    "title": "Registry source",
                    "description": "Retain caller requirement.",
                }
            ],
        }
    )
    context = SkillContext(
        run_id=f"registry-source-{project_id}",
        request=request,
        services={"file_registry": registry},
    )
    return asyncio.run(TenderDecompositionSkill().execute(request, context))


def _and_text() -> str:
    return (
        "2.1 供应商应同时满足以下两项：\n"
        "（1）通过 OAuth2.0 或 OpenID Connect（OIDC）与现有身份系统完成身份对接；\n"
        "（2）不得以新建登录中心、迁移账号或其他方式替换采购人现有身份系统。"
    )


def _or_text() -> str:
    return (
        "2.2 供应商须提供以下两项任选一项：\n"
        "（1）供应商提供甲类有效证书；\n"
        "（2）供应商提供乙类有效证书。"
    )


def _graphs(result: Mapping[str, Any]) -> list[dict[str, Any]]:
    graphs = result["document_relations"]
    assert isinstance(graphs, list)
    return graphs


def _nodes(graph: Mapping[str, Any]) -> list[dict[str, Any]]:
    nodes = graph.get("condition_nodes") or []
    if isinstance(nodes, Mapping):
        nodes = list(nodes.values())
    return [node for node in nodes if isinstance(node, dict)]


def _group(graph: Mapping[str, Any], op: str) -> dict[str, Any]:
    matches = [node for node in _nodes(graph) if node.get("op") == op]
    assert len(matches) == 1
    return matches[0]


def _statuses(value: Any) -> list[str]:
    if isinstance(value, Mapping):
        result = [
            str(value["status"])
        ] if "status" in value else []
        for item in value.values():
            result.extend(_statuses(item))
        return result
    if isinstance(value, (list, tuple)):
        return [status for item in value for status in _statuses(item)]
    return []


def _node_source_blocks(graph: Mapping[str, Any]) -> set[str]:
    return {
        str(block_id)
        for node in _nodes(graph)
        for block_id in node.get("source_block_ids", [])
    }


def _source_references(value: Any) -> list[dict[str, Any]]:
    if isinstance(value, Mapping):
        references = [
            dict(reference)
            for reference in value.get("source_references", [])
            if isinstance(reference, Mapping)
        ]
        return references + [
            reference
            for item in value.values()
            for reference in _source_references(item)
        ]
    if isinstance(value, (list, tuple)):
        return [
            reference
            for item in value
            for reference in _source_references(item)
        ]
    return []


def _synthetic_confirmed_graph(
    structure: Mapping[str, Any],
) -> dict[str, Any]:
    page_text = str((structure.get("pages") or [{}])[0].get("raw_text") or "")
    return {
        "schema_version": "document-relations-v1",
        "condition_nodes": [
            {
                "node_id": "synthetic-confirmed-node",
                "op": "ATOM",
                "status": "confirmed",
                "source_references": [
                    {
                        "document_id": str(structure.get("document_id") or ""),
                        "source_version": str(
                            structure.get("source_version") or ""
                        ),
                        "page": 1,
                        "char_start": 0,
                        "char_end": 1,
                        "quote": page_text[:1],
                    }
                ],
            }
        ],
        "warnings": [],
    }


def test_registered_txt_flows_through_intake_and_decomposition_relations() -> None:
    registry = ProjectFileRegistry()
    registration = registry.register(
        project_id="relations-runtime",
        file_name="tender.txt",
        file_role="tender",
        content=_and_text().encode("utf-8"),
    )
    runtime = AgentRuntime(
        build_default_registry(file_registry=registry),
        services={"file_registry": registry},
    )

    result = asyncio.run(
        runtime.run(
            SkillRequest.create(
                {
                    "project_id": "relations-runtime",
                    "file_ids": [registration.file.file_id],
                    "task": "分析招标文件",
                }
            )
        )
    )

    intake = next(step for step in result.steps if step.skill_name == "tender-intake")
    decomposition = next(
        step for step in result.steps if step.skill_name == "tender-decomposition"
    )
    graph = _graphs(decomposition.result.data)[0]
    assert intake.result.data["document_structures"][0]["document_id"] == (
        registration.file.file_id
    )
    assert graph["schema_version"] == "document-relations-v1"
    assert graph["document_id"] == registration.file.file_id
    assert graph["source_version"] == (
        f"{registration.file.file_id}:v{registration.file.version}"
    )
    assert graph["source_identity_status"] == "registry_verified"
    assert "confirmed" in _statuses(graph)
    analysis = decomposition.result.data["relation_analysis"]
    assert analysis["status"] == "executed"
    assert analysis["coverage_status"] == "partial"
    assert analysis["document_count"] == 1
    assert analysis["needs_human_review"] is True
    assert analysis["source_identity_status"] == "registry_verified"
    assert analysis["source_reference_status"] == "verified"


@pytest.mark.parametrize("case", FIXED_CASES, ids=lambda case: case["case_id"])
def test_public_negation_cases_flow_through_registry_runtime_and_decomposition(
    case: Mapping[str, Any],
) -> None:
    result = asyncio.run(execute_case(case))

    assert result["execution_state"] == "executed", result["errors"]
    assert result["status"] == "passed", result["errors"]
    assert result["relation_analysis"]["status"] == "executed"
    assert result["source_verification"]["status"] == "passed"


def test_direct_local_backend_builds_relations_from_structures() -> None:
    structure = _structure("direct-doc", "direct-doc:v1", _and_text())
    result = RegistryTenderDecompositionBackend().run(
        {
            "document_structures": [structure],
            "sections": [],
            "requirements": [
                {
                    "requirement_id": "R-JSON-1",
                    "category": "qualification",
                    "title": "显式输入",
                    "description": "保留既有显式输入",
                }
            ],
        },
        _context(),
    )

    assert result["document_structures"] == [structure]
    assert result["relation_analysis"]["status"] == "executed"
    graph = _graphs(result)[0]
    assert graph["schema_version"] == "document-relations-v1"
    assert (graph["document_id"], graph["source_version"]) == (
        "direct-doc",
        "direct-doc:v1",
    )


def test_normalizer_rebuilds_instead_of_trusting_backend_relations() -> None:
    structure = _structure("forged-doc", "forged-doc:v1", _and_text())
    forged_relations = [
        {
            "schema_version": "document-relations-v1",
            "document_id": "forged-doc",
            "source_version": "forged-doc:v1",
            "condition_nodes": [
                {
                    "node_id": "backend-forgery",
                    "op": "AND",
                    "status": "confirmed",
                    "text": "伪造的已确认关系",
                    "children": [],
                    "source_block_ids": [],
                    "source_references": [],
                }
            ],
        }
    ]

    class ForgedBackend:
        def run(
            self,
            _payload: Mapping[str, Any],
            _context: SkillContext,
        ) -> dict[str, Any]:
            return {
                "requirements": [],
                "scoring_items": [],
                "document_structures": [structure],
                "document_relations": forged_relations,
                "relation_analysis": {
                    "status": "executed",
                    "coverage_status": "complete",
                    "document_count": 100,
                    "needs_human_review": False,
                },
            }

    request = SkillRequest.create(
        {
            "project_id": "forged-project",
            "document_structures": [structure],
        }
    )
    result = asyncio.run(
        TenderDecompositionSkill(backend=ForgedBackend()).execute(
            request,
            SkillContext(run_id="forged-relations", request=request),
        )
    )

    assert result.status == "success"
    graph = _graphs(result.data)[0]
    assert "backend-forgery" not in {node.get("node_id") for node in _nodes(graph)}
    analysis = result.data["relation_analysis"]
    assert analysis["status"] == "executed"
    assert analysis["coverage_status"] == "partial"
    assert analysis["document_count"] == 1
    assert analysis["needs_human_review"] is True


def test_relation_graphs_bind_document_versions_and_do_not_mix_scopes() -> None:
    first = _structure("multi-a", "multi-a:v1", _and_text())
    first_version_two = _structure("multi-a", "multi-a:v2", _or_text())
    second = _structure("multi-b", "multi-b:v1", _or_text())
    duplicate = deepcopy(first)
    normalized = _normalize_output(
        {
            "requirements": [],
            "scoring_items": [],
            "document_structures": [duplicate, second],
        },
        project_id="multi-project",
        document_structures=[first, first_version_two, second],
    )

    graphs = _graphs(normalized)
    assert [
        (graph["document_id"], graph["source_version"]) for graph in graphs
    ] == [
        ("multi-a", "multi-a:v1"),
        ("multi-a", "multi-a:v2"),
        ("multi-b", "multi-b:v1"),
    ]
    assert normalized["relation_analysis"]["document_count"] == 3
    expected_blocks = {
        (first["document_id"], first["source_version"]): {
            block["block_id"] for block in first["blocks"]
        },
        (first_version_two["document_id"], first_version_two["source_version"]): {
            block["block_id"] for block in first_version_two["blocks"]
        },
        (second["document_id"], second["source_version"]): {
            block["block_id"] for block in second["blocks"]
        },
    }
    source_pages = {
        ("multi-a", "multi-a:v1"): first["pages"],
        ("multi-a", "multi-a:v2"): first_version_two["pages"],
        ("multi-b", "multi-b:v1"): second["pages"],
    }
    for graph in graphs:
        identity = (graph["document_id"], graph["source_version"])
        assert _node_source_blocks(graph) <= expected_blocks[identity]
        references = _source_references(graph)
        assert references
        for reference in references:
            assert (reference["document_id"], reference["source_version"]) == identity
            page = next(
                item
                for item in source_pages[identity]
                if item["page_number"] == reference["page"]
            )
            assert page["raw_text"][
                reference["char_start"] : reference["char_end"]
            ] == reference["quote"]


def test_numbered_and_scope_is_independent_of_parent_hints() -> None:
    and_structure = _structure("numbered-and", "numbered-and:v1", _and_text())
    backend = RegistryTenderDecompositionBackend()

    def run(structure: dict[str, Any]) -> dict[str, Any]:
        result = backend.run(
            {"document_structures": [structure], "sections": []},
            _context(),
        )
        return _graphs(result)[0]

    and_graph = run(and_structure)
    and_group = _group(and_graph, "AND")
    nested_or = next(
        node
        for node in _nodes(and_graph)
        if node.get("op") == "OR" and "OAuth2.0 或 OpenID Connect" in node["text"]
    )
    assert nested_or["node_id"] in and_group["children"]

    changed_hints = deepcopy(and_structure)
    for block in changed_hints["blocks"]:
        if block.get("kind") not in {"blank", "page_boundary"}:
            block["parent_block_id"] = None
            block["section_block_id"] = None
    changed_group = _group(run(changed_hints), "AND")
    assert changed_group["scope_relation"] == and_group["scope_relation"]
    assert and_group["operator_relation"]["status"] == "confirmed"
    assert and_group["scope_relation"]["status"] == "confirmed"
    assert len(and_group["scope_relation"]["target_node_ids"]) == 2


def test_numbered_or_scope_has_two_explicit_member_targets() -> None:
    structure = _structure("numbered-or", "numbered-or:v1", _or_text())
    result = RegistryTenderDecompositionBackend().run(
        {"document_structures": [structure], "sections": []},
        _context(),
    )

    group = _group(_graphs(result)[0], "OR")
    assert group["operator_relation"]["status"] == "confirmed"
    assert group["scope_relation"]["status"] == "confirmed"
    assert len(group["scope_relation"]["target_node_ids"]) == 2


def test_bad_source_reference_cannot_confirm_numbered_scope() -> None:
    structure = _structure("source-miss", "source-miss:v1", _and_text())
    target = next(
        block
        for block in structure["blocks"]
        if block["raw_text"].startswith("（2）")
    )
    target["source_references"][0]["document_id"] = "other-document"

    result = RegistryTenderDecompositionBackend().run(
        {"document_structures": [structure], "sections": []},
        _context(),
    )
    group = _group(_graphs(result)[0], "AND")

    assert group["scope_relation"]["status"] != "confirmed"
    assert result["relation_analysis"]["needs_human_review"] is True


def test_section_relative_relations_remain_candidates_with_review() -> None:
    result = RegistryTenderDecompositionBackend().run(
        {
            "sections": [
                {
                    "title": "excerpt.txt",
                    "content": _and_text(),
                }
            ]
        },
        _context(),
    )

    graph = _graphs(result)[0]
    assert graph["needs_human_review"] is True
    assert "section-relative source coordinates are unverified" in " ".join(
        graph["warnings"]
    )
    assert "confirmed" not in _statuses(graph)
    assert result["relation_analysis"]["needs_human_review"] is True


def test_unknown_coordinate_statuses_cannot_be_aggregated_as_verified(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        local_backends,
        "build_document_relations",
        _synthetic_confirmed_graph,
    )
    structures = []
    for level in (
        "root",
        "page",
        "page_metadata",
        "block",
        "block_metadata",
        "metadata",
    ):
        structure = _structure(
            f"unknown-coordinate-{level}",
            f"unknown-coordinate-{level}:v1",
            _and_text(),
        )
        if level == "root":
            structure["source_coordinate_status"] = "unknown"
        elif level == "page":
            structure["pages"][0]["source_coordinate_status"] = "unknown"
        elif level == "page_metadata":
            structure["pages"][0].setdefault("metadata", {})[
                "source_coordinate_status"
            ] = "unknown"
        elif level == "block":
            structure["blocks"][0]["source_coordinate_status"] = "unknown"
        elif level == "block_metadata":
            structure["blocks"][0].setdefault("metadata", {})[
                "source_coordinate_status"
            ] = "unknown"
        else:
            structure.setdefault("metadata", {})[
                "source_coordinate_status"
            ] = "unknown"
        structures.append(structure)

    result = RegistryTenderDecompositionBackend().run(
        {"document_structures": structures, "sections": []},
        _context(),
    )
    graphs = _graphs(result)

    assert len(graphs) == 6
    assert result["relation_analysis"]["source_reference_status"] != "verified"
    assert result["relation_analysis"]["unresolved_document_count"] == 6
    for graph in graphs:
        assert graph["source_reference_status"] != "verified"
        assert "confirmed" not in _statuses(graph)


def test_backend_only_source_identity_is_unverified_and_candidate_only(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        local_backends,
        "build_document_relations",
        _synthetic_confirmed_graph,
    )
    input_structure = _structure("input-anchor", "input-anchor:v1", _and_text())
    backend_structure = _structure(
        "backend-only",
        "backend-only:v999",
        _or_text(),
    )
    backend_structure.setdefault("metadata", {}).update(
        {
            "source_identity_status": "registry_verified",
            "trusted": True,
        }
    )

    normalized = _normalize_output(
        {
            "requirements": [],
            "scoring_items": [],
            "document_structures": [backend_structure],
        },
        project_id="backend-only-project",
        document_structures=[input_structure],
    )
    graphs_by_identity = {
        (graph["document_id"], graph["source_version"]): graph
        for graph in _graphs(normalized)
    }
    anchored_graph = graphs_by_identity[("input-anchor", "input-anchor:v1")]
    unanchored_graph = graphs_by_identity[("backend-only", "backend-only:v999")]

    assert anchored_graph["source_identity_status"] == "caller_asserted"
    assert "confirmed" in _statuses(anchored_graph)
    assert unanchored_graph["source_identity_status"] == "unverified"
    assert unanchored_graph["source_reference_status"] == "verified"
    assert "confirmed" not in _statuses(unanchored_graph)
    assert normalized["relation_analysis"]["source_identity_status"] == (
        "unverified"
    )


def test_registry_identity_requires_project_version_checksum_and_content(
    monkeypatch: Any,
) -> None:
    registry = ProjectFileRegistry()
    registration = registry.register(
        project_id="registry-anchor-project",
        file_name="source.txt",
        file_role="tender",
        content=_and_text().encode("utf-8"),
    )
    registry_structure = dict(
        registry.parse(registration.file.file_id)["document_structure"]
    )
    parse_calls: list[str] = []
    parse = registry.parse

    def tracked_parse(file_id: str) -> Mapping[str, Any]:
        parse_calls.append(file_id)
        return parse(file_id)

    monkeypatch.setattr(registry, "parse", tracked_parse)
    file_id = registration.file.file_id

    assert _registry_verified_document_structures(
        registry,
        project_id="other-project",
        document_structures=[registry_structure],
    ) == []
    stale_version = deepcopy(registry_structure)
    stale_version["source_version"] = f"{file_id}:v0"
    assert _registry_verified_document_structures(
        registry,
        project_id="registry-anchor-project",
        document_structures=[stale_version],
    ) == []
    bad_checksum = deepcopy(registry_structure)
    bad_checksum["source_checksum"] = "self-reported-checksum"
    assert _registry_verified_document_structures(
        registry,
        project_id="registry-anchor-project",
        document_structures=[bad_checksum],
    ) == []
    self_reported = deepcopy(registry_structure)
    self_reported["blocks"][0]["raw_text"] += " backend mutation"
    self_reported.setdefault("metadata", {}).update(
        {
            "source_identity_status": "registry_verified",
            "trusted": True,
        }
    )
    assert _registry_verified_document_structures(
        registry,
        project_id="registry-anchor-project",
        document_structures=[self_reported],
    ) == []
    page_metadata_tamper = deepcopy(registry_structure)
    page_metadata_tamper["pages"][0].setdefault("metadata", {})[
        "source_coordinate_status"
    ] = "unknown"
    assert _registry_verified_document_structures(
        registry,
        project_id="registry-anchor-project",
        document_structures=[page_metadata_tamper],
    ) == []
    assert parse_calls == [file_id, file_id]

    verified = _registry_verified_document_structures(
        registry,
        project_id="registry-anchor-project",
        document_structures=[registry_structure],
    )
    assert verified == [registry_structure]
    assert parse_calls == [file_id, file_id, file_id]

    monkeypatch.setattr(
        local_backends,
        "build_document_relations",
        _synthetic_confirmed_graph,
    )
    relation_output = local_backends.document_relations_for_structures(
        [registry_structure],
        input_anchor_structures=[],
        registry_verified_structures=verified,
    )
    graph = _graphs(relation_output)[0]
    assert graph["source_identity_status"] == "registry_verified"
    assert "confirmed" in _statuses(graph)


def test_execute_rejects_superseded_payload_version_before_parse(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        local_backends,
        "build_document_relations",
        _synthetic_confirmed_graph,
    )
    registry = ProjectFileRegistry()
    version_one = registry.register(
        project_id="superseded-source-project",
        file_name="tender.txt",
        file_role="tender",
        content=_and_text().encode("utf-8"),
    )
    old_structure = deepcopy(
        registry.parse(version_one.file.file_id)["document_structure"]
    )
    version_two = registry.register(
        project_id="superseded-source-project",
        file_name="tender.txt",
        file_role="tender",
        content=_or_text().encode("utf-8"),
    )
    assert version_two.file.version == 2
    assert version_two.file.supersedes == version_one.file.file_id

    parse_calls: list[str] = []
    parse = registry.parse

    def tracked_parse(file_id: str, *, force: bool = False) -> Mapping[str, Any]:
        parse_calls.append(file_id)
        return parse(file_id, force=force)

    monkeypatch.setattr(registry, "parse", tracked_parse)
    result = _execute_with_registry_structure(
        registry,
        project_id="superseded-source-project",
        structure=old_structure,
    )

    assert result.status == "success"
    graph = _graphs(result.data)[0]
    assert graph["source_identity_status"] == "unverified"
    assert "confirmed" not in _statuses(graph)
    assert result.data["relation_analysis"]["source_identity_status"] == (
        "unverified"
    )
    assert parse_calls == []


def test_execute_rejects_registry_project_mismatch_before_parse(
    monkeypatch: Any,
) -> None:
    monkeypatch.setattr(
        local_backends,
        "build_document_relations",
        _synthetic_confirmed_graph,
    )
    registry = ProjectFileRegistry()
    registration = registry.register(
        project_id="registered-source-project",
        file_name="tender.txt",
        file_role="tender",
        content=_and_text().encode("utf-8"),
    )
    structure = deepcopy(
        registry.parse(registration.file.file_id)["document_structure"]
    )

    parse_calls: list[str] = []
    parse = registry.parse

    def tracked_parse(file_id: str, *, force: bool = False) -> Mapping[str, Any]:
        parse_calls.append(file_id)
        return parse(file_id, force=force)

    monkeypatch.setattr(registry, "parse", tracked_parse)
    result = _execute_with_registry_structure(
        registry,
        project_id="payload-source-project",
        structure=structure,
    )

    assert result.status == "success"
    graph = _graphs(result.data)[0]
    assert graph["source_identity_status"] == "unverified"
    assert "confirmed" not in _statuses(graph)
    assert result.data["relation_analysis"]["source_identity_status"] == (
        "unverified"
    )
    assert parse_calls == []


def test_explicit_json_without_structure_is_not_run_and_keeps_existing_rule() -> None:
    requirement = {
        "requirement_id": "R-JSON-1",
        "category": "qualification",
        "title": "营业执照",
        "description": "投标人须提供有效营业执照。",
        "mandatory": True,
        "check_rule": {
            "rule_ast": {"op": "manual_review"},
            "coverage_status": "partial",
        },
    }
    request = SkillRequest.create(
        {
            "project_id": "explicit-json-project",
            "requirements": [requirement],
        }
    )
    result = asyncio.run(
        TenderDecompositionSkill().execute(
            request,
            SkillContext(run_id="explicit-json", request=request),
        )
    )

    assert result.status == "success"
    assert result.data["requirements"][0]["requirement_id"] == "R-JSON-1"
    assert result.data["requirements"][0]["check_rule"] == requirement["check_rule"]
    analysis = result.data["relation_analysis"]
    assert analysis["status"] == "not_run"
    assert analysis["coverage_status"] == "not_run"
    assert analysis["document_count"] == 0
    assert analysis["needs_human_review"] is False
    assert analysis["not_run_reason"] == "no_document_structures"
    assert analysis["warnings"] == []
    assert any(
        "relation analysis was not run" in item
        for item in analysis["diagnostics"]
    )
    assert result.data["warnings"] == []
    assert _graphs(result.data) == []


def test_runtime_allows_explicit_json_when_relations_are_not_run() -> None:
    result = asyncio.run(
        AgentRuntime(build_default_registry()).run(
            SkillRequest.create(
                {
                    "project_id": "project-1",
                    "requirements": [
                        {
                            "requirement_id": "license-1",
                            "category": "qualification",
                            "title": "营业执照",
                            "description": "提供有效营业执照",
                            "mandatory": True,
                            "evidence_required": ["business_license"],
                        }
                    ],
                    "scoring_items": [
                        {
                            "item_id": "technical-1",
                            "title": "技术方案",
                            "max_score": 20,
                            "criteria": "方案完整，提供技术方案",
                            "evidence_required": ["技术方案"],
                        }
                    ],
                    "bidder_profile": {
                        "bidder_id": "bidder-1",
                        "materials": [
                            {
                                "material_id": "license-material",
                                "material_type": "business_license",
                                "title": "营业执照",
                            }
                        ],
                    },
                    "plan": [
                        {
                            "skill_name": "tender-decomposition",
                            "input": {
                                "project_id": {"$ref": "$request/project_id"},
                                "requirements": {
                                    "$ref": "$request/requirements"
                                },
                                "scoring_items": {
                                    "$ref": "$request/scoring_items"
                                },
                            },
                        },
                        {
                            "skill_name": "bid-feasibility",
                            "input": {
                                "project_id": {"$ref": "$request/project_id"},
                                "requirements": {
                                    "$ref": "$state/tender-decomposition/requirements"
                                },
                                "bidder_profile": {
                                    "$ref": "$request/bidder_profile"
                                },
                            },
                        },
                        {
                            "skill_name": "evidence-matching",
                            "input": {
                                "requirements": {
                                    "$ref": "$state/tender-decomposition/requirements"
                                },
                                "scoring_items": {
                                    "$ref": "$state/tender-decomposition/scoring_items"
                                },
                                "materials": {
                                    "$ref": "$request/bidder_profile/materials"
                                },
                            },
                        },
                    ],
                }
            )
        )
    )

    assert result.status == "success"
    assert [step.skill_name for step in result.steps] == [
        "tender-decomposition",
        "bid-feasibility",
        "evidence-matching",
    ]
    decomposition = result.steps[0].result.data
    analysis = decomposition["relation_analysis"]
    assert analysis["status"] == "not_run"
    assert analysis["coverage_status"] == "not_run"
    assert analysis["not_run_reason"] == "no_document_structures"
    assert analysis["needs_human_review"] is False
    assert analysis["warnings"] == []
    assert result.steps[1].result.data["decision"] == "bid"


def test_unknown_schema_is_not_run_with_a_distinct_reason() -> None:
    unknown = {
        "schema_version": "unknown-structure",
        "document_id": "unknown-doc",
        "source_version": "unknown-doc:v1",
        "blocks": [{"block_id": "unknown-block", "raw_text": "原文"}],
    }
    result = _normalize_output(
        {
            "requirements": [],
            "scoring_items": [],
            "document_structures": [unknown],
        },
        project_id="unknown-schema-project",
        document_structures=[],
    )
    analysis = result["relation_analysis"]

    assert analysis["status"] == "not_run"
    assert analysis["not_run_reason"] == "unsupported_schema"
    assert analysis["needs_human_review"] is True
    assert analysis["warnings"]
    assert analysis["unprocessed_structures"] == [
        {
            "document_id": "unknown-doc",
            "source_version": "unknown-doc:v1",
            "reason": "unsupported_schema",
        }
    ]
    assert _graphs(result) == []


def test_empty_structure_is_not_run() -> None:
    empty = _structure("empty-doc", "empty-doc:v1", "")
    empty["blocks"] = []
    empty_result = RegistryTenderDecompositionBackend().run(
        {"document_structures": [empty], "sections": []},
        _context(),
    )
    empty_analysis = empty_result["relation_analysis"]
    assert empty_analysis["status"] == "not_run"
    assert empty_analysis["coverage_status"] == "not_run"
    assert empty_analysis["document_count"] == 0
    assert empty_analysis["not_run_reason"] == "empty_blocks"
    assert empty_analysis["needs_human_review"] is True
    assert empty_analysis["warnings"]
    assert empty_analysis["unprocessed_structures"][0]["reason"] == "empty_blocks"
    assert _graphs(empty_result) == []


def test_missing_verified_pages_are_executed_but_unresolved() -> None:
    no_pages = _structure("no-pages-doc", "no-pages-doc:v1", _and_text())
    no_pages["pages"] = []
    no_pages_result = RegistryTenderDecompositionBackend().run(
        {"document_structures": [no_pages], "sections": []},
        _context(),
    )
    analysis = no_pages_result["relation_analysis"]
    graph = _graphs(no_pages_result)[0]
    assert analysis["status"] == "executed"
    assert analysis["coverage_status"] == "partial"
    assert analysis["document_count"] == 1
    assert analysis["unresolved_document_count"] == 1
    assert analysis["source_reference_status"] == "unresolved"
    assert analysis["needs_human_review"] is True
    assert any("source pages are missing" in warning for warning in graph["warnings"])
    assert "confirmed" not in _statuses(graph)


def test_no_input_is_distinct_from_empty_or_unknown_structure() -> None:
    result = _normalize_output(
        {"requirements": [], "scoring_items": []},
        project_id="no-structure-project",
        document_structures=[],
    )
    analysis = result["relation_analysis"]

    assert analysis["status"] == "not_run"
    assert analysis["not_run_reason"] == "no_document_structures"
    assert analysis["needs_human_review"] is False
    assert analysis["warnings"] == []
    assert any(
        "relation analysis was not run" in item
        for item in analysis["diagnostics"]
    )
    assert analysis["unprocessed_structures"] == []
    assert _graphs(result) == []


def test_conflicting_same_version_structures_are_warned_and_not_combined() -> None:
    preferred = _structure("conflict-doc", "conflict-doc:v1", _and_text())
    conflicting = _structure("conflict-doc", "conflict-doc:v1", _or_text())
    normalized = _normalize_output(
        {
            "requirements": [],
            "scoring_items": [],
            "document_structures": [conflicting],
        },
        project_id="conflict-project",
        document_structures=[preferred],
    )
    analysis = normalized["relation_analysis"]

    assert normalized["document_structures"] == [preferred]
    assert _graphs(normalized) == []
    assert analysis["status"] == "not_run"
    assert analysis["not_run_reason"] == "conflicting_content"
    assert analysis["unprocessed_structures"] == [
        {
            "document_id": "conflict-doc",
            "source_version": "conflict-doc:v1",
            "reason": "conflicting_content",
        }
    ]
    assert any(
        "conflicting document content" in warning
        for warning in analysis["warnings"]
    )
    assert any(
        "conflicting document content" in warning
        for warning in normalized["warnings"]
    )


def test_skill_normalizer_detects_payload_backend_content_conflict() -> None:
    payload_structure = _structure(
        "payload-backend-doc",
        "payload-backend-doc:v1",
        _and_text(),
    )
    backend_structure = _structure(
        "payload-backend-doc",
        "payload-backend-doc:v1",
        _or_text(),
    )
    backend_inputs: list[list[Mapping[str, Any]]] = []

    class ConflictingBackend:
        def run(
            self,
            payload: Mapping[str, Any],
            _context: SkillContext,
        ) -> dict[str, Any]:
            backend_inputs.append(list(payload["document_structures"]))
            return {
                "requirements": [],
                "scoring_items": [],
                "document_structures": [backend_structure],
                "document_relations": [
                    {
                        "document_id": "payload-backend-doc",
                        "source_version": "payload-backend-doc:v1",
                        "condition_nodes": [
                            {
                                "node_id": "backend-forged-confirmation",
                                "op": "ATOM",
                                "status": "confirmed",
                            }
                        ],
                    }
                ],
                "relation_analysis": {
                    "status": "executed",
                    "coverage_status": "complete",
                    "document_count": 1,
                    "needs_human_review": False,
                },
            }

    request = SkillRequest.create(
        {
            "project_id": "payload-backend-project",
            "document_structures": [payload_structure],
        }
    )
    result = asyncio.run(
        TenderDecompositionSkill(backend=ConflictingBackend()).execute(
            request,
            SkillContext(
                run_id="payload-backend-conflict",
                request=request,
            ),
        )
    )

    assert result.status == "success"
    assert backend_inputs == [[payload_structure]]
    assert result.data["document_structures"] == [payload_structure]
    assert _graphs(result.data) == []
    analysis = result.data["relation_analysis"]
    assert analysis["status"] == "not_run"
    assert analysis["not_run_reason"] == "conflicting_content"
    assert analysis["needs_human_review"] is True
    assert analysis["unprocessed_structures"] == [
        {
            "document_id": "payload-backend-doc",
            "source_version": "payload-backend-doc:v1",
            "reason": "conflicting_content",
        }
    ]
    assert any(
        "conflicting document content" in warning
        for warning in analysis["warnings"]
    )
    assert any(
        "conflicting document content" in warning
        for warning in result.data["warnings"]
    )
