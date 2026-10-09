from __future__ import annotations

import hashlib
import json
from pathlib import Path

import pytest

from qiaowenshu_agent.domain.document_structure import build_document_structure


def _build(pages: list[dict], *, document_id: str = "doc", version: str = "v1"):
    return build_document_structure(
        pages,
        document_id=document_id,
        source_version=version,
        source_checksum="checksum",
    )


def test_preserves_physical_lines_line_endings_and_character_mappings() -> None:
    raw_text = "标题\r\n  短\t行 \r\n\r\n| A | B |\r\n"
    result = _build([{"page_number": 3, "text": raw_text}])

    assert result["schema_version"] == "document-structure-v1"
    assert result["pages"][0]["page_number"] == 3
    assert result["pages"][0]["raw_text"] == raw_text
    assert [block["raw_text"] for block in result["blocks"]] == [
        "标题",
        "  短\t行 ",
        "",
        "| A | B |",
    ]
    assert [block["line_ending"] for block in result["blocks"]] == [
        "\r\n",
        "\r\n",
        "\r\n",
        "\r\n",
    ]

    second = result["blocks"][1]
    assert second["normalized_text"] == " 短 行 "
    assert second["source_span"] == {
        "page_number": 3,
        "start": 4,
        "end": 10,
    }
    assert second["normalization_map"][0] == {
        "normalized_start": 0,
        "normalized_end": 1,
        "raw_start": 4,
        "raw_end": 6,
        "kind": "whitespace",
    }
    assert second["source_references"] == [
        {
            "document_id": "doc",
            "source_version": "v1",
            "page": 3,
            "quote": "  短\t行 ",
            "locator": "p3:c4-10",
            "char_start": 4,
            "char_end": 10,
        }
    ]
    _assert_map_resolves(second, result["pages"][0]["raw_text"])
    table = result["blocks"][3]
    assert table["kind"] == "table_row"
    assert [cell["raw_text"] for cell in table["cell_spans"]] == [
        " A ",
        " B ",
    ]


def test_numbering_tree_uses_only_real_ancestors_and_resets_at_new_chapter() -> None:
    result = _build(
        [
            {
                "page_number": 1,
                "text": (
                    "第一章 投标要求\n"
                    "1. 主体资格\n"
                    "1.1 投标人应提交以下材料之一：\n"
                    "（1）营业执照\n"
                    "（2）法人登记证明\n"
                    "第二章 技术要求\n"
                    "1.1 平台应支持 PostgreSQL。\n"
                    "（a）OAuth2.0 对接\n"
                    "（b）不得替换现有身份系统\n"
                ),
            }
        ]
    )
    by_text = {block["raw_text"]: block for block in result["blocks"]}

    assert by_text["第一章 投标要求"]["kind"] == "heading"
    assert by_text["1. 主体资格"]["kind"] == "list_item"
    assert by_text["1. 主体资格"]["heading_candidate"] is True
    assert (
        by_text["1. 主体资格"]["kind_ambiguity"]
        == "decimal_heading_or_numbered_clause"
    )
    assert by_text["1.1 投标人应提交以下材料之一："]["kind"] == "list_item"
    assert by_text["1.1 投标人应提交以下材料之一："]["parent_block_id"] == (
        by_text["1. 主体资格"]["block_id"]
    )
    for child in ("（1）营业执照", "（2）法人登记证明"):
        assert by_text[child]["parent_block_id"] == (
            by_text["1.1 投标人应提交以下材料之一："]["block_id"]
        )
        assert by_text[child]["numbering"]["style"] == "parenthesized_decimal"

    later_child = by_text["1.1 平台应支持 PostgreSQL。"]
    assert later_child["parent_block_id"] is None
    assert later_child["numbering"]["path"] == ["1", "1"]
    assert any(
        "missing decimal ancestor 1" in warning for warning in result["warnings"]
    )
    assert by_text["（a）OAuth2.0 对接"]["parent_block_id"] == later_child["block_id"]
    assert by_text["（b）不得替换现有身份系统"]["parent_block_id"] == later_child[
        "block_id"
    ]


