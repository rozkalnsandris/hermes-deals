#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

TARGET_SHA='42238d93045e60430a42cd13b85b598e78c7d528'
W4B_TARGET_SHA='128325461f249791af8a5653163772e955dd2b89'
PRIMARY='/home/andris/hermes-deals'
RUNNER_USER='github-release-runner'
INSTALL_ROOT='/usr/local/libexec/hermes-deals-w4c'
TARGET_ROOT="$INSTALL_ROOT/$TARGET_SHA"
SOURCE="$TARGET_ROOT/source"
DISPATCHER='/usr/local/sbin/hermes-deals-w4c-dispatch'
SUDOERS='/etc/sudoers.d/hermes-deals-w4c'
REPOSITORY='https://github.com/rozkalnsandris/hermes-deals.git'

blocked() {
  printf 'OWNER_FINALIZER_RESULT=BLOCKED\n'
  printf 'OWNER_FINALIZER_REASON=%s\n' "$1"
  exit 1
}

[[ "$(id -un)" == 'andris' && ${EUID:-$(id -u)} -ne 0 ]] || blocked 'owner_user_required'
[[ $# -eq 1 ]] || blocked 'usage_bridge_sha_required'
BRIDGE_SHA="$1"
[[ "$BRIDGE_SHA" =~ ^[0-9a-f]{40}$ ]] || blocked 'bridge_sha_invalid'

for command in docker find git install python3 sha256sum stat sudo tar visudo; do
  command -v "$command" >/dev/null 2>&1 || blocked "missing_command_${command}"
done
[[ -d "$PRIMARY" && ! -L "$PRIMARY" ]] || blocked 'production_root_missing_or_unsafe'
[[ -f "$PRIMARY/.env" && ! -L "$PRIMARY/.env" ]] || blocked 'production_env_missing_or_unsafe'

W="$(mktemp -d)"
trap 'rm -rf -- "$W"' EXIT
REPO="$W/repo"
STAGE="$W/source"
mkdir -m 0700 "$STAGE"

git clone --quiet --filter=blob:none --no-checkout "$REPOSITORY" "$REPO"
for sha in "$BRIDGE_SHA" "$TARGET_SHA" "$W4B_TARGET_SHA"; do
  git -C "$REPO" fetch --quiet origin "$sha"
done
git -C "$REPO" checkout --quiet --detach "$BRIDGE_SHA"
git -C "$REPO" merge-base --is-ancestor "$TARGET_SHA" "$BRIDGE_SHA" \
  || blocked 'target_not_ancestor_of_bridge'
git -C "$REPO" merge-base --is-ancestor "$W4B_TARGET_SHA" "$TARGET_SHA" \
  || blocked 'w4b_not_ancestor_of_w4c'

CONTROL_FILES=(
  'tools/runner/w4c/hermes_deals_w4c_operator.py'
  'tools/runner/w4c/http_header_contract.py'
  'tools/runner/w4c/docker-compose.w4c.yml'
  'tools/runner/w4c/hermes-deals-w4c-dispatch'
)
for relative in "${CONTROL_FILES[@]}"; do
  [[ -f "$REPO/$relative" && ! -L "$REPO/$relative" ]] \
    || blocked 'bridge_control_file_missing_or_unsafe'
done
python3 -m py_compile \
  "$REPO/tools/runner/w4c/hermes_deals_w4c_operator.py" \
  "$REPO/tools/runner/w4c/http_header_contract.py"
bash -n "$REPO/tools/runner/w4c/hermes-deals-w4c-dispatch"

grep -Fqx 'TARGET_SHA = "42238d93045e60430a42cd13b85b598e78c7d528"' \
  "$REPO/tools/runner/w4c/hermes_deals_w4c_operator.py" \
  || blocked 'operator_target_binding_missing'
grep -Fqx 'W4B_TARGET_SHA = "128325461f249791af8a5653163772e955dd2b89"' \
  "$REPO/tools/runner/w4c/hermes_deals_w4c_operator.py" \
  || blocked 'operator_baseline_binding_missing'

RUNTIME_PATHS=(
  backend/app
  backend/frontend
  backend/alembic
  backend/Dockerfile
  backend/requirements.txt
  backend/alembic.ini
  backend/.dockerignore
  docker-compose.yml
  docker-compose.production.yml
  infra/nginx.conf
)
mapfile -t runtime_changes < <(
  git -C "$REPO" diff --name-status "$W4B_TARGET_SHA" "$TARGET_SHA" -- "${RUNTIME_PATHS[@]}"
)
[[ ${#runtime_changes[@]} -eq 1 \
   && "${runtime_changes[0]}" == $'M\tbackend/app/runtime.py' ]] \
  || blocked 'w4c_runtime_delta_not_isolated'
git -C "$REPO" diff --check "$W4B_TARGET_SHA" "$TARGET_SHA" -- "${RUNTIME_PATHS[@]}" \
  || blocked 'w4c_runtime_delta_whitespace_invalid'

git -C "$REPO" show "$TARGET_SHA:backend/app/runtime.py" > "$W/target-runtime.py"
grep -Fq 'HTML_CACHE_CONTROL = "no-cache"' "$W/target-runtime.py" \
  || blocked 'target_html_cache_contract_missing'
grep -Fq 'HASHED_ASSET_CACHE_CONTROL = "public, max-age=31536000, immutable"' "$W/target-runtime.py" \
  || blocked 'target_asset_cache_contract_missing'

git -C "$REPO" archive --format=tar "$TARGET_SHA" > "$W/target.tar"
tar -xf "$W/target.tar" -C "$STAGE"
[[ -z "$(find "$STAGE" -type l -print -quit)" ]] || blocked 'target_snapshot_symlink_forbidden'

python3 - "$STAGE" <<'PY'
from pathlib import Path
import sys
root = Path(sys.argv[1])
required = [
    root / "backend/Dockerfile",
    root / "backend/requirements.txt",
    root / "backend/app/runtime.py",
    root / "docker-compose.yml",
    root / "docker-compose.production.yml",
    root / "infra/nginx.conf",
]
if any(not path.is_file() or path.is_symlink() for path in required):
    raise SystemExit(2)
PY

source_digest() {
  python3 - "$1" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys
root = Path(sys.argv[1])
if not root.is_dir() or root.is_symlink():
    raise SystemExit(2)
digest = sha256()
for path in sorted(root.rglob("*"), key=lambda item: item.relative_to(root).as_posix()):
    rel = path.relative_to(root).as_posix().encode()
    if path.is_symlink() or (not path.is_dir() and not path.is_file()):
        raise SystemExit(2)
    digest.update((b"D" if path.is_dir() else b"F") + b"\0" + rel + b"\0")
    if path.is_file():
        file_hash = sha256(path.read_bytes()).digest()
        digest.update(file_hash)
print(digest.hexdigest())
PY
}
TARGET_SOURCE_SHA256="$(source_digest "$STAGE")"

primary_state() {
  printf '%s\n' \
    "$(git -C "$PRIMARY" rev-parse HEAD)" \
    "$(git -C "$PRIMARY" branch --show-current)" \
    "$(git -C "$PRIMARY" status --porcelain=v1 --untracked-files=all)" \
    "$(git -C "$PRIMARY" diff --cached --binary --no-ext-diff --no-textconv)" \
    | sha256sum | awk '{print $1}'
}
container_id() {
  sudo --non-interactive docker ps \
    --filter 'label=com.docker.compose.project=hermes-deals' \
    --filter "label=com.docker.compose.service=$1" \
    --format '{{.ID}}'
}
cloudflared_pid() {
  sudo --non-interactive systemctl show -p MainPID --value cloudflared.service
}

PRIMARY_BEFORE="$(primary_state)"
ENV_BEFORE="$(sha256sum "$PRIMARY/.env" | awk '{print $1}')"
API_BEFORE="$(container_id api)"
WEB_BEFORE="$(container_id web)"
DB_BEFORE="$(container_id db)"
CLOUDFLARED_BEFORE="$(cloudflared_pid)"
[[ -n "$API_BEFORE" && -n "$WEB_BEFORE" && -n "$DB_BEFORE" ]] \
  || blocked 'production_container_baseline_missing'
[[ "$CLOUDFLARED_BEFORE" =~ ^[1-9][0-9]*$ ]] \
  || blocked 'cloudflared_baseline_invalid'

sudo --non-interactive install -d -o root -g root -m 0755 "$INSTALL_ROOT"
INSTALL_MODE='fresh'
if sudo --non-interactive test -e "$TARGET_ROOT"; then
  [[ "$(sudo --non-interactive stat -c '%U:%G:%a' "$TARGET_ROOT")" == 'root:root:755' ]] \
    || blocked 'existing_target_root_metadata_invalid'
  [[ "$(sudo --non-interactive stat -c '%U:%G:%a' "$SOURCE")" == 'root:root:755' ]] \
    || blocked 'existing_target_source_metadata_invalid'
  [[ -z "$(sudo --non-interactive find "$SOURCE" \( ! -user root -o ! -group root \) -print -quit)" ]] \
    || blocked 'existing_target_source_ownership_invalid'
  INSTALLED_SOURCE_SHA256="$(source_digest "$SOURCE")"
  [[ "$INSTALLED_SOURCE_SHA256" == "$TARGET_SOURCE_SHA256" ]] \
    || blocked 'existing_target_source_digest_mismatch'
  INSTALL_MODE='refresh'
else
  sudo --non-interactive install -d -o root -g root -m 0755 "$TARGET_ROOT" "$SOURCE"
  sudo --non-interactive cp -a "$STAGE/." "$SOURCE/"
  sudo --non-interactive chown -R root:root "$SOURCE"
  sudo --non-interactive find "$SOURCE" -type d -exec chmod 0755 {} +
  sudo --non-interactive find "$SOURCE" -type f -exec chmod 0644 {} +
  [[ "$(source_digest "$SOURCE")" == "$TARGET_SOURCE_SHA256" ]] \
    || blocked 'installed_target_source_digest_mismatch'
fi

sudo --non-interactive install -o root -g root -m 0755 \
  "$REPO/tools/runner/w4c/hermes_deals_w4c_operator.py" \
  "$INSTALL_ROOT/hermes_deals_w4c_operator.py"
sudo --non-interactive install -o root -g root -m 0755 \
  "$REPO/tools/runner/w4c/http_header_contract.py" \
  "$INSTALL_ROOT/http_header_contract.py"
sudo --non-interactive install -o root -g root -m 0644 \
  "$REPO/tools/runner/w4c/docker-compose.w4c.yml" \
  "$INSTALL_ROOT/docker-compose.w4c.yml"
sudo --non-interactive install -o root -g root -m 0755 \
  "$REPO/tools/runner/w4c/hermes-deals-w4c-dispatch" \
  "$DISPATCHER"

sudo --non-interactive sha256sum \
  "$INSTALL_ROOT/hermes_deals_w4c_operator.py" \
  "$INSTALL_ROOT/http_header_contract.py" \
  "$INSTALL_ROOT/docker-compose.w4c.yml" \
  > "$W/control.sha256"
sudo --non-interactive install -o root -g root -m 0644 \
  "$W/control.sha256" "$INSTALL_ROOT/control.sha256"

cat > "$W/sudoers" <<EOF
$RUNNER_USER ALL=(root) NOPASSWD: $DISPATCHER preflight
$RUNNER_USER ALL=(root) NOPASSWD: $DISPATCHER cutover
$RUNNER_USER ALL=(root) NOPASSWD: $DISPATCHER verify
EOF
visudo -cf "$W/sudoers" >/dev/null
sudo --non-interactive install -o root -g root -m 0440 "$W/sudoers" "$SUDOERS"
sudo --non-interactive visudo -cf "$SUDOERS" >/dev/null

set +e
PREFLIGHT_OUTPUT="$(sudo --non-interactive "$DISPATCHER" preflight 2>&1)"
PREFLIGHT_RC=$?
set -e
printf '%s\n' "$PREFLIGHT_OUTPUT" > "$W/preflight.out"
grep -E '^(W4C_RESULT|W4C_REASON|W4C_MODE|UI_STATE|BASELINE_CACHE|TARGET_CACHE|TARGET_SOURCE_READY|HASHED_ASSETS|LOOPBACK_BIND|DATABASE_UNCHANGED|PRODUCTION_GIT_UNCHANGED|PRODUCTION_ENV_UNCHANGED|CLOUDFLARED_STABLE|ROLLBACK_AVAILABLE|AUTO_ROLLBACK|PRODUCTION_MUTATED|NEXT_ACTION)=[A-Za-z0-9_.-]{1,96}$' "$W/preflight.out" || true
[[ $PREFLIGHT_RC -eq 0 ]] || blocked 'read_only_preflight_failed'
grep -Fxq 'W4C_RESULT=PASS' "$W/preflight.out" \
  || blocked 'read_only_preflight_not_pass'
grep -Fxq 'W4C_MODE=preflight' "$W/preflight.out" \
  || blocked 'read_only_preflight_mode_invalid'
grep -Fxq 'PRODUCTION_MUTATED=false' "$W/preflight.out" \
  || blocked 'read_only_preflight_mutation_flag_invalid'
grep -Fxq 'NEXT_ACTION=cutover' "$W/preflight.out" \
  || blocked 'read_only_preflight_next_action_invalid'

PRIMARY_AFTER="$(primary_state)"
ENV_AFTER="$(sha256sum "$PRIMARY/.env" | awk '{print $1}')"
API_AFTER="$(container_id api)"
WEB_AFTER="$(container_id web)"
DB_AFTER="$(container_id db)"
CLOUDFLARED_AFTER="$(cloudflared_pid)"
[[ "$PRIMARY_AFTER" == "$PRIMARY_BEFORE" ]] || blocked 'production_git_changed_during_finalizer'
[[ "$ENV_AFTER" == "$ENV_BEFORE" ]] || blocked 'production_env_changed_during_finalizer'
[[ "$API_AFTER" == "$API_BEFORE" && "$WEB_AFTER" == "$WEB_BEFORE" && "$DB_AFTER" == "$DB_BEFORE" ]] \
  || blocked 'production_runtime_changed_during_finalizer'
[[ "$CLOUDFLARED_AFTER" == "$CLOUDFLARED_BEFORE" ]] \
  || blocked 'cloudflared_changed_during_finalizer'

printf 'OWNER_FINALIZER_RESULT=PASS\n'
printf 'BRIDGE_SHA=%s\n' "$BRIDGE_SHA"
printf 'TARGET_SHA=%s\n' "$TARGET_SHA"
printf 'W4B_TARGET_SHA=%s\n' "$W4B_TARGET_SHA"
printf 'CONTROL_PLANE_INSTALL_MODE=%s\n' "$INSTALL_MODE"
printf 'TARGET_SOURCE_SHA256=%s\n' "$TARGET_SOURCE_SHA256"
printf 'RUNNER_PREFLIGHT_AUTHORIZED=true\n'
printf 'RUNNER_CUTOVER_AUTHORIZED=true\n'
printf 'RUNNER_VERIFY_AUTHORIZED=true\n'
printf 'RUNNER_ROLLBACK_AUTHORIZED=false\n'
printf 'READ_ONLY_PREFLIGHT=PASS\n'
printf 'PRODUCTION_GIT_UNCHANGED=true\n'
printf 'PRODUCTION_ENV_UNCHANGED=true\n'
printf 'PRODUCTION_RUNTIME_UNCHANGED=true\n'
printf 'CLOUDFLARED_UNCHANGED=true\n'
printf 'NEXT_GITHUB_ACTION=/hermes-477 preflight\n'
