#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HERMES_DEALS_REPO:-/home/andris/hermes-deals}"
CORPUS="${HERMES_LIDL_CORPUS:-$HOME/hermes-deals-lidl-corpus}"
WORKER_IMAGE="${HERMES_LIDL_WORKER_IMAGE:?set HERMES_LIDL_WORKER_IMAGE to an immutable release tag}"

FLYER_KEY="${1:-latest}"
SCAN="${2:-latest}"
OUT="${3:-}"
MODE="${4:-}"

[[ "$WORKER_IMAGE" != *:latest ]] || {
  echo "FAIL: mutable worker image is forbidden: $WORKER_IMAGE" >&2
  exit 2
}
docker image inspect "$WORKER_IMAGE" >/dev/null

if [[ "$FLYER_KEY" == "latest" ]]; then
  FLYER_KEY="$(find "$CORPUS/flyers" -mindepth 1 -maxdepth 1 -type d -printf '%f\n' | sort | tail -1)"
fi
[[ -n "$FLYER_KEY" ]] || { echo "FAIL: no flyer found" >&2; exit 1; }

FLYER="$CORPUS/flyers/$FLYER_KEY"
[[ -d "$FLYER" ]] || { echo "FAIL: flyer missing: $FLYER" >&2; exit 1; }

if [[ "$SCAN" == "latest" ]]; then
  SCAN="$(find "$FLYER/scans" -mindepth 1 -maxdepth 1 -type d -name 'scan-*' -printf '%f\n' | sort | tail -1)"
fi
[[ -n "$SCAN" && -d "$FLYER/scans/$SCAN" ]] || { echo "FAIL: scan missing: $SCAN" >&2; exit 1; }

STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
[[ -n "$OUT" ]] || OUT="$HOME/hermes-deals-lidl-weekly/$FLYER_KEY/$SCAN/$STAMP"
mkdir -p "$OUT"

ARGS=(
  --flyer-dir "/corpus/$FLYER_KEY"
  --scan "$SCAN"
  --output-dir /out
)
[[ "$MODE" != "--no-ocr" ]] || ARGS+=(--no-ocr)

exec docker run --rm \
  --user "$(id -u):$(id -g)" \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,nosuid,nodev,size=768m \
  -e PYTHONDONTWRITEBYTECODE=1 \
  --mount "type=bind,src=$REPO/backend,dst=/repo/backend,readonly" \
  --mount "type=bind,src=$REPO/tools,dst=/repo/tools,readonly" \
  --mount "type=bind,src=$FLYER,dst=/corpus/$FLYER_KEY,readonly" \
  --mount "type=bind,src=$OUT,dst=/out" \
  "$WORKER_IMAGE" \
  python /repo/tools/lidl-weekly-completeness.py "${ARGS[@]}"
