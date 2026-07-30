#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HERMES_DEALS_REPO:-/home/andris/hermes-deals}"
STAGING="${HERMES_LIDL_STAGING:-$HOME/hermes-deals-lidl-staging}"
CORPUS="${HERMES_LIDL_CORPUS:-$HOME/hermes-deals-lidl-corpus}"
WORKER_IMAGE="${HERMES_LIDL_WORKER_IMAGE:?set HERMES_LIDL_WORKER_IMAGE to an immutable release tag}"

DISCOVERY_DIR="${1:?discovery directory required}"
OUT="${2:?empty output directory required}"
TARGET="${3:-next}"

[[ "$WORKER_IMAGE" != *:latest ]] || {
  echo "FAIL: mutable worker image is forbidden: $WORKER_IMAGE" >&2
  exit 2
}
[[ -d "$DISCOVERY_DIR" ]] || {
  echo "FAIL: discovery directory missing: $DISCOVERY_DIR" >&2
  exit 2
}
[[ -d "$CORPUS" ]] || {
  echo "FAIL: reference corpus directory missing: $CORPUS" >&2
  exit 2
}
mkdir -p "$STAGING" "$OUT"
[[ -z "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit)" ]] || {
  echo "FAIL: output directory must be empty: $OUT" >&2
  exit 2
}
docker image inspect "$WORKER_IMAGE" >/dev/null

exec docker run --rm \
  --user "$(id -u):$(id -g)" \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,nosuid,nodev,size=768m \
  -e PYTHONDONTWRITEBYTECODE=1 \
  -e PYTHONPATH=/repo:/repo/backend:/repo/tools:/repo/tools/lidl_parser_provenance \
  --mount "type=bind,src=$REPO/backend,dst=/repo/backend,readonly" \
  --mount "type=bind,src=$REPO/tools,dst=/repo/tools,readonly" \
  --mount "type=bind,src=$(realpath "$DISCOVERY_DIR"),dst=/discovery,readonly" \
  --mount "type=bind,src=$(realpath "$CORPUS"),dst=/corpus,readonly" \
  --mount "type=bind,src=$(realpath "$STAGING"),dst=/staging" \
  --mount "type=bind,src=$(realpath "$OUT"),dst=/out" \
  "$WORKER_IMAGE" \
  python /repo/tools/lidl_weekly_staging.py \
    --discovery-dir /discovery \
    --staging-root /staging \
    --output-dir /out \
    --reference-corpus-root /corpus \
    --target "$TARGET"
