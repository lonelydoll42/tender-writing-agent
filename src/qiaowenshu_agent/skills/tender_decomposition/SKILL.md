---
name: tender-decomposition
version: 0.1.0
description: Convert tender content into atomic requirements and checklists.
---

# Tender Decomposition

This Skill turns page-aware tender content into auditable, atomic requirements.
It separates disqualification, qualification, compliance, technical,
commercial, scoring, format, and evidence requirements.

## Input

- `project_id`
- optional `profile` and `sections`
- `requirements` and `scoring_items` when supplied by a parser backend

## Constraints

- Keep requirement IDs stable across reruns when the source version is stable.
- Preserve source references for every requirement.
- Do not decide bidder eligibility; that belongs to `bid-feasibility`.
