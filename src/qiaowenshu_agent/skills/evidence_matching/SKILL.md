---
name: evidence-matching
version: 0.1.0
description: Match tender requirements and scoring items to bidder evidence materials.
---

# Evidence Matching

This Skill matches each qualification or scoring item to the most relevant
bidder evidence material. It is deliberately deterministic: evidence type,
keywords, semantic tags, validity metadata, and explicit requirement rules are
all reported through the resulting `EvidenceMatch` reason.

## Input

- `requirements`: `TenderRequirement` objects or dictionaries
- `scoring_items`: `ScoringItem` objects or dictionaries
- `materials` or `evidence_materials`: `EvidenceMaterial` objects or dictionaries
- optional `project_id`, `as_of`, and `options`

The dictionary form accepts the aliases already used by the domain models,
such as `id`, `name`, `required_evidence`, `type`, and `text`. A single object
is accepted for convenience. Materials can also be read from
`bidder_profile.materials`.

## Output

- `matches`: one serialized `EvidenceMatch` per requirement or scoring item
- `summary`: counts and weighted coverage information
- `warnings`

`source_references` on a match contains the requirement references followed by
the selected material references. A missing match has no material ID and only
retains the requirement references.

For compound evidence requirements, `check_rule.rule_ast` may use the
deterministic operators `all`, `any`, `exists`, `count`, and `bundle_count`.
`bundle_count` groups materials by a metadata field such as `case_id` and
requires every declared evidence type in the same group. A valid and invalid
version without an explicit priority is reported as `conflict`.

## Status rules

- `matched`: all explicit evidence units are covered by usable materials, or a
  non-explicit target has a strong type/keyword/tag match
- `partial`: a usable material supports only part of the evidence requirement
- `missing`: no relevant material was supplied or found
- `invalid`: a relevant material exists but is expired, revoked, unverified, or
  otherwise fails an explicit validity rule

An expired or invalid material cannot produce `matched`. Validity is checked
against `as_of` (the current date by default). `check_rule` may require an
expiry date with `validity_required` or `require_valid_until`, or require a
minimum number of remaining days with `min_valid_days`.

This Skill does not invent certificates, project cases, or other proof. It
does not decide the bidder's final bid/no-bid conclusion; that belongs to the
feasibility Skill.
