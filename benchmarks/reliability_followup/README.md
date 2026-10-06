# Reliability Follow-up Cases

This benchmark contains fixed service-boundary regression cases for the review
findings. It is not a general tender parser or factuality certification.

## Files

- `cases.json` maps case IDs to fixture keys. It contains no expected labels.
- `fixtures/writing.json` contains structured writing inputs and fixed simulated
  model outputs.
- `fixtures/runtime.json` contains compliance-review inputs, writing inputs,
  source/version/scope variations, and fixed simulated model outputs.
- `oracle.json` contains the positive/negative labels and acceptance criteria.

The runner executes the fixtures before loading `oracle.json`. It rejects
oracle-only keys if found in the evaluated request. The oracle is not registered
as a source file and is never passed into a Skill, Runtime, or mock model.
Fixture identities and evidence are synthetic; they are test data, not real
companies or certificates.

## Cases

Writing has 6 positive and 12 negative cases:

| Case | Label | Purpose |
| --- | --- | --- |
| `W-NEG-ISO-NUMBER-COLLISION` | negative | ISO9001 plus certificate number `CN27001-2026` must not satisfy ISO/IEC 27001 |
| `W-NEG-BIDDER-SUBJECT-MISMATCH` | negative | Certificate belongs to a different bidder |
| `W-NEG-BIDDER-SUBJECT-UNKNOWN` | negative | Certificate holder is absent or unknown |
| `W-NEG-BIDDER-SUBJECT-CONFLICT` | negative | Certificate title, body, and metadata disagree on holder |
| `W-NEG-UNSUPPORTED-GOVERNMENT-CASES` | negative | Unsupported “三十项大型政务项目” claim must be scanned and reviewed |
| `W-NEG-CMMI-LEVEL-MISMATCH` | negative | CMMI 3 evidence must not satisfy a CMMI 5 claim; this is a level mismatch, not a certificate-number collision |
| `W-NEG-CMMI-CERT-NUMBER-COLLISION` | negative | CMMI 5 standard/body plus certificate number `CN-CMMI-3-2026` must not support a CMMI 3 claim |
| `W-NEG-ISO-METADATA-BODY-CONFLICT` | negative | ISO metadata cannot override a contradictory certificate body |
| `W-NEG-HOLDER-METADATA-BODY-CONFLICT` | negative | Holder metadata cannot override a contradictory certificate body |
| `W-NEG-SAME-NAME-DIFFERENT-CREDIT-CODE` | negative | Same company name with a different unified social credit code is not the same subject |
| `W-NEG-CROSS-SUBJECT-CASE-COUNT` | negative | Evidence stating that Beta Company handled the same Chinese project count cannot support Alpha's first-person claim |
| `W-NEG-CROSS-SUBJECT-CONTRACT-AMOUNT` | negative | Evidence explicitly attributing the same historical contract amount to Beta cannot support Alpha's claim |
| `W-POS-SAME-SUBJECT-ISO27001` | positive | Matching ISO standard, holder name, and company identifier support a valid claim |
| `W-POS-SAME-SUBJECT-CMMI3` | positive | Matching CMMI 3 standard, body, and holder support a valid claim even when the certificate number contains `CMMI-3` |
| `W-POS-EVIDENCED-CHINESE-CASE-COUNT` | positive | Evidence supports the Chinese-number project count |
| `W-POS-SAME-SUBJECT-CONTRACT-AMOUNT` | positive | The same 135万元 claim is supported when the evidence body explicitly attributes it to the bidder |
| `W-POS-TENDER-REQUIREMENT-PARAPHRASE` | positive | Correct tender requirement paraphrase is accepted only as a tender-side fact |
| `W-POS-BENIGN-SECTION` | positive | Benign prose with no high-risk enterprise fact should not be blocked |

Runtime has 2 positive and 7 negative cases:

| Case | Label | Purpose |
| --- | --- | --- |
| `R-NEG-CROSS-PROJECT` | negative | Project A review cannot authorize project B writing |
| `R-NEG-REQUIREMENT-CONTENT-CHANGED` | negative | Matching IDs do not authorize changed requirement content |
| `R-NEG-REQUIREMENT-SCORING-ID-COLLISION` | negative | A requirement and a distinct 100-point scoring item sharing `SAME` are different review targets; a ledger row matching only `SAME` as `item_type=requirement` does not review the scoring item; writer must be refused with `requirement_scoring_id_collision` |
| `R-NEG-SOURCE-VERSION-CHANGED` | negative | Changed source version cannot reuse the old review |
| `R-NEG-WRITING-SCOPE-EXPANDED` | negative | Writing cannot exceed the reviewed section scope |
| `R-NEG-FORGED-APPROVAL` | negative | Client-supplied approval flags cannot replace a trusted review |
| `R-NEG-INVALID-WRITING-SCOPE` | negative | An unknown non-empty selector in both review and writer inputs cannot fall back to all sections; requires `writing_scope_unresolvable` and zero writer/model calls |
| `R-POS-MATCHED-SCOPE` | positive | Matching project, source, requirements, and writing scope permits one actual writer call |
| `R-POS-SAFE-SUBSET` | positive | A requested section that is a subset of the approved scope permits one actual writer call |

