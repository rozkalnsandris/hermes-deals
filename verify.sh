#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"

set -a
source ./.env
set +a

echo "[1/6] Compose config"
docker compose config >/dev/null

echo "[2/6] Containers"
docker compose ps

echo "[3/6] DB migration state"
docker compose run --rm api alembic current

echo "[4/6] Unit/regression tests"
docker compose run --rm api python -m unittest discover -s tests -v

echo "[5/6] Python dependency consistency"
docker compose run --rm api python -m pip check

echo "[6/6] API through Nginx"
docker compose exec -T web wget -qO- http://127.0.0.1/api/health
echo
echo "Latest source snapshots:"
docker compose exec -T web wget -qO- http://127.0.0.1/api/v1/sources/latest || true
echo
