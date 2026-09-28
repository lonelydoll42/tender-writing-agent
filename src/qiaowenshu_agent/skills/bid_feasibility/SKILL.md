---
name: bid-feasibility
version: 0.1.0
description: Determine bid feasibility from tender requirements and bidder evidence.
---

# Bid Feasibility

This Skill evaluates a bidder against decomposed tender requirements. It is a
deterministic gate for hard qualifications, similar project cases, personnel
certificates, technical parameters, and bid-bond requirements. It produces
domain-model checks and a domain-model decision; it does not ask a language
model to decide eligibility.

## Input

- `project_id`
- `requirements`, normally from `tender-decomposition`
- `bidder_profile` with bidder attributes and `materials`
- optional `options.as_of` for evaluating material validity dates

When `requirements` or `bidder_profile` is omitted, the Skill can read the
corresponding output from `context.state`. Runtime plans should prefer explicit
`$state/tender-decomposition/requirements` and `$state/<source>/...` references
when composing multiple Skills.

## Output

- `project_id`
- `decision`: `bid`, `no_bid`, or `human_review`
- serialized `FeasibilityCheck` rows with status `pass`, `fail`, `unknown`, or
  `not_applicable`
- serialized `FeasibilityDecision` blockers and warnings
- a compact `summary`

## Decision rules

- An explicit failed hard requirement produces `no_bid`.
- A missing or unverified hard requirement produces `human_review`.
- Missing evidence never becomes `pass`.
- Non-hard unknown checks are retained as warnings and do not by themselves
  change a `bid` decision.
- Requirement and material source references are copied into each check when
  available. No source reference is invented.

Compound evidence requirements can be expressed with `check_rule.rule_ast`
using `all`, `any`, `exists`, `count`, or `bundle_count`. These rules are
evaluated against structured material metadata and share the same evidence
references as the evidence-matching Skill. Conflicting valid and invalid
versions remain `unknown` until a human establishes version priority.

## Supported deterministic checks

`check_rule` may provide `attribute`, `expected`, `minimum`, `maximum`,
`contains`, `one_of`, and `evidence_types`. Evidence requirements may also be
declared through `evidence_required`. The Skill recognizes qualification,
similar-case, personnel-certificate, technical-parameter, and bid-bond
requirements from explicit rule types, categories, and common Chinese or
English titles.
