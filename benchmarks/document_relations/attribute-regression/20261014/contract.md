# Finite Copy Attribute Contract

Frozen by the main reviewer before delegation on 2026-10-14.
Classification: public development regression, not unseen acceptance.
Base commit: 91fb1b9751d010af9c0f804dc6afbfee1de36dd2.

## Diagnosis

The current case-09 graph retains two confirmed atoms and a reference to the
correct predecessor. It has no confirmed attribute scope or directed attribute
parent, and its confirmed reference evidence omits the antecedent clause.
The frozen 1.0.3 and 1.0.4 graders report these actual missing records.
This batch addresses the product representation, not grading or atom mapping.

## Finite Positive Binding

Only the explicit phrase "该复印件" and an affirmative, unconditional requirement
to affix a seal are in scope. The source and antecedent must be verified in the
same document/version/page. The antecedent must be the adjacent substantive
condition, with exactly one explicitly introduced copy object. Blank physical
lines may be skipped; headings, page boundaries, intervening requirements and
alternative or compound antecedents cannot be skipped to confirm a binding.
One condition node is not by itself proof of one object.

The original two atoms remain distinct. Add a non-AND/OR attribute scope with
exact direct members for the object requirement and attribute requirement.
The attribute has a directed typed attribute parent, a nonempty basis, and
exact antecedent target. The reference retains its antecedent target and cites
both antecedent and anaphoric clause. A structural parent pointer alone is
insufficient. Scope, parent and reference evidence each cite the original text
that proves that role; no inferred object text substitutes for original quotes.

No new AND, OR, REQUIRED wrapper, entity certificate ownership, same-person
constraint or time inference is introduced by this batch.

## Review Boundaries

Ambiguous antecedents, compound or alternative objects, scope interruptions,
cross-page text, a generic "该材料", negated seal instructions and conditional
seal instructions cannot yield a confirmed attribute binding under this
contract. Keep original blocks and source locations. Candidate or unresolved
relation output explains the unsupported interpretation and requests review;
do not silently discard an anaphoric attribute or invent a resolved target.
An independently justified reference does not confirm attribute scope.

Unverified identities, changed versions, invalid coordinates and duplicated
block IDs must not produce confirmed bindings. Attributes and contextual
parents must never authorize logical AND/OR inheritance.

## Verification

Freeze cases.json before implementation. The four positives and eight review
boundaries run through actual Registry/Runtime, retain graph/context/runtime
and distinguish execution failure, grading failure and not_run.
Source references must independently pass the existing frozen checker.
Add focused regression and forged-source tests before modifying the product;
retain the initial failing results and exact test snapshot.

Re-evaluate case-09 with the unchanged original graders and the unchanged v2
oracle. Capture all fourteen cases again. Any new comparison adapter must call
frozen public grading APIs, pin rules/overlay hashes and actual capture identity,
and keep the original historical CLI and current-20e79af adapter guards intact.
Only case-03 and case-11 use the existing 1.0.5 overlay; other twelve retain
the frozen 1.0.4 view. Preserve reports and graphs without relabelling old 10/14
as the new product score. Do not assume the new whole-bundle score in advance.

The main reviewer reruns from an exact Git export and independently tests
evidence/target mutations using the actual product graph, not a synthetic tree.
Preserve all old assets outside the explicitly allowed changes.

## Isolation And Acceptance Limits

The accepted 91fb1b9 public canary was readable by the developer. No independently
administered environment or denied-access proof has been supplied since that
preflight. This batch does not repeat a directory/worktree isolation claim,
create hidden files on the shared host, provision accounts or servers, or read
credentials. New unseen files remain zero and unseen evaluation remains not_run.
Freeze unseen inputs only after an independent administrator denies actual
developer file, credential and shared conversation/log access.

Case-13 contextual linkage, case-07 cross-page continuation and case-12
number interpretation are separate tasks. Enterprise materials and real model
services are not run. Public raw-file 0/8 is retained, production/general
completeness is not passed, and uv.lock remains separate.
