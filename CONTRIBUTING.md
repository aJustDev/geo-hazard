# Contributing

## Requirements

- [uv](https://docs.astral.sh/uv/) (it installs Python 3.14 for you).
- Docker: the development database and the integration tests
  (testcontainers) run PostGIS in containers.
- [just](https://just.systems/) is optional. Every recipe in the `justfile`
  is a plain command you can copy.

## Local setup

```sh
uv sync                      # runtime + dev dependencies from uv.lock
cp .env.example .env.local   # local config (gitignored)
just db                      # PostGIS on 127.0.0.1:5433 (compose.dev.yml)
just migrate                 # alembic upgrade head
just run                     # API with reload: http://127.0.0.1:8000/docs
```

The source drivers default to `fake`: the app ingests a few canned events and
needs no network. Set `EFFIS_DRIVER`, `IGN_DRIVER` and `AEMET_DRIVER` to
`http` in `.env.local` to sync the real sources (AEMET also needs a free
`AEMET_API_KEY` from [AEMET OpenData](https://opendata.aemet.es/)).

`compose.yml` is the production stack. Plain `docker compose up` picks it, so
use `just db` (or `-f compose.dev.yml`) for development.

## Tests and checks

| Command         | What it runs                                                                |
| --------------- | --------------------------------------------------------------------------- |
| `just test`     | Unit tests: no network, no Docker. Takes pytest arguments.                  |
| `just test-all` | What CI runs: unit + integration (real PostGIS) + coverage gates per layer. |
| `just contract` | Contract tests against the live upstreams (network; nightly in CI).         |
| `just lint`     | ruff, ruff format, mypy (strict) and the import-linter contracts.           |
| `just audit`    | pip-audit and the license policy (no GPL/AGPL/LGPL in the tree).            |
| `just fmt`      | Applies ruff fixes and formatting.                                          |

CI must be green before merging, and every push to `main` deploys.

## Conventions

- **Architecture is enforced, not suggested.** Layers and the boundary between
  the operational (`app.hazards`) and analytical (`app.analytics`) planes are
  import-linter contracts (`.importlinter`, ADR-0003, ADR-0012). If a change
  needs to break one, it needs an ADR first.
- **Significant design changes get an ADR** in `docs/adr/`: `Status`, `Date`,
  Context / Decision / Consequences, and a row in the index. Later changes to
  an accepted ADR are appended as a dated amendment.
- **Every fix ships with a test that fails without it.**
- **Language**: code comments and commit messages are in Spanish
  (Conventional Commits, e.g. `fix(jobs): ...`); public-facing docs (README,
  ADRs, OpenAPI descriptions) are in English.

## Adding a source

1. Capture real responses and document the endpoint and its quirks in
   `docs/sources.md`; keep the captures as fixtures in `tests/fixtures/`.
2. Write the driver in `app/core/<source>/` following the existing ones: an
   `http` driver with a byte cap and timeouts, a `fake` driver, and a parser
   that skips malformed records with an aggregated warning instead of failing
   the batch. Map network failures to `*TransientError` and contract changes
   to `*ProtocolError`.
3. Add a sync use case and a job handler, and seed the job in a migration.
4. Add a contract test in `tests/contract/`.
5. Add the credit the source's licence requires to `app/core/attribution.py`
   and `NOTICE`.

ADR-0020 describes where this is heading: sources and zones as configuration.
