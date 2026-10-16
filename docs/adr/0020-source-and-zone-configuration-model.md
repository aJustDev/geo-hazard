# 0020 - Sources and zones as configuration

Status: Proposed (design only; implementation starts with the first new zone or source)
Date: 2026-10-16

## Context

Geographic scope is hardcoded today, and in five different ways:

| Anchor                      | Where                                                        | Nature                                                     |
| --------------------------- | ------------------------------------------------------------ | ---------------------------------------------------------- |
| EFFIS bounding box          | `EFFIS_BBOX` setting (was a driver constant until 2026-10-16) | Parameter: EFFIS is supranational, widening = new bbox      |
| IGN national feed           | `app/core/ign/drivers/http.py` (`sismologia.xml`)             | Source choice: the feed takes no geographic parameter       |
| AEMET `/area/esp`           | `app/core/aemet/drivers/http.py`                              | Source choice: the area is fixed in the path                |
| `Europe/Madrid` timezone    | IGN and AEMET parsers                                         | Assumption baked into parsing                               |
| Spanish admin reference     | `provinces_es.parquet`, INE `province` filter (ADR-0013)      | Analytics plane anchored to Spain end to end                |

On top of that, `scheduled_jobs` has no parameters column and job handlers
take no arguments (`JobFunc = Callable[[], Coroutine]`), so a job cannot
receive configuration. The source catalog is a `CheckConstraint`
(`SOURCES` in `app/hazards/models/hazard_event.py`), and `/v1/sources/status`
relies on the `job_name = f"{source}_sync"` naming convention.

The project's horizon is the whole Mediterranean basin. Covering a new area
with a supranational source that is already implemented (EFFIS today; EMSC
or MeteoAlarm later) should be a configuration change, not a release. Adding
a territory that needs a new national source will always need code, but
turning it on or off should not.

## Decision

The unit of activation is the **zone**, not the country. Sources are
configured per zone through **feeds**, and jobs run one feed each.

- **`zones` table**: `slug` (primary key, a geographic name such as `iberia`,
  never a political one), `name`, reference geometry (MultiPolygon 4326, used
  for coverage reporting, not to clip data), informative ISO-3166 country
  codes, `enabled`.
- **`source_feeds` table**: one row per source x hazard type x zone, holding
  the endpoint parameters (JSONB: bbox, area code, layers), the effective area
  of interest, the upstream timezone (explicit; never assume the peninsular
  one), the sync interval, and a lifecycle `status`:
  `candidate -> evaluated -> implemented -> active`. Only `active` feeds are
  scheduled. Attribution stays per source in code (`app/core/attribution.py`,
  NOTICE): it follows the licence, not the zone.
- **Parametrized jobs**: a job handler receives its feed
  (`Callable[[FeedConfig], Coroutine]`). `scheduled_jobs` gains a nullable
  `feed_id`; a row with no feed keeps today's zero-argument behaviour, so the
  migration can move one source at a time. Activating a feed inserts its job
  row; deactivating it pauses the job (`next_run_at = 'infinity'`, as
  `docs/deploy.md` already does by hand).
- **`hazard_events` does not change.** The geometry already places the event;
  a zone or country column would be a redundant dimension. If the API ever
  needs a zone filter, it is derived spatially from `zones`.
- **Initial zones**: `iberia` = Spain + Portugal + Andorra with all their
  archipelagos (Balearic, Canary, Madeira, Azores), `enabled`;
  `sahara-occidental`, defined but disabled (non-EU, disputed territory, and
  no source coverage today).
- **`sync_state` stays per source** until a source runs in more than one
  feed; then the key becomes the feed. `/v1/sources/status` reports feeds,
  and the `{source}_sync` convention goes away with it.

## Consequences

- Activating a zone covered by implemented supranational sources becomes an
  `INSERT`/`UPDATE` on `source_feeds`. Activating territory that needs a new
  source still means code first (driver, parser, tests, a contract test in
  `tests/contract/`), then configuration. Implementing a source and turning
  it on stay separate steps: a feed can be `implemented` and off.
- Known code that has to change when this is built:
  - the job registry signature and `JobWorker._execute_job`, which loads the
    feed;
  - the seeding migrations and the meta test `tests/unit/meta/test_jobs_sembrados.py`,
    which parses `INSERT INTO scheduled_jobs` statements;
  - `app/api/v1/sources.py`, which relies on the `{source}_sync` naming;
  - the `SOURCES` check constraint, if a new source arrives (it stays a
    constraint: sources are code, feeds are data);
  - the three source registries and job handlers, near-identical on purpose
    (rule of three); the fourth source is the moment to generalize them.
- Overlapping sources (the same earthquake from IGN and EMSC) are accepted
  by design: `source` tells them apart and `content_hash` must not dedupe
  across sources.
- The analytics plane stays Spanish (INE provinces) until a non-Spanish zone
  is active; generalizing its administrative reference (NUTS/GISCO inside
  the EU, something else outside) is its own ADR and does not block ingest.
- Severity mapping is per source today; a new zone may need its own
  thresholds (ADR-0009) and that review is part of activating it.
