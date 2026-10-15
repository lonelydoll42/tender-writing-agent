# Finite Material Numbering Worker Result

Date: 2026-10-15. Shared checkout: `E:\project\tender-writing-agent`.
No delegation, new worktree, git add, commit, or push was performed.

## Product Scope

- Completed the predecessor's finite numbering integration in
  `src/qiaowenshu_agent/domain/document_relations.py`.
- The full sentence must match the frozen affirmative Chinese grammar, including
  its final full stop. Two distinct listed labels must match the quoted endpoints
  as literal strings. No floats, normalization, ordering, or intermediate members.
- Reused `_NodeBuilder` and `_add_inline_scope_relations`. Successful output is
  exactly two source-backed ATOMs and their direct AND parent. Leaf text and leaf
  references are the original listed `编号X项` spans. The shared operator supplies
  the submission duty; scope evidence contains the endpoints, enumeration, and
  two-item count; boundary evidence is the complete original block.
- Existing source validation gates all confirmation, including operator, scope,
  and semantic parent status. No global metadata recognition rules were changed.
- Numbering intervals and existing numbering explanation contexts that fail the
  finite grammar remain source-backed candidates/unresolved with review reasons.
- Removed the predecessor's overly broad bare-count review branch. A normal
  material list containing `共两项材料` retains its original confirmed AND behavior.
  N11's first numbering paragraph is checked as a candidate; the second ordinary
  obligation is handled independently and is not forced into numbering review.

## Tests And Evidence

Final command (run from the checkout root):

```powershell
$env:PYTHONDONTWRITEBYTECODE='1'
.venv\Scripts\python.exe -m pytest -p no:cacheprovider tests/test_document_relations_numbering_semantics.py tests/test_document_relations.py tests/test_document_relations_financial_context.py tests/test_document_relations_attributes.py tests/test_document_relations_copy_alternatives.py --basetemp=.qiaowenshu/pytest-numbering-worker-final-20261015-01 --junitxml=benchmarks/document_relations/reports/numbering-followup-20261015/worker/pytest-green-final-01.xml -q
```

Result: **231 passed**, zero failures/errors/skips.

| Test File | Passed |
| --- | ---: |
| New numbering semantics | 34 |
| Existing document relations | 122 |
| Existing financial context | 27 |
| Existing copy attributes (`test_document_relations_attributes.py`) | 32 |
| Existing copy alternatives | 16 |

The new 34 tests comprise all 20 frozen cases, all 6 additional public probes,
7 effective source corruptions, and 1 ordinary-list preservation control.
The corruptions cover block source-span coordinates, reference coordinates,
duplicate block ID, missing document ID/version, and conflicting reference
document ID/version. All require retained nodes without any confirmed node,
operator, scope, or semantic parent.

Positive tests check exactly two leaf source strings, their common semantic
parent, direct scope members, node/block scope agreement, full boundary evidence,
source document/version/coordinates/locator/quote, and unchanged partial/manual
review flags. N11 verifies evidence separately against each physical block.

Checks:

```powershell
.venv\Scripts\ruff.exe check --no-cache src/qiaowenshu_agent/domain/document_relations.py tests/test_document_relations_numbering_semantics.py
.venv\Scripts\ruff.exe format --no-cache --check tests/test_document_relations_numbering_semantics.py
```

Both passed. Only the new test file was formatted.

Worker evidence files:

- `pytest-green-final-01.xml` and `pytest-green-final-01.log`: final combined run.
- `ruff-check-final-01.log`, `ruff-format-final-01.log`: final checks.
- `pytest-implementation-01.xml`: first implementation run, 33 passed, before
  narrowing the bare-count trigger and adding the ordinary-list control.
- `pytest-existing-01.xml`: earlier existing-specialty run, 197 passed.
- `pytest-implementation-02.xml`: after narrowing, 34 passed.
- `pytest-baseline-red.xml`: predecessor baseline retained without overwrite or
  rerun; baseline counts are 23 total, 17 passed, 6 failed.
  SHA256: `461C0EEA809F2339EAC64803B1E2745ED0E2381B1CDF64F286AD351FCEDDF225`.

## Raw Byte Snapshots

`Copy-Item` preserved the final filesystem bytes. Each snapshot SHA256 was
checked against its source file and matched.

| Snapshot | SHA256 |
| --- | --- |
| `document_relations.final.py.txt` | `5AC7C3BD518C65B05564AC31CAD49263BF8C9525B0DC690D2A7F8794E966DE19` |
| `test_document_relations_numbering_semantics.final.py.txt` | `73A552055E3B373DE46806BFD27501CEAAF24A809D1A4ECA5F8301A848BA456B` |

## Limits And Handoff

Only the authorized product file, new numbering test, and this worker directory
were intentionally edited. Frozen contract/cases/probes, old tests, scorers,
oracle, reviewer checker, publication records, and `uv.lock` were not edited.
Existing unrelated shared-checkout changes were left in place.

These are public regression and unit/specialty results, not unseen acceptance.
The 26-case figure here refers to tests calling the actual structure/relations
builders, not the reviewer's independent Registry-to-Runtime acceptance.
This worker did not run the full suite, reviewer semantic/source mutation
harness, 14-case recollection, or three-scorer replay. Those remain with the
main reviewer, along with its separate 22/33 specialty runs and final delivery.
Case-07, cross-page continuation, enterprise material satisfaction, general
parsing completeness, and production acceptance remain outside this change.
Coverage remains `partial` and human review remains required.

Worker implementation is complete; no further writes are planned.
