# 0018 - Backups and disaster recovery

Status: Accepted
Date: 2026-07-05

## Context

The audit found one materially HIGH gap in an otherwise solid ops story: there
was NO backup or disaster-recovery strategy at all. Verified on the production
host - no cron, no systemd timer, no script, no restic/rclone. Two distinct
losses were unprotected:

- A bad migration or accidental write corrupts the operational database. The
  event data itself is re-derivable (the sources serve rolling windows and we
  re-ingest), but a broken schema or a truncated table has no recovery point.
- The `geohazard_data` volume holds the accumulated GeoParquet history. That is
  the ONE irreproducible asset: the upstreams only serve rolling windows, so
  the history we have snapshotted since the first ingest (ADR-0007) cannot be
  rebuilt from anywhere. Losing that volume is permanent data loss.

The host has 174 GB free and a working local MTA (`exim4`). There is no offsite
storage account provisioned, and choosing one (destination, credentials, cost)
is a pending decision the owner has not made.

## Decision

Local, tested backups now; offsite prepared but deferred.

- **Two artifacts, daily** ([`ops/backup.sh`](../../ops/backup.sh)): a logical
  `pg_dump` of the database (compressed with zstd, gzip fallback) and a `tar` of
  the `geohazard_data` volume. The dump uses `--no-owner --no-acl --clean
--if-exists` so it restores onto any target, empty or populated, as a single
  role.
- **Retention**: 7 daily + 4 weekly (the weekly copy is promoted on Sundays).
  Pruning is by age (`find -mtime`).
- **Backup destination is OUTSIDE the checkout** (`/srv/geohazard-backups` by
  default). The deploy does `git reset --hard`; backups must not live where that
  can touch them.
- **Scheduling** via a systemd timer
  ([`ops/systemd/geohazard-backup.timer`](../../ops/systemd/geohazard-backup.timer),
  `OnCalendar=daily`, `Persistent=true`) running as the deploy user. A cron line
  is documented as the fallback where systemd is not usable.
- **Pre-migration snapshot** ([`ops/deploy.sh`](../../ops/deploy.sh)): the deploy
  takes a quick DB-only `pg_dump` to `pre-migrate/` between the image build and
  the Alembic run. It never aborts the deploy if it fails; it is a rollback
  point if a migration writes badly. Keeps the last 5.
- **Restore is tested, not assumed** ([`ops/restore.sh`](../../ops/restore.sh)):
  a backup that has never been restored is not a backup. The script boots a
  throwaway PostGIS container, restores the dump into it, prints `hazard_events`
  counts per source, and destroys it. This is the repeatable DR drill; it also
  runs against production dumps on the host (into a throwaway, non-destructive)
  to confirm the counts match.
- **Offsite is a marked hook, deferred.** `backup.sh` has an explicit place to
  push the daily artifacts with restic once a destination is chosen. Until then
  the coverage is explicit (see below).

## Consequences

- **What is covered**: a bad migration (pre-migration snapshot + daily dump),
  accidental corruption of the database, and loss/corruption of the GeoParquet
  volume (the daily volume tar). RPO is up to 24h (last daily) or the moment of
  the last deploy (pre-migration snapshot); RTO is a `restore.sh` run plus a
  volume `tar -x`, minutes.
- **What is NOT covered, and accepted**: total loss of the VPS (disk failure,
  provider incident). The backups live on the same host. This is a deliberate,
  documented risk while offsite storage is unprovisioned; the restic hook is in
  place so closing it is additive, not a rewrite.
- The backup user must be able to write to `BACKUP_DIR`; if it cannot, the
  pre-migration snapshot is skipped with a warning rather than failing the
  deploy.
- Backups are excluded from git (`.gitignore`) as a belt-and-suspenders measure
  even though the default destination is outside the tree.
