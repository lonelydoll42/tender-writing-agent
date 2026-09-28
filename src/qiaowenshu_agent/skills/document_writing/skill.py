"""Generate reviewable tender chapters through the injected Qwen client."""

from __future__ import annotations

import inspect
import json
from typing import Any, Mapping, Protocol, Sequence

from qiaowenshu_agent.core.context import SkillContext
from qiaowenshu_agent.core.contracts import (
    Skill,
    SkillManifest,
    SkillRequest,
    SkillResult,
)
from qiaowenshu_agent.llm import LLMError, parse_json_object


class WritingLLM(Protocol):
    async def complete_json(
        self,
        messages: Sequence[Mapping[str, str]],
        *,
        purpose: str,
        model: str | None = None,
        temperature: float | None = None,
        max_tokens: int | None = None,
    ) -> Any:
        ...


MANIFEST = SkillManifest(
    name="document-writing",
    version="0.1.0",
    description=(
        "Write evidence-grounded tender chapters from parsed requirements "
        "and bidder materials."
    ),
    input_schema={
        "type": "object",
        "required": ["project_id"],
        "properties": {
            "project_id": {"type": "string"},
            "tender_profile": {"type": "object"},
            "sections": {"type": "array", "items": {"type": "object"}},
            "requirements": {"type": "array", "items": {"type": "object"}},
            "scoring_items": {
                "type": "array",
                "items": {"type": "object"},
            },
            "bidder_profile": {"type": "object"},
            "materials": {"type": "array", "items": {"type": "object"}},
            "evidence_matches": {
                "type": "array",
                "items": {"type": "object"},
            },
            "tender_text": {"type": "string"},
            "writing_scope": {"type": ["string", "array"]},
            "model": {"type": "string"},
            "max_sections": {"type": "integer"},
            "max_tokens": {"type": "integer"},
        },
    },
    output_schema={
        "type": "object",
        "required": [
            "project_id",
            "chapters",
            "markdown",
            "needs_human_review",
        ],
    },
    capabilities=(
        "tender.draft",
        "tender.technical_writing",
        "tender.commercial_writing",
        "tender.evidence_grounded_generation",
    ),
    required_permissions=("document.read", "document.write"),
)


