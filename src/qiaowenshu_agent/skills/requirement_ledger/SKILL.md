---
name: requirement-ledger
version: 0.1.0
description: Join requirements, evidence, feasibility and response coverage by stable IDs.
---

# Requirement Ledger

The ledger is the shared trace between tender requirements, bidder evidence,
feasibility checks, scoring coverage and response locations.  It does not
invent evidence or mark an unresolved mandatory item as matched.

## Input

- `requirements` and/or `scoring_items`
- optional `evidence_matches`, `feasibility_checks` and `response_map`

## Output

- one entry per stable requirement or scoring ID
- evidence IDs, response location, status and source references
- mandatory gaps and theoretical score coverage
