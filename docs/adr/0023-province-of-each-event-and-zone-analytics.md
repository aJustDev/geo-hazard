# 0023 - Province of each event, and zone analytics

Status: Accepted
Date: 2026-11-03

## Context

The front (ADR-0022) needs a "my area" view: pick a province or a circle and
see what is active there and its history, plus a national choropleth by
province. Three facts shaped the design:

- The province rule that works for AEMET zones is the one from ADR-0021: a
  point belongs to the province it falls in, a polygon to the province it
  overlaps most. Zones cross province borders and coastal zones are mostly
  sea, so neither plain intersection nor the centroid (ADR-0013) is right.
- Computing that rule on the fly costs about 2 ms per polygon. Measured in
  production on 2026-11-03: the whole history of Murcia took 4 s (1,823
  candidate polygons), and it only grows.
- The warnings summary counts CAP rows, and every AEMET Update is a new row,
  so "number of warnings" is inflated and means little to a reader.

## Decision

- **Every event stores its province.** `hazard_events.province_code` is the
  INE code given by the rule above, or NULL outside the 52 provinces (sea,
  Portugal, North Africa). The SQL function `hazard_event_province(geom)`
  holds the rule and a `BEFORE INSERT OR UPDATE OF geom` trigger fills the
  column, so the sync code never touches it. The function returns NULL and
  raises a warning on a geometry error rather than blocking ingestion.
- `GET /v1/events?province=NN` filters on that column (indexed with the
  keyset order). Province watch areas in notifications use the same column,
  so "my area" shows exactly what a province subscription matches.
- The GeoParquet snapshots carry `province_code`: the analytics plane groups
  by it instead of repeating the geometry (it still reads only GeoParquet,
  ADR-0012). Circles are resolved in DuckDB with `ST_DWithin` in
  EPSG:25830, the same semantics as `/v1/events/near`.
- Zone history is reported as **days with a warning per level**: each
  warning is expanded to the civil days (Europe/Madrid) it covers and each
  day counts once, with its worst level. Superseded Updates add no days.
- The existing `/v1/analytics/wildfires/burned-area` keeps its centroid rule
  (ADR-0013). The divergence is accepted and documented; new endpoints use
  `province_code`.

## Consequences

- One rule for the three planes (filter, notifications, analytics), computed
  once per write. Backfilling the existing rows ran in the migration.
- A point exactly on a shared border belongs to the province with the lowest
  code; a polygon touching no province gets NULL and is invisible to
  province filters (it still shows in bbox and circle queries).
- History starts in July 2026 (no backfill of the sources); the UI says so.
