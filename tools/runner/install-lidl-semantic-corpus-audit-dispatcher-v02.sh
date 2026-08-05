#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "run with sudo"
[[ $# -eq 1 ]] || fail "usage: sudo bash tools/runner/install-lidl-semantic-corpus-audit-dispatcher-v02.sh <merged-commit-sha>"

EXPECTED_SHA="$1"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid merged commit SHA"

AUDIT_REPO="/home/andris/hermes-deals-audit-source"
PRIMARY_REPO="/home/andris/hermes-deals"
V01_INSTALLER="tools/runner/install-lidl-semantic-corpus-audit-dispatcher.sh"
V02_SCRIPT="tools/run-hermes-deals-lidl-semantic-corpus-audit-v02.sh"
DISPATCHER="/usr/local/sbin/hermes-deals-lidl-semantic-corpus-audit-dispatch"
INSTALLED_SCRIPT="/usr/local/libexec/hermes-deals-audits/lidl-semantic-corpus.sh"
CONF="/etc/hermes-deals-audits.d/lidl-semantic-corpus.conf"
RUNNER_SERVICE="actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service"

for user in andris github-runner; do
  id "$user" >/dev/null 2>&1 || fail "required user is missing: $user"
done
for command in bash git install mktemp mount readlink sha256sum stat systemctl unshare visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

AUDIT_REPO="$(readlink -f -- "$AUDIT_REPO")"
[[ "$AUDIT_REPO" == "/home/andris/hermes-deals-audit-source" ]] || fail "isolated audit repository path drift"
[[ -d "$AUDIT_REPO/.git" && ! -L "$AUDIT_REPO/.git" ]] || fail "isolated audit repository is missing or unsafe"
[[ "$(stat -c '%U:%G' "$AUDIT_REPO")" == "andris:andris" ]] || fail "isolated audit repository ownership is invalid"
[[ "$(git -C "$AUDIT_REPO" branch --show-current)" == "main" ]] || fail "isolated audit repository branch must be main"
[[ -z "$(git -C "$AUDIT_REPO" status --porcelain)" ]] || fail "isolated audit repository is not clean"
[[ "$(git -C "$AUDIT_REPO" rev-parse HEAD)" == "$EXPECTED_SHA" ]] || fail "isolated audit repository HEAD mismatch"
git -C "$AUDIT_REPO" cat-file -e "$EXPECTED_SHA^{commit}" || fail "merged commit is missing"
git -C "$AUDIT_REPO" merge-base --is-ancestor "$EXPECTED_SHA" main || fail "merged commit is not reachable from isolated main"

origin="$(git -C "$AUDIT_REPO" remote get-url origin)"
case "$origin" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail "isolated audit repository origin is not allowlisted" ;;
esac

for path in "$V01_INSTALLER" "$V02_SCRIPT"; do
  git -C "$AUDIT_REPO" cat-file -e "$EXPECTED_SHA:$path" || fail "required registered file is missing: $path"
done

# The original V01 installer is executed in a private mount namespace where
# only that process sees the isolated clean clone at the legacy primary path.
# The real primary B15M2 worktree and its files are never switched or modified.
unshare --mount --propagation private /bin/bash -c '
  set -Eeuo pipefail
  source_repo="$1"
  expected_sha="$2"
  primary_repo="$3"
  mount --bind "$source_repo" "$primary_repo"
  /bin/bash "$primary_repo/tools/runner/install-lidl-semantic-corpus-audit-dispatcher.sh" "$expected_sha"
' audit-install "$AUDIT_REPO" "$EXPECTED_SHA" "$PRIMARY_REPO"

[[ -x "$DISPATCHER" && ! -L "$DISPATCHER" ]] || fail "V01 dispatcher installation did not complete"
[[ "$(stat -c '%U:%G' "$DISPATCHER")" == "root:root" ]] || fail "dispatcher ownership is invalid"

install_tmp="$(mktemp /tmp/lidl-semantic-corpus-v02.XXXXXX)"
conf_tmp=""
cleanup() {
  rm -f -- "$install_tmp"
  [[ -z "$conf_tmp" ]] || rm -f -- "$conf_tmp"
}
trap cleanup EXIT

git -C "$AUDIT_REPO" show "$EXPECTED_SHA:$V02_SCRIPT" > "$install_tmp"
[[ -s "$install_tmp" ]] || fail "registered V02 audit script is empty"
head -n 1 "$install_tmp" | grep -Fxq '#!/usr/bin/env bash' || fail "registered V02 audit header is invalid"
install -o root -g root -m 0755 "$install_tmp" "$INSTALLED_SCRIPT"
script_sha="$(sha256sum "$INSTALLED_SCRIPT" | awk '{print $1}')"
[[ "$script_sha" =~ ^[0-9a-f]{64}$ ]] || fail "installed V02 audit SHA is invalid"

conf_tmp="$(mktemp /etc/hermes-deals-audits.d/.lidl-semantic-corpus.conf.XXXXXX)"
cat > "$conf_tmp" <<EOF
audit_name='lidl-semantic-corpus'
commit_sha='$EXPECTED_SHA'
script_sha256='$script_sha'
script_path='$INSTALLED_SCRIPT'
EOF
chown root:root "$conf_tmp"
chmod 0644 "$conf_tmp"
mv -f -- "$conf_tmp" "$CONF"
conf_tmp=""

[[ "$(stat -c '%U:%G' "$INSTALLED_SCRIPT")" == "root:root" ]] || fail "installed audit ownership is invalid"
[[ "$(stat -c '%a' "$INSTALLED_SCRIPT")" == "755" ]] || fail "installed audit permissions are invalid"
[[ "$(sha256sum "$INSTALLED_SCRIPT" | awk '{print $1}')" == "$script_sha" ]] || fail "installed audit content drift"
systemctl is-active --quiet "$RUNNER_SERVICE" || fail "GitHub Actions runner service is not active"
visudo -cf /etc/sudoers.d/hermes-deals-lidl-semantic-corpus-audit >/dev/null
sudo -l -U github-runner | grep -Fq "$DISPATCHER" || fail "github-runner dispatcher sudo rule is missing"
runner_has_docker="$(id -nG github-runner | tr ' ' '\n' | grep -Fxq docker && echo true || echo false)"
[[ "$runner_has_docker" == false ]] || fail "github-runner must not belong to docker group"

printf 'INSTALL_RESULT=PASS\nAUDIT=lidl-semantic-corpus\nAUDIT_VERSION=lidl-semantic-corpus-audit-v02-isolated-source\nREGISTERED_COMMIT=%s\nISOLATED_SOURCE_REPO=%s\nPRIMARY_WORKTREE_MODIFIED=false\nSCRIPT_SHA256=%s\nDISPATCHER_SHA256=%s\nSUDOERS_VALID=true\nRUNNER_HAS_DOCKER_GROUP=false\nPRODUCTION_APPLY_AUTHORIZED=false\n' \
  "$EXPECTED_SHA" "$AUDIT_REPO" "$script_sha" "$(sha256sum "$DISPATCHER" | awk '{print $1}')"
