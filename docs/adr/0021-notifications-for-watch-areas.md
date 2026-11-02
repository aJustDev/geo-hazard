# 0021 - Notifications for watch areas

Status: Proposed (design; implementation is the first product stage: no
accounts, ntfy and webhook channels, subscriptions managed by CLI)
Date: 2026-11-02

## Context

The API is pull only: whoever wants to know that something happened in a
place they care about has to poll it. The pieces for push already exist:

- every sync that changes data publishes `hazards.batch_ingested` through
  the transactional outbox (ADR-0002), and the dispatcher runs several
  handlers per event with per-handler idempotency;
- severity is one 1-4 scale across sources (ADR-0009);
- each source has an explicit lifecycle (ADR-0010, ADR-0016);
- the CNIG provinces reference is committed (ADR-0013), although today only
  the analytics plane reads it.

Constraints that shape the design:

- **Latency is the sources' cadence**: IGN 15 min, AEMET 30 min, EFFIS 4 h.
  This is not an emergency system; the official channels are ES-Alert, 112
  and AEMET itself.
- **A new row is not a new hazard.** Every AEMET Update arrives with a new
  CAP identifier and closes the one it supersedes at the Update's `sent`
  (ADR-0010); one bulletin carries around 260 warnings. EFFIS serves about
  2,200 features a week over Iberia, mostly hotspot detections with a fixed
  severity 2 and many of them agricultural burns. IGN re-serves a 10-day
  window and revises magnitudes.
- **Spam kills the feature.** The operational source alert sent 571
  messages for 26 real episodes before it was rewritten (ADR-0019), and in
  2026-10/11 it looped again on alternating failure signatures.
- **`hazards.batch_ingested` carries counts, not event ids.**
- **No accounts and no personal data in this stage.** The channel (an ntfy
  topic, a webhook URL) is the credential.
- **Naming**: "warning" is already AEMET's `weather_warning` and "zone" is
  coverage in ADR-0020. This feature uses _notification_, _watch area_ and
  _subscription_.

## Decision

### A new context: `app.notifications`

Layers cli -> event_handlers -> use_cases -> repos -> services -> schemas ->
models, enforced by import-linter (no HTTP API in this stage). It may import
`app.hazards.models`, `app.hazards.events`, `app.hazards.services` (pure:
geometry validation, source health) and `app.hazards.schemas`; a forbidden
contract keeps it out of hazards' api, use_cases, repos and event handlers.
Hazards never imports notifications, and analytics stays independent of it.
The source-health rule behind `/v1/sources/status` moves into
`app.hazards.services.source_health` so the endpoint and the notifications
share it.

Channel senders (ntfy, webhook) are infrastructure in `app.core.channels`,
with fake and http drivers chosen by `NOTIFICATIONS_DRIVER`, like the source
drivers.

### Watch areas

`watch_areas` stores what was asked and the geometry it resolves to:

- `kind`: `province` (INE code), `bbox` (lon/lat envelope) or `circle`
  (lon, lat, radius between 1 km and 200 km);
- `params` (JSONB) with those inputs and a `label`, for display;
- `geom`: the resolved MultiPolygon in EPSG:4326, materialized at creation
  (a circle is a geography buffer, exact in Canarias too);
- `match_geom`: what polygon events are matched against. For a province it
  is the province shrunk 1 km inward, so an AEMET zone that only grazes the
  border (or a simplification sliver, ADR-0013) does not notify the
  neighbor; for bbox and circle it equals `geom`. Point events (quakes) are
  matched against `geom`: an epicenter on the border belongs to it.

Provinces move into PostGIS as a `provinces` table (code, name, `geom`,
`inner_geom`), seeded by a migration from the same
`data/reference/provinces_es.parquet` the analytics plane reads, so both
planes share one source of truth. The 1 km inner geometry is computed once
in that migration; changing the margin is a new migration, and CI checks
that no province ends up empty.

### Subscriptions

`subscriptions`: watch area, `hazard_types` (a non-empty subset of the
three), `severity_min` (1-4, required, no default), channel `ntfy` (server +
topic) or `webhook` (https URL + per-subscription key), `status` (`active` /
`paused` with a reason), and the delivery retry state (see Delivery).

- **Hotspots never notify.** EFFIS notifies only for burnt areas.
- Stage 1 manages subscriptions with a CLI run inside the API container
  (`python -m app.notifications.cli`). There is no public endpoint yet. The
  CLI refuses to create subscriptions in production while the fake driver
  is configured, which would mark everything as sent without sending.
