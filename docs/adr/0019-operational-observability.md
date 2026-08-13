# 0019 - Operational observability

Status: Accepted
Date: 2026-07-05

## Context

Observability was limited to unstructured logs on stdout. There was no way to
answer "are the sources fresh?" without opening a psql session, no request
correlation across log lines, and no metrics. The `consecutive_failures` column
on `source_sync_state` was written by the sync jobs and read by nobody, so a
source that had been failing for hours raised no signal. The host runs no
Prometheus/Grafana and none is planned short-term.

This ADR adds the cheap, high-leverage pieces that make the system operable and
transparent, without standing up a monitoring stack it does not need yet.

## Decision

Four parts.

1. **`GET /v1/sources/status`** as a trust-and-alert surface. It reads
   `source_sync_state` and joins the per-source cadence from `scheduled_jobs`
   (convention `job_name = "{source}_sync"`) to judge freshness against each
   source's OWN interval, not a fixed threshold - EFFIS syncs every 4h and a
   flat threshold would false-alarm. A source is `stale` if it has gone longer
   than `SOURCE_STALENESS_FACTOR` (3) times its interval without a success (or
   never succeeded), and `healthy` when it is neither stale nor over
   `SOURCE_MAX_FAILURES` (3) consecutive failures. Sources that are scheduled
   but have never recorded a run appear as degraded rather than silently
   missing. The endpoint lives in `app.api` because it crosses two contexts
   (hazards' sync state and core's job cadence); both imports are legal.

2. **Structured JSON logs with a request-id.** A `contextvar` carries a
   request-id set by the outermost middleware (incoming `X-Request-ID` honored,
   else a uuid4), returned in the response header and injected into every log
   record by a filter. `log_config.json` is the single source of truth for the
   format (app logs and uvicorn access logs), wired via uvicorn `--log-config`.

3. **`GET /metrics`** (Prometheus, via starlette-exporter), app-level and
   outside the `/v1` prefix, placed outside the rate limiter so it also counts
   429s. It is a prepared hook: no scraper consumes it yet. It is private -
   Caddy returns 404 for it at the edge; a co-located Prometheus would reach it
   over the docker network.

4. **Alerting by cron + local mail** ([`ops/check-sources.sh`](../../ops/check-sources.sh)):
   a cron job polls `/v1/sources/status` and, when the status is not `ok` or the
   API does not answer, sends a mail via the host's `exim4`. Silent when healthy.
   _Superseded on 2026-08-13, see the amendment below._

## Consequences

- `/sources/status` gives integrators an honest freshness view and gives the
  alert (part 4) its data surface, closing the loop on `consecutive_failures`.
- Request-ids correlate the app log lines of a single request and reach the
  client via the response header. **Known limitation**: uvicorn's access-log
  line is emitted after the response, outside the contextvar's scope, so it
  carries `request_id: "-"`. App logs within the request carry the real id;
  correlating the access line would need a pure-ASGI middleware that leaks the
  id across the connection, which is not worth it.
- `/metrics` has low immediate value with no scraper, but the hook is cheap and
  ready. **Known limitation**: FastAPI 0.139 nests included routers as
  `_IncludedRouter`, which starlette-exporter 0.23 cannot resolve, so
  `group_paths` does not template paths (e.g. `/v1/events/{id}` is seen by URL)
  and `filter_unhandled_paths=True` would drop ALL series. It is therefore set
  to `False`: every request is recorded, at the cost that a 404 scanner can
  create per-path series (bounded by frequent restarts and the container memory
  limit). This self-heals when the library learns `_IncludedRouter`; revisit
  when a real scraper is deployed.
- **Alerting is blind to a full host outage**: if the host is down, nothing
  sends the mail. Accepted for now; the gap closes with an external dead-man's
  switch, out of scope here. We deliberately do NOT run Prometheus/Alertmanager:
  it is disproportionate for a single small host, and cron+mail covers the one
  question that matters today ("did a source go stale?"). _The second half of
  that sentence was wrong about the host and is corrected in the amendment
  below; the conclusion for geohazard still holds._

## Amendment (2026-08-13): edge-triggered alerts, push instead of mail

Part 4 as shipped was wrong in two ways, and a month of production said so.

**It went nowhere.** cartagena's `exim4` runs in `local` mode with no
smarthost, so `mail` only ever wrote to `/var/mail/ductual`. Between 2026-07-06
and 2026-08-08 it accumulated **571 alerts that nobody read**.

**It was level-triggered.** The cron re-sent the same alert every 20 minutes for
as long as a source stayed degraded, so those 571 messages were only **26 real
episodes**. The distribution is the opposite of the intuition: `aemet` degraded
16 times and `effis` only 8, but the EFFIS outages ran 56h, 32h and 24h without
a break, which is what filled the mailbox.

Changed:

- The alert now goes through the host notifier `notify-cartagena.sh` (ntfy push
  plus Telegram), the same channel the rest of the host uses.
- It is **edge-triggered**: it fires when the set of unhealthy sources changes,
  including the recovery edge, and repeats an open episode once every 24h so a
  multi-day outage does not disappear after one message. State lives in
  `~/.local/state/geohazard-sources.state`.
- **Severity is per source.** `aemet` and `ign` feed weather warnings and
  earthquakes, so they page at priority 4; a full API outage pages at 5. EFFIS
  alone drops to priority 3, because ADR-0015 already classifies the gwis
  MapServer as intermittent by design (HTTP 500 for hours, retried next cycle,
  nothing corrupted) and explicitly asks for no human to be paged on it.

The host-outage gap is unchanged, and is now genuinely covered by the external
dead-man's switch (`ductual-healthcheck.timer` pinging healthchecks.io).

### Correction: a Prometheus stack does run on this host

The original text claims we do not run Prometheus/Alertmanager because it would
be disproportionate for a single small host. That was never true of the host.
cartagena has been running Prometheus, Alertmanager, Grafana, Loki, Tempo,
Alloy, node-exporter, cAdvisor and postgres-exporter for months — nine of its
eighteen containers — with eight alert rules and a working SMTP path. It serves
the sibling project (ductual) and scrapes nothing else.

That stack stays scoped to ductual **by decision, not by oversight**. geohazard,
apsis and shade are small side projects serving `ajustino.dev`; the question
worth alerting on for them is "did ingest go stale?", which the edge-triggered
cron above answers in fifteen lines and one push notification. Wiring three more
targets into a Grafana stack would add operational surface without answering a
question anyone is asking.

So the decision stands and the reasoning is replaced: geohazard stays out of
Prometheus because metrics-based alerting is disproportionate **for geohazard**,
not because the host cannot host it. The practical consequence is that the
`/metrics` endpoint this ADR exposes has no consumer, and the Caddy rule that
returns 404 for it publicly is the whole of its access policy.
