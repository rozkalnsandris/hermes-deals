#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'run installer with sudo'
[[ $# -eq 1 ]] || fail 'usage: installer <exact-merged-main-sha>'
EXPECTED_SHA="$1"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'invalid merged commit SHA'

AUDIT_REPO='/home/andris/hermes-deals-audit-source'
C3_REL='tools/lidl_v631_c3_readonly_preflight.py'
CORE_REL='backend/app/lidl_v631_c3_readonly_preflight.py'
PLANNER_REL='backend/app/lidl_v631_semantic_persistence.py'
DISPATCHER_REL='tools/runner/lidl-v631-c3-readonly-dispatcher.sh'
LOCK_REL='backend/locks/runtime-py311.txt'
MANIFEST_REL='backend/locks/manifest.json'
VERIFIER_REL='scripts/verify-python-lock-environment.py'
DISPATCHER='/usr/local/sbin/hermes-deals-lidl-v631-c3-readonly'
CONF='/etc/hermes-deals-audits.d/lidl-v631-c3-readonly.conf'
SUDOERS='/etc/sudoers.d/hermes-deals-lidl-v631-c3-readonly'
PRIVATE_ROOT='/var/lib/hermes-deals/lidl-v631-c3-readonly-private'
EVIDENCE_ROOT='/var/lib/hermes-deals/lidl-v631-c3-readonly'
RUNTIME_PARENT='/opt/hermes-deals-audits/lidl-v631-c3-readonly'
RUNNER_SERVICE='actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service'
EXPECTED_C3_BLOB='1975cab5cb8d9c27104eb10b85ec7018659bfe2c'
EXPECTED_CORE_BLOB='69bc685ca5792079fdda1e73c09af94dfc28e29c'
EXPECTED_PLANNER_BLOB='5c183c4459275c99c7d0f9d66a7a5c425384a5be'
EXPECTED_DISPATCHER_BLOB='40583d1f37b2b50007f024820c1b457869ae621e'
EXPECTED_LOCK_BLOB='d6a64564901ce38dd4a790d44ead89be917f1b21'
EXPECTED_MANIFEST_BLOB='bb0e40363afeb89a176b95bc3b9314dbef075a5d'
EXPECTED_VERIFIER_BLOB='5c7c8d5e32ef84308b688213224b2528d99378e0'

for user in andris github-runner; do id "$user" >/dev/null 2>&1 || fail "required user missing: $user"; done
for command in bash chmod docker find git grep head id install mktemp mv python3 readlink rm runuser sha256sum stat sudo systemctl visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command missing: $command"
done
AUDIT_REPO="$(readlink -f -- "$AUDIT_REPO")"
[[ "$AUDIT_REPO" == /home/andris/hermes-deals-audit-source ]] || fail 'audit repository path drift'
[[ -d "$AUDIT_REPO/.git" && ! -L "$AUDIT_REPO/.git" ]] || fail 'audit repository missing or unsafe'
[[ "$(stat -c '%U:%G' "$AUDIT_REPO")" == andris:andris ]] || fail 'audit repository ownership mismatch'
INDEX="$AUDIT_REPO/.git/index"
[[ -f "$INDEX" && ! -L "$INDEX" ]] || fail 'audit Git index missing or unsafe'
[[ "$(stat -c '%U:%G' "$INDEX")" == andris:andris ]] || fail 'audit Git index ownership mismatch'
[[ ! -e "$INDEX.lock" ]] || fail 'audit Git index lock exists'
INDEX_SHA_BEFORE="$(sha256sum "$INDEX" | awk '{print $1}')"
INDEX_STAT_BEFORE="$(stat -c '%U:%G:%a:%s:%Y' "$INDEX")"

git_read() { runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" "$@"; }
run_owner() { runuser -u andris -- env -i HOME=/home/andris USER=andris LOGNAME=andris PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 "$@"; }
BRANCH="$(git_read branch --show-current)"
HEAD_SHA="$(git_read rev-parse HEAD)"
STATUS="$(git_read status --porcelain=v1 --untracked-files=all)"
[[ "$BRANCH" == main && -z "$STATUS" ]] || fail 'audit clone is not clean main'
git_read cat-file -e "$EXPECTED_SHA^{commit}" || fail 'registered merge commit is unavailable'
git_read merge-base --is-ancestor "$EXPECTED_SHA" "$HEAD_SHA" || fail 'registered merge is not an ancestor of current audit main'
ORIGIN="$(git_read remote get-url origin)"
case "$ORIGIN" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail 'audit origin is not allowlisted' ;;
esac

for spec in \
  "$C3_REL:$EXPECTED_C3_BLOB" \
  "$CORE_REL:$EXPECTED_CORE_BLOB" \
  "$PLANNER_REL:$EXPECTED_PLANNER_BLOB" \
  "$DISPATCHER_REL:$EXPECTED_DISPATCHER_BLOB" \
  "$LOCK_REL:$EXPECTED_LOCK_BLOB" \
  "$MANIFEST_REL:$EXPECTED_MANIFEST_BLOB" \
  "$VERIFIER_REL:$EXPECTED_VERIFIER_BLOB"; do
  path="${spec%%:*}"; expected="${spec##*:}"
  git_read cat-file -e "$EXPECTED_SHA:$path" || fail "registered file missing: $path"
  [[ "$(git_read rev-parse "$EXPECTED_SHA:$path")" == "$expected" ]] || fail "registered blob identity drift: $path"
  [[ "$(git_read rev-parse "$HEAD_SHA:$path")" == "$expected" ]] || fail "current audit main blob identity drift: $path"
done

LOCK_SHA="$(sha256sum "$AUDIT_REPO/$LOCK_REL" | awk '{print $1}')"
MANIFEST_LOCK_SHA="$(python3 - "$AUDIT_REPO/$MANIFEST_REL" <<'PY'
import json, sys
obj=json.load(open(sys.argv[1],encoding='utf-8'))
row=obj.get('locks',{}).get('runtime-py311.txt') or {}
if row.get('python')!='3.11': raise SystemExit('runtime manifest Python mismatch')
print(row.get('sha256') or '')
PY
)"
[[ "$LOCK_SHA" =~ ^[0-9a-f]{64}$ && "$LOCK_SHA" == "$MANIFEST_LOCK_SHA" ]] || fail 'runtime lock manifest mismatch'
PYTHON_LINE="$(run_owner python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
[[ "$PYTHON_LINE" == 3.11 ]] || fail "pinned C3 runtime requires Python 3.11, got $PYTHON_LINE"
RUNTIME_ROOT="$RUNTIME_PARENT/runtime-py311-${EXPECTED_SHA:0:12}-${LOCK_SHA:0:16}"
RUNTIME_PYTHON="$RUNTIME_ROOT/bin/python"
[[ ! -e "$RUNTIME_ROOT" ]] || fail 'versioned C3 audit runtime path already exists'
install -d -o root -g root -m 0755 /etc/hermes-deals-audits.d /var/lib/hermes-deals /opt/hermes-deals-audits "$RUNTIME_PARENT"
install -d -o root -g root -m 0700 "$PRIVATE_ROOT"
install -d -o root -g root -m 0755 "$EVIDENCE_ROOT"

TMP="$(mktemp -d /var/tmp/hermes-deals-lidl-v631-c3-install.XXXXXX)"
RUNTIME_COMMITTED=false
cleanup() {
  rm -rf -- "$TMP"
  if [[ "$RUNTIME_COMMITTED" != true && -d "$RUNTIME_ROOT" ]]; then
    rm -rf -- "$RUNTIME_ROOT"
  fi
}
trap cleanup EXIT
chmod 0755 "$TMP"
git_read show "$EXPECTED_SHA:$DISPATCHER_REL" > "$TMP/dispatcher.sh"
[[ -s "$TMP/dispatcher.sh" ]] || fail 'dispatcher source empty'
head -n 1 "$TMP/dispatcher.sh" | grep -Fxq '#!/usr/bin/env bash' || fail 'dispatcher header invalid'
bash -n "$TMP/dispatcher.sh"

cat > "$TMP/sudoers" <<'SUDOERS'
Defaults!/usr/local/sbin/hermes-deals-lidl-v631-c3-readonly env_reset,secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-lidl-v631-c3-readonly *
SUDOERS
chmod 0440 "$TMP/sudoers"
visudo -cf "$TMP/sudoers" >/dev/null

install -d -o andris -g andris -m 0700 "$RUNTIME_ROOT"
BUILD_UMASK="$(umask)"
umask 022
run_owner python3 -m venv --copies "$RUNTIME_ROOT" || fail 'could not create pinned C3 audit venv at final path'
[[ -f "$RUNTIME_PYTHON" && ! -L "$RUNTIME_PYTHON" && -x "$RUNTIME_PYTHON" ]] || fail 'pinned C3 audit venv Python missing or unsafe'
runuser -u andris -- env -i \
  HOME=/home/andris USER=andris LOGNAME=andris PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 \
  PIP_CONFIG_FILE=/dev/null PIP_DISABLE_PIP_VERSION_CHECK=1 PIP_NO_INPUT=1 \
  "$RUNTIME_PYTHON" -m pip install --no-cache-dir --require-hashes --only-binary=:all: -r "$AUDIT_REPO/$LOCK_REL"
run_owner "$RUNTIME_PYTHON" -m pip check
ENVIRONMENT_REPORT="$(run_owner "$RUNTIME_PYTHON" "$AUDIT_REPO/$VERIFIER_REL" "$AUDIT_REPO/$LOCK_REL")"
INVENTORY_SHA="$(printf '%s\n' "$ENVIRONMENT_REPORT" | awk -F= '$1 == "LOCKED_INVENTORY_SHA256" {print $2}')"
[[ "$INVENTORY_SHA" =~ ^[0-9a-f]{64}$ ]] || fail 'pinned C3 runtime inventory SHA invalid'
for module in sqlalchemy psycopg pydantic; do
  run_owner "$RUNTIME_PYTHON" -c "import $module" >/dev/null 2>&1 || fail "pinned C3 runtime import failed: $module"
done
umask "$BUILD_UMASK"

chown -hR root:root "$RUNTIME_ROOT"
chmod -R a+rX,go-w "$RUNTIME_ROOT"
if find "$RUNTIME_ROOT" -xdev \( ! -user root -o ! -group root \) -print -quit | grep -q .; then
  fail 'installed C3 runtime ownership is unsafe'
fi
if find "$RUNTIME_ROOT" -xdev \( -type f -o -type d \) -perm /022 -print -quit | grep -q .; then
  fail 'installed C3 runtime write permissions are unsafe'
fi
[[ -f "$RUNTIME_PYTHON" && ! -L "$RUNTIME_PYTHON" && -x "$RUNTIME_PYTHON" ]] || fail 'installed C3 runtime Python missing or unsafe'
run_owner test -x "$RUNTIME_ROOT" || fail 'installed C3 runtime root is not traversable by audit owner'
run_owner test -x "$RUNTIME_PYTHON" || fail 'installed C3 runtime Python is not executable by audit owner'
run_owner "$RUNTIME_PYTHON" -c 'import sys; raise SystemExit(0 if sys.prefix else 1)' >/dev/null 2>&1 || fail 'installed C3 runtime Python cannot execute as audit owner'
RUNTIME_PYTHON_SHA="$(sha256sum "$RUNTIME_PYTHON" | awk '{print $1}')"
[[ "$RUNTIME_PYTHON_SHA" =~ ^[0-9a-f]{64}$ ]] || fail 'installed C3 runtime Python SHA invalid'
RUNTIME_PYTHON_VERSION="$(run_owner "$RUNTIME_PYTHON" - "$RUNTIME_ROOT" <<'PY'
import sys
expected=sys.argv[1]
version=f"{sys.version_info.major}.{sys.version_info.minor}"
if version != '3.11': raise SystemExit(f'unexpected runtime Python: {version}')
if sys.prefix != expected: raise SystemExit('runtime sys.prefix mismatch')
if sys.base_prefix == sys.prefix: raise SystemExit('runtime is not isolated')
print(version)
PY
)"
[[ "$RUNTIME_PYTHON_VERSION" == 3.11 ]] || fail 'installed C3 runtime Python identity mismatch'
FINAL_ENVIRONMENT_REPORT="$(run_owner "$RUNTIME_PYTHON" "$AUDIT_REPO/$VERIFIER_REL" "$AUDIT_REPO/$LOCK_REL")"
FINAL_INVENTORY_SHA="$(printf '%s\n' "$FINAL_ENVIRONMENT_REPORT" | awk -F= '$1 == "LOCKED_INVENTORY_SHA256" {print $2}')"
[[ "$FINAL_INVENTORY_SHA" == "$INVENTORY_SHA" ]] || fail 'installed C3 runtime inventory changed after root ownership transfer'
for module in sqlalchemy psycopg pydantic; do
  run_owner "$RUNTIME_PYTHON" -c "import $module" >/dev/null 2>&1 || fail "installed C3 runtime import failed: $module"
done

install -o root -g root -m 0755 "$TMP/dispatcher.sh" "$DISPATCHER"
install -o root -g root -m 0440 "$TMP/sudoers" "$SUDOERS"
DISPATCHER_SHA="$(sha256sum "$DISPATCHER" | awk '{print $1}')"
[[ "$(sha256sum "$INDEX" | awk '{print $1}')" == "$INDEX_SHA_BEFORE" ]] || fail 'audit Git index content changed during installation'
[[ "$(stat -c '%U:%G:%a:%s:%Y' "$INDEX")" == "$INDEX_STAT_BEFORE" ]] || fail 'audit Git index metadata changed during installation'
[[ ! -e "$INDEX.lock" ]] || fail 'installer left audit Git index lock'
[[ "$(stat -c '%U:%G:%a' "$PRIVATE_ROOT")" == root:root:700 ]] || fail 'private C3 root metadata mismatch'
[[ "$(stat -c '%U:%G:%a' "$EVIDENCE_ROOT")" == root:root:755 ]] || fail 'sanitized C3 evidence root metadata mismatch'
visudo -cf "$SUDOERS" >/dev/null
systemctl is-active --quiet "$RUNNER_SERVICE" || fail 'GitHub Actions audit runner service is not active'
sudo -l -U github-runner | grep -Fq "$DISPATCHER" || fail 'github-runner dispatcher sudo rule missing'
RUNNER_HAS_DOCKER="$(id -nG github-runner | tr ' ' '\n' | grep -Fxq docker && echo true || echo false)"
[[ "$RUNNER_HAS_DOCKER" == false ]] || fail 'github-runner must not belong to docker group'

CONF_TMP="$(mktemp /etc/hermes-deals-audits.d/.lidl-v631-c3-readonly.conf.XXXXXX)"
cat > "$CONF_TMP" <<CONF
audit_name='lidl-v631-c3-readonly'
registered_merge_sha='$EXPECTED_SHA'
c3_blob='$EXPECTED_C3_BLOB'
core_blob='$EXPECTED_CORE_BLOB'
planner_blob='$EXPECTED_PLANNER_BLOB'
dispatcher_blob='$EXPECTED_DISPATCHER_BLOB'
dispatcher_sha256='$DISPATCHER_SHA'
runtime_python='$RUNTIME_PYTHON'
runtime_python_sha256='$RUNTIME_PYTHON_SHA'
runtime_lock_sha256='$LOCK_SHA'
runtime_inventory_sha256='$INVENTORY_SHA'
CONF
chown root:root "$CONF_TMP"
chmod 0644 "$CONF_TMP"
mv -f -- "$CONF_TMP" "$CONF"

RUNTIME_COMMITTED=true

printf 'INSTALL_RESULT=PASS\n'
printf 'AUDIT=lidl-v631-c3-readonly\nREGISTERED_COMMIT=%s\nAUDIT_CURRENT_HEAD=%s\n' "$EXPECTED_SHA" "$HEAD_SHA"
printf 'C3_BLOB_SHA=%s\nCORE_BLOB_SHA=%s\nPLANNER_BLOB_SHA=%s\nDISPATCHER_BLOB_SHA=%s\n' "$EXPECTED_C3_BLOB" "$EXPECTED_CORE_BLOB" "$EXPECTED_PLANNER_BLOB" "$EXPECTED_DISPATCHER_BLOB"
printf 'DISPATCHER_SHA256=%s\n' "$DISPATCHER_SHA"
printf 'RUNTIME_PYTHON=%s\nRUNTIME_PYTHON_SHA256=%s\nRUNTIME_PYTHON_VERSION=%s\nRUNTIME_LOCK_SHA256=%s\nRUNTIME_INVENTORY_SHA256=%s\n' "$RUNTIME_PYTHON" "$RUNTIME_PYTHON_SHA" "$RUNTIME_PYTHON_VERSION" "$LOCK_SHA" "$INVENTORY_SHA"
printf 'AUDIT_GIT_INDEX_UNCHANGED=true\nSUDOERS_VALID=true\nRUNNER_HAS_DOCKER_GROUP=false\n'
printf 'PRIVATE_STAGING_ROOT=%s\nSANITIZED_EVIDENCE_ROOT=%s\n' "$PRIVATE_ROOT" "$EVIDENCE_ROOT"
printf 'AUDIT_RUNTIME_PACKAGE_INSTALL=true\nSYSTEM_PACKAGE_INSTALL=false\n'
printf 'PRODUCTION_DATABASE_WRITE=false\nCORPUS_WRITE=false\nREVIEW_WRITE=false\nPRODUCTION_PUBLISH=false\nPRODUCTION_DEPLOY=false\nSYSTEMD_CHANGE=false\nSCHEDULER_CHANGE=false\n'
printf 'NOTE=installer provisions a hash-pinned root-owned C3 audit venv and dispatcher registration only; C3 execution still requires separate owner authorization\n'
