#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

AUDIT_VERSION="lidl-semantic-corpus-audit-v02.2-authoritative-corpus-root"
AUDIT_REPO="/home/andris/hermes-deals-audit-source"
V01_PATH="tools/run-hermes-deals-lidl-semantic-corpus-audit-v01.sh"
EXPECTED_ORIGIN_HTTPS="https://github.com/rozkalnsandris/hermes-deals"
EXPECTED_ORIGIN_SSH="git@github.com:rozkalnsandris/hermes-deals.git"

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

git_read() {
  GIT_OPTIONAL_LOCKS=0 git -C "$AUDIT_REPO" "$@"
}

[[ "${HERMES_AUDIT_TRIGGER:-}" == "github-actions" ]] || fail "unexpected audit trigger"
[[ "${HERMES_AUDIT_EXPECTED_BRANCH:-}" == "main" ]] || fail "expected branch must be main"
[[ "${HERMES_AUDIT_EXPECTED_HEAD:-}" =~ ^[0-9a-f]{40}$ ]] || fail "expected head is invalid"
[[ -n "${HERMES_AUDIT_EXPORT_DIR:-}" ]] || fail "export directory is missing"

EXPECTED_SHA="$HERMES_AUDIT_EXPECTED_HEAD"
for command in bash git mktemp python3 readlink rm sha256sum stat; do
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

branch="$(git_read branch --show-current)" || fail "cannot read isolated audit repository branch"
[[ "$branch" == "main" ]] || fail "isolated audit repository branch is not main"
status="$(git_read status --porcelain)" || fail "cannot read isolated audit repository status"
[[ -z "$status" ]] || fail "isolated audit repository is not clean"
head_sha="$(git_read rev-parse HEAD)" || fail "cannot read isolated audit repository HEAD"
[[ "$head_sha" == "$EXPECTED_SHA" ]] || fail "isolated audit repository HEAD mismatch"
git_read cat-file -e "$EXPECTED_SHA^{commit}" || fail "registered commit is missing"
git_read merge-base --is-ancestor "$EXPECTED_SHA" main || fail "registered commit is not reachable from isolated main"

origin="$(git_read remote get-url origin)" || fail "cannot read isolated audit repository origin"
case "$origin" in
  "$EXPECTED_ORIGIN_HTTPS"|"$EXPECTED_ORIGIN_HTTPS.git"|"$EXPECTED_ORIGIN_SSH") ;;
  *) fail "isolated audit repository origin is not allowlisted" ;;
esac

work_root="$(mktemp -d /home/andris/hermes-deals-runner-evidence/.lidl-semantic-v02.XXXXXX)"
cleanup() {
  rm -rf -- "$work_root"
}
trap cleanup EXIT
source_script="$work_root/v01-source.sh"
patched_script="$work_root/v02-runtime.sh"

git_read show "$EXPECTED_SHA:$V01_PATH" > "$source_script"
[[ -s "$source_script" && ! -L "$source_script" ]] || fail "frozen V01 audit source is missing"

python3 - "$source_script" "$patched_script" "$AUDIT_REPO" "$AUDIT_VERSION" <<'PY'
import pathlib
import sys

source = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
repo = sys.argv[3]
version = sys.argv[4]
text = source.read_text(encoding="utf-8")

old_discovery = r'''find_flyer_dir() {
  local flyer_key="$1"
  local scan="$2"
  local -a matches=()
  local candidate
  while IFS= read -r candidate; do
    [[ -f "$candidate/source.pdf" ]] || continue
    [[ -f "$candidate/source.json" ]] || continue
    [[ -f "$candidate/review-profile.json" ]] || continue
    [[ -d "$candidate/scans/$scan" ]] || continue
    matches+=("$candidate")
  done < <(
    find /home/andris -xdev \
      \( -path /home/andris/.cache -o -path /home/andris/.local -o -path /home/andris/Downloads -o -path '*/.git' -o -path '*/node_modules' \) -prune -o \
      -type d -name "$flyer_key" -print 2>/dev/null
  )
  [[ ${#matches[@]} -eq 1 ]] || fail "expected exactly one complete corpus directory for $flyer_key; found ${#matches[@]}"
  printf '%s\n' "${matches[0]}"
}'''

new_discovery = r'''CORPUS_ROOT="/home/andris/hermes-deals-lidl-corpus/flyers"
CORPUS_ROOT="$(readlink -f -- "$CORPUS_ROOT")"
[[ "$CORPUS_ROOT" == "/home/andris/hermes-deals-lidl-corpus/flyers" ]] || fail "authoritative corpus root path drift"
[[ -d "$CORPUS_ROOT" && ! -L "$CORPUS_ROOT" ]] || fail "authoritative corpus root is missing or unsafe"
[[ "$(stat -c '%U:%G' "$CORPUS_ROOT")" == "andris:andris" ]] || fail "authoritative corpus root ownership is invalid"

find_flyer_dir() {
  local flyer_key="$1"
  local scan="$2"
  local candidate="$CORPUS_ROOT/$flyer_key"
  local scan_dir="$candidate/scans/$scan"
  local resolved
  local required

  [[ "$flyer_key" != */* && "$flyer_key" != "." && "$flyer_key" != ".." ]] || fail "invalid frozen flyer key"
  [[ "$scan" != */* && "$scan" != "." && "$scan" != ".." ]] || fail "invalid frozen scan key"
  [[ -d "$candidate" && ! -L "$candidate" ]] || fail "authoritative corpus directory is missing or unsafe for $flyer_key"
  resolved="$(readlink -f -- "$candidate")"
  [[ "$resolved" == "$candidate" ]] || fail "authoritative corpus directory path drift for $flyer_key"
  [[ "$(stat -c '%U:%G' "$candidate")" == "andris:andris" ]] || fail "authoritative corpus directory ownership is invalid for $flyer_key"

  for required in source.pdf source.json review-profile.json; do
    [[ -f "$candidate/$required" && ! -L "$candidate/$required" ]] || fail "authoritative corpus file is missing or unsafe for $flyer_key: $required"
  done
  [[ -d "$scan_dir" && ! -L "$scan_dir" ]] || fail "authoritative corpus scan is missing or unsafe for $flyer_key/$scan"
  [[ "$(readlink -f -- "$scan_dir")" == "$scan_dir" ]] || fail "authoritative corpus scan path drift for $flyer_key/$scan"

  printf '%s\n' "$candidate"
}'''

replacements = {
    'AUDIT_VERSION="lidl-semantic-corpus-audit-v01"': f'AUDIT_VERSION="{version}"',
    'REPO="/home/andris/hermes-deals"': f'REPO="{repo}"',
    '/home/andris/hermes-deals-runner-evidence/hermes-deals-audit-*': (
        '/home/andris/hermes-deals-runner-evidence/'
        'hermes-deals-lidl-semantic-audit-*'
    ),
    old_discovery: new_discovery,
}
for old, new in replacements.items():
    if text.count(old) != 1:
        raise SystemExit(f"expected exactly one frozen V01 marker: {old}")
    text = text.replace(old, new, 1)
destination.write_text(text, encoding="utf-8")
PY

chmod 0700 "$source_script" "$patched_script"
[[ "$(sha256sum "$source_script" | awk '{print $1}')" =~ ^[0-9a-f]{64}$ ]] || fail "frozen V01 audit SHA is invalid"

/bin/bash --noprofile --norc "$patched_script"
