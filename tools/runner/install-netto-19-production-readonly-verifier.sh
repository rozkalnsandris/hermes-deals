#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH PYTHONDONTWRITEBYTECODE=1

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'run with sudo'
[[ $# -eq 2 ]] || fail 'usage: sudo bash tools/runner/install-netto-19-production-readonly-verifier.sh <merged-main-sha> <clean-detached-source-worktree>'

REGISTERED_SHA="$1"
SOURCE_REPO="$(readlink -f -- "$2")"
EXPECTED_SOURCE_REPO='/home/andris/hermes-deals-worktrees/netto-19-production-readonly-v1'
PRIMARY_GIT_COMMON_DIR='/home/andris/hermes-deals/.git'
INSTALLER_REL='tools/runner/install-netto-19-production-readonly-verifier.sh'
VERIFIER_REL='tools/runner/netto_19_production_readonly_verify.py'
RUNTIME_ROOT='/usr/local/libexec/hermes-deals-audits/netto-19-production-readonly-v1'
VERIFIER_DST="$RUNTIME_ROOT/netto_19_production_readonly_verify.py"
DISPATCHER_DST='/usr/local/sbin/hermes-deals-netto-19-production-readonly-verify'
REGISTRY_DIR='/etc/hermes-deals-audits.d'
CONFIG_DST="$REGISTRY_DIR/netto-19-production-readonly-v1.conf"
SUDOERS_DST='/etc/sudoers.d/hermes-deals-netto-19-production-readonly'
RUNNER_USER='github-runner'

[[ "$REGISTERED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'registered SHA is invalid'
[[ "$SOURCE_REPO" == "$EXPECTED_SOURCE_REPO" ]] || fail "source worktree must be $EXPECTED_SOURCE_REPO"
INSTALLER_SOURCE="$(readlink -f -- "${BASH_SOURCE[0]}")"
[[ "$INSTALLER_SOURCE" == "$SOURCE_REPO/$INSTALLER_REL" ]] \
  || fail 'installer must execute from the reviewed detached source worktree'

for command in git grep id install mktemp python3 readlink runuser sha256sum stat sudo tr visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
for user in andris "$RUNNER_USER"; do
  id "$user" >/dev/null 2>&1 || fail "required local user is missing: $user"
done
if id -nG "$RUNNER_USER" | tr ' ' '\n' | grep -Fxq docker; then
  fail "$RUNNER_USER must not belong to the Docker group"
fi

git_source() {
  runuser -u andris -- /usr/bin/env -i \
    HOME=/home/andris USER=andris LOGNAME=andris \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    GIT_OPTIONAL_LOCKS=0 \
    /usr/bin/git "$@"
}

[[ "$(git_source -C "$SOURCE_REPO" rev-parse --is-inside-work-tree 2>/dev/null)" == true ]] \
  || fail 'source path is not a Git worktree'
[[ "$(git_source -C "$SOURCE_REPO" rev-parse HEAD)" == "$REGISTERED_SHA" ]] \
  || fail 'source worktree HEAD mismatch'
[[ -z "$(git_source -C "$SOURCE_REPO" branch --show-current)" ]] \
  || fail 'source worktree must be detached'
[[ -z "$(git_source -C "$SOURCE_REPO" status --porcelain=v1 --untracked-files=all)" ]] \
  || fail 'source worktree is not clean'
COMMON_DIR="$(git_source -C "$SOURCE_REPO" rev-parse --git-common-dir)"
case "$COMMON_DIR" in
  /*) COMMON_DIR="$(readlink -f -- "$COMMON_DIR")" ;;
  *) COMMON_DIR="$(readlink -f -- "$SOURCE_REPO/$COMMON_DIR")" ;;
esac
[[ "$COMMON_DIR" == "$PRIMARY_GIT_COMMON_DIR" ]] \
  || fail 'source is not a worktree of /home/andris/hermes-deals'
git_source -C "$SOURCE_REPO" show-ref --verify --quiet refs/remotes/origin/main \
  || fail 'origin/main unavailable'
git_source -C "$SOURCE_REPO" merge-base --is-ancestor "$REGISTERED_SHA" refs/remotes/origin/main \
  || fail 'registered SHA is not reachable from origin/main'
for tracked in "$INSTALLER_REL" "$VERIFIER_REL"; do
  git_source -C "$SOURCE_REPO" ls-files --error-unmatch "$tracked" >/dev/null \
    || fail "required source is not tracked: $tracked"
  [[ -f "$SOURCE_REPO/$tracked" && ! -L "$SOURCE_REPO/$tracked" ]] \
    || fail "required source is missing or unsafe: $tracked"
done

INSTALLER_BLOB="$(git_source -C "$SOURCE_REPO" rev-parse "$REGISTERED_SHA:$INSTALLER_REL")"
[[ "$INSTALLER_BLOB" =~ ^[0-9a-f]{40}$ ]] || fail 'installer blob identity is invalid'
[[ "$(git_source -C "$SOURCE_REPO" hash-object "$INSTALLER_SOURCE")" == "$INSTALLER_BLOB" ]] \
  || fail 'running installer bytes differ from registered commit'
VERIFIER_BLOB="$(git_source -C "$SOURCE_REPO" rev-parse "$REGISTERED_SHA:$VERIFIER_REL")"
[[ "$VERIFIER_BLOB" =~ ^[0-9a-f]{40}$ ]] || fail 'verifier blob identity is invalid'
[[ "$(git_source -C "$SOURCE_REPO" hash-object "$SOURCE_REPO/$VERIFIER_REL")" == "$VERIFIER_BLOB" ]] \
  || fail 'running verifier bytes differ from registered commit'

install -d -o root -g root -m 0755 "$RUNTIME_ROOT" "$REGISTRY_DIR"
install -o root -g root -m 0555 "$SOURCE_REPO/$VERIFIER_REL" "$VERIFIER_DST"
VERIFIER_SHA256="$(sha256sum "$VERIFIER_DST" | awk '{print $1}')"

TMP="$(mktemp -d /tmp/hermes-netto-19-installer.XXXXXX)"
cleanup() { rm -rf -- "$TMP"; }
trap cleanup EXIT

cat >"$TMP/config" <<EOF
registered_sha='$REGISTERED_SHA'
installer_blob='$INSTALLER_BLOB'
verifier_blob='$VERIFIER_BLOB'
verifier_sha256='$VERIFIER_SHA256'
verifier_path='$VERIFIER_DST'
EOF
install -o root -g root -m 0600 "$TMP/config" "$CONFIG_DST"

cat >"$TMP/dispatcher" <<'DISPATCH'
#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH PYTHONDONTWRITEBYTECODE=1
fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'dispatcher must run as root through sudo'
[[ $# -eq 2 ]] || fail 'usage: hermes-deals-netto-19-production-readonly-verify <registered-sha> <evidence-dir>'
REQUESTED_SHA="$1"
EVIDENCE_DIR="$(readlink -f -- "$2")"
CONFIG='/etc/hermes-deals-audits.d/netto-19-production-readonly-v1.conf'
[[ "$REQUESTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'requested SHA is invalid'
[[ -f "$CONFIG" && ! -L "$CONFIG" ]] || fail 'verifier is not registered'
[[ "$(stat -c '%U:%G %a' "$CONFIG")" == 'root:root 600' ]] || fail 'verifier config metadata invalid'
# shellcheck disable=SC1090
source "$CONFIG"
[[ "$registered_sha" == "$REQUESTED_SHA" ]] || fail 'registered verifier SHA mismatch'
[[ "$installer_blob" =~ ^[0-9a-f]{40}$ ]] || fail 'registered installer identity invalid'
[[ "$verifier_blob" =~ ^[0-9a-f]{40}$ && "$verifier_sha256" =~ ^[0-9a-f]{64}$ ]] \
  || fail 'registered verifier identity invalid'
[[ -f "$verifier_path" && ! -L "$verifier_path" ]] || fail 'registered verifier file unsafe'
[[ "$(sha256sum "$verifier_path" | awk '{print $1}')" == "$verifier_sha256" ]] \
  || fail 'registered verifier content drift'
[[ -d "$EVIDENCE_DIR" && ! -L "$EVIDENCE_DIR" ]] || fail 'evidence directory unsafe'
[[ "$EVIDENCE_DIR" == /home/github-runner/_work/_temp/hermes-netto-19-production-verify-* ]] \
  || fail 'evidence directory outside runner temp allowlist'
[[ "$(stat -c '%U:%G %a' "$EVIDENCE_DIR")" == 'github-runner:github-runner 700' ]] \
  || fail 'evidence directory metadata invalid'

/usr/bin/python3 "$verifier_path" \
  --registered-sha "$REQUESTED_SHA" \
  --evidence-dir "$EVIDENCE_DIR"
DISPATCH
install -o root -g root -m 0755 "$TMP/dispatcher" "$DISPATCHER_DST"

{
  printf 'Cmnd_Alias HERMES_DEALS_NETTO_19_READONLY_VERIFY = %s [0-9a-f][0-9a-f]* /home/github-runner/_work/_temp/hermes-netto-19-production-verify-*\n' "$DISPATCHER_DST"
  printf '%s ALL=(root) %s%s: HERMES_DEALS_NETTO_19_READONLY_VERIFY\n' "$RUNNER_USER" 'NO' 'PASSWD'
} >"$TMP/sudoers"
visudo -cf "$TMP/sudoers" >/dev/null
install -o root -g root -m 0440 "$TMP/sudoers" "$SUDOERS_DST"
visudo -cf "$SUDOERS_DST" >/dev/null

printf 'NETTO_19_READONLY_REGISTRATION=PASS\n'
printf 'REGISTERED_SHA=%s\n' "$REGISTERED_SHA"
printf 'INSTALLER_BLOB=%s\n' "$INSTALLER_BLOB"
printf 'VERIFIER_BLOB=%s\n' "$VERIFIER_BLOB"
printf 'VERIFIER_SHA256=%s\n' "$VERIFIER_SHA256"
printf 'PRODUCTION_MUTATED=false\n'
printf 'DATABASE_WRITE=false\n'
printf 'REVIEW_WRITE=false\n'
printf 'PRODUCTION_DEPLOY=false\n'
