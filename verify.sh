#!/usr/bin/env bash
set -Eeuo pipefail
cd "$(dirname "$0")"

set -a
source ./.env
set +a

echo "[1/7] Compose config"
docker compose config >/dev/null

echo "[2/7] Containers"
docker compose ps

echo "[3/7] Running API image"
docker compose ps --format json api

echo "[4/7] DB migration state and metadata"
docker compose exec -T api alembic current
docker compose exec -T api alembic check

echo "[5/7] Unit/regression tests in the running API image"
docker compose exec -T api python -m unittest discover -s tests -v

echo "[6/7] Python dependency consistency"
docker compose exec -T api python -m pip check

echo "[7/7] API through Nginx"
docker compose exec -T web wget -qO- http://127.0.0.1/api/health
echo
echo "Latest source snapshots:"
docker compose exec -T web wget -qO- http://127.0.0.1/api/v1/sources/latest
echo
