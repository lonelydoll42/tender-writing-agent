"""Reviewer-owned source annotations; does not import product or grader code."""

from __future__ import annotations

import argparse
import hashlib
import json
from datetime import datetime
from pathlib import Path


def ref(text: str, line: int, quote: str, *, terminal: bool = False) -> dict:
    rows = text.split("\n")
    start = sum(len(row) + 1 for row in rows[: line - 1])
    value = rows[line - 1]
    local = value.rfind(quote) if terminal else value.index(quote)
    if local < 0:
        raise ValueError((line, quote))
    return {
        "page": 1,
        "line": line,
        "quote": quote,
        "char_start": start + local,
        "char_end": start + local + len(quote),
    }


def annotate(case_id: str, text: str, *, negative: str | None = None) -> dict:
    rows = text.split("\n")
    group_lines = [
        index + 1 for index, line in enumerate(rows) if line.startswith("第")
    ]
    assert len(group_lines) == 2
    atoms, contracts, groups = [], {}, []
    terminals = [ref(text, line, "。", terminal=True) for line in group_lines]
    root_quote = rows[0].split("，", 1)[0].split("。", 1)[0]
    inherited = "每组" in rows[0]
    selection = None
    if inherited:
        selection = rows[0].split("但", 1)[1].rstrip("：:")
        root_quote = rows[0].split("，", 1)[0]
    root_cue = ref(text, 1, root_quote)
    group_labels = [
        ref(text, line, rows[line - 1].split("：")[0][:3]) for line in group_lines
    ]
    member_id = 0
    for index, line in enumerate(group_lines, 1):
        row = rows[line - 1]
        prefix, payload = row.split("：", 1)
        pieces = payload.rstrip("。").split("；")
        members, member_sources = [], {}
        for piece in pieces:
            if "）" in piece:
                piece = piece.split("）", 1)[1]
            member_id += 1
            atom_id = f"A{member_id}"
            source = ref(text, line, piece)
            atoms.append(
                {
                    "id": atom_id,
                    "text": piece,
                    "certainty": "confirmed",
                    "source": [source],
                }
            )
            members.append(atom_id)
            member_sources[atom_id] = [source]
        group_id = f"S{index}"
        groups.append(
            {
                "id": group_id,
                "operator": "OR",
                "status": "confirmed",
                "members": members,
                "boundary_basis": [
                    ref(text, 1, selection) if inherited else ref(text, line, prefix),
                    ref(text, line, row.rstrip("。")),
                ],
            }
        )
        local_state = (
            "absent"
            if prefix == f"第{'一' if index == 1 else '二'}组"
            else "compatible"
        )
        if index == 1 and negative in {"local_conflict", "unsupported_count"}:
            local_state = negative
        contract = {
            "operator": "OR",
            "members": members,
            "operator_sources": [
                ref(text, 1, selection)
                if inherited and local_state == "absent"
                else ref(text, line, prefix)
            ],
            "scope_sources": [group_labels[index - 1]],
            "member_sources": member_sources,
            "region": {
                "page": 1,
                "char_start": group_labels[index - 1]["char_start"],
                "char_end": terminals[index - 1]["char_end"],
            },
            "termination_sources": [terminals[index - 1]],
            "local_instruction": {
                "state": local_state,
                "source": ref(text, line, prefix),
            },
            "inheritance": None,
        }
        if inherited and local_state == "absent":
            contract["inheritance"] = {
                "parent_group_id": "S0",
                "applicability_sources": [ref(text, 1, rows[0])],
                "parent_link_sources": [root_cue, group_labels[index - 1]],
                "declared_count": 2,
                "group_labels": group_labels,
                "contiguous": negative != "intervening_paragraph",
            }
        contracts[group_id] = contract
    groups.append(
        {
            "id": "S0",
            "operator": "AND",
            "status": "confirmed",
            "members": ["S1", "S2"],
            "boundary_basis": [root_cue],
        }
    )
    contracts["S0"] = {
        "operator": "AND",
        "members": ["S1", "S2"],
        "operator_sources": [root_cue],
        "scope_sources": [ref(text, 1, root_quote.split("均", 1)[0])],
        "member_sources": {"S1": [group_labels[0]], "S2": [group_labels[1]]},
        "region": {"page": 1, "char_start": 0, "char_end": terminals[-1]["char_end"]},
        "termination_sources": terminals,
        "local_instruction": {"state": "compatible", "source": root_cue},
        "inheritance": None,
    }
    atom_count = len(atoms)
    case = {
        "case_id": case_id,
        "conditions": atoms,
        "groups": groups,
        "expect_confirmed": {
            "conditions": [atom["id"] for atom in atoms],
            "relations": [],
        },
        "forbidden": [],
        "needs_review": [],
        "denominators": {
            "confirmed_atom_count": atom_count,
            "condition_omission": atom_count,
            "wrong_merge_pairs": atom_count * (atom_count - 1) // 2,
            "wrong_split_atom_units": atom_count,
            "confirmed_scope_count": 3,
            "scope_membership_decisions": atom_count * 3,
        },
    }
    return {
        "case_id": case_id,
        "raw_input_sha256": hashlib.sha256(text.encode("utf-8")).hexdigest(),
        "expected_grader_decision": "reject_incorrect_confirmed"
        if negative
        else "accept_valid",
        "expected_product_review": bool(negative),
        "negative_reason": negative,
        "case": case,
        "evidence_contract": {
            "schema": "boundary-evidence-contract-v1",
            "case_id": case_id,
            "groups": contracts,
        },
    }


