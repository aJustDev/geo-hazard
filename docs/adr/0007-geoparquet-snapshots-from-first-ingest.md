# 0007 - GeoParquet snapshots from the first ingest

Status: Accepted
Date: 2026-07-02

## Context

The analytical plane (DuckDB) arrives in a later phase, but the sources are
rolling windows: EFFIS serves the last 1/7/30 days, AEMET only the warnings
in force. Whatever is not captured now is unrecoverable later.

## Decision

The `hazards.batch_ingested` outbox handler exports a full per-source
snapshot to `{DATA_DIR}/exports/hazard_events_{source}.parquet` from the very
first batch, written via DuckDB spatial (`ST_GeomFromWKB` + `COPY ... FORMAT
PARQUET`) so the files carry proper GeoParquet metadata. Writes go to a
`.tmp` file and `os.replace` (atomic on POSIX), which makes the handler
naturally idempotent under the outbox's at-least-once delivery.

Details that keep the files consumable:

- Explicit Arrow schema (type inference would flip column types between
  batches, e.g. an all-NULL `ends_at`).
- `attrs` serialized as a JSON string column: a stable schema beats an
  inferred struct that changes with every new key.
- Full-snapshot rewrite: at Iberian volumes it costs milliseconds; hive
  partitioning by year is the documented growth path once a file approaches
  ~100 MB.

## Consequences

- History accumulates from day one even though nothing reads it yet.
- The parquet files are an open contract reusable outside this API (pandas,
  QGIS, DuckDB CLI).
- The analytical phase becomes a pure consumer: no backfill work.
