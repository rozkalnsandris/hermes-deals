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
PLAN_SOURCE='tools/lidl_gate_b_freeze_plan.py'
APPLY_SOURCE='tools/lidl_gate_b_freeze_apply.py'
DISPATCHER_SOURCE='tools/runner/lidl-gate-b-plan-dispatcher.sh'
RUNNER_SERVICE='actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service'
INSTALLED_PLAN='/usr/local/libexec/hermes-deals-audits/lidl-gate-b-freeze-plan.py'
DISPATCHER='/usr/local/sbin/hermes-deals-lidl-gate-b-plan-dispatch'
CONF='/etc/hermes-deals-audits.d/lidl-gate-b-plan.conf'
SUDOERS='/etc/sudoers.d/hermes-deals-lidl-gate-b-plan'
EXPECTED_PLAN_BLOB='02f85620e4c881e4ef4b518751223bfb92fd91f8'
EXPECTED_APPLY_BLOB='b8e38b52be69aa6f0cdaa5dbb3f76ccb013c772f'

for user in andris github-runner; do id "$user" >/dev/null 2>&1 || fail "required user is missing: $user"; done
for command in bash git grep head id install mktemp readlink rm runuser sha256sum stat sudo systemctl visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
AUDIT_REPO="$(readlink -f -- "$AUDIT_REPO")"
[[ "$AUDIT_REPO" == /home/andris/hermes-deals-audit-source ]] || fail 'audit repository path drift'
[[ -d "$AUDIT_REPO/.git" && ! -L "$AUDIT_REPO/.git" ]] || fail 'audit repository is missing or unsafe'
[[ "$(stat -c '%U:%G' "$AUDIT_REPO")" == andris:andris ]] || fail 'audit repository ownership mismatch'
INDEX="$AUDIT_REPO/.git/index"
[[ -f "$INDEX" && ! -L "$INDEX" ]] || fail 'audit Git index is missing or unsafe'
[[ "$(stat -c '%U:%G' "$INDEX")" == andris:andris ]] || fail 'audit Git index ownership mismatch'
[[ ! -e "$INDEX.lock" ]] || fail 'audit Git index lock exists'
INDEX_SHA_BEFORE="$(sha256sum "$INDEX" | awk '{print $1}')"
INDEX_STAT_BEFORE="$(stat -c '%U:%G:%a:%s:%Y' "$INDEX")"

