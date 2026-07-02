# 0004 - Unified hazard_events table

Status: Accepted
Date: 2026-07-02

## Context

Three heterogeneous sources: EFFIS mixes point hotspots and burnt-area
polygons, IGN gives points with magnitude/date, AEMET gives warning-zone
polygons with validity windows and levels. The public API is spatial and
cross-source: "what hazards are in this bbox / radius", plus clustering.

## Decision

One table, `hazard_events`, with common typed columns (`source`,
`hazard_type`, `external_id`, `geom geometry(GEOMETRY, 4326)`, `severity`,
`starts_at`/`ends_at`) and per-source raw attributes in `attrs JSONB`,
validated at the driver boundary so the JSONB is never an opaque bag in code.
CHECK constraints instead of native ENUMs (adding a value is a cheap
constraint swap, not an enum migration). The geometry column is generic
GEOMETRY: even a single source mixes points and polygons, and GiST indexes
both the same.

## Consequences

- bbox/radius/clustering are ONE query over ONE GiST index; a per-source
  table design would make every endpoint a UNION of three plans and
  cross-type clustering impractical in plain SQL.
- Adding a source touches drivers and a migration seed, not the API.
- Per-source queries pay a `source` filter instead of a smaller table; at
  Iberian volumes (thousands of rows/month) that is noise.
