# 0015 - EFFIS HTTP adapter reads the gwis mapfile

Status: Accepted
Date: 2026-07-04

## Context

The EFFIS HTTP adapter was blocked since phase 2: on the `/effis` mapfile
the NRT burnt-area layers (`effis.nrt.ba.*`) fail server-side with a
persistent SQL error, the plain hotspot layers time out, and without a real
payload the property schema was unknown. Tracing the official
current-situation viewer's network traffic (2026-07-04) showed it is fed by
the sibling `/gwis` mapfile on the same server, where the NRT burnt-area
family (`nrt.ba.poly.*`) and the hotspot family (`all.hs.*`) answer with
fresh data. Real payloads are captured under `tests/fixtures/effis/`.

## Decision

- Base URL `https://maps.effis.emergency.copernicus.eu/gwis`, WFS 1.0.0
  with `outputFormat=geojson` (2.0.0 returns 502, 1.1.0 hangs).
- Layers: `nrt.ba.poly.week` (stable `fire_id`, `initialdate`, `area` in
  hectares) and `all.hs.week` (`id`, `acq_at`, `CLASS`). The rolling window
  is resolved by the layer NAME; the WFS silently ignores `TIME`. "week"
  over "today": with a 4-hour sync cadence the overlap makes missed runs
  harmless, and content-hash upserts absorb re-served rows. The
  attribute-rich `*.hs.query` archives are unusable for sync (full history
  since 2019; any date FILTER times out).
- `bbox=-19,27,5,44` (peninsula + Baleares + Canarias). A bbox is a
  rectangle: neighboring territory inside it (Portugal, north African
  coast) is ingested as-is, like the IGN feed's border quakes.
- Axis order: the gwis GeoJSON output serializes coordinates as
  `[lat, lon]` while the request `bbox` is normal lon,lat order. The swap
  to canonical GeoJSON happens ONLY in the EFFIS parser - the boundary
  where the source vocabulary dies - mirroring CAP's swap living only in
  `cap_polygon_to_wkb`.
- Timestamps carry no zone marker; EFFIS satellite products publish UTC,
  so they are read as UTC and the raw strings survive in `attrs` (same
  doctrine as IGN's Europe/Madrid interpretation).
- `external_id` prefixes `hs-` / `ba-` keep the two products' id spaces
  from colliding under the `(source, hazard_type, external_id)` uniqueness.
- MapServer answers HTTP 200 with a `ServiceExceptionReport` XML when a
  layer backend fails (observed for days on `/effis`): the driver maps
  that to a TRANSIENT error (retry next poll). Protocol errors are
  reserved for real contract changes: 4xx or unparseable JSON.

## Consequences

- Fetch weight in fire season: ~8k hotspot points + ~100 polygons per
  poll. Steady state is cheap: unchanged content hashes skip the update.
- A burnt area that grows keeps its `fire_id`: the upsert updates geometry
  and area in place, so the catalog holds one row per fire, not one per
  observation.
- If gwis degrades the way `/effis` did, the sync fails transiently and
  retries on schedule - no data corruption and no human paged on the
  first blip.
