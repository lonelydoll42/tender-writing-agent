---
name: quotation-check
version: 0.1.0
description: Validate tender quotation arithmetic, amount formats and price rules.
---

# Quotation Check

All arithmetic is performed with `Decimal`.  The Skill checks line-item sums,
quantity times unit price, repeated totals, upper limits and optional Chinese
uppercase amounts.  A missing input is `unknown`; it is never silently treated
as a passed price check.
