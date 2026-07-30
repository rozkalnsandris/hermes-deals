# Hermes Deals production release images

Production API deploys must use an explicit release image tag. Do not use the
mutable default Compose build tag as the rollback contract, and do not use
`docker commit` as a release backup.

The base `docker-compose.yml` remains convenient for development/testing.
Production adds `docker-compose.production.yml`, which requires
`HERMES_DEALS_API_TAG` and sets `pull_policy: never`.

Release flow:

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

## Scheduled retailer collectors

The production systemd collector services are stored in `infra/systemd/`.
Their `ExecStart` commands use `docker compose exec` against the already
running `api` service. This is intentional: every scheduled collection must
run the exact immutable release image currently deployed in production, not
the mutable base-Compose `hermes-deals-api:latest` image.

Install an updated service unit, reload systemd, and verify the resolved
command before starting a canary:

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
