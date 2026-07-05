# Deployment

Push-to-deploy to a single production host running Docker Compose behind a
reverse proxy (Caddy). No registry, no orchestrator: the server builds the
image it runs (ADR-0014).

## Flow

1. Push to `main` -> the `CI` workflow runs lint, types, architecture
   contracts and both test suites.
2. When CI succeeds, the `Deploy` workflow fires (`workflow_run`). It never
   sees a commit that broke CI.
3. The workflow opens an SSH connection with a dedicated key. On the server
   that key is pinned in `authorized_keys` to a single command
   (`command="/usr/local/bin/deploy_geohazard"`, plus `no-pty`,
   `no-port-forwarding`, `restrict`): even if the key leaked, all it can do
   is trigger a deploy.
4. The server-side script (source of truth: [`ops/deploy.sh`](../ops/deploy.sh))
   resets the checkout to `origin/main`, builds the images, runs Alembic
   migrations as a blocking one-shot container, recreates the API and smoke
   tests it locally.
5. The workflow finishes with a public smoke test through the reverse proxy:
   `https://geohazard.ajustino.dev/v1/health/liveness`.

## GitHub configuration

Secrets (server identity never appears in the repo):

| Secret                     | Content                           |
| -------------------------- | --------------------------------- |
| `GEOHAZARD_DEPLOY_SSH_KEY` | private ed25519 key (deploy-only) |
| `GEOHAZARD_DEPLOY_HOST`    | server address                    |
| `GEOHAZARD_DEPLOY_PORT`    | sshd port                         |
| `GEOHAZARD_DEPLOY_USER`    | unix user                         |

Repository variable `GEOHAZARD_DEPLOY_ENABLED` is the master switch: the
deploy job is skipped unless it is `true`. It stays `false` until the DNS
record and the server provisioning exist, so enabling deploys is an explicit,
auditable act.

## Server layout

- `/opt/geohazard`: git checkout of this repo. Runtime configuration lives
  ONLY in `/opt/geohazard/.env` (database credentials, `AEMET_API_KEY`,
  `*_DRIVER=http`); it is never committed.
- [`compose.yml`](../compose.yml) (production): PostGIS on
  `127.0.0.1:5436`, API on `127.0.0.1:8002`, both with explicit memory
  limits. Named volumes: `geohazard_pgdata` (database) and `geohazard_data`
  (GeoParquet snapshots - the accumulated history, ADR-0007).
- The reverse proxy owns TLS and forwards `geohazard.ajustino.dev` to
  `localhost:8002`.

## Operational notes

- All three sources (EFFIS, IGN, AEMET) sync in production. A source can be
  paused as data, not code: `UPDATE scheduled_jobs SET next_run_at =
'infinity' WHERE job_name = '<source>_sync';` - the scheduler only claims
  jobs with `next_run_at <= now()`, and `'infinity'` survives every deploy.
  Reactivate with `next_run_at = now()`.
- Migrations run BEFORE the API container is recreated; a failing migration
  aborts the deploy and leaves the previous API running.
- A deploy is idempotent: re-running it converges to the same state.

### Availability defenses (ADR-0017)

- **Statement timeouts.** `compose.yml` sets a transversal
  `statement_timeout=30s` and `lock_timeout=5s` on the database; the API
  engine tightens `statement_timeout` to 10s (`DB_STATEMENT_TIMEOUT_MS`).
  Migrations are exempted in `migrations/env.py` (`SET statement_timeout=0`),
  so a long DDL never aborts a deploy. Verify after deploy with
  `docker exec geohazard-db psql -U "$DB_USER" -d "$DB_NAME" -c "SHOW
statement_timeout"` (expect `30s`).
- **Rate limiting** is enforced in the app (slowapi), keyed on
  `X-Forwarded-For` from Caddy: a generous global limit plus a stricter one on
  `/clusters` and `/analytics/*`. Tune via `RATE_LIMIT_*`; counters are
  in-memory and reset on redeploy. A burst over the limit returns `429` with a
  `Retry-After` header.
- **`/clusters` requires a bounding filter** (`bbox` or `starts_after`); a
  call with neither is a `400`, by design.
