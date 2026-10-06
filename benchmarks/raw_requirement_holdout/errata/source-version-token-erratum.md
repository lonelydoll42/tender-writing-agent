# Erratum E-001: `source_version` Token Interpretation

Status: recorded independently; does not modify the frozen raw inputs or oracle.
Recorded on: 2026-10-06
Applies to: all oracle provenance entries that currently show a `source_version` value

## Correction

The `source_version` values written in the frozen oracle, such as
`2026-09-18-r2`, are labels appearing inside the synthetic raw documents. They
are content-level labels for fixture provenance and are not the authoritative
runtime `SourceReference.source_version` values.

The current baseline contract defines the authoritative runtime value as:

`Registry.file_version_token(file_id)`

That token includes the registered version/checksum identity. During the actual
acceptance, the evaluator must obtain `SourceReference.source_version` from the
runtime result and verify that it equals the corresponding Registry
`file_version_token(file_id)`.

## Acceptance handling

- Treat the oracle's displayed `source_version` as an inline-document label only.
- Do not replace the runtime token with the inline label.
- Do not fabricate a token from the inline label.
- Do not treat equality between the inline label and the Registry token as a
  business fact; the two values represent different fields.
- Preserve and report both values when available:
  - inline document label: the literal value found in the raw text;
  - runtime provenance token: the value returned in `SourceReference.source_version`.
- The runtime provenance check must use the actual `file_id`, Registry record,
  registered version/checksum, document, page, and quote. A keyword match or
  matching-looking label is insufficient.

## Scope and freeze constraints

This erratum explains the interpretation of the existing oracle field only. It
does not alter any raw document, oracle expectation, sample wording, logical
relation, expected disposition, or bundle fingerprint. It must be applied only
when the implementation is frozen and the final registry/runtime acceptance is
authorized.