class DocumentWritingSkill(Skill):
    manifest = MANIFEST

    def __init__(self, *, llm: WritingLLM | None = None) -> None:
        self.llm = llm

    async def execute(
        self,
        request: SkillRequest,
        context: SkillContext,
    ) -> SkillResult:
        try:
            payload = _parse_input(request.input)
        except (TypeError, ValueError) as exc:
            return SkillResult.failure(
                message=str(exc),
                error_code="INVALID_DOCUMENT_WRITING_INPUT",
            )

        llm = context.get_service("llm", self.llm)
        if llm is None:
            return SkillResult.blocked(
                message="Qwen LLM backend is not configured",
                error_code="LLM_BACKEND_NOT_CONFIGURED",
            )
        if not hasattr(llm, "complete_json"):
            return SkillResult.failure(
                message="configured LLM backend does not support JSON completion",
                error_code="LLM_BACKEND_INVALID",
            )

        sections = _select_sections(payload)
        if not sections:
            return SkillResult.failure(
                message=(
                    "no writable tender sections were supplied; provide "
                    "sections or tender requirements"
                ),
                error_code="DOCUMENT_WRITING_OUTLINE_EMPTY",
            )

        generated: list[dict[str, Any]] = []
        failures: list[str] = []
        warnings: list[str] = []
        total_usage: dict[str, int] = {}
        configured_model = _configured_model(
            llm,
            payload.get("model"),
            purpose="document_writing",
        )
        models_used: dict[str, str] = {}
        for section in sections:
            max_tokens = payload["max_tokens"]
            if not context.budget.reserve_tokens(max_tokens):
                failures.append(f"{section['section_id']}: token budget exhausted")
                break
            purpose = _purpose_for_section(section)
            try:
                raw, usage = await _call_section(
                    llm,
                    payload,
                    section,
                    purpose=purpose,
                    model=payload.get("model"),
                )
                actual_tokens = _usage_total(usage) or max_tokens
                context.budget.commit_tokens(actual_tokens, estimated=max_tokens)
                _merge_usage(total_usage, usage)
                chapter = _normalize_chapter(raw, payload, section)
                generated.append(chapter)
                models_used[purpose] = _configured_model(
                    llm,
                    payload.get("model"),
                    purpose=purpose,
                )
            except LLMError as exc:
                context.budget.commit_tokens(0, estimated=max_tokens)
                failures.append(f"{section['section_id']}: {exc}")
                if getattr(exc, "retryable", False):
                    warnings.append(str(exc))
            except (TypeError, ValueError, KeyError) as exc:
                context.budget.commit_tokens(0, estimated=max_tokens)
                failures.append(f"{section['section_id']}: {exc}")

        if not generated:
            message = "document writing did not produce a chapter"
            if failures:
                message = f"{message}: {failures[0]}"
            return SkillResult.failure(
                message=message,
                error_code="DOCUMENT_WRITING_FAILED",
                retryable=bool(failures),
                warnings=warnings,
                usage=total_usage,
            )

        markdown = _build_markdown(payload, generated, failures)
        missing_materials = _missing_materials(payload)
        chapter_unknowns = [
            unknown
            for chapter in generated
            for unknown in chapter["unknowns"]
        ]
        needs_review = bool(failures or missing_materials or chapter_unknowns)
        if failures:
            warnings.append(f"有 {len(failures)} 个章节未生成")
        if missing_materials:
            warnings.append("存在未匹配或未提供的证明材料，生成内容必须人工核验")
        data = {
            "project_id": payload["project_id"],
            "model": configured_model,
            "model_purpose": "document_writing",
            "models_used": models_used,
            "chapters": generated,
            "markdown": markdown,
            "missing_materials": missing_materials,
            "unsupported_claims": chapter_unknowns,
            "needs_human_review": needs_review,
            "summary": {
                "requested_sections": len(sections),
                "generated_sections": len(generated),
                "failed_sections": len(failures),
                "unknown_count": len(chapter_unknowns),
            },
        }
        artifacts = [
            {
                "artifact_type": "tender_draft",
                "format": "markdown",
                "filename": f"{payload['project_id']}-投标文件草案.md",
                "content": markdown,
            }
        ]
        if needs_review:
            return SkillResult.partial(
                data,
                message="投标文件草案已生成，但仍有内容需要人工核验",
                warnings=warnings,
                artifacts=artifacts,
                usage=total_usage,
            )
        return SkillResult.success(
            data,
            message="投标文件草案生成完成",
            warnings=warnings,
            artifacts=artifacts,
            usage=total_usage,
        )


def _parse_input(data: Mapping[str, Any]) -> dict[str, Any]:
    if not isinstance(data, Mapping):
        raise TypeError("document writing input must be an object")
    profile = _mapping(data.get("tender_profile"))
    project_id = str(data.get("project_id") or profile.get("project_id") or "").strip()
    if not project_id:
        raise ValueError("project_id is required")
    sections = _mapping_list(data.get("sections"), "sections")
    requirements = _mapping_list(data.get("requirements"), "requirements")
    scoring_items = _mapping_list(data.get("scoring_items"), "scoring_items")
    materials = _mapping_list(data.get("materials"), "materials")
    bidder_profile = _mapping(data.get("bidder_profile"))
    if not materials and bidder_profile.get("materials"):
        materials = _mapping_list(bidder_profile.get("materials"), "materials")
    matches = _mapping_list(data.get("evidence_matches"), "evidence_matches")
    scope = data.get("writing_scope")
    if isinstance(scope, str):
        writing_scope = [item.strip() for item in scope.split(",") if item.strip()]
    elif isinstance(scope, (list, tuple)):
        writing_scope = [str(item).strip() for item in scope if str(item).strip()]
    else:
        writing_scope = []
    max_sections = _positive_int(data.get("max_sections"), default=12)
    max_tokens = _positive_int(data.get("max_tokens"), default=3500)
    return {
        "project_id": project_id,
        "tender_profile": profile,
        "sections": sections,
        "requirements": requirements,
        "scoring_items": scoring_items,
        "bidder_profile": bidder_profile,
        "materials": materials,
        "evidence_matches": matches,
        "tender_text": str(data.get("tender_text") or data.get("source_text") or ""),
        "writing_scope": writing_scope,
        "model": str(data.get("model") or "").strip() or None,
        "max_sections": max_sections,
        "max_tokens": max_tokens,
        "style": str(data.get("style") or "正式、准确、可审查").strip(),
    }


