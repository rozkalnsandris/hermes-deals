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

AUDIT_REPO='/home/andris/hermes-deals-audit-source-lidl-refresh'
TOOL_SOURCE='tools/lidl_source_refresh_audit.py'
DISPATCHER_SOURCE='tools/runner/lidl-source-refresh-audit-dispatcher.sh'
RUNNER_SERVICE='actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service'
INSTALLED_TOOL='/usr/local/libexec/hermes-deals-audits/lidl-source-refresh-audit.py'
DISPATCHER='/usr/local/sbin/hermes-deals-lidl-source-refresh-audit-dispatch'
CONF='/etc/hermes-deals-audits.d/lidl-source-refresh.conf'
SUDOERS='/etc/sudoers.d/hermes-deals-lidl-source-refresh-audit'

for user in andris github-runner; do id "$user" >/dev/null 2>&1 || fail "required user is missing: $user"; done
for command in bash git grep head id install mktemp readlink rm runuser sha256sum stat sudo systemctl visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
AUDIT_REPO="$(readlink -f -- "$AUDIT_REPO")"
[[ "$AUDIT_REPO" == /home/andris/hermes-deals-audit-source-lidl-refresh ]] || fail 'audit repository path drift'
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
for path in "$TOOL_SOURCE" "$DISPATCHER_SOURCE"; do
  git_read cat-file -e "$EXPECTED_SHA:$path" || fail "registered file is missing: $path"
done
TOOL_BLOB="$(git_read rev-parse "$EXPECTED_SHA:$TOOL_SOURCE")"
DISPATCHER_BLOB="$(git_read rev-parse "$EXPECTED_SHA:$DISPATCHER_SOURCE")"
[[ "$TOOL_BLOB" =~ ^[0-9a-f]{40}$ && "$DISPATCHER_BLOB" =~ ^[0-9a-f]{40}$ ]] || fail 'registered blob identity is invalid'

TMP="$(mktemp -d /tmp/hermes-deals-lidl-source-refresh-install.XXXXXX)"
cleanup() { rm -rf -- "$TMP"; }
trap cleanup EXIT
git_read show "$EXPECTED_SHA:$TOOL_SOURCE" > "$TMP/tool.py"
git_read show "$EXPECTED_SHA:$DISPATCHER_SOURCE" > "$TMP/dispatcher.sh"
[[ -s "$TMP/tool.py" && -s "$TMP/dispatcher.sh" ]] || fail 'registered files are empty'
head -n 1 "$TMP/tool.py" | grep -Fxq '#!/usr/bin/env python3' || fail 'tool header is invalid'
head -n 1 "$TMP/dispatcher.sh" | grep -Fxq '#!/usr/bin/env bash' || fail 'dispatcher header is invalid'
python3 -m py_compile "$TMP/tool.py"
bash -n "$TMP/dispatcher.sh"

cat > "$TMP/sudoers" <<'SUDOERS'
Defaults!/usr/local/sbin/hermes-deals-lidl-source-refresh-audit-dispatch env_reset,secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-lidl-source-refresh-audit-dispatch *
SUDOERS
chmod 0440 "$TMP/sudoers"
visudo -cf "$TMP/sudoers" >/dev/null

install -d -o root -g root -m 0755 /usr/local/libexec/hermes-deals-audits /etc/hermes-deals-audits.d
install -d -o andris -g andris -m 0700 /home/andris/hermes-deals-runner-evidence
FAMILY='/home/andris/hermes-deals-lidl-corpus/flyers/aktionsprospekt-03-08-2026-08-08-2026-b1cf3b--src-6da2135ea984'
[[ -d "$FAMILY" && ! -L "$FAMILY" ]] || fail 'exact frozen rev05 sibling is missing or unsafe'
[[ "$(stat -c '%U:%G:%a' "$FAMILY")" == andris:andris:700 ]] || fail 'exact frozen rev05 sibling metadata mismatch'
install -o root -g root -m 0755 "$TMP/tool.py" "$INSTALLED_TOOL"
install -o root -g root -m 0755 "$TMP/dispatcher.sh" "$DISPATCHER"
install -o root -g root -m 0440 "$TMP/sudoers" "$SUDOERS"
TOOL_SHA="$(sha256sum "$INSTALLED_TOOL" | awk '{print $1}')"
DISPATCHER_SHA="$(sha256sum "$DISPATCHER" | awk '{print $1}')"
CONF_TMP="$(mktemp /etc/hermes-deals-audits.d/.lidl-source-refresh.conf.XXXXXX)"
cat > "$CONF_TMP" <<CONF
audit_name='lidl-source-refresh'
commit_sha='$EXPECTED_SHA'
tool_path='$INSTALLED_TOOL'
tool_sha256='$TOOL_SHA'
tool_blob_sha='$TOOL_BLOB'
dispatcher_blob_sha='$DISPATCHER_BLOB'
dispatcher_sha256='$DISPATCHER_SHA'
CONF
chown root:root "$CONF_TMP"
chmod 0644 "$CONF_TMP"
mv -f -- "$CONF_TMP" "$CONF"

[[ "$(sha256sum "$INDEX" | awk '{print $1}')" == "$INDEX_SHA_BEFORE" ]] || fail 'audit Git index content changed during installation'
[[ "$(stat -c '%U:%G:%a:%s:%Y' "$INDEX")" == "$INDEX_STAT_BEFORE" ]] || fail 'audit Git index metadata changed during installation'
[[ ! -e "$INDEX.lock" ]] || fail 'installer left an audit Git index lock'
visudo -cf "$SUDOERS" >/dev/null
systemctl is-active --quiet "$RUNNER_SERVICE" || fail 'GitHub Actions audit runner service is not active'
sudo -l -U github-runner | grep -Fq "$DISPATCHER" || fail 'github-runner source-refresh dispatcher sudo rule is missing'
RUNNER_HAS_DOCKER="$(id -nG github-runner | tr ' ' '\n' | grep -Fxq docker && echo true || echo false)"
[[ "$RUNNER_HAS_DOCKER" == false ]] || fail 'github-runner must not belong to docker group'

printf 'INSTALL_RESULT=PASS\nAUDIT=lidl-source-refresh\nREGISTERED_COMMIT=%s\n' "$EXPECTED_SHA"
printf 'TOOL_BLOB_SHA=%s\nDISPATCHER_BLOB_SHA=%s\nTOOL_SHA256=%s\nDISPATCHER_SHA256=%s\n' "$TOOL_BLOB" "$DISPATCHER_BLOB" "$TOOL_SHA" "$DISPATCHER_SHA"
printf 'AUDIT_GIT_INDEX_UNCHANGED=true\nSUDOERS_VALID=true\nRUNNER_HAS_DOCKER_GROUP=false\n'
printf 'CORPUS_WRITE=false\nPARSER_SCAN=false\nPRODUCTION_DATABASE_WRITE=false\nREVIEW_WRITE=false\nPRODUCTION_PUBLISH=false\nPRODUCTION_DEPLOY=false\nSYSTEMD_CHANGE=false\nAUTOMATIC_RETRY=false\nGATE_C_D_AUTHORIZED=false\n'
