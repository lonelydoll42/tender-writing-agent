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
- `claim_verification` with claim counts and a per-run `coverage` record containing
  `status`, `scanned_sentence_count`, `recognized_claim_count`,
  `unclassified_high_risk_claim_count`, `unclassified_high_risk_snippets` and
  `recognized_patterns`
- `business_status`, `submission_allowed`, `unknowns`, `missing_materials` and `needs_human_review`
- `notices` for non-blocking delivery constraints; action-required findings remain in `warnings`
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
- Enterprise certification claims compare the complete typed standard
  identifier, such as `ISO/IEC 27001`; certificate numbers and untyped digits
  are not standards. A disagreement between `metadata.certificate_type` and
  certificate text requires review.
- Enterprise qualification evidence must identify the same bidder through an
  exact legal name or explicit registration identifier from `bidder_profile`
  and the evidence holder. Missing or conflicting identity is not support;
  subsidiaries and people named as personnel-certificate holders are not
  automatically the bidder.
- Material IDs are checked against the exact chapter context. A source only
  supports a detected claim when its content matches and its status, validity
  and available confidence checks permit use. Model-reported claims are not
  trusted; the verifier scans the rendered chapter text.
- `claim_verification.status` is `verified`, `no_claims_detected`,
  `needs_review` or `not_checked`. `coverage.status` is `complete`, `partial`
  or `not_scanned`; `complete` means the configured pattern scan ran, not that
  every natural-language fact was found. Unclassified high-risk snippets
  require review, and zero detected claims is not a factual verification pass.
- The rule scanner covers selected high-risk patterns and is not a complete
  natural-language fact verifier. Any generated document remains a draft:
  `submission_allowed` is always `false`, including when `business_status` is
  `passed`.
- The Skill does not decide bid/no-bid. Run `bid-feasibility` first.
