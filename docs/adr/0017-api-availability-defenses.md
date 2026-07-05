# 0017 - API availability defenses

Status: Accepted
Date: 2026-07-05

## Context

The API is public and unauthenticated by design (it serves open data). An
audit found one HIGH finding: `GET /events/clusters` ran an
`ST_ClusterDBSCAN` window function over the whole filtered table with every
filter optional and no output cap, on a 1 GB-class host shared with Postgres
and two other projects. Anyone could force a 200 km-neighborhood DBSCAN over
every event, repeatedly - a trivial CPU/RAM exhaustion. The reverse proxy
(Caddy) sets security headers and TLS but does NOT rate limit, and production
had `statement_timeout = 0`. The analytical plane shares a single DuckDB
connection (`threads=2`, `memory_limit=512MB`) across up to ~40 threadpool
requests, so a burst of heavy queries can OOM.

Closing access is not an option (open data). The defense is to bound the cost
per request and per client.

## Decision

Four coordinated defenses, all app-side and versioned in the repo so they do
not depend on server configuration we cannot review:

1. **Bounded `/clusters`.** The endpoint requires at least one bounding
   filter - a `bbox` or a temporal window (`starts_after`) - or it returns
   `400 business_validation` without touching the database. When present, the
   `bbox` prefilters on the GiST before the DBSCAN, and the output is capped
   at 500 clusters. The `eps_m`/`min_points` ceilings stay; the bounding
   filter plus the statement timeout are the real defense.

2. **Rate limiting per IP (slowapi).** In the app, not in Caddy: it stays in
   the repo, is testable, and the host's Caddy is a distro package without the
   rate-limit plugin. A generous global default (120/min) protects everything;
   a stricter limit (20/min) guards the compute endpoints (`/clusters`,
   `/analytics/*`) via a decorator. The client IP comes from `X-Forwarded-For`
   (Caddy is the only ingress; the app binds to 127.0.0.1, so trusting that
   header is safe). Over-limit responses use the homogeneous `{detail, code}`
   envelope with `Retry-After`. Counters live in memory (single instance) and
   reset on redeploy - acceptable for this scale.

3. **Statement timeouts, two levels.** A moderate global default in
   `compose.yml` (`statement_timeout=30s`, `lock_timeout=5s`) is a transversal
   net for any connection. The API engine sets a stricter 10s via asyncpg
   `server_settings` for the connections that serve public requests (and the
   workers, whose Postgres statements are sub-second). Migrations run on their
   own connection and are exempted (`SET statement_timeout = 0` in
   `migrations/env.py`) so a long DDL on a grown dataset never aborts a deploy.

4. **Bounded analytical concurrency.** An `anyio.CapacityLimiter` caps
   concurrent DuckDB queries; if no slot frees within a short window, the
   request is rejected with `503 service_overloaded` + `Retry-After` instead
   of piling up toward an OOM.

Alongside these, the two source drivers stream upstream responses with a byte
cap (50 MB) instead of buffering the whole body, and the AEMET tar reader
guards member size and count (tar-bomb defense).

## Consequences

- `/clusters` callers must now pass a bbox or a time window; a call with no
  filters is a 400, not an unbounded scan. This is a deliberate contract
  change (the only consumer is the project's own frontend).
- Rate-limit counters reset on every redeploy; a client's budget refreshes
  then. For a single-instance open-data API that is fine; a multi-instance or
  shared-budget setup would need a shared store (Redis), which we do not run.
- The global statement timeout means any future migration that legitimately
  needs longer must keep the explicit exemption; the API's 10s ceiling caps
  the DBSCAN and every other request query.
- The analytical 503 is a load-shedding signal, not an error: clients should
  honor `Retry-After`. It also gives the API its first `Retry-After` on a 503.
- Rate limiting lives in the app and is independent of whatever the reverse
  proxy does; if Caddy later gains rate limiting, the two compose (defense in
  depth), they do not conflict.
