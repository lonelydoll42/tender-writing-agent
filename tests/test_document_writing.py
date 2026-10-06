from __future__ import annotations

from types import SimpleNamespace
from typing import Any, Mapping, Sequence

import pytest

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import SkillRequest
from qiaowenshu_agent.skills.document_writing import DocumentWritingSkill
from qiaowenshu_agent.skills.document_writing.skill import (
    _parse_input,
    _select_sections,
)


class FakeWritingLLM:
    config = SimpleNamespace(model_for=lambda purpose: "qwen-max")

    def __init__(self) -> None:
        self.calls: list[Sequence[Mapping[str, str]]] = []

    async def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        purpose: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        self.calls.append(messages)
        return (
            {
                "section_id": "implementation",
                "title": "项目实施方案",
                "content_markdown": "我方将根据招标要求制定实施计划。[待补材料]",
                "evidence_used": [],
                "unknowns": ["项目团队名单和人员证书待确认"],
                "risk_flags": [],
                "requirement_coverage": ["tech-1"],
                "scoring_coverage": ["score-1"],
            },
            SimpleNamespace(usage={"total_tokens": 42}),
        )


class FallbackWritingLLM(FakeWritingLLM):
    async def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        purpose: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        return (
            {"requirement_id": "tech-1", "page": 8, "quote": "原文"},
            SimpleNamespace(usage={"total_tokens": 12}),
        )

    async def complete(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        purpose: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        return SimpleNamespace(
            content="## 实施方案\n\n根据招标文件要求编制实施计划。",
            usage={"total_tokens": 18},
        )


def _context() -> SkillContext:
    return SkillContext(run_id="run-writing", request=SkillRequest.create())


def _scope_test_input() -> dict[str, Any]:
    return {
        "project_id": "project-scope",
        "sections": [
            {
                "section_id": "implementation",
                "title": "实施方案",
                "kind": "technical",
            },
            {
                "section_id": "testing",
                "title": "测试方案",
                "kind": "technical",
            },
            {
                "section_id": "commercial",
                "title": "商务响应",
                "kind": "commercial",
            },
        ],
    }


@pytest.mark.parametrize(
    ("include_scope", "scope"),
    [
        (False, None),
        (True, None),
        (True, ""),
        (True, []),
    ],
)
def test_empty_writing_scope_defaults_to_all_sections(
    include_scope: bool,
    scope: Any,
) -> None:
    data = _scope_test_input()
    if include_scope:
        data["writing_scope"] = scope

    selected = _select_sections(_parse_input(data))

    assert [section["section_id"] for section in selected] == [
        "implementation",
        "testing",
        "commercial",
    ]


@pytest.mark.parametrize(
    ("scope", "expected"),
    [
        (["implementation"], ["implementation"]),
        (["technical"], ["implementation", "testing"]),
    ],
)
def test_valid_writing_scope_selects_requested_sections(
    scope: list[str],
    expected: list[str],
) -> None:
    data = _scope_test_input()
    data["writing_scope"] = scope

    selected = _select_sections(_parse_input(data))

    assert [section["section_id"] for section in selected] == expected


@pytest.mark.asyncio
@pytest.mark.parametrize("scope", [123, {"section": "implementation"}])
async def test_invalid_writing_scope_type_fails_before_model_call(scope: Any) -> None:
    llm = FakeWritingLLM()
    result = await DocumentWritingSkill(llm=llm).execute(
        SkillRequest.create({**_scope_test_input(), "writing_scope": scope}),
        _context(),
    )

    assert result.status == "error"
    assert result.error_code == "INVALID_DOCUMENT_WRITING_INPUT"
    assert llm.calls == []


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "scope",
    ["does-not-match", ["implementation", "does-not-match"]],
)
async def test_unmatched_writing_scope_fails_before_model_call(scope: Any) -> None:
    llm = FakeWritingLLM()
    result = await DocumentWritingSkill(llm=llm).execute(
        SkillRequest.create({**_scope_test_input(), "writing_scope": scope}),
        _context(),
    )

    assert result.status == "error"
    assert result.error_code == "DOCUMENT_WRITING_SCOPE_INVALID"
    assert llm.calls == []


@pytest.mark.asyncio
async def test_document_writing_keeps_missing_evidence_reviewable() -> None:
    llm = FakeWritingLLM()
    skill = DocumentWritingSkill(llm=llm)
    result = await skill.execute(
        SkillRequest.create(
            {
                "project_id": "project-1",
                "tender_profile": {"project_name": "测试项目"},
                "sections": [
                    {
                        "section_id": "implementation",
                        "title": "项目实施方案",
                        "kind": "technical",
                    }
                ],
                "requirements": [
                    {
                        "requirement_id": "tech-1",
                        "category": "technical",
                        "title": "项目实施",
                        "description": "提供项目组织和进度计划",
                        "source_references": [{"document_id": "tender.pdf", "page": 7}],
                    }
                ],
                "scoring_items": [
                    {
                        "item_id": "score-1",
                        "title": "实施方案",
                        "max_score": 10,
                    }
                ],
                "evidence_matches": [
                    {
                        "requirement_id": "tech-1",
                        "status": "missing",
                        "reason": "未提供项目团队材料",
                    }
                ],
            }
        ),
        _context(),
    )

    assert result.status == "partial"
    assert result.data["needs_human_review"] is True
    assert result.data["business_status"] == "needs_review"
    assert result.data["submission_allowed"] is False
    assert result.data["summary"]["generated_sections"] == 1
    assert result.data["missing_materials"][0]["requirement_id"] == "tech-1"
    assert result.data["chapters"][0]["source_references"][0]["page"] == 7
    assert "qwen-max" == result.data["model"]
    assert "项目实施方案" in result.data["markdown"]
    assert llm.calls
    assert "绝不虚构企业资质" in llm.calls[0][0]["content"]


@pytest.mark.asyncio
async def test_document_writing_without_llm_is_blocked() -> None:
    result = await DocumentWritingSkill().execute(
        SkillRequest.create(
            {
                "project_id": "project-1",
                "requirements": [
                    {
                        "requirement_id": "r1",
                        "title": "技术要求",
                        "description": "满足技术要求",
                    }
                ],
            }
        ),
        _context(),
    )

    assert result.status == "blocked"
    assert result.error_code == "LLM_BACKEND_NOT_CONFIGURED"


@pytest.mark.asyncio
async def test_document_writing_falls_back_from_citation_json_to_markdown() -> None:
    result = await DocumentWritingSkill(llm=FallbackWritingLLM()).execute(
        SkillRequest.create(
            {
                "project_id": "project-1",
                "sections": [
                    {
                        "section_id": "implementation",
                        "title": "项目实施方案",
                        "kind": "technical_response",
                    }
                ],
                "requirements": [
                    {
                        "requirement_id": "tech-1",
                        "category": "technical",
                        "title": "实施方案",
                        "description": "提供实施方案",
                    }
                ],
            }
        ),
        _context(),
    )

    assert result.status == "partial"
    assert result.data["chapters"][0]["content_markdown"].startswith("## 实施方案")
    assert "structured_output_fallback" in result.data["chapters"][0]["risk_flags"]
    assert result.data["needs_human_review"] is True
    assert result.data["submission_allowed"] is False
    assert result.data["business_status"] == "needs_review"
