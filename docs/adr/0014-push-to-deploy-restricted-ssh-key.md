# 0014 - Push-to-deploy over a command-restricted SSH key

Status: Accepted
Date: 2026-07-03

## Context

Production is one small shared server running Docker Compose behind Caddy.
The deployment options considered: a container registry plus a puller
(watchtower or cron), a self-hosted runner on the server, or plain SSH from
GitHub Actions. A registry adds an account, a token and image lifecycle
management to ship to exactly one machine; a self-hosted runner hands the
server a standing GitHub credential and a daemon to babysit.

## Decision

Plain SSH, with the blast radius cut down on both ends:

- The `Deploy` workflow only fires via `workflow_run` when `CI` concluded
  successfully on `main`: broken commits never reach the server.
- The SSH key is dedicated to deploying. In `authorized_keys` it is pinned
  with `command="/usr/local/bin/deploy_geohazard"` plus `no-pty`,
  `no-port-forwarding`, `no-agent-forwarding`, `no-X11-forwarding` and
  `restrict`: the workflow does not even send a command, and a leaked key
  can only trigger a deploy, never open a shell.
- Server identity (host, port, user) lives in GitHub secrets; the repo never
  names the machine.
- The server-side script (`ops/deploy.sh` in the repo, installed at
  provisioning time) is the whole deploy: reset to `origin/main`, build,
  blocking Alembic migration container, recreate API, local smoke test. The
  workflow adds a public smoke test through the proxy.
- A repository variable (`GEOHAZARD_DEPLOY_ENABLED`) gates the job, so the
  pipeline can merge before the infrastructure (DNS, provisioning) exists
  and enabling it is an explicit act.

## Consequences

- The server builds images itself: a deploy costs it one or two minutes of
  CPU. Acceptable at this scale; a registry is the escape hatch if it hurts.
- `git reset --hard` means the checkout is disposable; anything mutable
  (`.env`, volumes) lives outside it by construction.
- The installed script and `ops/deploy.sh` can drift; the file header names
  the repo copy as source of truth and drift is caught the next time the
  script is reinstalled. The alternative (executing the freshly-pulled
  script) risks bash reading a file that mutates mid-run.
