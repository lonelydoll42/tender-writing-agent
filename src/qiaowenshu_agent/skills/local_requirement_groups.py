"""Conservative grouping of explicitly scoped numbered requirements."""

from __future__ import annotations

import re
from collections.abc import Mapping
from typing import Any

from qiaowenshu_agent.skills.local_requirement_logic import (
    build_local_requirement_rule,
)

_NUMBERED_LINE = re.compile(
    r"^\s*(?:(?P<paren>[（(]\d+[）)])\s*|"
    r"(?P<decimal>\d+(?:\.\d+)+)(?:[、.)）:：]|\s+)|"
    r"(?P<integer>\d+)[、.)）．:：])\s*(?P<body>.*)$"
)
_FRAME = re.compile(
    r"以下.{0,16}(?:任选一项|任一项|任一|任意一项|全部|各项|两项|条件)"
    r"|以下条件同时满足|以下各项均须满足|以下各项均应满足"
    r"|(?:\d+(?:\.\d+)*[、和及与\s]*){2,}"
    r"(?:为|属于).{0,8}(?:AND|AND关系|同时满足)",
    re.IGNORECASE,
)
_FRAME_ITEM_COUNT = re.compile(
    r"以下\s*(?:(?:共|有|条件(?:中|中的)?|所列(?:的)?|列出的?)\s*)?"
    r"(?P<count>[0-9]+|"
    r"[零〇一二两三四五六七八九十百千万亿壹贰貳叁參肆伍陆陸柒捌玖拾佰仟萬億廿卅]+)"
    r"(?P<ambiguous>\s*(?:或者|或|至|到|[-~～])\s*"
    r"(?:[0-9]+|[零〇一二两三四五六七八九十百千万亿壹贰貳叁參肆伍陆陸柒捌玖拾佰仟萬億廿卅]+))?"
    r"\s*项"
)
_OBLIGATION = re.compile(
    r"须|应|需|必须|提供|提交|具备|满足|符合|取得|持有|达到|不得|不低于"
)
_CHILD_OBLIGATION = re.compile(
    r"提供|提交|具备|具有|满足|符合|取得|持有|达到|缴纳|依法登记"
)
_NON_REQUIREMENT_CONTEXT = re.compile(r"评分|评审|得分|加分|技术方案|选型|品牌|型号")
_NON_REQUIREMENT_SECTION = re.compile(r"评分|评审|投标文件格式|材料清单|材料目录")
_EXPLICIT_ALL = re.compile(r"全部|各项|同时满足|均须|均应|AND", re.I)
_EXPLICIT_ANY = re.compile(r"任选一项|任一项|任一|任意一项|或", re.I)


def group_requirement_records(
    sections: list[Any],
    records: list[tuple[str, list[dict]]],
) -> list[tuple[str, list[dict], dict | None]]:
    """Group only uniquely sourced, explicitly framed numbered sibling clauses.

    Uncertain provenance, numbering, scope, or obligation intent leaves records
    untouched. References are copied from the input records, never synthesized
    from the combined display description.
    """

    result = [
        (text, [dict(ref) for ref in refs], None) for text, refs in records
    ]
    if not sections or not records:
        return result

    owners = _record_owners(sections, records)
    by_owner: dict[int, list[int]] = {}
    for index, owner in enumerate(owners):
        if owner is not None:
            by_owner.setdefault(owner, []).append(index)

    for owner, indices in by_owner.items():
        _group_section(result, records, indices, sections[owner])
    return [item for item in result if item[0]]


def _record_owners(
    sections: list[Any], records: list[tuple[str, list[dict]]]
) -> list[int | None]:
    section_keys = [_section_keys(section) for section in sections]
    if len(sections) == 1 and all(not refs for _, refs in records):
        if _records_appear_in_section(records, sections[0]):
            return [0] * len(records)
    owners: list[int | None] = []
    for _text, refs in records:
        record_keys = {_source_key(ref) for ref in refs if _source_key(ref)}
        if not record_keys:
            owners.append(None)
            continue
        matches = [
            index
            for index, keys in enumerate(section_keys)
            if record_keys & keys
        ]
        owners.append(matches[0] if len(matches) == 1 else None)
    return owners


