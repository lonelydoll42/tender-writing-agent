---
name: document-writing
version: 0.1.0
description: Write evidence-grounded tender chapters from parsed tender requirements and bidder materials.
---

# Document Writing

This Skill generates a reviewable tender draft one chapter at a time. It
consumes the outputs of tender intake, decomposition, scoring strategy and
evidence matching, then calls the injected Qwen LLM service for prose.

## Input

- `project_id` and optional `tender_profile`
- parsed `sections`, or enough tender context to derive a standard outline
- `requirements` and `scoring_items`
- optional `bidder_profile`, `materials` and `evidence_matches`
- optional `tender_text` or section source excerpts
- optional `model`, `writing_scope`, `max_sections` and `max_tokens`

## Output

- chapter-level Markdown with requirement and scoring coverage
- evidence IDs and source references carried into each chapter
- `unknowns`, `missing_materials` and `needs_human_review`
- a generated Markdown artifact descriptor

## Safety rules

- A missing certificate, case, person, parameter or company fact is never
  invented. The draft must mark it as `[待补材料]` or `[待确认]`.
- The model may propose wording, but it cannot change numeric tender values,
  deadlines, required parameters or scoring thresholds.
- Missing evidence makes the result `partial` and requires human review; it
  does not silently become a successful factual claim.
- The Skill does not decide bid/no-bid. Run `bid-feasibility` first.
