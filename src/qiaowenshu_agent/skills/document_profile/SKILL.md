---
name: document-profile
version: 0.1.0
description: Analyze document structure and produce routing or anatomy metadata.
---

# Document Profile

This skill decides how a document should continue through the parsing pipeline.
It may return a coarse profile, a lightweight anatomy map, or a structural shard
plan. The deterministic parser remains the owner of format conversion and chunk
generation.

## Input

- `file_path` or `file_id`
- `job_id`
- `mode`: `coarse`, `structural`, or `lightweight`
- optional `output_dir` and `settings`

## Constraints

- Do not expose object-storage paths to callers.
- Preserve the reference agent's fallback and validation behavior.
- Return a reason-bearing partial result when the optional VLM backend is absent.
