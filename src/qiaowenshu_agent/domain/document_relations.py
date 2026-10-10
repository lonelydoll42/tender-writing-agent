"""Conservative, source-verified relations between document conditions."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Mapping
from typing import Any

_SCHEMA_VERSION = "document-relations-v1"
_SOURCE_SCHEMA_VERSION = "document-structure-v1"
_UNVERIFIED_COORDINATE_MARKERS = (
    "unknown",
    "unverified",
    "unmarked",
    "unresolved",
    "not_set",
    "not_available",
    "partial",
    "relative",
)
_CHINESE_DIGITS = "零〇一二两三四五六七八九十"
_NUMBER_TOKEN = rf"(?:[0-9]+|[{_CHINESE_DIGITS}]+)"
_PAREN_ITEM_RE = re.compile(rf"[（(]\s*(?P<label>{_NUMBER_TOKEN})\s*[）)]")
_ALPHA_ITEM_RE = re.compile(r"^\s*(?P<label>[A-Za-z])\s*[.)、]")
_COLON_RE = re.compile(r"[：:]")
_AND_CUE_RE = re.compile(
    r"均须同时提交|均须提交|均须满足|均应满足|各项均须|各项均应|"
    r"须全部提交|须同时提交|同时满足|同时提交|同时提供|同时具备|"
    r"均须|均应|全部满足|都须满足"
)
_UNARY_CUE_RE = re.compile(r"(?:必须|须|应|需)(?:同时)?(?:提供|提交|具备|满足)")
_OR_CUE_RE = re.compile(
    r"每组只需择一|任选其一|任选一项|任意一项|任一项|任一条件|"
    r"二选一|两者择一|任取一项"
)
_COUNT_RE = re.compile(rf"(?:以下|下列)\s*(?:共|有)?\s*(?P<count>{_NUMBER_TOKEN})\s*项")
_COUNT_IN_RE = re.compile(rf"(?P<count>{_NUMBER_TOKEN})\s*项中")
_K_OF_N_RE = re.compile(
    rf"(?:以下|下列)\s*(?P<declared>{_NUMBER_TOKEN})\s*(?:类|项)"
    rf"\s*中\s*任取\s*(?P<choose>{_NUMBER_TOKEN})\s*(?:类|项)"
)
_AMBIGUOUS_COUNT_RE = re.compile(
    rf"(?:以下|下列)\s*(?:共|有)?\s*{_NUMBER_TOKEN}\s*"
    rf"(?:至|到|[-~～])\s*{_NUMBER_TOKEN}\s*项|"
    r"(?:不少于|至少|至多|不超过|若干)\s*\S{0,8}项"
)
_SCOPE_RE = re.compile(
    r"(?:以下|下列).{0,18}?(?:条件|各项|材料|证明|要求|内容|项)|"
    r"第[一二三四五六七八九十0-9]+组|"
    r"[\u4e00-\u9fff]{1,8}(?:材料|证明|条件|要求|内容)"
)
_NEGATION_RE = re.compile(
    r"不得|不应|不须|不必|无需|无须|不能|未能|不符合|未满足|不满足"
)
_REQUIREMENT_PREDICATE_RE = re.compile(
    r"(?:应当|必须|须|应|需)(?:同时)?"
    r"(?:提交|提供|出具|加盖|满足|具备|达到|具有|符合|包含|包括)|"
    r"提交|提供|出具|加盖|满足|具备|达到|符合|"
    r"列明|记载|注明|"
    r"不得低于|不得少于|不低于|不少于|"
    r"按要求|按照要求"
)
_SCOPE_COMPLETENESS_REASON = (
    "condition completeness is not explicit outside a confirmed scope"
)
_SCOPE_END_RE = re.compile(
    r"(?:以上|上述)(?:各项|条件|材料)"
    r"(?:均已满足|均已提供|满足|完毕|结束|为限)|"
    r"(?:清单|列表|条件范围)(?:至此)?(?:结束|完毕|为限)"
)
_CONTINUATION_RE = re.compile(
    r"^\s*(?:(?:[（(]\s*)?(?:续|续上页|接上页|承上页|接续上文|承接上文)"
    r"(?:\s*[）)])?|以下为(?:上文|前项|上项)(?:的)?续(?:项|列)?|"
    r"[（(]?\s*(?:承接|续接)(?:上|上一|前)页.{0,36}"
    r"(?:材料|清单|条件|要求|项目).*[）)]?)\s*[。；;]?\s*$"
)
_ANAPHORA_RE = re.compile(
    r"上述|前述|前项|前款|前条|前文所述|该材料|该复印件|该说明|"
    r"该项|该条件|该对象|营业收入|此类|"
    r"同上|其(?:应|须|需|必须|不得|不应|可|具有|提供|提交|法定代表人)"
)
_LOGIC_RE = re.compile(r"并且|或者|且|或|及|以及|并")
_NAMED_GROUP_RE = re.compile(r"第(?P<label>[一二三四五六七八九十0-9]+)组")
_COMPOSITE_GROUP_RE = re.compile(
    rf"(?P<count>{_NUMBER_TOKEN})\s*组.{{0,12}}?"
    r"(?:均须|都须|均应).{0,10}?(?:提交|满足)"
)
_GROUP_DIRECTIVE_RE = re.compile(rf"(?:{_NUMBER_TOKEN}\s*组|每组|各组)")
_GROUP_SELECTION_RE = re.compile(
    r"(?:每|各)组.{0,16}?(?:只需|仅需|择一|任选|任一|二选一|任取)"
)
_NUMBERING_META_RE = re.compile(
    r"(?:仅|只)\s*(?:按|依|依据|根据).{0,20}?(?:材料)?(?:编号|序号)"
    r".{0,12}?(?:理解|解释|认定)|"
    r"(?:编号|序号).{0,24}?(?:表示|对应|含义|解释为)"
)
_LIST_INTRO_RE = re.compile(
    r"材料项如下|材料如下|(?:材料|证明|条件)清单(?:如下)?|"
    r"(?:以下|下列).{0,10}(?:类|项|材料|证明|条件)"
)
_CONTINUED_AND_RE = re.compile(r"^\s*(?:并|且并|同时|另须|并须|并应|并需)")
_BACKWARD_SCOPE_RE = re.compile(
    rf"(?P<reference>上述|前述|以上|前项|前款)\s*"
    rf"(?:(?P<count>{_NUMBER_TOKEN})\s*项)?\s*"
    r"(?P<object>材料|条件|要求|各项)"
)
_REFERENCE_RE = re.compile(
    rf"(?:参见|详见|见|依据|根据|按照|依照|参照|引用|按)\s*第?"
    rf"(?P<label>\d+(?:[.．]\d+)*|[{_CHINESE_DIGITS}]+)\s*"
    r"(?P<unit>条|款|项)?"
)
_STANDALONE_REFERENCE_RE = re.compile(
    rf"第(?P<label>\d+(?:[.．]\d+)*|[{_CHINESE_DIGITS}]+)\s*"
    r"(?P<unit>条|款|项)"
)
_TERMINAL_RE = re.compile(r"[。；;！？!?]$")
_CONDITION_KINDS = {"paragraph", "list_item"}
_SKIP_KINDS = {"blank", "page_boundary", "heading", "table_row"}


def build_document_relations(structure: Mapping[str, Any]) -> dict[str, Any]:
    """Extract only explicitly scoped, source-verifiable document relations.

    Physical parent pointers remain candidates. They are deliberately kept
    separate from explicit condition-node membership.
    """

    if not isinstance(structure, Mapping):
        raise TypeError("structure must be a mapping")

    document_id = _nonempty_string(structure.get("document_id"))
    source_version = _nonempty_string(structure.get("source_version"))
    source_identity_valid = bool(document_id and source_version)
    source_schema_valid = structure.get("schema_version") == _SOURCE_SCHEMA_VERSION
    pages, invalid_pages = _index_pages(structure.get("pages"))
    blocks_value = structure.get("blocks")
    blocks = blocks_value if isinstance(blocks_value, list) else []

    records: list[dict[str, Any]] = []
    for index, value in enumerate(blocks):
        block = value if isinstance(value, Mapping) else {}
        valid, references, reason = _validate_block_source(
            structure,
            block,
            pages,
            invalid_pages,
            document_id=document_id,
            source_version=source_version,
            identity_valid=source_identity_valid,
            schema_valid=source_schema_valid,
        )
        block_id = block.get("block_id")
        records.append(
            {
                "index": index,
                "block": block,
                "block_id": block_id if isinstance(block_id, str) else None,
                "raw_text": block.get("raw_text")
                if isinstance(block.get("raw_text"), str)
                else "",
                "source_valid": valid,
                "source_references": references,
                "source_reason": reason,
                "kind": str(block.get("kind") or ""),
            }
        )

    id_counts: dict[str, int] = {}
    for record in records:
        if record["block_id"]:
            id_counts[record["block_id"]] = id_counts.get(record["block_id"], 0) + 1
    unique_by_id = {
        record["block_id"]: record
        for record in records
        if record["block_id"] and id_counts[record["block_id"]] == 1
    }
    for record in records:
        if record["block_id"] and id_counts.get(record["block_id"], 0) > 1:
            record["source_valid"] = False
            record["source_references"] = []
            record["source_reason"] = "block_id is duplicated"

    cyclic_ids = _parent_cycle_ids(records, unique_by_id)
    block_relations: list[dict[str, Any]] = []
    block_relation_by_index: dict[int, dict[str, Any]] = {}
    for record in records:
        relation = {
            "block_id": record["block_id"],
            "parent_relation": _parent_relation(
                record,
                unique_by_id,
                id_counts,
                cyclic_ids,
                source_identity_valid=source_identity_valid,
            ),
            "scope_relations": [],
            "reference_relations": [],
            "list_membership_relations": [],
        }
        block_relations.append(relation)
        block_relation_by_index[record["index"]] = relation

    warnings: list[str] = []
    if not records:
        warnings.append("structure contains no blocks; relations were not executed")
    if not source_identity_valid:
        warnings.append("document_id or source_version is missing")
    if not source_schema_valid:
        warnings.append("unsupported or missing document structure schema")
    if not pages:
        warnings.append("source pages are missing; source relations are unresolved")
    if invalid_pages:
        warnings.append("duplicate or invalid page numbers block source verification")

    node_builder = _NodeBuilder(
        document_id=document_id,
        source_version=source_version,
    )
    roots_by_block: dict[int, list[str]] = {}
    frame_indices: list[int] = []
    unsupported_selection_indices: list[int] = []
    composite_header_indices: list[int] = []
    backward_frames = {
        record["index"]: info
        for record in records
        if (info := _detect_backward_frame(record["raw_text"])) is not None
    }

    for record in records:
        if not record["raw_text"].strip() or record["kind"] in {
            "blank",
            "page_boundary",
            "table_row",
        }:
            continue
        if record["index"] in backward_frames:
            continue
        if _K_OF_N_RE.search(record["raw_text"]):
            unsupported_selection_indices.append(record["index"])
            opaque_reason = _opaque_clause_reason(record["raw_text"])
            root_id = node_builder.emit(
                _atom_ast(
                    record["raw_text"],
                    0,
                    len(record["raw_text"]),
                    opaque_reason,
                ),
                record,
            )
            roots_by_block[record["index"]] = [root_id]
            continue
        opaque_reason = _opaque_clause_reason(record["raw_text"])
        if opaque_reason:
            root_id = node_builder.emit(
                _atom_ast(
                    record["raw_text"],
                    0,
                    len(record["raw_text"]),
                    opaque_reason,
                ),
                record,
            )
            roots_by_block[record["index"]] = [root_id]
            continue
        if record["kind"] == "heading" and _detect_frame(record["raw_text"]) is None:
            continue
        if _COMPOSITE_GROUP_RE.search(record["raw_text"]):
            composite_header_indices.append(record["index"])
            continue
        if _CONTINUATION_RE.fullmatch(record["raw_text"]):
            continue
        inline_ast = _parse_inline_numbered_group(record)
        if inline_ast is not None:
            root_id = node_builder.emit(inline_ast, record)
            roots = [root_id]
            roots.extend(
                node_builder.emit(independent, record)
                for independent in inline_ast.get("independent_asts", [])
            )
            roots_by_block[record["index"]] = roots
            _add_inline_scope_relations(
                inline_ast,
                root_id,
                record,
                node_builder,
                block_relation_by_index[record["index"]],
            )
            continue
        unary_ast = _parse_inline_unary_group(record)
        if unary_ast is not None:
            root_id = node_builder.emit(unary_ast, record)
            roots_by_block[record["index"]] = [root_id]
            _add_inline_scope_relations(
                unary_ast,
                root_id,
                record,
                node_builder,
                block_relation_by_index[record["index"]],
            )
            continue
        delimited_ast = _parse_inline_delimited_group(record)
        if delimited_ast is not None:
            root_id = node_builder.emit(delimited_ast, record)
            roots_by_block[record["index"]] = [root_id]
            _add_inline_scope_relations(
                delimited_ast,
                root_id,
                record,
                node_builder,
                block_relation_by_index[record["index"]],
            )
            continue
        numbered_prefix = _numbered_prefix(record["raw_text"])
        expression = _parse_expression(
            record["raw_text"],
            start=numbered_prefix["end"] if numbered_prefix else 0,
            end=len(record["raw_text"]),
            depth=0,
        )
        if (
            expression is not None
            and expression["op"] in {"AND", "OR"}
            and numbered_prefix is not None
        ):
            title_span = _numbered_title_evidence_span(
                record["raw_text"],
                numbered_prefix,
            )
            if title_span is not None:
                expression["scope_spans"] = [
                    *expression.get("scope_spans", []),
                    title_span,
                ]
                expression["numbered_title_source_span"] = title_span
        if expression is not None and expression["op"] in {"AND", "OR"}:
            root_id = node_builder.emit(expression, record)
            roots_by_block[record["index"]] = [root_id]
            _add_inline_scope_relations(
                expression,
                root_id,
                record,
                node_builder,
                block_relation_by_index[record["index"]],
            )
            continue
        frame = _detect_frame(record["raw_text"])
        if frame is not None:
            frame_indices.append(record["index"])
            continue
        if expression is not None:
            root_id = node_builder.emit(expression, record)
            roots_by_block[record["index"]] = [root_id]
            _add_inline_scope_relations(
                expression,
                root_id,
                record,
                node_builder,
                block_relation_by_index[record["index"]],
            )

    physical_group_roots: list[tuple[int, str, list[int], dict[str, Any]]] = []
    for frame_index in frame_indices:
        frame_record = records[frame_index]
        frame_info = _detect_frame(frame_record["raw_text"])
        if frame_info is None:
            continue
        members, boundary_record, boundary_span, scan_reason = _scan_scoped_items(
            records,
            frame_index,
            frame_info,
        )
        preceding_frames = _has_adjacent_frame(
            records,
            frame_index,
            frame_indices,
        )
        if preceding_frames:
            scan_reason = "multiple_scope_antecedents"
        member_nodes: list[str] = []
        for member in members:
            member_index = member["record"]["index"]
            member_root_ids = roots_by_block.get(member_index, [])
            if not member_root_ids:
                fallback_ast = _atom_ast(
                    member["record"]["raw_text"],
                    member["body_start"],
                    member["body_end"],
                )
                member_root_ids = [node_builder.emit(fallback_ast, member["record"])]
                roots_by_block[member_index] = member_root_ids
            member_nodes.extend(member_root_ids)

        group, group_id, scope_object = node_builder.emit_physical_group(
            frame_record=frame_record,
            frame_info=frame_info,
            members=members,
            member_node_ids=member_nodes,
            boundary_record=boundary_record,
            boundary_span=boundary_span,
            scan_reason=scan_reason,
        )
        physical_group_roots.append(
            (
                frame_index,
                group_id,
                [member["record"]["index"] for member in members],
                scope_object,
            )
        )
        affected_indices = [
            frame_index,
            *(member["record"]["index"] for member in members),
        ]
        for affected_index in affected_indices:
            block_relation_by_index[affected_index]["scope_relations"].append(
                dict(scope_object)
            )

    backward_references: list[dict[str, Any]] = []
    resolved_anaphora_spans: dict[int, list[tuple[int, int]]] = {}
    backward_group_roots: list[tuple[int, str, list[int], dict[str, Any]]] = []
    for frame_index, frame_info in backward_frames.items():
        frame_record = records[frame_index]
        members, boundary_record, boundary_span, scan_reason = _scan_backward_items(
            records, frame_index, frame_info
        )
        member_nodes: list[str] = []
        for member in members:
            member_index = member["record"]["index"]
            member_root_ids = roots_by_block.get(member_index, [])
            if not member_root_ids:
                member_root_ids = [
                    node_builder.emit(
                        _atom_ast(
                            member["record"]["raw_text"],
                            member["body_start"],
                            member["body_end"],
                        ),
                        member["record"],
                    )
                ]
                roots_by_block[member_index] = member_root_ids
            member_nodes.extend(member_root_ids)

        _group, group_id, scope_object = node_builder.emit_physical_group(
            frame_record=frame_record,
            frame_info=frame_info,
            members=members,
            member_node_ids=member_nodes,
            boundary_record=boundary_record,
            boundary_span=boundary_span,
            scan_reason=scan_reason,
        )
        member_indices = [member["record"]["index"] for member in members]
        backward_group_roots.append(
            (frame_index, group_id, member_indices, scope_object)
        )

        antecedent_records = _backward_candidates(
            records,
            frame_index,
            members,
            scan_reason,
        )
        target_block_ids = [
            candidate["block_id"]
            for candidate in antecedent_records
            if candidate["block_id"] and id_counts.get(candidate["block_id"]) == 1
        ]
        target_node_ids = _unique(
            [
                node_id
                for candidate in antecedent_records
                for node_id in roots_by_block.get(candidate["index"], [])
            ]
        )
        antecedent_source_refs = _merge_refs(
            *[candidate["source_references"] for candidate in antecedent_records]
        )
        if scan_reason is not None:
            scope_object["target_block_ids"] = list(target_block_ids)
            scope_object["target_node_ids"] = list(target_node_ids)
            scope_object["source_references"] = _merge_refs(
                scope_object["source_references"],
                antecedent_source_refs,
            )
            group_node = node_builder.by_id[group_id]
            group_node["scope_relation"]["target_node_ids"] = list(target_node_ids)
            group_node["scope_relation"]["source_references"] = _merge_refs(
                group_node["scope_relation"]["source_references"],
                antecedent_source_refs,
            )
            group_node["source_references"] = _merge_refs(
                group_node["source_references"],
                antecedent_source_refs,
            )
        for affected_index in [frame_index, *member_indices]:
            block_relation_by_index[affected_index]["scope_relations"].append(
                dict(scope_object)
            )
        reference_status = (
            "unresolved"
            if not frame_record["source_valid"]
            else "confirmed"
            if scan_reason is None and target_block_ids
            else "candidate"
            if target_block_ids
            else "unresolved"
        )
        reference_reason = (
            frame_record["source_reason"]
            if not frame_record["source_valid"]
            else "explicit backward scope has one verified member set"
            if reference_status == "confirmed"
            else scan_reason or "backward scope is not uniquely bounded"
        )
        backward_reference = {
            "reference_id": _stable_id(
                "reference",
                frame_record["block_id"],
                frame_info["scope_span"],
                target_block_ids,
            ),
            "source_block_id": frame_record["block_id"],
            "status": reference_status,
            "target_block_ids": target_block_ids,
            "target_node_ids": target_node_ids,
            "source_references": _refs_for_span(
                frame_record,
                frame_info["scope_span"][0],
                frame_info["scope_span"][1],
            ),
            "candidate_source_references": _merge_refs(
                *[candidate["source_references"] for candidate in antecedent_records]
            )
            if reference_status != "confirmed"
            else [],
            "reason": reference_reason,
        }
        backward_references.append(backward_reference)
        block_relation_by_index[frame_index]["reference_relations"].append(
            dict(backward_reference)
        )
        resolved_anaphora_spans[frame_index] = [frame_info["scope_span"]]

    _extend_inline_groups_from_continuations(
        records,
        roots_by_block,
        node_builder,
        block_relation_by_index,
    )
    composite_group_roots = _emit_composite_groups(
        records,
        composite_header_indices,
        physical_group_roots,
        node_builder,
        block_relation_by_index,
    )

    root_ids: list[str] = []
    for index in sorted(roots_by_block):
        root_ids.extend(roots_by_block[index])
    for _frame_index, group_id, member_indices, scope_object in [
        *physical_group_roots,
        *backward_group_roots,
    ]:
        root_ids = [
            node_id
            for node_id in root_ids
            if not any(
                node_id in roots_by_block.get(member_index, [])
                for member_index in member_indices
            )
        ]
        root_ids.append(group_id)
        if scope_object["status"] != "confirmed":
            warnings.append(f"explicit scope requires review: {scope_object['reason']}")
    for _header_index, group_id, child_ids, scope_object in composite_group_roots:
        root_ids = [node_id for node_id in root_ids if node_id not in child_ids]
        root_ids.append(group_id)
        if scope_object["status"] != "confirmed":
            warnings.append(f"explicit scope requires review: {scope_object['reason']}")

    reference_nodes = _build_references(
        records,
        unique_by_id,
        id_counts,
        node_builder.nodes,
        roots_by_block,
        source_identity_valid=source_identity_valid,
        block_relation_by_index=block_relation_by_index,
        resolved_anaphora_spans=resolved_anaphora_spans,
    )
    reference_nodes = [*backward_references, *reference_nodes]
    unresolved_reference_sources = {
        item["source_block_id"]
        for item in reference_nodes
        if item["status"] != "confirmed"
    }
    for node in node_builder.nodes:
        if (
            node["op"] == "ATOM"
            and node["status"] == "confirmed"
            and any(
                block_id in unresolved_reference_sources
                for block_id in node["source_block_ids"]
            )
        ):
            node["status"] = "candidate"
            node["reason"] = "referential object does not have one verified antecedent"
    _apply_list_memberships(
        records,
        block_relation_by_index,
        roots_by_block,
        node_builder,
        unsupported_selection_indices,
    )
    _add_candidate_reference_relations(
        records,
        reference_nodes,
        block_relation_by_index,
        roots_by_block,
        node_builder.by_id,
    )
    _add_cross_page_candidate_relations(
        records,
        block_relation_by_index,
        roots_by_block,
        node_builder.by_id,
    )
    for record in records:
        _add_unresolved_reference_scope(
            record,
            block_relation_by_index[record["index"]],
        )
        _add_unknown_scope_relation(
            record,
            block_relation_by_index[record["index"]],
            roots_by_block,
            node_builder.by_id,
        )
    for relation in block_relations:
        for scope_relation in relation["scope_relations"]:
            if scope_relation["status"] != "confirmed":
                warnings.append(
                    f"scope relation requires review: {scope_relation['reason']}"
                )
        parent = relation["parent_relation"]
        if parent["status"] == "unresolved" and parent["reason"] not in {
            "no legacy parent pointer",
            "source coordinates are not verified",
        }:
            warnings.append(f"parent relation unresolved: {parent['reason']}")

    warnings = _unique(warnings)
    return {
        "schema_version": _SCHEMA_VERSION,
        "document_id": document_id,
        "source_version": source_version,
        "block_relations": block_relations,
        "condition_nodes": node_builder.nodes,
        "roots": _unique(root_ids),
        "references": reference_nodes,
        "coverage_status": "partial",
        "needs_human_review": True,
        "warnings": warnings,
    }


class _NodeBuilder:
    def __init__(self, *, document_id: str | None, source_version: str | None):
        self.document_id = document_id
        self.source_version = source_version
        self.nodes: list[dict[str, Any]] = []
        self.by_id: dict[str, dict[str, Any]] = {}

    def emit(self, ast: dict[str, Any], record: dict[str, Any]) -> str:
        if ast["op"] == "ATOM":
            return self._emit_atom(ast, record)
        child_ids = [self.emit(child, record) for child in ast.get("children", [])]
        operator_refs = _refs_for_spans(record, ast.get("operator_spans", []))
        requirement_refs = _refs_for_spans(
            record,
            ast.get("requirement_spans", []),
        )
        unary_normalization = (
            ast.get("operator_basis") == "unary_required_normalization"
        )
        operator_relation_refs = (
            [
                {**reference, "source_role": "requirement"}
                for reference in requirement_refs
            ]
            if unary_normalization
            else operator_refs
        )
        scope_refs = _refs_for_spans(record, ast.get("scope_spans", []))
        boundary_refs = _refs_for_spans(record, ast.get("boundary_spans", []))
        if ast["op"] in {"AND", "OR"}:
            boundary_refs = _merge_refs(
                boundary_refs,
                _refs_for_span(record, ast["start"], ast["end"]),
            )
        if ast.get("numbered_title_source_span"):
            boundary_refs = _merge_refs(
                boundary_refs,
                _refs_for_span(record, 0, len(record["raw_text"])),
            )
        source_ok = record["source_valid"]
        operator_status = (
            "confirmed"
            if source_ok
            and (operator_refs or (unary_normalization and requirement_refs))
            else "unresolved"
        )
        operator_reason = (
            "single mandatory branch uses the unary required normalization"
            if unary_normalization and operator_status == "confirmed"
            else "explicit operator is supported by the source"
            if operator_status == "confirmed"
            else record["source_reason"]
            if not source_ok
            else "operator source span is missing"
        )
        scope_reason = ast.get("scope_reason")
        scope_ok = bool(ast.get("scope_ok")) and source_ok and bool(scope_refs)
        scope_status = (
            "confirmed" if scope_ok else "unresolved" if not source_ok else "candidate"
        )
        if not scope_reason:
            scope_reason = (
                "explicit member and terminal boundaries are source-supported"
                if scope_ok
                else "inline scope boundary is incomplete"
            )
        status = (
            "confirmed"
            if operator_status == "confirmed" and scope_status == "confirmed"
            else "unresolved"
            if operator_status == "unresolved" or scope_status == "unresolved"
            else "candidate"
        )
        identity = _stable_id(
            "node",
            self.document_id,
            self.source_version,
            ast["op"],
            record["block_id"],
            ast["start"],
            ast["end"],
            child_ids,
            ast.get("text", ""),
        )
        scope_relation = {
            "status": scope_status,
            "target_node_ids": child_ids,
            "trigger_text": ast.get("text", ""),
            "scope_source_references": scope_refs,
            "member_source_references": _merge_refs(
                requirement_refs,
                *[
                    self.by_id[node_id].get("source_references", [])
                    for node_id in child_ids
                ]
            ),
            "requirement_source_references": requirement_refs,
            "source_references": _merge_refs(
                scope_refs,
                requirement_refs,
                *[
                    self.by_id[node_id].get("source_references", [])
                    for node_id in child_ids
                ],
            ),
            "boundary_source_references": boundary_refs,
            "reason": scope_reason,
        }
        node = {
            "node_id": identity,
            "op": ast["op"],
            "status": status,
            "text": ast.get("text", ""),
            "children": child_ids,
            "source_block_ids": [record["block_id"]] if record["block_id"] else [],
            "source_references": _merge_refs(
                operator_refs,
                requirement_refs,
                scope_relation["source_references"],
                boundary_refs,
            ),
            "operator_relation": {
                "status": operator_status,
                "source_references": operator_relation_refs,
                "reason": operator_reason,
                "kind": "unary_required_normalization"
                if unary_normalization
                else "explicit_logical_operator",
                "basis": "single_item_requirement"
                if unary_normalization
                else "explicit_operator_cue",
            },
            "operator_source_references": operator_refs,
            "scope_relation": scope_relation,
            "parent_relations": [],
        }
        self._store(node)
        self._add_child_parents(child_ids, identity, scope_relation)
        return identity

    def _emit_atom(self, ast: dict[str, Any], record: dict[str, Any]) -> str:
        text = record["raw_text"][ast["start"] : ast["end"]]
        source_refs = _refs_for_span(record, ast["start"], ast["end"])
        opaque_reason = _opaque_clause_reason(text)
        if not text.strip():
            text = ast.get("text", "")
        if not record["source_valid"]:
            status = "unresolved"
            reason = record["source_reason"]
        elif opaque_reason or ast.get("candidate_reason"):
            status = "candidate"
            reason = opaque_reason or ast["candidate_reason"]
        elif not _REQUIREMENT_PREDICATE_RE.search(text):
            status = "candidate"
            reason = _SCOPE_COMPLETENESS_REASON
        else:
            status = "confirmed"
            reason = "explicit requirement predicate is source-verified"
        identity = _stable_id(
            "node",
            self.document_id,
            self.source_version,
            "ATOM",
            record["block_id"],
            ast["start"],
            ast["end"],
            text,
        )
        node = {
            "node_id": identity,
            "op": "ATOM",
            "status": status,
            "text": text.strip(),
            "children": [],
            "source_block_ids": [record["block_id"]] if record["block_id"] else [],
            "source_references": source_refs,
            "parent_relations": [],
            "reason": reason,
        }
        if opaque_reason:
            node["role"] = "opaque"
        self._store(node)
        return identity

    def emit_physical_group(
        self,
        *,
        frame_record: dict[str, Any],
        frame_info: dict[str, Any],
        members: list[dict[str, Any]],
        member_node_ids: list[str],
        boundary_record: dict[str, Any] | None,
        boundary_span: tuple[int, int] | None,
        scan_reason: str | None,
    ) -> tuple[dict[str, Any], str, dict[str, Any]]:
        requirement_refs = (
            _refs_for_span(
                frame_record,
                frame_info["operator_span"][0],
                frame_info["operator_span"][1],
            )
            if frame_info.get("unary")
            else []
        )
        operator_refs = (
            []
            if frame_info.get("unary")
            else _refs_for_span(
                frame_record,
                frame_info["operator_span"][0],
                frame_info["operator_span"][1],
            )
        )
        unary_normalization = bool(frame_info.get("unary"))
        operator_relation_refs = (
            [
                {**reference, "source_role": "requirement"}
                for reference in requirement_refs
            ]
            if unary_normalization
            else operator_refs
        )
        scope_refs = _refs_for_span(
            frame_record,
            frame_info["scope_span"][0],
            frame_info["scope_span"][1],
        )
        boundary_refs: list[dict[str, Any]] = []
        boundary_refs.extend(frame_record["source_references"])
        if frame_info.get("count_span"):
            boundary_refs.extend(
                _refs_for_span(
                    frame_record,
                    frame_info["count_span"][0],
                    frame_info["count_span"][1],
                )
            )
        if boundary_record is not None and boundary_span is not None:
            boundary_refs.extend(
                _refs_for_span(
                    boundary_record,
                    boundary_span[0],
                    boundary_span[1],
                )
            )
        additional_boundary_records = frame_info.get(
            "additional_boundary_records",
            [],
        )
        for boundary in additional_boundary_records:
            boundary_refs.extend(boundary["source_references"])

        member_source_refs: list[dict[str, Any]] = []
        source_ok = frame_record["source_valid"]
        for member in members:
            record = member["record"]
            source_ok = source_ok and record["source_valid"]
            member_source_refs.extend(record["source_references"])
            boundary_refs.extend(record["source_references"])
        continuation_records = frame_info.get("continuation_records", [])
        continuation_source_refs: list[dict[str, Any]] = []
        for continuation in continuation_records:
            source_ok = source_ok and continuation["source_valid"]
            continuation_source_refs.extend(continuation["source_references"])
            boundary_refs.extend(continuation["source_references"])
        for boundary in additional_boundary_records:
            source_ok = source_ok and boundary["source_valid"]

        operator_status = (
            "confirmed"
            if frame_record["source_valid"]
            and (operator_refs or (unary_normalization and requirement_refs))
            else "unresolved"
        )
        operator_reason = (
            "single mandatory branch uses the unary required normalization"
            if unary_normalization and operator_status == "confirmed"
            else "explicit operator is supported by the source"
            if operator_status == "confirmed"
            else frame_record["source_reason"]
        )
        terminal_boundary = frame_info.get("terminal_boundary")
        terminal_boundary_refs = (
            _refs_for_span(
                terminal_boundary["record"],
                terminal_boundary["span"][0],
                terminal_boundary["span"][1],
            )
            if terminal_boundary
            else []
        )
        following_nonlist_record = frame_info.get("following_nonlist_record")
        following_nonlist_refs = (
            following_nonlist_record["source_references"]
            if following_nonlist_record
            else []
        )
        boundary_refs.extend(terminal_boundary_refs)
        boundary_refs.extend(following_nonlist_refs)
        scope_status = (
            "confirmed"
            if frame_info["scope_ok"]
            and scan_reason is None
            and source_ok
            and scope_refs
            and member_source_refs
            and boundary_refs
            else "unresolved"
            if not source_ok
            else "candidate"
        )
        reason = scan_reason or frame_info.get("scope_reason")
        if scope_status == "confirmed":
            reason = "explicit scope, members, and terminal boundary are verified"
        elif not reason:
            reason = "explicit scope could not be bounded from source"
        node_status = (
            "confirmed"
            if operator_status == "confirmed" and scope_status == "confirmed"
            else "unresolved"
            if operator_status == "unresolved" or scope_status == "unresolved"
            else "candidate"
        )
        source_block_ids = (
            [frame_record["block_id"]] if frame_record["block_id"] else []
        )
        source_block_ids.extend(
            member["record"]["block_id"]
            for member in members
            if member["record"]["block_id"]
        )
        source_block_ids.extend(
            continuation["block_id"]
            for continuation in continuation_records
            if continuation["block_id"]
        )
        source_block_ids.extend(
            boundary["block_id"]
            for boundary in additional_boundary_records
            if boundary["block_id"]
        )
        text_parts = [frame_record["raw_text"].strip()]
        text_parts.extend(member["record"]["raw_text"].strip() for member in members)
        text_parts.extend(
            continuation["raw_text"].strip() for continuation in continuation_records
        )
        text_parts.extend(
            boundary["raw_text"].strip() for boundary in additional_boundary_records
        )
        node_id = _stable_id(
            "node",
            self.document_id,
            self.source_version,
            frame_info["op"],
            source_block_ids,
            member_node_ids,
            frame_info["operator_span"],
            frame_info["scope_span"],
            scan_reason,
        )
        scope_object = {
            "relation_id": _stable_id("scope", node_id),
            "operator": frame_info["op"]
            if operator_status == "confirmed"
            else "UNRESOLVED",
            "status": scope_status,
            "operator_status": operator_status,
            "scope_status": scope_status,
            "trigger_text": "\n".join(text_parts),
            "operator_source_references": operator_refs,
            "requirement_source_references": requirement_refs,
            "operator_relation": {
                "status": operator_status,
                "source_references": operator_relation_refs,
                "reason": operator_reason,
                "kind": "unary_required_normalization"
                if unary_normalization
                else "explicit_logical_operator",
                "basis": "single_item_requirement"
                if unary_normalization
                else "explicit_operator_cue",
            },
            "scope_source_references": scope_refs,
            "member_source_references": _merge_refs(
                member_source_refs,
                continuation_source_refs,
            ),
            "target_block_ids": [
                member["record"]["block_id"]
                for member in members
                if member["record"]["block_id"]
            ],
            "target_node_ids": list(member_node_ids),
            "source_references": _merge_refs(
                scope_refs,
                requirement_refs,
                member_source_refs,
                continuation_source_refs,
            ),
            "boundary_source_references": _merge_refs(boundary_refs),
            "terminal_boundary_source_references": terminal_boundary_refs,
            "following_nonlist_boundary_source_references": following_nonlist_refs,
            "reason": reason,
        }
        node = {
            "node_id": node_id,
            "op": frame_info["op"],
            "status": node_status,
            "text": "\n".join(text_parts),
            "children": list(member_node_ids),
            "source_block_ids": source_block_ids,
            "source_references": _merge_refs(
                operator_refs,
                requirement_refs,
                scope_object["source_references"],
                boundary_refs,
            ),
            "operator_relation": {
                "status": operator_status,
                "source_references": operator_relation_refs,
                "reason": operator_reason,
                "kind": "unary_required_normalization"
                if unary_normalization
                else "explicit_logical_operator",
                "basis": "single_item_requirement"
                if unary_normalization
                else "explicit_operator_cue",
            },
            "operator_source_references": operator_refs,
            "scope_relation": {
                "status": scope_status,
                "operator_status": operator_status,
                "operator_relation": scope_object["operator_relation"],
                "target_node_ids": list(member_node_ids),
                "trigger_text": "\n".join(text_parts),
                "scope_source_references": scope_refs,
                "member_source_references": _merge_refs(
                    member_source_refs,
                    continuation_source_refs,
                ),
                "source_references": scope_object["source_references"],
                "requirement_source_references": requirement_refs,
                "boundary_source_references": scope_object[
                    "boundary_source_references"
                ],
                "terminal_boundary_source_references": terminal_boundary_refs,
                "following_nonlist_boundary_source_references": (
                    following_nonlist_refs
                ),
                "reason": reason,
            },
            "parent_relations": [],
        }
        self._store(node)
        self._add_child_parents(member_node_ids, node_id, node["scope_relation"])
        return node, node_id, scope_object

    def _add_child_parents(
        self,
        child_ids: list[str],
        parent_id: str,
        scope_relation: Mapping[str, Any],
    ) -> None:
        for child_id in child_ids:
            child = self.by_id.get(child_id)
            if child is None:
                continue
            if (
                scope_relation["status"] == "confirmed"
                and child["op"] == "ATOM"
                and child["status"] == "candidate"
                and child.get("reason") == _SCOPE_COMPLETENESS_REASON
            ):
                child["status"] = "confirmed"
                child["reason"] = (
                    "bare condition item belongs to a confirmed explicit scope"
                )
            child["parent_relations"].append(
                {
                    "status": scope_relation["status"],
                    "layer": "semantic_parent",
                    "basis": "explicit confirmed logical scope",
                    "target_node_ids": [parent_id],
                    "source_references": _merge_refs(
                        scope_relation.get("source_references", []),
                        scope_relation.get("boundary_source_references", []),
                    ),
                    "reason": scope_relation["reason"],
                }
            )

    def emit_composite_group(
        self,
        *,
        header_record: dict[str, Any],
        child_ids: list[str],
        scope_match: re.Match[str],
        expected_child_count: int,
    ) -> tuple[str, dict[str, Any]]:
        text = header_record["raw_text"]
        operator_match = _AND_CUE_RE.search(text)
        operator_refs = (
            _refs_for_span(header_record, operator_match.start(), operator_match.end())
            if operator_match
            else []
        )
        scope_end = operator_match.start() if operator_match else scope_match.end()
        scope_refs = _refs_for_span(header_record, scope_match.start(), scope_end)
        boundary = _terminal_span(text, 0, len(text))
        if boundary is None:
            colon = re.search(r"[：:]\s*$", text)
            boundary = (colon.start(), colon.end()) if colon else None
        boundary_refs = (
            _refs_for_span(header_record, boundary[0], boundary[1])
            if boundary
            else []
        )
        children = [
            self.by_id[node_id] for node_id in child_ids if node_id in self.by_id
        ]
        source_ok = header_record["source_valid"] and len(children) == len(child_ids)
        child_count_ok = len(child_ids) == expected_child_count
        child_sources_ok = all(
            child["status"] == "confirmed"
            and child.get("operator_relation", {}).get("status") == "confirmed"
            and child.get("scope_relation", {}).get("status") == "confirmed"
            for child in children
        )
        operator_status = (
            "confirmed" if source_ok and operator_refs else "unresolved"
        )
        scope_status = (
            "confirmed"
            if source_ok
            and child_count_ok
            and child_sources_ok
            and scope_refs
            and boundary_refs
            else "unresolved"
            if not source_ok
            else "candidate"
        )
        reason = (
            "explicit composite scope binds the named child groups"
            if scope_status == "confirmed"
            else "composite group count or child scope requires review"
        )
        node_id = _stable_id(
            "node",
            self.document_id,
            self.source_version,
            "AND",
            header_record["block_id"],
            scope_match.start(),
            scope_match.end(),
            child_ids,
        )
        child_source_refs = _merge_refs(
            *[child["source_references"] for child in children]
        )
        child_block_ids = _unique(
            [
                block_id
                for child in children
                for block_id in child["source_block_ids"]
            ]
        )
        scope_object = {
            "relation_id": _stable_id("scope", node_id),
            "operator": "AND",
            "status": scope_status,
            "trigger_text": text,
            "operator_source_references": operator_refs,
            "scope_source_references": scope_refs,
            "member_source_references": child_source_refs,
            "target_block_ids": child_block_ids,
            "target_node_ids": list(child_ids),
            "source_references": _merge_refs(scope_refs, child_source_refs),
            "boundary_source_references": boundary_refs,
            "reason": reason,
        }
        node = {
            "node_id": node_id,
            "op": "AND",
            "status": (
                "confirmed"
                if operator_status == "confirmed" and scope_status == "confirmed"
                else "unresolved"
                if operator_status == "unresolved" or scope_status == "unresolved"
                else "candidate"
            ),
            "text": text,
            "children": list(child_ids),
            "source_block_ids": _unique(
                [
                    *([header_record["block_id"]] if header_record["block_id"] else []),
                    *child_block_ids,
                ]
            ),
            "source_references": _merge_refs(
                operator_refs,
                scope_object["source_references"],
                boundary_refs,
            ),
            "operator_relation": {
                "status": operator_status,
                "source_references": operator_refs,
                "reason": (
                    "explicit AND operator is source-verified"
                    if operator_status == "confirmed"
                    else header_record["source_reason"]
                ),
            },
            "scope_relation": {
                "status": scope_status,
                "target_node_ids": list(child_ids),
                "trigger_text": text,
                "scope_source_references": scope_refs,
                "member_source_references": child_source_refs,
                "source_references": scope_object["source_references"],
                "boundary_source_references": boundary_refs,
                "reason": reason,
            },
            "parent_relations": [],
        }
        self._store(node)
        self._add_child_parents(child_ids, node_id, node["scope_relation"])
        return node_id, scope_object

    def _store(self, node: dict[str, Any]) -> None:
        self.nodes.append(node)
        self.by_id[node["node_id"]] = node


def _apply_list_memberships(
    records: list[dict[str, Any]],
    block_relations: Mapping[int, dict[str, Any]],
    roots_by_block: Mapping[int, list[str]],
    node_builder: _NodeBuilder,
    unsupported_selection_indices: list[int],
) -> None:
    groups: dict[int, list[dict[str, Any]]] = {}
    group_scan_reasons: dict[int, str] = {}
    for header in records:
        if not _LIST_INTRO_RE.search(header["raw_text"]):
            continue
        members: list[dict[str, Any]] = []
        previous_item: dict[str, Any] | None = None
        top_level_item: dict[str, Any] | None = None
        cursor = header["index"] + 1
        while cursor < len(records):
            record = records[cursor]
            if record["kind"] == "blank":
                cursor += 1
                continue
            if record["kind"] in {"page_boundary", "heading"}:
                break
            item = _numbered_prefix(record["raw_text"])
            if item is None:
                break
            if previous_item is None:
                if item["number"] != 1:
                    group_scan_reasons[header["index"]] = (
                        "visible list does not begin with member 1"
                    )
                    break
                top_level_item = item
            elif _same_numbered_sequence(previous_item, item):
                if len(item["path"]) == 1:
                    top_level_item = item
                elif top_level_item is not None:
                    group_scan_reasons[header["index"]] = (
                        "visible list contains a nested numbering family"
                    )
            elif top_level_item is not None and _is_next_top_level_item(
                top_level_item,
                item,
            ):
                top_level_item = item
                group_scan_reasons[header["index"]] = (
                    group_scan_reasons.get(header["index"])
                    or "visible list contains a nested numbering family"
                )
            elif top_level_item is not None and _is_first_nested_item(
                top_level_item,
                item,
            ):
                group_scan_reasons[header["index"]] = (
                    "visible list contains a nested numbering family"
                )
            else:
                group_scan_reasons[header["index"]] = (
                    "visible list has a numbering gap, duplicate, or new nested family"
                )
                break
            members.append({"record": record, "item": item})
            previous_item = item
            cursor += 1
        if members:
            groups[header["index"]] = members

    for header_index, members in groups.items():
        header = records[header_index]
        member_block_ids = [
            member["record"]["block_id"]
            for member in members
            if member["record"]["block_id"]
        ]
        structural_refs = _merge_refs(
            header["source_references"],
            *[member["record"]["source_references"] for member in members],
        )
        block_relations[header_index]["list_membership_relations"].append(
            {
                "relation_id": _stable_id(
                    "structural_list",
                    header["block_id"],
                    member_block_ids,
                ),
                "status": "confirmed"
                if header["source_valid"]
                and all(member["record"]["source_valid"] for member in members)
                else "unresolved",
                "layer": "structural_list",
                "basis": "structural_list_membership",
                "target_block_ids": member_block_ids,
                "source_references": structural_refs,
                "reason": (
                    "explicit list introduction establishes visible membership"
                    if header["source_valid"]
                    and all(member["record"]["source_valid"] for member in members)
                    else "list introduction or member source is unverified"
                ),
            }
        )
        for member in members:
            record = member["record"]
            status = (
                "confirmed"
                if header["source_valid"] and record["source_valid"]
                else "unresolved"
            )
            source_refs = _merge_refs(
                header["source_references"],
                record["source_references"],
            )
            header_node_ids = roots_by_block.get(header_index, [])
            parent_relation = {
                "relation_id": _stable_id(
                    "structural_list_membership",
                    header["block_id"],
                    record["block_id"],
                ),
                "status": status,
                "layer": "structural_list",
                "basis": "structural_list_membership",
                "target_block_ids": [header["block_id"]]
                if header["block_id"]
                else [],
                "target_node_ids": header_node_ids
                if len(header_node_ids) == 1
                else [],
                "source_references": source_refs,
                "reason": (
                    "explicit list introduction establishes structural membership"
                    if status == "confirmed"
                    else "list introduction or member source is unverified"
                ),
            }
            block_relations[record["index"]]["list_membership_relations"].append(
                dict(parent_relation)
            )
            item = member["item"]
            if len(item["path"]) > 1:
                parent_path = item["path"][:-1]
                numbered_parent = next(
                    (
                        candidate
                        for candidate in reversed(members)
                        if candidate is not member
                        and candidate["record"]["index"] < record["index"]
                        and candidate["item"]["path"] == parent_path
                    ),
                    None,
                )
                if numbered_parent is not None:
                    numbered_parent_record = numbered_parent["record"]
                    hierarchy_relation = {
                        "relation_id": _stable_id(
                            "numbered_hierarchy_candidate",
                            record["block_id"],
                            numbered_parent_record["block_id"],
                        ),
                        "status": "candidate"
                        if record["source_valid"]
                        and numbered_parent_record["source_valid"]
                        else "unresolved",
                        "layer": "structural_hierarchy",
                        "basis": "nested_numbering_parent_candidate",
                        "target_block_ids": [numbered_parent_record["block_id"]]
                        if numbered_parent_record["block_id"]
                        else [],
                        "target_node_ids": roots_by_block.get(
                            numbered_parent_record["index"],
                            [],
                        ),
                        "source_references": _merge_refs(
                            record["source_references"],
                            numbered_parent_record["source_references"],
                        ),
                        "reason": (
                            "numbering suggests a nested parent but does not "
                            "confirm semantic scope"
                        ),
                    }
                    for node_id in roots_by_block.get(record["index"], []):
                        node = node_builder.by_id.get(node_id)
                        if node is not None:
                            node["parent_relations"].append(
                                dict(hierarchy_relation)
                            )
            for node_id in roots_by_block.get(record["index"], []):
                node = node_builder.by_id.get(node_id)
                if node is None:
                    continue
                if (
                    status == "confirmed"
                    and _REQUIREMENT_PREDICATE_RE.search(header["raw_text"])
                    and node["op"] == "ATOM"
                    and node["status"] == "candidate"
                    and node.get("reason") == _SCOPE_COMPLETENESS_REASON
                ):
                    node["status"] = "confirmed"
                    node["reason"] = (
                        "visible listed option is source-verified; selection scope "
                        "is represented separately"
                    )
                node["parent_relations"].append(dict(parent_relation))

        if (
            header_index not in unsupported_selection_indices
            and not block_relations[header_index]["scope_relations"]
        ):
            nested_family = any(
                len(member["item"]["path"]) > 1 for member in members
            )
            scope_status = "unresolved" if nested_family else "candidate"
            scope = {
                "relation_id": _stable_id(
                    "unresolved_list_scope",
                    header["block_id"],
                    member_block_ids,
                ),
                "operator": "UNRESOLVED",
                "status": scope_status
                if header["source_valid"]
                and all(member["record"]["source_valid"] for member in members)
                else "unresolved",
                "operator_status": "unresolved",
                "scope_status": scope_status
                if header["source_valid"]
                and all(member["record"]["source_valid"] for member in members)
                else "unresolved",
                "target_block_ids": member_block_ids,
                "target_node_ids": _unique(
                    [
                        node_id
                        for member in members
                        for node_id in roots_by_block.get(
                            member["record"]["index"],
                            [],
                        )
                    ]
                ),
                "trigger_text": header["raw_text"],
                "scope_source_references": list(header["source_references"]),
                "member_source_references": _merge_refs(
                    *[member["record"]["source_references"] for member in members]
                ),
                "operator_source_references": [],
                "source_references": structural_refs,
                "operator_relation": {
                    "status": "unresolved",
                    "source_references": [],
                    "reason": "no explicit logical AND/OR operator is present",
                },
                "boundary_source_references": _merge_refs(
                    *[
                        _refs_for_span(
                            member["record"],
                            0,
                            member["item"]["end"],
                        )
                        for member in members
                    ]
                ),
                "missing_member_count": None,
                "reason": (
                    "structural list membership does not establish a logical "
                    "AND/OR operator"
                    + (
                        f"; {group_scan_reasons[header_index]}"
                        if header_index in group_scan_reasons
                        else ""
                    )
                ),
            }
            for index in [
                header_index,
                *(member["record"]["index"] for member in members),
            ]:
                block_relations[index]["scope_relations"].append(dict(scope))

    for header_index in unsupported_selection_indices:
        header = records[header_index]
        members = groups.get(header_index, [])
        match = _K_OF_N_RE.search(header["raw_text"])
        if match is None:
            continue
        member_node_ids = _unique(
            [
                node_id
                for member in members
                for node_id in roots_by_block.get(member["record"]["index"], [])
            ]
        )
        member_records = [member["record"] for member in members]
        source_valid = header["source_valid"] and all(
            member["source_valid"] for member in member_records
        )
        declared_count = _parse_count(match.group("declared"))
        missing_member_count = (
            max(declared_count - len(member_records), 0)
            if declared_count is not None
            else None
        )
        operator_refs = _refs_for_span(header, match.start(), match.end())
        context_refs = _merge_refs(
            header["source_references"],
            *[member["source_references"] for member in member_records],
        )
        boundary_refs = [
            reference
            for member in members
            for reference in _refs_for_span(
                member["record"],
                0,
                member["item"]["end"],
            )
        ]
        if member_records:
            final = member_records[-1]
            terminal = _terminal_span(final["raw_text"], 0, len(final["raw_text"]))
            if terminal:
                boundary_refs.extend(
                    _refs_for_span(final, terminal[0], terminal[1])
                )
        scope = {
            "relation_id": _stable_id(
                "unsupported_selection_scope",
                header["block_id"],
                match.start(),
                match.end(),
                [member["record"]["block_id"] for member in members],
            ),
            "operator": "UNRESOLVED",
            "status": "candidate" if source_valid else "unresolved",
            "operator_status": "unresolved",
            "scope_status": "candidate" if source_valid else "unresolved",
            "target_block_ids": [
                member["record"]["block_id"]
                for member in members
                if member["record"]["block_id"]
            ],
            "target_node_ids": member_node_ids,
            "trigger_text": header["raw_text"],
            "operator_source_references": operator_refs,
            "scope_source_references": list(header["source_references"]),
            "member_source_references": _merge_refs(
                *[member["record"]["source_references"] for member in members]
            ),
            "source_references": _merge_refs(
                header["source_references"],
                *[member["record"]["source_references"] for member in members],
            ),
            "boundary_source_references": _merge_refs(boundary_refs),
            "missing_member_count": missing_member_count,
            "operator_relation": {
                "status": "unresolved",
                "source_references": context_refs,
                "cue_source_references": operator_refs,
                "context_source_references": context_refs,
                "reason": (
                    "K-of-N selection cardinality is outside the supported grammar"
                ),
            },
            "reason": (
                "K-of-N selection cardinality is outside the supported grammar"
                if not missing_member_count
                else "visible list is missing declared members; K-of-N selection "
                "cardinality is outside the supported grammar"
            ),
        }
        affected_indices = [
            header_index,
            *(member["record"]["index"] for member in members),
        ]
        for index in affected_indices:
            block_relations[index]["scope_relations"].append(dict(scope))
        semantic_parent = {
            "relation_id": _stable_id(
                "unsupported_k_of_n_parent",
                header["block_id"],
                [member["record"]["block_id"] for member in members],
            ),
            "status": "unresolved",
            "layer": "semantic_parent",
            "basis": "unsupported_k_of_n_selection",
            "target_block_ids": [header["block_id"]]
            if header["block_id"]
            else [],
            "target_node_ids": roots_by_block.get(header_index, []),
            "source_references": context_refs,
            "reason": (
                "selection cardinality is outside the supported grammar; "
                "semantic parentage is not confirmed"
            ),
        }
        for member in members:
            for node_id in roots_by_block.get(member["record"]["index"], []):
                node = node_builder.by_id.get(node_id)
                if node is not None:
                    node["parent_relations"].append(dict(semantic_parent))


def _extend_inline_groups_from_continuations(
    records: list[dict[str, Any]],
    roots_by_block: dict[int, list[str]],
    node_builder: _NodeBuilder,
    block_relations: Mapping[int, dict[str, Any]],
) -> None:
    for boundary_index, boundary in enumerate(records):
        if boundary["kind"] != "page_boundary":
            continue
        note_index = boundary_index + 1
        while note_index < len(records) and records[note_index]["kind"] == "blank":
            note_index += 1
        if note_index >= len(records):
            continue
        note = records[note_index]
        if not _CONTINUATION_RE.fullmatch(note["raw_text"]) or not note["source_valid"]:
            continue
        member_index = note_index + 1
        while (
            member_index < len(records)
            and records[member_index]["kind"] == "blank"
        ):
            member_index += 1
        if member_index >= len(records):
            continue
        member = records[member_index]
        if (
            not member["source_valid"]
            or not _CONTINUED_AND_RE.match(member["raw_text"])
            or not _REQUIREMENT_PREDICATE_RE.search(member["raw_text"])
        ):
            continue

        previous_index = boundary_index - 1
        while previous_index >= 0 and records[previous_index]["kind"] in {
            "blank",
            "page_boundary",
        }:
            previous_index -= 1
        if previous_index < 0:
            continue
        group_id = next(
            (
                node_id
                for node_id in reversed(roots_by_block.get(previous_index, []))
                if node_id in node_builder.by_id
                and node_builder.by_id[node_id]["op"] == "AND"
                and node_builder.by_id[node_id]["status"] == "confirmed"
                and node_builder.by_id[node_id]["scope_relation"]["status"]
                == "confirmed"
            ),
            None,
        )
        if group_id is None:
            continue
        group = node_builder.by_id[group_id]
        quoted = re.search(r"[“「『\"']([^”」』\"']{1,20})[”」』\"']", note["raw_text"])
        if quoted and quoted.group(1) not in group["text"]:
            continue
        member_node_ids = roots_by_block.get(member_index, [])
        if len(member_node_ids) != 1:
            continue
        member_node = node_builder.by_id.get(member_node_ids[0])
        if (
            member_node is None
            or member_node["op"] != "ATOM"
            or member_node["status"] != "confirmed"
        ):
            continue

        old_group_id = group_id
        new_children = [*group["children"], member_node["node_id"]]
        new_source_block_ids = _unique(
            [
                *group["source_block_ids"],
                note["block_id"],
                member["block_id"],
            ]
        )
        new_group_id = _stable_id(
            "node",
            node_builder.document_id,
            node_builder.source_version,
            "AND",
            new_source_block_ids,
            new_children,
            "explicit_cross_page_continuation",
        )
        note_refs = note["source_references"]
        member_refs = member_node["source_references"]
        terminal = _terminal_span(member["raw_text"], 0, len(member["raw_text"]))
        terminal_refs = (
            _refs_for_span(member, terminal[0], terminal[1]) if terminal else []
        )
        scope = group["scope_relation"]
        scope["relation_id"] = _stable_id("scope", new_group_id)
        scope["target_node_ids"] = new_children
        scope["source_references"] = _merge_refs(
            scope["source_references"],
            note_refs,
            member_refs,
        )
        scope["member_source_references"] = _merge_refs(
            scope["member_source_references"],
            member_refs,
        )
        scope["boundary_source_references"] = _merge_refs(
            scope["boundary_source_references"],
            note_refs,
            terminal_refs,
        )
        scope["reason"] = (
            "explicit operator and source-verified cross-page continuation bind "
            "the additional member"
        )
        group["node_id"] = new_group_id
        group["children"] = new_children
        group["source_block_ids"] = new_source_block_ids
        group["text"] = "\n".join(
            [group["text"], note["raw_text"], member["raw_text"]]
        )
        group["source_references"] = _merge_refs(
            group["source_references"],
            note_refs,
            member_refs,
            terminal_refs,
        )
        node_builder.by_id.pop(old_group_id, None)
        node_builder.by_id[new_group_id] = group

        for node in node_builder.nodes:
            if node is group:
                continue
            node["children"] = [
                new_group_id if child_id == old_group_id else child_id
                for child_id in node["children"]
            ]
            node.get("scope_relation", {})["target_node_ids"] = [
                new_group_id if child_id == old_group_id else child_id
                for child_id in node.get("scope_relation", {}).get(
                    "target_node_ids",
                    [],
                )
            ]
            for relation in node.get("parent_relations", []):
                relation["target_node_ids"] = [
                    new_group_id if child_id == old_group_id else child_id
                    for child_id in relation.get("target_node_ids", [])
                ]
        for child_id in new_children:
            child = node_builder.by_id.get(child_id)
            if child is None:
                continue
            for relation in child.get("parent_relations", []):
                relation["target_node_ids"] = [
                    new_group_id if parent_id == old_group_id else parent_id
                    for parent_id in relation.get("target_node_ids", [])
                ]
            if child_id == member_node["node_id"]:
                child["parent_relations"].append(
                    {
                        "status": "confirmed",
                        "basis": "explicit_logical_scope",
                        "target_node_ids": [new_group_id],
                        "source_references": _merge_refs(
                            scope["source_references"],
                            scope["boundary_source_references"],
                        ),
                        "reason": scope["reason"],
                    }
                )

        roots_by_block[previous_index] = [
            new_group_id if node_id == old_group_id else node_id
            for node_id in roots_by_block.get(previous_index, [])
        ]
        roots_by_block[member_index] = [
            node_id
            for node_id in roots_by_block.get(member_index, [])
            if node_id != member_node["node_id"]
        ]
        relation_id = _stable_id("scope", old_group_id)
        for block_relation in block_relations.values():
            for relation in block_relation["scope_relations"]:
                if relation.get("relation_id") != relation_id:
                    continue
                relation["relation_id"] = scope["relation_id"]
                relation["target_block_ids"] = _unique(
                    [
                        *relation.get("target_block_ids", []),
                        member["block_id"],
                    ]
                )
                relation["target_node_ids"] = new_children
                relation["trigger_text"] = group["text"]
                relation["source_references"] = _merge_refs(
                    relation.get("source_references", []),
                    note_refs,
                    member_refs,
                    terminal_refs,
                )
                relation["member_source_references"] = _merge_refs(
                    relation.get("member_source_references", []),
                    member_refs,
                )
                relation["boundary_source_references"] = _merge_refs(
                    relation.get("boundary_source_references", []),
                    note_refs,
                    terminal_refs,
                )
        extended_relation = {
            "relation_id": scope["relation_id"],
            "operator": "AND",
            "status": "confirmed",
            "target_block_ids": list(new_source_block_ids),
            "target_node_ids": new_children,
            "trigger_text": group["text"],
            "scope_source_references": list(
                scope.get("scope_source_references", [])
            ),
            "member_source_references": list(
                scope["member_source_references"]
            ),
            "source_references": _merge_refs(
                group["operator_relation"]["source_references"],
                scope["source_references"],
            ),
            "operator_source_references": list(
                group["operator_relation"]["source_references"]
            ),
            "boundary_source_references": list(
                scope["boundary_source_references"]
            ),
            "reason": scope["reason"],
        }
        for index in (note_index, member_index):
            block_relations[index]["scope_relations"].append(
                dict(extended_relation)
            )


def _emit_composite_groups(
    records: list[dict[str, Any]],
    header_indices: list[int],
    physical_group_roots: list[tuple[int, str, list[int], dict[str, Any]]],
    node_builder: _NodeBuilder,
    block_relations: Mapping[int, dict[str, Any]],
) -> list[tuple[int, str, list[str], dict[str, Any]]]:
    output: list[tuple[int, str, list[str], dict[str, Any]]] = []
    block_index_by_id = {
        record["block_id"]: record["index"]
        for record in records
        if record["block_id"]
    }
    for header_index in header_indices:
        header = records[header_index]
        match = _COMPOSITE_GROUP_RE.search(header["raw_text"])
        expected_count = (
            _parse_count(match.group("count")) if match is not None else None
        )
        if match is None or expected_count is None:
            continue
        child_ids: list[str] = []
        expected_label = 1
        for frame_index, group_id, member_indices, _scope in sorted(
            physical_group_roots
        ):
            if frame_index <= header_index:
                continue
            if any(
                records[index]["kind"] == "heading"
                and _NAMED_GROUP_RE.search(records[index]["raw_text"]) is None
                for index in range(header_index + 1, frame_index)
            ):
                break
            named = _NAMED_GROUP_RE.search(records[frame_index]["raw_text"])
            if named is None:
                continue
            label = _parse_count(named.group("label"))
            if label != expected_label:
                break
            child_ids.append(group_id)
            expected_label += 1
            if len(child_ids) == expected_count:
                break

        group_id, scope = node_builder.emit_composite_group(
            header_record=header,
            child_ids=child_ids,
            scope_match=match,
            expected_child_count=expected_count,
        )
        target_blocks = list(scope["target_block_ids"])
        affected_indices = _unique(
            [
                header_index,
                *[
                    block_index_by_id[block_id]
                    for block_id in target_blocks
                    if block_id in block_index_by_id
                ],
            ]
        )
        for index in affected_indices:
            block_relations[index]["scope_relations"].append(
                {
                    "relation_id": scope["relation_id"],
                    "operator": "AND",
                    "status": scope["status"],
                    "target_block_ids": target_blocks,
                    "target_node_ids": list(child_ids),
                    "trigger_text": header["raw_text"],
                    "scope_source_references": list(
                        scope["scope_source_references"]
                    ),
                    "member_source_references": list(
                        scope["member_source_references"]
                    ),
                    "source_references": _merge_refs(
                        scope["operator_source_references"],
                        scope["source_references"],
                    ),
                    "operator_source_references": list(
                        scope["operator_source_references"]
                    ),
                    "boundary_source_references": list(
                        scope["boundary_source_references"]
                    ),
                    "reason": scope["reason"],
                }
            )
        output.append((header_index, group_id, child_ids, scope))
    return output


def _add_inline_scope_relations(
    ast: dict[str, Any],
    root_id: str,
    record: dict[str, Any],
    node_builder: _NodeBuilder,
    block_relation: dict[str, Any],
) -> None:
    pending = [root_id]
    seen: set[str] = set()
    while pending:
        node_id = pending.pop()
        if node_id in seen:
            continue
        seen.add(node_id)
        node = node_builder.by_id.get(node_id)
        if node is None:
            continue
        pending.extend(node["children"])
        if node["op"] not in {"AND", "OR"}:
            continue
        scope = node["scope_relation"]
        operator_status = node["operator_relation"]["status"]
        scope_status = scope["status"]
        block_relation["scope_relations"].append(
            {
                "relation_id": _stable_id("scope", node_id),
                "operator": node["op"]
                if operator_status == "confirmed"
                else "UNRESOLVED",
                "status": scope_status
                if operator_status == "confirmed"
                else "unresolved",
                "operator_status": operator_status,
                "scope_status": scope_status,
                "target_block_ids": [record["block_id"]]
                if node["children"] and record["block_id"]
                else [],
                "target_node_ids": list(node["children"]),
                "trigger_text": node["text"],
                "scope_source_references": list(
                    scope.get("scope_source_references", [])
                ),
                "member_source_references": list(
                    scope.get("member_source_references", [])
                ),
                "source_references": _merge_refs(
                    node["operator_relation"]["source_references"],
                    scope["source_references"],
                ),
                "operator_source_references": list(
                    node.get(
                        "operator_source_references",
                        node["operator_relation"]["source_references"],
                    )
                ),
                "boundary_source_references": list(scope["boundary_source_references"]),
                "operator_relation": node["operator_relation"],
                "reason": node["operator_relation"]["reason"]
                if operator_status != "confirmed"
                else scope["reason"],
            }
        )

    if (
        ast["op"] == "ATOM"
        and ast.get("candidate_reason")
        and (
            _LOGIC_RE.search(ast.get("text", ""))
            or _NEGATION_RE.search(ast.get("text", ""))
        )
    ):
        connectors = _top_level_connectors(
            record["raw_text"],
            ast["start"],
            ast["end"],
        )
        operator_refs = _refs_for_spans(
            record,
            [
                (start, end)
                for _op, start, end in connectors
                if record["raw_text"][start:end] != "、"
            ],
        )
        negation = _NEGATION_RE.search(ast.get("text", ""))
        operator_candidates = _unique(
            [operator for operator, _start, _end in connectors]
        )
        if negation:
            operator_refs = _merge_refs(
                operator_refs,
                _refs_for_span(
                    record,
                    ast["start"] + negation.start(),
                    ast["start"] + negation.end(),
                ),
            )
            for pattern, operator in ((_AND_CUE_RE, "AND"), (_OR_CUE_RE, "OR")):
                matches = list(
                    pattern.finditer(record["raw_text"], ast["start"], ast["end"])
                )
                if matches:
                    operator_candidates.append(operator)
        operator_candidates = _unique(operator_candidates)
        scope_refs = _refs_for_span(record, ast["start"], ast["end"])
        boundary = _terminal_span(
            record["raw_text"],
            ast["start"],
            ast["end"],
        )
        boundary_refs = (
            _refs_for_span(record, boundary[0], boundary[1]) if boundary else []
        )
        block_relation["scope_relations"].append(
            {
                "relation_id": _stable_id(
                    "unresolved_scope",
                    record["block_id"],
                    ast["start"],
                    ast["end"],
                    ast.get("text", ""),
                ),
                "operator": "UNRESOLVED",
                "status": "candidate" if record["source_valid"] else "unresolved",
                "operator_status": (
                    "candidate" if record["source_valid"] else "unresolved"
                ),
                "scope_status": (
                    "candidate" if record["source_valid"] else "unresolved"
                ),
                "operator_candidates": operator_candidates,
                "target_block_ids": [],
                "target_node_ids": [],
                "source_references": _merge_refs(operator_refs, scope_refs),
                "operator_source_references": operator_refs,
                "boundary_source_references": boundary_refs,
                "operator_relation": {
                    "status": "candidate" if record["source_valid"] else "unresolved",
                    "source_references": operator_refs,
                    "reason": "unsupported NOT is retained for manual review"
                    if negation
                    else ast["candidate_reason"],
                },
                "reason": ast["candidate_reason"],
                "trigger_text": record["raw_text"],
            }
        )


def _add_unresolved_reference_scope(
    record: dict[str, Any],
    block_relation: dict[str, Any],
) -> None:
    unresolved_refs = [
        reference
        for reference in block_relation["reference_relations"]
        if reference["status"] != "confirmed"
    ]
    if not unresolved_refs or block_relation["scope_relations"]:
        return
    raw_text = record["raw_text"]
    and_matches = list(_AND_CUE_RE.finditer(raw_text))
    or_matches = list(_OR_CUE_RE.finditer(raw_text))
    connectors = [
        (operator, start, end)
        for operator, start, end in _top_level_connectors(
            raw_text,
            0,
            len(raw_text),
        )
        if raw_text[start:end] != "、"
    ]
    and_spans = [
        (match.start(), match.end()) for match in and_matches
    ] + [(start, end) for operator, start, end in connectors if operator == "AND"]
    or_spans = [
        (match.start(), match.end()) for match in or_matches
    ] + [(start, end) for operator, start, end in connectors if operator == "OR"]
    if not and_spans and not or_spans:
        return
    operator = (
        "UNRESOLVED" if and_spans and or_spans else "AND" if and_spans else "OR"
    )
    operator_spans = list(dict.fromkeys([*and_spans, *or_spans]))
    operator_refs = _refs_for_spans(record, operator_spans)
    boundary = _terminal_span(raw_text, 0, len(raw_text))
    boundary_refs = _refs_for_span(record, boundary[0], boundary[1]) if boundary else []
    block_relation["scope_relations"].append(
        {
            "relation_id": _stable_id(
                "unresolved_reference_scope",
                record["block_id"],
                operator_spans,
                [item["reference_id"] for item in unresolved_refs],
            ),
            "operator": operator,
            "status": "candidate" if record["source_valid"] else "unresolved",
            "operator_status": "candidate" if record["source_valid"] else "unresolved",
            "scope_status": "candidate" if record["source_valid"] else "unresolved",
            "target_block_ids": _unique(
                [
                    block_id
                    for reference in unresolved_refs
                    for block_id in reference["target_block_ids"]
                ]
            ),
            "target_node_ids": _unique(
                [
                    node_id
                    for reference in unresolved_refs
                    for node_id in reference["target_node_ids"]
                ]
            ),
            "source_references": _merge_refs(
                operator_refs,
                *[reference["source_references"] for reference in unresolved_refs],
                *[
                    reference.get("candidate_source_references", [])
                    for reference in unresolved_refs
                ],
            ),
            "operator_source_references": operator_refs,
            "boundary_source_references": boundary_refs,
            "reason": "operator scope depends on an unresolved referential object",
            "trigger_text": raw_text,
        }
    )


def _add_unknown_scope_relation(
    record: dict[str, Any],
    block_relation: dict[str, Any],
    roots_by_block: Mapping[int, list[str]],
    nodes_by_id: Mapping[str, dict[str, Any]],
) -> None:
    if block_relation["scope_relations"]:
        return
    node_ids = roots_by_block.get(record["index"], [])
    uncertain_nodes = [
        nodes_by_id[node_id]
        for node_id in node_ids
        if node_id in nodes_by_id
        and nodes_by_id[node_id]["op"] == "ATOM"
        and nodes_by_id[node_id]["status"] != "confirmed"
    ]
    if not uncertain_nodes:
        return
    unresolved = not record["source_valid"] or any(
        node["status"] == "unresolved" for node in uncertain_nodes
    )
    negation = _NEGATION_RE.search(record["raw_text"])
    operator_refs = (
        _refs_for_span(record, negation.start(), negation.end())
        if negation
        else []
    )
    boundary = _terminal_span(record["raw_text"], 0, len(record["raw_text"]))
    block_relation["scope_relations"].append(
        {
            "relation_id": _stable_id(
                "unknown_scope",
                record["block_id"],
                record["raw_text"],
            ),
            "operator": "UNRESOLVED" if negation else "UNKNOWN",
            "status": "unresolved" if unresolved else "candidate",
            "target_block_ids": [],
            "target_node_ids": list(node_ids),
            "trigger_text": record["raw_text"],
            "source_references": list(record["source_references"]),
            "operator_source_references": operator_refs,
            "operator_relation": {
                "status": "unresolved" if unresolved else "candidate",
                "source_references": operator_refs,
                "reason": "unsupported NOT is retained for manual review"
                if negation
                else "operator and member scope are not explicit",
            },
            "boundary_source_references": (
                _refs_for_span(record, boundary[0], boundary[1]) if boundary else []
            ),
            "reason": next(
                (node.get("reason") for node in uncertain_nodes if node.get("reason")),
                "unsupported NOT or no explicit scope boundary is established"
                if negation
                else "no explicit scope boundary or membership is established",
            ),
        }
    )


def _parse_inline_numbered_group(
    record: dict[str, Any],
) -> dict[str, Any] | None:
    raw_text = record["raw_text"]
    prefix = _numbered_prefix(raw_text)
    body_start = prefix["end"] if prefix else 0
    markers = list(_PAREN_ITEM_RE.finditer(raw_text, body_start))
    if not markers:
        return None
    info = _detect_frame(raw_text[: markers[0].start()])
    if info is None or (len(markers) < 2 and not info["unary"]):
        return None

    labels = [_simple_number(match.group("label")) for match in markers]
    styles = [
        "decimal"
        if match.group("label").isascii() and match.group("label").isdigit()
        else "chinese"
        for match in markers
    ]
    scope_ok = info["scope_ok"]
    reason: str | None = info["scope_reason"] if not scope_ok else None
    count = info["count"]
    if len(set(styles)) != 1 or any(label is None for label in labels):
        scope_ok = False
        reason = "inline list numbering is ambiguous"
        selected_count = len(markers)
    elif count is not None:
        selected_count = count
        if count == 1 and not info["unary"]:
            scope_ok = False
            reason = "a one-member scope is not explicitly mandatory"
        if len(markers) < count:
            scope_ok = False
            reason = "explicit item count is not present in the source list"
        elif labels[:count] != list(range(1, count + 1)):
            scope_ok = False
            reason = "inline list has missing or duplicate member numbers"
    else:
        selected_count = len(markers)
        if info["unary"]:
            selected_count = 1
            if len(markers) > 1 and labels[:1] != [1]:
                scope_ok = False
                reason = "unary scope has an ambiguous numbered member"
        elif info["op"] == "OR":
            if labels != list(range(1, len(markers) + 1)):
                scope_ok = False
                reason = "OR list has missing or duplicate member numbers"
            elif not _TERMINAL_RE.search(raw_text.rstrip()):
                scope_ok = False
                reason = "OR scope has no explicit terminal boundary"
        elif labels != list(range(1, len(markers) + 1)):
            scope_ok = False
            reason = "inline list has missing or duplicate member numbers"
        elif not _TERMINAL_RE.search(raw_text.rstrip()):
            scope_ok = False
            reason = "inline AND list has no explicit terminal boundary"

    if selected_count < 2 and not info["unary"]:
        scope_ok = False
        reason = reason or "a condition group needs at least two members"
        selected_count = min(len(markers), 1)
    children: list[dict[str, Any]] = []
    member_spans: list[tuple[int, int]] = []
    for index, marker in enumerate(markers[:selected_count]):
        member_start = marker.end()
        member_end = (
            markers[index + 1].start() if index + 1 < len(markers) else len(raw_text)
        )
        member_start, member_end = _trim_bounds(raw_text, member_start, member_end)
        if member_start >= member_end:
            scope_ok = False
            reason = "an explicitly numbered member has no source text"
            continue
        member_spans.append((marker.start(), marker.end()))
        children.append(
            _parse_expression(
                raw_text,
                start=member_start,
                end=member_end,
                depth=1,
            )
            or _atom_ast(raw_text, member_start, member_end)
        )
    if len(markers) > selected_count:
        next_marker = markers[selected_count]
        boundary_spans = [(next_marker.start(), next_marker.end())]
    elif info.get("count_span"):
        boundary_spans = [info["count_span"]]
    else:
        terminal = _terminal_span(raw_text, 0, len(raw_text))
        boundary_spans = [terminal] if terminal else []
    if not boundary_spans:
        scope_ok = False
        reason = reason or "inline group has no separately evidenced boundary"
    scope_spans = [info["scope_span"], *member_spans]
    ast = {
        "op": info["op"],
        "start": body_start,
        "end": len(raw_text),
        "text": raw_text[body_start:].strip(),
        "children": children,
        "operator_spans": [] if info["unary"] else [info["operator_span"]],
        "requirement_spans": [info["operator_span"]] if info["unary"] else [],
        "operator_basis": "unary_required_normalization" if info["unary"] else None,
        "scope_spans": scope_spans,
        "boundary_spans": boundary_spans,
        "scope_ok": scope_ok,
        "scope_reason": reason,
    }
    if len(markers) > selected_count:
        independent_asts: list[dict[str, Any]] = []
        for index in range(selected_count, len(markers)):
            marker = markers[index]
            item_start = marker.end()
            item_end = (
                markers[index + 1].start()
                if index + 1 < len(markers)
                else len(raw_text)
            )
            item_start, item_end = _trim_bounds(raw_text, item_start, item_end)
            if item_start < item_end:
                independent_asts.append(
                    _parse_expression(
                        raw_text,
                        start=item_start,
                        end=item_end,
                        depth=1,
                    )
                    or _atom_ast(raw_text, item_start, item_end)
                )
        ast["independent_asts"] = independent_asts
    return ast


def _parse_inline_unary_group(
    record: dict[str, Any],
) -> dict[str, Any] | None:
    raw_text = record["raw_text"]
    info = _detect_frame(raw_text)
    if info is None or not info["unary"] or _PAREN_ITEM_RE.search(raw_text):
        return None
    separator = re.search(r"[：:]\s*", raw_text[info["scope_span"][1] :])
    if separator is None:
        return None
    child_start = info["scope_span"][1] + separator.end()
    child_start, child_end = _trim_bounds(raw_text, child_start, len(raw_text))
    if child_start >= child_end:
        return None
    terminal = _terminal_span(raw_text, child_start, child_end)
    if not terminal:
        return {
            "op": "AND",
            "start": 0,
            "end": len(raw_text),
            "text": raw_text.strip(),
            "children": [
                _parse_expression(
                    raw_text,
                    start=child_start,
                    end=child_end,
                    depth=1,
                )
                or _atom_ast(raw_text, child_start, child_end)
            ],
            "operator_spans": [],
            "requirement_spans": [info["operator_span"]],
            "operator_basis": "unary_required_normalization",
            "scope_spans": [info["scope_span"]],
            "boundary_spans": [],
            "scope_ok": False,
            "scope_reason": "unary mandatory scope has no explicit terminal boundary",
        }
    return {
        "op": "AND",
        "start": 0,
        "end": len(raw_text),
        "text": raw_text.strip(),
        "children": [
            _parse_expression(
                raw_text,
                start=child_start,
                end=child_end,
                depth=1,
            )
            or _atom_ast(raw_text, child_start, child_end)
        ],
        "operator_spans": [],
        "requirement_spans": [info["operator_span"]],
        "operator_basis": "unary_required_normalization",
        "scope_spans": [info["scope_span"]],
        "boundary_spans": [terminal],
        "scope_ok": info["scope_ok"],
        "scope_reason": info["scope_reason"],
    }


def _parse_inline_delimited_group(
    record: dict[str, Any],
) -> dict[str, Any] | None:
    text = record["raw_text"]
    info = _detect_frame(text)
    if info is None or not _COLON_RE.search(text):
        return None
    colon = _COLON_RE.search(text, info["operator_span"][1])
    if colon is None:
        return None
    terminal = _terminal_span(text, colon.end(), len(text))
    body_end = terminal[0] if terminal else len(text)
    separators = list(re.finditer(r"[；;]", text[colon.end() : body_end]))
    spans: list[tuple[int, int]] = []
    cursor = colon.end()
    for separator in separators:
        split = colon.end() + separator.start()
        spans.append(_trim_bounds(text, cursor, split))
        cursor = colon.end() + separator.end()
    spans.append(_trim_bounds(text, cursor, body_end))
    spans = [(start, end) for start, end in spans if start < end]
    if len(spans) < 2:
        return None

    count = info["count"]
    scope_ok = info["scope_ok"] and (count is None or count == len(spans))
    reason = info["scope_reason"] if not info["scope_ok"] else None
    if count is not None and count != len(spans):
        scope_ok = False
        reason = "explicit list quantity does not match visible members"
    if terminal is None:
        scope_ok = False
        reason = reason or "inline delimited group has no terminal boundary"
    children = [
        _parse_expression(text, start=start, end=end, depth=1)
        or _atom_ast(text, start, end)
        for start, end in spans
    ]
    if any(child["op"] not in {"ATOM", "AND", "OR"} for child in children):
        scope_ok = False
        reason = "inline delimited member could not be parsed"
    return {
        "op": info["op"],
        "start": 0,
        "end": len(text),
        "text": text.strip(),
        "children": children,
        "operator_spans": [info["operator_span"]],
        "scope_spans": [info["scope_span"], *spans],
        "boundary_spans": [
            *((colon.start(), colon.end()),),
            *[
                (colon.end() + item.start(), colon.end() + item.end())
                for item in separators
            ],
            *([terminal] if terminal else []),
            *([info["count_span"]] if info.get("count_span") else []),
        ],
        "scope_ok": scope_ok,
        "scope_reason": reason,
    }


def _parse_expression(
    text: str,
    *,
    start: int,
    end: int,
    depth: int,
) -> dict[str, Any] | None:
    start, end = _trim_bounds(text, start, end)
    if start >= end:
        return None
    if depth > 3:
        return _atom_ast(text, start, end, "nested condition depth exceeds limit")

    outer = _enclosing_parentheses(text, start, end)
    if outer is not None:
        inner_start, inner_end = outer
        nested = _parse_expression(
            text,
            start=inner_start,
            end=inner_end,
            depth=depth + 1,
        )
        if nested is not None and nested["op"] != "ATOM":
            nested["scope_spans"] = [
                *nested.get("scope_spans", []),
                (start, start + 1),
                (end - 1, end),
            ]
            nested["boundary_spans"] = [
                *nested.get("boundary_spans", []),
                (end - 1, end),
            ]
            nested["scope_ok"] = True
            nested["scope_reason"] = "balanced parentheses bound the expression"
            nested["start"] = start
            nested["end"] = end
            nested["text"] = text[start:end]
            return nested
        if nested is not None:
            return nested

    if _NEGATION_RE.search(text[start:end]):
        return _atom_ast(
            text,
            start,
            end,
            "unsupported NOT or negative condition",
        )

    connectors = _top_level_connectors(text, start, end)
    if connectors:
        operators = {item[0] for item in connectors}
        if len(operators) != 1:
            return _atom_ast(
                text,
                start,
                end,
                "mixed operators require explicit parenthesized nesting",
            )
        op = next(iter(operators))
        operand_spans: list[tuple[int, int]] = []
        cursor = start
        for _operator, op_start, op_end in connectors:
            operand_spans.append((cursor, op_start))
            cursor = op_end
        operand_spans.append((cursor, end))
        cue_matches = [
            match
            for pattern in (_UNARY_CUE_RE, _AND_CUE_RE)
            if (match := pattern.search(text, start, operand_spans[0][1]))
        ]
        if cue_matches:
            cue = min(cue_matches, key=lambda match: match.end())
            first_start, first_end = operand_spans[0]
            cue_end = cue.end()
            while cue_end < first_end and (
                text[cue_end].isspace() or text[cue_end] in "：:,，"
            ):
                cue_end += 1
            operand_spans[0] = (
                _trim_bounds(text, cue_end, first_end)[0],
                first_end,
            )
        terminal = _terminal_span(text, start, end)
        if terminal:
            last_start, last_end = operand_spans[-1]
            operand_spans[-1] = (last_start, min(last_end, terminal[0]))
        operand_spans = [
            _trim_bounds(text, part_start, part_end)
            for part_start, part_end in operand_spans
        ]
        children = [
            _parse_expression(
                text,
                start=part_start,
                end=part_end,
                depth=depth + 1,
            )
            for part_start, part_end in operand_spans
        ]
        children = [child for child in children if child is not None]
        closing = (end - 1, end) if text[end - 1] in "）)" else None
        boundary_spans = [item for item in [terminal, closing] if item]
        scope_ok = len(children) >= 2 and bool(boundary_spans)
        cue_spans = [
            (match.start(), match.end())
            for pattern in (_AND_CUE_RE,)
            for match in pattern.finditer(text, start, end)
            if op == "AND"
        ]
        cue_spans.extend(
            (match.start(), match.end())
            for match in _OR_CUE_RE.finditer(text, start, end)
            if op == "OR"
        )
        operator_cue_spans = [
            (match.start(), match.end())
            for match in _AND_CUE_RE.finditer(text, start, end)
            if op == "AND"
        ]
        requirement_spans = [
            (match.start(), match.end())
            for match in _UNARY_CUE_RE.finditer(
                text,
                start,
                operand_spans[0][1] if operand_spans else end,
            )
            if not any(
                match.start() < cue_end and match.end() > cue_start
                for cue_start, cue_end in operator_cue_spans
            )
        ]
        scope_start = operand_spans[0][0] if operand_spans else start
        scope_end = operand_spans[-1][1] if operand_spans else end
        scope_spans = [(scope_start, scope_end)]
        operator_connector_spans = [
            (op_start, op_end)
            for _operator, op_start, op_end in connectors
            if text[op_start:op_end] != "、"
        ]
        return {
            "op": op,
            "start": start,
            "end": end,
            "text": text[start:end],
            "children": children,
            "operator_spans": [*operator_connector_spans, *cue_spans],
            "scope_spans": scope_spans,
            "requirement_spans": requirement_spans,
            "boundary_spans": boundary_spans,
            "scope_ok": scope_ok,
            "scope_reason": (
                None
                if scope_ok
                else "inline expression lacks a distinct terminal boundary"
            ),
        }

    candidate_reason = None
    atom_text = text[start:end]
    if _NEGATION_RE.search(atom_text):
        candidate_reason = "unsupported NOT or negative condition"
    elif _LOGIC_RE.search(atom_text):
        candidate_reason = "explicit operator could not be parsed safely"
    return _atom_ast(text, start, end, candidate_reason)


def _atom_ast(
    text: str,
    start: int,
    end: int,
    candidate_reason: str | None = None,
) -> dict[str, Any]:
    start, end = _trim_bounds(text, start, end)
    return {
        "op": "ATOM",
        "start": start,
        "end": end,
        "text": text[start:end],
        "children": [],
        "candidate_reason": candidate_reason,
    }


def _opaque_clause_reason(text: str) -> str | None:
    if _K_OF_N_RE.search(text):
        return "K-of-N selection directive is outside the supported grammar"
    if (
        _GROUP_DIRECTIVE_RE.search(text)
        and _GROUP_SELECTION_RE.search(text)
    ):
        return "nested group selection directive requires manual review"
    if _NUMBERING_META_RE.search(text):
        return "numbering explanation is metadata, not a material condition"
    return None


def _detect_frame(text: str) -> dict[str, Any] | None:
    if _NEGATION_RE.search(text):
        return None
    and_matches = list(_AND_CUE_RE.finditer(text))
    or_matches = list(_OR_CUE_RE.finditer(text))
    unary_matches = list(_UNARY_CUE_RE.finditer(text))
    if and_matches and or_matches:
        return None
    unary = False
    if and_matches or or_matches:
        op = "AND" if and_matches else "OR"
        match = (and_matches or or_matches)[0]
    elif unary_matches and _SCOPE_RE.search(text) and (
        re.search(r"(?:以下|下列)|[:：]", text) or _NAMED_GROUP_RE.search(text)
    ):
        op = "AND"
        match = unary_matches[0]
        unary = True
    else:
        return None
    count_match = _COUNT_RE.search(text) or _COUNT_IN_RE.search(text)
    count = _parse_count(count_match.group("count")) if count_match else None
    count_ambiguous = bool(_AMBIGUOUS_COUNT_RE.search(text)) or bool(
        count_match and count is None
    )
    count_ambiguous = count_ambiguous or (op == "OR" and count == 1)
    scope_match = _SCOPE_RE.search(text)
    scope_span = (
        (scope_match.start(), scope_match.end())
        if scope_match
        else (match.start(), match.end())
    )
    count_span = (
        (count_match.start("count"), count_match.end("count"))
        if count_match and count is not None
        else None
    )
    return {
        "op": op,
        "operator_span": (match.start(), match.end()),
        "scope_span": scope_span,
        "count": count,
        "count_span": count_span,
        "unary": unary,
        "scope_ok": bool(scope_match) and not count_ambiguous,
        "scope_reason": None
        if scope_match and not count_ambiguous
        else "explicit quantity is complex or ambiguous"
        if scope_match
        else "explicit scope phrase is missing",
        "count_ambiguous": count_ambiguous,
    }


def _detect_backward_frame(text: str) -> dict[str, Any] | None:
    scope_match = _BACKWARD_SCOPE_RE.search(text)
    and_matches = list(_AND_CUE_RE.finditer(text))
    or_matches = list(_OR_CUE_RE.finditer(text))
    if scope_match is None or bool(and_matches) == bool(or_matches):
        return None
    operator_match = (and_matches or or_matches)[0]
    count_value = scope_match.group("count")
    count = _parse_count(count_value) if count_value else None
    count_ambiguous = bool(count_value and count is None) or bool(
        _AMBIGUOUS_COUNT_RE.search(text)
    )
    count_ambiguous = count_ambiguous or (bool(or_matches) and count == 1)
    terminal = _terminal_span(text, 0, len(text))
    scope_span = (scope_match.start(), scope_match.end())
    count_span = (
        (scope_match.start("count"), scope_match.end("count"))
        if count is not None
        else None
    )
    scope_ok = bool(count and terminal) and not count_ambiguous
    return {
        "op": "AND" if and_matches else "OR",
        "operator_span": (operator_match.start(), operator_match.end()),
        "scope_span": scope_span,
        "count": count,
        "count_span": count_span,
        "unary": False,
        "backward": True,
        "scope_ok": scope_ok,
        "scope_reason": None
        if scope_ok
        else "backward quantity is complex or ambiguous"
        if count_ambiguous
        else "backward reference count or sentence boundary is ambiguous",
    }


def _scan_scoped_items(
    records: list[dict[str, Any]],
    frame_index: int,
    frame_info: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any] | None,
    tuple[int, int] | None,
    str | None,
]:
    members: list[dict[str, Any]] = []
    boundary_record: dict[str, Any] | None = None
    boundary_span: tuple[int, int] | None = None
    reason: str | None = None
    count = frame_info["count"]
    previous_item: dict[str, Any] | None = None
    cursor = frame_index + 1

    while cursor < len(records):
        record = records[cursor]
        if record["kind"] == "page_boundary":
            next_cursor = cursor + 1
            while (
                next_cursor < len(records) and records[next_cursor]["kind"] == "blank"
            ):
                next_cursor += 1
            if next_cursor >= len(records):
                reason = "page boundary has no explicitly sourced continuation"
                break
            continuation = records[next_cursor]
            if (
                _CONTINUATION_RE.fullmatch(continuation["raw_text"])
                and continuation["source_valid"]
            ):
                continuation_records = frame_info.setdefault("continuation_records", [])
                if all(
                    item["index"] != continuation["index"]
                    for item in continuation_records
                ):
                    continuation_records.append(continuation)
                cursor = next_cursor + 1
                continue
            boundary_record = continuation
            boundary_span = _whole_block_span(continuation)
            reason = "cross-page members lack an explicit continuation statement"
            break
        if record["kind"] == "blank":
            cursor += 1
            continue
        if record["kind"] == "heading":
            boundary_record = record
            boundary_span = _whole_block_span(record)
            current_group = _NAMED_GROUP_RE.search(records[frame_index]["raw_text"])
            next_group = _NAMED_GROUP_RE.search(record["raw_text"])
            if (
                current_group
                and next_group
                and current_group.group("label") != next_group.group("label")
            ):
                boundary_span = (next_group.start(), next_group.end())
                frame_info.setdefault("additional_boundary_records", []).append(
                    record
                )
                break
            if count is not None and len(members) < count:
                reason = "a heading starts before the explicit member count is met"
            elif count is None and members:
                closure = _SCOPE_END_RE.search(record["raw_text"])
                if closure and record["source_valid"]:
                    boundary_span = (closure.start(), closure.end())
                else:
                    boundary_record = None
                    boundary_span = None
                    reason = "heading alone does not explicitly close the scope"
            break

        item = _numbered_prefix(record["raw_text"])
        if item is None:
            if (
                frame_info.get("unary")
                and not members
                and record["kind"] in _CONDITION_KINDS
                and record["source_valid"]
                and _REQUIREMENT_PREDICATE_RE.search(record["raw_text"])
            ):
                members.append(
                    {
                        "record": record,
                        "body_start": 0,
                        "body_end": len(record["raw_text"]),
                        "marker_span": None,
                        "item": None,
                    }
                )
                terminal = _terminal_span(
                    record["raw_text"],
                    0,
                    len(record["raw_text"]),
                )
                boundary_record = record
                boundary_span = terminal
                break
            if (
                members
                and _CONTINUED_AND_RE.match(record["raw_text"])
                and _REQUIREMENT_PREDICATE_RE.search(record["raw_text"])
            ):
                members.append(
                    {
                        "record": record,
                        "body_start": 0,
                        "body_end": len(record["raw_text"]),
                        "marker_span": None,
                        "item": None,
                    }
                )
                terminal = _terminal_span(
                    record["raw_text"],
                    0,
                    len(record["raw_text"]),
                )
                boundary_record = record
                boundary_span = terminal
                break
            if (
                count is None
                and frame_info["op"] == "OR"
                and len(members) >= 2
                and members[-1]["item"]["style"] == "alpha"
                and frame_info["scope_ok"]
                and record["source_valid"]
            ):
                final_member = members[-1]
                terminal = _terminal_span(
                    final_member["record"]["raw_text"],
                    final_member["body_start"],
                    final_member["body_end"],
                )
                if terminal is not None:
                    frame_info["terminal_boundary"] = {
                        "record": final_member["record"],
                        "span": terminal,
                    }
                    frame_info["following_nonlist_record"] = record
                    boundary_record = record
                    boundary_span = _whole_block_span(record)
                    break
            boundary_record = record
            boundary_span = _whole_block_span(record)
            if count is not None and len(members) < count:
                reason = "a non-list block interrupts the explicit member count"
            elif count is None and members:
                closure = _SCOPE_END_RE.search(record["raw_text"])
                if closure and record["source_valid"]:
                    boundary_span = (closure.start(), closure.end())
                else:
                    boundary_record = None
                    boundary_span = None
                    reason = "non-list text does not explicitly close the scope"
            break
        if not members:
            if item["number"] != 1:
                reason = "numbered scope does not begin with member 1"
                boundary_record = record
                boundary_span = (0, item["end"])
                break
            members.append(
                {
                    "record": record,
                    "body_start": item["end"],
                    "body_end": len(record["raw_text"]),
                    "marker_span": (0, item["end"]),
                    "item": item,
                }
            )
            previous_item = item
            cursor += 1
            if count is not None and len(members) >= count:
                break
            continue

        if not _same_numbered_sequence(previous_item, item):
            boundary_record = record
            boundary_span = (0, item["end"])
            if count is not None and len(members) < count:
                reason = "numbered members are missing, repeated, or ambiguous"
            elif count is None and _same_numbering_family(previous_item, item):
                reason = "numbered scope has a gap or duplicate member"
            break

        members.append(
            {
                "record": record,
                "body_start": item["end"],
                "body_end": len(record["raw_text"]),
                "marker_span": (0, item["end"]),
                "item": item,
            }
        )
        previous_item = item
        cursor += 1
        if count is not None and len(members) >= count:
            break

    if count is not None:
        if len(members) != count:
            reason = reason or "explicit member count is incomplete"
        elif not frame_info["scope_ok"]:
            reason = frame_info["scope_reason"]
        else:
            next_cursor = cursor
            while next_cursor < len(records) and records[next_cursor]["kind"] in {
                "page_boundary",
                "blank",
            }:
                next_cursor += 1
            if next_cursor < len(records):
                next_item = _numbered_prefix(records[next_cursor]["raw_text"])
                last_item = members[-1]["item"]
                if next_item and _same_numbering_family(last_item, next_item):
                    if _is_next_numbered_item(last_item, next_item):
                        boundary_record = records[next_cursor]
                        boundary_span = (0, next_item["end"])
                    else:
                        reason = (
                            "numbered item after the explicit count has a gap "
                            "or duplicate number"
                        )
            if not boundary_span and frame_info.get("count_span"):
                boundary_record = records[frame_index]
                boundary_span = frame_info["count_span"]
        return members, boundary_record, boundary_span, reason

    minimum_members = 1 if frame_info.get("unary") else 2
    if len(members) < minimum_members:
        reason = reason or "explicit scope has fewer than two numbered members"
    elif boundary_record is None:
        final_record = members[-1]["record"]
        terminal = _terminal_span(
            final_record["raw_text"],
            members[-1]["body_start"],
            members[-1]["body_end"],
        )
        if terminal:
            boundary_record = final_record
            boundary_span = terminal
        else:
            reason = reason or "numbered scope reaches end of source without a boundary"
    elif not frame_info["scope_ok"]:
        reason = frame_info["scope_reason"]
    elif reason is None:
        final_record = members[-1]["record"]
        terminal = _terminal_span(
            final_record["raw_text"],
            members[-1]["body_start"],
            members[-1]["body_end"],
        )
        if terminal:
            if frame_info.get("following_nonlist_record") is None:
                boundary_record = final_record
                boundary_span = terminal
        else:
            reason = "explicit terminal boundary is missing from the final member"
    return members, boundary_record, boundary_span, reason


def _scan_backward_items(
    records: list[dict[str, Any]],
    frame_index: int,
    frame_info: dict[str, Any],
) -> tuple[
    list[dict[str, Any]],
    dict[str, Any] | None,
    tuple[int, int] | None,
    str | None,
]:
    count = frame_info["count"]
    frame_record = records[frame_index]
    terminal = _terminal_span(
        frame_record["raw_text"], 0, len(frame_record["raw_text"])
    )
    if count is None or (frame_info["op"] == "OR" and count < 2):
        return [], frame_record, terminal, "backward reference lacks a safe item count"

    reverse_members: list[dict[str, Any]] = []
    cursor = frame_index - 1
    reason: str | None = None
    while cursor >= 0 and len(reverse_members) < count:
        record = records[cursor]
        if record["kind"] == "blank":
            cursor -= 1
            continue
        if record["kind"] == "page_boundary":
            following = cursor + 1
            while following < frame_index and records[following]["kind"] == "blank":
                following += 1
            if (
                following < frame_index
                and _CONTINUATION_RE.fullmatch(records[following]["raw_text"])
                and records[following]["source_valid"]
            ):
                continuation_records = frame_info.setdefault("continuation_records", [])
                if all(
                    item["index"] != records[following]["index"]
                    for item in continuation_records
                ):
                    continuation_records.append(records[following])
                cursor -= 1
                continue
            reason = "cross-page antecedents lack an explicit continuation statement"
            break
        if _CONTINUATION_RE.fullmatch(record["raw_text"]):
            if record["source_valid"]:
                continuation_records = frame_info.setdefault("continuation_records", [])
                if all(
                    item["index"] != record["index"] for item in continuation_records
                ):
                    continuation_records.append(record)
                cursor -= 1
                continue
            reason = "continuation statement source is unverified"
            break
        if record["kind"] == "heading":
            reason = "a heading interrupts the backward reference scope"
            break
        item = _numbered_prefix(record["raw_text"])
        if item is None:
            reason = "a non-list block interrupts the backward reference scope"
            break
        reverse_members.append(
            {
                "record": record,
                "body_start": item["end"],
                "body_end": len(record["raw_text"]),
                "marker_span": (0, item["end"]),
                "item": item,
            }
        )
        cursor -= 1

    members = list(reversed(reverse_members))
    if reason is None and len(members) != count:
        reason = "backward reference count is not present in the source"
    if reason is None and any(
        not _same_numbered_sequence(first["item"], second["item"])
        for first, second in zip(members, members[1:])
    ):
        reason = "backward reference members have missing or duplicate numbers"
    if reason is None and any(
        not member["record"]["source_valid"] for member in members
    ):
        reason = "backward reference member source is unverified"
    if reason is None and not frame_info["scope_ok"]:
        reason = frame_info["scope_reason"]
    return members, frame_record, terminal, reason


def _backward_candidates(
    records: list[dict[str, Any]],
    frame_index: int,
    members: list[dict[str, Any]],
    scan_reason: str | None,
) -> list[dict[str, Any]]:
    if scan_reason is None:
        return [member["record"] for member in members]
    candidates = {member["record"]["index"]: member["record"] for member in members}
    candidates.update(
        {
            record["index"]: record
            for record in _possible_antecedents(records, frame_index)
        }
    )
    return [candidates[index] for index in sorted(candidates)]


def _has_adjacent_frame(
    records: list[dict[str, Any]],
    frame_index: int,
    frame_indices: list[int],
) -> bool:
    previous = frame_index - 1
    while previous >= 0 and records[previous]["kind"] in {
        "blank",
        "page_boundary",
    }:
        previous -= 1
    return previous in frame_indices


def _numbered_prefix(text: str) -> dict[str, Any] | None:
    chinese = re.match(
        r"^\s*(?P<label>[一二三四五六七八九十]+)[、.．]\s*",
        text,
    )
    if chinese:
        label = chinese.group("label")
        number = _simple_number(label)
        if number is None:
            return None
        return {
            "style": "chinese",
            "label": label,
            "number": number,
            "path": (number,),
            "end": chinese.end(),
        }

    paren = re.match(rf"^\s*[（(]\s*(?P<label>{_NUMBER_TOKEN})\s*[）)]", text)
    if paren:
        label = paren.group("label")
        number = _simple_number(label)
        if number is None:
            return None
        return {
            "style": "paren_decimal"
            if label.isascii() and label.isdigit()
            else "paren_chinese",
            "label": label,
            "number": number,
            "path": (number,),
            "end": paren.end(),
        }

    alpha = _ALPHA_ITEM_RE.match(text)
    if alpha:
        label = alpha.group("label").upper()
        number = ord(label) - ord("A") + 1
        return {
            "style": "alpha",
            "label": label,
            "number": number,
            "path": (number,),
            "end": alpha.end(),
        }

    match = re.match(r"^\s*(?P<core>\d+(?:[.．]\d+)*)(?P<tail>.*)$", text)
    if not match:
        return None
    core = match.group("core").replace("．", ".")
    parts = core.split(".")
    tail = match.group("tail")
    if parts[-1].isdigit() and len(parts[-1]) > 1:
        return None
    punct = re.match(r"[、.．)）]\s*", tail)
    if punct:
        end = match.start("tail") + punct.end()
    elif tail[:1].isspace() and len(parts[-1]) == 1:
        end = match.start("tail") + len(tail) - len(tail.lstrip())
    elif (
        len(parts) > 1
        and len(parts[-1]) == 1
        and tail
        and not re.match(r"(?:表|图|附件|年|月|日|元|万元|%|％)", tail)
    ):
        end = match.start("tail")
    else:
        return None
    path = tuple(int(part) for part in parts)
    return {
        "style": "decimal",
        "label": core,
        "number": path[-1],
        "path": path,
        "end": end,
    }


def _numbered_title_evidence_span(
    text: str,
    prefix: Mapping[str, Any],
) -> tuple[int, int] | None:
    colon = _COLON_RE.search(text, int(prefix["end"]))
    if colon is None or colon.start() <= int(prefix["end"]):
        return None
    title_start = int(prefix["end"])
    if _REQUIREMENT_PREDICATE_RE.search(text, title_start, colon.start()):
        return None
    if _LOGIC_RE.search(text, title_start, colon.start()):
        return None
    if not _top_level_connectors(text, colon.end(), len(text)):
        return None
    return (0, colon.end())


def _same_numbering_family(first: dict[str, Any], second: dict[str, Any]) -> bool:
    return (
        first["style"] == second["style"] and first["path"][:-1] == second["path"][:-1]
    )


def _same_numbered_sequence(first: dict[str, Any], second: dict[str, Any]) -> bool:
    return (
        _same_numbering_family(first, second)
        and second["number"] == first["number"] + 1
    )


def _is_first_nested_item(
    parent: dict[str, Any],
    candidate: dict[str, Any],
) -> bool:
    return (
        parent["style"] == "decimal"
        and candidate["style"] == "decimal"
        and len(candidate["path"]) == len(parent["path"]) + 1
        and candidate["path"][:-1] == parent["path"]
        and candidate["path"][-1] == 1
    )


def _is_next_top_level_item(
    current: dict[str, Any],
    candidate: dict[str, Any],
) -> bool:
    return (
        len(current["path"]) == len(candidate["path"]) == 1
        and _same_numbered_sequence(current, candidate)
    )


def _is_next_numbered_item(first: dict[str, Any], second: dict[str, Any]) -> bool:
    return _same_numbered_sequence(first, second)


def _parse_count(value: str) -> int | None:
    if value.isascii() and value.isdigit():
        if len(value) > 2 or (len(value) > 1 and value.startswith("0")):
            return None
        number = int(value)
        return number if 1 <= number <= 20 else None
    chinese = {
        "一": 1,
        "二": 2,
        "两": 2,
        "三": 3,
        "四": 4,
        "五": 5,
        "六": 6,
        "七": 7,
        "八": 8,
        "九": 9,
        "十": 10,
    }
    return chinese.get(value)


def _simple_number(value: str) -> int | None:
    if value.isascii() and value.isdigit():
        return int(value) if len(value) <= 2 else None
    return _parse_count(value)


def _top_level_connectors(
    text: str,
    start: int,
    end: int,
) -> list[tuple[str, int, int]]:
    tokens = [
        ("AND", "并且"),
        ("OR", "或者"),
        ("AND", "且"),
        ("OR", "或"),
    ]
    segment = text[start:end]
    has_explicit_and_cue = bool(
        _AND_CUE_RE.search(segment) or _UNARY_CUE_RE.search(segment)
    )
    for match in re.finditer("并", segment):
        left = segment[: match.start()]
        right = segment[match.end() :]
        if (
            _REQUIREMENT_PREDICATE_RE.search(left)
            and _REQUIREMENT_PREDICATE_RE.search(right)
        ):
            tokens.append(("AND", "并"))
            break
    if has_explicit_and_cue:
        tokens.extend(
            [
                ("AND", "以及"),
                ("AND", "及"),
                ("AND", "和"),
                ("AND", "与"),
                ("AND", "、"),
            ]
        )
    result: list[tuple[str, int, int]] = []
    stack: list[str] = []
    index = start
    while index < end:
        char = text[index]
        if char in "（(":
            stack.append("）" if char == "（" else ")")
            index += 1
            continue
        if stack and char == stack[-1]:
            stack.pop()
            index += 1
            continue
        if stack:
            index += 1
            continue
        found = next(
            ((op, token) for op, token in tokens if text.startswith(token, index, end)),
            None,
        )
        if found:
            op, token = found
            result.append((op, index, index + len(token)))
            index += len(token)
        else:
            index += 1
    return result


def _enclosing_parentheses(
    text: str,
    start: int,
    end: int,
) -> tuple[int, int] | None:
    if text[start] not in "（(" or text[end - 1] not in "）)":
        return None
    expected = "）" if text[start] == "（" else ")"
    stack: list[str] = []
    for index in range(start, end):
        char = text[index]
        if char in "（(":
            stack.append("）" if char == "（" else ")")
        elif stack and char == stack[-1]:
            stack.pop()
            if not stack and index != end - 1:
                return None
    return (start + 1, end - 1) if not stack and text[end - 1] == expected else None


def _terminal_span(
    text: str,
    start: int,
    end: int,
) -> tuple[int, int] | None:
    trimmed_end = end
    while trimmed_end > start and text[trimmed_end - 1].isspace():
        trimmed_end -= 1
    if trimmed_end > start and text[trimmed_end - 1] in "。；;！？!?":
        return trimmed_end - 1, trimmed_end
    return None


def _trim_bounds(text: str, start: int, end: int) -> tuple[int, int]:
    while start < end and text[start].isspace():
        start += 1
    while end > start and text[end - 1].isspace():
        end -= 1
    return start, end


def _index_pages(
    pages_value: Any,
) -> tuple[dict[int, str], set[int]]:
    if not isinstance(pages_value, list):
        return {}, set()
    pages: dict[int, str] = {}
    invalid: set[int] = set()
    seen: set[int] = set()
    for page in pages_value:
        if not isinstance(page, Mapping):
            continue
        number = page.get("page_number")
        if isinstance(number, bool) or not isinstance(number, int) or number <= 0:
            continue
        if number in seen:
            invalid.add(number)
            pages.pop(number, None)
            continue
        seen.add(number)
        raw_text = page.get("raw_text")
        if (
            not isinstance(raw_text, str)
            or _mapping_coordinates_unverified(page)
        ):
            invalid.add(number)
            continue
        pages[number] = raw_text
    return pages, invalid


def _validate_block_source(
    structure: Mapping[str, Any],
    block: Mapping[str, Any],
    pages: Mapping[int, str],
    invalid_pages: set[int],
    *,
    document_id: str | None,
    source_version: str | None,
    identity_valid: bool,
    schema_valid: bool,
) -> tuple[bool, list[dict[str, Any]], str]:
    if not identity_valid or not schema_valid:
        return False, [], "document identity or source schema is unverified"
    if _coordinates_unverified(structure, block):
        return False, [], "source coordinates are not verified"
    references = block.get("source_references")
    if not isinstance(references, list) or not references:
        return False, [], "block has no source reference"
    if len(references) != 1 or not isinstance(references[0], Mapping):
        return False, [], "block source references are duplicate or ambiguous"
    reference = references[0]
    page = reference.get("page")
    start = reference.get("char_start")
    end = reference.get("char_end")
    quote = reference.get("quote")
    span = block.get("source_span")
    raw_text = block.get("raw_text")
    if (
        not isinstance(page, int)
        or isinstance(page, bool)
        or page <= 0
        or not isinstance(start, int)
        or isinstance(start, bool)
        or not isinstance(end, int)
        or isinstance(end, bool)
        or end < start
        or not isinstance(quote, str)
        or not isinstance(raw_text, str)
        or not isinstance(span, Mapping)
        or not isinstance(span.get("start"), int)
        or isinstance(span.get("start"), bool)
        or not isinstance(span.get("end"), int)
        or isinstance(span.get("end"), bool)
        or not isinstance(span.get("page_number"), int)
        or isinstance(span.get("page_number"), bool)
        or not isinstance(block.get("page_number"), int)
        or isinstance(block.get("page_number"), bool)
    ):
        return False, [], "source reference lacks exact page coordinates or quote"
    if page in invalid_pages:
        return False, [], "source page is missing or duplicated"
    if page not in pages:
        return False, [], "source page is missing"
    if (
        reference.get("document_id") != document_id
        or reference.get("source_version") != source_version
    ):
        return False, [], "source reference document or version conflicts"
    expected_locator = f"p{page}:c{start}-{end}"
    if (
        span.get("page_number") != page
        or span.get("start") != start
        or span.get("end") != end
        or block.get("page_number") != page
        or reference.get("locator") != expected_locator
        or not _valid_line_number(block, reference, pages[page], start)
        or not 0 <= start <= end <= len(pages[page])
        or quote != raw_text
        or pages[page][start:end] != quote
    ):
        return False, [], "source quote or character span conflicts with page text"
    cleaned = _clean_reference(reference)
    return True, [cleaned], "source reference is verified"


def _valid_line_number(
    block: Mapping[str, Any],
    reference: Mapping[str, Any],
    page_text: str,
    start: int,
) -> bool:
    line_number = block.get("line_number")
    if (
        not isinstance(line_number, int)
        or isinstance(line_number, bool)
        or line_number <= 0
    ):
        return False
    if "line_number" in reference and reference["line_number"] != line_number:
        return False
    if "line_number" in reference and (
        not isinstance(reference["line_number"], int)
        or isinstance(reference["line_number"], bool)
    ):
        return False
    physical_line = len(re.findall(r"\r\n|\r|\n|\f", page_text[:start])) + 1
    return line_number == physical_line


def _coordinates_unverified(
    structure: Mapping[str, Any],
    block: Mapping[str, Any],
) -> bool:
    return _mapping_coordinates_unverified(
        structure
    ) or _mapping_coordinates_unverified(block)


def _mapping_coordinates_unverified(value: Mapping[str, Any]) -> bool:
    for key, field_value in value.items():
        if key == "metadata" and isinstance(field_value, Mapping):
            if _mapping_coordinates_unverified(field_value):
                return True
            continue
        normalized_key = str(key).lower()
        if not any(token in normalized_key for token in ("coordinate", "scope")):
            continue
        if _coordinate_value_is_unverified(field_value):
            return True
    return False


def _coordinate_value_is_unverified(value: Any) -> bool:
    normalized = str(value or "").strip().lower().replace("-", "_")
    return bool(
        normalized
        and any(marker in normalized for marker in _UNVERIFIED_COORDINATE_MARKERS)
    )


def _clean_reference(reference: Mapping[str, Any]) -> dict[str, Any]:
    keys = (
        "document_id",
        "source_version",
        "page",
        "line_number",
        "locator",
        "char_start",
        "char_end",
        "quote",
    )
    return {key: reference[key] for key in keys if key in reference}


def _refs_for_span(
    record: Mapping[str, Any],
    start: int,
    end: int,
) -> list[dict[str, Any]]:
    return _refs_for_spans(record, [(start, end)])


def _refs_for_spans(
    record: Mapping[str, Any],
    spans: list[tuple[int, int]],
) -> list[dict[str, Any]]:
    if not record["source_valid"]:
        return []
    raw_text = record["raw_text"]
    output: list[dict[str, Any]] = []
    for start, end in spans:
        if start < 0 or end <= start or end > len(raw_text):
            continue
        for base in record["source_references"]:
            clipped = dict(base)
            offset = base["char_start"]
            clipped_start = offset + start
            clipped_end = offset + end
            clipped["char_start"] = clipped_start
            clipped["char_end"] = clipped_end
            clipped["quote"] = raw_text[start:end]
            clipped["locator"] = f"p{base['page']}:c{clipped_start}-{clipped_end}"
            output.append(clipped)
    return _merge_refs(output)


def _merge_refs(*groups: Any) -> list[dict[str, Any]]:
    output: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for group in groups:
        if not isinstance(group, (list, tuple)):
            continue
        for reference in group:
            if not isinstance(reference, Mapping):
                continue
            key = (
                reference.get("document_id"),
                reference.get("source_version"),
                reference.get("page"),
                reference.get("char_start"),
                reference.get("char_end"),
                reference.get("quote"),
            )
            if key not in seen:
                seen.add(key)
                output.append(dict(reference))
    return output


def _whole_block_span(record: Mapping[str, Any]) -> tuple[int, int] | None:
    raw_text = record["raw_text"]
    return (0, len(raw_text)) if raw_text else None


def _parent_relation(
    record: dict[str, Any],
    unique_by_id: Mapping[str, dict[str, Any]],
    id_counts: Mapping[str, int],
    cyclic_ids: set[str],
    *,
    source_identity_valid: bool,
) -> dict[str, Any]:
    parent_id = record["block"].get("parent_block_id")
    status = "unresolved"
    reason = "no legacy parent pointer"
    targets: list[str] = []
    source_references = list(record["source_references"])
    if parent_id is not None:
        if not isinstance(parent_id, str) or not parent_id:
            reason = "legacy parent pointer is invalid"
        elif id_counts.get(parent_id, 0) != 1:
            reason = "legacy parent target is missing, duplicated, or cross-version"
        else:
            targets = [parent_id]
            parent_record = unique_by_id[parent_id]
            source_references = _merge_refs(
                source_references,
                parent_record["source_references"],
            )
            if record["block_id"] in cyclic_ids or parent_id in cyclic_ids:
                reason = "legacy parent chain contains a cycle"
            elif not source_identity_valid:
                reason = "document identity or source version is missing"
            elif not record["source_valid"] or not parent_record["source_valid"]:
                reason = "source coordinates are not verified"
            else:
                status = "candidate"
                reason = "legacy physical parent is only a structural candidate"
    return {
        "status": status,
        "target_block_ids": targets,
        "source_references": source_references,
        "reason": reason,
    }


def _parent_cycle_ids(
    records: list[dict[str, Any]],
    unique_by_id: Mapping[str, dict[str, Any]],
) -> set[str]:
    cycles: set[str] = set()
    for record in records:
        start_id = record["block_id"]
        if not start_id or start_id not in unique_by_id:
            continue
        path: list[str] = []
        positions: dict[str, int] = {}
        current_id = start_id
        while current_id in unique_by_id:
            if current_id in positions:
                cycles.update(path[positions[current_id] :])
                break
            positions[current_id] = len(path)
            path.append(current_id)
            parent_id = unique_by_id[current_id]["block"].get("parent_block_id")
            if not isinstance(parent_id, str):
                break
            current_id = parent_id
    return cycles


def _build_references(
    records: list[dict[str, Any]],
    unique_by_id: Mapping[str, dict[str, Any]],
    id_counts: Mapping[str, int],
    nodes: list[dict[str, Any]],
    roots_by_block: Mapping[int, list[str]],
    *,
    source_identity_valid: bool,
    block_relation_by_index: Mapping[int, dict[str, Any]],
    resolved_anaphora_spans: Mapping[int, list[tuple[int, int]]],
) -> list[dict[str, Any]]:
    labels: dict[str, list[dict[str, Any]]] = {}
    nodes_by_id = {node["node_id"]: node for node in nodes}
    for record in records:
        label = _numbering_label(record)
        if label:
            labels.setdefault(label, []).append(record)
    output: list[dict[str, Any]] = []
    for record in records:
        text = record["raw_text"]
        matches = list(_REFERENCE_RE.finditer(text))
        explicit_spans = [(item.start(), item.end()) for item in matches]
        matches.extend(
            item
            for item in _STANDALONE_REFERENCE_RE.finditer(text)
            if not any(
                start <= item.start() and end >= item.end()
                for start, end in (
                    (match.start(), match.end())
                    for match in _REFERENCE_RE.finditer(text)
                )
            )
        )
        anaphora_matches = [
            item
            for item in _ANAPHORA_RE.finditer(text)
            if not any(
                start <= item.start() and end >= item.end()
                for start, end in [
                    *explicit_spans,
                    *resolved_anaphora_spans.get(record["index"], []),
                ]
            )
        ]
        for match in anaphora_matches:
            candidates = _possible_antecedents(records, record["index"])
            target_nodes = _anaphora_target_nodes(
                match.group(),
                candidates,
                roots_by_block,
                nodes_by_id,
            )
            if match.group() == "营业收入" and not target_nodes:
                continue
            candidate_ids = [
                candidate["block_id"]
                for candidate in candidates
                if candidate["block_id"] and id_counts.get(candidate["block_id"]) == 1
            ]
            target_block_ids = _unique(
                [
                    block_id
                    for node in target_nodes
                    for block_id in node["source_block_ids"]
                    if block_id and id_counts.get(block_id) == 1
                ]
            )
            unique_target = len(target_nodes) == 1 and bool(target_block_ids)
            status = (
                "unresolved"
                if not record["source_valid"]
                else "confirmed"
                if unique_target and target_nodes[0]["source_references"]
                else "candidate"
                if target_nodes or candidate_ids
                else "unresolved"
            )
            expression_refs = _refs_for_span(record, match.start(), match.end())
            context_refs = _refs_for_span(record, 0, len(text))
            reference = {
                "reference_id": _stable_id(
                    "reference",
                    record["block_id"],
                    match.start(),
                    match.end(),
                    match.group(),
                    [],
                ),
                "reference_kind": "anaphora",
                "reference_text": match.group(),
                "source_block_id": record["block_id"],
                "status": status,
                "target_block_ids": target_block_ids or candidate_ids,
                "target_node_ids": [node["node_id"] for node in target_nodes]
                or _unique(
                    [
                        node_id
                        for candidate in candidates
                        for node_id in roots_by_block.get(candidate["index"], [])
                    ]
                ),
                "source_references": _merge_refs(expression_refs, context_refs),
                "expression_source_references": expression_refs,
                "context_source_references": context_refs,
                "candidate_source_references": []
                if status == "confirmed"
                else _merge_refs(
                    *[
                        node["source_references"]
                        for node in target_nodes
                    ],
                    *[candidate["source_references"] for candidate in candidates]
                    if not target_nodes
                    else [],
                ),
                "candidate_target_context_references": [],
                "reason": (
                    "referential expression has one source-verified antecedent"
                    if status == "confirmed"
                    else "referential expression has multiple or unverified possible "
                    "antecedents"
                    if status == "candidate"
                    else "referential expression has no explicit antecedent"
                ),
            }
            output.append(reference)
            block_relation_by_index[record["index"]]["reference_relations"].append(
                dict(reference)
            )
        for match in sorted(matches, key=lambda item: item.start()):
            label = match.group("label").replace("．", ".")
            candidates = labels.get(label, [])
            targets = [
                item for item in candidates if item["block_id"] != record["block_id"]
            ]
            target_ids = [
                item["block_id"]
                for item in targets
                if item["block_id"] and id_counts.get(item["block_id"]) == 1
            ]
            target_nodes = [
                node_id
                for target in targets
                for node_id in roots_by_block.get(target["index"], [])
            ]
            source_refs = _refs_for_span(record, match.start(), match.end())
            if not record["source_valid"] or not source_identity_valid:
                status = "unresolved"
                reason = record["source_reason"]
            elif id_counts.get(record["block_id"], 0) != 1:
                status = "unresolved"
                reason = "source block identifier is duplicated"
            elif not _has_explicit_local_item_namespace(text, match):
                status = "candidate" if target_ids else "unresolved"
                reason = (
                    "number label collides without a verified item namespace"
                    if target_ids
                    else "numbered reference has no target in a verified namespace"
                )
            elif len(targets) == 1 and len(target_ids) == 1:
                target = targets[0]
                if target["source_valid"]:
                    status = "confirmed"
                    reason = "explicit local item reference has one verified target"
                else:
                    status = "unresolved"
                    reason = "unique numbered target has unverified source coordinates"
            elif len(targets) > 1:
                status = "candidate"
                reason = "numbered reference matches multiple possible targets"
            else:
                status = "unresolved"
                reason = "explicit numbered reference has no unique target"
            reference_id = _stable_id(
                "reference",
                record["block_id"],
                match.start(),
                match.end(),
                label,
                target_ids,
            )
            reference = {
                "reference_id": reference_id,
                "reference_kind": "numbered",
                "source_block_id": record["block_id"],
                "status": status,
                "target_block_ids": target_ids,
                "target_node_ids": _unique(target_nodes),
                "source_references": source_refs,
                "candidate_source_references": _merge_refs(
                    *[target["source_references"] for target in targets]
                ),
                "reason": reason,
            }
            output.append(reference)
            block_relation_by_index[record["index"]]["reference_relations"].append(
                dict(reference)
            )
    return output


def _add_candidate_reference_relations(
    records: list[dict[str, Any]],
    references: list[dict[str, Any]],
    block_relations: Mapping[int, dict[str, Any]],
    roots_by_block: Mapping[int, list[str]],
    nodes_by_id: Mapping[str, dict[str, Any]],
) -> None:
    records_by_id = {
        record["block_id"]: record for record in records if record["block_id"]
    }
    for reference in references:
        if (
            reference.get("reference_kind") != "anaphora"
            or reference["status"] == "confirmed"
        ):
            continue
        record = records_by_id.get(reference["source_block_id"])
        if record is None:
            continue

        candidate_nodes = [
            nodes_by_id[node_id]
            for node_id in reference["target_node_ids"]
            if node_id in nodes_by_id
        ]
        candidate_context_refs: list[dict[str, Any]] = []
        for candidate in candidate_nodes:
            candidate_context_refs.extend(candidate.get("source_references", []))
            for parent in candidate.get("parent_relations", []):
                if (
                    parent.get("layer") != "semantic_parent"
                    or parent.get("status") != "confirmed"
                ):
                    continue
                for parent_id in parent.get("target_node_ids", []):
                    parent_node = nodes_by_id.get(parent_id)
                    if (
                        parent_node is None
                        or parent_node.get("op") not in {"AND", "OR"}
                    ):
                        continue
                    parent_scope = parent_node.get("scope_relation", {})
                    candidate_context_refs.extend(
                        parent_scope.get("source_references", [])
                    )
                    candidate_context_refs.extend(
                        parent_scope.get("boundary_source_references", [])
                    )
        candidate_context_refs = _merge_refs(
            reference.get("candidate_source_references", []),
            candidate_context_refs,
        )
        source_refs = _merge_refs(
            reference.get("source_references", []),
            record["source_references"],
            candidate_context_refs,
        )
        reference["candidate_source_references"] = candidate_context_refs
        reference["candidate_target_context_references"] = candidate_context_refs
        reference["source_references"] = source_refs
        block_relation = block_relations[record["index"]]
        for block_reference in block_relation["reference_relations"]:
            if block_reference["reference_id"] == reference["reference_id"]:
                block_reference.update(
                    {
                        "source_references": source_refs,
                        "candidate_source_references": candidate_context_refs,
                        "candidate_target_context_references": (
                            candidate_context_refs
                        ),
                    }
                )
                break

        relation_status = (
            "unresolved"
            if not record["source_valid"] or reference["status"] == "unresolved"
            else "candidate"
        )
        boundary = _terminal_span(record["raw_text"], 0, len(record["raw_text"]))
        boundary_refs = (
            _refs_for_span(record, boundary[0], boundary[1]) if boundary else []
        )
        reason = (
            "anaphoric attribute has multiple or unverified antecedents; "
            "no candidate is bound"
        )
        scope_relation = {
            "relation_id": _stable_id(
                "candidate_anaphoric_scope",
                reference["reference_id"],
                reference["target_node_ids"],
            ),
            "relation_type": "anaphoric_attribute_scope",
            "operator": "UNRESOLVED",
            "status": relation_status,
            "operator_status": "unresolved",
            "scope_status": relation_status,
            "target_block_ids": list(reference["target_block_ids"]),
            "target_node_ids": list(reference["target_node_ids"]),
            "trigger_text": record["raw_text"],
            "source_references": source_refs,
            "candidate_target_source_references": candidate_context_refs,
            "operator_source_references": [],
            "boundary_source_references": boundary_refs,
            "reason": reason,
        }
        block_relation["scope_relations"].append(scope_relation)

        parent_relation = {
            "relation_id": scope_relation["relation_id"],
            "status": relation_status,
            "layer": "semantic_parent",
            "basis": "unresolved_anaphoric_attribute",
            "target_block_ids": list(reference["target_block_ids"]),
            "target_node_ids": list(reference["target_node_ids"]),
            "source_references": source_refs,
            "candidate_target_source_references": candidate_context_refs,
            "reason": reason,
        }
        for node_id in roots_by_block.get(record["index"], []):
            node = nodes_by_id.get(node_id)
            if node is not None and node["op"] == "ATOM":
                node["parent_relations"].append(dict(parent_relation))


def _add_cross_page_candidate_relations(
    records: list[dict[str, Any]],
    block_relations: Mapping[int, dict[str, Any]],
    roots_by_block: Mapping[int, list[str]],
    nodes_by_id: Mapping[str, dict[str, Any]],
) -> None:
    for boundary_index, boundary in enumerate(records):
        if boundary["kind"] != "page_boundary":
            continue
        previous_index = boundary_index - 1
        while previous_index >= 0 and records[previous_index]["kind"] == "blank":
            previous_index -= 1
        next_index = boundary_index + 1
        while next_index < len(records) and records[next_index]["kind"] == "blank":
            next_index += 1
        if previous_index < 0 or next_index >= len(records):
            continue
        previous = records[previous_index]
        following = records[next_index]
        if (
            previous["kind"] not in _CONDITION_KINDS
            or following["kind"] not in _CONDITION_KINDS
            or _CONTINUATION_RE.fullmatch(following["raw_text"])
            or previous["block"].get("page_number")
            == following["block"].get("page_number")
        ):
            continue

        previous_group = next(
            (
                nodes_by_id[node_id]
                for node_id in reversed(roots_by_block.get(previous_index, []))
                if node_id in nodes_by_id
                and nodes_by_id[node_id].get("op") in {"AND", "OR"}
                and nodes_by_id[node_id].get("status") == "confirmed"
                and nodes_by_id[node_id]
                .get("scope_relation", {})
                .get("status")
                == "confirmed"
            ),
            None,
        )
        if previous_group is None:
            continue
        following_atoms = [
            nodes_by_id[node_id]
            for node_id in roots_by_block.get(next_index, [])
            if node_id in nodes_by_id
            and nodes_by_id[node_id].get("op") == "ATOM"
            and nodes_by_id[node_id].get("status") != "confirmed"
        ]
        if not following_atoms:
            continue

        previous_scope = previous_group["scope_relation"]
        previous_context_refs = _merge_refs(
            previous_group.get("source_references", []),
            previous_scope.get("source_references", []),
            previous_scope.get("boundary_source_references", []),
        )
        following_refs = list(following["source_references"])
        source_refs = _merge_refs(previous_context_refs, following_refs)
        relation_status = (
            "candidate"
            if previous["source_valid"] and following["source_valid"]
            else "unresolved"
        )
        relation_id = _stable_id(
            "cross_page_scope_candidate",
            previous_group["node_id"],
            following["block_id"],
        )
        reason = (
            "page adjacency suggests possible continuation, but no explicit "
            "continuation statement confirms membership"
        )
        scope_relation = {
            "relation_id": relation_id,
            "relation_type": "cross_page_continuation_candidate",
            "operator": "UNRESOLVED",
            "status": relation_status,
            "operator_status": "unresolved",
            "scope_status": relation_status,
            "target_block_ids": list(previous_group["source_block_ids"]),
            "target_node_ids": [previous_group["node_id"]],
            "trigger_text": following["raw_text"],
            "source_references": source_refs,
            "candidate_source_references": following_refs,
            "operator_source_references": [],
            "boundary_source_references": _merge_refs(
                previous_scope.get("boundary_source_references", []),
                following_refs,
            ),
            "reason": reason,
        }
        block_relations[following["index"]]["scope_relations"].append(
            scope_relation
        )
        parent_relation = {
            "relation_id": relation_id,
            "status": relation_status,
            "layer": "semantic_parent",
            "basis": "cross_page_continuation_candidate",
            "target_block_ids": list(previous_group["source_block_ids"]),
            "target_node_ids": [previous_group["node_id"]],
            "source_references": source_refs,
            "reason": reason,
        }
        for atom in following_atoms:
            atom["parent_relations"].append(dict(parent_relation))


def _possible_antecedents(
    records: list[dict[str, Any]],
    source_index: int,
) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for record in reversed(records[:source_index]):
        if record["kind"] == "page_boundary":
            break
        if record["kind"] in {"blank", "heading"}:
            if record["kind"] == "heading":
                break
            continue
        if record["kind"] in _CONDITION_KINDS and record["raw_text"].strip():
            candidates.append(record)
            if len(candidates) == 6:
                break
    return candidates


def _anaphora_target_nodes(
    reference_text: str,
    candidates: list[dict[str, Any]],
    roots_by_block: Mapping[int, list[str]],
    nodes_by_id: Mapping[str, dict[str, Any]],
) -> list[dict[str, Any]]:
    fragment = {
        "该复印件": "复印件",
        "该说明": "说明",
        "营业收入": "营业收入",
    }.get(reference_text)
    output: list[dict[str, Any]] = []
    seen: set[str] = set()
    for candidate in candidates:
        pending = list(roots_by_block.get(candidate["index"], []))
        while pending:
            node_id = pending.pop()
            if node_id in seen:
                continue
            seen.add(node_id)
            node = nodes_by_id.get(node_id)
            if node is None:
                continue
            if node["op"] == "ATOM":
                if fragment is None or fragment in node["text"]:
                    output.append(node)
            else:
                pending.extend(node["children"])
    return output


def _has_explicit_local_item_namespace(
    text: str,
    match: re.Match[str],
) -> bool:
    if match.groupdict().get("unit") != "项":
        return False
    prefix = text[: match.start("label")]
    return bool(
        re.search(
            r"(?:本清单|本列表|上文|上述|前述|前项|本节|本章)\s*第?\s*$",
            prefix,
        )
    )


def _numbering_label(record: Mapping[str, Any]) -> str | None:
    parsed = _numbered_prefix(record["raw_text"])
    if parsed:
        return str(parsed["label"]).replace("．", ".").upper()
    numbering = record["block"].get("numbering")
    if isinstance(numbering, Mapping):
        label = numbering.get("label")
        if isinstance(label, str) and re.fullmatch(r"\d+(?:\.\d+)*", label):
            return label.replace("．", ".")
    return None


def _unique(values: list[str]) -> list[str]:
    output: list[str] = []
    seen: set[str] = set()
    for value in values:
        if value not in seen:
            seen.add(value)
            output.append(value)
    return output


def _stable_id(*parts: Any) -> str:
    encoded = json.dumps(
        parts,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
        default=str,
    ).encode("utf-8")
    return "cond_" + hashlib.sha256(encoded).hexdigest()[:24]


def _nonempty_string(value: Any) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None
