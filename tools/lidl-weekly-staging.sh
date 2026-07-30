#!/usr/bin/env bash
set -Eeuo pipefail

REPO="${HERMES_DEALS_REPO:-/home/andris/hermes-deals}"
STAGING="${HERMES_LIDL_STAGING:-$HOME/hermes-deals-lidl-staging}"
CORPUS="${HERMES_LIDL_CORPUS:-$HOME/hermes-deals-lidl-corpus}"
WORKER_IMAGE="${HERMES_LIDL_WORKER_IMAGE:?set HERMES_LIDL_WORKER_IMAGE to an immutable release tag}"

DISCOVERY_DIR="${1:?discovery directory required}"
OUT="${2:?empty output directory required}"
TARGET="${3:-next}"
SOURCE_REVIEW_FILE="${4:-}"
REVIEW_PROFILE_FILE="${5:-}"

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

SOURCE_REVIEW_MOUNT=()
SOURCE_REVIEW_ARGS=()
if [[ -n "$SOURCE_REVIEW_FILE" ]]; then
  [[ -f "$SOURCE_REVIEW_FILE" ]] || {
    echo "FAIL: source review file missing: $SOURCE_REVIEW_FILE" >&2
    exit 2
  }
  SOURCE_REVIEW_MOUNT=(
    --mount "type=bind,src=$(realpath "$SOURCE_REVIEW_FILE"),dst=/source-review.json,readonly"
  )
  SOURCE_REVIEW_ARGS=(--source-review-file /source-review.json)
fi

REVIEW_PROFILE_MOUNT=()
REVIEW_PROFILE_ARGS=()
if [[ -n "$REVIEW_PROFILE_FILE" ]]; then
  [[ -f "$REVIEW_PROFILE_FILE" ]] || {
    echo "FAIL: review profile file missing: $REVIEW_PROFILE_FILE" >&2
    exit 2
  }
  REVIEW_PROFILE_MOUNT=(
    --mount "type=bind,src=$(realpath "$REVIEW_PROFILE_FILE"),dst=/review-profile.json,readonly"
  )
  REVIEW_PROFILE_ARGS=(--review-profile-file /review-profile.json)
fi

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
  "${SOURCE_REVIEW_MOUNT[@]}" \
  "${REVIEW_PROFILE_MOUNT[@]}" \
  "$WORKER_IMAGE" \
  python /repo/tools/lidl_weekly_staging.py \
    --discovery-dir /discovery \
    --staging-root /staging \
    --output-dir /out \
    --reference-corpus-root /corpus \
    --target "$TARGET" \
    "${SOURCE_REVIEW_ARGS[@]}" \
    "${REVIEW_PROFILE_ARGS[@]}"
