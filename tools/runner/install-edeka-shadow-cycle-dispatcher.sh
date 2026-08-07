#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "run with sudo"
[[ $# -eq 1 ]] || fail "usage: sudo bash tools/runner/install-edeka-shadow-cycle-dispatcher.sh <merged-commit-sha>"
EXPECTED_SHA="$1"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid merged commit SHA"

AUDIT_REPO='/home/andris/hermes-deals-audit-source-edeka'
RUNNER_SCRIPT='tools/run-hermes-deals-edeka-shadow-cycle-v01.sh'
DISPATCHER_SCRIPT='tools/runner/edeka-shadow-cycle-dispatcher.sh'
RUNNER_SERVICE='actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service'
INSTALLED_SCRIPT='/usr/local/libexec/hermes-deals-audits/edeka-shadow-cycle.sh'
DISPATCHER='/usr/local/sbin/hermes-deals-edeka-shadow-cycle-dispatch'
CONF='/etc/hermes-deals-audits.d/edeka-shadow-cycle.conf'
SUDOERS='/etc/sudoers.d/hermes-deals-edeka-shadow-cycle'
for user in andris github-runner; do id "$user" >/dev/null 2>&1 || fail "required user is missing: $user"; done
for command in awk bash git grep head id install mktemp readlink rm sha256sum stat sudo systemctl visudo; do command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"; done

AUDIT_REPO="$(readlink -f -- "$AUDIT_REPO")"
[[ "$AUDIT_REPO" == '/home/andris/hermes-deals-audit-source-edeka' ]] || fail "isolated repository path drift"
[[ -d "$AUDIT_REPO/.git" && ! -L "$AUDIT_REPO/.git" ]] || fail "isolated repository is missing or unsafe"
[[ "$(stat -c '%U:%G' "$AUDIT_REPO")" == 'andris:andris' ]] || fail "isolated repository ownership is invalid"
GIT_INDEX="$AUDIT_REPO/.git/index"
[[ -f "$GIT_INDEX" && ! -L "$GIT_INDEX" ]] || fail "isolated repository index is missing or unsafe"
[[ "$(stat -c '%U:%G' "$GIT_INDEX")" == 'andris:andris' ]] || fail "isolated repository index ownership is invalid"
[[ ! -e "$AUDIT_REPO/.git/index.lock" ]] || fail "isolated repository has a stale index lock"
index_sha_before="$(sha256sum "$GIT_INDEX" | awk '{print $1}')"
index_stat_before="$(stat -c '%U:%G:%a:%s:%Y' "$GIT_INDEX")"
git_read() { GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" "$@"; }
branch="$(git_read branch --show-current)" || fail "cannot read isolated repository branch"
status="$(git_read status --porcelain)" || fail "cannot read isolated repository status"
head_sha="$(git_read rev-parse HEAD)" || fail "cannot read isolated repository HEAD"
[[ "$branch" == main && -z "$status" && "$head_sha" == "$EXPECTED_SHA" ]] || fail "isolated repository is not exact clean main at registered SHA"
git_read merge-base --is-ancestor "$EXPECTED_SHA" main || fail "registered SHA is not reachable from isolated main"
origin="$(git_read remote get-url origin)" || fail "cannot read isolated repository origin"
case "$origin" in https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;; *) fail "origin is not allowlisted";; esac
for path in "$RUNNER_SCRIPT" "$DISPATCHER_SCRIPT"; do git_read cat-file -e "$EXPECTED_SHA:$path" || fail "registered file is missing: $path"; done

tmp="$(mktemp -d /tmp/hermes-deals-edeka-shadow-install.XXXXXX)"
cleanup() { rm -rf -- "$tmp"; }
trap cleanup EXIT
git_read show "$EXPECTED_SHA:$RUNNER_SCRIPT" > "$tmp/runner.sh"
git_read show "$EXPECTED_SHA:$DISPATCHER_SCRIPT" > "$tmp/dispatcher.sh"
for file in runner.sh dispatcher.sh; do [[ -s "$tmp/$file" ]] || fail "registered $file is empty"; head -n 1 "$tmp/$file" | grep -Fxq '#!/usr/bin/env bash' || fail "$file header is invalid"; bash -n "$tmp/$file"; done
cat > "$tmp/sudoers" <<'SUDOERS'
Defaults!/usr/local/sbin/hermes-deals-edeka-shadow-cycle-dispatch env_reset,secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-edeka-shadow-cycle-dispatch
SUDOERS
chmod 0440 "$tmp/sudoers"
visudo -cf "$tmp/sudoers" >/dev/null

install -d -o root -g root -m 0755 /usr/local/libexec/hermes-deals-audits /etc/hermes-deals-audits.d
install -d -o andris -g andris -m 0700 /home/andris/hermes-deals-runner-evidence
install -o root -g root -m 0755 "$tmp/runner.sh" "$INSTALLED_SCRIPT"
install -o root -g root -m 0755 "$tmp/dispatcher.sh" "$DISPATCHER"
install -o root -g root -m 0440 "$tmp/sudoers" "$SUDOERS"
script_sha="$(sha256sum "$INSTALLED_SCRIPT" | awk '{print $1}')"
conf_tmp="$(mktemp /etc/hermes-deals-audits.d/.edeka-shadow-cycle.conf.XXXXXX)"
cat > "$conf_tmp" <<CONF
audit_name='edeka-shadow-cycle'
commit_sha='$EXPECTED_SHA'
script_sha256='$script_sha'
script_path='$INSTALLED_SCRIPT'
CONF
chown root:root "$conf_tmp"; chmod 0644 "$conf_tmp"; mv -f -- "$conf_tmp" "$CONF"

[[ "$(sha256sum "$GIT_INDEX" | awk '{print $1}')" == "$index_sha_before" ]] || fail "isolated Git index content changed during installation"
[[ "$(stat -c '%U:%G:%a:%s:%Y' "$GIT_INDEX")" == "$index_stat_before" ]] || fail "isolated Git index metadata changed during installation"
[[ ! -e "$AUDIT_REPO/.git/index.lock" ]] || fail "installer left an index lock"
visudo -cf "$SUDOERS" >/dev/null
systemctl is-active --quiet "$RUNNER_SERVICE" || fail "GitHub Actions runner service is not active"
sudo -l -U github-runner | grep -Fq "$DISPATCHER" || fail "github-runner dispatcher sudo rule is missing"
runner_has_docker="$(id -nG github-runner | tr ' ' '\n' | grep -Fxq docker && echo true || echo false)"
[[ "$runner_has_docker" == false ]] || fail "github-runner must not belong to docker group"
printf 'INSTALL_RESULT=PASS\nAUDIT=edeka-shadow-cycle\nREGISTERED_COMMIT=%s\nAUDIT_GIT_INDEX_UNCHANGED=true\nSCRIPT_SHA256=%s\nDISPATCHER_SHA256=%s\nSUDOERS_VALID=true\nRUNNER_HAS_DOCKER_GROUP=false\nPRODUCTION_DATABASE_WRITE=false\nPRODUCTION_DEPLOYMENT=false\nSCHEDULER_ACTIVATION=false\n' "$EXPECTED_SHA" "$script_sha" "$(sha256sum "$DISPATCHER" | awk '{print $1}')"
