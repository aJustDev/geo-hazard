# Data sources: captured endpoints and formats

Facts captured against the live services on 2026-07-02. Fixtures under
`tests/fixtures/` are real responses (trimmed where noted).

## EFFIS (wildfires)

- Base URL (OGC WMS/WFS): `https://maps.effis.emergency.copernicus.eu/effis`
- Per the official downloads instructions: standard OGC services; the `TIME`
  parameter is mandatory for the fire layers.
- Layers of interest (per the EFFIS data-and-services catalog): active fires
  MODIS/VIIRS (last 1/7/30 days) and burnt areas (updated in near real time).
- **Pending capture**: the map server was unresponsive during the spike
  (GetCapabilities timed out on `maps.effis.emergency.copernicus.eu` and on
  the `maps.wild-fire.eu` mirror). Exact WFS feature type names, GeoJSON
  output format and conditional-GET support are still to be verified against
  a live response. No driver code before that.

## IGN (earthquakes)

- Endpoint: `https://www.ign.es/ign/RssTools/sismologia.xml` (GeoRSS, RSS 2.0)
- No authentication. Rolling window: last 10 days (14 items on capture day).
- Per item: `guid`/`link` carrying a stable event id (`evid=es2026mvdms`),
  `geo:lat` / `geo:long` (WGS84), and the magnitude, region name and local
  date-time embedded in the Spanish `description` text. Depth is not
  published in the feed.
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
