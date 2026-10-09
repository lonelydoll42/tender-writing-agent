from __future__ import annotations

import asyncio
from dataclasses import replace
from pathlib import Path
from typing import Any

import pytest

import qiaowenshu_agent.core.files as files_module
from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.core.files import ProjectFileRegistry, extract_document_text
from qiaowenshu_agent.core.runtime import AgentRuntime
from qiaowenshu_agent.core.store import SQLiteStore
from qiaowenshu_agent.domain.document_structure import build_document_structure
from qiaowenshu_agent.skills import build_default_registry
from qiaowenshu_agent.skills.local_backends import (
    RegistryTenderDecompositionBackend,
    _candidate_source_blocks,
)
from qiaowenshu_agent.skills.tender_decomposition.skill import (
    TenderDecompositionSkill,
    _normalize_output as _normalize_decomposition_output,
)
from qiaowenshu_agent.skills.tender_intake.skill import _normalize_output


def _structure(document_id: str, source_version: str, text: str) -> dict[str, Any]:
    return build_document_structure(
        [{"page_number": 1, "text": text}],
        document_id=document_id,
        source_version=source_version,
        source_checksum=f"checksum-{source_version}",
    )


def _reference(document_id: str, source_version: str) -> dict[str, Any]:
    return {
        "document_id": document_id,
        "source_version": source_version,
        "page": 1,
        "quote": "source text",
    }


def _exact_block_reference(
    structure: dict[str, Any],
    block: dict[str, Any],
    **overrides: Any,
) -> dict[str, Any]:
    span = block["source_span"]
    reference = {
        "document_id": structure["document_id"],
        "source_version": structure["source_version"],
        "page": block["page_number"],
        "line_number": block["line_number"],
        "locator": (
            f"p{block['page_number']}:l{block['line_number']}"
        ),
        "quote": block["raw_text"],
        "char_start": span["start"],
        "char_end": span["end"],
    }
    reference.update(overrides)
    return reference


def test_document_structure_survives_registry_to_runtime_decomposition() -> None:
    raw_text = "一、项目概况\n目录\n投标人须提供有效营业执照。"
    registry = ProjectFileRegistry()
    registration = registry.register(
        project_id="structure-project",
        file_name="tender.txt",
        file_role="tender",
        content=raw_text.encode("utf-8"),
    )
    parsed = registry.parse(registration.file.file_id)

    structure = parsed["document_structure"]
    assert structure["schema_version"] == "document-structure-v1"
    assert structure["document_id"] == registration.file.file_id
    assert structure["source_version"] == (
        f"{registration.file.file_id}:v{registration.file.version}"
    )
    assert structure["source_checksum"] == registration.file.checksum
    assert structure["metadata"]["source_representation"] == "extracted_page_text"
    clause = next(
        block
        for block in structure["blocks"]
        if block["raw_text"] == "投标人须提供有效营业执照。"
    )
    assert clause["source_span"]["page_number"] == 1
    assert (
        raw_text[clause["source_span"]["start"] : clause["source_span"]["end"]]
        == clause["raw_text"]
    )
    assert clause["source_references"][0]["document_id"] == registration.file.file_id
    assert clause["source_references"][0]["source_version"] == (
        f"{registration.file.file_id}:v{registration.file.version}"
    )
    stored = registry.store.get_artifact(parsed["artifact_id"])
    assert stored is not None
    assert files_module._content_hash(stored.content) == stored.content_hash
    content_without_structure = dict(stored.content)
    content_without_structure.pop("document_structure")
    assert files_module._content_hash(content_without_structure) != stored.content_hash

    runtime = AgentRuntime(
        build_default_registry(file_registry=registry),
        services={"file_registry": registry},
    )
    result = asyncio.run(
        runtime.run(
            SkillRequest.create(
                {
                    "project_id": "structure-project",
                    "file_ids": [registration.file.file_id],
                    "task": "分析招标文件",
                }
            )
        )
    )

    preprocess = next(
        step for step in result.steps if step.skill_name == "document-preprocess"
    )
    intake = next(step for step in result.steps if step.skill_name == "tender-intake")
    decomposition = next(
        step for step in result.steps if step.skill_name == "tender-decomposition"
    )
    preprocess_structure = preprocess.result.data["artifact"]["document_structure"]
    intake_structure = intake.result.data["document_structures"][0]
    assert intake.result.data["sections"][0]["document_structure"] == intake_structure
    assert preprocess_structure == structure == intake_structure
    assert decomposition.result.data["document_structures"] == [structure]
    assert decomposition.result.data["block_projection_audit"]["candidate_projection"][
        "blocks"
    ]
    assert (
        decomposition.result.data["block_projection_audit"][
            "final_requirement_extraction"
        ]["complete"]
        is False
    )


