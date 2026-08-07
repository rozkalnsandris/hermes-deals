#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'dispatcher must run as root through sudo'
[[ $# -eq 4 ]] || fail 'usage: dispatcher <sha> <gate-a-run-id> <gate-a-attempt> <artifact-dir>'
EXPECTED_SHA="$1"
GATE_A_RUN_ID="$2"
GATE_A_ATTEMPT="$3"
EXPORT_DIR="$4"
CONF='/etc/hermes-deals-audits.d/lidl-gate-b-plan.conf'
EVIDENCE_ROOT='/home/andris/hermes-deals-lidl-gate-a-evidence'
CORPUS_ROOT='/home/andris/hermes-deals-lidl-corpus'
PRIMARY='/home/andris/hermes-deals'
V08_SCRIPT="$PRIMARY/tools/run-hermes-deals-b15m2-least-privilege-shadow-migration-api-regression-v08.sh"
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'invalid registered commit SHA'
[[ "$GATE_A_RUN_ID" =~ ^[1-9][0-9]*$ ]] || fail 'Gate A run ID must be positive'
[[ "$GATE_A_ATTEMPT" =~ ^[1-9][0-9]*$ ]] || fail 'Gate A run attempt must be positive'
[[ -f "$CONF" && ! -L "$CONF" ]] || fail 'Gate B plan registration is missing'
[[ "$(stat -c '%U:%G:%a' "$CONF")" == root:root:644 ]] || fail 'Gate B registration metadata mismatch'
# shellcheck disable=SC1090
source "$CONF"
[[ "${audit_name:-}" == lidl-gate-b-plan ]] || fail 'registration name mismatch'
[[ "${commit_sha:-}" == "$EXPECTED_SHA" ]] || fail 'requested SHA is not registered'
[[ "${planner_path:-}" == /usr/local/libexec/hermes-deals-audits/lidl-gate-b-freeze-plan.py ]] || fail 'registered planner path mismatch'
[[ "${planner_sha256:-}" =~ ^[0-9a-f]{64}$ ]] || fail 'registered planner SHA is invalid'
[[ "${planner_blob_sha:-}" == 02f85620e4c881e4ef4b518751223bfb92fd91f8 ]] || fail 'registered planner blob mismatch'
[[ "${apply_blob_sha:-}" == b8e38b52be69aa6f0cdaa5dbb3f76ccb013c772f ]] || fail 'registered apply blob mismatch'
[[ -f "$planner_path" && ! -L "$planner_path" ]] || fail 'registered planner is missing or unsafe'
[[ "$(stat -c '%U:%G:%a' "$planner_path")" == root:root:755 ]] || fail 'registered planner metadata mismatch'
[[ "$(sha256sum "$planner_path" | awk '{print $1}')" == "$planner_sha256" ]] || fail 'registered planner content drift'

for root in "$EVIDENCE_ROOT" "$CORPUS_ROOT" "$CORPUS_ROOT/flyers" "$PRIMARY"; do
  [[ "$(readlink -f -- "$root")" == "$root" ]] || fail "protected root path drift: $root"
  [[ -d "$root" && ! -L "$root" ]] || fail "protected root is missing or unsafe: $root"
done
[[ "$(stat -c '%U:%G' "$EVIDENCE_ROOT")" == andris:andris ]] || fail 'Gate A evidence ownership mismatch'
[[ "$(stat -c '%U:%G' "$CORPUS_ROOT")" == andris:andris ]] || fail 'corpus ownership mismatch'

RUN_KEY="lidl-gate-a-${GATE_A_RUN_ID}-${GATE_A_ATTEMPT}"
RUN_DIR="$EVIDENCE_ROOT/$RUN_KEY"
[[ -d "$RUN_DIR" && ! -L "$RUN_DIR" ]] || fail 'retained Gate A run is missing or unsafe'
[[ "$RUN_DIR" == "$EVIDENCE_ROOT"/lidl-gate-a-* ]] || fail 'retained Gate A run path is outside allowlist'
[[ "$(stat -c '%U:%G' "$RUN_DIR")" == andris:andris ]] || fail 'retained Gate A run ownership mismatch'

EXPORT_DIR="$(readlink -f -- "$EXPORT_DIR")"
[[ -d "$EXPORT_DIR" && ! -L "$EXPORT_DIR" ]] || fail 'artifact directory is missing or unsafe'
[[ "$EXPORT_DIR" == /home/github-runner/_work/_temp/hermes-deals-lidl-gate-b-plan-* ]] || fail 'artifact directory is outside runner temp allowlist'
[[ "$(stat -c '%U:%G:%a' "$EXPORT_DIR")" == github-runner:github-runner:700 ]] || fail 'artifact directory metadata mismatch'
ARTIFACT_KEY="$(basename -- "$EXPORT_DIR")"
[[ "$ARTIFACT_KEY" =~ ^hermes-deals-lidl-gate-b-plan-[0-9]+-[0-9]+$ ]] || fail 'artifact directory name is invalid'

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
  if [[ ! -e "$path" ]]; then
    printf 'missing\n'
    return
  fi
  [[ -f "$path" && ! -L "$path" ]] || fail "unsafe protected file: $path"
  printf '%s:%s\n' "$(stat -c '%U:%G:%a:%s:%Y' "$path")" "$(sha256sum "$path" | awk '{print $1}')"
}

PRIMARY_BRANCH_BEFORE="$(git_read branch --show-current)"
PRIMARY_HEAD_BEFORE="$(git_read rev-parse HEAD)"
PRIMARY_STATUS_BEFORE="$(git_read status --porcelain=v1 --untracked-files=all)"
PRIMARY_INDEX_PATH="$(git_read rev-parse --path-format=absolute --git-path index)"
[[ -f "$PRIMARY_INDEX_PATH" && ! -L "$PRIMARY_INDEX_PATH" ]] || fail 'primary Git index is missing or unsafe'
[[ ! -e "${PRIMARY_INDEX_PATH}.lock" ]] || fail 'primary Git index lock exists'
PRIMARY_INDEX_BEFORE="$(file_state "$PRIMARY_INDEX_PATH")"
PRIMARY_V08_BEFORE="$(file_state "$V08_SCRIPT")"

CORPUS_BEFORE="$(python3 - "$CORPUS_ROOT" <<'PY'
from hashlib import sha256
from pathlib import Path
import json
import os
import stat
import sys
root = Path(sys.argv[1])
rows = []
for path in sorted(root.rglob('*')):
    meta = path.lstat()
    if stat.S_ISLNK(meta.st_mode):
        raise SystemExit(f'symlink in corpus: {path.relative_to(root)}')
    rel = str(path.relative_to(root))
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
)"
[[ "$CORPUS_BEFORE" =~ ^[0-9a-f]{64}$ ]] || fail 'corpus preflight snapshot is invalid'