def test_cross_page_fragments_stay_separate_and_emit_review_candidate() -> None:
    pages = [
        {
            "page_number": 1,
            "text": "1.1 审计报告中的资产负债表和利润表",
        },
        {
            "page_number": 2,
            "text": "关键页；\r\n（2）银行出具的资信证明。",
        },
    ]
    result = _build(pages)

    assert result["pages"][0]["raw_text"] == pages[0]["text"]
    assert result["pages"][1]["raw_text"] == pages[1]["text"]
    assert [block["raw_text"] for block in result["blocks"]] == [
        "1.1 审计报告中的资产负债表和利润表",
        "\f",
        "关键页；",
        "（2）银行出具的资信证明。",
    ]
    boundary = result["blocks"][1]
    assert boundary["kind"] == "page_boundary"
    assert boundary["boundary_marker"] == "\f"
    assert boundary["synthetic"] is True
    assert boundary["source_span"] is None
    assert boundary["source_references"] == []
    assert boundary["boundary_position"] == {
        "after_page_number": 1,
        "char_offset": len(pages[0]["text"]),
        "before_page_number": 2,
    }

    assert len(result["continuation_candidates"]) == 1
    candidate = result["continuation_candidates"][0]
    assert candidate["status"] == "needs_review"
    assert candidate["source_block_ids"] == [
        result["blocks"][0]["block_id"],
        result["blocks"][2]["block_id"],
    ]
    assert result["blocks"][2]["parent_block_id"] is None
    assert result["blocks"][2]["section_block_id"] is None
    assert (
        result["blocks"][2]["structural_ambiguity"]
        == "cross_page_continuation_candidate"
    )
    assert [reference["page"] for reference in candidate["source_references"]] == [
        1,
        2,
    ]
    assert result["blocks"][2]["raw_text"] == "关键页；"


def test_form_feed_inside_page_is_a_physical_boundary_with_original_span() -> None:
    result = _build([{"page_number": 4, "raw_text": "上页\f下页"}])

    boundary = next(
        block for block in result["blocks"] if block["kind"] == "page_boundary"
    )
    assert boundary["raw_text"] == "\f"
    assert boundary["source_span"] is None
    assert boundary["source_references"] == []
    assert boundary["boundary_position"] == {
        "page_number": 4,
        "char_offset": 2,
        "origin": "form_feed_in_extracted_page_text",
    }


