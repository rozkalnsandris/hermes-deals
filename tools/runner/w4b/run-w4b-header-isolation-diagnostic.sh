#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

TARGET_SHA='128325461f249791af8a5653163772e955dd2b89'
TARGET_SHORT="${TARGET_SHA:0:12}"
TARGET_IMAGE="hermes-deals-api:w4b-$TARGET_SHORT"
TARGET_ROOT="/usr/local/libexec/hermes-deals-w4b/$TARGET_SHA"
TARGET_NGINX="$TARGET_ROOT/source/infra/nginx.conf"
NGINX_IMAGE='nginx:1.30.4-alpine'
PRODUCTION_PROJECT='hermes-deals'

fail() {
  printf 'W4B_HEADER_DIAG_RESULT=BLOCKED\n'
  printf 'W4B_HEADER_DIAG_REASON=%s\n' "$1"
  printf 'PRODUCTION_MUTATED=false\n'
  exit 1
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'diagnostic_must_run_as_root'
[[ $# -eq 0 ]] || fail 'unexpected_arguments'

for command in docker grep mktemp stat systemctl; do
  command -v "$command" >/dev/null 2>&1 || fail "missing_command_${command}"
done

[[ -d "$TARGET_ROOT" && ! -L "$TARGET_ROOT" ]] || fail 'target_root_missing_or_unsafe'
[[ -f "$TARGET_NGINX" && ! -L "$TARGET_NGINX" ]] || fail 'target_nginx_missing_or_unsafe'
[[ "$(stat -c '%U:%G' "$TARGET_ROOT")" == 'root:root' ]] || fail 'target_root_ownership_invalid'
[[ "$(stat -c '%U:%G' "$TARGET_NGINX")" == 'root:root' ]] || fail 'target_nginx_ownership_invalid'

docker image inspect "$TARGET_IMAGE" >/dev/null 2>&1 || fail 'target_image_missing'
[[ "$(docker image inspect "$TARGET_IMAGE" --format '{{index .Config.Labels "org.opencontainers.image.revision"}}')" == "$TARGET_SHA" ]] \
  || fail 'target_image_revision_mismatch'
docker image inspect "$NGINX_IMAGE" >/dev/null 2>&1 || fail 'nginx_image_missing'

service_container() {
  local service="$1"
  docker ps \
    --filter "label=com.docker.compose.project=$PRODUCTION_PROJECT" \
    --filter "label=com.docker.compose.service=$service" \
    --format '{{.ID}}'
}

single_service_container() {
  local service="$1" value
  value="$(service_container "$service")"
  [[ -n "$value" && "$value" != *$'\n'* ]] || return 1
  printf '%s\n' "$value"
}

cloudflared_pid() {
  local pid
  pid="$(systemctl show -p MainPID --value cloudflared.service 2>/dev/null || true)"
  [[ "$pid" =~ ^[1-9][0-9]*$ ]] || return 1
  printf '%s\n' "$pid"
}

API_BEFORE="$(single_service_container api)" || fail 'production_api_identity_invalid'
WEB_BEFORE="$(single_service_container web)" || fail 'production_web_identity_invalid'
DB_BEFORE="$(single_service_container db)" || fail 'production_db_identity_invalid'
CLOUDFLARED_BEFORE="$(cloudflared_pid)" || fail 'cloudflared_not_active'

baseline_body="$(mktemp)"
trap 'rm -f -- "$baseline_body"' EXIT
if ! curl --fail --silent --show-error --max-time 8 \
  'http://127.0.0.1:9128/ui' -o "$baseline_body"; then
  fail 'production_ui_unreachable'
fi
grep -Fq 'data-hermes-production-bundle="app.js"' "$baseline_body" \
  || fail 'production_not_inline_w3'
if grep -Fq 'hermes-w4-shadow' "$baseline_body"; then
  fail 'production_not_inline_w3'
fi
rm -f -- "$baseline_body"
trap - EXIT

suffix="$$"
DIAG_NETWORK="hermes-w4b-header-diag-$suffix"
DIAG_API="hermes-w4b-header-api-$suffix"
DIAG_WEB="hermes-w4b-header-web-$suffix"

cleanup() {
  docker rm -f "$DIAG_WEB" >/dev/null 2>&1 || true
  docker rm -f "$DIAG_API" >/dev/null 2>&1 || true
  docker network rm "$DIAG_NETWORK" >/dev/null 2>&1 || true
}
trap cleanup EXIT
cleanup

docker network create "$DIAG_NETWORK" >/dev/null

docker run --detach --pull=never \
  --name "$DIAG_API" \
  --network "$DIAG_NETWORK" \
  --network-alias api \
  --env 'DATABASE_URL=postgresql+psycopg://diag:diag@127.0.0.1:9/diag' \
  --env 'HERMES_UI_ASSET_MODE=hashed-w4' \
  "$TARGET_IMAGE" >/dev/null

[[ "$(docker inspect "$DIAG_API" --format '{{json .HostConfig.PortBindings}}')" == 'null' ]] \
  || fail 'diagnostic_api_has_published_ports'

wait_for_url() {
  local url="$1"
  local attempt
  for attempt in $(seq 1 40); do
    if docker exec "$DIAG_API" python -c \
      'import sys, urllib.request; urllib.request.urlopen(sys.argv[1], timeout=2).read(1)' \
      "$url" >/dev/null 2>&1; then
      return 0
    fi
    [[ "$(docker inspect "$DIAG_API" --format '{{.State.Running}}' 2>/dev/null || true)" == true ]] \
      || return 1
    sleep 0.25
  done
  return 1
}

probe_url() {
  local url="$1"
  docker exec -i "$DIAG_API" python - "$url" <<'PY'
import sys
import urllib.request

url = sys.argv[1]
with urllib.request.urlopen(url, timeout=4) as response:
    body = response.read().decode("utf-8", errors="replace")
    mode = (response.headers.get("X-Hermes-UI-Asset-Mode") or "").strip().casefold()
    cache = (response.headers.get("Cache-Control") or "").strip().casefold()
    print(response.status)
    print("HASHED_W4" if mode == "hashed-w4" else ("MISSING" if not mode else "OTHER"))
    print("NO_STORE" if cache == "no-store" else ("MISSING" if not cache else "OTHER"))
    print("true" if '<meta name="hermes-w4-shadow" content="hashed-assets-v1">' in body else "false")
PY
}

wait_for_url 'http://127.0.0.1:8000/ui' || fail 'diagnostic_api_not_ready'
mapfile -t DIRECT < <(probe_url 'http://127.0.0.1:8000/ui')
[[ ${#DIRECT[@]} -eq 4 ]] || fail 'direct_probe_shape_invalid'

docker run --detach --pull=never \
  --name "$DIAG_WEB" \
  --network "$DIAG_NETWORK" \
  --volume "$TARGET_NGINX:/etc/nginx/conf.d/default.conf:ro" \
  "$NGINX_IMAGE" >/dev/null

[[ "$(docker inspect "$DIAG_WEB" --format '{{json .HostConfig.PortBindings}}')" == 'null' ]] \
  || fail 'diagnostic_web_has_published_ports'

wait_for_url "http://$DIAG_WEB/ui" || fail 'diagnostic_proxy_not_ready'
mapfile -t PROXY < <(probe_url "http://$DIAG_WEB/ui")
[[ ${#PROXY[@]} -eq 4 ]] || fail 'proxy_probe_shape_invalid'

if [[ "${DIRECT[0]}" != 200 ]]; then
  DIAGNOSIS='DIRECT_API_HTTP'
elif [[ "${DIRECT[1]}" != HASHED_W4 || "${DIRECT[3]}" != true ]]; then
  DIAGNOSIS='DIRECT_API_RUNTIME'
elif [[ "${PROXY[0]}" != 200 ]]; then
  DIAGNOSIS='NGINX_PROXY_HTTP'
elif [[ "${PROXY[1]}" != HASHED_W4 || "${PROXY[3]}" != true ]]; then
  DIAGNOSIS='NGINX_PROXY_PATH'
else
  DIAGNOSIS='TRANSITION_PATH_OR_TIMING'
fi

cleanup
trap - EXIT

[[ "$(single_service_container api)" == "$API_BEFORE" ]] || fail 'production_api_changed'
[[ "$(single_service_container web)" == "$WEB_BEFORE" ]] || fail 'production_web_changed'
[[ "$(single_service_container db)" == "$DB_BEFORE" ]] || fail 'production_db_changed'
[[ "$(cloudflared_pid)" == "$CLOUDFLARED_BEFORE" ]] || fail 'cloudflared_changed'

printf 'W4B_HEADER_DIAG_RESULT=PASS\n'
printf 'DIRECT_STATUS=%s\n' "${DIRECT[0]}"
printf 'DIRECT_MODE=%s\n' "${DIRECT[1]}"
printf 'DIRECT_CACHE=%s\n' "${DIRECT[2]}"
printf 'DIRECT_MARKER=%s\n' "${DIRECT[3]}"
printf 'PROXY_STATUS=%s\n' "${PROXY[0]}"
printf 'PROXY_MODE=%s\n' "${PROXY[1]}"
printf 'PROXY_CACHE=%s\n' "${PROXY[2]}"
printf 'PROXY_MARKER=%s\n' "${PROXY[3]}"
printf 'DIAGNOSIS=%s\n' "$DIAGNOSIS"
printf 'PRODUCTION_RUNTIME_UNCHANGED=true\n'
printf 'CLOUDFLARED_UNCHANGED=true\n'
printf 'PRODUCTION_MUTATED=false\n'