def test_parse_cache_force_and_legacy_text_shape_are_stable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    content = "第一行\n投标人须提供营业执照。".encode("utf-8")
    registry = ProjectFileRegistry()
    registration = registry.register(
        project_id="cache-project",
        file_name="tender.txt",
        content=content,
    )

    first = registry.parse(registration.file.file_id)
    cached = registry.parse(registration.file.file_id)
    forced = registry.parse(registration.file.file_id, force=True)
    legacy_text, page_count, _warnings = extract_document_text(
        content,
        "tender.txt",
    )

    assert first["artifact_id"] == cached["artifact_id"] == forced["artifact_id"]
    assert first["source_file_versions"] == cached["source_file_versions"]
    assert cached["source_file_versions"] == forced["source_file_versions"]
    assert first["content_hash"] == cached["content_hash"] == forced["content_hash"]
    assert first["text"] == cached["text"] == forced["text"] == legacy_text
    assert first["pages"][0]["text"] == "第一行\n投标人须提供营业执照。"
    assert page_count == first["page_count"] == 1
    assert len(registry.list("cache-project")) == 1

    stored = registry.store.get_artifact(first["artifact_id"])
    assert stored is not None
    legacy_content = dict(stored.content)
    legacy_content.pop("document_structure")
    registry.store.save_artifact(
        replace(
            stored,
            schema_version="1.1",
            content_hash=files_module._content_hash(legacy_content),
            content=legacy_content,
        )
    )
    monkeypatch.setattr(
        files_module,
        "extract_document_pages",
        lambda *_args, **_kwargs: pytest.fail(
            "cache structure upgrade must reuse stored page text"
        ),
    )

    upgraded = registry.parse(registration.file.file_id)
    assert upgraded["artifact_id"] == first["artifact_id"]
    assert upgraded["schema_version"] == "1.2"
    assert upgraded["document_structure"]["source_version"] == (
        f"{registration.file.file_id}:v1"
    )
    assert upgraded["text"] == legacy_text