PLAN_A="$STAGING/plan-a.json"
PLAN_B="$STAGING/plan-b.json"
LOG_A="$STAGING/planner-a.log"
LOG_B="$STAGING/planner-b.log"
set +e
run_owner python3 "$planner_path" \
  --gate-a-run-dir "$RUN_DIR" \
  --evidence-root "$EVIDENCE_ROOT" \
  --corpus-root "$CORPUS_ROOT" \
  --output "$PLAN_A" >"$LOG_A" 2>&1
RC_A=$?
run_owner python3 "$planner_path" \
  --gate-a-run-dir "$RUN_DIR" \
  --evidence-root "$EVIDENCE_ROOT" \
  --corpus-root "$CORPUS_ROOT" \
  --output "$PLAN_B" >"$LOG_B" 2>&1
RC_B=$?
set -e
[[ "$RC_A" -eq "$RC_B" ]] || fail 'repeated planner exit codes differ'
[[ "$RC_A" -eq 0 || "$RC_A" -eq 30 ]] || fail "unexpected planner exit code: $RC_A"

if [[ "$RC_A" -eq 0 ]]; then
  [[ -f "$PLAN_A" && ! -L "$PLAN_A" && -f "$PLAN_B" && ! -L "$PLAN_B" ]] || fail 'planner output is missing or unsafe'
  cmp -s "$PLAN_A" "$PLAN_B" || fail 'repeated Gate B plans are not byte-identical'
else
  [[ ! -e "$PLAN_A" && ! -e "$PLAN_B" ]] || fail 'BLOCKED planner unexpectedly wrote a plan'
  cmp -s "$LOG_A" "$LOG_B" || fail 'repeated BLOCKED planner diagnostics differ'