def _records_appear_in_section(
    records: list[tuple[str, list[dict]]], section: Any
) -> bool:
    if isinstance(section, Mapping):
        content = str(section.get("content") or section.get("text") or "")
    else:
        content = str(section)
    searchable = re.sub(r"\s+", " ", content)
    offset = 0
    for text, _refs in records:
        candidate = re.sub(r"\s+", " ", text).strip()
        position = searchable.find(candidate, offset)
        if position < 0:
            candidate = re.sub(r"^\s*\d+(?:\.\d+)*[、.)）．:：]?\s*", "", candidate)
            position = searchable.find(candidate, offset) if candidate else -1
        if position < 0:
            return False
        offset = position + len(candidate)
    return True


def _section_keys(section: Any) -> set[tuple[str, str]]:
    if not isinstance(section, Mapping):
        return set()
    refs = section.get("source_references") or []
    if not isinstance(refs, (list, tuple)):
        return set()
    return {
        key
        for ref in refs
        if isinstance(ref, Mapping)
        if (key := _source_key(ref))
    }


def _source_key(reference: Mapping[str, Any]) -> tuple[str, str] | None:
    document = str(reference.get("document_id") or "").strip()
    version = str(
        reference.get("source_version")
        or reference.get("source_file_version")
        or ""
    ).strip()
    if not document or not version:
        return None
    return document, version


def _group_section(
    result: list[tuple[str, list[dict], dict | None]],
    records: list[tuple[str, list[dict]]],
    indices: list[int],
    section: Any,
) -> None:
    section_context = ""
    if isinstance(section, Mapping):
        section_context = " ".join(
            str(section.get(key) or "")
            for key in ("title", "kind")
        )
    if _NON_REQUIREMENT_SECTION.search(section_context):
        return
    raw_content = ""
    if isinstance(section, Mapping):
        raw_content = str(section.get("content") or section.get("text") or "")
    scope_ids = _record_scope_ids(records, indices, raw_content)

    cursor = 0
    while cursor < len(indices):
        first_index = indices[cursor]
        numbered = _numbered_record(records[first_index])
        if numbered is None:
            cursor += 1
            continue
        label, _style = numbered
        parent = label.rpartition(".")[0] if "." in label else ""
        end = cursor + 1
        while end < len(indices):
            next_label = _numbered_record(records[indices[end]])
            if next_label is None:
                break
            next_parent = (
                next_label[0].rpartition(".")[0] if "." in next_label[0] else ""
            )
            if next_parent != parent or not _same_source_scope(
                records[first_index][1], records[indices[end]][1]
            ):
                break
            if scope_ids.get(indices[end]) != scope_ids.get(first_index):
                break
            end += 1
        if end - cursor < 2 or cursor == 0:
            cursor = max(end, cursor + 1)
            continue

        frame_index = indices[cursor - 1]
        frame_text = records[frame_index][0]
        frame_match = _FRAME.search(frame_text)
        children = indices[cursor:end]
        operator = _frame_operator(frame_text) if frame_match else None
        has_item_count, item_count = (
            _frame_item_count(frame_text) if frame_match else (False, None)
        )
        if has_item_count and item_count is None:
            cursor = end
            continue
        if item_count is not None:
            if len(children) < item_count or not _has_complete_numbered_prefix(
                records, children, item_count
            ):
                cursor = end
                continue
            children = children[:item_count]
        if (
            frame_match
            and operator
            and scope_ids.get(frame_index, -1) >= 0
            and scope_ids.get(first_index, -1) >= 0
            and (
                _OBLIGATION.search(frame_text)
                or all(
                    _CHILD_OBLIGATION.search(records[index][0])
                    for index in children
                )
            )
            and not _NON_REQUIREMENT_CONTEXT.search(frame_text)
            and _same_source_scope(
                records[frame_index][1], records[first_index][1]
            )
            and scope_ids.get(frame_index) == scope_ids.get(first_index)
            and (
                bool(raw_content)
                or _physically_contiguous(
                    records, [frame_index, *children]
                )
            )
        ):
            _emit_group(result, records, frame_index, children, operator)
        cursor = end


