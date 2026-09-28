---
name: document-preprocess
version: 0.1.0
description: Normalize files and create parse-ready document artifacts.
---

# Document Preprocess

This skill calls the standalone preprocessing service. It owns the task request
contract but not storage paths, tenant authorization, file conversion internals,
or Celery implementation details.

## Input

- `file_id`
- `business_scene`
- optional `file_role`, `options`, and `force`

For a submitted bid file that will later be checked for rejection risks, use
`business_scene: bid_rejection_check` and `file_role: bid_file`. The referenced
preprocessing service accepts this scene and returns a `parse_ready_file_id`.

## Constraints

- Callers only exchange `file_id` values, never object-storage paths.
- Preserve tenant and gateway authorization headers from the host application.
- Keep preprocessing status and error codes in the result.
- `bid_rejection_check` only standardizes the submitted file. It does not by
  itself produce a rejection verdict, missing-item list, or qualification
  decision; those require a downstream evaluator.
