"""Loss-aware physical document structure extraction."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any


_SCHEMA_VERSION = "document-structure-v1"
_CHINESE_NUMBER = "零〇一二三四五六七八九十百千万"
_TERMINAL_PUNCTUATION = "。；;！？!?"
_CHAPTER_RE = re.compile(
    rf"^\s*(?P<label>第[{_CHINESE_NUMBER}0-9]+"
    r"(?P<unit>部分|章节|章|节|篇|条))"
)
_PAREN_RE = re.compile(
    rf"^[（(]\s*(?P<token>[0-9]+|[A-Za-z]|[{_CHINESE_NUMBER}]+)"
    r"\s*[）)]"
)
_DECIMAL_RE = re.compile(
    r"^(?P<core>[0-9]+(?:[.．][0-9]+)*)"
    r"(?P<punct>[、.．)）])?(?P<space>\s*)"
)
_DECIMAL_PREFIX_RE = re.compile(r"^(?P<core>[0-9]+(?:[.．][0-9]+)*)")
_CHINESE_ORDINAL_RE = re.compile(
    rf"^(?P<token>[{_CHINESE_NUMBER}]+)"
    r"(?:(?P<punct>[、.．)])(?P<after_punct>\s*)|(?P<space>\s+))"
)
_ALPHA_RE = re.compile(r"^(?P<token>[A-Za-z])(?P<punct>[.)、])(?P<space>\s*)")


def build_document_structure(
    pages: list[Mapping[str, Any]],
    *,
    document_id: str,
    source_version: str,
    source_checksum: str | None = None,
) -> dict[str, Any]:
    """Build deterministic blocks from extracted page text.

    Source offsets are Unicode character offsets within each input page. The
    normalization map uses page-global raw offsets; page separators have an
    explicit boundary position and never claim a page-local source span.
    """

    if not isinstance(pages, list):
        raise TypeError("pages must be a list")
    if not document_id:
        raise ValueError("document_id is required")
    if not source_version:
        raise ValueError("source_version is required")

    page_records: list[dict[str, Any]] = []
    output_pages: list[dict[str, Any]] = []
    warnings: list[str] = []
    seen_page_numbers: set[int] = set()
    for index, page in enumerate(pages, start=1):
        if not isinstance(page, Mapping):
            raise TypeError(f"pages[{index - 1}] must be a mapping")
        page_number = _page_number(page.get("page_number"), fallback=index)
        if page_number in seen_page_numbers:
            raise ValueError(f"duplicate page_number: {page_number}")
        seen_page_numbers.add(page_number)
        raw_value = page.get("raw_text")
        if raw_value is None:
            raw_value = page.get("text")
        raw_text = raw_value if isinstance(raw_value, str) else str(raw_value or "")

        output_page = dict(page)
        output_page["page_number"] = page_number
        output_page["raw_text"] = raw_text
        output_pages.append(output_page)
        page_records.append(
            {"page_number": page_number, "raw_text": raw_text}
        )

        page_warnings = page.get("warnings")
        if isinstance(page_warnings, (list, tuple)):
            warnings.extend(
                f"page {page_number}: {item}"
                for item in page_warnings
                if str(item).strip()
            )

    blocks: list[dict[str, Any]] = []
    page_blocks: list[list[dict[str, Any]]] = []
    for page_index, page in enumerate(page_records):
        current_page_blocks: list[dict[str, Any]] = []
        fragments = _physical_fragments(page["raw_text"])
        for line_number, fragment in enumerate(fragments, start=1):
            fragment_kind, raw_text, start, end, line_ending = fragment
            kind = fragment_kind or _classify_line(raw_text)
            if kind == "page_boundary":
                block = _make_boundary_block(
                    document_id=document_id,
                    source_version=source_version,
                    page_number=page["page_number"],
                    line_number=line_number,
                    boundary_position={
                        "page_number": page["page_number"],
                        "char_offset": start,
                        "origin": "form_feed_in_extracted_page_text",
                    },
                    boundary_origin="form_feed_in_extracted_page_text",
                    synthetic=False,
                )
            else:
                block = _make_block(
                    document_id=document_id,
                    source_version=source_version,
                    page_number=page["page_number"],
                    line_number=line_number,
                    start=start,
                    end=end,
                    raw_text=raw_text,
                    line_ending=line_ending,
                    kind=kind,
                )
            blocks.append(block)
            current_page_blocks.append(block)
        page_blocks.append(current_page_blocks)

        if page_index < len(page_records) - 1:
            boundary = _make_boundary_block(
                document_id=document_id,
                source_version=source_version,
                page_number=page["page_number"],
                line_number=len(current_page_blocks) + 1,
                boundary_position={
                    "after_page_number": page["page_number"],
                    "char_offset": len(page["raw_text"]),
                    "before_page_number": page_records[page_index + 1][
                        "page_number"
                    ],
                },
                boundary_origin="between_extracted_pages",
                synthetic=True,
            )
            blocks.append(boundary)

    _assign_table_groups(blocks)
    _assign_numbering_and_hierarchy(
        blocks,
        warnings=warnings,
    )
    continuation_candidates = _cross_page_continuations(
        page_blocks,
        warnings=warnings,
    )
    block_by_id = {block["block_id"]: block for block in blocks}
    for candidate in continuation_candidates:
        if candidate["candidate_kind"] != "paragraph_continuation":
            continue
        following_id = candidate["source_block_ids"][1]
        following = block_by_id[following_id]
        following["parent_block_id"] = None
        following["section_block_id"] = None
        following["structural_ambiguity"] = (
            "cross_page_continuation_candidate"
        )

    return {
        "schema_version": _SCHEMA_VERSION,
        "document_id": document_id,
        "source_version": source_version,
        "source_checksum": source_checksum,
        "metadata": {
            "source_representation": "extracted_page_text",
            "offset_unit": "unicode_codepoint",
        },
        "pages": output_pages,
        "blocks": blocks,
        "title_candidates": _title_candidates(page_blocks),
        "continuation_candidates": continuation_candidates,
        "warnings": _unique(warnings),
        "coverage_status": "partial",
        "needs_human_review": True,
    }


def _page_number(value: Any, *, fallback: int) -> int:
    if value is None:
        return fallback
    if isinstance(value, bool):
        raise ValueError("page_number must be a positive integer")
    try:
        page_number = int(value)
    except (TypeError, ValueError):
        raise ValueError("page_number must be a positive integer") from None
    if isinstance(value, float) and value != page_number:
        raise ValueError("page_number must be a positive integer")
    if isinstance(value, str) and not re.fullmatch(r"\+?\d+", value.strip()):
        raise ValueError("page_number must be a positive integer")
    if page_number <= 0:
        raise ValueError("page_number must be a positive integer")
    return page_number


def _physical_fragments(
    text: str,
) -> list[tuple[str | None, str, int, int, str]]:
    """Split physical lines without losing line endings or form feeds."""

    if not text:
        return [(None, "", 0, 0, "")]

    fragments: list[tuple[str | None, str, int, int, str]] = []
    offset = 0
    while offset < len(text):
        start = offset
        while offset < len(text) and text[offset] not in "\r\n\f":
            offset += 1
        raw_line = text[start:offset]

        if offset == len(text):
            fragments.append((None, raw_line, start, offset, ""))
            break

        char = text[offset]
        if char == "\f":
            if raw_line:
                fragments.append((None, raw_line, start, offset, ""))
            fragments.append(("page_boundary", "\f", offset, offset + 1, ""))
            offset += 1
            continue

        if char == "\r" and offset + 1 < len(text) and text[offset + 1] == "\n":
            line_ending = "\r\n"
        else:
            line_ending = char
        fragments.append(
            (None, raw_line, start, offset, line_ending)
        )
        offset += len(line_ending)

    return fragments


def _classify_line(raw_text: str) -> str:
    stripped = raw_text.strip()
    if not stripped:
        return "blank"
    if _is_table_row(raw_text):
        return "table_row"
    if _CHAPTER_RE.match(raw_text):
        return "heading"

    numbering = _parse_numbering(raw_text)
    if numbering is not None:
        if numbering["style"] == "chinese":
            body = raw_text[numbering["end"] :].strip()
            if (
                numbering["label"].endswith(("、", ".", "．"))
                and body
                and len(body) <= 6
                and not stripped.endswith(
                    tuple(_TERMINAL_PUNCTUATION + "：:")
                )
            ):
                return "heading"
            return "list_item"
        return "list_item"
    return "paragraph"


def _is_table_row(raw_text: str) -> bool:
    content = raw_text.lstrip(" \t")
    return (
        "\t" in content
        or raw_text.count("|") >= 2
        or bool(re.match(r"^\s*\+[-+=+]+\+\s*$", raw_text))
    )


def _make_block(
    *,
    document_id: str,
    source_version: str,
    page_number: int,
    line_number: int,
    start: int,
    end: int,
    raw_text: str,
    line_ending: str,
    kind: str,
) -> dict[str, Any]:
    normalized_text, normalization_map = _normalize(raw_text, raw_offset=start)
    block_id = _stable_id(
        document_id,
        source_version,
        page_number,
        start,
        end,
        raw_text,
    )
    locator = f"p{page_number}:c{start}-{end}"
    return {
        "block_id": block_id,
        "kind": kind,
        "raw_text": raw_text,
        "normalized_text": normalized_text,
        "line_ending": line_ending,
        "page_number": page_number,
        "line_number": line_number,
        "source_span": {
            "page_number": page_number,
            "start": start,
            "end": end,
        },
        "normalization_map": normalization_map,
        "numbering": None,
        "parent_block_id": None,
        "section_block_id": None,
        "source_references": [
            {
                "document_id": document_id,
                "source_version": source_version,
                "page": page_number,
                "quote": raw_text,
                "locator": locator,
                "char_start": start,
                "char_end": end,
            }
        ],
        **(
            {"cell_spans": _cell_spans(raw_text, start)}
            if kind == "table_row"
            else {}
        ),
    }


def _make_boundary_block(
    *,
    document_id: str,
    source_version: str,
    page_number: int,
    line_number: int,
    boundary_position: Mapping[str, Any],
    boundary_origin: str,
    synthetic: bool,
) -> dict[str, Any]:
    boundary_id = _stable_id(
        document_id,
        source_version,
        "page_boundary",
        page_number,
        boundary_position,
        "\f",
    )
    return {
        "block_id": boundary_id,
        "kind": "page_boundary",
        "raw_text": "\f",
        "normalized_text": "",
        "line_ending": "",
        "page_number": page_number,
        "line_number": line_number,
        "source_span": None,
        "normalization_map": [],
        "numbering": None,
        "parent_block_id": None,
        "section_block_id": None,
        "source_references": [],
        "boundary_marker": "\f",
        "boundary_position": dict(boundary_position),
        "boundary_origin": boundary_origin,
        "synthetic": synthetic,
    }


def _normalize(
    raw_text: str,
    *,
    raw_offset: int,
) -> tuple[str, list[dict[str, Any]]]:
    normalized: list[str] = []
    mappings: list[dict[str, Any]] = []
    normalized_length = 0
    raw_index = 0
    while raw_index < len(raw_text):
        if raw_text[raw_index].isspace():
            run_start = raw_index
            while raw_index < len(raw_text) and raw_text[raw_index].isspace():
                raw_index += 1
            normalized_start = normalized_length
            normalized.append(" ")
            normalized_length += 1
            mappings.append(
                {
                    "normalized_start": normalized_start,
                    "normalized_end": normalized_length,
                    "raw_start": raw_offset + run_start,
                    "raw_end": raw_offset + raw_index,
                    "kind": "whitespace",
                }
            )
            continue

        normalized_start = normalized_length
        run_start = raw_index
        while raw_index < len(raw_text) and not raw_text[raw_index].isspace():
            raw_index += 1
        identity_text = raw_text[run_start:raw_index]
        normalized.append(identity_text)
        normalized_length += len(identity_text)
        mappings.append(
            {
                "normalized_start": normalized_start,
                "normalized_end": normalized_length,
                "raw_start": raw_offset + run_start,
                "raw_end": raw_offset + raw_index,
                "kind": "identity",
            }
        )
    return "".join(normalized), mappings


def _cell_spans(raw_text: str, page_offset: int) -> list[dict[str, Any]]:
    delimiter = "\t" if "\t" in raw_text else "|"
    if delimiter == "|" and raw_text.count("|") < 2:
        return []
    pieces = raw_text.split(delimiter)
    if delimiter == "|" and pieces and not pieces[0].strip():
        leading_piece_length = len(pieces[0])
        pieces = pieces[1:]
        page_offset += leading_piece_length + 1
    if delimiter == "|" and pieces and not pieces[-1].strip():
        pieces = pieces[:-1]

    cells: list[dict[str, Any]] = []
    cursor = page_offset
    for index, piece in enumerate(pieces):
        cells.append(
            {
                "start": cursor,
                "end": cursor + len(piece),
                "raw_text": piece,
            }
        )
        cursor += len(piece)
        if index < len(pieces) - 1:
            cursor += 1
    return cells


def _table_format(raw_text: str) -> str:
    if "\t" in raw_text:
        return "tab"
    if raw_text.count("|") >= 2 or re.match(
        r"^\s*\+[-+=+]+\+\s*$", raw_text
    ):
        return "pipe"
    return "unknown"


def _assign_table_groups(blocks: list[dict[str, Any]]) -> None:
    active_group_id: str | None = None
    active_format: str | None = None
    row_index = 0
    for block in blocks:
        if block["kind"] == "page_boundary" or block["kind"] == "blank":
            active_group_id = None
            active_format = None
            row_index = 0
            continue
        if block["kind"] != "table_row":
            active_group_id = None
            active_format = None
            row_index = 0
            continue

        row_format = _table_format(block["raw_text"])
        if active_group_id is None or row_format != active_format:
            active_group_id = block["block_id"]
            active_format = row_format
            row_index = 1
        else:
            row_index += 1
        block["table_group_id"] = active_group_id
        block["table_row_index"] = row_index


def _parse_numbering(raw_text: str) -> dict[str, Any] | None:
    leading = len(raw_text) - len(raw_text.lstrip())
    text = raw_text[leading:]

    chapter_match = _CHAPTER_RE.match(text)
    if chapter_match:
        label = chapter_match.group("label")
        return {
            "label": label,
            "style": "chinese_section",
            "level": 1,
            "path": [label],
            "token": label,
            "section_unit": chapter_match.group("unit"),
            "start": leading,
            "end": leading + chapter_match.end("label"),
        }

    match = _PAREN_RE.match(text)
    if match:
        token = match.group("token")
        label = text[: match.end()]
        if token.isdigit():
            style = "parenthesized_decimal"
        elif token.isascii() and token.isalpha():
            style = "parenthesized_alpha"
        else:
            style = "parenthesized_chinese"
        return {
            "label": label,
            "style": style,
            "level": 1,
            "path": [token],
            "token": token,
            "start": leading,
            "end": leading + match.end(),
        }

    match = _DECIMAL_RE.match(text)
    if match:
        core = match.group("core")
        punct = match.group("punct") or ""
        token_path = re.split(r"[.．]", core)
        body = text[match.end() :]
        has_explicit_separator = bool(punct or match.group("space"))
        compact_single_digit_path = (
            bool(body)
            and len(token_path) > 1
            and len(token_path[-1]) == 1
        )
        ambiguous_numeric_value = (
            len(token_path) > 1 and len(token_path[-1]) > 1
        )
        if (
            ambiguous_numeric_value
            or (
                not has_explicit_separator
                and not compact_single_digit_path
            )
            or (not body and not punct)
        ):
            match = None
        else:
            label = text[: match.end("punct")] if punct else core
            return {
                "label": label,
                "style": "decimal",
                "level": len(token_path),
                "path": token_path,
                "token": token_path[-1],
                "start": leading,
                "end": leading + (match.end("punct") if punct else match.end("core")),
            }

    match = _CHINESE_ORDINAL_RE.match(text)
    if match:
        token = match.group("token")
        punctuation = match.group("punct") or ""
        label_end = (
            match.end("punct") if punctuation else match.end("token")
        )
        return {
            "label": text[:label_end],
            "style": "chinese",
            "level": 1,
            "path": [token],
            "token": token,
            "start": leading,
            "end": leading + label_end,
        }

    match = _ALPHA_RE.match(text)
    if match:
        token = match.group("token")
        return {
            "label": text[: match.end("punct")],
            "style": "alpha",
            "level": 1,
            "path": [token],
            "token": token,
            "start": leading,
            "end": leading + match.end("punct"),
        }
    return None


def _ambiguous_decimal_candidate(raw_text: str) -> dict[str, Any] | None:
    leading = len(raw_text) - len(raw_text.lstrip())
    text = raw_text[leading:]
    match = _DECIMAL_PREFIX_RE.match(text)
    if match is None:
        return None
    core = match.group("core")
    token_path = re.split(r"[.．]", core)
    if len(token_path) < 2 or len(token_path[-1]) < 2:
        return None
    return {
        "label": core,
        "style": "ambiguous_decimal_or_value",
        "token_path": token_path,
        "status": "needs_review",
        "start": leading,
        "end": leading + len(core),
    }


def _assign_numbering_and_hierarchy(
    blocks: list[dict[str, Any]],
    *,
    warnings: list[str],
) -> None:
    decimal_blocks: dict[tuple[str, ...], str] = {}
    block_by_id = {block["block_id"]: block for block in blocks}
    current_section_id: str | None = None
    active_chapter_id: str | None = None
    last_container_id: str | None = None
    enumeration_stack: list[dict[str, Any]] = []

    for block in blocks:
        if block["kind"] == "page_boundary":
            block["section_block_id"] = current_section_id
            continue

        raw_text = block["raw_text"]
        parsed = _parse_numbering(raw_text)
        if parsed is None:
            decimal_candidate = _ambiguous_decimal_candidate(raw_text)
            if decimal_candidate is not None:
                block["numbering_candidate"] = {
                    key: value
                    for key, value in decimal_candidate.items()
                    if key not in {"start", "end"}
                }
                block["kind_ambiguity"] = "ambiguous_decimal_prefix"
                warnings.append(
                    f"ambiguous decimal prefix requires review: "
                    f"{block['block_id']}"
                )
            block["section_block_id"] = current_section_id
            if block["kind"] in {"paragraph", "table_row"}:
                block["parent_block_id"] = last_container_id
            if block["kind"] == "heading" and raw_text.strip():
                decimal_blocks.clear()
                enumeration_stack.clear()
                current_section_id = block["block_id"]
                block["section_block_id"] = block["block_id"]
                last_container_id = block["block_id"]
            elif (
                block["kind"] == "paragraph"
                and raw_text.rstrip().endswith(("：", ":"))
            ):
                last_container_id = block["block_id"]
                enumeration_stack.clear()
            continue

        block_id = block["block_id"]
        style = parsed["style"]
        path = tuple(parsed["path"])
        if style == "chinese_section":
            decimal_blocks.clear()
            enumeration_stack.clear()
            block["kind"] = "heading"
            block["numbering"] = _numbering_object(parsed, path)
            block["section_block_id"] = block_id
            current_section_id = block_id
            last_container_id = block_id
            if parsed["section_unit"] == "章":
                active_chapter_id = block_id
            else:
                active_chapter_id = None
                block["kind_ambiguity"] = "unsupported_chinese_section_hierarchy"
                warnings.append(
                    f"unsupported Chinese section hierarchy "
                    f"({parsed['section_unit']}) requires review: {block_id}"
                )
            continue

        if style == "chinese":
            block["numbering"] = _numbering_object(parsed, path)
            if block["kind"] == "heading":
                decimal_blocks.clear()
                enumeration_stack.clear()
                block["parent_block_id"] = active_chapter_id
                block["section_block_id"] = block_id
                block["kind_ambiguity"] = "short_chinese_numbered_heading"
                current_section_id = block_id
                last_container_id = block_id
                warnings.append(
                    f"short Chinese numbered heading is a structural boundary "
                    f"candidate requiring review: {block_id}"
                )
            else:
                block["parent_block_id"] = current_section_id
                block["section_block_id"] = current_section_id
                if not parsed["label"].endswith(("、", ".", "．")):
                    block["kind_ambiguity"] = "unpunctuated_chinese_numbering"
                    warnings.append(
                        f"unpunctuated Chinese numbering requires review: {block_id}"
                    )
                last_container_id = block_id
                enumeration_stack.clear()
            continue

        if style == "decimal":
            level = len(path)
            if level == 1:
                decimal_blocks.clear()
                enumeration_stack.clear()
                parent_id = active_chapter_id
                current_section_id = block_id
                section_id = block_id
                body = raw_text[parsed["end"] :].strip()
                if (
                    body
                    and len(body) <= 40
                    and not raw_text.strip().endswith(
                        tuple(_TERMINAL_PUNCTUATION + "：:")
                    )
                ):
                    block["heading_candidate"] = True
                    block["kind_ambiguity"] = (
                        "decimal_heading_or_numbered_clause"
                    )
            elif level > 1:
                parent_id = decimal_blocks.get(path[:-1])
                if parent_id is None:
                    warnings.append(
                        f"ambiguous numbering parent for {block_id}: "
                        f"missing decimal ancestor {'.'.join(path[:-1])}"
                    )
                    section_id = current_section_id
                else:
                    section_id = block_id

            block["parent_block_id"] = parent_id
            block["section_block_id"] = section_id
            block["numbering"] = _numbering_object(parsed, path)
            for old_path in list(decimal_blocks):
                if (
                    len(old_path) >= level
                    and old_path[: level - 1] == path[: level - 1]
                ):
                    del decimal_blocks[old_path]
            decimal_blocks[path] = block_id
            last_container_id = block_id
            enumeration_stack.clear()
            if parent_id is not None or level == 1:
                current_section_id = block_id
            continue

        indent = _indent_width(raw_text)
        rank = _parenthesized_rank(style)
        matching_group = next(
            (
                index
                for index in range(len(enumeration_stack) - 1, -1, -1)
                if enumeration_stack[index]["style"] == style
                and enumeration_stack[index]["indent"] == indent
                and enumeration_stack[index]["rank"] == rank
            ),
            None,
        )
        if matching_group is not None:
            group = enumeration_stack[matching_group]
            del enumeration_stack[matching_group + 1 :]
            parent_id = group["parent_block_id"]
            group["block_id"] = block_id
        else:
            while enumeration_stack and (
                indent < enumeration_stack[-1]["indent"]
                or rank < enumeration_stack[-1]["rank"]
                or (
                    indent == enumeration_stack[-1]["indent"]
                    and rank == enumeration_stack[-1]["rank"]
                )
            ):
                enumeration_stack.pop()
            if enumeration_stack and (
                indent > enumeration_stack[-1]["indent"]
                or rank > enumeration_stack[-1]["rank"]
            ):
                parent_id = enumeration_stack[-1]["block_id"]
            else:
                parent_id = last_container_id
            enumeration_stack.append(
                {
                    "style": style,
                    "indent": indent,
                    "rank": rank,
                    "parent_block_id": parent_id,
                    "block_id": block_id,
                }
            )

        if parent_id is None:
            warnings.append(
                f"ambiguous numbering parent for {block_id}: "
                f"no preceding structural container"
            )
        parent_block = block_by_id.get(parent_id) if parent_id else None
        base_path = (
            parent_block["numbering"]["path"]
            if parent_block and parent_block.get("numbering")
            else []
        )
        resolved_path = [*base_path, parsed["token"]]
        block["parent_block_id"] = parent_id
        block["section_block_id"] = _nearest_section(
            parent_id, block_by_id, current_section_id
        )
        block["numbering"] = _numbering_object(parsed, resolved_path)


def _numbering_object(
    parsed: Mapping[str, Any],
    path: tuple[str, ...] | list[str],
) -> dict[str, Any]:
    resolved_path = list(path)
    return {
        "label": parsed["label"],
        "style": parsed["style"],
        "level": len(resolved_path),
        "path": resolved_path,
    }


def _nearest_section(
    parent_id: str | None,
    block_by_id: Mapping[str, dict[str, Any]],
    fallback: str | None,
) -> str | None:
    if parent_id is None:
        return fallback
    parent = block_by_id.get(parent_id)
    if parent and parent["kind"] == "heading":
        return parent_id
    return fallback


def _indent_width(raw_text: str) -> int:
    prefix = raw_text[: len(raw_text) - len(raw_text.lstrip())]
    return sum(4 if char == "\t" else 1 for char in prefix)


def _parenthesized_rank(style: str) -> int:
    if style in {"parenthesized_alpha", "alpha"}:
        return 2
    return 1


def _cross_page_continuations(
    page_blocks: list[list[dict[str, Any]]],
    *,
    warnings: list[str],
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for index in range(len(page_blocks) - 1):
        previous = _last_content_block(page_blocks[index])
        following = _first_content_block(page_blocks[index + 1])
        if previous is None or following is None:
            continue
        if (
            previous["kind"] == "table_row"
            and following["kind"] == "table_row"
        ):
            candidate_id = _stable_id(
                "table_continuation",
                previous["block_id"],
                following["block_id"],
            )
            candidates.append(
                {
                    "candidate_id": candidate_id,
                    "candidate_kind": "table_continuation",
                    "status": "needs_review",
                    "source": "cross_page_physical_adjacency",
                    "source_block_ids": [
                        previous["block_id"],
                        following["block_id"],
                    ],
                    "source_references": [
                        *previous["source_references"],
                        *following["source_references"],
                    ],
                }
            )
            warnings.append(
                f"possible cross-page table continuation requires review: "
                f"{candidate_id}"
            )
            continue
        if previous["kind"] not in {"paragraph", "list_item"}:
            continue
        if following["kind"] != "paragraph":
            continue
        previous_text = previous["raw_text"].rstrip()
        if not previous_text or previous_text.endswith(
            tuple(_TERMINAL_PUNCTUATION + "：:")
        ):
            continue

        candidate_id = _stable_id(
            "continuation",
            previous["block_id"],
            following["block_id"],
            "cross_page",
        )
        candidates.append(
            {
                "candidate_id": candidate_id,
                "candidate_kind": "paragraph_continuation",
                "status": "needs_review",
                "source": "cross_page_physical_adjacency",
                "source_block_ids": [
                    previous["block_id"],
                    following["block_id"],
                ],
                "source_references": [
                    *previous["source_references"],
                    *following["source_references"],
                ],
            }
        )
        warnings.append(
            f"possible cross-page continuation requires review: {candidate_id}"
        )
    return candidates


def _title_candidates(
    page_blocks: list[list[dict[str, Any]]],
) -> list[dict[str, Any]]:
    if not page_blocks:
        return []
    first = _first_content_block(page_blocks[0])
    if first is None or first["kind"] != "paragraph":
        return []
    text = first["normalized_text"].strip()
    if (
        not 2 <= len(text) <= 40
        or _parse_numbering(first["raw_text"]) is not None
        or text.endswith(tuple(_TERMINAL_PUNCTUATION + "：:"))
    ):
        return []
    candidate_id = _stable_id("document_title_candidate", first["block_id"])
    return [
        {
            "candidate_id": candidate_id,
            "candidate_kind": "document_title",
            "status": "ambiguous",
            "block_id": first["block_id"],
            "raw_text": first["raw_text"],
            "evidence": (
                "short_unnumbered_first_content_line_"
                "without_terminal_punctuation"
            ),
            "source_references": list(first["source_references"]),
        }
    ]


def _last_content_block(blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next(
        (
            block
            for block in reversed(blocks)
            if block["kind"] not in {"blank", "page_boundary"}
            and block["raw_text"].strip()
        ),
        None,
    )


def _first_content_block(blocks: list[dict[str, Any]]) -> dict[str, Any] | None:
    return next(
        (
            block
            for block in blocks
            if block["kind"] not in {"blank", "page_boundary"}
            and block["raw_text"].strip()
        ),
        None,
    )


def _stable_id(*parts: Any) -> str:
    encoded = json.dumps(
        parts,
        ensure_ascii=False,
        separators=(",", ":"),
    ).encode("utf-8")
    return "blk_" + hashlib.sha256(encoded).hexdigest()[:24]


def _unique(values: list[str]) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            result.append(value)
            seen.add(value)
    return result
