# geo-hazard

[![CI](https://github.com/aJustDev/geo-hazard/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/aJustDev/geo-hazard/actions/workflows/ci.yml)
[![Python 3.14](https://img.shields.io/badge/python-3.14-3776ab)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A natural-hazard spatial API for the Iberian Peninsula, built on open European
data: wildfires from Copernicus EFFIS, earthquakes from the Spanish IGN and
severe-weather warnings from AEMET.

**Status: in production** at <https://geohazard.ajustino.dev>
([interactive docs](https://geohazard.ajustino.dev/docs),
[source freshness](https://geohazard.ajustino.dev/v1/sources/status)). All
three sources sync continuously; the history accumulates from the first
ingest.

## What it does

- Serves hazard events from the three sources under one model: GeoJSON
  (RFC 7946) in EPSG:4326, a common 1-4 severity scale, and an honest
  lifecycle per event (`active` means "in force now").
- Answers spatial queries: bounding box, radius in meters, density-based
  clustering (DBSCAN), with keyset pagination.
- Keeps its catalogs in sync through Postgres-native scheduled jobs and a
  transactional outbox. No message broker.
- Turns the sources' rolling windows into permanent history: every ingest
  rewrites a GeoParquet snapshot, and the analytics endpoints (burned area by
  province and month, earthquake frequency, warnings by phenomenon) run on
  DuckDB over that history, never on the operational database.

## Why it exists

geo-hazard is two things at once. It is a public open-data API: free, without
authentication, and transparent about how fresh each source is. It is also
an engineering reference for a small geospatial backend done carefully: two
data planes kept apart by contracts enforced in CI, a transactional outbox
without a broker (one dispatch per event, idempotent handlers), ingest that
tolerates hostile upstreams, and one ADR for every decision that matters.

## Try it

```sh
# Events in force now in the peninsula
curl 'https://geohazard.ajustino.dev/v1/events?bbox=-9.5,36,3.4,43.8&active=true&limit=5'

# The nearest events within 100 km of Madrid, with distance in meters
curl 'https://geohazard.ajustino.dev/v1/events/near?lon=-3.70&lat=40.42&radius_m=100000&limit=5'

# Wildfire clusters in Galicia (DBSCAN, 5 km neighborhood)
curl 'https://geohazard.ajustino.dev/v1/events/clusters?eps_m=5000&min_points=5&hazard_type=wildfire&bbox=-9.5,41.8,-6.7,43.8'

# Burned hectares per month in Badajoz (INE province 06)
curl 'https://geohazard.ajustino.dev/v1/analytics/wildfires/burned-area?year=2026&province=06'

# How fresh each source is
curl 'https://geohazard.ajustino.dev/v1/sources/status'
```

The API is rate limited per IP (stricter on clustering and analytics); a
`429` or `503` carries `Retry-After`.

## Stack

FastAPI + SQLAlchemy 2 (async) + PostgreSQL/PostGIS as the operational plane;
DuckDB over GeoParquet as the analytical plane. Python 3.14, managed with uv.

## Documentation

- [Architecture decision records](docs/adr)
- [Data sources: captured endpoints and formats](docs/sources.md)
- [Deployment and operations](docs/deploy.md)
- [Contributing and local development](CONTRIBUTING.md)

## Data sources and attribution

The data is not this project's. Each source is credited in every API response
(an `attribution` member) and its reuse terms are summarized in
[NOTICE](NOTICE):

- Wildfires: [EFFIS](https://forest-fire.emergency.copernicus.eu/),
  Copernicus Emergency Management Service, (c) European Union, CC BY 4.0.
- Earthquakes: earthquake catalog of the
  [IGN](https://www.ign.es/web/ign/portal/sis-area-sismicidad), the Spanish
  national geographic institute, CC BY 4.0.
- Weather warnings: [AEMET OpenData](https://opendata.aemet.es/), (c) AEMET.
- Provincial boundaries: derived from the CNIG/IGN administrative units
  ("lineas limite",
  [Centro de Descargas del CNIG](https://centrodedescargas.cnig.es/)),
  (c) Instituto Geografico Nacional, CC BY 4.0. A simplified snapshot is
  committed at `data/reference/` and regenerated with
  `scripts/build_provinces_reference.py`.

geo-hazard is not affiliated with or endorsed by any of these organizations.

## License

Code: MIT, see [LICENSE](LICENSE). Data: see [NOTICE](NOTICE).