def _select_sections(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    sections = [dict(item) for item in payload["sections"]]
    if not sections:
        sections = _derive_outline(payload)
    scope = {str(item).casefold() for item in payload["writing_scope"]}
    if scope:
        filtered = [
            section
            for section in sections
            if _section_matches_scope(section, scope)
        ]
        if filtered:
            sections = filtered
    limit = int(payload["max_sections"])
    return sections[:limit]


def _derive_outline(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    requirements = payload["requirements"]
    scoring_items = payload["scoring_items"]
    outline = [
        {
            "section_id": "project-understanding",
            "title": "项目理解与需求响应",
            "kind": "technical",
            "requirement_categories": ["technical", "compliance"],
        },
        {
            "section_id": "overall-solution",
            "title": "总体技术方案",
            "kind": "technical",
            "requirement_categories": ["technical"],
        },
        {
            "section_id": "implementation-plan",
            "title": "项目实施方案",
            "kind": "technical",
            "scoring_keywords": ["实施", "进度", "组织", "质量", "风险"],
        },
        {
            "section_id": "quality-and-risk",
            "title": "质量管理与风险控制",
            "kind": "technical",
            "scoring_keywords": ["质量", "风险"],
        },
        {
            "section_id": "training-and-support",
            "title": "培训与售后服务",
            "kind": "technical",
            "scoring_keywords": ["培训", "售后", "服务"],
        },
        {
            "section_id": "technical-response",
            "title": "技术需求逐项响应",
            "kind": "technical_response",
            "requirement_categories": ["technical", "compliance"],
        },
        {
            "section_id": "commercial-response",
            "title": "商务条款逐项响应",
            "kind": "commercial_response",
            "requirement_categories": ["commercial", "qualification", "format"],
        },
    ]
    if not requirements and not scoring_items:
        return []
    return outline


async def _call_section(
    llm: WritingLLM,
    payload: Mapping[str, Any],
    section: Mapping[str, Any],
    *,
    purpose: str,
    model: str | None,
) -> tuple[dict[str, Any], dict[str, int]]:
    context_payload = _section_context(payload, section)
    messages = [
        {
            "role": "system",
            "content": (
                "你是政府采购和企业投标文件撰写专家。你只可以使用用户提供的招标要求、"
                "评分标准、企业材料和原文证据。绝不虚构企业资质、案例、人员、参数、"
                "金额、日期或服务承诺。缺少证据时必须在正文写明[待补材料]或[待确认]，"
                "并在unknowns中列出。严格保持招标文件中的数字、单位、期限和条件。"
                "请只返回一个JSON对象，不要返回Markdown代码围栏或解释文字。JSON字段为："
                "section_id、title、content_markdown、evidence_used、unknowns、risk_flags、"
                "requirement_coverage、scoring_coverage。content_markdown应是可直接进入标书"
                "的正式正文，使用清晰的小标题、列表或表格。"
            ),
        },
        {
            "role": "user",
            "content": json.dumps(
                {
                    "task": "撰写一个投标文件章节",
                    "style": payload["style"],
                    "section": dict(section),
                    "available_context": context_payload,
                    "output_constraints": {
                        "no_unsupported_facts": True,
                        "mark_missing_evidence": True,
                        "preserve_source_values": True,
                    },
                },
                ensure_ascii=False,
                default=str,
            ),
        },
    ]
    raw = llm.complete_json(
        messages,
        purpose=purpose,
        model=model,
        temperature=0.2,
        max_tokens=int(payload["max_tokens"]),
    )
    if inspect.isawaitable(raw):
        raw = await raw
    usage: dict[str, int] = {}
    if isinstance(raw, tuple) and len(raw) == 2:
        body, completion = raw
        usage = _usage_mapping(getattr(completion, "usage", None))
    else:
        body = raw
    if not isinstance(body, Mapping):
        raise ValueError("LLM writing response must be an object")
    body_dict = dict(body)
    if _has_writing_content(body_dict) or not hasattr(llm, "complete"):
        return body_dict, usage

    # Some Qwen reasoning models honor JSON mode but still return a citation
    # object when the context is long. A plain-text retry is safer than
    # treating that citation object as a chapter.
    fallback_messages = [
        {
            "role": "system",
            "content": (
                "你是投标文件撰写专家。根据用户提供的上下文直接写出一个可进入标书的"
                "Markdown章节正文。只使用已提供事实，不得虚构企业资质、案例、人员、"
                "参数、金额、日期或服务承诺。缺少证据时写[待补材料]或[待确认]。"
                "只输出正文，不要输出JSON、证据对象、分析过程或解释。"
            ),
        },
        {
            "role": "user",
            "content": (
                messages[1]["content"]
                + "\n请直接输出章节正文，正文不能为空。"
            ),
        },
    ]
    fallback = llm.complete(
        fallback_messages,
        purpose=purpose,
        model=model,
        temperature=0.2,
        max_tokens=int(payload["max_tokens"]),
    )
    if inspect.isawaitable(fallback):
        fallback = await fallback
    fallback_usage = _usage_mapping(getattr(fallback, "usage", None))
    _merge_usage(usage, fallback_usage)
    text = str(getattr(fallback, "content", fallback) or "").strip()
    if not text:
        raise ValueError("LLM writing text fallback is empty")
    try:
        fallback_json = parse_json_object(text)
    except LLMError:
        fallback_json = {}
    if _has_writing_content(fallback_json):
        return dict(fallback_json), usage
    return {
        "section_id": section["section_id"],
        "title": section.get("title") or "未命名章节",
        "content_markdown": _strip_code_fence(text),
        "evidence_used": [],
        "unknowns": ["模型未按结构化格式返回，正文使用文本回退，需人工复核"],
        "risk_flags": ["structured_output_fallback"],
        "requirement_coverage": [],
        "scoring_coverage": [],
    }, usage


def _section_context(
    payload: Mapping[str, Any],
    section: Mapping[str, Any],
) -> dict[str, Any]:
    requirements = payload["requirements"]
    scoring_items = payload["scoring_items"]
    requirement_ids = _string_list(
        section.get("requirement_ids") or section.get("linked_requirement_ids")
    )
    scoring_ids = _string_list(
        section.get("scoring_item_ids") or section.get("linked_scoring_item_ids")
    )
    categories = {str(item) for item in section.get("requirement_categories", [])}
    keywords = _string_list(section.get("scoring_keywords"))
    if requirement_ids:
        selected_requirements = [
            item
            for item in requirements
            if str(item.get("requirement_id") or item.get("id")) in requirement_ids
        ]
    elif categories:
        selected_requirements = [
            item for item in requirements if str(item.get("category")) in categories
        ]
    else:
        selected_requirements = requirements[:80]
    if scoring_ids:
        selected_scoring = [
            item
            for item in scoring_items
            if str(item.get("item_id") or item.get("id")) in scoring_ids
        ]
    elif keywords:
        selected_scoring = [
            item
            for item in scoring_items
            if any(
                keyword in str(item.get("title") or item.get("criteria") or "")
                for keyword in keywords
            )
        ]
    else:
        selected_scoring = scoring_items[:80]
    return {
        "tender_profile": payload["tender_profile"],
        "requirements": selected_requirements,
        "scoring_items": selected_scoring,
        "bidder_profile": payload["bidder_profile"],
        "materials": payload["materials"][:100],
        "evidence_matches": payload["evidence_matches"][:100],
        "source_excerpt": _clip(payload["tender_text"], 24000),
        "source_section": _clip(str(section.get("source_content") or ""), 12000),
    }


def _normalize_chapter(
    raw: Mapping[str, Any],
    payload: Mapping[str, Any],
    section: Mapping[str, Any],
) -> dict[str, Any]:
    content = str(raw.get("content_markdown") or raw.get("content") or "").strip()
    if not content:
        raise ValueError("LLM writing response content_markdown is empty")
    requirement_coverage = _string_list(raw.get("requirement_coverage"))
    scoring_coverage = _string_list(raw.get("scoring_coverage"))
    unknowns = _string_list(raw.get("unknowns"))
    risk_flags = _string_list(raw.get("risk_flags"))
    source_references = _chapter_references(
        payload,
        section,
        requirement_coverage,
        scoring_coverage,
    )
    return {
        "section_id": str(raw.get("section_id") or section["section_id"]),
        "title": str(raw.get("title") or section.get("title") or "未命名章节"),
        "kind": str(section.get("kind") or "technical"),
        "content_markdown": content,
        "evidence_used": _string_list(raw.get("evidence_used")),
        "unknowns": unknowns,
        "risk_flags": risk_flags,
        "requirement_coverage": requirement_coverage,
        "scoring_coverage": scoring_coverage,
        "source_references": source_references,
    }


def _has_writing_content(value: Mapping[str, Any]) -> bool:
    content = value.get("content_markdown") or value.get("content") or ""
    return bool(str(content).strip())


def _strip_code_fence(value: str) -> str:
    text = value.strip()
    if text.startswith("```") and text.endswith("```"):
        lines = text.splitlines()
        if len(lines) >= 3:
            return "\n".join(lines[1:-1]).strip()
    return text


def _chapter_references(
    payload: Mapping[str, Any],
    section: Mapping[str, Any],
    requirement_ids: list[str],
    scoring_ids: list[str],
) -> list[dict[str, Any]]:
    refs: list[dict[str, Any]] = []
    seen: set[str] = set()
    selected = set(requirement_ids) | set(scoring_ids)
    for item in payload["requirements"] + payload["scoring_items"]:
        item_id = str(
            item.get("requirement_id")
            or item.get("item_id")
            or item.get("id")
            or ""
        )
        if selected and item_id not in selected:
            continue
        for reference in item.get("source_references") or []:
            if not isinstance(reference, Mapping):
                continue
            key = json.dumps(
                dict(reference), ensure_ascii=False, sort_keys=True, default=str
            )
            if key not in seen:
                seen.add(key)
                refs.append(dict(reference))
    for reference in section.get("source_references") or []:
        if not isinstance(reference, Mapping):
            continue
        key = json.dumps(
            dict(reference), ensure_ascii=False, sort_keys=True, default=str
        )
        if key not in seen:
            seen.add(key)
            refs.append(dict(reference))
    return refs


def _build_markdown(
    payload: Mapping[str, Any],
    chapters: list[Mapping[str, Any]],
    failures: list[str],
) -> str:
    profile = payload["tender_profile"]
    title = str(profile.get("project_name") or payload["project_id"])
    lines = [f"# {title} 投标文件草案", "", f"项目编号：{payload['project_id']}", ""]
    lines.append(
        "> 本文件由 Agent 生成，提交前必须完成证据、合规、签章和金额人工复核。"
    )
    lines.append("")
    for index, chapter in enumerate(chapters, start=1):
        lines.extend(
            [
                f"## {index}. {chapter['title']}",
                "",
                chapter["content_markdown"],
                "",
            ]
        )
        if chapter["unknowns"]:
            lines.extend(["**待补材料/待确认：**", ""])
            lines.extend(f"- {item}" for item in chapter["unknowns"])
            lines.append("")
    if failures:
        lines.extend(["## 生成失败章节", ""])
        lines.extend(f"- {failure}" for failure in failures)
        lines.append("")
    return "\n".join(lines).strip() + "\n"


def _missing_materials(payload: Mapping[str, Any]) -> list[dict[str, Any]]:
    missing: list[dict[str, Any]] = []
    for match in payload["evidence_matches"]:
        status = str(match.get("status") or "").lower()
        if status in {"matched", "pass"}:
            continue
        missing.append(
            {
                "requirement_id": str(match.get("requirement_id") or ""),
                "status": status or "unknown",
                "reason": str(match.get("reason") or "未提供有效证据"),
                "material_id": match.get("material_id"),
            }
        )
    return missing


def _configured_model(llm: Any, override: str | None, *, purpose: str) -> str:
    if override:
        return override
    config = getattr(llm, "config", None)
    if config is not None and hasattr(config, "model_for"):
        return str(config.model_for(purpose))
    return "configured-llm"


def _purpose_for_section(section: Mapping[str, Any]) -> str:
    kind = str(section.get("kind") or "").casefold()
    title = str(section.get("title") or "").casefold()
    if "commercial" in kind or "商务" in title:
        return "commercial_response"
    if "technical" in kind or "技术" in title:
        return "technical_response"
    return "document_writing"


def _usage_mapping(value: Any) -> dict[str, int]:
    if not isinstance(value, Mapping):
        return {}
    result: dict[str, int] = {}
    for key in ("prompt_tokens", "completion_tokens", "total_tokens"):
        if value.get(key) is None:
            continue
        try:
            result[key] = max(int(value[key]), 0)
        except (TypeError, ValueError):
            continue
    return result


def _usage_total(value: Mapping[str, int]) -> int:
    if value.get("total_tokens") is not None:
        return int(value["total_tokens"])
    return int(value.get("prompt_tokens", 0) + value.get("completion_tokens", 0))


def _merge_usage(target: dict[str, int], value: Mapping[str, int]) -> None:
    for key, amount in value.items():
        target[key] = target.get(key, 0) + int(amount)


def _mapping(value: Any) -> dict[str, Any]:
    return dict(value) if isinstance(value, Mapping) else {}


def _mapping_list(value: Any, field_name: str) -> list[dict[str, Any]]:
    if value is None:
        return []
    if not isinstance(value, (list, tuple)):
        raise ValueError(f"{field_name} must be a list")
    result: list[dict[str, Any]] = []
    for item in value:
        if not isinstance(item, Mapping):
            raise ValueError(f"{field_name} items must be objects")
        result.append(dict(item))
    return result


def _string_list(value: Any) -> list[str]:
    if value is None:
        return []
    if isinstance(value, str):
        return [
            item.strip()
            for item in value.replace("，", ",").split(",")
            if item.strip()
        ]
    if isinstance(value, (list, tuple, set)):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _positive_int(value: Any, *, default: int) -> int:
    if value in (None, ""):
        return default
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"expected a positive integer, got {value}") from exc
    if parsed <= 0:
        raise ValueError("integer values must be positive")
    return parsed


def _clip(value: Any, limit: int) -> str:
    text = str(value or "")
    if len(text) <= limit:
        return text
    return text[:limit] + "\n[原文已截断，禁止据此推断未提供内容]"


def _section_matches_scope(section: Mapping[str, Any], scope: set[str]) -> bool:
    values = {
        str(section.get("kind") or "").casefold(),
        str(section.get("section_id") or "").casefold(),
        str(section.get("title") or "").casefold(),
    }
    return any(
        wanted in value or value in wanted
        for wanted in scope
        for value in values
        if wanted and value
    )
