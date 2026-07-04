# 0016 - Per-source event lifecycle and `active` semantics

Status: Accepted
Date: 2026-07-04

## Context

The `active` filter required a closed validity window (`ends_at NOT NULL`
covering now). AEMET warnings carry one, but earthquakes and everything
from EFFIS were stored with `ends_at = NULL`, so `active` combined with
those hazard types always returned an empty set - the filter was
meaningless for two of the three sources. Mapping the burnt areas'
`finaldate` to `ends_at` alone would not fix it: observed windows are
minutes long (first to last detection of a mapping pass), so nothing would
ever be "in force now".

## Decision

Every event gets an honest lifecycle, decided per source vocabulary:

- **Instantaneous events** (IGN earthquakes, EFFIS hotspot detections):
  `ends_at = starts_at`. A quake or a satellite detection is a moment,
  not a state; it is never "in force now" after the fact.
- **EFFIS NRT burnt areas**: OPEN (`ends_at = NULL`) while the
  `nrt.ba.poly.week` layer serves them; when a fire vanishes from the
  layer, the sync closes it at that sync's time. EFFIS does not publish
  extinction - dropping out of its near-real-time catalog is the most
  honest end-of-life signal it gives. Same vanished-cursor pattern as the
  AEMET bulletin (ADR-0010), reusing `close_events`; if the source
  re-serves a closed fire, the upsert's `ends_at IS DISTINCT` clause
  reopens it.
- **AEMET warnings**: unchanged (`[onset, expires]`, Update/Cancel and
  bulletin reconciliation per ADR-0010).
- **`active` filter**: `starts_at <= now AND (ends_at IS NULL OR
ends_at >= now)` - "already started and still open, or window covering
  this instant". Open-ended now MEANS something ("the source still serves
  it"), so it counts as in force.

A data migration backfills `ends_at = starts_at` for already-ingested
earthquakes and hotspots; open burnt areas stay open.

## Consequences

- `active=true&hazard_type=wildfire` returns exactly the burnt-area
  polygons EFFIS currently serves - the "current fires" picture - instead
  of an empty set. Hotspot noise is excluded by construction.
- A fire can stay "in force" for up to a week after its last mapped
  growth (the NRT window's tail). That imprecision is the source's, not
  ours, and it errs on the side of showing a fire too long rather than
  declaring extinction we cannot know.
- `closed` joins the `hazards.batch_ingested` payload for EFFIS, mirroring
  AEMET, so a batch that only closes fires still refreshes the snapshot.