def test_block_ids_are_repeatable_and_scoped_to_document_version() -> None:
    pages = [{"page_number": 1, "text": "一 投标人须提交材料"}]
    first = _build(pages)
    repeated = _build(pages)
    other_document = _build(pages, document_id="other")
    other_version = _build(pages, version="v2")

    first_id = first["blocks"][0]["block_id"]
    assert first_id == repeated["blocks"][0]["block_id"]
    assert first_id != other_document["blocks"][0]["block_id"]
    assert first_id != other_version["blocks"][0]["block_id"]
    assert first["blocks"][0]["kind"] == "list_item"
    assert first["blocks"][0]["numbering"]["label"] == "一"
    expected_identity = [
        "doc",
        "v1",
        1,
        0,
        len(pages[0]["text"]),
        pages[0]["text"],
    ]
    expected_digest = hashlib.sha256(
        json.dumps(
            expected_identity,
            ensure_ascii=False,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()[:24]
    assert first_id == f"blk_{expected_digest}"
    assert first["coverage_status"] == "partial"
    assert first["needs_human_review"] is True


def test_normalization_map_uses_character_offsets_across_merged_runs() -> None:
    raw_text = "abcdef  ghi"
    block = _build([{"page_number": 1, "text": raw_text}])["blocks"][0]

    assert block["normalized_text"] == "abcdef ghi"
    assert block["normalization_map"] == [
        {
            "normalized_start": 0,
            "normalized_end": 6,
            "raw_start": 0,
            "raw_end": 6,
            "kind": "identity",
        },
        {
            "normalized_start": 6,
            "normalized_end": 7,
            "raw_start": 6,
            "raw_end": 8,
            "kind": "whitespace",
        },
        {
            "normalized_start": 7,
            "normalized_end": 10,
            "raw_start": 8,
            "raw_end": 11,
            "kind": "identity",
        },
    ]
    _assert_map_resolves(block, raw_text)


def test_chinese_numbering_without_spacing_is_kept_and_styled_correctly() -> None:
    result = _build(
        [
            {
                "page_number": 1,
                "text": (
                    "一、投标人须提供以下材料\n"
                    "第一章资格要求\n"
                    "（一）营业执照\n"
                    "（a）身份协议\n"
                    "一 投标人须提交资质证明\n"
                    "2025年度财务报表"
                ),
            }
        ]
    )
    by_text = {block["raw_text"]: block for block in result["blocks"]}

    assert by_text["一、投标人须提供以下材料"]["kind"] == "list_item"
    assert by_text["一、投标人须提供以下材料"]["numbering"] == {
        "label": "一、",
        "style": "chinese",
        "level": 1,
        "path": ["一"],
    }
    assert by_text["第一章资格要求"]["kind"] == "heading"
    assert by_text["第一章资格要求"]["numbering"]["label"] == "第一章"
    assert by_text["（一）营业执照"]["numbering"]["style"] == (
        "parenthesized_chinese"
    )
    assert by_text["（a）身份协议"]["numbering"]["style"] == (
        "parenthesized_alpha"
    )
    assert by_text["一 投标人须提交资质证明"]["kind"] == "list_item"
    assert (
        by_text["一 投标人须提交资质证明"]["kind_ambiguity"]
        == "unpunctuated_chinese_numbering"
    )
    assert by_text["2025年度财务报表"]["numbering"] is None


def test_compact_numbering_prefixes_and_ambiguous_numeric_values() -> None:
    result = _build(
        [
            {
                "page_number": 1,
                "text": (
                    "1.投标人须提交材料\n"
                    "1.1投标人须具有独立民事责任能力\n"
                    "A.提供证件\n"
                    "1.50万元\n"
                    "2026-10-09更正"
                ),
            }
        ]
    )
    by_text = {block["raw_text"]: block for block in result["blocks"]}

    assert by_text["1.投标人须提交材料"]["numbering"] == {
        "label": "1.",
        "style": "decimal",
        "level": 1,
        "path": ["1"],
    }
    assert by_text["1.1投标人须具有独立民事责任能力"]["numbering"] == {
        "label": "1.1",
        "style": "decimal",
        "level": 2,
        "path": ["1", "1"],
    }
    alpha_item = by_text["A.提供证件"]
    assert alpha_item["numbering"]["label"] == "A."
    assert alpha_item["numbering"]["style"] == "alpha"
    assert alpha_item["kind"] == "list_item"
    amount = by_text["1.50万元"]
    assert amount["numbering"] is None
    assert amount["numbering_candidate"] == {
        "label": "1.50",
        "style": "ambiguous_decimal_or_value",
        "token_path": ["1", "50"],
        "status": "needs_review",
    }
    date = by_text["2026-10-09更正"]
    assert date["numbering"] is None
    assert "numbering_candidate" not in date


def test_tab_indented_letter_items_are_not_table_rows() -> None:
    result = _build(
        [
            {
                "page_number": 1,
                "text": (
                    "第一章 资格要求\n"
                    "1. 资格材料\n"
                    "1.1 提交材料：\n"
                    "（1）主体证明\n"
                    "\t（a）营业执照\n"
                    "\t（b）法人证明\n"
                    "（2）审计报告\n"
                    "A\tB"
                ),
            }
        ]
    )
    by_text = {block["raw_text"]: block for block in result["blocks"]}

    parent = by_text["（1）主体证明"]["block_id"]
    for text in ("\t（a）营业执照", "\t（b）法人证明"):
        block = by_text[text]
        assert block["kind"] == "list_item"
        assert block["numbering"]["style"] == "parenthesized_alpha"
        assert block["parent_block_id"] == parent
    assert by_text["A\tB"]["kind"] == "table_row"
    tab_row = by_text["A\tB"]
    row_start = tab_row["source_span"]["start"]
    assert tab_row["cell_spans"] == [
        {"start": row_start, "end": row_start + 1, "raw_text": "A"},
        {"start": row_start + 2, "end": row_start + 3, "raw_text": "B"},
    ]


def test_table_rows_keep_physical_groups_and_exact_cell_spans() -> None:
    raw_text = (
        "第一章 资料\n"
        "3. 资料索引表\n"
        "A\tB\n"
        "C\tD\n"
        "| A | B |\n"
        "| C | D |\n"
        "\n"
        "| A | B |\n"
        "| C | D |"
    )
    result = _build([{"page_number": 1, "text": raw_text}])
    by_text = {block["raw_text"]: block for block in result["blocks"]}
    table_rows = [
        block for block in result["blocks"] if block["kind"] == "table_row"
    ]
    section_id = by_text["3. 资料索引表"]["block_id"]

    assert [block["table_row_index"] for block in table_rows] == [
        1,
        2,
        1,
        2,
        1,
        2,
    ]
    assert len({block["table_group_id"] for block in table_rows[:2]}) == 1
    assert len({block["table_group_id"] for block in table_rows[2:4]}) == 1
    assert len({block["table_group_id"] for block in table_rows[4:]}) == 1
    assert len({block["table_group_id"] for block in table_rows}) == 3
    assert table_rows[0]["table_group_id"] == table_rows[0]["block_id"]
    assert table_rows[2]["table_group_id"] == table_rows[2]["block_id"]
    assert table_rows[4]["table_group_id"] == table_rows[4]["block_id"]

    page_text = result["pages"][0]["raw_text"]
    for row in table_rows:
        assert row["parent_block_id"] == section_id
        span = row["source_span"]
        for cell in row["cell_spans"]:
            assert page_text[cell["start"] : cell["end"]] == cell["raw_text"]
            assert span["start"] <= cell["start"] <= cell["end"] <= span["end"]


def test_indented_pipe_cell_spans_use_page_global_character_offsets() -> None:
    second_page_text = "页眉\n  | A | B |\n  | C | D |"
    result = _build(
        [
            {"page_number": 4, "text": ""},
            {"page_number": 7, "text": second_page_text},
        ]
    )
    rows = [block for block in result["blocks"] if block["kind"] == "table_row"]

    assert len(rows) == 2
    for row in rows:
        assert row["page_number"] == 7
        assert row["source_span"]["start"] > 0
        for cell in row["cell_spans"]:
            assert (
                second_page_text[cell["start"] : cell["end"]]
                == cell["raw_text"]
            )
    assert [cell["raw_text"] for cell in rows[0]["cell_spans"]] == [" A ", " B "]
    assert [cell["raw_text"] for cell in rows[1]["cell_spans"]] == [" C ", " D "]


def test_cross_page_table_rows_remain_separate_with_review_candidate() -> None:
    result = _build(
        [
            {"page_number": 1, "text": "3. 资料索引表\n| A | B |"},
            {"page_number": 2, "text": "| C | D |"},
        ]
    )
    rows = [block for block in result["blocks"] if block["kind"] == "table_row"]

    assert len(rows) == 2
    assert rows[0]["table_group_id"] == rows[0]["block_id"]
    assert rows[1]["table_group_id"] == rows[1]["block_id"]
    assert rows[0]["table_group_id"] != rows[1]["table_group_id"]
    assert rows[0]["table_row_index"] == rows[1]["table_row_index"] == 1
    assert len(result["continuation_candidates"]) == 1
    candidate = result["continuation_candidates"][0]
    assert candidate["candidate_kind"] == "table_continuation"
    assert candidate["status"] == "needs_review"
    assert [item["quote"] for item in candidate["source_references"]] == [
        "| A | B |",
        "| C | D |",
    ]


def test_public_h01_cross_page_item_keeps_its_numbered_container() -> None:
    source = (
        Path(__file__).parents[1]
        / "benchmarks"
        / "raw_requirement_holdout"
        / "raw"
        / "holdout-01-qualification-finance.txt"
    )
    with source.open(encoding="utf-8", newline="") as handle:
        raw_text = handle.read()
    pages = [
        {"page_number": index, "text": text}
        for index, text in enumerate(raw_text.split("\f"), start=1)
    ]
    result = _build(pages, document_id="H01-QF-A", version="2026-09-18-r2")
    by_text = {block["raw_text"]: block for block in result["blocks"]}

    container = by_text["2.1 投标人应提供下列材料之一："]
    continuation = by_text["关键页；"]
    second_item = by_text["（2）银行出具的资信证明。"]
    assert continuation["kind"] == "paragraph"
    assert continuation["parent_block_id"] is None
    assert continuation["section_block_id"] is None
    assert second_item["parent_block_id"] == container["block_id"]
    assert second_item["numbering"]["label"] == "（2）"
    assert len(result["continuation_candidates"]) == 1
    assert [
        reference["quote"] for reference in continuation["source_references"]
    ] == ["关键页；"]
    assert [
        reference["quote"] for reference in second_item["source_references"]
    ] == ["（2）银行出具的资信证明。"]
    assert result["title_candidates"][0]["status"] == "ambiguous"
    title = by_text["采购需求摘录"]
    assert result["title_candidates"][0]["block_id"] == title["block_id"]
    assert result["title_candidates"][0]["source_references"] == (
        title["source_references"]
    )

    table_rows = [
        block for block in result["blocks"] if block["kind"] == "table_row"
    ]
    table_section = by_text["3. 资料索引表"]
    assert table_rows
    assert len({block["table_group_id"] for block in table_rows}) == 1
    assert all(
        block["parent_block_id"] == table_section["block_id"]
        for block in table_rows
    )
    final_note_text = (
        "“注册资本 5000 万元”“成立日期 2014-05-19”属于背景字段，"
        "不单独构成上述两项资格。"
    )
    final_note = by_text[final_note_text]
    assert final_note["parent_block_id"] == by_text["4. 其他说明"]["block_id"]


def test_public_h05_letter_siblings_and_h08_chapterless_restart() -> None:
    root = Path(__file__).parents[1] / "benchmarks" / "raw_requirement_holdout" / "raw"
    with (root / "holdout-05-identity-oauth-no-replace.txt").open(
        encoding="utf-8", newline=""
    ) as handle:
        h05_text = handle.read()
    h05 = _build(
        [{"page_number": 1, "text": h05_text}],
        document_id="H05-public",
    )
    h05_by_text = {block["raw_text"]: block for block in h05["blocks"]}
    h05_container = h05_by_text[
        "2.1 供应商应同时满足以下两项："
    ]["block_id"]
    assert h05_by_text[
        "（a）通过 OAuth2.0 或 OpenID Connect（OIDC）与现有身份系统完成身份对接；"
    ]["parent_block_id"] == h05_container
    assert h05_by_text[
        "（b）不得以新建登录中心、迁移账号或其他方式替换采购人现有身份系统。"
    ]["parent_block_id"] == h05_container

    with (root / "holdout-08-platform-portability-positive.txt").open(
        encoding="utf-8", newline=""
    ) as handle:
        h08_text = handle.read()
    h08_pages = [
        {"page_number": index, "text": text}
        for index, text in enumerate(h08_text.split("\f"), start=1)
    ]
    h08 = _build(h08_pages, document_id="H08-public")
    h08_by_text = {block["raw_text"]: block for block in h08["blocks"]}
    restarted_text = (
        "2.1 方案不得绑定单一公有云厂商。除云环境外，应支持采购人自有机房"
        "或其他符合条件的基础设施独立运行；不得把某一家云厂商的专有服务"
        "作为系统不可替代的前置条件。"
    )
    restarted = h08_by_text[restarted_text]
    assert restarted["numbering"]["path"] == ["2", "1"]
    assert restarted["parent_block_id"] == h08_by_text["2. 部署独立性"]["block_id"]
    assert h08["title_candidates"][0]["raw_text"] == "部署环境与数据库适配要求"


def test_title_candidate_is_not_assigned_to_every_first_line() -> None:
    numbered = _build(
        [{"page_number": 1, "text": "1. 投标人须提交材料\n后续正文"}]
    )
    sentence = _build(
        [{"page_number": 1, "text": "这是首行说明内容，且具有明确句末标点。"}]
    )

    assert numbered["title_candidates"] == []
    assert sentence["title_candidates"] == []


@pytest.mark.parametrize("page_number", [0, -1, 1.5, "invalid", True])
def test_rejects_invalid_page_numbers(page_number: object) -> None:
    with pytest.raises(ValueError, match="page_number must be a positive integer"):
        _build([{"page_number": page_number, "text": "同一原文"}])


def test_rejects_duplicate_page_numbers_and_falls_back_only_when_missing() -> None:
    with pytest.raises(ValueError, match="duplicate page_number: 1"):
        _build(
            [
                {"page_number": 1, "text": "同一原文"},
                {"page_number": 1, "text": "同一原文"},
            ]
        )

    result = _build([{"text": "第一页"}, {"text": "第二页"}])
    assert [page["page_number"] for page in result["pages"]] == [1, 2]
    assert result["blocks"][0]["block_id"] != result["blocks"][2]["block_id"]


def test_chinese_section_heading_resets_decimal_and_list_state() -> None:
    result = _build(
        [
            {
                "page_number": 1,
                "text": (
                    "1. 旧章节\n"
                    "1.1 旧条款\n"
                    "二、财务资格\n"
                    "1.1 新章节条款"
                ),
            }
        ]
    )
    by_text = {block["raw_text"]: block for block in result["blocks"]}
    new_section = by_text["二、财务资格"]
    restarted_item = by_text["1.1 新章节条款"]

    assert new_section["kind"] == "heading"
    assert new_section["numbering"]["style"] == "chinese"
    assert new_section["numbering"]["label"] == "二、"
    assert restarted_item["parent_block_id"] is None
    assert restarted_item["section_block_id"] == new_section["block_id"]
    assert any(
        "missing decimal ancestor 1" in warning for warning in result["warnings"]
    )


def test_nested_letters_share_parent_and_decimal_headings_keep_chapter_parent() -> None:
    result = _build(
        [
            {
                "page_number": 1,
                "text": (
                    "第一章 资格要求\n"
                    "1. 资格材料\n"
                    "1.1 提供材料：\n"
                    "（1）主体证明\n"
                    "  （a）营业执照\n"
                    "  （b）法人证明\n"
                    "（2）审计报告\n"
                    "2. 其他资格\n"
                    "2.1 补充材料\n"
                    "第二章 技术要求\n"
                    "1. 技术条款\n"
                    "1.1 应支持 TLS。"
                ),
            }
        ]
    )
    by_text = {block["raw_text"]: block for block in result["blocks"]}

    chapter_one = by_text["第一章 资格要求"]
    section_one = by_text["1. 资格材料"]
    materials = by_text["1.1 提供材料："]
    subject_proof = by_text["（1）主体证明"]
    license_item = by_text["  （a）营业执照"]
    legal_item = by_text["  （b）法人证明"]
    audit_item = by_text["（2）审计报告"]
    section_two = by_text["2. 其他资格"]
    section_two_child = by_text["2.1 补充材料"]

    assert chapter_one["numbering"]["label"] == "第一章"
    assert section_one["parent_block_id"] == chapter_one["block_id"]
    assert section_two["parent_block_id"] == chapter_one["block_id"]
    assert section_two_child["parent_block_id"] == section_two["block_id"]
    assert materials["parent_block_id"] == section_one["block_id"]
    assert subject_proof["parent_block_id"] == materials["block_id"]
    assert license_item["parent_block_id"] == subject_proof["block_id"]
    assert legal_item["parent_block_id"] == subject_proof["block_id"]
    assert audit_item["parent_block_id"] == materials["block_id"]
    assert license_item["source_references"][0]["quote"] == "  （a）营业执照"
    assert legal_item["source_references"][0]["quote"] == "  （b）法人证明"

    chapter_two = by_text["第二章 技术要求"]
    technical_section = by_text["1. 技术条款"]
    restarted_item = by_text["1.1 应支持 TLS。"]
    assert technical_section["parent_block_id"] == chapter_two["block_id"]
    assert restarted_item["parent_block_id"] == technical_section["block_id"]
    assert restarted_item["parent_block_id"] != section_one["block_id"]


def test_unsupported_chinese_section_hierarchy_is_explicitly_ambiguous() -> None:
    result = _build(
        [
            {
                "page_number": 1,
                "text": (
                    "第一章 资格要求\n"
                    "1. 旧一级标题\n"
                    "1.1 旧子项\n"
                    "第一节 资格材料\n"
                    "1. 新节一级标题"
                ),
            }
        ]
    )
    by_text = {block["raw_text"]: block for block in result["blocks"]}
    section = by_text["第一节 资格材料"]
    restarted = by_text["1. 新节一级标题"]

    assert section["numbering"]["label"] == "第一节"
    assert section["kind_ambiguity"] == "unsupported_chinese_section_hierarchy"
    assert restarted["parent_block_id"] is None
    assert restarted["parent_block_id"] != by_text["1. 旧一级标题"]["block_id"]
    assert any(
        "unsupported Chinese section hierarchy" in item
        for item in result["warnings"]
    )


def _assert_map_resolves(block: dict, page_text: str) -> None:
    previous_normalized_end = 0
    for item in block["normalization_map"]:
        normalized = block["normalized_text"][
            item["normalized_start"] : item["normalized_end"]
        ]
        raw = page_text[item["raw_start"] : item["raw_end"]]
        assert item["normalized_start"] == previous_normalized_end
        if item["kind"] == "identity":
            assert normalized == raw
        else:
            assert item["kind"] == "whitespace"
            assert raw and all(char.isspace() for char in raw)
            assert normalized == " "
        previous_normalized_end = item["normalized_end"]
    assert previous_normalized_end == len(block["normalized_text"])
