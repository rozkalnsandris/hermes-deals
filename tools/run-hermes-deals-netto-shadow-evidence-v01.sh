#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH
export PYTHONDONTWRITEBYTECODE=1

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ ${EUID:-$(id -u)} -ne 0 ]] || fail "audit must run as the unprivileged andris user"
[[ "${HERMES_AUDIT_TRIGGER:-}" == "github-actions" ]] || fail "unexpected audit trigger"
[[ "${HERMES_AUDIT_EXPECTED_BRANCH:-}" == "main" ]] || fail "expected branch must be main"
[[ "${HERMES_AUDIT_EXPECTED_HEAD:-}" =~ ^[0-9a-f]{40}$ ]] || fail "expected HEAD is invalid"
[[ -n "${HERMES_AUDIT_EXPORT_DIR:-}" ]] || fail "audit export directory is required"

REPO='/home/andris/hermes-deals'
EXPORT_DIR="$(readlink -f -- "$HERMES_AUDIT_EXPORT_DIR")"
[[ -d "$EXPORT_DIR" && ! -L "$EXPORT_DIR" ]] || fail "audit export directory is missing or unsafe"
[[ "$EXPORT_DIR" == /home/andris/hermes-deals-runner-evidence/hermes-deals-netto-shadow-* ]] || fail "audit export directory is outside the dedicated staging root"
[[ "$(stat -c '%U:%G' "$EXPORT_DIR")" == 'andris:andris' ]] || fail "audit export directory ownership is invalid"
[[ "$(stat -c '%a' "$EXPORT_DIR")" == '700' ]] || fail "audit export directory permissions must be 0700"

[[ -d "$REPO/.git" ]] || fail "Hermes Deals repository is unavailable"
[[ "$(git -C "$REPO" branch --show-current)" == 'main' ]] || fail "repository branch is not main"
[[ "$(git -C "$REPO" rev-parse HEAD)" == "$HERMES_AUDIT_EXPECTED_HEAD" ]] || fail "repository HEAD mismatch"
[[ -z "$(git -C "$REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail "repository worktree is not clean"

AUDIT_TOOL="${HERMES_NETTO_AUDIT_TOOL:-}"
[[ "$AUDIT_TOOL" == '/usr/local/libexec/hermes-deals-audits/netto-shadow-v1.py' ]] || fail "installed audit tool path is invalid"
[[ -f "$AUDIT_TOOL" && ! -L "$AUDIT_TOOL" ]] || fail "installed audit tool is missing or unsafe"
[[ "$(stat -c '%U:%G' "$AUDIT_TOOL")" == 'root:root' ]] || fail "installed audit tool ownership is invalid"

exec /usr/bin/python3 "$AUDIT_TOOL" \
  --repo "$REPO" \
  --expected-head "$HERMES_AUDIT_EXPECTED_HEAD" \
  --audit-root /home/andris/hermes-deals-audits \
  --raw-root /home/andris/hermes-deals/data/raw \
  --state-root /var/lib/hermes-deals/netto-weekly-shadow \
  --output "$EXPORT_DIR"
