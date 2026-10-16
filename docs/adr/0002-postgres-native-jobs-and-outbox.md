# 0002 - Postgres-native jobs and transactional outbox, no broker

Status: Accepted
Date: 2026-07-02

## Context

The catalogs must be polled on a schedule (three sync jobs) and every ingest
must trigger derived work (GeoParquet snapshot exports) reliably: if a batch
is written, its export event must not be lost; if the transaction rolls back,
the event must not exist.

The conventional answer is a broker (Celery + Redis/RabbitMQ). The expected
volume here is a handful of jobs and tens of events per hour, and the service
runs on a small shared server.

## Decision

Run both concerns on PostgreSQL itself, following the pattern published in
[apsis](https://github.com/aJustDev/apsis):

- `scheduled_jobs`: one row per recurring job. Workers claim with an atomic
  `UPDATE ... WHERE status='PENDING' RETURNING` (optimistic claim) plus a
  lease (`lease_until`) so a crashed worker's job is recovered by the next
  poll. Fits few long-lived rows.
- `outbox_events`: events are inserted in the same transaction as the domain
  write (`EventBus.publish` never commits). A worker dispatches one event per
  transaction with `SELECT ... FOR UPDATE SKIP LOCKED`, with per-handler state
  for idempotent retries and exponential backoff with jitter. LISTEN/NOTIFY is
  a wake-up optimization; the poll is the source of truth.

## Consequences

- One less piece of infrastructure to run, monitor and pay for; events are
  atomic with the writes that produce them by construction.
- Delivery is at-least-once: every event handler must be idempotent (the
  snapshot export naturally is: it rewrites the file).
- Throughput ceiling is a non-issue at this scale, but the pattern is not the
  right call for high-volume fan-out; that trade-off is documented upstream in
  apsis' ADRs.

## Amendment (2026-10-16): the outbox worker is poll-only

The LISTEN/NOTIFY "wake-up optimization" never woke anything: the callback
only logged, and the loop waited on the shutdown event alone. It cost a raw
asyncpg connection per worker, a heartbeat, and a `pg_notify` per publish. It
is removed; the outbox worker now polls every `OUTBOX_POLL_INTERVAL_SECONDS`
(5 s) and backs off exponentially (capped at 60 s) while the database errors.

Why not wire it instead: the only consumer today is the snapshot export, and
end-to-end latency is set by the sources' sync cadence (IGN 15 min, AEMET 30
min, EFFIS 4 h), not by the poll. Even a future push consumer (webhooks) would
gain under 1% from it. If latency ever matters, lowering the poll interval is
the cheap lever (one indexed `SKIP LOCKED` select on a small table); wiring
NOTIFY back means a listener that sets an `asyncio.Event` the loop waits on,
recoverable from this commit's parent.
