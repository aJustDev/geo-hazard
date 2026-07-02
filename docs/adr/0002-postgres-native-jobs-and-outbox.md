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
