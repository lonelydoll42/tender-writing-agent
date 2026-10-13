# Current Product Baseline Contract

Freeze before implementation, 2026-10-13. This batch does not change product
parsing, frozen graders, frozen inputs, or historical reports.

## Product Identity And Capture

1. Target product commit is
   `20e79af22ef1666dc862234d3f7c555c82eb90e0`.
2. Export the target commit with `core.autocrlf=false`. Verify all 65 product
   source files against their Git blobs before invoking the product.
3. Expected exact source-tree SHA-256 is
   `51b1b18212c84ce50e8606106b96e4b5d5b548fb68bab491669cf08cf4e1ea34`.
4. Use the unchanged 1.0.3 runner and v2 bundle to capture all fourteen cases
   through the real Registry/Runtime. Save original graphs, registered source
   contexts, runtime records, and execution states. Never substitute an old
   product report or a synthesized graph.
5. The existing v2 input, oracle, and bundle fingerprint remain authoritative.
   Product execution failures, scoring failures, and not-run cases are distinct.

## Same-Capture Scoring

1. Independently score the exact same new capture using unchanged 1.0.3 and
   1.0.4 entry points. Preserve graph/context/runtime fingerprints and case IDs.
2. Frozen 1.0.5 historical `rescore_report` is bound to its original report hash.
   Do not edit or monkey-patch that guard, the overlay, its rules, or old files.
3. A new adapter may invoke frozen 1.0.5 `score_case` for the two originally
   listed cases using the original frozen evidence-contract payloads. Other
   cases retain frozen 1.0.4 rules. No new oracle or contract group is added.
4. Before scoring, pin all existing grader/rule/overlay hashes, verify the
   requested new product-report hash, source-tree hash, v2 fingerprint, every
   raw input/page, exact case IDs, source identities/versions, and replay
   material using existing structured validators. Verify contract members,
   operators, and raw evidence against the frozen oracle and current registered
   contexts. Unsupported, malformed, or ambiguous inputs fail closed.
5. The new adapter is an invocation/validation layer, not a new grading version.
   Record its own hash independently of the frozen 1.0.5 scorer and distinguish
   live product capture from offline scoring. Output paths are create-only.
6. Tests must cover valid scoring plus changed report hash, wrong source tree,
   duplicate/missing cases, changed input/pages/identity/version, changed
   frozen contracts, missing authorization, and existing output paths.

## Isolation Preflight

1. Only a clearly labelled nonsensitive public canary may be used before an
   enforced reviewer/developer access boundary exists.
2. Record the main reviewer and developer execution identities without storing
   credentials. Attempt direct canary reading with the developer's actual
   tools; a successful read proves this local arrangement is not isolated.
3. A new path, worktree, process, different prompt, or an untested remote host
   is not a credential boundary. Available developer tools/credentials and
   shared conversation/log access must be considered before declaring denial.
4. Do not modify host security policy, create accounts, expose credentials,
   provision paid infrastructure, or repurpose unrelated servers in this batch.
5. Freeze new unseen inputs/answers only after access is demonstrably denied
   under the actual developer capabilities. Otherwise retain new unseen files
   at zero and unseen evaluation at not_run; report the missing prerequisite.

## Acceptance And Publication

Keep worker output and independent main-reviewer replay separate. Compare
scoring summaries and exact replay material within the new capture; historical
10/14 remains historical, not a proxy for the current baseline.

Protect all existing files except the explicitly allowed documentation,
publication index, and path-specific attributes. Preserve every intermediate
failure. No enterprise materials or real model service are run. Current
fourteen-case scores do not establish arbitrary-document completeness,
business false-pass/block rates, or production acceptance. Old public 0/8 and
uv.lock remain separate.
