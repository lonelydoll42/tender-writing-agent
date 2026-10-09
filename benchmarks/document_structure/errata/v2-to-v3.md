# Public Oracle and Grader Errata: v2 to v3

## Preserved V2 History

V2 was frozen and used by the initial debug evaluation. Its oracle SHA-256 is `007fbd2575ff99ab519e5ab84645f5fd47ffae5a3206ad778cec1be144104f11`, its bundle fingerprint is `7f76f29b11eb0f194389599fdf689ef3064d1bac1ad3b8682208e534d8ec5314`, and its report remains `reports/initial-debug-worktree-v5-20261009.json`. Neither v2 artifact nor that report is overwritten.

## Correction

V2 accidentally omitted the v1 `parent=null` and `section=null` expectations for H01 p2l1, and its grader skipped those relations whenever a block had a `needs_review` marker. That was an unsupported relaxation: a global continuation candidate records uncertainty; it does not prove either relationship. V3 restores both null expectations and requires the current block's `parent_block_id` and `section_block_id` to be exactly null while independently validating the ordered global continuation candidate and its real source references.

This correction does not change the v2 visual-classification policy. Numbered text remains `list_item`; the unnumbered first line remains `paragraph` with an ambiguous, source-located title candidate; short level-one numbered items remain ambiguous heading candidates. No fixture bytes or v1/v2 files change.

The grader also applies structure-wide reference integrity even where the oracle leaves a relationship unspecified: every non-empty parent and section ID must resolve to exactly one physical block in the same structure; parents cannot self-reference or form cycles. Tests cover dangling IDs, self-parenting, parent cycles, and a valid-ID parent/section forced onto the uncertain H01 block.

## V3 Freeze

V3 is frozen in `freeze-manifest-v3.json`, with oracle SHA-256 `60129bd55703390027c6cc7f744c2bc2f98785e9f2e2e5d7b8fc612b8bc3a5ee` and bundle fingerprint `e03d75abad901766cbb7b70985bcea35c2cfa6d2a2299138d0008cd50dc6df4f`. The public raw inputs remain byte-identical to the v1/v2 fixture hashes.