def test_sqlite_restart_upgrades_cached_structure_without_reparsing(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "structure-cache.sqlite3"
    first_store = SQLiteStore(database)
    first_registry = ProjectFileRegistry(first_store)
    registration = first_registry.register(
        project_id="sqlite-structure-project",
        file_name="tender.txt",
        content="重启后仍使用缓存页文本".encode("utf-8"),
    )
    parsed = first_registry.parse(registration.file.file_id)
    stored = first_store.get_artifact(parsed["artifact_id"])
    assert stored is not None
    legacy_content = dict(stored.content)
    legacy_content.pop("document_structure")
    first_store.save_artifact(
        replace(
            stored,
            schema_version="1.1",
            content_hash=files_module._content_hash(legacy_content),
            content=legacy_content,
        )
    )
    first_store.close()

    second_store = SQLiteStore(database)
    second_registry = ProjectFileRegistry(second_store)
    monkeypatch.setattr(
        files_module,
        "extract_document_pages",
        lambda *_args, **_kwargs: pytest.fail(
            "restarted cache migration must not reparse the source bytes"
        ),
    )
    upgraded = second_registry.parse(registration.file.file_id)
    assert upgraded["artifact_id"] == parsed["artifact_id"]
    assert upgraded["document_structure"]["source_version"] == (
        f"{registration.file.file_id}:v1"
    )
    upgraded_stored = second_store.get_artifact(parsed["artifact_id"])
    assert upgraded_stored is not None
    assert files_module._content_hash(upgraded_stored.content) == upgraded[
        "content_hash"
    ]
    second_store.close()


def test_stale_old_version_structure_upgrade_does_not_revive_artifact() -> None:
    registry = ProjectFileRegistry()
    first_registration = registry.register(
        project_id="stale-structure-project",
        file_name="tender.txt",
        file_role="tender",
        content="第一版正文".encode("utf-8"),
    )
    parsed = registry.parse(first_registration.file.file_id)
    registry.register(
        project_id="stale-structure-project",
        file_name="tender.txt",
        file_role="tender",
        content="第二版正文".encode("utf-8"),
    )

    stale_artifact = registry.store.get_artifact(parsed["artifact_id"])
    assert stale_artifact is not None
    assert stale_artifact.status == "stale"
    stale_reason = stale_artifact.stale_reason
    legacy_content = dict(stale_artifact.content)
    legacy_content.pop("document_structure")
    registry.store.save_artifact(
        replace(
            stale_artifact,
            schema_version="1.1",
            content_hash=files_module._content_hash(legacy_content),
            content=legacy_content,
        )
    )

    upgraded = registry.parse(first_registration.file.file_id)
    assert upgraded["status"] == "stale"
    assert upgraded["stale_reason"] == stale_reason
    assert upgraded["document_structure"]["source_version"] == (
        f"{first_registration.file.file_id}:v1"
    )

    stored = registry.store.get_artifact(parsed["artifact_id"])
    assert stored is not None
    registry.store.save_artifact(
        replace(stored, source_file_versions=["damaged-source:v1"])
    )
    repaired = registry.parse(first_registration.file.file_id)
    assert repaired["status"] == "stale"
    assert repaired["stale_reason"] == stale_reason
    assert repaired["source_file_versions"] == [f"{first_registration.file.file_id}:v1"]


def test_intake_attaches_structures_by_document_and_version_not_position() -> None:
    version_one = _structure("doc-1", "doc-1:v1", "version one")
    version_two = _structure("doc-1", "doc-1:v2", "version two")
    normalized = _normalize_output(
        {
            "project_id": "matching-project",
            "profile": {"project_id": "matching-project"},
            "sections": [
                {
                    "section_id": "section-v1",
                    "file_id": "doc-1",
                    "source_references": [_reference("doc-1", "doc-1:v1")],
                    "content": "version one",
                },
                {
                    "section_id": "section-v2",
                    "file_id": "doc-1",
                    "source_references": [_reference("doc-1", "doc-1:v2")],
                    "content": "version two",
                },
            ],
            "document_structures": [version_two, version_one],
            "pages": [],
            "artifacts": [],
        },
        project_id="matching-project",
    )

    assert normalized["document_structures"] == [version_two, version_one]
    assert normalized["sections"][0]["document_structure"] == version_one
    assert normalized["sections"][1]["document_structure"] == version_two


def test_intake_leaves_ambiguous_or_conflicting_structure_unattached() -> None:
    version_one = _structure("doc-1", "doc-1:v1", "version one")
    version_two = _structure("doc-1", "doc-1:v2", "version two")
    other_document = _structure("doc-2", "doc-2:v1", "other document")

    ambiguous = _normalize_output(
        {
            "profile": {"project_id": "matching-project"},
            "sections": [{"section_id": "ambiguous", "file_id": "doc-1"}],
            "document_structures": [version_one, version_two],
            "pages": [],
            "artifacts": [],
        },
        project_id="matching-project",
    )
    assert "document_structure" not in ambiguous["sections"][0]
    assert ambiguous["document_structures"] == [version_one, version_two]
    assert any(
        "matches multiple structures" in warning for warning in ambiguous["warnings"]
    )

    conflicting = _normalize_output(
        {
            "profile": {"project_id": "matching-project"},
            "sections": [
                {
                    "section_id": "conflict",
                    "file_id": "doc-1",
                    "source_references": [_reference("doc-2", "doc-2:v1")],
                }
            ],
            "document_structures": [version_one, other_document],
            "pages": [],
            "artifacts": [],
        },
        project_id="matching-project",
    )
    assert "document_structure" not in conflicting["sections"][0]
    assert conflicting["document_structures"] == [version_one, other_document]
    assert any(
        "conflicts with source references" in warning
        for warning in conflicting["warnings"]
    )


def test_zero_of_eight_heading_blocks_remains_partial_and_needs_review() -> None:
    headings = "\n".join(
        f"{number}、第{number}部分标题" for number in "一二三四五六七八"
    )
    result = RegistryTenderDecompositionBackend().run(
        {"sections": [{"title": "legacy.txt", "content": headings}]},
        SkillContext(
            run_id="structure-empty-decomposition",
            request=SkillRequest.create(),
        ),
    )

    audit = result["block_projection_audit"]
    candidate_projection = audit["candidate_projection"]
    final_extraction = audit["final_requirement_extraction"]
    assert len(result["document_structures"][0]["blocks"]) == 8
    assert len(candidate_projection["blocks"]) == 8
    assert candidate_projection["candidates"] == []
    assert all(
        block["filter_reason"] == "heading" for block in candidate_projection["blocks"]
    )
    assert final_extraction["candidate_results"] == []
    assert result["requirements"] == []
    assert result["scoring_items"] == []
    assert result["extraction_complete"] is False
    assert result["needs_human_review"] is True
    assert result["business_status"] == "needs_review"

    skill = TenderDecompositionSkill(backend=RegistryTenderDecompositionBackend())
    request = SkillRequest.create(
        {
            "project_id": "heading-only-project",
            "sections": [{"title": "legacy.txt", "content": headings}],
        }
    )
    normalized = asyncio.run(
        skill.execute(
            request,
            SkillContext(run_id="heading-only-skill", request=request),
        )
    )
    assert normalized.status == "success"
    assert normalized.data["extraction_complete"] is False
    assert normalized.data["needs_human_review"] is True
    assert normalized.data["business_status"] == "needs_review"
    assert normalized.data["summary"]["requirement_count"] == 0
    assert normalized.data["block_projection_audit"] == audit


def test_candidate_projection_does_not_claim_nonrequirement_as_extracted() -> None:
    result = RegistryTenderDecompositionBackend().run(
        {
            "sections": [
                {
                    "title": "legacy.txt",
                    "content": "项目预算金额为人民币一百万元。",
                }
            ]
        },
        SkillContext(
            run_id="candidate-not-requirement",
            request=SkillRequest.create(),
        ),
    )

    audit = result["block_projection_audit"]
    assert len(audit["candidate_projection"]["candidates"]) == 1
    assert result["requirements"] == []
    assert audit["final_requirement_extraction"]["complete"] is False
    outcome = audit["final_requirement_extraction"]["candidate_results"][0][
        "outcomes"
    ][0]
    assert outcome["outcome"] == "not_requirement_under_local_rules"
    assert outcome["generated_ids"] == []


def test_preprocess_structure_diagnostics_do_not_change_business_status() -> None:
    registry = ProjectFileRegistry()
    registration = registry.register(
        project_id="preprocess-structure-project",
        file_name="tender.txt",
        content="一般说明文本".encode("utf-8"),
    )
    runtime = AgentRuntime(
        build_default_registry(file_registry=registry),
        services={"file_registry": registry},
    )
    result = asyncio.run(
        runtime.run(
            SkillRequest.create(
                {
                    "project_id": "preprocess-structure-project",
                    "plan": [
                        {
                            "skill_name": "document-preprocess",
                            "input": {
                                "file_id": registration.file.file_id,
                                "business_scene": "tender_parse",
                            },
                        }
                    ],
                }
            )
        )
    )

    assert result.steps[0].result.status == "success"
    assert result.steps[0].result.data["artifact"]["document_structure"][
        "needs_human_review"
    ] is True
    assert result.execution_status == "completed"
    assert result.status == "success"
    assert result.business_status == "not_checked"


def test_candidate_projection_maps_repeated_text_by_exact_page_and_line() -> None:
    clause = "投标人须提供有效营业执照。"
    page_one = f"{clause}\n\n{clause}"
    structure = build_document_structure(
        [
            {"page_number": 1, "text": page_one},
            {"page_number": 2, "text": clause},
        ],
        document_id="duplicate-doc",
        source_version="duplicate-doc:v1",
    )
    references = [
        {
            "document_id": "duplicate-doc",
            "source_version": "duplicate-doc:v1",
            "page": 1,
            "locator": "duplicate-doc:p1",
        },
        {
            "document_id": "duplicate-doc",
            "source_version": "duplicate-doc:v1",
            "page": 2,
            "locator": "duplicate-doc:p2",
        },
    ]
    result = RegistryTenderDecompositionBackend().run(
        {
            "sections": [
                {
                    "file_id": "duplicate-doc",
                    "source_version": "duplicate-doc:v1",
                    "content": f"{page_one}\f{clause}",
                    "source_references": references,
                }
            ],
            "document_structures": [structure],
        },
        SkillContext(
            run_id="duplicate-source-lines",
            request=SkillRequest.create(),
        ),
    )
    projection = result["block_projection_audit"]["candidate_projection"]
    candidates = projection["candidates"]
    expected = {
        (1, 1),
        (1, 3),
        (2, 1),
    }
    assert len(candidates) == 3
    assert all(
        candidate["source_mapping_status"] == "mapped_exact_locator"
        for candidate in candidates
    )
    mapped_locations = {
        (
            block["page_number"],
            block["line_number"],
        )
        for candidate in candidates
        for block in candidate["source_blocks"]
        for block in structure["blocks"]
        if block["block_id"] == candidate["source_block_ids"][0]
    }
    assert mapped_locations == expected
    assert len({candidate["source_block_ids"][0] for candidate in candidates}) == 3


def test_exact_locator_requires_quote_to_match_raw_line() -> None:
    clause = "投标人须提交营业执照。"
    structure = _structure("quote-check-doc", "quote-check-doc:v1", clause)
    block = structure["blocks"][0]
    reference = _exact_block_reference(structure, block)

    mapped, status, reason = _candidate_source_blocks(
        clause,
        [reference],
        [structure],
    )
    assert status == "mapped_exact_locator"
    assert reason is None
    assert mapped[0]["block_id"] == block["block_id"]

    wrong_quote = {
        **reference,
        "quote": "投标人须具有ISO27001认证。",
    }
    mapped, status, reason = _candidate_source_blocks(
        clause,
        [wrong_quote],
        [structure],
    )
    assert mapped == []
    assert status == "unmapped"
    assert reason == "source reference quote conflicts with source raw line"


def test_exact_quote_does_not_drop_numbering_prefix() -> None:
    raw_line = "1. 投标人须提交营业执照。"
    structure = _structure("numbered-quote-doc", "numbered-quote-doc:v1", raw_line)
    block = structure["blocks"][0]
    reference = _exact_block_reference(
        structure,
        block,
        quote="投标人须提交营业执照。",
    )

    mapped, status, reason = _candidate_source_blocks(
        "投标人须提交营业执照。",
        [reference],
        [structure],
    )

    assert mapped == []
    assert status == "unmapped"
    assert reason == "source reference quote conflicts with source raw line"


def test_exact_locator_rejects_conflicting_span_or_page() -> None:
    clause = "投标人须提交营业执照。"
    structure = _structure("span-check-doc", "span-check-doc:v1", clause)
    block = structure["blocks"][0]
    reference = _exact_block_reference(structure, block)

    wrong_span = {
        **reference,
        "char_start": reference["char_start"] + 1,
        "char_end": reference["char_end"] + 1,
    }
    mapped, status, reason = _candidate_source_blocks(
        clause,
        [wrong_span],
        [structure],
    )
    assert mapped == []
    assert status == "unmapped"
    assert reason == "source reference character span conflicts with source block span"

    wrong_page = {**reference, "page": 2}
    mapped, status, reason = _candidate_source_blocks(
        clause,
        [wrong_page],
        [structure],
    )
    assert mapped == []
    assert status == "ambiguous"
    assert reason == (
        "line locator conflicts with explicit page, line, or version metadata"
    )


def test_duplicate_exact_locator_with_conflicting_quotes_is_ambiguous() -> None:
    clause = "投标人须提交营业执照。"
    structure = _structure("duplicate-quote-doc", "duplicate-quote-doc:v1", clause)
    block = structure["blocks"][0]
    reference = _exact_block_reference(structure, block)
    conflicting_reference = {
        **reference,
        "quote": "投标人须具有ISO27001认证。",
    }

    mapped, status, reason = _candidate_source_blocks(
        clause,
        [reference, conflicting_reference],
        [structure],
    )

    assert mapped == []
    assert status == "ambiguous"
    assert reason == "duplicate locator has conflicting quote or span claims"


def test_candidate_projection_does_not_guess_missing_or_multiple_versions() -> None:
    clause = "投标人须提供有效营业执照。"
    structures = [
        _structure("versioned-doc", "versioned-doc:v1", clause),
        _structure("versioned-doc", "versioned-doc:v2", clause),
    ]
    result = RegistryTenderDecompositionBackend().run(
        {
            "sections": [
                {
                    "file_id": "versioned-doc",
                    "content": clause,
                    "source_references": [
                        {
                            "document_id": "versioned-doc",
                            "page": 1,
                            "quote": clause,
                        }
                    ],
                }
            ],
            "document_structures": structures,
        },
        SkillContext(
            run_id="missing-source-version",
            request=SkillRequest.create(),
        ),
    )

    candidate = result["block_projection_audit"]["candidate_projection"][
        "candidates"
    ][0]
    assert candidate["source_mapping_status"] == "ambiguous"
    assert candidate["source_block_ids"] == []
    assert candidate["source_mapping_reason"] == (
        "line locator lacks a complete document/version/page key"
    )


def test_text_fallback_requires_one_unique_block_and_explicit_version() -> None:
    clause = "投标人须提供有效营业执照。"
    unique = _structure("text-fallback-doc", "text-fallback-doc:v1", clause)
    references = [
        {
            "document_id": "text-fallback-doc",
            "source_version": "text-fallback-doc:v1",
            "quote": clause,
        }
    ]
    mapped, status, reason = _candidate_source_blocks(
        clause,
        references,
        [unique],
    )
    assert status == "mapped_unique_text"
    assert reason is None
    assert mapped[0]["mapping_method"] == "unique_text_match"

    repeated = build_document_structure(
        [
            {"page_number": 1, "text": clause},
            {"page_number": 2, "text": clause},
        ],
        document_id="text-fallback-doc",
        source_version="text-fallback-doc:v1",
    )
    mapped, status, reason = _candidate_source_blocks(
        clause,
        references,
        [repeated],
    )
    assert mapped == []
    assert status == "ambiguous"
    assert reason == "text fallback matches multiple source blocks"

    wrong_quote = [
        {
            "document_id": "text-fallback-doc",
            "source_version": "text-fallback-doc:v1",
            "quote": "投标人须具有ISO27001认证。",
        }
    ]
    mapped, status, reason = _candidate_source_blocks(
        clause,
        wrong_quote,
        [unique],
    )
    assert mapped == []
    assert status == "unmapped"
    assert reason == "text fallback quote is not supported by source raw text"


def test_candidate_pipeline_preserves_exact_reference_quote_for_audit() -> None:
    clause = "投标人须提交营业执照。"
    structure = _structure("pipeline-quote-doc", "pipeline-quote-doc:v1", clause)
    correct_reference = _exact_block_reference(structure, structure["blocks"][0])
    wrong_reference = {
        **correct_reference,
        "quote": "投标人须具有ISO27001认证。",
    }

    result = RegistryTenderDecompositionBackend().run(
        {
            "sections": [
                {
                    "file_id": "pipeline-quote-doc",
                    "source_version": "pipeline-quote-doc:v1",
                    "content": clause,
                    "source_references": [
                        correct_reference,
                        wrong_reference,
                    ],
                }
            ],
            "document_structures": [structure],
        },
        SkillContext(
            run_id="pipeline-conflicting-quotes",
            request=SkillRequest.create(),
        ),
    )

    candidate = result["block_projection_audit"]["candidate_projection"][
        "candidates"
    ][0]
    assert candidate["source_mapping_status"] == "ambiguous"
    assert candidate["source_block_ids"] == []


def test_mixed_decomposition_keeps_unverified_legacy_section_raw_text() -> None:
    provided = _structure("known-doc", "known-doc:v1", "已结构化文本")
    legacy_text = "旧section中的原始条款内容"
    result = RegistryTenderDecompositionBackend().run(
        {
            "sections": [
                {
                    "file_id": "known-doc",
                    "source_version": "known-doc:v1",
                    "content": "已结构化文本",
                    "document_structure": provided,
                },
                {
                    "section_id": "legacy-mixed-source",
                    "content": legacy_text,
                    "source_references": [
                        _reference("unknown-doc", "unknown-doc:v1"),
                        _reference("unknown-doc", "unknown-doc:v2"),
                    ],
                },
            ],
            "document_structures": [provided],
        },
        SkillContext(
            run_id="mixed-source-fallback",
            request=SkillRequest.create(),
        ),
    )

    structures = result["document_structures"]
    assert result["block_projection_audit"]["candidate_projection"][
        "structure_source"
    ] == "mixed"
    assert provided in structures
    fallback = next(
        structure
        for structure in structures
        if structure.get("metadata", {}).get("integration_source")
        == "legacy_section_text_fallback"
    )
    assert fallback["metadata"]["source_identity_status"] == "unverified"
    assert fallback["document_id"].startswith("unverified-section-")
    assert fallback["source_version"] == "unverified"
    assert fallback["blocks"][0]["raw_text"] == legacy_text
    assert fallback["blocks"][0]["source_references"] == []


def test_legacy_page_three_excerpt_coordinates_remain_section_relative() -> None:
    clause = "投标人须提供有效营业执照。"
    original_reference = {
        "document_id": "excerpt-doc",
        "source_version": "excerpt-doc:v1",
        "page": 3,
        "locator": "excerpt-doc:p3",
        "quote": clause,
    }
    result = RegistryTenderDecompositionBackend().run(
        {
            "sections": [
                {
                    "file_id": "excerpt-doc",
                    "source_version": "excerpt-doc:v1",
                    "title": "legacy.pdf",
                    "content": clause,
                    "source_references": [original_reference],
                }
            ]
        },
        SkillContext(
            run_id="legacy-page-three-excerpt",
            request=SkillRequest.create(),
        ),
    )

    fallback = result["document_structures"][0]
    block = fallback["blocks"][0]
    assert fallback["document_id"] == "excerpt-doc"
    assert fallback["source_version"] == "excerpt-doc:v1"
    assert fallback["source_coordinate_status"] == "section_relative_unverified"
    assert fallback["source_coordinate_scope"] == "section_relative"
    assert fallback["metadata"]["source_references_status"] == "diagnostic_only"
    assert fallback["metadata"]["source_references_diagnostic_only"] == [
        original_reference
    ]
    assert fallback["pages"][0]["page_number"] == 1
    assert fallback["pages"][0]["page_number_scope"] == "section_relative"
    assert block["source_span"]["page_number"] == 1
    assert block["source_coordinate_status"] == "section_relative_unverified"
    assert block["source_coordinate_scope"] == "section_relative"
    assert block["source_span_coordinate_status"] == "section_relative_unverified"
    assert block["source_span_scope"] == "section_relative"
    assert block["source_references"] == []

    candidate = result["block_projection_audit"]["candidate_projection"][
        "candidates"
    ][0]
    assert candidate["source_mapping_status"] == "unmapped"
    assert candidate["source_block_ids"] == []

    mapped, status, reason = _candidate_source_blocks(
        clause,
        [
            {
                **original_reference,
                "page": 1,
                "locator": "excerpt-doc:p1:l1",
                "line_number": 1,
            }
        ],
        [fallback],
    )
    assert mapped == []
    assert status == "unmapped"
    assert reason == "matching block has section-relative unverified coordinates"
    block_audit = result["block_projection_audit"]["candidate_projection"][
        "blocks"
    ][0]
    assert block_audit["filter_reason"] == "source_coordinates_unverified"


def test_unknown_same_title_fallback_sections_get_distinct_ids() -> None:
    clause = "投标人须提供有效营业执照。"
    result = RegistryTenderDecompositionBackend().run(
        {
            "sections": [
                {"title": "legacy.pdf", "content": clause},
                {"title": "legacy.pdf", "content": clause},
            ]
        },
        SkillContext(
            run_id="same-title-legacy-sections",
            request=SkillRequest.create(),
        ),
    )

    fallbacks = [
        structure
        for structure in result["document_structures"]
        if structure.get("metadata", {}).get("integration_source")
        == "legacy_section_text_fallback"
    ]
    assert len(fallbacks) == 2
    assert fallbacks[0]["document_id"] != fallbacks[1]["document_id"]
    assert fallbacks[0]["blocks"][0]["block_id"] != fallbacks[1]["blocks"][0][
        "block_id"
    ]
    assert all(
        structure["source_coordinate_status"] == "section_relative_unverified"
        for structure in fallbacks
    )


def test_decomposition_normalization_retains_input_structures() -> None:
    structure = _structure("normalization-doc", "normalization-doc:v1", "原文")
    normalized = _normalize_decomposition_output(
        {
            "requirements": [],
            "scoring_items": [],
            "document_structures": [],
        },
        project_id="normalization-project",
        document_structures=[structure],
    )

    assert normalized["document_structures"] == [structure]
