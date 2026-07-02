# 0003 - Layered architecture enforced with import-linter

Status: Accepted
Date: 2026-07-02

## Context

The codebase splits into a generic engine (`app/core`: config, db, generic
repo, jobs, outbox, exceptions) and domain contexts that will arrive in later
phases: `app/hazards` (operational plane, PostGIS) and `app/analytics`
(analytical plane, DuckDB over GeoParquet). Layer discipline that lives only
in code review erodes; one convenient import at a time.

## Decision

Encode the architecture as import-linter contracts (`.importlinter`), checked
in CI next to lint and types:

- `app.core` must not import `app.api`, `app.deps` or `app.main` (in force
  now). When the domain contexts land, `app.core` must not import them either,
  with the composition root (`db_registry`) and the per-source job handlers as
  the only named wiring exceptions.
- Each domain context declares internal layers:
  `api -> use_cases -> repos/services -> schemas -> models`.
- `app.hazards` and `app.analytics` must not import each other. This is the
  operational/analytical boundary of the project: the analytical plane reads
  GeoParquet files, never Postgres, and the contract makes that structural
  instead of aspirational.

## Consequences

- Architectural violations fail CI with the offending import chain printed.
- Exceptions are visible and auditable: every `ignore_imports` line carries a
  comment explaining why it exists.
- The contracts grow with the phases; adding a context means adding its
  contract in the same PR.
