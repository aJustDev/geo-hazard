# 0001 - Data sources for the MVP

Status: Accepted
Date: 2026-07-02

## Context

The API needs hazard catalogs for the Iberian Peninsula that are open, machine
readable and refreshed often enough to sync on a schedule. Candidates:
Copernicus EFFIS (wildfires), the IGN earthquake catalog, AEMET OpenData
(severe-weather warnings) and Copernicus EFAS (floods).

## Decision

Ship the MVP with EFFIS, IGN and AEMET. Leave EFAS out.

- EFFIS exposes public OGC services (active fires from MODIS/VIIRS, burnt
  areas) with no authentication, updated several times a day.
- IGN publishes a GeoRSS feed with the earthquakes of the last 10 days,
  updated continuously, no authentication, with a stable event id per item.
  Magnitude is embedded in the item text; depth is not published in the feed.
  The full catalog form remains available for manual backfill.
- AEMET OpenData serves the current warnings as CAP v1.2 XML behind a free API
  key, through a two-step flow: a JSON envelope pointing to a temporary
  payload URL, which returns a tar archive with one CAP file per warning zone.
- EFAS real-time products are restricted to registered partners, and its
  archive requires an ECMWF account and batch downloads. That does not fit a
  continuously synced catalog.

## Consequences

- Three heterogeneous protocols (OGC WFS, GeoRSS, REST + CAP) must live behind
  the same ingestion model; each source gets its own driver with no shared
  abstraction until a fourth source proves the pattern.
- Earthquake depth stays out of the MVP attributes.
- Floods can be added later, through EFAS partnership or another open source,
  without touching the ingestion architecture.
