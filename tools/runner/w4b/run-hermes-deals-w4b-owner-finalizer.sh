#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

TARGET_SHA='128325461f249791af8a5653163772e955dd2b89'
REPOSITORY='https://github.com/rozkalnsandris/hermes-deals.git'
PRIMARY='/home/andris/hermes-deals'
RUNNER_USER='github-release-runner'
INSTALL_ROOT='/usr/local/libexec/hermes-deals-w4b'
TARGET_ROOT="$INSTALL_ROOT/$TARGET_SHA"
SOURCE_ROOT="$TARGET_ROOT/source"
OPERATOR='/usr/local/sbin/hermes-deals-w4b-operator'
DISPATCHER='/usr/local/sbin/hermes-deals-w4b-dispatch'
SUDOERS='/etc/sudoers.d/hermes-deals-w4b'
HASH_FILE="$INSTALL_ROOT/operator.sha256"

fail() {
  printf 'OWNER_FINALIZER_RESULT=BLOCKED\nOWNER_FINALIZER_REASON=%s\n' "$1"
  exit 1
}

[[ $# -eq 1 ]] || fail 'usage_bridge_sha_required'
BRIDGE_SHA="$1"
[[ "$BRIDGE_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'bridge_sha_invalid'
[[ "$(id -un)" == andris ]] || fail 'owner_finalizer_must_run_as_andris'
for command in curl git install sha256sum sudo tar visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "missing_command_${command}"
done
[[ -d "$PRIMARY" && ! -L "$PRIMARY" ]] || fail 'production_repository_missing_or_unsafe'
id "$RUNNER_USER" >/dev/null 2>&1 || fail 'release_runner_user_missing'
if id -nG "$RUNNER_USER" | tr ' ' '\n' | grep -qx docker; then
  fail 'release_runner_must_not_have_docker_group'
fi

primary_state() {
  printf '%s\n' \
    "$(git -C "$PRIMARY" rev-parse HEAD)" \
    "$(git -C "$PRIMARY" branch --show-current)" \
    "$(git -C "$PRIMARY" status --porcelain=v1 --untracked-files=all)" \
    "$(git -C "$PRIMARY" diff --cached --binary)" |
    sha256sum | awk '{print $1}'
}

service_id() {
  docker ps \
    --filter 'label=com.docker.compose.project=hermes-deals' \
    --filter "label=com.docker.compose.service=$1" \
    --format '{{.ID}}'
}

cloudflared_pid() {
  systemctl show -p MainPID --value cloudflared.service
}

PRIMARY_STATE_BEFORE="$(primary_state)"
ENV_SHA_BEFORE="$(sha256sum "$PRIMARY/.env" | awk '{print $1}')"
API_BEFORE="$(service_id api)"
WEB_BEFORE="$(service_id web)"
DB_BEFORE="$(service_id db)"
CLOUDFLARED_BEFORE="$(cloudflared_pid)"
[[ -n "$API_BEFORE" && -n "$WEB_BEFORE" && -n "$DB_BEFORE" ]] || fail 'production_containers_missing'
[[ "$CLOUDFLARED_BEFORE" =~ ^[1-9][0-9]*$ ]] || fail 'cloudflared_not_active'

WORK="$(mktemp -d)"
cleanup() { rm -rf -- "$WORK"; }
trap cleanup EXIT
CLONE="$WORK/repo"
SNAPSHOT="$WORK/source"
install -d -m 0700 "$SNAPSHOT"

git clone --quiet --filter=blob:none --no-checkout "$REPOSITORY" "$CLONE"
git -C "$CLONE" fetch --quiet origin "$BRIDGE_SHA" "$TARGET_SHA"
git -C "$CLONE" cat-file -e "$BRIDGE_SHA^{commit}"
git -C "$CLONE" cat-file -e "$TARGET_SHA^{commit}"
git -C "$CLONE" merge-base --is-ancestor "$TARGET_SHA" "$BRIDGE_SHA" \
  || fail 'target_sha_is_not_ancestor_of_bridge_sha'
git -C "$CLONE" checkout --quiet --detach "$BRIDGE_SHA"
[[ "$(git -C "$CLONE" rev-parse HEAD)" == "$BRIDGE_SHA" ]] || fail 'bridge_checkout_mismatch'

for path in \
  tools/runner/w4b/hermes-deals-w4b-operator \
  tools/runner/w4b/hermes-deals-w4b-dispatch \
  tools/runner/w4b/docker-compose.w4b.yml; do
  git -C "$CLONE" ls-files --error-unmatch "$path" >/dev/null || fail 'bridge_runtime_file_not_tracked'
done
bash -n "$CLONE/tools/runner/w4b/hermes-deals-w4b-operator"
bash -n "$CLONE/tools/runner/w4b/hermes-deals-w4b-dispatch"

git -C "$CLONE" archive "$TARGET_SHA" \
  backend docker-compose.yml docker-compose.production.yml infra/nginx.conf |
  tar -x -C "$SNAPSHOT"
[[ -f "$SNAPSHOT/backend/Dockerfile" ]] || fail 'target_backend_snapshot_missing'
[[ -f "$SNAPSHOT/docker-compose.yml" ]] || fail 'target_compose_snapshot_missing'
[[ -f "$SNAPSHOT/infra/nginx.conf" ]] || fail 'target_nginx_snapshot_missing'

grep -Fq 'CMD ["uvicorn", "app.runtime:app"' "$SNAPSHOT/backend/Dockerfile" \
  || fail 'target_image_does_not_use_w4_runtime'
grep -Fq 'HERMES_UI_ASSET_MODE: ${HERMES_UI_ASSET_MODE:-inline-w3}' "$SNAPSHOT/docker-compose.yml" \
  || fail 'target_compose_missing_w4_mode'
grep -Fq 'location ^~ /ui/assets/' "$SNAPSHOT/infra/nginx.conf" \
  || fail 'target_nginx_missing_hashed_asset_proxy'

sudo -v
if sudo test -e "$TARGET_ROOT"; then
  fail 'target_runtime_already_installed'
fi
sudo install -d -o root -g root -m 0755 "$INSTALL_ROOT" "$TARGET_ROOT" "$SOURCE_ROOT"
sudo cp -a "$SNAPSHOT/." "$SOURCE_ROOT/"
sudo chown -R root:root "$SOURCE_ROOT"
sudo find "$SOURCE_ROOT" -type d -exec chmod 0755 {} +
sudo find "$SOURCE_ROOT" -type f -exec chmod 0644 {} +
sudo install -o root -g root -m 0644 \
  "$CLONE/tools/runner/w4b/docker-compose.w4b.yml" \
  "$TARGET_ROOT/docker-compose.w4b.yml"
sudo install -o root -g root -m 0755 \
  "$CLONE/tools/runner/w4b/hermes-deals-w4b-operator" "$OPERATOR"
sudo install -o root -g root -m 0755 \
  "$CLONE/tools/runner/w4b/hermes-deals-w4b-dispatch" "$DISPATCHER"
OPERATOR_SHA="$(sha256sum "$CLONE/tools/runner/w4b/hermes-deals-w4b-operator" | awk '{print $1}')"
printf '%s\n' "$OPERATOR_SHA" | sudo tee "$HASH_FILE" >/dev/null
sudo chown root:root "$HASH_FILE"
sudo chmod 0644 "$HASH_FILE"

SUDOERS_TMP="$WORK/sudoers"
cat >"$SUDOERS_TMP" <<EOF
$RUNNER_USER ALL=(root) NOPASSWD: $DISPATCHER preflight
$RUNNER_USER ALL=(root) NOPASSWD: $DISPATCHER cutover
$RUNNER_USER ALL=(root) NOPASSWD: $DISPATCHER verify
EOF
sudo visudo -cf "$SUDOERS_TMP" >/dev/null
sudo install -o root -g root -m 0440 "$SUDOERS_TMP" "$SUDOERS"
sudo visudo -cf "$SUDOERS" >/dev/null

[[ "$(sudo stat -c '%U:%G:%a' "$OPERATOR")" == 'root:root:755' ]] || fail 'installed_operator_metadata_invalid'
[[ "$(sudo stat -c '%U:%G:%a' "$DISPATCHER")" == 'root:root:755' ]] || fail 'installed_dispatcher_metadata_invalid'
[[ "$(sudo sha256sum "$OPERATOR" | awk '{print $1}')" == "$OPERATOR_SHA" ]] || fail 'installed_operator_hash_mismatch'

if sudo -u "$RUNNER_USER" sudo --non-interactive "$OPERATOR" rollback >/dev/null 2>&1; then
  fail 'runner_unexpectedly_authorized_for_root_only_rollback'
fi
PREFLIGHT_OUTPUT="$(sudo -u "$RUNNER_USER" sudo --non-interactive "$DISPATCHER" preflight)" 
printf '%s\n' "$PREFLIGHT_OUTPUT"
grep -Fq 'W4B_RESULT=PASS' <<<"$PREFLIGHT_OUTPUT" || fail 'runner_preflight_did_not_pass'
grep -Fq 'W4B_MODE=preflight' <<<"$PREFLIGHT_OUTPUT" || fail 'runner_preflight_mode_mismatch'
grep -Fq 'PRODUCTION_MUTATED=false' <<<"$PREFLIGHT_OUTPUT" || fail 'runner_preflight_mutation_boundary_failed'

PRIMARY_STATE_AFTER="$(primary_state)"
ENV_SHA_AFTER="$(sha256sum "$PRIMARY/.env" | awk '{print $1}')"
API_AFTER="$(service_id api)"
WEB_AFTER="$(service_id web)"
DB_AFTER="$(service_id db)"
CLOUDFLARED_AFTER="$(cloudflared_pid)"
[[ "$PRIMARY_STATE_AFTER" == "$PRIMARY_STATE_BEFORE" ]] || fail 'production_git_changed_during_bootstrap'
[[ "$ENV_SHA_AFTER" == "$ENV_SHA_BEFORE" ]] || fail 'production_env_changed_during_bootstrap'
[[ "$API_AFTER" == "$API_BEFORE" ]] || fail 'api_container_changed_during_bootstrap'
[[ "$WEB_AFTER" == "$WEB_BEFORE" ]] || fail 'web_container_changed_during_bootstrap'
[[ "$DB_AFTER" == "$DB_BEFORE" ]] || fail 'db_container_changed_during_bootstrap'
[[ "$CLOUDFLARED_AFTER" == "$CLOUDFLARED_BEFORE" ]] || fail 'cloudflared_changed_during_bootstrap'

printf 'OWNER_FINALIZER_RESULT=PASS\n'
printf 'BRIDGE_SHA=%s\n' "$BRIDGE_SHA"
printf 'TARGET_SHA=%s\n' "$TARGET_SHA"
printf 'OPERATOR_SHA256=%s\n' "$OPERATOR_SHA"
printf 'RUNNER_PREFLIGHT_AUTHORIZED=true\n'
printf 'RUNNER_CUTOVER_AUTHORIZED=true\n'
printf 'RUNNER_VERIFY_AUTHORIZED=true\n'
printf 'RUNNER_ROLLBACK_AUTHORIZED=false\n'
printf 'READ_ONLY_PREFLIGHT=PASS\n'
printf 'PRODUCTION_GIT_UNCHANGED=true\n'
printf 'PRODUCTION_ENV_UNCHANGED=true\n'
printf 'PRODUCTION_RUNTIME_UNCHANGED=true\n'
printf 'CLOUDFLARED_UNCHANGED=true\n'
printf 'NEXT_GITHUB_ACTION=/hermes-374 preflight\n'
