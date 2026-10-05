---
name: document-writing
version: 0.1.1
description: Write tender draft chapters and independently verify selected high-risk claims against supplied evidence.
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
- optional `confirmed_facts` and explicitly `approved_commitments`
- optional `tender_text` or section source excerpts
- optional `model`, `writing_scope`, `max_sections` and `max_tokens`

## Output

- chapter-level Markdown with requirement and scoring coverage
- context-checked evidence IDs, requirement/scoring coverage IDs and source references
- structured `verification_findings`, `claim_evidence_mapping` and `unsupported_claims`
- `business_status`, `submission_allowed`, `unknowns`, `missing_materials` and `needs_human_review`
- a generated Markdown artifact descriptor

## Safety rules

- A missing certificate, case, person, parameter or company fact is never
  invented. The draft must mark it as `[待补材料]` or `[待确认]`.
- The model may propose wording, but it cannot change numeric tender values,
  deadlines, required parameters or scoring thresholds.
- Missing evidence makes the result `partial` and requires human review; it
  does not silently become a successful factual claim.
- Coverage requirements and tender text prove what the buyer asked for, not
  that the bidder already holds a qualification, has completed past projects,
  or approved a future commitment. Unreviewed `bidder_profile` self-reports
  are not verification sources for high-risk claims.
- Material IDs are checked against the exact chapter context. A source only
  supports a detected claim when its content matches and its status, validity
  and available confidence checks permit use. Model-reported claims are not
  trusted; the verifier scans the rendered chapter text.
- The rule scanner covers selected high-risk patterns and is not a complete
  natural-language fact verifier. Any generated document remains a draft:
  `submission_allowed` is always `false`, including when `business_status` is
  `passed`.
- The Skill does not decide bid/no-bid. Run `bid-feasibility` first.
