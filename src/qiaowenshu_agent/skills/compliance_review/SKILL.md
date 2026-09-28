---
name: compliance-review
version: 0.1.0
description: Run the final rule-based compliance gate over tender artifacts and draft findings.
---

# Compliance Review

This is a review gate, not a final-submission claim.  It combines the
requirement ledger, evidence status, quotation checks, consistency findings,
attachment presence and draft placeholders into `blocker`, `high_risk`,
`warning` and `passed` findings.