- The ntfy topic and the webhook key are credentials. The CLI generates
  them (they never travel in argv or shell history) and prints them once;
  they live in the database (and therefore in its backups) and are never
  returned again. Delivery errors are stored and logged without URLs: only
  the exception class, scheme and host.

### Finding what a batch changed

The three sync use cases add `batch_at` to the event payload: the
transaction timestamp (`SELECT now()` inside the sync transaction, read
after the upstream fetch). `now()` is constant within a transaction, so
every row the batch inserted, updated or closed carries exactly that value
in `created_at` (inserts) or `updated_at` (updates and closures), and the
handler selects precisely the batch:
`source = :source AND (created_at = :batch_at OR updated_at = :batch_at)`,
backed by indexes on `(source, created_at)` and `(source, updated_at)`.
Warnings and fires that vanish from their source are closed at `batch_at`,
not at the Python clock, which runs later than the transaction start and
would leave a withdrawn warning looking alive. Events published before this
change have no `batch_at` and are skipped with a log line.

### Matching produces episodes, not messages

A new outbox handler, `match_notifications`, runs after
`export_geoparquet`. It is database only: no network I/O, one transaction,
idempotent. It takes the batch's notifiable rows (AEMET: `ends_at >
batch_at`, which excludes closures and includes future onsets; EFFIS: open
burnt areas; IGN: quakes that started within the last 48 h, so a revision
sweep over the 10-day window cannot burst), keeps those that pass each
subscription's type and severity filters, intersects them with `match_geom`
/ `geom` (GiST), and assigns each match to an **episode**:

| Source           | Episode key                                           | The episode stays current while                   |
| ---------------- | ----------------------------------------------------- | ------------------------------------------------- |
| IGN earthquake   | `external_id`                                         | always (one quake, one episode)                   |
| EFFIS burnt area | `external_id` (stable `fire_id`, ADR-0015)            | always (a fire that grows keeps its id)           |
| AEMET warning    | phenomenon code (the part of `phenomenon` before `;`) | `expires_at` + 3 h grace is later than `batch_at` |

An AEMET episode's `expires_at` is the latest `ends_at` of the warnings
matched into it, as ingested. The grace covers the gap an Update leaves
when it closes the warning it supersedes; later early closures do not
shorten the episode. A match **notifies only when** its subscription has no
current episode for that key (the stale one is closed and a new one opens),
or when its severity is higher than the severity already notified in the
current episode (escalation). Everything else is silent: an AEMET Update at
the same level, a level that drops, a fire re-served unchanged, a revised
quake at the same severity, a closure. The rule is a pure function with
table-driven tests; no sweep job is needed.

`notification_episodes` (subscription, key, `notified_severity`,
`expires_at`, `opened_at`, `last_matched_at`, `closed_at`; a partial unique
index allows one open episode per subscription and key). Each notification
is a `notification_deliveries` row unique on `(episode_id, severity)` and
inserted with `ON CONFLICT DO NOTHING`, so a retried handler cannot
duplicate it. The row keeps a snapshot of the matched events as GeoJSON
Features, so delivery never reads `hazard_events`.

### Delivery is a separate job

A scheduled job, `notifications_deliver` (ADR-0002 jobs, every 60 s),
claims subscriptions with pending deliveries (`FOR UPDATE SKIP LOCKED`),
**groups their deliveries into one message per subscription and run** (up
to a fixed number of items, then "and N more"), sends outside any
transaction within a time budget shorter than the job timeout, and records
the outcome. Delivery is at-least-once: a crash between sending and
recording resends the same deliveries, and the webhook carries their ids so
receivers can deduplicate.

- **Retry state lives on the subscription**, not on each delivery, because
  one message carries all of a subscription's pending items:
  `consecutive_failures`, `failing_since`, `retry_at` (exponential backoff,
  capped at 1 h; also the claim's lease) and a sanitized `last_error`.
  After 24 h of uninterrupted failure the subscription is paused with the
  reason and its pending deliveries are marked failed, so a later resume
  does not send stale items. It does not resume by itself.
- **Minimum interval** between messages per subscription (10 min). What
  arrives meanwhile stays pending and goes out grouped in the next message:
  nothing is dropped, it only arrives batched.
- Why not send from the outbox handler: its timeout and retries cover the
  whole handler, a slow webhook would hold the outbox, and grouping per run
  is what keeps one bulletin from becoming dozens of messages.

Channels:

- **ntfy**: JSON publish to the server root (`topic`, `title`, `message`,
  `priority`, `tags`, `click`), which keeps the topic out of URLs and UTF-8
  out of headers. Priority from severity (1 -> 2, 2 -> 3, 3 -> 4, 4 -> 5),
  body capped at ntfy's 4,096 bytes, click URL to the event
  (`/v1/events/{id}` until the frontend exists).
- **webhook**: `POST` of a versioned JSON envelope (`version`, message id,
  subscription id, `sent_at`, items with delivery id, episode id, reason
  `opened` / `escalated` and the event as a GeoJSON Feature, the
  not-official notice, attribution, degraded sources). Signed with
  `X-Geohazard-Signature: t=<unix>,v1=<hex HMAC-SHA256(key, "<t>.<body>")>`
  so the receiver can check integrity and freshness.
- **Outbound guard** for both: https only, no redirects, no proxy from the
  environment, a total timeout (10 s), and every address the host resolves
  to must be global, checked at creation and before each send. The API
  shares its server with other services and must not become a way to reach
  them. Pinning the resolved address against DNS rebinding is left for the
  stage that opens subscriptions to the public; in this one only the
  operator creates them.

Every message states that it is not an official alert and names the
official channel, carries the source attribution its licence requires
(`app/core/attribution.py`), and says so when a source it depends on is
degraded (`source_health`), so silence is not read as "nothing is
happening". There are no separate "source degraded" notifications in this
stage: they flap. Times are shown in Europe/Madrid (Atlantic/Canary west of
13 W). Texts are Spanish and live in one module, ready for i18n when the
frontend arrives.

### Retention

Sent or failed deliveries are kept 90 days. Episodes are purged 90 days
after they were closed or last matched (IGN and EFFIS episodes never close)
when they have no pending delivery. The delivery job purges both.

## Consequences

- New tables: `provinces`, `watch_areas`, `subscriptions`,
  `notification_episodes`, `notification_deliveries`; a new seeded job row.
- The three sync use cases gain `batch_at` in their payload and close
  vanished events at it; `hazard_events` gains two indexes, built
  concurrently because the table is live during deploys.
  `export_geoparquet` ignores the new key.
- import-linter: a layers contract for notifications, the restricted
  surface towards hazards, a forbidden contract hazards -> notifications,
  independence between analytics and notifications, and wiring allowances
  for `db_registry` and the delivery job handler.
- End-to-end latency is the source cadence plus the outbox poll (up to 5 s)
  plus the delivery job (up to 60 s) plus the minimum interval when a
  message just went out.
- Provinces now exist in both planes from the same file; regenerating the
  reference (ADR-0013 script) means a new seeding migration too.
- Observability is the CLI (`list` shows paused subscriptions and their
  last error, `stats` messages per week) and the logs; nobody is paged for
  a paused subscription in this stage, and there is no Prometheus counter:
  `/metrics` has no consumer and a per-process counter resets on deploy.
- Accepted limits for this stage: a heatwave that AEMET extends day after
  day is one episode, so later days merge silently into it; a change in
  what feeds `content_hash` re-updates live events and can produce one
  grouped burst of "opened" items; a new subscription does not backfill
  events already in force; an outbox event that exhausts its retries (about
  8 minutes of database outage) never notifies unless it is replayed by
  hand (`status = 'PENDING', retry_count = 0`).
- The first values of the knobs (1 km inward margin, 3 h grace, 48 h quake
  age, 10 min interval, items per message, 24 h pause) are guesses. A few
  weeks of real use by the operator, measuring messages per week and false
  positives, set them before anyone else subscribes.
- The tables are built so the next stages are additions: a public API with
  an unguessable per-subscription management token when the frontend
  exists, then email and accounts for the public opening. Each gets its own
  ADR.

## Alternatives considered

- **One notification per changed row**: re-notifies every AEMET Update and
  every re-served fire. Rejected; it is the spam this design exists to
  avoid.
- **Matching inside each sync use case**: couples ingest to notifications
  and makes hazards import them. The outbox already decouples consumers.
- **Event ids in the payload** instead of `batch_at`: a first EFFIS sync
  touches thousands of rows. **A watermark cursor**: needs its own state
  and breaks with out-of-order commits. The transaction timestamp is exact
  and free.
- **AEMET episodes that stay current while an unexpired warning remains**:
  an Update closes the warning it supersedes in the same batch that brings
  its replacement, so the episode would look dead and re-notify every
  Update. Hence `expires_at` plus grace.
- **Retry state per delivery**: one message groups several deliveries, so
  per-delivery backoff would send fresh items while older ones wait.
- **Public per-province ntfy topics** with no subscription state at all:
  cheapest, but no bbox or circle and no per-user severity, both wanted
  from the start.
