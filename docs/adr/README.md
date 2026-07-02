# Architecture Decision Records

One short markdown file per significant decision: `Status`, `Date` and
Context / Decision / Consequences sections.

| Num                                                    | Title                                                    | Status   | Date       |
| ------------------------------------------------------ | -------------------------------------------------------- | -------- | ---------- |
| [0001](0001-data-sources.md)                           | Data sources for the MVP                                 | Accepted | 2026-07-02 |
| [0002](0002-postgres-native-jobs-and-outbox.md)        | Postgres-native jobs and transactional outbox, no broker | Accepted | 2026-07-02 |
| [0003](0003-layered-architecture-import-linter.md)     | Layered architecture enforced with import-linter         | Accepted | 2026-07-02 |
| [0004](0004-unified-hazard-events-table.md)            | Unified hazard_events table                              | Accepted | 2026-07-02 |
| [0005](0005-crs-store-4326-project-25830.md)           | CRS: store EPSG:4326, project to EPSG:25830 on the fly   | Accepted | 2026-07-02 |
| [0006](0006-geojson-featurecollection-responses.md)    | GeoJSON FeatureCollection responses, keyset pagination   | Accepted | 2026-07-02 |
| [0007](0007-geoparquet-snapshots-from-first-ingest.md) | GeoParquet snapshots from the first ingest               | Accepted | 2026-07-02 |
| [0008](0008-content-hash-upserts-and-sync-cursor.md)   | Content-hash upserts and per-source sync cursor          | Accepted | 2026-07-02 |
