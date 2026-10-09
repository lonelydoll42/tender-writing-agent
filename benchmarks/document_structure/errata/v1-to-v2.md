# Public Oracle Errata: v1 to v2

## Reason for Correction

The source corpus contains extracted TXT, not PDF layout, font metadata, or an outline tree. A decimal prefix identifies numbering syntax, but it does not prove that a complete numbered clause is displayed as a typographic heading. The v1 oracle labeled numbered clause sentences as `heading` and the first unnumbered line as `title`; those classifications asserted visual facts unavailable from the evidence. This correction is based on the input modality and structure contract, not on matching product output.

## V2 Contract

- Every explicitly numbered block is `kind=list_item`, including complete numbered clause sentences.
- Numbering, parent links, and section membership are evaluated independently. A decimal-numbered block is its own section container; this records structural membership, not displayed heading status.
- A short level-one numbered item may carry an ambiguous `heading_candidate`. The oracle expresses semantic intent, not a required output object shape: the current interface represents this as `heading_candidate=true` plus `kind_ambiguity=decimal_heading_or_numbered_clause`, with exact source references on that physical block. A bare boolean without the ambiguity marker and valid original-block references is insufficient.
- An unnumbered first line remains a paragraph. Where the oracle marks a possible title, the `title_candidate` must be `ambiguous` and carry source references that resolve to that exact physical block.
- The cross-page continuation remains uncertain and separate. The runner requires the exact ordered global `continuation_candidates.source_block_ids`, `needs_review` status, and real source references to both blocks. The v2 draft omitted H01 p2l1's v1 `parent=null` and `section=null` assertions; this was an oracle/grader defect, not an approved visual-classification correction. V3 restores both null assertions and independently rejects explicit parent/section relationships on the uncertain block.
- The normalization map only accepts identity runs and one normalized space mapped to a complete source whitespace run. A run mixing text and whitespace is not accepted.
- Table row grouping and exact cell offsets are evaluated. `table_group_id` identifies the first physical row block and `table_row_index` is one-based.

## Changed Oracle Fields

The intended v1-to-v2 correction is limited to unsupported visual classification: the first unnumbered line changes from `title` to `paragraph` and receives an ambiguous `title_candidate` at the exact locator; numbered blocks previously labeled `heading` become `list_item`, and short level-one numbered blocks receive an ambiguous `heading_candidate`. The v2 draft also omitted H01 p2l1's explicit null relationships. V3 restores these unchanged v1 assertions; a continuation candidate never establishes a parent or section.

V1 files are preserved unchanged: `oracle/structure-oracle.json` has SHA-256 `186f3ae6fa2cc5327c4122138f014705b6d362bbbbd6338a16025f95af8f69f0`, and its freeze bundle fingerprint is `f894c05126e65e3d9504f6ac368fc6a5df814ec6e7a89fc338543eb4feb81ac1`. V2 was frozen and used for the initial debug evaluation; its oracle SHA-256 is `007fbd2575ff99ab519e5ab84645f5fd47ffae5a3206ad778cec1be144104f11` and bundle fingerprint is `7f76f29b11eb0f194389599fdf689ef3064d1bac1ad3b8682208e534d8ec5314`. V2 and its report are preserved as history. V3 is frozen separately and restores the omitted H01 null assertions without modifying v1 or v2.

## Historical Result Boundary

`reports/initial-debug-worktree-v4.json` is preserved with its original `generated_at` value `2026-10-09T00:34:38.28141+08:00`. Under its v1 contract it measured 13/85 kind mismatches, 13/85 parent-or-merge mismatches, 11/85 section mismatches, and one failed local continuation review marker. Those counts are historical and are not directly comparable with v2: the expected kind and uncertainty contract changed, and the v4 runner did not verify global continuation candidates, projection dispositions, or table cell offsets. V2 results must be reported from a fresh run; this historical timestamp does not establish freeze ordering or canonical archive status.