fi

CORPUS_AFTER="$(python3 - "$CORPUS_ROOT" <<'PY'
from hashlib import sha256
from pathlib import Path
import json
import stat
import sys
root = Path(sys.argv[1])
rows = []
for path in sorted(root.rglob('*')):
    meta = path.lstat()
    if stat.S_ISLNK(meta.st_mode):
        raise SystemExit(f'symlink in corpus: {path.relative_to(root)}')
    rel = str(path.relative_to(root))
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
)"
[[ "$CORPUS_AFTER" == "$CORPUS_BEFORE" ]] || fail 'authoritative corpus changed during read-only planning'
[[ "$(git_read branch --show-current)" == "$PRIMARY_BRANCH_BEFORE" ]] || fail 'primary branch changed'
[[ "$(git_read rev-parse HEAD)" == "$PRIMARY_HEAD_BEFORE" ]] || fail 'primary HEAD changed'
[[ "$(git_read status --porcelain=v1 --untracked-files=all)" == "$PRIMARY_STATUS_BEFORE" ]] || fail 'primary worktree status changed'
[[ "$(file_state "$PRIMARY_INDEX_PATH")" == "$PRIMARY_INDEX_BEFORE" ]] || fail 'primary Git index changed'
[[ ! -e "${PRIMARY_INDEX_PATH}.lock" ]] || fail 'primary Git index lock appeared'
[[ "$(file_state "$V08_SCRIPT")" == "$PRIMARY_V08_BEFORE" ]] || fail 'protected B15M2 V08 state changed'

DESTINATION="$EXPORT_DIR/audit-evidence"
python3 - "$PLAN_A" "$DESTINATION" "$EXPECTED_SHA" "$RUN_KEY" "$RC_A" <<'PY'
from __future__ import annotations
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import sys

plan_path = Path(sys.argv[1])
destination = Path(sys.argv[2])
commit_sha, run_key = sys.argv[3:5]
runner_rc = int(sys.argv[5])
destination.mkdir(mode=0o700, parents=False, exist_ok=False)

if runner_rc == 30:
    summary = {
        'schema_version': 1,
        'audit': 'lidl-gate-b-plan',
        'commit_sha': commit_sha,
        'gate_a_run_key': run_key,
        'result': 'BLOCKED',
        'reason': 'planner_failed_closed',
        'plan_fingerprint': None,
        'destination_name': None,
        'source': None,
        'safety': {
            'plan_only': True,
            'corpus_write_authorized': False,
            'parser_scan_authorized': False,
            'database_write_authorized': False,
            'review_write_authorized': False,
            'production_publish_authorized': False,
            'production_deploy_authorized': False,
            'systemd_change_authorized': False,
            'automatic_retry_authorized': False,
            'gate_c_d_authorized': False,
        },
    }
