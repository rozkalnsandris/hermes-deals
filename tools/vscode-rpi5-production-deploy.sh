#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'

RELEASE_LAUNCHER='tools/vscode-rpi5-release.sh'
PRIMARY_ROOT='/home/andris/hermes-deals'

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

for command in date docker git tee; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

git rev-parse --is-inside-work-tree >/dev/null 2>&1 \
  || fail 'open the Hermes Deals repository in VS Code'
ROOT="$(git rev-parse --show-toplevel)"
[[ "$ROOT" == "$PRIMARY_ROOT" ]] \
  || fail "open the primary repository in VS Code: $PRIMARY_ROOT"
cd "$ROOT"
[[ -x "$RELEASE_LAUNCHER" && ! -L "$RELEASE_LAUNCHER" ]] \
  || fail 'guarded VS Code release launcher is missing or unsafe'

STATE_ROOT="${XDG_STATE_HOME:-$HOME/.local/state}/hermes-deals/deploy"
mkdir -p "$STATE_ROOT"
chmod 700 "$STATE_ROOT"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
LOG_FILE="$STATE_ROOT/vscode-production-deploy-${STAMP}.log"
: >"$LOG_FILE"
chmod 600 "$LOG_FILE"
exec > >(tee -a "$LOG_FILE") 2>&1

printf 'Hermes Deals VS Code production deploy\n'
printf 'LOG_FILE=%s\n' "$LOG_FILE"
printf 'STARTED_AT_UTC=%s\n' "$STAMP"

printf '\nRunning read-only preflight...\n'
if ! CHECK_OUTPUT="$("$RELEASE_LAUNCHER" check 2>&1)"; then
  printf '%s\n' "$CHECK_OUTPUT"
  fail 'read-only preflight failed; production was not changed'
fi
printf '%s\n' "$CHECK_OUTPUT"
if [[ "$CHECK_OUTPUT" == *"NO DEPLOY NEEDED"* ]]; then
  printf '\nNO DEPLOY NEEDED: production already matches exact current main.\n'
  printf 'PRODUCTION_CHANGED=false\n'
  exit 0
fi

git fetch --quiet origin main
LOCAL_SHA="$(git rev-parse HEAD)"
TARGET_SHA="$(git rev-parse origin/main)"
[[ "$LOCAL_SHA" == "$TARGET_SHA" ]] \
  || fail 'main changed after preflight; synchronize and run Check deploy again'
[[ "$TARGET_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'invalid target main SHA'

printf '\nProduction authorization boundary\n'
printf 'TARGET_SHA=%s\n' "$TARGET_SHA"
printf 'Required confirmation:\n  DEPLOY %s\n' "$TARGET_SHA"
read -r -p '> ' CONFIRMATION
[[ "$CONFIRMATION" == "DEPLOY ${TARGET_SHA}" ]] \
  || fail 'confirmation did not match the exact target SHA; deployment cancelled'
printf 'CONFIRMATION_MATCH=PASS\n'

printf '\nStarting guarded exact-main deploy...\n'
"$RELEASE_LAUNCHER" deploy

COMPOSE=(
  docker compose
  --project-directory "$ROOT"
  --env-file "$ROOT/.env"
  -f "$ROOT/docker-compose.yml"
  -f "$ROOT/docker-compose.production.yml"
)
API_CONTAINER="$("${COMPOSE[@]}" ps -q api)"
[[ -n "$API_CONTAINER" ]] || fail 'production API container is missing after deploy'
API_RUNNING="$(docker inspect "$API_CONTAINER" --format '{{.State.Running}}')"
[[ "$API_RUNNING" == true ]] || fail 'production API container is not running after deploy'
API_REVISION="$(docker inspect "$API_CONTAINER" --format '{{ index .Config.Labels "org.opencontainers.image.revision" }}')"
[[ "$API_REVISION" == "$TARGET_SHA" ]] \
  || fail 'production API container revision does not match the confirmed target SHA'

FINISHED_AT="$(date -u +%Y%m%dT%H%M%SZ)"
printf '\nVS CODE PRODUCTION DEPLOY PASS\n'
printf 'CONFIRMED_TARGET_SHA=%s\n' "$TARGET_SHA"
printf 'POST_DEPLOY_API_CONTAINER_RUNNING=true\n'
printf 'POST_DEPLOY_API_REVISION=%s\n' "$API_REVISION"
printf 'FINISHED_AT_UTC=%s\n' "$FINISHED_AT"
printf 'LOG_FILE=%s\n' "$LOG_FILE"
