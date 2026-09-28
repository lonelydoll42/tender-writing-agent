---
name: knowledge-retrieval
version: 0.1.0
description: Retrieve scoped evidence through the knowledge base workflow.
---

# Knowledge Retrieval

This skill owns document discovery, navigation, evidence hydration, reference
projection, and retrieval trace output. Answer synthesis remains outside this
skill so downstream agents can decide how to use evidence.

## Input

- `query`
- `namespace`
- `top_k`
- exclusion, channel, filter, and rerank policy fields

When configured, the HTTP backend supports official `ragflow_retrieval`,
deployment-specific `search_docs`, legacy `rag_chat`, and
`business_rag_chat` request styles.
The backend returns normalized evidence rows and references; answer synthesis
does not belong to this Skill.

## Constraints

- Preserve the full retrieval policy instead of dropping unsupported fields.
- Keep tenant and namespace scope in every backend call.
- Return evidence and references separately.
- Do not hard-code a knowledge-base name, customer, project, or document title.
- Do not place deployment credentials in source code, manifests, traces, or
  error messages.
