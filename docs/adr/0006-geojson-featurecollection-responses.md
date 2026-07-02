# 0006 - GeoJSON FeatureCollection responses with keyset pagination

Status: Accepted
Date: 2026-07-02

## Context

The API serves spatial features to unknown clients. The candidates were plain
JSON rows with an embedded geometry field, or RFC 7946 GeoJSON.

## Decision

`GET /v1/events` returns a GeoJSON FeatureCollection (RFC 7946). Pagination
travels as _foreign members_ (`numberReturned`, `nextCursor`), which section
6.1 of the RFC explicitly allows. Per-source raw attributes stay nested under
`properties.attrs` so three sources' vocabularies never collide in one flat
namespace.

Pagination is keyset over `(starts_at DESC, id DESC)`, encoded as an opaque
base64 cursor: OFFSET degrades linearly and skips or repeats rows when an
ingest inserts between pages; a keyset is stable under concurrent writes.

## Consequences

- Leaflet, MapLibre, QGIS and geopandas consume the response with zero
  adapter code; for a portfolio API, "paint it on a map in five lines" is the
  point.
- Clients cannot jump to page N; for spatial browsing nobody does.
- The cursor is opaque by contract: its internals can change without breaking
  clients.