def _numbered_record(record: tuple[str, list[dict]]) -> tuple[str, str] | None:
    text, refs = record
    quotes = [
        str(ref.get("quote") or "").strip()
        for ref in refs
        if isinstance(ref, Mapping)
    ]
    if not quotes:
        quotes = [text.strip()]
    if not quotes:
        return None
    parsed = [_NUMBERED_LINE.match(quote) for quote in quotes]
    parsed = [item for item in parsed if item]
    if len(parsed) != len(quotes) or not parsed:
        return None
    labels = {
        (
            item.group("paren") or item.group("decimal") or item.group("integer"),
            "paren"
            if item.group("paren")
            else "decimal"
            if item.group("decimal")
            else "integer",
        )
        for item in parsed
    }
    if len(labels) != 1:
        return None
    label, style = labels.pop()
    if label.startswith(("(", "（")):
        label = label[1:-1]
    return label, style


def _same_source_scope(first: list[dict], second: list[dict]) -> bool:
    first_keys = {_source_key(ref) for ref in first if _source_key(ref)}
    second_keys = {_source_key(ref) for ref in second if _source_key(ref)}
    if not first and not second:
        return True
    return len(first_keys) == len(second_keys) == 1 and first_keys == second_keys


def _physically_contiguous(
    records: list[tuple[str, list[dict]]], indices: list[int]
) -> bool:
    positions: list[tuple[str, int, int]] = []
    for index in indices:
        refs = records[index][1]
        locators = {
            (
                _source_key(ref),
                int(match.group(1)),
                int(match.group(2)),
            )
            for ref in refs
            if (match := re.search(r":p(\d+):l(\d+)$", str(ref.get("locator") or "")))
            and _source_key(ref)
        }
        if len(locators) != 1:
            return False
        source, page, line = next(iter(locators))
        if source is None:
            return False
        positions.append((f"{source[0]}|{source[1]}", page, line))
    return all(
        first[0] == second[0]
        and first[1] == second[1]
        and second[2] == first[2] + 1
        for first, second in zip(positions, positions[1:])
    )


def _record_scope_ids(
    records: list[tuple[str, list[dict]]],
    indices: list[int],
    content: str,
) -> dict[int, int]:
    if not content:
        return {index: 0 for index in indices}
    normalized = "\n".join(
        re.sub(r"[^\S\r\n]+", " ", line) for line in content.splitlines()
    )
    boundaries = [
        match.start()
        for match in re.finditer(
            r"(?m)^[ \t]*(?:[一二三四五六七八九十百]+[、.．]\s*\S.*|"
            r"第.{1,12}[章节])",
            normalized,
        )
    ]
    position = 0
    scopes: dict[int, int] = {}
    for index in indices:
        text = re.sub(r"[^\S\r\n]+", " ", records[index][0]).strip()
        found = normalized.find(text, position)
        if found < 0:
            text = re.sub(r"^\s*\d+(?:\.\d+)*[、.)）．:：]?\s*", "", text)
            found = normalized.find(text, position) if text else -1
        if found < 0:
            scopes[index] = -1
            continue
        scopes[index] = sum(boundary <= found for boundary in boundaries)
        position = found + len(text)
    return scopes


def _frame_operator(frame: str) -> str | None:
    has_all = bool(_EXPLICIT_ALL.search(frame))
    has_any = bool(_EXPLICIT_ANY.search(frame))
    if has_all == has_any:
        return None
    return "all" if has_all else "any"


def _frame_item_count(frame: str) -> tuple[bool, int | None]:
    match = _FRAME_ITEM_COUNT.search(frame)
    if not match:
        return False, None
    if match.group("ambiguous"):
        return True, None
    value = match.group("count")
    chinese_counts = {"两": 2, "二": 2, "三": 3}
    if value in chinese_counts:
        return True, chinese_counts[value]
    if value.isascii() and value.isdigit():
        if len(value) > 6:
            return True, None
        count = int(value)
        return True, count if count >= 2 and str(count) == value else None
    return True, None


