# 0009 - Severity normalized to a common 1-4 ordinal scale

Status: Accepted
Date: 2026-07-03

## Context

The three sources speak incompatible severity languages: EFFIS has none
(a hotspot is a detection, a burnt area has hectares), IGN publishes a
magnitude, AEMET publishes the Meteoalerta color levels. The API offers one
cross-source filter (`severity_min`), so the sources must land on one scale.

## Decision

One ordinal scale, 1 (minor) to 4 (extreme), mapped per source in
`app/hazards/services/severity.py`:

| Source | Rule                                                                      |
| ------ | ------------------------------------------------------------------------- |
| EFFIS  | hotspot = 2 fixed; burnt area 2 by default, >= 500 ha = 3, >= 5000 ha = 4 |
| IGN    | magnitude < 3.0 = 1; 3.0-3.9 = 2; 4.0-5.4 = 3; >= 5.5 = 4                 |
| AEMET  | verde = 1, amarillo = 2, naranja = 3, rojo = 4                            |

Rationale per source:

- **EFFIS**: a hotspot is confirmed fire activity with unknown extent, hence
  a fixed middle-low 2. Burnt areas scale with mapped hectares; EFFIS maps
  fires from roughly 30 ha, so any polygon is already "relevant".
- **IGN**: thresholds anchored to typical effects in Iberia: below 3.0 is
  rarely felt, 3.0-3.9 is felt without damage, 4.0-5.4 can cause light
  damage, 5.5+ makes structural damage likely.
- **AEMET**: Meteoalerta already IS a four-level ordinal scale; the mapping
  is the identity. `verde` means "no risk", so green warnings are mapped for
  completeness but never ingested (ADR-0010).

The scale is lossy and opinionated by design. The raw source values
(hectares, magnitude, nivel) always survive verbatim in `attrs`, so no
information is destroyed: the normalized value only feeds the cross-source
filter.

## Consequences

- `severity_min=3` means "significant" regardless of source: a large burnt
  area, a magnitude-4 quake or an orange warning.
- The thresholds are editable without migrations: severity is recomputed on
  every sync, and a threshold change simply re-updates rows through the
  content-hash upsert on the next poll (severity is not part of the hash).
- An unknown input (new AEMET level, unknown EFFIS kind) raises instead of
  guessing: the sync fails loudly and a human updates the map.
