# 0008 - Content-hash upserts and a per-source sync cursor

Status: Accepted
Date: 2026-07-02

## Context

Every poll re-serves mostly known records: EFFIS re-sends the same burnt
areas (whose polygons grow while a fire is active), IGN re-sends its 10-day
window. Sync is reconciliation against a window, not "give me the new ones".
A naive upsert would rewrite every row on every poll and emit derived-work
events for batches that changed nothing.

## Decision

- `UNIQUE (source, external_id)` as the idempotency key, with
  `ON CONFLICT DO UPDATE ... WHERE content_hash IS DISTINCT FROM
excluded.content_hash`: an identical re-serve touches nothing.
- `content_hash` = sha256 of the canonical JSON (sorted keys) of what defines
  a real change: geometry, attributes, observation time.
- Insert vs update counts come from `RETURNING (xmax = 0)`: a freshly
  inserted row has no previous version (xmax 0), an updated one does, and
  rows skipped by the WHERE are not returned at all.
- The batch event `hazards.batch_ingested` is only published when
  inserted + updated > 0.
- Per-source sync bookkeeping lives in `source_sync_state` (last run/success,
  JSONB cursor, consecutive failures), separate from `scheduled_jobs`: the
  cursor is ingestion-domain knowledge, the scheduler is generic
  infrastructure. Failures are recorded in their own transaction so they
  survive the batch rollback.

## Consequences

- A no-change poll is a true no-op: no disk writes, no events, no snapshot
  rewrite (proven by the integration pipeline test).
- The hash must include everything that matters and nothing that does not;
  adding a field to `attrs` intentionally causes one full re-update wave.
