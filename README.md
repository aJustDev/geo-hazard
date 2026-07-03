# geo-hazard

[![CI](https://github.com/aJustDev/geo-hazard/actions/workflows/ci.yml/badge.svg?branch=main)](https://github.com/aJustDev/geo-hazard/actions/workflows/ci.yml)
[![Python 3.14](https://img.shields.io/badge/python-3.14-3776ab)](pyproject.toml)
[![License: MIT](https://img.shields.io/badge/license-MIT-green)](LICENSE)

A natural-hazard spatial API for the Iberian Peninsula, built on open European
data: wildfires from Copernicus EFFIS, earthquakes from the Spanish IGN and
severe-weather warnings from AEMET.

**Status: early development.** The architecture is decided (see the
[ADRs](docs/adr)) and the project is being built in the open, one vertical
slice at a time.

## What it will do

- Serve current hazard events through spatial queries: bounding box, radius in
  meters, density-based clustering.
- Keep its catalogs in sync with the upstream sources through Postgres-native
  scheduled jobs and a transactional outbox. No message broker.
- Accumulate history as GeoParquet snapshots from the very first ingest, and
  answer analytical questions (burned area by month and province, earthquake
  frequency) through DuckDB, keeping the operational and analytical planes
  strictly separated.

## Stack

FastAPI + SQLAlchemy 2 (async) + PostgreSQL/PostGIS as the operational plane;
DuckDB over GeoParquet as the analytical plane. Python 3.14, managed with uv.

## Documentation

- [Architecture decision records](docs/adr)
- [Data sources: captured endpoints and formats](docs/sources.md)

## Data sources and attribution

- Wildfires: [EFFIS](https://forest-fire.emergency.copernicus.eu/), (c)
  European Union, Copernicus Emergency Management Service.
- Earthquakes: earthquake catalog of the
  [IGN](https://www.ign.es/web/ign/portal/sis-area-sismicidad), the Spanish
  national geographic institute.
- Weather warnings: [AEMET OpenData](https://opendata.aemet.es/), (c) AEMET.
- Provincial boundaries: derived from the CNIG/IGN administrative units
  ("lineas limite",
  [Centro de Descargas del CNIG](https://centrodedescargas.cnig.es/)),
  (c) Instituto Geografico Nacional, CC BY 4.0. A simplified snapshot is
  committed at `data/reference/` and regenerated with
  `scripts/build_provinces_reference.py`.

## License

MIT. See [LICENSE](LICENSE).
