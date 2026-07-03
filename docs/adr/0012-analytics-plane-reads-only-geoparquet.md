# 0012 - The analytics plane reads only GeoParquet

Status: Accepted
Date: 2026-07-03

## Context

ADR-0007 has been accumulating per-source GeoParquet snapshots since the
first ingest. The analytical questions (burned area by province and month,
earthquake frequency, warnings summary) are aggregations over history -
exactly what the operational plane is bad at serving and DuckDB is built
for. The temptation to resist: letting the analytics code "just query
Postgres for the missing bit".

## Decision

`app.analytics` reads ONLY the GeoParquet files. The boundary is mechanical,
not conventional: import-linter forbids `app.analytics` from importing
`app.core.db`, `app.core.repo`, the workers, or `app.hazards` - and an
`independence` contract keeps both planes mutually unaware. The parquet
layout (`{DATA_DIR}/exports/hazard_events_{source}.parquet`, columns as
written by the export handler) IS the interface between planes.

Engine choices, sized for a small shared server:

- One lazy in-memory connection with `spatial` loaded once; each request
  gets its own cursor. No `.duckdb` file: the data lives in the parquet
  files, re-read per query - always fresh, zero cache invalidation, and at
  Iberian volumes a re-read costs milliseconds.
- `threads = 2` and `memory_limit = 512MB`: DuckDB's defaults assume it
  owns the machine; here it shares it with the API and Postgres.
- Queries run through `run_blocking`: DuckDB is synchronous and would
  otherwise serialize every request in the event loop.
- Responses are plain JSON, not GeoJSON: aggregates carry no geometry.
- A missing snapshot returns an empty result, not an error: "no ingests
  yet" is a legitimate answer to a legitimate question.

## Consequences

- The integration suite proves the boundary end to end: the same figure
  answered by PostGIS (operational sum) and by DuckDB over the exported
  snapshot (analytical aggregate) must match.
- Analytics can never degrade the operational plane: no connections stolen
  from the pool, no long scans on the transactional tables.
- The price of freshness-by-reread: analytics lags the last snapshot
  export, i.e. one outbox handler run behind the operational truth.
