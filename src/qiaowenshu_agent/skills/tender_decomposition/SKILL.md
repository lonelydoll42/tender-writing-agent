---
name: tender-decomposition
version: 0.1.0
description: Convert tender content into atomic requirements and checklists.
---

# Tender Decomposition

This Skill turns page-aware tender content into auditable, atomic requirements.
It separates disqualification, qualification, compliance, technical,
commercial, scoring, format, and evidence requirements.
It also builds a separate, partial document-relations graph from valid
document structures. Relation status does not determine bidder eligibility or
authorize writing.

## Input

- `project_id`
- optional `profile` and `sections`
- `requirements` and `scoring_items` when supplied by a parser backend
- optional `document_structures`

## Output

- `document_relations`: one independently built graph per valid document and
  source version
- `relation_analysis`: execution and coverage status, document count, and
  human-review requirement. It distinguishes skipped structures from executed
  graphs whose source references remain unresolved. With no raw document
  structures, it remains `not_run` and records a diagnostic without raising a
  relation-level review flag; invalid or incomplete raw structures still
  require review.

## Constraints

- Keep requirement IDs stable across reruns when the source version is stable.
- Preserve source references for every requirement.
- Do not decide bidder eligibility; that belongs to `bid-feasibility`.
- Physical parent hints do not establish condition scope. Preserve uncertain
  relations as candidates and require human review; do not use the graph as a
  writing authorization.
- When local parsing has warnings or receives correction/clarification files,
  retain the warning and request human review instead of inferring precedence.
