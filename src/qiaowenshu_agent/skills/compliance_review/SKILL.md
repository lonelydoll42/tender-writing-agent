---
name: compliance-review
version: 0.1.0
description: Run the final rule-based compliance gate over tender artifacts and draft findings.
---

# Compliance Review

This skill reports the business outcome for the explicitly supplied review
scope. It does not certify that the complete tender package is ready for final
submission.

## Input coverage

- `ledger.entries` (or the legacy `ledger_entries`) supplies requirement
  review records. Each entry must be an object with a stable
  `requirement_id`/`id`; `mandatory` must be a JSON boolean when supplied.
- When `requirements` is supplied, every requirement ID must have a ledger
  record. Missing mandatory IDs are blockers. Ledger IDs absent from the
  supplied catalog, malformed entries, unknown statuses, and non-boolean
  `mandatory` values are reported as input-integrity findings, never ignored.
- Ledger statuses `matched` and `pass` remain accepted. Unresolved statuses
  such as `unknown`, `partial`, `conflict`, `human_review`, and `unreviewed`
  cannot produce a passed business status.
- A mandatory entry marked `not_applicable` needs a non-empty
  `not_applicable_reason`; an unreasoned exemption remains unresolved.
- A signature passes only with boolean `true` or the explicit string status
  `pass`/`passed`. False/missing/invalid statuses block; null, unknown, and
  other values need review.
- `check_coverage` reports requested, completed, and pending checks plus
  requirement record coverage. An explicitly supplied but empty check section
  remains pending when another check has run. An empty input, project ID alone,
  or an empty ledger is `not_checked`, not a pass.

## Output status

- `passed`: at least one real check completed and no blocker, warning, pending
  check, or human-review finding remains. `scoped_gate_passed` is true only for
  this supplied scope.
- `failed`: one or more blockers exist.
- `needs_review`: unresolved risks, warnings, pending checks, or input-integrity
  problems require follow-up.
- `not_checked`: no actual check completed; `checked` and
  `submission_allowed` are false.

The skill returns `partial` for all non-passed business statuses so findings
remain available to the diagnostic report. Runtime owns downstream gating and
should use `business_status`, `checked`, and `summary` for its writing decision.
`submission_allowed` is always false in this prototype because this skill does
not perform a final-submission readiness check; it must not be used as the
writing gate. A scoped pass is available through `scoped_gate_passed`; this
result is not a claim that unprovided documents or requirements have been
checked.
