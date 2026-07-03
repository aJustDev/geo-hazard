# 0011 - Metric queries: GiST prefilter + exact refine, and DBSCAN clusters

Status: Accepted
Date: 2026-07-03

## Context

ADR-0005 fixed the doctrine (store 4326, project the PARAMETER to 25830 for
metric work) but no query exercised it yet. The phase adds two: "what is
within N meters of this point" and "where are events concentrated". The
naive version of the first - `ST_DWithin(ST_Transform(geom, 25830), ...)`
alone - cannot use the GiST index on `geom`: the index stores 4326
geometries and an expression over a transform is invisible to it, so every
row would be transformed and measured on every request.

## Decision

**`GET /v1/events/near`** runs in two steps inside one query:

1. Prefilter: build the metric circle (`ST_Buffer` of the projected query
   point), transform it BACK to 4326 and intersect its envelope with `geom`
   - a plain `ST_Intersects` the GiST index can serve. The buffer gets a +1%
     margin because `ST_Buffer` approximates the circle with an inscribed
     polygon (its chords fall inside the true circle).
2. Refine: `ST_DWithin` in 25830 over the few candidates only. This is the
   sole authority on membership; the prefilter is allowed false positives,
   never false negatives.

`distance_m` (to the edge for polygons, 0 inside) travels in `properties`
and orders the response. No cursor: a radius query means "the N nearest",
not a browsable listing. Radius is capped at 200 km - beyond that, UTM 30N
distortion grows and the question stops being local.

**`GET /v1/events/clusters`** uses `ST_ClusterDBSCAN(ST_Transform(geom,
25830), eps_m, min_points) OVER ()`, a window function: every row keeps its
cluster id, and an outer GROUP BY produces one centroid Feature per cluster
(count, max severity, time range). Chosen over `ST_ClusterWithin` because
that returns opaque GeometryCollections that would need dismantling to
aggregate anything. Noise (cluster_id NULL) is excluded: an isolated event
is not a concentration. The centroid is computed in 25830 - the metric
centroid - and returned in 4326.

## Consequences

- Both endpoints reuse the existing GiST index and the shared filter set
  (hazard_type, source, severity_min, time window, active); no new index,
  no new column, no stored 25830 geometry.
- DBSCAN runs over the full filtered set on every request: fine at Iberian
  volumes (thousands of rows); if it ever hurts, the escape hatch is
  filtering by time window first, which the API already encourages.
- eps_m and min_points are the client's knobs: the API does not pretend to
  know what "a cluster" means for every hazard type.
