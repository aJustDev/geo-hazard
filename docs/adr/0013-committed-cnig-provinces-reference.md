# 0013 - Committed CNIG provinces reference

Status: Accepted
Date: 2026-07-03

## Context

The burned-area aggregate groups wildfires by province, which requires a
spatial join against provincial boundaries. Candidates: Natural Earth
(light, but its generalized borders misassign events near province limits),
a live WFS call per query (a runtime dependency on a third party), or the
official CNIG "lineas limite" product (66 MB of GML, authoritative).

## Decision

Commit a simplified snapshot, `data/reference/provinces_es.parquet`
(~550 KB, 52 provinces including Ceuta and Melilla), derived from the CNIG
INSPIRE AdministrativeUnit 3rdOrder GML via a reproducible script
(`scripts/build_provinces_reference.py`):

- Source: the stable ATOM download URL (no session, no scraping).
- `ST_SimplifyPreserveTopology` at 0.002 degrees (~200 m): far below the
  positional uncertainty of the hazard data itself, so province assignment
  near borders stays honest at 1/100th of the official size.
- Province INE code extracted from the INSPIRE `nationalCode`
  (34 + CCAA + province + zeros); the "territories not attached to any
  province" unit (code 54, islets) is excluded.
- The event-to-province assignment uses the event's CENTROID: a fire
  crossing a border counts once, not twice (per-province split would claim
  a precision the source data does not have).
- The file lives in the repo, not in `DATA_DIR`: it is code-adjacent
  reference data that ships with the image, not runtime state. Attribution
  (CNIG / IGN, CC BY 4.0) is in the README.

## Consequences

- Analytics works offline and in CI with zero network dependencies.
- Simplification can leave hairline slivers between neighboring provinces;
  an event whose centroid falls exactly in a sliver joins no province and
  silently drops from the per-province aggregate. At 0.002 degrees this is
  negligible against the source data's own uncertainty.
- Boundary changes (rare, years apart) require re-running the script and
  committing the diff - an auditable, reviewable event.
