# 0005 - CRS: store EPSG:4326, project to EPSG:25830 on the fly

Status: Accepted
Date: 2026-07-02

## Context

Everything the API serves is GeoJSON, whose coordinate system is WGS84
(EPSG:4326) by RFC. But metric operations (radius in meters, areas, DBSCAN
eps) need a projected CRS; degrees are not meters and their metric size
varies with latitude. Spain's official projected CRS for the peninsula is
ETRS89 / UTM zone 30N (EPSG:25830).

## Decision

Store and expose everything in 4326. Project to 25830 inside SQL, on the fly,
only where math needs meters.

- Prefer **transforming the query parameter, not the column**: transform the
  query point to 25830, buffer in meters, transform the buffer back to 4326
  and prefilter with `ST_Intersects` against the existing GiST. The index is
  used as-is and only candidate rows pay any further exact math.
- A functional GiST index on `ST_Transform(geom, 25830)` remains the escape
  hatch if measurements ever show the parameter-side transform insufficient.

Alternatives considered:

- `geography` type: honest meters everywhere without zone limits, but a more
  limited function set (no ST_ClusterDBSCAN input, fewer operators), costlier
  geodesic math, and it would remove the projected-CRS learning this project
  exists for.
- Storing 25830: would force reprojection on every GeoJSON response and break
  the "GeoJSON is 4326" contract.

## Consequences

- Metric accuracy degrades toward the UTM zone edges (Galicia is zone 29,
  Catalonia/Balearics zone 31): acceptable error for km-scale radii, and it
  grows with distance, hence the radius cap in the API.
- The Canary Islands are outside the 25830 domain (REGCAN95 / UTM 28 would be
  correct). Canary events are stored and served in 4326 like everything else,
  but metric queries there are documented as degraded; dual-CRS support is
  out of the MVP.
