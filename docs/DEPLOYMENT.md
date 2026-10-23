# Hermes Deals release paths: legacy and SIMPLE-DEPLOY

**Runtime cutover receipt (2026-10-23):** The owner-authorized RPi5
SIMPLE-DEPLOY API-only activation completed with source SHA
`84366a83cf907404febe113b5739a2c1fc1fb3fa` and immutable GHCR digest
`sha256:6f94ac0e8479b26ba15cdd8207a2f6907743130b7df948bcce0e0e037eff8446`.
The independently read-only-verified ALDI snapshot matched RAW bytes, its
`SourceSnapshot` row and the API's latest-source response. Netto, ALDI and
EDEKA collector timers were subsequently restored; EDEKA monitor stayed
inactive. These are owner terminal receipts documented in
[#992](https://github.com/rozkalnsandris/hermes-deals/issues/992), not
standing authorization for more LIVE operations or proof of all-retailer
freshness and full booklet coverage.

**Legacy release retirement in source:** This change keeps both historical
workflows for audit, but gates their GitHub Actions jobs behind an event predicate that cannot
match their configured trigger: manual/control `.github/workflows/deploy-main.yml` cannot start
the self-hosted legacy release, and issue-comment
`.github/workflows/hermes-direct-main-deploy.yml` cannot dispatch it.
The safeguards become effective only **after this source PR is merged**.
They do not cancel already-running/queued historical jobs, remove installed
host helpers, change runner permissions or start/stop any host service.
SIMPLE-DEPLOY remains the ordinary API release path. Any recovery needing
the legacy path requires a distinct reviewed decision and LIVE authority.

## Legacy controlled release (pre-cutover reference)

The following local-image procedure documents the **legacy direct-main**
release path, not the future ordinary SIMPLE-DEPLOY path. It must not be
dispatched during, or automatically resumed after, SIMPLE-DEPLOY cutover.
Any application of this procedure requires separate exact LIVE authorization.
Do not use it as fallback if the SIMPLE-DEPLOY preflight fails.

Legacy API releases use an explicit local `hermes-deals-api:*` image tag.
Do not use the mutable default Compose build tag as a rollback contract, and
do not use `docker commit` as a release backup. Base
`docker-compose.yml` remains useful for development/testing. The legacy
`docker-compose.production.yml` override requires
`HERMES_DEALS_API_TAG` with `pull_policy: never`.

Legacy release flow (not SIMPLE-DEPLOY):

1. build and test the release image under an immutable version+Git tag;
2. save the previous and new release images with `docker image save`;
3. SHA256 the archives and keep them outside Docker's image store;
4. back up and restore-test Postgres before any production DB write;
5. deploy only the API with both Compose files, `--no-deps --no-build --wait`;
6. run health/UI/API canaries;
7. only then perform controlled Review seeding;
8. on failure, load the previous saved image if necessary and recreate only API.

Example deployment selector:

```sh
HERMES_DEALS_API_TAG=release-<version>-<gitsha> \
docker compose \
  -f docker-compose.yml \
  -f docker-compose.production.yml \
  up -d --no-deps --no-build --wait api
```

The last known-good release image archive must be retained across Docker image
pruning. Keep at least the previous and current release archives.

## Controlled GitHub release workflow

The repository-side controlled API/UI release implementation is documented in
`docs/operations/rpi5-github-release-runner.md`.

The workflow is manual-only and requires an exact current `main` squash merge
SHA, successful exact-SHA CI, a separate release runner account, root
registration of immutable image and rollback archives, and an exact apply
confirmation phrase. The first implementation slice cannot run migrations or
authorize database writes.

## SIMPLE-DEPLOY target and cutover gate

The intended **post-cutover** application release is the reviewed
`ghcr.io/rozkalnsandris/hermes-deals` image resolved to an **immutable
digest** through the shared SIMPLE-DEPLOY workflow and the trusted
`RPi5_main` deployer. The `production` tag is a discovery pointer, not a
rollback identity. The target API adapter is source-defined in
`RPi5_main/ops/deploy/simple-deploy-compose/hermes-deals-household-api.yml`;
its adopted raw state and read-only config are separate from the legacy
checkout-relative `./data/raw` and `./config` mounts. The legacy base
Compose paths are **not** evidence of the selected LIVE API container.

Before any authorized promotion, the operator must establish the installed
legacy release-helper identity, prevent competing old-path release jobs,
quiesce the four relevant collector/monitor services and timers, and
establish the state-adoption, image-digest and installed-unit baselines.
Neither the tracked units nor an adopted point-in-time copy prove the
installed units use the promoted API. Follow
[`aldi-cutover-snapshot-verification.md`](operations/aldi-cutover-snapshot-verification.md)
for fixed host selection and the bounded ALDI collector-write/API-read
provenance canary. The RPi5 state-adoption source contract is
`RPi5_main/docs/HERMES_STATE_ADOPTION_V1.md`; its SOURCE ONLY status must
not be mistaken for completed adoption.

State copy/permissions, timer lifecycle, image promotion, Docker mutations
and the one-write canary all require separate, exact owner LIVE authority.
A failed or uncertain one-shot is STOP, never a cue to rerun a legacy
release or restore timers. SIMPLE-DEPLOY must not be described as the
active production path until the installed runtime and canary receipts
prove that fact.

## Scheduled retailer collectors (legacy unit maintenance)

The production systemd collector services are stored in `infra/systemd/`.
Their `ExecStart` commands use `docker compose exec` against the already
running `api` service. This is intentional: every scheduled collection must
run the exact immutable release image currently deployed in production, not
the mutable base-Compose `hermes-deals-api:latest` image.

The following commands are a **legacy, separately LIVE-gated** unit
maintenance example, not a SIMPLE-DEPLOY cutover instruction. Installing
units or reloading systemd changes host runtime state. Do not execute
them based on this documentation or on source merge alone:

```sh
sudo install -m 0644 infra/systemd/hermes-deals-*-collector.service \
  /etc/systemd/system/
sudo systemctl daemon-reload
systemctl show -p ExecStart hermes-deals-netto-collector.service
```

Keep the existing timer schedules and arming files separate from the service
command. After changing a collector service, run one controlled retailer
canary and compare health, snapshot/offer counts, invariants, and the API read
path before relying on the next timer execution.
