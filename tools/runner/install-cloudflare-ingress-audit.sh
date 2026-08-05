#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }

AUDIT_NAME='cloudflare-ingress'
DISPATCH_TARGET='/usr/local/sbin/hermes-deals-cloudflare-ingress-audit-dispatch'
COLLECTOR_TARGET='/usr/local/libexec/hermes-deals-audits/cloudflare-ingress-audit.py'
CONF='/etc/hermes-deals-audits.d/cloudflare-ingress.conf'
SUDOERS='/etc/sudoers.d/hermes-deals-cloudflare-ingress-audit'
PRIMARY_REPO='/home/andris/hermes-deals'

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "installer must run as root"

if [[ ${1:-} == '--remove' ]]; then
  [[ $# -eq 1 ]] || fail "usage: $0 --remove"
  rm -f -- "$SUDOERS" "$CONF" "$DISPATCH_TARGET" "$COLLECTOR_TARGET"
  printf 'REMOVED=%s\n' "$AUDIT_NAME"
  exit 0
fi

[[ $# -eq 2 ]] || fail "usage: $0 <detached-source-root> <commit-sha>"
SOURCE_ROOT="$(readlink -f -- "$1")"
COMMIT_SHA="$2"
[[ "$COMMIT_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "commit SHA must be 40 lowercase hex characters"
[[ -d "$SOURCE_ROOT/.git" || -f "$SOURCE_ROOT/.git" ]] || fail "source root is not a Git worktree"
[[ "$SOURCE_ROOT" != "$PRIMARY_REPO" ]] || fail "primary production worktree is forbidden"
[[ "$(git -C "$SOURCE_ROOT" rev-parse HEAD)" == "$COMMIT_SHA" ]] || fail "source HEAD does not match requested commit"
[[ -z "$(git -C "$SOURCE_ROOT" status --porcelain=v1 --untracked-files=all)" ]] || fail "source worktree is not clean"
[[ "$(git -C "$SOURCE_ROOT" symbolic-ref -q HEAD || true)" == '' ]] || fail "source worktree must be detached"
git -C "$SOURCE_ROOT" merge-base --is-ancestor "$COMMIT_SHA" origin/main || fail "commit is not reachable from origin/main"

COLLECTOR_SOURCE="$SOURCE_ROOT/tools/cloudflare_ingress_audit.py"
DISPATCH_SOURCE="$SOURCE_ROOT/tools/runner/cloudflare-ingress-audit-dispatcher.sh"
WORKFLOW_SOURCE="$SOURCE_ROOT/.github/workflows/cloudflare-ingress-rpi5-audit.yml"
DOC_SOURCE="$SOURCE_ROOT/docs/operations/cloudflare-ingress-rpi5-audit.md"
for path in "$COLLECTOR_SOURCE" "$DISPATCH_SOURCE" "$WORKFLOW_SOURCE" "$DOC_SOURCE"; do
  [[ -f "$path" && ! -L "$path" ]] || fail "required source file is missing or unsafe: $path"
done

python3 -m py_compile "$COLLECTOR_SOURCE"
bash -n "$DISPATCH_SOURCE"

install -d -o root -g root -m 0755 /usr/local/libexec/hermes-deals-audits
install -d -o root -g root -m 0755 /etc/hermes-deals-audits.d
install -o root -g root -m 0755 "$DISPATCH_SOURCE" "$DISPATCH_TARGET"
install -o root -g root -m 0755 "$COLLECTOR_SOURCE" "$COLLECTOR_TARGET"

collector_sha256="$(sha256sum "$COLLECTOR_TARGET" | awk '{print $1}')"
dispatcher_sha256="$(sha256sum "$DISPATCH_TARGET" | awk '{print $1}')"
workflow_sha256="$(sha256sum "$WORKFLOW_SOURCE" | awk '{print $1}')"

tmp_conf="$(mktemp)"
tmp_sudoers="$(mktemp)"
cleanup() { rm -f -- "$tmp_conf" "$tmp_sudoers"; }
trap cleanup EXIT

cat > "$tmp_conf" <<EOF
audit_name='$AUDIT_NAME'
commit_sha='$COMMIT_SHA'
collector_path='$COLLECTOR_TARGET'
collector_sha256='$collector_sha256'
dispatcher_sha256='$dispatcher_sha256'
workflow_sha256='$workflow_sha256'
expected_hostname='deals.rozkalns.net'
expected_service='http://192.168.0.180:9128'
expected_health_path='/api/health'
EOF
install -o root -g root -m 0600 "$tmp_conf" "$CONF"

cat > "$tmp_sudoers" <<EOF
github-runner ALL=(root) NOPASSWD: $DISPATCH_TARGET
EOF
visudo -cf "$tmp_sudoers" >/dev/null
install -o root -g root -m 0440 "$tmp_sudoers" "$SUDOERS"
visudo -cf "$SUDOERS" >/dev/null

printf 'INSTALLED=%s\nCOMMIT_SHA=%s\nCOLLECTOR_SHA256=%s\nDISPATCHER_SHA256=%s\nWORKFLOW_SHA256=%s\n' \
  "$AUDIT_NAME" "$COMMIT_SHA" "$collector_sha256" "$dispatcher_sha256" "$workflow_sha256"
printf 'EXPECTED_HOSTNAME=deals.rozkalns.net\nEXPECTED_SERVICE=http://192.168.0.180:9128\n'
printf 'PRODUCTION_DEPLOYMENT=false\nPRODUCTION_DATABASE_READ=false\nPRODUCTION_DATABASE_WRITE=false\n'
printf 'CLOUDFLARE_CONFIGURATION_MUTATION=false\nWORKFLOW_EXECUTED=false\n'
