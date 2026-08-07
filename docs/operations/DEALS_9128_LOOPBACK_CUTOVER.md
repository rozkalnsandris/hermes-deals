# Deals 9128 loopback cutover

Issue: #307

## Goal

Move the Hermes Deals web origin from the production LAN address `192.168.0.180:9128` to loopback-only `127.0.0.1:9128` without making the application responsible for the shared Cloudflare connector and without an avoidable origin outage window.

The final desired application contract is already represented by the base Compose default:

```text
${DEALS_BIND_IP:-127.0.0.1}:${DEALS_HTTP_PORT:-9128}:80
```

The production `.env` currently overrides that default to the LAN address. `.env.example` now documents the desired loopback value for new/future production configuration.

## Production evidence captured before this change

The read-only issue #307 audit established:

- production worktree: `/home/andris/hermes-deals`;
- deployed worktree HEAD: `24d7e9e5d82b9c9971b3f69b8390ceb757c89840`;
- current GitHub-main audit snapshot: `e0c40f380a8da83bb1344e3b9af400779cde8a41`;
- live web container: `hermes-deals-web-1`;
- live web image ID: `sha256:97d490c12ba55b4946b01546d1c3ed324e8d41ab1c9fcb2a616aa470620e5b46`;
- live binding: exactly `192.168.0.180:9128 -> 80/tcp`;
- loopback `127.0.0.1:9128`: closed;
- LAN `192.168.0.180:9128`: open;
- no UFW `9128/tcp` LAN rule;
- Cloudflare connector: healthy with four HA connections;
- production Git index/worktree and live container identity were unchanged by the audit.

The normal GitHub-main deploy helper changes only the API service and explicitly requires the web container to remain unchanged. Therefore this migration uses a separate one-time web-runtime operator and does not hide a web recreation inside the normal API deploy path.

## Ownership boundary

The application-owned operator may recreate only the Hermes Deals `web` service and may create/remove its private issue-307 state files.

It must not:

- start, stop, restart, install or reconfigure `cloudflared.service`;
- read or hold the Cloudflare tunnel token;
- mutate Cloudflare routes or Access policy;
- mutate UFW;
- recreate the API or database containers;
- execute collectors, migrations or database writes;
- pull/prune/remove images;
- fast-forward, reset or otherwise mutate the production Git worktree.

The Cloudflare route remains a separately authorized control-plane change.

## Why a temporary dual bind is required

The current listener serves only `192.168.0.180:9128`, so changing the Cloudflare route to `127.0.0.1:9128` first would point the tunnel at a closed socket. Recreating the web service as loopback-only first would instead make the still-LAN Cloudflare route fail.

The transition therefore adds a second *specific* loopback mapping temporarily:

```text
192.168.0.180:9128 -> 80/tcp
127.0.0.1:9128   -> 80/tcp
```

No wildcard `0.0.0.0:9128` publish is permitted.

Docker Compose merges the production base file with a root-owned issue-307 override. Before any recreation, `docker compose config --format json` must resolve the web service to exactly those two bindings.

## Phase A — source review and merge

This change adds:

- `tools/runner/release/hermes-deals-web-dual-bind-cutover`;
- focused contract tests;
- loopback `DEALS_BIND_IP` in `.env.example`;
- this runbook.

Merging Phase A does not change production.

## Phase B — read-only check

Run the merged operator in `check` mode from a reviewed exact source copy. It must prove:

- the production `.env` still has exactly one `DEALS_BIND_IP=192.168.0.180` entry without printing the rest of `.env`;
- web/API/database containers are running;
- the web container belongs to project `hermes-deals`, service `web`, working directory `/home/andris/hermes-deals`;
- binding is LAN-only;
- LAN health passes and loopback is closed;
- no `9128/tcp` UFW rule exists;
- `cloudflared.service` is active and HA count is four;
- no issue-307 transition state already exists.

## Phase C — temporary dual bind

`apply-dual` writes only root-owned `0600` state/override files under:

```text
/var/lib/hermes-deals-ops/issue-307/
```

It then validates the merged Compose model and recreates only `web` with `--no-deps --no-build --pull never`.

After the recreation it must prove:

- both specific 9128 bindings exist and no other web publish exists;
- both LAN and loopback `/api/health` calls pass;
- API and database container IDs are unchanged;
- web image ID is unchanged;
- Cloudflare PID and HA count are unchanged.

If the mutation path fails before successful verification, the operator attempts an automatic return to the original LAN-only base Compose state.

## Phase D — separately authorized Cloudflare route cutover

Only after `verify-dual` passes, change the Cloudflare route for `deals.rozkalns.net` from:

```text
http://192.168.0.180:9128
```

to:

```text
http://127.0.0.1:9128
```

Do not change the shared connector lifecycle or Access policy.

Because Deals is protected by Cloudflare Access, an authenticated browser/service-auth check must be used to prove the external application path after the route change. An unauthenticated Access redirect by itself is not origin-health evidence.

## Rollback during the dual-bind phase

Before the Cloudflare route changes, or after it has explicitly been returned to the LAN origin, the operator can run `rollback-lan` only with:

```text
DEALS_307_ROUTE_LAN_CONFIRMED=yes
```

That mode recreates only `web` from the original base Compose file, verifies LAN-only health, and removes the private issue-307 state files.

Do not invoke `rollback-lan` while Cloudflare still points to loopback.

## Final loopback-only phase

Phase A deliberately does **not** remove the LAN binding. After the Cloudflare route is independently proven on loopback, a follow-up reviewed change will:

1. change only the production `DEALS_BIND_IP` value to `127.0.0.1` without exposing other `.env` values;
2. recreate only the web service from the base Compose file;
3. prove loopback-only binding and direct-LAN failure;
4. keep API/database identities and the shared connector unchanged;
5. update the current ingress/monitoring contracts from the old LAN origin to loopback;
6. remove the temporary issue-307 override/state only after all final checks pass.

The issue remains open until that final phase is complete.