The Runtime oracle checks the number of actual `DocumentWritingSkill.execute`
invocations, not only the final run status. Any writer invocation in a negative
case is a false release, even if the run later ends in `needs_review`. Positive
cases require a completed run with `business_status=passed`, one actual writer
invocation, one mock-model call, and an authorized writer-step
`runtime_scope_authorization` whose `match_kind` matches the oracle. A
`submission_allowed=false` draft is not itself an authorization failure, but
business warnings still prevent a positive case from counting as passed.

## Metrics

The report contains separate metrics for `writing` and `runtime`:

- `correct_pass_rate`: correct passes divided by all fixed positive cases.
- `false_block_rate`: blocked, failed, `needs_review`, or `not_checked` positive
  cases divided by all fixed positive cases.
- `false_release_count` and `false_release_rate`: negative cases improperly
  passed; for Runtime, any actual writer call counts as a release.
- `not_run_count` and `inconclusive_count` are explicit. Both remain in the
  fixed-polarity rate denominator and are not silently excluded.
- Runtime captures actual gate/scope rejection reasons from result fields,
  actual writer invocations, and mock-model calls.
- Writing captures `claim_verification.coverage`. A missing field is
  `not_reported`; a missed claim or unreported coverage is not treated as
  successful scanning.

The mock LLM only returns the fixture output under test. It does not answer
oracle questions or measure a real model. No real model or OCR is called.

The 27-case follow-up runner does not process PDFs. Its
`raw_file_baseline` field in `reliability-followup-final-2.json` remains a
historical reference (`not_retested_in_this_followup`), not a measurement from
the current raw-file run.

The primary 332-test suite included
`tests/evals/test_raw_file_benchmark.py`, which calls `run_raw_file_eval`.
Additionally, the raw-file evaluation was run separately and saved to
`.qiaowenshu/acceptance/raw-file-followup-acceptance.json`. It completed with
Poppler available:

| Raw-file metric | Result |
| --- | ---: |
| Requirement text coverage | 4/10; 6 omissions |
| Amount normalization | 6/6 |
| Score maximum | 2/2 |
| Hard false releases | 0/7; `inconclusive=0` |

The 4/10 measures text coverage of fixed constraint groups, not whether
requirements became correct, complete executable rules. The six omissions
remain unresolved and unaccepted. The 0/7 result reflects conservative gate
blocking, not qualification accuracy. The report's scripted OCR returned
fixed text at confidence `0.61` in one call; this checks warning/provenance
handling, not real OCR accuracy.

## Frozen Final-2 Result

The independent acceptance run is recorded in
`.qiaowenshu/acceptance/reliability-followup-final-2.json`. This is a limited
evaluation of the fixed cases, not general factuality, parser completeness, or
production reliability certification.

| Domain | Cases | Correct positive passes | False blocks | False releases | `not_run` | `inconclusive` |
| --- | ---: | ---: | ---: | ---: | ---: | ---: |
| Writing | 18 (6 positive, 12 negative) | 6/6 | 0/6 | 0/12 | 0 | 0 |
| Runtime | 9 (2 positive, 7 negative) | 2/2 | 0/2 | 0/7 | 0 | 0 |

The seven Runtime negatives had zero writer/model calls; each of the two
positives had one writer call and one model call. The full suite recorded
`332 passed` with one pre-existing Starlette deprecation warning; Ruff and
`git diff --check` passed. No real model or OCR was called.

Additional probes outside the 27-case denominator required review for
conflicting company registration identifiers and rejected invalid or
unresolvable scopes before model calls; matching identifiers and valid scope
selectors passed. Natural-language quantity and amount scanning uses only
finite patterns and extraction rules, not exhaustive semantic coverage.

The earlier 23-case report
`.qiaowenshu/acceptance/reliability-followup-final.json` and the pre-fix report
`.qiaowenshu/acceptance/reliability-followup-expanded-before-fix.json` remain
preserved as historical records. The latter recorded three false releases
before the fixes and is not a post-fix result.

The raw-file rerun above is separate from the 27-case follow-up metrics. This
evaluation does not certify production authorization, Word delivery,
real-model behavior, real OCR accuracy, or end-to-end tender submission. See
`docs/reliability_acceptance.md` for the full boundaries.

Run:

```powershell
.venv\Scripts\python.exe -m pytest tests\evals\test_reliability_followup.py -q --basetemp=.pytest-basetemp-reliability-followup
.venv\Scripts\python.exe scripts\run_reliability_followup_eval.py
```

The runner prints JSON to stdout by default. It writes a report only when an
explicit `--output` path is supplied, and refuses to overwrite an existing
file.
