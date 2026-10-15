# Case-13 Financial Context Follow-up

Classification: public regression and reviewer-public probes; not unseen.
Baseline: `57f1a8fec8718cadab31d31822ae593f41ac2d4b`.

## Change

Added a finite `financial_context_scope` and directed `contextual_parent` from
the threshold ATOM to the listed-revenue ATOM. The original `AND(A1,A2)` is
preserved; no three-member logical operator was added. The reference and every
candidate evidence set retain source references from the statement and
threshold ends.

Confirmation is intentionally conservative. It requires the complete numbered
financial-statement sentence, the complete affirmative RMB lower-bound
sentence on the next substantive block on the same page, valid unique source
identity/version/coordinates/block IDs, exactly one matching statement and
threshold ATOM, and exactly two occurrences of `营业收入` across the entire
structure. Extra or unknown same-name mentions make the financial reference
and scope review-only. This implementation does not generalize financial
reasoning or other anaphora.

## Verification

- Red baseline before the product change: `pytest-baseline-red-20261015.xml`
  records 15 failures and 5 passes in the initial 20-test suite.
- Green: `59 passed` across the 27 new financial-context tests and the 32
  existing finite-copy attribute tests, using `.qiaowenshu` as pytest's
  temporary root.
- Ruff lint passed for `document_relations.py` and
  `test_document_relations_financial_context.py`.
- Ruff format check passed for the new test file.
- New cases cover the 15 frozen contract cases, six reviewer-public probes,
  source identity/version/coordinate and duplicate-block-ID tampering,
  multiple same-name sources including a distant prior owner field, scope/node
  consistency, directed parent targets, preserved `AND(A1,A2)`, and source
  reference validation.

## Not Run / Unsupported

The independent RegistryRuntime capture, mutation checker, full test suite,
and 14-case frozen rescore are left to the main reviewer. This is not a
production or unseen-data acceptance. Case-07/12, broader financial language,
non-Arabic or alternate statement forms, subject/time inference, bidder
material verification, and business-gate changes are out of scope.
