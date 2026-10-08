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
at evaluation time. The hash is SHA-256 over sorted `src/**/*.py` relative
paths and each file's SHA-256 digest bytes (32 binary bytes, not hex text),
using the existing path-tab-digest-newline sequence. File line endings are
part of those bytes. Git
revision is separate provenance: `git_revision_at_run` is populated only when
the evaluation root is itself the local Git top-level.
`git_worktree_dirty` describes the whole worktree, with
`git_src_worktree_dirty` and `git_src_worktree_status` exposing source-tree
changes specifically. When running from an exported/archive tree whose parent
directory happens to be another repository, the report uses
`repository_context: archive/no_local_git_root` and a null Git revision rather
than attributing the parent repository's HEAD to the evaluated source.

### Canonical Windows Snapshot

With `core.autocrlf=true`, plain `git archive` can apply line-ending
conversion. On Windows, do not use plain `git archive` as the source of a
canonical byte snapshot. Export the staged index tree with the configuration
explicitly disabled, then use PowerShell `Expand-Archive`. The system
`C:\Windows\system32\tar.exe` may garble UTF-8 Chinese archive paths in this
Windows environment. This is an environment-specific observation, not a claim
about every tar implementation. This procedure expects the final runner and
`src` files to already be staged. `git write-tree` captures the index, not
unstaged working-tree edits.

```powershell
$repoRoot = (Resolve-Path .).Path
$tree = (git write-tree).Trim()
if ($LASTEXITCODE -ne 0 -or [string]::IsNullOrWhiteSpace($tree)) {
    throw "Could not resolve the staged index tree"
}

$runRoot = Join-Path $env:TEMP ("raw-holdout-" + [guid]::NewGuid().ToString("N"))
New-Item -ItemType Directory -Path $runRoot | Out-Null
$archivePath = Join-Path $runRoot "staged.zip"
$exportRoot = Join-Path $runRoot "export"
git -c core.autocrlf=false archive --format=zip --output="$archivePath" "$tree"
if ($LASTEXITCODE -ne 0) { throw "git archive failed" }
Expand-Archive -LiteralPath $archivePath -DestinationPath $exportRoot -ErrorAction Stop

$python = (Resolve-Path .venv\Scripts\python.exe).Path
$reportName = "public-regression-final-20261008-" + [guid]::NewGuid().ToString("N") + ".json"
$reportPath = Join-Path $repoRoot "benchmarks\raw_requirement_holdout\reports\$reportName"
if (Test-Path -LiteralPath $reportPath) {
    throw "Refusing to overwrite the existing report"
}
Push-Location $exportRoot
try {
    & $python -X utf8 scripts\run_raw_requirement_holdout_eval.py --output $reportPath
    $evaluationExitCode = $LASTEXITCODE
} finally {
    Pop-Location
}
"staged_tree=$tree"
"evaluation_exit_code=$evaluationExitCode"
```

The export root has no local `.git`, so its report is expected to contain
`repository_context: archive/no_local_git_root` and null Git revision/dirty
metadata. Do not substitute the parent repository's `HEAD` for these values.
Before accepting the report, verify its `source_tree_sha256` against the exact
staged-tree source bytes; the regression test creates a temporary repository
with `core.autocrlf=true`, exports a ZIP with the same override, and compares
each extracted Python file byte-for-byte with `git show <tree>:<path>`,
including a Chinese path.

On 2026-10-08, an independent check of baseline commit
`9d9cbe02bebf7b9a85315f7a74cae2c00ff596a9` verified all 63 `src/**/*.py`
files against their `git show 9d9cbe02bebf7b9a85315f7a74cae2c00ff596a9:<path>`
blobs. Its `source_tree_sha256` was
`207b0de46cdd303e1b9c723a5b6651e9707cb73dd3461dfbfc498fb76c39428c`. This is
a measured baseline snapshot only, not a reference to whichever commit is
currently `HEAD`; do not copy it into a later staged-tree report unless that
report's exported source files are verified to be identical.

The published staged-tree report is
[`reports/public-regression-final-20261008.json`](reports/public-regression-final-20261008.json).
It was generated at `2026-10-08T11:53:10.381492+08:00` from staged tree
`1989ef5e66e271dcf1da3962191e8b6cba5677fd`. All 63 `src/**/*.py` files were
compared byte-for-byte with blobs from that tree; `source_tree_sha256` is
`c7b6040cd13b1e2bc5245073356c5a5d14c22ed6ac156a1e426f1f1ed0b22ce4`.
The archive correctly records `repository_context=archive/no_local_git_root`
and `git_revision_at_run=null`; source attribution is by the staged-tree
verification and source hash, not a fabricated parent revision. The report's
raw, oracle, and machine-freeze checks are valid and unchanged. All 8
decompositions succeeded; finite checks are `0/8 passed`, `8 failed`,
`not_run=0`, with `18/18` emitted source references exact. This remains a
public finite regression, not production acceptance; business evidence is
`not_run/8`, and no real model, OCR, or blind holdout was used.

The existing `reports/public-regression-20261007.json` is a pre-closeout
snapshot. Keep it unchanged; generate any follow-up under a different,
previously unused path so the final report can include these provenance and
raw parser-output fields. Its source hash describes files at that report's
generation time and can differ from a later mutable worktree.
The primary `reports/public-regression-final-20261008.json` report is also
reserved and must not be overwritten. The command above chooses a fresh
unique filename and still checks that it does not exist.
Both previous public reports, `reports/public-regression-20261007.json` and
`reports/public-regression-final-20261007.json`, remain byte-for-byte unchanged.

The corpus is a public regression set. No real model, OCR, or blind-holdout
claim is made. `reports/validate_holdout_v2.py.txt` is the original validator
archived as text so it is excluded from normal Python linting. It contains
historical hardcoded assessments and source hashes, depends on its old
acceptance-tree layout, and must not be run as a current product verdict or
hash gate. The copied historical report records its own input baseline; its
contents are preserved verbatim and are not current product evidence.