git_read() { runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" "$@"; }
BRANCH="$(git_read branch --show-current)" || fail 'cannot read audit branch'
HEAD_SHA="$(git_read rev-parse HEAD)" || fail 'cannot read audit HEAD'
STATUS="$(git_read status --porcelain=v1 --untracked-files=all)" || fail 'cannot read audit status'
[[ "$BRANCH" == main && "$HEAD_SHA" == "$EXPECTED_SHA" && -z "$STATUS" ]] || fail 'audit clone is not exact clean main at registered SHA'
git_read merge-base --is-ancestor "$EXPECTED_SHA" main || fail 'registered SHA is not reachable from audit main'
ORIGIN="$(git_read remote get-url origin)" || fail 'cannot read audit origin'
case "$ORIGIN" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail 'audit origin is not allowlisted' ;;
esac
for path in "$PLAN_SOURCE" "$APPLY_SOURCE" "$DISPATCHER_SOURCE"; do
  git_read cat-file -e "$EXPECTED_SHA:$path" || fail "registered file is missing: $path"
done
PLAN_BLOB="$(git_read rev-parse "$EXPECTED_SHA:$PLAN_SOURCE")"
APPLY_BLOB="$(git_read rev-parse "$EXPECTED_SHA:$APPLY_SOURCE")"
[[ "$PLAN_BLOB" == "$EXPECTED_PLAN_BLOB" ]] || fail 'Gate B planner blob identity drift'
[[ "$APPLY_BLOB" == "$EXPECTED_APPLY_BLOB" ]] || fail 'Gate B apply blob identity drift'

TMP="$(mktemp -d /tmp/hermes-deals-lidl-gate-b-plan-install.XXXXXX)"
cleanup() { rm -rf -- "$TMP"; }
trap cleanup EXIT
git_read show "$EXPECTED_SHA:$PLAN_SOURCE" > "$TMP/planner.py"
git_read show "$EXPECTED_SHA:$DISPATCHER_SOURCE" > "$TMP/dispatcher.sh"
[[ -s "$TMP/planner.py" && -s "$TMP/dispatcher.sh" ]] || fail 'registered files are empty'
head -n 1 "$TMP/planner.py" | grep -Fxq '#!/usr/bin/env python3' || fail 'planner header is invalid'
head -n 1 "$TMP/dispatcher.sh" | grep -Fxq '#!/usr/bin/env bash' || fail 'dispatcher header is invalid'
python3 -m py_compile "$TMP/planner.py"
bash -n "$TMP/dispatcher.sh"

cat > "$TMP/sudoers" <<'SUDOERS'
Defaults!/usr/local/sbin/hermes-deals-lidl-gate-b-plan-dispatch env_reset,secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-lidl-gate-b-plan-dispatch *
SUDOERS
chmod 0440 "$TMP/sudoers"
visudo -cf "$TMP/sudoers" >/dev/null

install -d -o root -g root -m 0755 /usr/local/libexec/hermes-deals-audits /etc/hermes-deals-audits.d
install -d -o andris -g andris -m 0700 /home/andris/hermes-deals-runner-evidence
[[ -d /home/andris/hermes-deals-lidl-gate-a-evidence && ! -L /home/andris/hermes-deals-lidl-gate-a-evidence ]] || fail 'retained Gate A evidence root is missing or unsafe'
[[ -d /home/andris/hermes-deals-lidl-corpus/flyers && ! -L /home/andris/hermes-deals-lidl-corpus/flyers ]] || fail 'authoritative Lidl corpus is missing or unsafe'
[[ "$(stat -c '%U:%G' /home/andris/hermes-deals-lidl-gate-a-evidence)" == andris:andris ]] || fail 'Gate A evidence root ownership mismatch'
[[ "$(stat -c '%U:%G' /home/andris/hermes-deals-lidl-corpus)" == andris:andris ]] || fail 'Lidl corpus root ownership mismatch'
install -o root -g root -m 0755 "$TMP/planner.py" "$INSTALLED_PLAN"
install -o root -g root -m 0755 "$TMP/dispatcher.sh" "$DISPATCHER"
install -o root -g root -m 0440 "$TMP/sudoers" "$SUDOERS"
PLANNER_SHA="$(sha256sum "$INSTALLED_PLAN" | awk '{print $1}')"
DISPATCHER_SHA="$(sha256sum "$DISPATCHER" | awk '{print $1}')"
CONF_TMP="$(mktemp /etc/hermes-deals-audits.d/.lidl-gate-b-plan.conf.XXXXXX)"
cat > "$CONF_TMP" <<CONF
audit_name='lidl-gate-b-plan'
commit_sha='$EXPECTED_SHA'
planner_path='$INSTALLED_PLAN'
planner_sha256='$PLANNER_SHA'
planner_blob_sha='$PLAN_BLOB'
apply_blob_sha='$APPLY_BLOB'
dispatcher_sha256='$DISPATCHER_SHA'
CONF
chown root:root "$CONF_TMP"
chmod 0644 "$CONF_TMP"
mv -f -- "$CONF_TMP" "$CONF"

[[ "$(sha256sum "$INDEX" | awk '{print $1}')" == "$INDEX_SHA_BEFORE" ]] || fail 'audit Git index content changed during installation'
[[ "$(stat -c '%U:%G:%a:%s:%Y' "$INDEX")" == "$INDEX_STAT_BEFORE" ]] || fail 'audit Git index metadata changed during installation'
[[ ! -e "$INDEX.lock" ]] || fail 'installer left an audit Git index lock'
[[ ! -e /usr/local/libexec/hermes-deals-audits/lidl-gate-b-freeze-apply.py ]] || fail 'installer must not install Gate B apply capability'
visudo -cf "$SUDOERS" >/dev/null
systemctl is-active --quiet "$RUNNER_SERVICE" || fail 'GitHub Actions audit runner service is not active'
sudo -l -U github-runner | grep -Fq "$DISPATCHER" || fail 'github-runner dispatcher sudo rule is missing'
RUNNER_HAS_DOCKER="$(id -nG github-runner | tr ' ' '\n' | grep -Fxq docker && echo true || echo false)"
[[ "$RUNNER_HAS_DOCKER" == false ]] || fail 'github-runner must not belong to docker group'

printf 'INSTALL_RESULT=PASS\n'
printf 'AUDIT=lidl-gate-b-plan\n'
printf 'REGISTERED_COMMIT=%s\n' "$EXPECTED_SHA"
printf 'PLANNER_BLOB_SHA=%s\n' "$PLAN_BLOB"
printf 'APPLY_BLOB_SHA=%s\n' "$APPLY_BLOB"
printf 'PLANNER_SHA256=%s\n' "$PLANNER_SHA"
printf 'DISPATCHER_SHA256=%s\n' "$DISPATCHER_SHA"
printf 'AUDIT_GIT_INDEX_UNCHANGED=true\nSUDOERS_VALID=true\nRUNNER_HAS_DOCKER_GROUP=false\n'
printf 'APPLY_CAPABILITY_INSTALLED=false\nCORPUS_WRITE=false\nPARSER_SCAN=false\nPRODUCTION_DATABASE_WRITE=false\nREVIEW_WRITE=false\nPRODUCTION_PUBLISH=false\nPRODUCTION_DEPLOY=false\nSYSTEMD_CHANGE=false\nAUTOMATIC_RETRY=false\nGATE_C_D_AUTHORIZED=false\n'
