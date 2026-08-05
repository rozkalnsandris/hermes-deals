#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

RUNNER_SERVICE="actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service"
AUDIT_REPO="/home/andris/hermes-deals-audit-source"
AUDIT_NAME="aldi-a30-source-discovery"
RUNNER_SOURCE="tools/run-hermes-deals-aldi-a30-source-discovery-v04.sh"
DISPATCHER_SOURCE="tools/runner/aldi-a30-source-discovery-dispatcher.sh"
INSTALLED_SCRIPT="/usr/local/libexec/hermes-deals-audits/aldi-a30-source-discovery.sh"
INSTALLED_DISPATCHER="/usr/local/sbin/hermes-deals-aldi-a30-source-discovery-dispatch"
REGISTRY="/etc/hermes-deals-audits.d/aldi-a30-source-discovery.conf"
SUDOERS="/etc/sudoers.d/hermes-deals-aldi-a30-source-discovery"

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "run with sudo"
[[ $# -eq 1 ]] || fail "usage: sudo bash tools/runner/install-aldi-a30-source-discovery-dispatcher.sh <merged-commit-sha>"
EXPECTED_SHA="$1"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid merged commit SHA"

for user in andris github-runner; do
  id "$user" >/dev/null 2>&1 || fail "required user is missing: $user"
done
for command in bash git install readlink sha256sum stat systemctl visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

AUDIT_REPO="$(readlink -f -- "$AUDIT_REPO")"
[[ "$AUDIT_REPO" == "/home/andris/hermes-deals-audit-source" ]] || fail "audit repository path drift"
[[ -d "$AUDIT_REPO/.git" && ! -L "$AUDIT_REPO/.git" ]] || fail "audit repository is missing or unsafe"
[[ "$(stat -c '%U:%G' "$AUDIT_REPO")" == 'andris:andris' ]] || fail "audit repository ownership is invalid"
[[ -f "$AUDIT_REPO/.git/index" && ! -L "$AUDIT_REPO/.git/index" ]] || fail "audit repository index is missing or unsafe"
[[ ! -e "$AUDIT_REPO/.git/index.lock" ]] || fail "audit repository has a stale index lock"

read_git() { GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" "$@"; }
branch="$(read_git branch --show-current)"
head_sha="$(read_git rev-parse HEAD)"
status="$(read_git status --porcelain=v1 --untracked-files=all)"
[[ "$branch" == "main" ]] || fail "audit repository branch must be main"
[[ "$head_sha" == "$EXPECTED_SHA" ]] || fail "audit repository HEAD mismatch"
[[ -z "$status" ]] || fail "audit repository is not clean"
read_git cat-file -e "$EXPECTED_SHA^{commit}" || fail "merged commit is missing"
read_git merge-base --is-ancestor "$EXPECTED_SHA" main || fail "merged commit is not reachable from audit main"
origin="$(read_git remote get-url origin)"
case "$origin" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail "audit repository origin is not allowlisted" ;;
esac

for relative in "$RUNNER_SOURCE" "$DISPATCHER_SOURCE"; do
  [[ -f "$AUDIT_REPO/$relative" && ! -L "$AUDIT_REPO/$relative" ]] || fail "required source file is missing or unsafe: $relative"
done
/bin/bash -n "$AUDIT_REPO/$RUNNER_SOURCE"
/bin/bash -n "$AUDIT_REPO/$DISPATCHER_SOURCE"

index_sha_before="$(sha256sum "$AUDIT_REPO/.git/index" | awk '{print $1}')"
index_stat_before="$(stat -c '%U:%G:%a:%s:%Y' "$AUDIT_REPO/.git/index")"
install -d -o root -g root -m 0755 /usr/local/libexec/hermes-deals-audits
install -d -o root -g root -m 0755 /etc/hermes-deals-audits.d
install -o root -g root -m 0755 "$AUDIT_REPO/$RUNNER_SOURCE" "$INSTALLED_SCRIPT"
install -o root -g root -m 0755 "$AUDIT_REPO/$DISPATCHER_SOURCE" "$INSTALLED_DISPATCHER"
script_sha="$(sha256sum "$INSTALLED_SCRIPT" | awk '{print $1}')"
dispatcher_sha="$(sha256sum "$INSTALLED_DISPATCHER" | awk '{print $1}')"
[[ "$script_sha" =~ ^[0-9a-f]{64}$ ]] || fail "installed script SHA is invalid"
[[ "$dispatcher_sha" =~ ^[0-9a-f]{64}$ ]] || fail "installed dispatcher SHA is invalid"

registry_tmp="$(mktemp /tmp/aldi-a30-source-discovery-registry.XXXXXX)"
sudoers_tmp="$(mktemp /tmp/aldi-a30-source-discovery-sudoers.XXXXXX)"
cleanup() { rm -f -- "$registry_tmp" "$sudoers_tmp"; }
trap cleanup EXIT
cat > "$registry_tmp" <<EOF
audit_name='$AUDIT_NAME'
commit_sha='$EXPECTED_SHA'
script_path='$INSTALLED_SCRIPT'
script_sha256='$script_sha'
EOF
install -o root -g root -m 0600 "$registry_tmp" "$REGISTRY"
cat > "$sudoers_tmp" <<EOF
github-runner ALL=(root) NOPASSWD: $INSTALLED_DISPATCHER
EOF
visudo -cf "$sudoers_tmp" >/dev/null
install -o root -g root -m 0440 "$sudoers_tmp" "$SUDOERS"
visudo -cf "$SUDOERS" >/dev/null

[[ "$(sha256sum "$AUDIT_REPO/.git/index" | awk '{print $1}')" == "$index_sha_before" ]] || fail "audit repository index content changed"
[[ "$(stat -c '%U:%G:%a:%s:%Y' "$AUDIT_REPO/.git/index")" == "$index_stat_before" ]] || fail "audit repository index metadata changed"
[[ ! -e "$AUDIT_REPO/.git/index.lock" ]] || fail "installer left an index lock"
[[ "$(stat -c '%U:%G:%a' "$INSTALLED_SCRIPT")" == 'root:root:755' ]] || fail "installed script metadata is invalid"
[[ "$(stat -c '%U:%G:%a' "$INSTALLED_DISPATCHER")" == 'root:root:755' ]] || fail "installed dispatcher metadata is invalid"
[[ "$(stat -c '%U:%G:%a' "$REGISTRY")" == 'root:root:600' ]] || fail "registry metadata is invalid"
systemctl is-active --quiet "$RUNNER_SERVICE" || fail "GitHub Actions runner service is not active"
sudo -l -U github-runner | grep -Fq "$INSTALLED_DISPATCHER" || fail "github-runner dispatcher sudo rule is missing"
runner_has_docker="$(id -nG github-runner | tr ' ' '\n' | grep -Fxq docker && echo true || echo false)"
[[ "$runner_has_docker" == false ]] || fail "github-runner must not belong to docker group"

printf 'INSTALL_RESULT=PASS\n'
printf 'AUDIT=%s\n' "$AUDIT_NAME"
printf 'REGISTERED_COMMIT=%s\n' "$EXPECTED_SHA"
printf 'INSTALLED_SCRIPT=%s\n' "$INSTALLED_SCRIPT"
printf 'SCRIPT_SHA256=%s\n' "$script_sha"
printf 'INSTALLED_DISPATCHER=%s\n' "$INSTALLED_DISPATCHER"
printf 'DISPATCHER_SHA256=%s\n' "$dispatcher_sha"
printf 'RUNNER_HAS_DOCKER_GROUP=%s\n' "$runner_has_docker"
printf 'PRIMARY_WORKTREE_MODIFIED=false\n'
printf 'PRODUCTION_APPLY_AUTHORIZED=false\n'
