#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'dispatcher must run as root through sudo'
[[ $# -eq 3 ]] || fail 'usage: dispatcher <registered-sha> <as-of> <artifact-dir>'
REGISTERED_SHA="$1"
AS_OF="$2"
EXPORT_DIR="$3"

CONF='/etc/hermes-deals-audits.d/lidl-source-refresh.conf'
TOOL='/usr/local/libexec/hermes-deals-audits/lidl-source-refresh-audit.py'
CORPUS_ROOT='/home/andris/hermes-deals-lidl-corpus'
FAMILY="$CORPUS_ROOT/flyers/aktionsprospekt-03-08-2026-08-08-2026-b1cf3b--src-6da2135ea984"
PRIMARY='/home/andris/hermes-deals'
V08_SCRIPT="$PRIMARY/tools/run-hermes-deals-b15m2-least-privilege-shadow-migration-api-regression-v08.sh"
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'

[[ "$REGISTERED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'registered SHA is invalid'
[[ "$AS_OF" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || fail 'as-of is not canonical YYYY-MM-DD'
[[ -f "$CONF" && ! -L "$CONF" ]] || fail 'source-refresh registration is missing'
[[ "$(stat -c '%U:%G:%a' "$CONF")" == root:root:644 ]] || fail 'registration metadata mismatch'
# shellcheck disable=SC1090
source "$CONF"
[[ "${audit_name:-}" == lidl-source-refresh ]] || fail 'registration name mismatch'
[[ "${commit_sha:-}" == "$REGISTERED_SHA" ]] || fail 'requested SHA is not registered'
[[ "${tool_path:-}" == "$TOOL" ]] || fail 'registered tool path mismatch'
[[ "${tool_sha256:-}" =~ ^[0-9a-f]{64}$ ]] || fail 'registered tool SHA is invalid'
[[ "${dispatcher_sha256:-}" =~ ^[0-9a-f]{64}$ ]] || fail 'registered dispatcher SHA is invalid'
[[ -f "$TOOL" && ! -L "$TOOL" ]] || fail 'registered tool is missing or unsafe'
[[ "$(stat -c '%U:%G:%a' "$TOOL")" == root:root:755 ]] || fail 'registered tool metadata mismatch'
[[ "$(sha256sum "$TOOL" | awk '{print $1}')" == "$tool_sha256" ]] || fail 'registered tool content drift'
[[ "$(sha256sum /usr/local/sbin/hermes-deals-lidl-source-refresh-audit-dispatch | awk '{print $1}')" == "$dispatcher_sha256" ]] || fail 'dispatcher content drift'

for root in "$CORPUS_ROOT" "$CORPUS_ROOT/flyers" "$FAMILY" "$PRIMARY"; do
  [[ "$(readlink -f -- "$root")" == "$root" ]] || fail "protected root path drift: $root"
  [[ -d "$root" && ! -L "$root" ]] || fail "protected root is missing or unsafe: $root"
done
[[ "$(stat -c '%U:%G' "$CORPUS_ROOT")" == andris:andris ]] || fail 'corpus ownership mismatch'
[[ "$(stat -c '%U:%G:%a' "$FAMILY")" == andris:andris:700 ]] || fail 'rev05 family metadata mismatch'

EXPORT_DIR="$(readlink -f -- "$EXPORT_DIR")"
[[ -d "$EXPORT_DIR" && ! -L "$EXPORT_DIR" ]] || fail 'artifact directory is missing or unsafe'
[[ "$EXPORT_DIR" == /home/github-runner/_work/_temp/hermes-deals-lidl-source-refresh-* ]] || fail 'artifact directory is outside runner temp allowlist'
[[ "$(stat -c '%U:%G:%a' "$EXPORT_DIR")" == github-runner:github-runner:700 ]] || fail 'artifact directory metadata mismatch'
ARTIFACT_KEY="$(basename -- "$EXPORT_DIR")"
[[ "$ARTIFACT_KEY" =~ ^hermes-deals-lidl-source-refresh-[0-9]+-[0-9]+$ ]] || fail 'artifact directory name is invalid'

install -d -o andris -g andris -m 0700 "$STAGING_ROOT"
STAGING="$STAGING_ROOT/$ARTIFACT_KEY"
[[ ! -e "$STAGING" ]] || fail 'private staging path already exists'
install -d -o andris -g andris -m 0700 "$STAGING"
cleanup() { rm -rf -- "$STAGING"; }
trap cleanup EXIT

run_owner() {
  runuser -u andris -- env HOME=/home/andris PATH=/usr/local/bin:/usr/bin:/bin "$@"
}

git_read() {
  runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 git -C "$PRIMARY" "$@"
}

file_state() {
  local path="$1"
  if [[ ! -e "$path" ]]; then printf 'missing\n'; return; fi
  [[ -f "$path" && ! -L "$path" ]] || fail "unsafe protected file: $path"
  printf '%s:%s\n' "$(stat -c '%U:%G:%a:%s' "$path")" "$(sha256sum "$path" | awk '{print $1}')"
}

corpus_digest() {
  run_owner python3 - "$CORPUS_ROOT" <<'PY'
from hashlib import sha256
from pathlib import Path
import json, stat, sys
root = Path(sys.argv[1])
rows = []
for path in sorted(root.rglob('*')):
    meta = path.lstat()
    rel = str(path.relative_to(root))
    if stat.S_ISLNK(meta.st_mode):
        raise SystemExit(f'symlink in corpus: {rel}')
    if stat.S_ISDIR(meta.st_mode):
        rows.append([rel, 'd', stat.S_IMODE(meta.st_mode), meta.st_uid, meta.st_gid])
    elif stat.S_ISREG(meta.st_mode):
        digest = sha256()
        with path.open('rb') as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b''):
                digest.update(chunk)
        rows.append([rel, 'f', stat.S_IMODE(meta.st_mode), meta.st_uid, meta.st_gid, meta.st_size, digest.hexdigest()])
    else:
        raise SystemExit(f'unsupported corpus entry: {rel}')
print(sha256(json.dumps(rows, separators=(',', ':'), ensure_ascii=True).encode()).hexdigest())
PY
}

PRIMARY_BRANCH_BEFORE="$(git_read branch --show-current)"
PRIMARY_HEAD_BEFORE="$(git_read rev-parse HEAD)"
PRIMARY_STATUS_BEFORE="$(git_read status --porcelain=v1 --untracked-files=all)"
PRIMARY_INDEX_PATH="$(git_read rev-parse --path-format=absolute --git-path index)"
[[ -f "$PRIMARY_INDEX_PATH" && ! -L "$PRIMARY_INDEX_PATH" ]] || fail 'primary Git index is missing or unsafe'
[[ ! -e "${PRIMARY_INDEX_PATH}.lock" ]] || fail 'primary Git index lock exists'
PRIMARY_INDEX_BEFORE="$(file_state "$PRIMARY_INDEX_PATH")"
PRIMARY_V08_BEFORE="$(file_state "$V08_SCRIPT")"
CORPUS_BEFORE="$(corpus_digest)"
[[ "$CORPUS_BEFORE" =~ ^[0-9a-f]{64}$ ]] || fail 'corpus baseline digest is invalid'

AUDIT_OUT="$STAGING/audit"
install -d -o andris -g andris -m 0700 "$AUDIT_OUT"
set +e
run_owner python3 "$TOOL" \
  --frozen-family "$FAMILY" \
  --as-of "$AS_OF" \
  --output-dir "$AUDIT_OUT" \
  >"$STAGING/audit.stdout" 2>"$STAGING/audit.stderr"
AUDIT_RC=$?
set -e
[[ "$AUDIT_RC" -eq 0 ]] || {
  printf 'SOURCE_REFRESH_AUDIT_RC=%s\n' "$AUDIT_RC" >&2
  if [[ -s "$STAGING/audit.stderr" ]]; then
    head -c 1000 "$STAGING/audit.stderr" >&2
    printf '\n' >&2
  fi
  fail 'source-refresh audit failed closed'
}

EXPECTED_FILES=$'audit-manifest.json\nsource-refresh-summary.json\nsource-review-template.json'
ACTUAL_FILES="$(find "$AUDIT_OUT" -mindepth 1 -maxdepth 1 -type f -printf '%f\n' | sort)"
[[ "$ACTUAL_FILES" == "$EXPECTED_FILES" ]] || fail 'sanitized audit file set mismatch'
[[ -z "$(find "$AUDIT_OUT" -mindepth 1 -maxdepth 1 ! -type f -print -quit)" ]] || fail 'unexpected non-file audit output'

run_owner python3 - "$AUDIT_OUT" "$AS_OF" <<'PY'
import json, re, sys
from pathlib import Path
root = Path(sys.argv[1])
as_of = sys.argv[2]
summary = json.loads((root / 'source-refresh-summary.json').read_text())
manifest = json.loads((root / 'audit-manifest.json').read_text())
template = json.loads((root / 'source-review-template.json').read_text())
if summary.get('result') not in {'SOURCE_REFRESH_REVIEW_REQUIRED', 'NO_SEMANTIC_REFRESH'}:
    raise SystemExit('unexpected source-refresh result')
if summary.get('as_of') != as_of:
    raise SystemExit('as-of mismatch')
if summary.get('pdf_sha256') != '6da2135ea984d1f79bdb311dfa0d8affd1d2f8d46c63a1bba25b202a30a5fb16':
    raise SystemExit('PDF identity mismatch')
if summary.get('stable_source_identity_sha256') != '7486e32f837869b3dedc36b5a129c034129f653bf698df4ad55649510623ff17':
    raise SystemExit('stable identity mismatch')
for side in ('reference_input', 'live_input'):
    block = summary.get(side) or {}
    for key in ('raw_sha256', 'parser_input_identity_sha256', 'product_binding_sha256'):
        if not re.fullmatch(r'[0-9a-f]{64}', str(block.get(key) or '')):
            raise SystemExit(f'invalid {side}.{key}')
    for key in ('product_binding_count', 'product_link_count'):
        if isinstance(block.get(key), bool) or not isinstance(block.get(key), int) or block[key] < 0:
            raise SystemExit(f'invalid {side}.{key}')
changes = summary.get('observed_changes')
if not isinstance(changes, dict) or set(changes) != {'binding_added', 'binding_removed', 'binding_title_changed'}:
    raise SystemExit('binding change summary mismatch')
if any(isinstance(value, bool) or not isinstance(value, int) or value < 0 for value in changes.values()):
    raise SystemExit('binding change value invalid')
expected_safety = {
    'raw_source_exported': False,
    'corpus_write': False,
    'parser_scan': False,
    'database_write': False,
    'review_write': False,
    'production_publish': False,
    'production_deploy': False,
    'systemd_change': False,
    'automatic_retry': False,
    'gate_c_d_authorized': False,
}
if summary.get('safety') != expected_safety:
    raise SystemExit('summary safety mismatch')
if manifest.get('sanitization_passed') is not True or manifest.get('raw_source_exported') is not False:
    raise SystemExit('manifest sanitization mismatch')
if manifest.get('safety') != expected_safety:
    raise SystemExit('manifest safety mismatch')
if template.get('decision') != 'PENDING_OWNER_REVIEW':
    raise SystemExit('review template must remain pending')
if template.get('scope') != 'authoritative_staging_scan_only':
    raise SystemExit('review template scope mismatch')
if template.get('permissions') != {
    'staging_scan': True,
    'corpus_write': False,
    'db_write': False,
    'review_seed': False,
    'auto_approve': False,
    'auto_publish': False,
    'systemd_change': False,
}:
    raise SystemExit('review template permission mismatch')
PY

CORPUS_AFTER="$(corpus_digest)"
[[ "$CORPUS_AFTER" == "$CORPUS_BEFORE" ]] || fail 'authoritative Lidl corpus changed during read-only audit'
[[ "$(git_read branch --show-current)" == "$PRIMARY_BRANCH_BEFORE" ]] || fail 'primary branch changed'
[[ "$(git_read rev-parse HEAD)" == "$PRIMARY_HEAD_BEFORE" ]] || fail 'primary HEAD changed'
[[ "$(git_read status --porcelain=v1 --untracked-files=all)" == "$PRIMARY_STATUS_BEFORE" ]] || fail 'primary status changed'
[[ "$(file_state "$PRIMARY_INDEX_PATH")" == "$PRIMARY_INDEX_BEFORE" ]] || fail 'primary Git index changed'
[[ ! -e "${PRIMARY_INDEX_PATH}.lock" ]] || fail 'primary Git index lock appeared'
[[ "$(file_state "$V08_SCRIPT")" == "$PRIMARY_V08_BEFORE" ]] || fail 'protected B15M2 V08 state changed'

DEST="$EXPORT_DIR/audit-evidence"
install -d -o github-runner -g github-runner -m 0700 "$DEST"
for name in audit-manifest.json source-refresh-summary.json source-review-template.json; do
  install -o github-runner -g github-runner -m 0600 "$AUDIT_OUT/$name" "$DEST/$name"
done

RESULT="$(run_owner python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["result"])' "$AUDIT_OUT/source-refresh-summary.json")"
printf 'AUDIT=lidl-source-refresh\nREGISTERED_COMMIT=%s\nAS_OF=%s\nRESULT=%s\n' "$REGISTERED_SHA" "$AS_OF" "$RESULT"
printf 'CORPUS_WRITE=false\nPARSER_SCAN=false\nPRODUCTION_DATABASE_WRITE=false\nREVIEW_WRITE=false\nPRODUCTION_PUBLISH=false\nPRODUCTION_DEPLOY=false\nSYSTEMD_CHANGE=false\nAUTOMATIC_RETRY=false\nGATE_C_D_AUTHORIZED=false\n'
printf 'CORPUS_UNCHANGED=true\nPRIMARY_WORKTREE_UNCHANGED=true\nPRIMARY_GIT_INDEX_UNCHANGED=true\nPRIMARY_V08_UNCHANGED=true\n'
