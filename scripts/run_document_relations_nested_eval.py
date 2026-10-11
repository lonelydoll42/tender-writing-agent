"""Evaluate supplied nested relation cases through frozen evaluator 1.0.3."""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import re
import sys
import tempfile
from collections import Counter
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts import run_document_relations_eval as frozen  # noqa: E402

REPORT_SCHEMA = "document-relations-nested-eval-report-v1"
_SCOPE = re.compile(
    r"(?:以下|下列).{0,18}?(?:条件|各项|材料|证明|要求|内容|项)|"
    r"第[一二三四五六七八九十0-9]+组|"
    r"[\u4e00-\u9fff]{1,8}(?:材料|证明|条件|要求|内容)"
)
_REQUIRED = re.compile(
    r"(?:必须|须|应|需)(?:同时)?(?:提交|提供|出具|加盖|满足|具备|达到|具有|符合|包含|包括)"
)
_TERMINAL = re.compile(
    r"[。；;！？!?]|"
    r"(?:以上|上述)(?:各项|条件|材料)(?:均已满足|均已提供|满足|完毕|结束|为限)|"
    r"(?:清单|列表|条件范围)(?:至此)?(?:结束|完毕|为限)"
)


def _sha256(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _positions(context: Mapping[str, Any], quote: str, pattern=None) -> list[dict]:
    pages = context.get("pages")
    if not isinstance(pages, list) or (not quote and pattern is None):
        return []
    found = []
    for page_no, page in enumerate(pages, 1):
        offset = 0
        for line_no, line in enumerate(str(page).split("\n"), 1):
            if pattern is not None:
                spans = [(m.start(), m.end(), m.group())
                         for m in pattern.finditer(line)]
            else:
                spans, start = [], 0
                while (index := line.find(quote, start)) >= 0:
                    spans.append((index, index + len(quote), quote))
                    start = index + 1
            for start, end, text in spans:
                first, last = offset + start, offset + end
                found.append({
                    "document_id": str(context.get("document_id") or ""),
                    "source_version": str(context.get("source_version") or ""),
                    "page": page_no, "line": line_no,
                    "locator": f"p{page_no}:c{first}-{last}",
                    "char_start": first, "char_end": last, "quote": text,
                })
            offset += len(line) + 1
    return found


def _refs(value: Any) -> list[dict]:
    return frozen._actual_references(value)


def _bounds(ref: Mapping[str, Any]) -> tuple[int, int] | None:
    start = ref.get("char_start", ref.get("start"))
    end = ref.get("char_end", ref.get("end"))
    span = ref.get("source_span")
    if isinstance(span, Mapping) and ("start" in span or "end" in span):
        start, end = span.get("start"), span.get("end")
    if isinstance(start, bool) or isinstance(end, bool):
        return None
    try:
        return int(start), int(end)
    except (TypeError, ValueError):
        return None


def _span_matches(actual: Mapping[str, Any], expected: Mapping[str, Any]) -> bool:
    a, e = _bounds(actual), _bounds(expected)
    if frozen._locator(actual) != frozen._locator(expected) or not a or not e:
        return False
    aq, eq = str(actual.get("quote") or ""), str(expected.get("quote") or "")
    if not aq or not eq:
        return False
    if aq in eq:
        return a[0] == e[0] + eq.find(aq) and a[1] == a[0] + len(aq)
    if eq in aq:
        return e[0] == a[0] + aq.find(eq) and e[1] == e[0] + len(eq)
    return False


def _covers(actual: Any, expected: list[Mapping[str, Any]]) -> bool:
    return any(_span_matches(a, e) for a in _refs({"source_references": actual})
               for e in expected)


def _near(refs: list[dict], anchors: list[Mapping[str, Any]]) -> list[dict]:
    if not refs or not anchors:
        return refs
    locs = [(int(x["page"]), int(x["line"])) for x in anchors]

    def distance(ref):
        return min(abs(int(ref["page"]) - p) * 100000 + abs(int(ref["line"]) - n)
                   for p, n in locs)

    nearest = min(map(distance, refs))
    return [x for x in refs if distance(x) == nearest]


def _atoms(tree: Any) -> list[str]:
    if isinstance(tree, str):
        return [tree]
    return [atom for child in tree.get("children", []) for atom in _atoms(child)]


def _group_quotes(tree, context):
    atoms = [r for atom in _atoms(tree) for r in _positions(context, atom)]
    operator = _positions(context, str(tree.get("operator_quote") or ""))
    quote = tree.get("scope_quote")
    scope = (_positions(context, quote) if isinstance(quote, str) and quote
             else _positions(context, "", _SCOPE))
    return _near(operator, scope or atoms), _near(scope, operator or atoms)


def _nodes(graph: Mapping[str, Any]) -> tuple[dict[str, Mapping[str, Any]], list[str]]:
    rows = graph.get("condition_nodes")
    if not isinstance(rows, list):
        return {}, ["condition_nodes is missing"]
    nodes, errors = {}, []
    for row in rows:
        if not isinstance(row, Mapping) or not row.get("node_id"):
            errors.append("condition node has no node_id")
            continue
        key = str(row["node_id"])
        if key in nodes:
            errors.append(f"duplicate node_id: {key}")
        nodes[key] = row
    return nodes, errors


def _match(node_id: str, expected: Any, nodes: Mapping[str, Mapping[str, Any]],
           seen: frozenset[str] = frozenset()) -> dict | None:
    if node_id in seen or node_id not in nodes:
        return None
    node = nodes[node_id]
    op, raw = str(node.get("op") or "").upper(), node.get("children")
    if not isinstance(raw, list):
        return None
    children = [str(x) for x in raw]
    if len(children) != len(set(children)):
        return None
    seen = seen | {node_id}
    if isinstance(expected, str):
        text = str(node.get("text") or "").strip()
        if op == "ATOM" and not children and text == expected:
            return dict(node_id=node_id, leaf_id=node_id, unary=False, children=[])
        if op != "AND" or len(children) != 1 or children[0] in seen:
            return None
        leaf_id = children[0]
        leaf = nodes.get(leaf_id)
        if (not leaf or str(leaf.get("op") or "").upper() != "ATOM"
                or leaf.get("children") not in ([], None)
                or str(leaf.get("text") or "").strip() != expected):
            return None
        leaf_match = {"node_id": leaf_id, "leaf_id": leaf_id,
                      "unary": False, "children": []}
        return {"node_id": node_id, "leaf_id": leaf_id, "unary": True,
                "children": [{"expected": expected, "node_id": leaf_id,
                              "match": leaf_match}]}
    if not isinstance(expected, Mapping):
        return None
    wanted = expected.get("children")
    if (op not in {"AND", "OR"} or op != str(expected.get("op") or "").upper()
            or not isinstance(wanted, list) or len(children) != len(wanted)):
        return None

    def assign(index: int, remaining: list[str]) -> list[dict] | None:
        if index == len(wanted):
            return [] if not remaining else None
        for candidate in remaining:
            match = _match(candidate, wanted[index], nodes, seen)
            if match is None:
                continue
            tail = assign(index + 1, [x for x in remaining if x != candidate])
            if tail is not None:
                return [{"expected": wanted[index], "node_id": candidate,
                         "match": match}, *tail]
        return None

    matched = assign(0, children)
    if matched is None:
        return None
    return {"node_id": node_id, "leaf_id": None, "unary": False,
            "expected": expected, "children": matched}


def _walk(match: Mapping[str, Any]):
    yield match
    for child in match.get("children", []):
        yield from _walk(child["match"])


def _descendants(node, nodes):
    children = node.get("children")
    pending = [str(x) for x in children] if isinstance(children, list) else []
    found = set()
    while pending:
        current = pending.pop()
        if current in found or current not in nodes:
            continue
        found.add(current)
        children = nodes[current].get("children")
        if isinstance(children, list):
            pending.extend(str(x) for x in children)
    return found


def _targets(scope: Mapping[str, Any], direct: list[str]) -> bool:
    values = scope.get("target_node_ids")
    if not isinstance(values, list):
        return False
    ids = [str(x) for x in values]
    return len(ids) == len(set(ids)) == len(direct) and set(ids) == set(direct)


def _operator_ok(op: str, quotes: list[dict], node: Mapping[str, Any]) -> bool:
    relation = node.get("operator_relation")
    if not isinstance(relation, Mapping):
        return False
    refs = _refs(relation)
    return any(
        frozen._operator_evidence({"operator": op, "boundary_basis": [quote]}, node)[0]
        and refs and all(_span_matches(ref, quote) for ref in refs)
        for quote in quotes
    )


def _parent_ok(child: Mapping[str, Any], parent: str, operators: list[dict],
               scopes: list[dict]) -> bool:
    relations = child.get("parent_relations")
    return isinstance(relations, list) and any(
        isinstance(rel, Mapping)
        and frozen._status(rel.get("status")) == "confirmed"
        and isinstance(rel.get("target_node_ids"), list)
        and [str(x) for x in rel["target_node_ids"]] == [parent]
        and str(rel.get("basis") or "").strip() and _refs(rel)
        and (_covers(rel.get("source_references"), operators)
             or _covers(rel.get("source_references"), scopes))
        for rel in relations
    )


def _validate_atom(node: Mapping[str, Any], atom: str, context: Mapping[str, Any],
                   errors: list[str], path: str) -> None:
    if frozen._status(node.get("status")) != "confirmed":
        errors.append(f"{path}: ATOM is not confirmed")
    if not _covers(node.get("source_references"), _positions(context, atom)):
        errors.append(f"{path}: ATOM source does not cover its original text")


def _leaf_rows(match, expected, nodes, context):
    if isinstance(expected, str):
        leaf_id = str(match.get("leaf_id") or match["node_id"])
        refs = _refs(nodes[leaf_id])
        return [
            {"node_id": leaf_id, "position": p}
            for p in _positions(context, expected)
            if any(_span_matches(ref, p) for ref in refs)
        ]
    return [row for child in match.get("children", [])
            for row in _leaf_rows(child["match"], child["expected"], nodes, context)]


def _boundary(match: Mapping[str, Any], expected: Any,
              nodes: Mapping[str, Mapping[str, Any]], context: Mapping[str, Any],
              all_leaves: list[dict]) -> list[dict]:
    leaves = _leaf_rows(match, expected, nodes, context)
    if not leaves:
        return []
    last = max(leaves, key=lambda x: (x["position"]["page"],
                                      x["position"]["char_end"]))["position"]
    page, line, end = int(last["page"]), int(last["line"]), int(last["char_end"])
    local = {str(x["node_id"]) for x in leaves}
    following = [(int(x["position"]["page"]), int(x["position"]["char_start"]))
                 for x in all_leaves if str(x["node_id"]) not in local
                 and (int(x["position"]["page"]), int(x["position"]["char_start"]))
                 > (page, end)]
    limit = min(following, default=(page, 10**12))
    return [p for p in _positions(context, "", _TERMINAL)
            if int(p["page"]) == page and int(p["line"]) == line
            and int(p["char_start"]) >= end
            and (int(p["page"]), int(p["char_start"])) < limit][:1]


def _boundary_cited(scope, expected):
    return bool(expected) and _covers(scope.get("boundary_source_references"), expected)


def _validate_match(match: Mapping[str, Any], expected: Any,
                    nodes: Mapping[str, Mapping[str, Any]], context: Mapping[str, Any],
                    all_leaves: list[dict], errors: list[str], path: str) -> None:
    node = nodes[str(match["node_id"])]
    if isinstance(expected, str) and not match.get("unary"):
        _validate_atom(node, expected, context, errors, path)
        return
    if match.get("unary"):
        atom_id = str(match["leaf_id"])
        atom = nodes[atom_id]
        required = _near(_positions(context, "", _REQUIRED),
                         _positions(context, str(expected)))
        relation = node.get("operator_relation")
        if (str(node.get("op") or "").upper() != "AND"
                or frozen._status(node.get("status")) != "confirmed"
                or not isinstance(relation, Mapping)
                or frozen._status(relation.get("status")) != "confirmed"
                or relation.get("kind") != "unary_required_normalization"
                or relation.get("basis") != "single_item_requirement"
                or not required
                or not _covers(relation.get("source_references"), required)):
            errors.append(f"{path}: unary AND lacks confirmed REQUIRED evidence")
        scope = node.get("scope_relation")
        boundary = _boundary(match, expected, nodes, context, all_leaves)
        atom_refs = _positions(context, expected)
        if (not isinstance(scope, Mapping)
                or frozen._status(scope.get("status")) != "confirmed"
                or not _targets(scope, [atom_id])
                or not _boundary_cited(scope, boundary)
                or not _covers(scope.get("source_references"), atom_refs)):
            errors.append(f"{path}: unary scope lacks its own terminal boundary")
        _validate_atom(atom, expected, context, errors, f"{path}/{atom_id}")
        if not _parent_ok(atom, str(match["node_id"]), required,
                          _positions(context, expected)):
            errors.append(f"{path}: unary ATOM lacks confirmed parent evidence")
        return

    op = str(expected["op"]).upper()
    operators, scopes = _group_quotes(expected, context)
    relation = node.get("operator_relation")
    if frozen._status(node.get("status")) != "confirmed":
        errors.append(f"{path}: group node is not confirmed")
    if (not isinstance(relation, Mapping)
            or frozen._status(relation.get("status")) != "confirmed"):
        errors.append(f"{path}: operator_relation is not confirmed")
    elif not _operator_ok(op, operators, node):
        errors.append(f"{path}: operator_relation lacks its own cited cue")
    scope = node.get("scope_relation")
    if not isinstance(scope, Mapping):
        errors.append(f"{path}: scope_relation is missing")
        scope = {}
    if frozen._status(scope.get("status")) != "confirmed":
        errors.append(f"{path}: scope_relation is not confirmed")
    direct = [str(x["node_id"]) for x in match.get("children", [])]
    if not _targets(scope, direct):
        errors.append(f"{path}: scope targets differ from direct children")
    boundary = _boundary(match, expected, nodes, context, all_leaves)
    if not _boundary_cited(scope, boundary):
        errors.append(f"{path}: boundary refs do not cover this group's terminal")
    if not scopes or not _covers(scope.get("source_references"), scopes):
        errors.append(f"{path}: scope_relation lacks its own label/count evidence")
    nested = scope.get("operator_relation")
    if (isinstance(nested, Mapping)
            and frozen._status(nested.get("status")) != "confirmed"):
        errors.append(f"{path}: nested scope operator is not confirmed")
    for child in match.get("children", []):
        child_id = str(child["node_id"])
        if not _parent_ok(nodes[child_id], str(match["node_id"]), operators, scopes):
            errors.append(f"{path}: child {child_id} lacks confirmed parent evidence")
        _validate_match(child["match"], child["expected"], nodes, context,
                        all_leaves, errors, f"{path}/{child_id}")


def _material_node(node: Mapping[str, Any], material: str,
                   context: Mapping[str, Any]) -> bool:
    return (str(node.get("op") or "").upper() == "ATOM"
            and material in str(node.get("text") or "")
            and _covers(node.get("source_references"), _positions(context, material)))


def _positive(case: Mapping[str, Any], graph: Mapping[str, Any],
              context: Mapping[str, Any]) -> list[str]:
    errors = []
    nodes, node_errors = _nodes(graph)
    errors.extend(node_errors)
    tree, roots = case["expected_tree"], graph.get("roots")
    root_ids = {str(x) for x in roots} if isinstance(roots, list) else set()
    matches = [_match(n, tree, nodes) for n in root_ids if n in nodes
               and str(nodes[n].get("op") or "").upper() == str(tree["op"]).upper()]
    matches = [x for x in matches if x is not None]
    if len(matches) != 1:
        return [*errors, "expected exactly one graph root matching the nested tree"]
    match = matches[0]
    walked = list(_walk(match))
    tree_ids = {str(x["node_id"]) for x in walked}
    if len(tree_ids) != len(walked):
        errors.append("nested tree reuses a node or contains a cycle")
    root_id = str(match["node_id"])
    for node_id, node in nodes.items():
        if (node_id in tree_ids
                or str(node.get("op") or "").upper() not in {"AND", "OR"}
                or frozen._status(node.get("status")) != "confirmed"):
            continue
        descendants = _descendants(node, nodes)
        children = node.get("children")
        direct = set(map(str, children)) if isinstance(children, list) else set()
        ancestor = root_id in descendants and not (direct & (tree_ids - {root_id}))
        if descendants & tree_ids and not ancestor:
            errors.append(f"confirmed group {node_id} reuses expected-tree nodes")
    expected = Counter(_atoms(tree))
    actual = Counter(str(n.get("text") or "").strip() for n in nodes.values()
                     if str(n.get("op") or "").upper() == "ATOM"
                     and frozen._status(n.get("status")) == "confirmed"
                     and str(n.get("text") or "").strip() in expected)
    for atom, count in expected.items():
        if actual[atom] != count:
            errors.append(f"confirmed leaf count for {atom!r}: {actual[atom]}/{count}")
    leaves = _leaf_rows(match, tree, nodes, context)
    _validate_match(match, tree, nodes, context, leaves, errors, root_id)
    for atom in case.get("outside_atoms", []):
        if not any(n not in tree_ids and _material_node(node, atom, context)
                   for n, node in nodes.items()):
            errors.append(f"outside atom {atom!r} was not retained outside the tree")
    return errors


def _linked(value: Any, refs: list[dict]) -> bool:
    return isinstance(value, Mapping) and _covers(value.get("source_references"), refs)


def _review_evidence(value: Any, refs: list[dict]) -> bool:
    if isinstance(value, Mapping):
        return ((frozen._status(value.get("status")) in {"candidate", "unresolved"}
                 and _linked(value, refs))
                or any(_review_evidence(x, refs) for x in value.values()))
    return isinstance(value, list) and any(_review_evidence(x, refs) for x in value)


def _review(case: Mapping[str, Any], graph: Mapping[str, Any],
            context: Mapping[str, Any]) -> list[str]:
    errors = []
    forbidden = _positions(context, case["forbidden_operator_quote"])
    review = _positions(context, case["review_quote"])
    if not forbidden:
        errors.append("forbidden_operator_quote does not occur in source")
    if not review or not _review_evidence(graph, review):
        errors.append("review_quote was not retained as candidate/unresolved evidence")
    nodes, node_errors = _nodes(graph)
    errors.extend(node_errors)
    targets = []
    for node in nodes.values():
        if str(node.get("op") or "").upper() not in {"AND", "OR"}:
            continue
        scope = node.get("scope_relation")
        scope = scope if isinstance(scope, Mapping) else {}
        if any(_linked(x, forbidden) for x in (
            node.get("operator_relation"), scope, scope.get("operator_relation")
        )):
            targets.append((node, scope, "node"))
    blocks = graph.get("block_relations")
    if isinstance(blocks, list):
        for block in blocks:
            if not isinstance(block, Mapping):
                continue
            for scope in block.get("scope_relations", []):
                if isinstance(scope, Mapping) and any(_linked(x, forbidden) for x in (
                    scope, scope.get("operator_relation")
                )):
                    targets.append((block, scope, "block_scope"))
    for owner, scope, kind in targets:
        if ((kind == "node" and frozen._status(owner.get("status")) == "confirmed")
                or frozen._status(scope.get("status")) == "confirmed"):
            errors.append(f"{kind}: forbidden source confirms the complete group/scope")
        if case.get("forbid_confirmed_operator", False):
            rel = (scope.get("operator_relation") if kind == "block_scope"
                   else owner.get("operator_relation"))
            confirmed = (isinstance(rel, Mapping)
                         and frozen._status(rel.get("status")) == "confirmed")
            if (kind == "block_scope"
                    and frozen._status(scope.get("operator_status")) == "confirmed"):
                confirmed = True
            if confirmed:
                errors.append(f"{kind}: forbidden source confirms its operator")
    for atom in case.get("retained_atoms", []):
        if not any(_material_node(node, atom, context) for node in nodes.values()):
            errors.append(f"retained atom {atom!r} lacks a source-backed ATOM")
    return errors


def _validate_cases(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, Mapping) or "schema_version" not in payload:
        raise ValueError("cases JSON must be an object with schema_version")
    rows = payload.get("cases")
    if not isinstance(rows, list):
        raise ValueError("cases JSON must contain a cases list")
    result, seen = [], set()
    for index, row in enumerate(rows):
        if not isinstance(row, Mapping):
            raise ValueError(f"case {index} must be an object")
        case = dict(row)
        case_id, text = case.get("id"), case.get("text")
        if not isinstance(case_id, str) or not case_id.strip() or case_id in seen:
            raise ValueError(f"case {index} has a missing or duplicate id")
        if not isinstance(text, str) or not text:
            raise ValueError(f"{case_id}: text must be non-empty")
        seen.add(case_id)
        if case.get("review_only") is True:
            for key in ("forbidden_operator_quote", "review_quote"):
                if not isinstance(case.get(key), str) or not case[key]:
                    raise ValueError(f"{case_id}: {key} is required")
            if type(case.get("forbid_confirmed_operator", False)) is not bool:
                raise ValueError(f"{case_id}: forbid_confirmed_operator must be bool")
            retained = case.get("retained_atoms")
            if not isinstance(retained, list) or any(
                not isinstance(x, str) or not x for x in retained
            ):
                raise ValueError(f"{case_id}: retained_atoms must be strings")
        else:
            def check_tree(tree: Any) -> None:
                if isinstance(tree, str) and tree:
                    return
                scope = tree.get("scope_quote") if isinstance(tree, Mapping) else None
                if (not isinstance(tree, Mapping)
                        or str(tree.get("op") or "").upper() not in {"AND", "OR"}
                        or not isinstance(tree.get("operator_quote"), str)
                        or not tree["operator_quote"]
                        or (scope is not None
                            and (not isinstance(scope, str) or not scope))):
                    raise ValueError(f"{case_id}: invalid expected_tree node")
                children = tree.get("children")
                if not isinstance(children, list) or len(children) < 2:
                    raise ValueError(f"{case_id}: groups need at least two children")
                for child in children:
                    check_tree(child)
            tree = case.get("expected_tree")
            if not isinstance(tree, Mapping):
                raise ValueError(f"{case_id}: expected_tree root must be a group")
            check_tree(tree)
            outside = case.get("outside_atoms", [])
            if not isinstance(outside, list) or any(
                not isinstance(x, str) or not x for x in outside
            ):
                raise ValueError(f"{case_id}: outside_atoms must be strings")
        result.append(case)
    return result


def _identity(case: Mapping[str, Any], runtime: Mapping[str, Any],
              graph: Mapping[str, Any], context: Mapping[str, Any]) -> list[str]:
    errors = []
    raw_hash = _sha256(str(case["text"]).encode("utf-8"))
    schema = graph.get("schema", graph.get("schema_version"))
    doc = graph.get("document_id", graph.get("docid"))
    version = graph.get("source_version", graph.get("version"))
    pages = context.get("pages")
    context_doc = context.get("document_id")
    context_version = context.get("source_version")
    if schema != "document-relations-v1":
        errors.append("graph schema is not document-relations-v1")
    if not context_doc or str(doc or "") != str(context_doc):
        errors.append("graph document identity is not registry-verified")
    if not context_version or str(version or "") != str(context_version):
        errors.append("graph source version is not registry-verified")
    pages_match = (
        isinstance(pages, list)
        and frozen.BOUNDARY.join(map(str, pages)) == case["text"]
    )
    if not pages_match:
        errors.append("source_context pages differ from the supplied input")
    registry_hash = runtime.get("registered_input_sha256")
    if context.get("raw_input_sha256") != raw_hash or registry_hash != raw_hash:
        errors.append("registered input checksum does not match the supplied input")
    return errors


def _empty_validation() -> dict[str, Any]:
    return {"checked_references": 0, "invalid_references": 0,
            "denominator": 0, "failures": []}


async def _evaluate(cases: list[dict[str, Any]]) -> list[dict[str, Any]]:
    results = []
    with tempfile.TemporaryDirectory(prefix="document-relations-nested-") as directory:
        for index, case in enumerate(cases):
            case_id = str(case["id"])
            path = Path(directory) / f"case-{index + 1}.txt"
            path.write_bytes(case["text"].encode("utf-8"))
            kind = "review" if case.get("review_only") is True else "positive"
            try:
                runtime = await frozen._run_input(path, case_id)
            except Exception as exc:
                results.append({
                    "id": case_id, "kind": kind, "status": "failed",
                    "execution_state": "failed",
                    "errors": [f"runtime exception: {type(exc).__name__}: {exc}"],
                    "source_identity": {"status": "not_run"},
                    "source_validation": _empty_validation(),
                    "actual_graph": None, "source_context": None,
                })
                continue
            state = str(runtime.get("execution_state") or "failed")
            execution_state = (
                state if state in {"executed", "failed", "not_run"} else "failed"
            )
            entry = {
                "id": case_id, "kind": kind,
                "status": state if state in {"failed", "not_run"} else "failed",
                "execution_state": execution_state,
                "errors": [str(runtime["reason"])] if runtime.get("reason") else [],
                "source_identity": {"status": "not_run"},
                "source_validation": _empty_validation(),
                "actual_graph": deepcopy(runtime.get("graph")),
                "source_context": deepcopy(runtime.get("source_context")),
            }
            if state != "executed":
                if state not in {"failed", "not_run"}:
                    entry["errors"].append(f"unknown runtime state: {state}")
                results.append(entry)
                continue
            graph, context = runtime.get("graph"), runtime.get("source_context")
            if not isinstance(graph, Mapping) or not isinstance(context, Mapping):
                entry["errors"].append("runtime omitted graph or source_context")
                results.append(entry)
                continue
            identity = _identity(case, runtime, graph, context)
            entry["source_identity"] = {
                "status": "failed" if identity else "registry_verified"
            }
            validation = frozen._validate_graph_source_references(graph, context)
            checked, invalid = (int(validation["checked_references"]),
                                int(validation["invalid_references"]))
            entry["source_validation"] = {
                "checked_references": checked, "invalid_references": invalid,
                "denominator": checked, "failures": validation["failures"],
            }
            errors = list(identity)
            if checked == 0:
                errors.append("source validation checked zero references")
            if invalid:
                errors.append("one or more source references failed raw validation")
            checked_graph = validation["normalized_graph"]
            errors.extend(_review(case, checked_graph, context) if kind == "review"
                          else _positive(case, checked_graph, context))
            entry["errors"], entry["status"] = errors, "failed" if errors else "passed"
            results.append(entry)
    return results


async def run_evaluation(
    payload: Mapping[str, Any], raw_cases: bytes
) -> dict[str, Any]:
    cases = _validate_cases(payload)
    results = await _evaluate(cases)
    checked = sum(x["source_validation"]["checked_references"] for x in results)
    invalid = sum(x["source_validation"]["invalid_references"] for x in results)
    positives = [x for x in results if x["kind"] == "positive"]
    reviews = [x for x in results if x["kind"] == "review"]
    frozen_path = Path(frozen.__file__).resolve()
    return {
        "schema": REPORT_SCHEMA,
        "generated_at": datetime.now().astimezone().isoformat(),
        "cases_schema_version": payload["schema_version"],
        "hashes": {
            "cases_json_sha256": _sha256(raw_cases),
            "source_tree_sha256": frozen._source_tree_sha256(ROOT),
            "grader_sha256": _sha256(Path(__file__).resolve().read_bytes()),
            "frozen_1_0_3_sha256": _sha256(frozen_path.read_bytes()),
        },
        "frozen_evaluator_version": frozen.EVALUATOR_VERSION,
        "summary": {
            "passed": sum(x["status"] == "passed" for x in results),
            "failed": sum(x["status"] == "failed" for x in results),
            "not_run": sum(x["status"] == "not_run" for x in results),
            "executed": sum(x["execution_state"] == "executed" for x in results),
            "total": len(results),
            "positive_passed": sum(x["status"] == "passed" for x in positives),
            "positive_total": len(positives),
            "review_handled": sum(x["status"] == "passed" for x in reviews),
            "review_total": len(reviews),
            "source_references": {"invalid": invalid, "checked": checked},
        },
        "cases": results,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cases", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    output = args.output.resolve()
    if output.exists():
        parser.error(f"refusing to overwrite existing report: {output}")
    try:
        raw = args.cases.read_bytes()
        payload = json.loads(raw.decode("utf-8"))
        if not isinstance(payload, Mapping):
            raise ValueError("cases JSON root must be an object")
        report = asyncio.run(run_evaluation(payload, raw))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError, ValueError) as exc:
        parser.error(f"invalid cases input: {exc}")
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(report, ensure_ascii=False, indent=2) + "\n")
    if report["summary"]["failed"]:
        return 1
    return 2 if report["summary"]["not_run"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
