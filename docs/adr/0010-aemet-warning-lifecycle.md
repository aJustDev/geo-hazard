# 0010 - AEMET warning lifecycle: reconciling against the full bulletin

Status: Accepted
Date: 2026-07-03

## Context

AEMET's "ultimo elaborado" bulletin is not a diff: it is the COMPLETE set of
warnings in force, one CAP file per warning and zone. CAP identifiers are
immutable per message; an updated warning arrives as a NEW identifier whose
`references` lists the messages it supersedes, and `msgType` distinguishes
Alert (new), Update (supersedes) and Cancel (withdraws). Warnings also
simply disappear from the bulletin once superseded or withdrawn.

Keying rows by CAP identifier alone would let superseded warnings stay
"in force" (their `expires` is still in the future) next to their
replacements: double counting for any `active=true` query.

## Decision

`external_id` = CAP identifier, and the sync applies three lifecycle rules:

1. **Ingest Alert/Update with level amarillo or higher.** `verde` is the
   absence of risk, not a hazard (its mapping to severity 1 exists only for
   completeness, ADR-0009); a Cancel is not a warning either. A warning
   without polygon or validity window is skipped with a log.
2. **Update/Cancel close what they reference**: the referenced identifiers
   get `ends_at` = the superseding message's `sent`, via
   `HazardEventRepo.close_events` (which only touches rows still open at
   that moment, so an already-expired warning keeps its original window).
3. **Vanished warnings are closed at "now"**: the sync cursor
   (`source_sync_state.cursor`, ADR-0008) stores the full identifier set of
   the last bulletin. Anything in the previous set that is missing from the
   current one without a Cancel was withdrawn when AEMET elaborated the new
   bulletin.

The counterpart in the upsert: its update condition is `content_hash IS
DISTINCT ... OR ends_at IS DISTINCT ...`. If the bulletin re-serves as open
a warning we had closed (e.g. a poll that misread one CAP member), the
source wins and the row reopens even though its content hash is unchanged.

## Consequences

- `active=true` never double-counts a warning and its replacement.
- Every close is capped, not deleted: the historical row (and the
  GeoParquet snapshot) keeps the real observed lifecycle.
- The cursor grows with the bulletin size (a few hundred identifiers,
  a few KB of JSONB): negligible, and it makes the reconciliation
  self-contained - no extra table, no full scan of open rows.
