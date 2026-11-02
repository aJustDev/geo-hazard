# 0022 - Own frontend in a separate repo, self-hosted basemap

Status: Accepted
Date: 2026-11-02

## Context

The only UI today is a showcase console inside the portfolio
(`ajustinodev`, Astro), with a Natural Earth background and no streets or
places. Notifications (ADR-0021) link to the raw JSON of
`/v1/events/{id}`, which is useless on a phone. The product plan calls for
an app of its own: what is active now, an event page the notification can
open, and later a "my area" view.

Measured in production on 2026-11-02: everything active now is ~180
features (~60 kB of GeoJSON). A year of history is 21k AEMET polygons
(16 MB) and 102k EFFIS hotspots (5 MB), which drawn raw on a map is noise,
not information.

## Decision

- **Separate repo** (`geohazard-web`, private), same stack as the other
  fronts (Vite, React, TypeScript, Tailwind, MapLibre). It is a static SPA on
  Cloudflare Pages at `alertas.ajustino.dev`, deployed from its own CI.
  Mixing a JS pipeline into this repo would make every front change
  redeploy the API.
- **The API stays as is.** The current view reads
  `/v1/events?active=true` (plus recent earthquakes) as GeoJSON. History
  goes through the existing analytics aggregates. **No dynamic vector tiles
  (`ST_AsMVT`)**: at these volumes they add a moving part without a reader.
  Revisit only for a hotspot density layer.
- **Self-hosted basemap.** A Protomaps extract of Spain (peninsula,
  Balearics, Ceuta, Melilla and the Canaries, with the neighbouring border
  area) at max zoom 12 (~450 MB). It is a single PMTiles file plus the
  glyphs and sprites the style needs, served by Caddy from
  `/opt/geohazard-tiles` under `https://geohazard.ajustino.dev/tiles/`.
  - No third-party tile server and no API key at runtime.
  - Zoom 12 shows villages and main roads, enough to place a quake or a fire.
    The client only downloads the tiles it looks at.
  - The file name carries the build date and is cached as immutable, so a
    new extract is a new URL.
  - It is built on a dev machine with `scripts/build_basemap.sh` (the server
    has no `pmtiles` CLI) and uploaded with rsync.
- CORS stays an exact list (`CORS_ORIGINS`): the front origin is added by
  hand. Tiles answer with `Access-Control-Allow-Origin: *`; they are public
  OpenStreetMap-derived data.

## Consequences

- Refreshing the basemap is a manual operation (`docs/deploy.md`, section
  "Basemap"). Nothing breaks if it is never refreshed; OSM changes slowly.
- The notification link moves to the front (`/e/{id}`) once the event page
  is live (ADR-0021 is amended then).
- Beyond zoom 12 MapLibre overzooms: streets thin out at city scale, which
  this product does not need.
- The basemap requires OpenStreetMap and Protomaps attribution, which the
  front shows next to the data sources' attribution.
