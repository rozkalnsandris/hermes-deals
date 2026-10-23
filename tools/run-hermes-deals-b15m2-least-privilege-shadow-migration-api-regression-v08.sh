#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

fail() {
  printf 'B15M2_V08_FAIL: %s\n' "$*" >&2
  exit 1
}

[[ $# -eq 0 ]] || fail "unexpected arguments"
[[ "${HERMES_AUDIT_TRIGGER:-}" == github-actions ]] || fail "registered dispatcher required"
[[ "${HERMES_AUDIT_EXPECTED_BRANCH:-}" == main ]] || fail "registered main branch required"
SHA="${HERMES_AUDIT_EXPECTED_HEAD:-}"
[[ "$SHA" =~ ^[0-9a-f]{40}$ ]] || fail "missing or invalid registered commit"

REPO=/home/andris/hermes-deals
ENGINE=tools/b15m2_v08_shadow.py
[[ -d "$REPO/.git" && ! -L "$REPO/.git" ]] || fail "unsafe source checkout"
[[ "$(/usr/bin/git -C "$REPO" cat-file -t "$SHA:$ENGINE")" == blob ]] ||
  fail "exact registered engine Git blob is unavailable"

# The root-owned installed Bash wrapper is verified against its registered
# sha256 by the existing dispatcher. The engine is read from the exact
# registered Git commit, not the mutable worktree on RPi5. Python performs
# a clean-main check before Docker, PostgreSQL, or evidence mutation.
GIT_OPTIONAL_LOCKS=0 /usr/bin/git -C "$REPO" cat-file blob "$SHA:$ENGINE" |
  /usr/bin/python3 -
