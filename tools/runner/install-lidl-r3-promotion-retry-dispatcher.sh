#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'run retry installer with sudo'
[[ $# -eq 1 ]] || fail 'usage: installer <exact-merged-main-sha>'
EXPECTED_SHA="$1"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'invalid merged commit SHA'

AUDIT_REPO='/home/andris/hermes-deals-audit-source-lidl-refresh'
BASE_APPLY_SOURCE='tools/lidl_source_refresh_r3_apply.py'
APPLY_V2_SOURCE='tools/lidl_source_refresh_r3_apply_v2.py'
PLAN_SOURCE='tools/lidl_source_refresh_r3_plan.py'
PLAN_V2_SOURCE='tools/lidl_source_refresh_r3_plan_v2.py'
DISPATCHER_SOURCE='tools/runner/lidl_r3_promotion_retry_dispatcher.py'
RUNNER_SERVICE='actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service'
LIBEXEC='/usr/local/libexec/hermes-deals-r3-retry'
BASE_APPLY="$LIBEXEC/lidl_source_refresh_r3_apply.py"
APPLY_V2="$LIBEXEC/lidl_source_refresh_r3_apply_v2.py"
PLAN="$LIBEXEC/lidl_source_refresh_r3_plan.py"
PLAN_V2="$LIBEXEC/lidl_source_refresh_r3_plan_v2.py"
DISPATCHER='/usr/local/sbin/hermes-deals-lidl-r3-promotion-retry-dispatch'
CONF='/etc/hermes-deals-audits.d/lidl-r3-promotion-retry.json'
SUDOERS='/etc/sudoers.d/hermes-deals-lidl-r3-promotion-retry'
AUDIT_TOOL='/usr/local/libexec/hermes-deals-audits/lidl-source-refresh-audit.py'
AUDIT_TOOL_SHA='3ff8e244b463fb62ef632f8a8cf3be78012a7e72f6b36606a519590b7b634222'
FAMILY='/home/andris/hermes-deals-lidl-corpus/flyers/aktionsprospekt-03-08-2026-08-08-2026-b1cf3b--src-6da2135ea984'

for user in andris github-runner; do id "$user" >/dev/null 2>&1 || fail "required user missing: $user"; done
for command in bash git id install mktemp readlink rm runuser sha256sum stat sudo systemctl visudo python3; do
  command -v "$command" >/dev/null 2>&1 || fail "required command missing: $command"
done
AUDIT_REPO="$(readlink -f -- "$AUDIT_REPO")"
[[ "$AUDIT_REPO" == /home/andris/hermes-deals-audit-source-lidl-refresh ]] || fail 'audit repository path drift'
[[ -d "$AUDIT_REPO/.git" && ! -L "$AUDIT_REPO/.git" && "$(stat -c '%U:%G' "$AUDIT_REPO")" == andris:andris ]] || fail 'audit repository unsafe'
INDEX="$AUDIT_REPO/.git/index"
[[ -f "$INDEX" && ! -L "$INDEX" && ! -e "$INDEX.lock" ]] || fail 'audit Git index missing/locked/unsafe'
INDEX_SHA_BEFORE="$(sha256sum "$INDEX" | awk '{print $1}')"
INDEX_STAT_BEFORE="$(stat -c '%U:%G:%a:%s:%Y' "$INDEX")"

git_read() { runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" "$@"; }
[[ "$(git_read branch --show-current)" == main ]] || fail 'audit clone not on main'
[[ "$(git_read rev-parse HEAD)" == "$EXPECTED_SHA" ]] || fail 'audit clone HEAD differs from registered SHA'
[[ -z "$(git_read status --porcelain=v1 --untracked-files=all)" ]] || fail 'audit clone dirty'
case "$(git_read remote get-url origin)" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail 'audit origin not allowlisted' ;;
esac

SOURCES=("$BASE_APPLY_SOURCE" "$APPLY_V2_SOURCE" "$PLAN_SOURCE" "$PLAN_V2_SOURCE" "$DISPATCHER_SOURCE")
for path in "${SOURCES[@]}"; do git_read cat-file -e "$EXPECTED_SHA:$path" || fail "registered file missing: $path"; done
BASE_BLOB="$(git_read rev-parse "$EXPECTED_SHA:$BASE_APPLY_SOURCE")"
APPLY_V2_BLOB="$(git_read rev-parse "$EXPECTED_SHA:$APPLY_V2_SOURCE")"
PLAN_BLOB="$(git_read rev-parse "$EXPECTED_SHA:$PLAN_SOURCE")"
PLAN_V2_BLOB="$(git_read rev-parse "$EXPECTED_SHA:$PLAN_V2_SOURCE")"
DISPATCHER_BLOB="$(git_read rev-parse "$EXPECTED_SHA:$DISPATCHER_SOURCE")"
for value in "$BASE_BLOB" "$APPLY_V2_BLOB" "$PLAN_BLOB" "$PLAN_V2_BLOB" "$DISPATCHER_BLOB"; do [[ "$value" =~ ^[0-9a-f]{40}$ ]] || fail 'registered blob invalid'; done

TMP="$(mktemp -d /tmp/hermes-deals-lidl-r3-retry-install.XXXXXX)"
cleanup() { rm -rf -- "$TMP"; }
trap cleanup EXIT
git_read show "$EXPECTED_SHA:$BASE_APPLY_SOURCE" > "$TMP/lidl_source_refresh_r3_apply.py"
git_read show "$EXPECTED_SHA:$APPLY_V2_SOURCE" > "$TMP/lidl_source_refresh_r3_apply_v2.py"
git_read show "$EXPECTED_SHA:$PLAN_SOURCE" > "$TMP/lidl_source_refresh_r3_plan.py"
git_read show "$EXPECTED_SHA:$PLAN_V2_SOURCE" > "$TMP/lidl_source_refresh_r3_plan_v2.py"
git_read show "$EXPECTED_SHA:$DISPATCHER_SOURCE" > "$TMP/dispatcher.py"
for name in lidl_source_refresh_r3_apply.py lidl_source_refresh_r3_apply_v2.py lidl_source_refresh_r3_plan.py lidl_source_refresh_r3_plan_v2.py dispatcher.py; do
  [[ -s "$TMP/$name" ]] || fail "empty retry runtime: $name"
  python3 -m py_compile "$TMP/$name"
done
PYTHONPATH="$TMP" python3 - <<'PY'
import lidl_source_refresh_r3_apply_v2 as r
assert r.APPLY_VERSION == 'lidl-source-refresh-r3-promotion-apply-v2-retry'
assert r.RETIRED_AUTHORIZATION_COMMENT_ID == 5227260615
PY

cat > "$TMP/sudoers" <<'SUDOERS'
Defaults!/usr/local/sbin/hermes-deals-lidl-r3-promotion-retry-dispatch env_reset,secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-lidl-r3-promotion-retry-dispatch *
SUDOERS
chmod 0440 "$TMP/sudoers"
visudo -cf "$TMP/sudoers" >/dev/null

[[ -f "$AUDIT_TOOL" && ! -L "$AUDIT_TOOL" && "$(stat -c '%U:%G:%a' "$AUDIT_TOOL")" == root:root:755 ]] || fail 'semantic audit tool missing/unsafe'
[[ "$(sha256sum "$AUDIT_TOOL" | awk '{print $1}')" == "$AUDIT_TOOL_SHA" ]] || fail 'semantic audit tool drift'
[[ -d "$FAMILY" && ! -L "$FAMILY" && "$(stat -c '%U:%G:%a' "$FAMILY")" == andris:andris:700 ]] || fail 'rev05 family missing/unsafe'
[[ "$(sha256sum "$FAMILY/source.pdf" | awk '{print $1}')" == '6da2135ea984d1f79bdb311dfa0d8affd1d2f8d46c63a1bba25b202a30a5fb16' ]] || fail 'rev05 PDF drift'
[[ "$(sha256sum "$FAMILY/source.json" | awk '{print $1}')" == 'd1af2062f10f5fd25d4ac197fe74459bf0c313d7f5890f5d96c3db9572b7ddf1' ]] || fail 'rev05 source JSON drift'
[[ ! -e "$FAMILY/review-profile.json" && ! -L "$FAMILY/review-profile.json" ]] || fail 'rev05 profile must be absent'
[[ ! -e "$FAMILY/scans/scan-v631-7191e910f07b" && ! -L "$FAMILY/scans/scan-v631-7191e910f07b" ]] || fail 'R3 scan target already occupied'
[[ ! -e "$FAMILY/source-refresh/e6ebe5669551a2d455e7b2c036746e08e3bdd20e8e0562fab6972ab97e2a88e8" && ! -L "$FAMILY/source-refresh/e6ebe5669551a2d455e7b2c036746e08e3bdd20e8e0562fab6972ab97e2a88e8" ]] || fail 'R3 refresh target already occupied'

install -d -o root -g root -m 0755 "$LIBEXEC" /etc/hermes-deals-audits.d
install -d -o andris -g andris -m 0700 /home/andris/hermes-deals-r3-promotion-retry-evidence
install -o root -g root -m 0755 "$TMP/lidl_source_refresh_r3_apply.py" "$BASE_APPLY"
install -o root -g root -m 0755 "$TMP/lidl_source_refresh_r3_apply_v2.py" "$APPLY_V2"
install -o root -g root -m 0755 "$TMP/lidl_source_refresh_r3_plan.py" "$PLAN"
install -o root -g root -m 0755 "$TMP/lidl_source_refresh_r3_plan_v2.py" "$PLAN_V2"
install -o root -g root -m 0755 "$TMP/dispatcher.py" "$DISPATCHER"
install -o root -g root -m 0440 "$TMP/sudoers" "$SUDOERS"

BASE_SHA="$(sha256sum "$BASE_APPLY" | awk '{print $1}')"
APPLY_V2_SHA="$(sha256sum "$APPLY_V2" | awk '{print $1}')"
PLAN_SHA="$(sha256sum "$PLAN" | awk '{print $1}')"
PLAN_V2_SHA="$(sha256sum "$PLAN_V2" | awk '{print $1}')"
DISPATCHER_SHA="$(sha256sum "$DISPATCHER" | awk '{print $1}')"
CONF_TMP="$(mktemp /etc/hermes-deals-audits.d/.lidl-r3-promotion-retry.XXXXXX)"
EXPECTED_SHA="$EXPECTED_SHA" BASE_SHA="$BASE_SHA" APPLY_V2_SHA="$APPLY_V2_SHA" PLAN_SHA="$PLAN_SHA" PLAN_V2_SHA="$PLAN_V2_SHA" DISPATCHER_SHA="$DISPATCHER_SHA" python3 - <<'PY' > "$CONF_TMP"
import json, os
print(json.dumps({
 'schema_version':1,
 'audit_name':'lidl-r3-promotion-retry',
 'commit_sha':os.environ['EXPECTED_SHA'],
 'base_apply_sha256':os.environ['BASE_SHA'],
 'apply_v2_sha256':os.environ['APPLY_V2_SHA'],
 'plan_sha256':os.environ['PLAN_SHA'],
 'plan_v2_sha256':os.environ['PLAN_V2_SHA'],
 'dispatcher_sha256':os.environ['DISPATCHER_SHA'],
},sort_keys=True,indent=2))
PY
chown root:root "$CONF_TMP"; chmod 0644 "$CONF_TMP"; mv -f -- "$CONF_TMP" "$CONF"

[[ "$(sha256sum "$INDEX" | awk '{print $1}')" == "$INDEX_SHA_BEFORE" ]] || fail 'audit Git index content changed'
[[ "$(stat -c '%U:%G:%a:%s:%Y' "$INDEX")" == "$INDEX_STAT_BEFORE" ]] || fail 'audit Git index metadata changed'
[[ ! -e "$INDEX.lock" ]] || fail 'installer left Git index lock'
visudo -cf "$SUDOERS" >/dev/null
systemctl is-active --quiet "$RUNNER_SERVICE" || fail 'GitHub Actions audit runner inactive'
sudo -l -U github-runner | grep -Fq "$DISPATCHER" || fail 'runner retry dispatcher sudo rule missing'
RUNNER_HAS_DOCKER="$(id -nG github-runner | tr ' ' '\n' | grep -Fxq docker && echo true || echo false)"
[[ "$RUNNER_HAS_DOCKER" == false ]] || fail 'github-runner must not belong to docker group'

printf 'INSTALL_RESULT=PASS\nAUDIT=lidl-r3-promotion-retry\nREGISTERED_COMMIT=%s\n' "$EXPECTED_SHA"
printf 'BASE_APPLY_BLOB_SHA=%s\nAPPLY_V2_BLOB_SHA=%s\nPLAN_BLOB_SHA=%s\nPLAN_V2_BLOB_SHA=%s\nDISPATCHER_BLOB_SHA=%s\n' "$BASE_BLOB" "$APPLY_V2_BLOB" "$PLAN_BLOB" "$PLAN_V2_BLOB" "$DISPATCHER_BLOB"
printf 'BASE_APPLY_SHA256=%s\nAPPLY_V2_SHA256=%s\nPLAN_SHA256=%s\nPLAN_V2_SHA256=%s\nDISPATCHER_SHA256=%s\n' "$BASE_SHA" "$APPLY_V2_SHA" "$PLAN_SHA" "$PLAN_V2_SHA" "$DISPATCHER_SHA"
printf 'SUDOERS_VALID=true\nRUNNER_HAS_DOCKER_GROUP=false\nPROMOTION_EXECUTED=false\n'
printf 'CORPUS_WRITE=false\nPARSER_SCAN=false\nPRODUCTION_DATABASE_WRITE=false\nREVIEW_WRITE=false\nPRODUCTION_PUBLISH=false\nPRODUCTION_DEPLOY=false\nSYSTEMD_CHANGE=false\nAUTOMATIC_RETRY=false\nGATE_C_D_AUTHORIZED=false\nB15M2_V08_AUTHORIZED=false\n'
