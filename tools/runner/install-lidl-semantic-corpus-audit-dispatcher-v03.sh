#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

DISPATCHER_VERSION="lidl-semantic-corpus-dispatcher-v03-owned-log"
AUDIT_VERSION="lidl-semantic-corpus-audit-v02.3-partition-contract"
AUDIT_REPO="/home/andris/hermes-deals-audit-source"
V02_INSTALLER="tools/runner/install-lidl-semantic-corpus-audit-dispatcher-v02.sh"
DISPATCHER="/usr/local/sbin/hermes-deals-lidl-semantic-corpus-audit-dispatch"
RUNNER_SERVICE="actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "run with sudo"
[[ $# -eq 1 ]] || fail "usage: sudo bash tools/runner/install-lidl-semantic-corpus-audit-dispatcher-v03.sh <merged-commit-sha>"

EXPECTED_SHA="$1"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid merged commit SHA"

for user in andris github-runner; do
  id "$user" >/dev/null 2>&1 || fail "required user is missing: $user"
done
for command in bash git install mktemp python3 readlink rm sha256sum stat systemctl visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

AUDIT_REPO="$(readlink -f -- "$AUDIT_REPO")"
[[ "$AUDIT_REPO" == "/home/andris/hermes-deals-audit-source" ]] || fail "isolated audit repository path drift"
[[ -d "$AUDIT_REPO/.git" && ! -L "$AUDIT_REPO/.git" ]] || fail "isolated audit repository is missing or unsafe"
[[ "$(stat -c '%U:%G' "$AUDIT_REPO")" == "andris:andris" ]] || fail "isolated audit repository ownership is invalid"
GIT_INDEX="$AUDIT_REPO/.git/index"
[[ -f "$GIT_INDEX" && ! -L "$GIT_INDEX" ]] || fail "isolated audit repository index is missing or unsafe"
[[ "$(stat -c '%U:%G' "$GIT_INDEX")" == "andris:andris" ]] || fail "isolated audit repository index ownership is invalid"
[[ ! -e "$AUDIT_REPO/.git/index.lock" ]] || fail "isolated audit repository has a stale index lock"

index_sha_before="$(sha256sum "$GIT_INDEX" | awk '{print $1}')"
index_stat_before="$(stat -c '%U:%G:%a:%s:%Y' "$GIT_INDEX")"

git_read() {
  GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" "$@"
}

branch="$(git_read branch --show-current)" || fail "cannot read isolated audit repository branch"
[[ "$branch" == "main" ]] || fail "isolated audit repository branch must be main"
status="$(git_read status --porcelain)" || fail "cannot read isolated audit repository status"
[[ -z "$status" ]] || fail "isolated audit repository is not clean"
head_sha="$(git_read rev-parse HEAD)" || fail "cannot read isolated audit repository HEAD"
[[ "$head_sha" == "$EXPECTED_SHA" ]] || fail "isolated audit repository HEAD mismatch"
git_read cat-file -e "$EXPECTED_SHA^{commit}" || fail "merged commit is missing"
git_read merge-base --is-ancestor "$EXPECTED_SHA" main || fail "merged commit is not reachable from isolated main"

origin="$(git_read remote get-url origin)" || fail "cannot read isolated audit repository origin"
case "$origin" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail "isolated audit repository origin is not allowlisted" ;;
esac

[[ -f "$AUDIT_REPO/$V02_INSTALLER" && ! -L "$AUDIT_REPO/$V02_INSTALLER" ]] || fail "V02 installer is missing or unsafe"
/bin/bash "$AUDIT_REPO/$V02_INSTALLER" "$EXPECTED_SHA"

[[ "$(sha256sum "$GIT_INDEX" | awk '{print $1}')" == "$index_sha_before" ]] || fail "isolated audit repository index content changed during V03 installation"
[[ "$(stat -c '%U:%G:%a:%s:%Y' "$GIT_INDEX")" == "$index_stat_before" ]] || fail "isolated audit repository index metadata changed during V03 installation"
[[ ! -e "$AUDIT_REPO/.git/index.lock" ]] || fail "V03 installer left an index lock"

[[ -x "$DISPATCHER" && ! -L "$DISPATCHER" ]] || fail "V02 dispatcher installation did not complete"
[[ "$(stat -c '%U:%G' "$DISPATCHER")" == "root:root" ]] || fail "dispatcher ownership is invalid"
dispatcher_sha_before="$(sha256sum "$DISPATCHER" | awk '{print $1}')"

patched_dispatcher="$(mktemp /tmp/lidl-semantic-corpus-dispatcher-v03.XXXXXX)"
cleanup() {
  rm -f -- "$patched_dispatcher"
}
trap cleanup EXIT

python3 - "$DISPATCHER" "$patched_dispatcher" <<'PY'
import pathlib
import sys

source = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
text = source.read_text(encoding="utf-8")

old = r'''set +e
runuser -u andris -- /usr/bin/env -i \
  HOME=/home/andris \
'''
new = r'''install -o andris -g andris -m 0600 /dev/null "$staging/audit-execution.log"
[[ -f "$staging/audit-execution.log" && ! -L "$staging/audit-execution.log" ]] || fail "audit execution log is missing or unsafe"
[[ "$(stat -c '%U:%G:%a' "$staging/audit-execution.log")" == 'andris:andris:600' ]] || fail "audit execution log ownership or permissions are invalid"

set +e
runuser -u andris -- /usr/bin/env -i \
  HOME=/home/andris \
'''
if text.count(old) != 1:
    raise SystemExit("expected exactly one V01 dispatcher runuser marker")
text = text.replace(old, new, 1)
destination.write_text(text, encoding="utf-8")
PY

/bin/bash -n "$patched_dispatcher"
install -o root -g root -m 0755 "$patched_dispatcher" "$DISPATCHER"

dispatcher_sha="$(sha256sum "$DISPATCHER" | awk '{print $1}')"
[[ "$dispatcher_sha" =~ ^[0-9a-f]{64}$ ]] || fail "installed dispatcher SHA is invalid"
[[ "$dispatcher_sha" != "$dispatcher_sha_before" ]] || fail "dispatcher V03 patch did not change the installed dispatcher"
[[ "$(stat -c '%U:%G:%a' "$DISPATCHER")" == "root:root:755" ]] || fail "installed dispatcher metadata is invalid"
grep -Fq 'install -o andris -g andris -m 0600 /dev/null "$staging/audit-execution.log"' "$DISPATCHER" || fail "dispatcher does not precreate the audit execution log"
grep -Fq "andris:andris:600" "$DISPATCHER" || fail "dispatcher audit-log metadata guard is missing"

systemctl is-active --quiet "$RUNNER_SERVICE" || fail "GitHub Actions runner service is not active"
visudo -cf /etc/sudoers.d/hermes-deals-lidl-semantic-corpus-audit >/dev/null
sudo -l -U github-runner | grep -Fq "$DISPATCHER" || fail "github-runner dispatcher sudo rule is missing"
runner_has_docker="$(id -nG github-runner | tr ' ' '\n' | grep -Fxq docker && echo true || echo false)"
[[ "$runner_has_docker" == false ]] || fail "github-runner must not belong to docker group"

printf 'INSTALL_RESULT=PASS\nAUDIT=lidl-semantic-corpus\nAUDIT_VERSION=%s\nDISPATCHER_VERSION=%s\nREGISTERED_COMMIT=%s\nISOLATED_SOURCE_REPO=%s\nPRIMARY_WORKTREE_MODIFIED=false\nAUDIT_GIT_INDEX_UNCHANGED=true\nDISPATCHER_SHA256=%s\nSUDOERS_VALID=true\nRUNNER_HAS_DOCKER_GROUP=false\nPRODUCTION_APPLY_AUTHORIZED=false\n' \
  "$AUDIT_VERSION" "$DISPATCHER_VERSION" "$EXPECTED_SHA" "$AUDIT_REPO" "$dispatcher_sha"
