# Agent Architecture

## Runtime boundary

`AgentRuntime` owns the execution envelope:

- request and tenant context
- deterministic or LLM-backed planning
- step and token budgets
- execution events
- reason-bearing results
- trace serialization
- durable run checkpoints and recovery

The runtime does not import document parsers, database models, Celery tasks, or
knowledge-base implementations.

Declared multi-Skill plans can pass data explicitly with `$state/<skill>/<path>`
and `$request/<path>` references. The runtime resolves these references before
invocation and rejects unavailable paths, so a downstream Skill never silently
receives incomplete input.

## Skill boundary

Each Skill owns one business capability and exposes:

1. `SkillManifest`
2. typed input validation
3. an injected backend port
4. a typed `SkillResult`
5. `SKILL.md` and `manifest.json`

The backend port is the migration seam. Existing implementations can be wrapped
without moving them first.

## Tender workflow

The tender workflow is intentionally split into independent Skills so that a
project can persist and review each intermediate artifact:

1. `ProjectFileRegistry` registers project files, checksums, versions and parse status
   through the `Store` port. `InMemoryStore` is used for tests and
   `SQLiteStore` is used by the local service.
2. `document-preprocess` creates parse artifacts; `tender-intake` creates a
   page-aware tender profile.
3. `tender-decomposition` creates atomic requirements and scoring items.
4. `bidder-material-intake` builds evidence materials and bidder attributes from
   enterprise files.
5. `bid-feasibility` evaluates hard qualification and compliance checks against
   a bidder profile.
6. `scoring-strategy` calculates score totals, coverage, evidence gaps, and
   deterministic work priorities.
7. `evidence-matching` links requirements to enterprise evidence materials.
8. `requirement-ledger` joins each stable requirement ID to evidence, feasibility
   status and response location.
9. `consistency-review` and `quotation-check` run deterministic cross-document
   and arithmetic checks.
10. `compliance-review` acts as the final review gate for the current artifact set.
11. `document-writing` uses the Qwen LLM port to write reviewable chapters from
   those structured artifacts. It returns Markdown and never treats missing
   evidence as a company fact.

The registry stores file metadata separately from bytes and creates a parsed
artifact with source file ID, version, checksum, page count, text and warnings.
Artifacts also record their schema version, source file versions, dependency IDs,
creating run, content hash and validity status. When a superseding file version
is registered, stale status propagates through dependent artifacts without
deleting historical results. The runtime checkpoints its request, plan, state,
steps, budget and events after each step; a new process can resume the stored
run at its next unfinished step. `HumanReviewTask` is persisted alongside the
same project state so a manual decision remains auditable.

The host can replace `SQLiteStore` with a PostgreSQL/object-storage adapter
without changing Skills. Scanned PDFs with no extracted text remain explicitly
OCR-required.

For a submitted bid file, `document-preprocess` can call the reference service
with `business_scene=bid_rejection_check` and `file_role=bid_file`. That service
produces a standardized `parse_ready_file_id`; it does not produce the final
rejection verdict. The later evaluator must consume the normalized file and
return structured findings with source references.

`TenderRequirement`, `ScoringItem`, `EvidenceMaterial`, `FeasibilityCheck`,
`FeasibilityDecision`, and `EvidenceMatch` are persistence-independent domain
models. A parser or LLM may propose structured fields, but it cannot turn an
unproven requirement into a passing check or fabricate an evidence match.
Missing, invalid, or ambiguous source material remains visible to the caller
for human review.

## Qwen LLM boundary

`llm/config.py` owns environment parsing and per-purpose model routing;
`llm/client.py` is the only OpenAI-compatible HTTP adapter. A Skill can receive
the client through `SkillContext.services["llm"]` or the default registry. The
configured base URL should be the provider's `/compatible-mode/v1` endpoint;
the provider's `/api/v1` DashScope endpoint is a different protocol.
default route is deliberately conservative:

| Purpose | Default model | Reason |
| --- | --- | --- |
| OCR/image understanding | `qwen-vl-ocr` | visual pages and tables |
| long tender intake | `qwen-long` | long source context |
| document profile | `qwen3.7-flash` | lightweight structure analysis |
| requirement extraction | `qwen3.7-plus` | structured recall/cost balance |
| scoring strategy | `qwen3.8-max` | complex scoring decomposition |
| tender drafting | `qwen3.8-max` | high-stakes prose and consistency |
| commercial drafting | `qwen3.7-plus` | constrained response language |
| compliance review | `qwen3.8-max` | conservative second-pass review |
| hard feasibility/evidence status | rule engine | model must not decide proof |

Every route can be overridden with `QIAOWENSHU_LLM_MODEL_<PURPOSE>` or the
request-level `model`. The API key is never included in public diagnostics or
remote error messages. The reference preprocessing service uses compatible
aliases such as `LLM_API_BASE_URL`, `LLM_MODEL` and
`LLM_BID_INTELLIGENT_WRITE_MODEL`.

## Reference mapping

| New Skill | Reference implementation |
| --- | --- |
| `document-profile` | `knowleagev1.0/apps/worker/app/services/document_agent` |
| `knowledge-retrieval` | `knowleagev1.0/packages/shared-python/shared/services/retrieval/agentic` and `workflow` |
| `document-preprocess` | `document-preprocess-service/app/services/document_processor.py` and its API |
| `document-writing` | `BidCheckService_v3` `tech_bid/generate_bid` and `business_bid/business_writing/write_chapter` patterns |
| legacy tool compatibility | `LingQiao/libs/lingqiao-server/lingqiao/server/agent/tools_factory` |
| tender parsing and layout extraction | Docling and Unstructured |
| tender workflow orchestration | Bharat Procure AI workflow pattern; LangGraph persistence patterns |
| deterministic rule evaluation | Microsoft RulesEngine concepts |

The deterministic parser and preprocessing workers remain infrastructure. The
Agent should decide which capability to invoke and how to recover, not replace
every parser function with an LLM tool.

## Knowledge-base adapter

`skills/knowledge_retrieval/ragflow_backend.py` is the deployment boundary for
the knowledge base. `RagFlowRetrievalBackend` converts the Skill policy to an
HTTP request and normalizes official `data.chunks` plus common
`docs`/`sources`/`references` response shapes into evidence rows. The official
`/api/v1/retrieval` style and the reference service's `/knowledge_base/search_docs`
style are separate configurations; legacy chat and business wrapper styles are
explicit compatibility modes.

The backend is created from `QIAOWENSHU_KB_*` environment variables only when a
base URL is present. The application can still inject a custom backend through
`build_default_registry(knowledge_retrieval_backend=...)`, which is the
preferred path when the deployed API contract is known precisely.