def save_new(path: Path, value: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        json.dump(value, handle, ensure_ascii=False, indent=2, allow_nan=False)
        handle.write("\n")


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--kind", choices=("development", "holdout", "historical"), required=True
    )
    args = parser.parse_args()
    if args.kind == "historical":
        oracle_path = args.root / "machine-oracle.json"
        raw_oracle = oracle_path.read_bytes()
        oracle = json.loads(raw_oracle)
        overlays = []
        for case in oracle["cases"]:
            if case["case_id"] not in {"case-03", "case-11"}:
                continue
            text = (args.root / case["input"]).read_bytes().decode("utf-8")
            entry = annotate(case["case_id"], text)
            if case["case_id"] == "case-03":
                del entry["evidence_contract"]["groups"]["S2"]
            overlays.append(
                {
                    "case_id": case["case_id"],
                    "raw_input_sha256": entry["raw_input_sha256"],
                    "evidence_contract": entry["evidence_contract"],
                }
            )
        save_new(
            args.output,
            {
                "schema": "boundary-evidence-historical-overlay-v1",
                "frozen_at": datetime.now().astimezone().isoformat(),
                "oracle_sha256": hashlib.sha256(raw_oracle).hexdigest(),
                "product_report_sha256": (
                    "1745cb650edca81e163fc773c71cd9db96e33b3e2df10dc3b8c208af050eb7b7"
                ),
                "unlisted_groups": "unchanged legacy 1.0.4 rules",
                "cases": overlays,
            },
        )
        return
    specs = (
        [
            ("D01", None),
            ("D02", None),
            ("D03", "local_conflict"),
            ("D04", "unsupported_count"),
            ("D05", "intervening_paragraph"),
        ]
        if args.kind == "development"
        else [
            ("H01", None),
            ("H02", None),
            ("H03", None),
            ("H04", "local_conflict"),
            ("H05", "unsupported_count"),
            ("H06", "intervening_paragraph"),
        ]
    )
    cases = []
    for case_id, negative in specs:
        path = args.root / "raw" / f"{case_id}.txt"
        text = path.read_bytes().decode("utf-8")
        entry = annotate(case_id, text, negative=negative)
        entry["input"] = f"raw/{case_id}.txt"
        cases.append(entry)
    save_new(
        args.output,
        {
            "schema": "boundary-evidence-frozen-cases-v1",
            "frozen_at": datetime.now().astimezone().isoformat(),
            "kind": args.kind,
            "classification": (
                "reviewer-authored source annotations; invalid confirmed graphs "
                "are grader counterexamples, not product gold trees"
            ),
            "policy_only_isolation": args.kind == "holdout",
            "cases": cases,
            "positive_mutations": [
                "unchanged",
                "boundary_whole_own_line",
                "boundary_only_final_punctuation",
                "parent_reference_superset_inside_scope",
            ],
            "negative_mutations": [
                "operator_from_adjacent_group",
                "scope_from_adjacent_group",
                "missing_one_member_source",
                "scope_not_confirmed",
                "leaf_targets_for_root",
                "boundary_from_adjacent_group",
                "boundary_operator_only",
                "boundary_semicolon_only",
                "boundary_missing",
                "boundary_wrong_occurrence",
                "boundary_cross_paragraph",
                "parent_not_confirmed",
                "parent_scope_not_confirmed",
                "parent_link_missing",
                "structural_parent_only",
                "parent_link_wrong_group",
                "parent_link_wrong_source",
                "additional_conflicting_parent",
                "forged_raw_valid_flag",
                "wrong_source_version",
            ],
        },
    )


if __name__ == "__main__":
    main()
