# Source position and relationship evidence contract

Frozen before product implementation, 2026-10-13. This is a public regression
contract, not a new unseen evaluation. H01-H06 remain public.

## Source Roles

1. The document structure retains every raw block, including empty lines,
   whitespace, their exact identity/version/page/line/character coordinates
   and original source references. No raw block or position is discarded.
2. Relationship records may expose `position_references` for verified physical
   positions. Empty/whitespace-only quotes and zero-length spans are allowed
   only here, not as relationship evidence.
3. `source_references`, operator, membership, parent proof and termination
   evidence must have a non-whitespace exact source quote and a positive span.
   A verified position is not proof of a condition or parent relationship.
4. Empty or whitespace-only blocks have no relationship evidence and cannot
   confirm a parent, operator, scope or membership. Invalid identity, version
   or coordinates must not become verified positions.
5. The frozen 1.0.3, 1.0.4 and 1.0.5 graders and historical reports are unchanged.
   The product must emit the correct roles; no global empty-evidence exemption
   is added to a grader.

## Finite Group Parsing

Explicit composite group headers may name materials, requirements, proofs or
conditions. The complete actual product output, not an injected tree, must
contain the expected outer AND and two directly owned inner OR groups, four
separate atomic conditions and independently verified operator/member/end
evidence. The existing inheritance, negation and review gates remain in force.

Local AND versus inherited OR, unsupported K-of-N, wrong group count, duplicate
or missing labels, and intervening substantive paragraphs must not produce a
confirmed complete outer relationship. Empty layout lines alone are not a
substantive scope interruption. Independent local relationships are reported
separately from the complete outer tree.

## Reporting

Capture original H01-H06 and D01-D05 through the real Registry/Runtime, with
input hashes and actual execution states. Keep all baseline and intermediate
failures. Keep product positives separate from synthetic/mutated graph checks.
For negative graph mutations record source validation and semantic rejection
roles so a blank locator cannot masquerade as detecting a different error.

Historical output scored 10/14 by 1.0.5 remains a historical result; it is not
the score of newly captured product output. No business materials are run by
this regression, and no business false-pass/block rates may be inferred.
General completeness, Step 2 and production acceptance remain unpassed.