def _has_complete_numbered_prefix(
    records: list[tuple[str, list[dict]]],
    indices: list[int],
    item_count: int,
) -> bool:
    numbered = [_numbered_record(records[index]) for index in indices]
    if any(item is None for item in numbered):
        return False
    labels = [item[0] for item in numbered if item is not None]
    if len(set(labels)) != len(labels):
        return False
    selected = numbered[:item_count]
    if len({item[1] for item in selected if item is not None}) != 1:
        return False

    components = [label.split(".") for label in labels[:item_count]]
    if len({len(parts) for parts in components}) != 1:
        return False
    if any(
        not part.isascii()
        or not part.isdigit()
        or (len(part) > 1 and part.startswith("0"))
        for parts in components
        for part in parts
    ):
        return False
    if any(parts[:-1] != components[0][:-1] for parts in components):
        return False
    return [int(parts[-1]) for parts in components] == list(
        range(1, item_count + 1)
    )


def _emit_group(
    result: list[tuple[str, list[dict], dict | None]],
    records: list[tuple[str, list[dict]]],
    frame_index: int,
    child_indices: list[int],
    operator: str,
) -> None:
    pieces = [records[frame_index][0]]
    references = [dict(ref) for ref in records[frame_index][1]]
    children: list[dict[str, Any]] = []
    for index in child_indices:
        pieces.append(records[index][0])
        references.extend(dict(ref) for ref in records[index][1])
        child_rule = build_local_requirement_rule(records[index][0])
        child_logic = child_rule.get("condition_logic")
        if not isinstance(child_logic, dict):
            child_logic = {
                "op": "manual_review",
                "reason": "编号子条款叶子语义无法可靠解析",
                "source_text": records[index][0],
            }
        children.append(child_logic)
    description = "\n".join(pieces)
    combined = build_local_requirement_rule(description).get("condition_logic")
    frame_text = records[frame_index][0]
    if (
        operator == "all"
        and
        "项目经理" in description
        and re.search(
            r"同一人|同一项目经理|拟任项目经理.*(?:同时|均)", frame_text
        )
        and isinstance(combined, dict)
        and _contains_operator(combined, "sameperson")
    ):
        logic = combined
    else:
        logic = {
            "op": operator,
            "conditions": children,
            "source_text": description,
        }
    rule = _manual_group_rule(description, logic)

    first = frame_index
    result[first] = (description, _unique_references(references), rule)
    for index in child_indices:
        result[index] = ("", [], None)


def _contains_operator(node: dict[str, Any], operator: str) -> bool:
    if node.get("op") == operator:
        return True
    children = node.get("conditions")
    if isinstance(children, list):
        return any(
            isinstance(child, dict) and _contains_operator(child, operator)
            for child in children
        )
    condition = node.get("condition")
    return isinstance(condition, dict) and _contains_operator(condition, operator)


def _manual_group_rule(
    source: str, logic: dict[str, Any] | None = None
) -> dict[str, Any]:
    condition_logic = logic or {
        "op": "manual_review",
        "reason": "组合条件需人工复核",
        "source_text": source,
    }
    return {
        "rule_ast": {
            "op": "manual_review",
            "reason": "分组条款保留有限结构，自动核验不支持",
            "source_text": source,
            "condition_logic": condition_logic,
            "coverage_status": "partial",
        },
        "condition_logic": condition_logic,
        "coverage_status": "partial",
        "source_text": source,
        "evaluation_capability": {"automatic": "unsupported", "human_review": True},
    }


def _unique_references(references: list[dict]) -> list[dict]:
    output: list[dict] = []
    seen: set[tuple[str, str, str, str]] = set()
    for ref in references:
        key = (
            str(ref.get("document_id") or ""),
            str(ref.get("source_version") or ref.get("source_file_version") or ""),
            str(ref.get("locator") or ""),
            str(ref.get("quote") or ""),
        )
        if key not in seen:
            seen.add(key)
            output.append(ref)
    return output
