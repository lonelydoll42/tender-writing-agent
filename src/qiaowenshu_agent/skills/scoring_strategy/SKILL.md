---
name: scoring-strategy
version: 0.1.0
description: Decompose scoring criteria and produce an auditable bid priority strategy.
---

# Scoring Strategy

This Skill converts structured or semi-structured scoring criteria into
auditable scoring items. It calculates the total available points, evidence
coverage, evidence gaps, and a deterministic writing priority.

## Input

- `project_id`
- `scoring_items`, or a `scoring_table`/`scoring_criteria` value
- optional `scoring_text` for simple line or pipe-delimited tables
- optional `requirements` from `tender-decomposition`
- optional `evidence_materials` or upstream `evidence_matches`

An injected backend may extract candidate rows from a document. The backend
does not provide the final score or priority; its output is normalized and
calculated again by this Skill.

## Output

- normalized `scoring_items` with score conditions, evidence requirements,
  source references, subjectivity classification, evidence status, and priority
- `summary` containing total score, objective evidence score, price-score
  availability, subjective-score availability, and uncovered objective score
- `evidence_matches`, `evidence_gaps`, and a score-ordered `priorities` list

`objective_proven_score` (and its compatibility alias `covered_score`) means
only the maximum objective score whose evidence obligations are currently
satisfied. It is an evidence-backed ceiling, not the bidder's actual score.
Price and subjective scores are reported separately and are not included in
that ceiling. This Skill never accepts a model-generated or free-text awarded
score as the final score.

## Deterministic rules

- `total_score` is the sum of normalized item `max_score` values.
- Items are classified as `objective`, `price`, `subjective`, or `unknown`.
- An item without evidence obligations is considered evidence-complete for
  objective coverage, but a subjective item still does not become an awarded
  score.
- A required evidence entry counts as covered only when its status is
  `matched`; `partial`, `missing`, `invalid`, and `conflict` remain gaps.
- `objective_proven_score` is the covered objective score; price and subjective
  maxima are exposed as `price_max_score` and `subjective_max_score`.
- `price_available` and `subjective_available` remain false unless an upstream
  evaluator explicitly supplies a result. No price formula or subjective
  review is invented from bidder materials.
- `score_coverage_rate` is objective evidence score divided by total score;
  `objective_score_coverage_rate` divides by objective maximum.
- `evidence_coverage_rate` is matched evidence entries divided by all required
  evidence entries. With no evidence obligations it is `1.0`.
- Priority uses item score share and subjective space. The deterministic
  priority score is `score_share * (1 + 0.35 * subjective_space_weight)`, where
  high, medium, low, and unknown subjective space have weights `1.0`, `0.5`,
  `0.0`, and `0.25`. Items are sorted by this score, then max score, then ID.
  `P1`, `P2`, and `P3` are assigned from score bands at 75% and 40% of the
  highest priority score.

## Constraints

- Preserve page, section, quote, and document references when available.
- Do not turn criteria prose into an awarded score.
- Do not decide whether the bidder is eligible; that belongs to
  `bid-feasibility`.
- Keep missing or ambiguous evidence visible instead of silently marking it as
  covered.
