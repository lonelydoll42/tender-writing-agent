---
name: tender-intake
version: 0.1.0
description: Build a page-aware structured profile from tender documents.
---

# Tender Intake

This Skill owns the first structured representation of a tender package. It
does not decide whether the bidder should bid and it does not write the bid.
The parser backend must preserve document, page, section, and artifact
references so downstream requirements can be audited.

## Input

- `project_id`
- `file_ids` or `file_id`
- optional `business_scene` and parser `options`

## Output

- `profile`
- page-aware `sections` and `pages`
- parser `artifacts` and `warnings`

## Constraints

- Every extracted conclusion should retain source references when available.
- Low-confidence or missing fields are warnings, not invented values.
- Parsing and OCR belong to the injected backend.
