# Raw Requirement Holdout Regression Bundle

The eight synthetic TXT files and `oracle/expected-semantics.md` are copied
byte-for-byte from the original frozen bundle. Their original manifest and
bundle fingerprint still cover exactly those nine inputs (eight TXT files and
the Markdown oracle). `oracle/cases.json` is a separately hashed public
machine-readable supplement; it does not replace or rewrite the Markdown.

This finite machine oracle is a limited public regression check, not the
historical full semantic assessment and not a claim that every expected fact
is extracted. A finite check can fail on a missing or malformed required
structure, but passing it is not equivalent to complete semantic correctness.
The runner records each finite check and labels any finite-check success
explicitly.

## Finite Structure Checks

Only `requirement.check_rule.condition_logic` is traversed for structure.
`source_text`, descriptions, titles, and root-level serialized text never
satisfy a structural predicate.

- `any` requires exactly the frozen alternative branches, each matched by a
  distinct semantic leaf. `all`/`and` requires independently matched expected
  branches but may retain additional conditions. Branch order is irrelevant;
  one actual child cannot satisfy two expected branches. The AND check is a
  necessary finite subset, not a complete semantic comparison.
- Evidence leaves require an evidence operator and a material/evidence type.
- Comparison leaves require a field, supported operator, and an explicit value.
- Date-range leaves require a field, explicit start/end, and a continuity flag.
- Same-person checks require a person subject, personnel evidence, employer
  relationship evidence, and the required continuous date range inside the
  same subject subtree.
- NOT checks require the expected target predicate and exact operator/value.
- TLS threshold checks require the TLS version field, a `gte` predicate, and
  the 1.2 floor. PostgreSQL checks accept PostgreSQL version fields with a
  `gte`/at-least operator and a 14 floor.
- Manual review requires an explicit `manual_review`/`manual` node, a true
  required flag, and the expected target. Explanatory source text is not enough.

These predicates cover selected logical, subject, date, threshold, negation,
and version cases only. They do not independently assess every oracle
expectation or infer business-material compliance.

## Provenance And Scope

Every parser-emitted source reference is checked against the registered file
ID and actual Registry version token. Its page and `:pN:lN` locator must resolve
to the raw form-feed-delimited page and physical line, and its quote must equal
that line after trimming surrounding whitespace. References attached to a
requirement carrying `condition_logic` must be present on that requirement.
The citation denominator is the set of references actually emitted by the
parser; expected Markdown anchors are not fabricated into that denominator.

Expected anchors remain visible as diagnostics. Embedded sample rows, example
certificates, and the H07 AES-256-GCM statement are marked
`embedded_evidence_not_evaluated_business`; they are not mandatory parser
citation targets and do not count as registered bidder materials. Business
evidence therefore remains `not_run/8`.

H08's “采购人自有基础设施” is a semantic label, not a literal quote in the
TXT. The machine oracle records the source wording alias “采购人自有机房”.
Neither raw input nor frozen Markdown is altered.

## Running

From any checkout with the project dependencies installed, run from the
repository root:

```powershell
python scripts/run_raw_requirement_holdout_eval.py
```

By default the JSON report is written to stdout; no report file is created.
To save a report, choose a path that does not exist:

```powershell
python scripts/run_raw_requirement_holdout_eval.py --output reports/public-regression-<unique-name>.json
```

The runner refuses an existing output path before starting evaluation and
never overwrites it. In particular, the checked-in
`benchmarks/raw_requirement_holdout/reports/public-regression-20261007.json`
is an existing result and must not be used as a new output target.

Exit code `0` means all eight finite checks passed. Exit code `1` means one or
more cases failed a finite check or were `not_run`; it does not by itself mean
the runtime did not execute. Read `finite_checks_failed`, `not_run`, and each
case's `finite_check_status` in the emitted report to distinguish those
outcomes. Business evidence is independently reported as `not_run/8`.
A nonzero termination without a JSON report indicates a preflight, bundle
integrity, or runtime error prevented a final summary; do not interpret it as
eight executed failures or as eight unexecuted cases.

Each case retains the actual decomposition Skill `result.data` under
`parser_output`, including the original `requirements` and `check_rule`
objects. The adjacent `decomposition_extraction_complete` and
`decomposition_needs_human_review` fields are copied from that same result.
No oracle content is merged into `parser_output`.

Reports include `source_tree_sha256`, computed from the source files measured
at evaluation time. Git revision is separate provenance: `git_revision_at_run`
is populated only when the evaluation root is itself the local Git top-level.
`git_worktree_dirty` describes the whole worktree, with
`git_src_worktree_dirty` and `git_src_worktree_status` exposing source-tree
changes specifically. When running from an exported/archive tree whose parent
directory happens to be another repository, the report uses
`repository_context: archive/no_local_git_root` and a null Git revision rather
than attributing the parent repository's HEAD to the evaluated source.

The existing `reports/public-regression-20261007.json` is a pre-closeout
snapshot. Keep it unchanged; generate any follow-up under a different,
previously unused path so the final report can include these provenance and
raw parser-output fields. Its source hash describes files at that report's
generation time and can differ from a later mutable worktree.

The corpus is a public regression set. No real model, OCR, or blind-holdout
claim is made. `reports/validate_holdout_v2.py.txt` is the original validator
archived as text so it is excluded from normal Python linting. It contains
historical hardcoded assessments and source hashes, depends on its old
acceptance-tree layout, and must not be run as a current product verdict or
hash gate. The copied historical report records its own input baseline; its
contents are preserved verbatim and are not current product evidence.
