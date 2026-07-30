#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${REPO:-/home/andris/hermes-deals}"
STAGING="${STAGING:-/home/andris/hermes-deals-lidl-staging}"
CORPUS="${CORPUS:-/home/andris/hermes-deals-lidl-corpus}"
WORKER_IMAGE="${WORKER_IMAGE:?WORKER_IMAGE is required}"
APPROVAL_FILE="${APPROVAL_FILE:?APPROVAL_FILE is required}"
OUTPUT_DIR="${OUTPUT_DIR:?OUTPUT_DIR is required}"
FLYER_KEY="${FLYER_KEY:?FLYER_KEY is required}"
RAW_SHA256="${RAW_SHA256:?RAW_SHA256 is required}"
PARSER_SHA256="${PARSER_SHA256:?PARSER_SHA256 is required}"
STAGING_DIGEST_SHA256="${STAGING_DIGEST_SHA256:?STAGING_DIGEST_SHA256 is required}"

mkdir -p "$OUTPUT_DIR"
[[ -d "$REPO/backend" ]] || { echo "missing backend" >&2; exit 2; }
[[ -d "$REPO/tools" ]] || { echo "missing tools" >&2; exit 2; }
[[ -d "$STAGING" ]] || { echo "missing staging root" >&2; exit 2; }
[[ -d "$CORPUS" ]] || { echo "missing corpus root" >&2; exit 2; }
[[ -f "$APPROVAL_FILE" ]] || { echo "missing approval file" >&2; exit 2; }

docker run --rm --read-only \
  --user "$(id -u):$(id -g)" \
  --network none \
  --cap-drop ALL \
  --security-opt no-new-privileges:true \
  --tmpfs /tmp:rw,nosuid,nodev,size=256m \
  -e PYTHONDONTWRITEBYTECODE=1 \
  --mount "type=bind,src=$(realpath "$REPO/backend"),dst=/repo/backend,readonly" \
  --mount "type=bind,src=$(realpath "$REPO/tools"),dst=/repo/tools,readonly" \
  --mount "type=bind,src=$(realpath "$STAGING"),dst=/staging,readonly" \
  --mount "type=bind,src=$(realpath "$CORPUS"),dst=/corpus" \
  --mount "type=bind,src=$(realpath "$APPROVAL_FILE"),dst=/approval.json,readonly" \
  --mount "type=bind,src=$(realpath "$OUTPUT_DIR"),dst=/out" \
  --entrypoint python "$WORKER_IMAGE" \
  /repo/tools/lidl_weekly_corpus_promotion.py \
    --staging-root /staging \
    --corpus-root /corpus \
    --approval-file /approval.json \
    --output-dir /out \
    --flyer-key "$FLYER_KEY" \
    --raw-sha256 "$RAW_SHA256" \
    --parser-sha256 "$PARSER_SHA256" \
    --staging-digest-sha256 "$STAGING_DIGEST_SHA256"
