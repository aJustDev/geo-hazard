# Data sources: captured endpoints and formats

Facts captured against the live services on 2026-07-02. Fixtures under
`tests/fixtures/` are real responses (trimmed where noted).

## EFFIS (wildfires)

- Base URL (OGC WMS/WFS): `https://maps.effis.emergency.copernicus.eu/gwis`
  (see history below: the `/effis` mapfile we tried first has broken NRT
  layers; the EFFIS current-situation viewer is fed from `/gwis`).
- Transport quirks (both mapfiles): the server **hangs indefinitely on
  requests without a browser-like `User-Agent`** (and on HTTP/2). WFS
  **2.0.0 returns 502**, 1.1.0 hangs; **1.0.0 works** (`typename=`,
  `maxFeatures=`, `bbox=`) and accepts `outputFormat=geojson`. The HTTP
  driver must always send a UA over HTTP/1.1.
- **Working layers, captured 2026-07-04** (WFS 1.0.0 on `/gwis`):
  - Burnt areas (near real time): `nrt.ba.poly.{today,week,month,season}`.
    Properties: `id`, `fire_id` (stable), `initialdate`, `finaldate`,
    `area` (ha). The rolling window is resolved server-side by the layer
    name; the `TIME` parameter is silently ignored on WFS.
  - Hotspots: `all.hs.{today,week,month,season}` (union of sensors; also
    per-sensor `modis.hs.*`, `viirs.hs.*`, `s3.hs.*` but several of those
    time out intermittently). Properties: `id`, `acq_at`, `CLASS`.
  - **Axis-order gotcha**: the GeoJSON output serializes coordinates as
    `[lat, lon]` (inverted, like AEMET CAP polygons). The `bbox=` request
    parameter, however, is interpreted in normal `minLon,minLat,maxLon,
maxLat` order. Swap on ingest.
  - Attribute-rich archives exist (`viirs.hs.query`: `frp`, `confidence`,
    `satellite`...) but they span the full history since 2019 and any
    date `FILTER` on them times out; not usable for sync.
- Fixtures (real responses, Iberia bbox `-10,35,5,44`, captured 2026-07-04):
  `tests/fixtures/effis/nrt_ba_poly_week_iberia.geojson` (84 features),
  `tests/fixtures/effis/all_hs_week_iberia.geojson` (40 features,
  `maxFeatures=40`). Capture command:
  `curl --http1.1 -A "Mozilla/5.0 ..." "https://maps.effis.emergency.copernicus.eu/gwis?service=WFS&version=1.0.0&request=GetFeature&typename=nrt.ba.poly.week&outputFormat=geojson&bbox=-10,35,5,44"`
- History (2026-07-02/03): on the `/effis` mapfile the NRT burnt-area layers
  (`effis.nrt.ba.*`) fail server-side with `msPostGISLayerGetItems(): Query
error` and the plain hotspot layers time out; only the historical
  `modis.ba.poly[.year|.week|...]` family answers there. That mapfile also
  lacks the `nrt.ba.*` family entirely. Both facts still true on
  2026-07-04; the blocker was the mapfile choice, not the service.

## IGN (earthquakes)

- Endpoint: `https://www.ign.es/ign/RssTools/sismologia.xml` (GeoRSS, RSS 2.0)
- No authentication. Rolling window: last 10 days (14 items on capture day).
- Per item: `guid`/`link` carrying a stable event id (`evid=es2026mvdms`),
  `geo:lat` / `geo:long` (WGS84), and the magnitude, region name and local
  date-time embedded in the Spanish `description` text. Depth is not
  published in the feed.
- **Timezone doctrine**: the embedded date-time carries no timezone marker;
  per the capture-day check it is local (peninsular official) time. The
  parser interprets it as `Europe/Madrid` and converts to UTC, keeping the
  raw string in `attrs` so the interpretation can be audited or corrected.
- Fixture: `tests/fixtures/ign/georss_ultimos_10_dias.xml` (full response).

## AEMET (severe-weather warnings)

- Two-step flow:
  1. `GET https://opendata.aemet.es/opendata/api/avisos_cap/ultimoelaborado/area/esp`
     with header `api_key: <key>` returns a JSON envelope
     `{descripcion, estado, datos, metadatos}`.
  2. `GET` on the `datos` URL (temporary, does not embed the key) returns a
     tar archive with one CAP v1.2 XML per warning and zone (338 files on
     capture day).
- CAP fields of interest: `identifier` (unique), `msgType`
  (Alert/Update/Cancel), `references` (chain of superseded messages), info
  blocks in es-ES and en-GB, `onset`/`expires` (validity window), CAP
  `severity`, parameter `AEMET-Meteoalerta nivel` (verde/amarillo/naranja/
  rojo), eventCode `AEMET-Meteoalerta fenomeno`, `area/polygon` and `geocode`
  (warning zone id).
- **Axis order**: CAP polygons are `lat,lon` pairs, the reverse of GeoJSON.
  The geometry service will be the single module allowed to deal with this.
- Fixtures: `tests/fixtures/aemet/first_hop_response.json` and
  `tests/fixtures/aemet/cap_aviso_naranja_ta.xml` (one real orange warning).
