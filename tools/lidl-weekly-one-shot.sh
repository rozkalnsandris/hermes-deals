#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HERMES_DEALS_REPO:-/home/andris/hermes-deals}"
CORPUS="${HERMES_LIDL_CORPUS:-$HOME/hermes-deals-lidl-corpus}"
WORKER_IMAGE="${HERMES_LIDL_WORKER_IMAGE:?set HERMES_LIDL_WORKER_IMAGE to an immutable release tag}"
TARGET="${1:-next}"
OUT="${2:-}"
TODAY="${3:-}"

[[ "$WORKER_IMAGE" != *:latest ]] || {
  echo "FAIL: mutable worker image is forbidden: $WORKER_IMAGE" >&2
  exit 2
}
docker image inspect "$WORKER_IMAGE" >/dev/null
[[ -d "$REPO/backend" && -d "$REPO/tools" ]] || {
  echo "FAIL: Hermes Deals repo is incomplete: $REPO" >&2
  exit 2
}
[[ -d "$CORPUS/flyers" ]] || {
  echo "FAIL: Lidl corpus is missing: $CORPUS" >&2
  exit 2
}
[[ "$TARGET" == "current" || "$TARGET" == "next" ]] || {
  echo "FAIL: target must be current or next" >&2
  exit 2
}

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
[[ -n "$OUT" ]] || OUT="$HOME/hermes-deals-lidl-one-shot/$STAMP-$TARGET"
mkdir -p "$OUT"
[[ -z "$(find "$OUT" -mindepth 1 -maxdepth 1 -print -quit)" ]] || {
  echo "FAIL: output directory must be empty: $OUT" >&2
  exit 2
}

ARGS=(
  --corpus /corpus
  --output-dir /out
  --target "$TARGET"
)
[[ -z "$TODAY" ]] || ARGS+=(--today "$TODAY")

exec docker run --rm \
  --user "$(id -u):$(id -g)" \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,nosuid,nodev,size=768m \
  -e PYTHONDONTWRITEBYTECODE=1 \
  --mount "type=bind,src=$REPO/backend,dst=/repo/backend,readonly" \
  --mount "type=bind,src=$REPO/tools,dst=/repo/tools,readonly" \
  --mount "type=bind,src=$CORPUS,dst=/corpus,readonly" \
  --mount "type=bind,src=$OUT,dst=/out" \
  "$WORKER_IMAGE" \
  python /repo/tools/lidl_weekly_one_shot.py "${ARGS[@]}"