else:
    plan = json.loads(plan_path.read_text(encoding='utf-8'))
    if plan.get('schema_version') != 1 or plan.get('plan_version') != 'lidl-gate-b-freeze-plan-v2-source-revision':
        raise SystemExit('plan schema/version mismatch')
    if plan.get('result') != 'READY_TO_FREEZE' or plan.get('reason') != 'validated_gate_a_wait_source_evidence':
        raise SystemExit('plan result/reason mismatch')
    fingerprint = str(plan.get('plan_fingerprint') or '')
    if not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
        raise SystemExit('plan fingerprint is invalid')
    gate_a = plan.get('gate_a') or {}
    source = plan.get('source') or {}
    destination_block = plan.get('destination') or {}
    if Path(str(gate_a.get('run_dir') or '')).name != run_key:
        raise SystemExit('plan Gate A run key mismatch')
    if gate_a.get('result') != 'WAIT' or gate_a.get('one_shot_result') != 'WAIT_SOURCE':
        raise SystemExit('plan Gate A state mismatch')
    for key in ('pdf_sha256', 'raw_sha256', 'stable_source_identity_sha256'):
        if not re.fullmatch(r'[0-9a-f]{64}', str(source.get(key) or '')):
            raise SystemExit(f'plan source digest invalid: {key}')
    flyer_dir = Path(str(destination_block.get('flyer_dir') or ''))
    if not flyer_dir.name or flyer_dir.parent.name != 'flyers':
        raise SystemExit('plan destination shape mismatch')
    expected_safety = {
        'plan_only': True,
        'corpus_write_authorized': False,
        'database_write_authorized': False,
        'review_write_authorized': False,
        'production_publish_authorized': False,
        'production_deploy_authorized': False,
        'systemd_change_authorized': False,
        'bounded_retry_authorized': False,
    }
    if plan.get('safety') != expected_safety:
        raise SystemExit('plan safety mismatch')
    summary = {
        'schema_version': 1,
        'audit': 'lidl-gate-b-plan',
        'commit_sha': commit_sha,
        'gate_a_run_key': run_key,
        'result': 'READY_TO_FREEZE',
        'reason': 'validated_gate_a_wait_source_evidence',
        'plan_fingerprint': fingerprint,
        'destination_name': flyer_dir.name,
        'gate_a': {
            'registered_commit': gate_a.get('registered_commit'),
            'target': gate_a.get('target'),
            'as_of': gate_a.get('as_of'),
        },
        'source': {
            'flyer_key': source.get('flyer_key'),
            'route_region': source.get('route_region'),
            'valid_from': source.get('valid_from'),
            'valid_until': source.get('valid_until'),
            'official_flyer_id': source.get('official_flyer_id'),
            'page_count': source.get('page_count'),
            'pdf_sha256': source.get('pdf_sha256'),
            'raw_sha256': source.get('raw_sha256'),
            'stable_source_identity_sha256': source.get('stable_source_identity_sha256'),
        },
        'safety': {
            'plan_only': True,
            'corpus_write_authorized': False,
            'parser_scan_authorized': False,
            'database_write_authorized': False,
            'review_write_authorized': False,
            'production_publish_authorized': False,
            'production_deploy_authorized': False,
            'systemd_change_authorized': False,
            'automatic_retry_authorized': False,
            'gate_c_d_authorized': False,
        },
    }

summary_path = destination / 'gate-b-plan-summary.json'
summary_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n', encoding='utf-8')
os.chmod(summary_path, 0o600)
exit_path = destination / 'planner-exit-code.txt'
exit_path.write_text(f'{runner_rc}\n', encoding='utf-8')
os.chmod(exit_path, 0o600)
manifest = {
    'schema_version': 1,
    'audit': 'lidl-gate-b-plan',
    'commit_sha': commit_sha,
    'gate_a_run_key': run_key,
    'result': summary['result'],
    'runner_exit_code': runner_rc,
    'sanitization_passed': True,
    'corpus_write_authorized': False,
    'parser_scan_authorized': False,
    'database_write_authorized': False,
    'review_write_authorized': False,
    'production_publish_authorized': False,
    'production_deploy_authorized': False,
    'systemd_change_authorized': False,
    'automatic_retry_authorized': False,
    'gate_c_d_authorized': False,
    'files': {},
}
for path in sorted(destination.iterdir()):
    data = path.read_bytes()
    manifest['files'][path.name] = {'bytes': len(data), 'sha256': sha256(data).hexdigest()}
manifest_path = destination / 'dispatcher-evidence-manifest.json'
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
os.chmod(manifest_path, 0o600)
PY

chown -R github-runner:github-runner "$DESTINATION"
find "$DESTINATION" -type d -exec chmod 0700 {} +
find "$DESTINATION" -type f -exec chmod 0600 {} +
printf 'AUDIT=lidl-gate-b-plan\nREGISTERED_COMMIT=%s\nGATE_A_RUN_KEY=%s\nPLANNER_EXIT_CODE=%s\nCORPUS_WRITE=false\nPARSER_SCAN=false\nPRODUCTION_DATABASE_WRITE=false\nREVIEW_WRITE=false\nPRODUCTION_PUBLISH=false\nPRODUCTION_DEPLOY=false\nSYSTEMD_CHANGE=false\nAUTOMATIC_RETRY=false\nGATE_C_D_AUTHORIZED=false\nPRIMARY_WORKTREE_UNCHANGED=true\nPRIMARY_GIT_INDEX_UNCHANGED=true\nPRIMARY_V08_UNCHANGED=true\n' \
  "$EXPECTED_SHA" "$RUN_KEY" "$RC_A"
exit "$RC_A"
