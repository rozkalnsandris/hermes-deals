#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'dispatcher must run as root through sudo'
[[ $# -eq 5 ]] || fail 'usage: dispatcher <sha> <target> <as-of> <use-previous> <artifact-dir>'
EXPECTED_SHA="$1"
TARGET="$2"
AS_OF="$3"
USE_PREVIOUS="$4"
EXPORT_DIR="$5"
CONF='/etc/hermes-deals-audits.d/lidl-weekly-gate-a.conf'
EVIDENCE_ROOT='/home/andris/hermes-deals-lidl-gate-a-evidence'
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'invalid registered commit SHA'
[[ "$TARGET" == current || "$TARGET" == next ]] || fail 'target must be current or next'
[[ "$AS_OF" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || fail 'as-of must be YYYY-MM-DD'
[[ "$USE_PREVIOUS" == true || "$USE_PREVIOUS" == false ]] || fail 'use-previous must be true or false'
[[ -f "$CONF" && ! -L "$CONF" ]] || fail 'Gate A registration is missing'
[[ "$(stat -c '%U:%G:%a' "$CONF")" == root:root:644 ]] || fail 'Gate A registration metadata mismatch'
# shellcheck disable=SC1090
source "$CONF"
[[ "${audit_name:-}" == lidl-weekly-gate-a ]] || fail 'registration name mismatch'
[[ "${commit_sha:-}" == "$EXPECTED_SHA" ]] || fail 'requested SHA is not registered'
[[ "${script_path:-}" == /usr/local/libexec/hermes-deals-audits/lidl-weekly-gate-a.sh ]] || fail 'registered script path mismatch'
[[ "${script_sha256:-}" =~ ^[0-9a-f]{64}$ ]] || fail 'registered script SHA is invalid'
[[ "${image_id:-}" =~ ^sha256:[0-9a-f]{64}$ ]] || fail 'registered image ID is invalid'
[[ -f "$script_path" && ! -L "$script_path" ]] || fail 'registered script is missing or unsafe'
[[ "$(stat -c '%U:%G:%a' "$script_path")" == root:root:755 ]] || fail 'registered script metadata mismatch'
[[ "$(sha256sum "$script_path" | awk '{print $1}')" == "$script_sha256" ]] || fail 'registered script content drift'
[[ "$(docker image inspect --format '{{.Id}}' "$image_id")" == "$image_id" ]] || fail 'registered image is unavailable or drifted'

EXPORT_DIR="$(readlink -f -- "$EXPORT_DIR")"
[[ -d "$EXPORT_DIR" && ! -L "$EXPORT_DIR" ]] || fail 'artifact directory is missing or unsafe'
[[ "$EXPORT_DIR" == /home/github-runner/_work/_temp/hermes-deals-lidl-gate-a-* ]] || fail 'artifact directory is outside runner temp allowlist'
[[ "$(stat -c '%U:%G:%a' "$EXPORT_DIR")" == github-runner:github-runner:700 ]] || fail 'artifact directory metadata mismatch'
RUN_KEY="$(basename -- "$EXPORT_DIR")"
[[ "$RUN_KEY" =~ ^hermes-deals-lidl-gate-a-[0-9]+-[0-9]+$ ]] || fail 'artifact directory name is invalid'
RUN_DIR="$EVIDENCE_ROOT/lidl-gate-a-${RUN_KEY#hermes-deals-lidl-gate-a-}"
STAGING="$STAGING_ROOT/$RUN_KEY"
install -d -o andris -g andris -m 0700 "$EVIDENCE_ROOT"
install -d -o andris -g andris -m 0700 "$STAGING_ROOT"
[[ ! -e "$RUN_DIR" && ! -e "$STAGING" ]] || fail 'Gate A run or staging directory already exists'
install -d -o andris -g andris -m 0700 "$STAGING"
cleanup() { rm -rf -- "$STAGING"; }
trap cleanup EXIT

set +e
"$script_path" "$EXPECTED_SHA" "$image_id" "$TARGET" "$AS_OF" "$USE_PREVIOUS" "$RUN_DIR" > "$STAGING/runner.log" 2>&1
RUNNER_RC=$?
set -e
printf '%s\n' "$RUNNER_RC" > "$STAGING/runner-exit-code.txt"

SUMMARY="$RUN_DIR/sanitized-summary.json"
SAFETY="$RUN_DIR/safety-result.txt"
REQUEST="$RUN_DIR/run-request.txt"
[[ -f "$SUMMARY" && ! -L "$SUMMARY" ]] || fail 'sanitized summary is missing or unsafe'
[[ -f "$SAFETY" && ! -L "$SAFETY" ]] || fail 'safety result is missing or unsafe'
[[ -f "$REQUEST" && ! -L "$REQUEST" ]] || fail 'run request is missing or unsafe'

DESTINATION="$EXPORT_DIR/audit-evidence"
python3 - "$SUMMARY" "$SAFETY" "$REQUEST" "$STAGING/runner-exit-code.txt" "$DESTINATION" "$EXPECTED_SHA" "$image_id" "$TARGET" "$AS_OF" "$USE_PREVIOUS" <<'PY'
from __future__ import annotations
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys

summary_path, safety_path, request_path, exit_path, destination = map(Path, sys.argv[1:6])
commit_sha, image_id, target, as_of, use_previous = sys.argv[6:11]
runner_rc = int(exit_path.read_text(encoding='utf-8').strip())
summary = json.loads(summary_path.read_text(encoding='utf-8'))
if not isinstance(summary, dict):
    raise SystemExit('sanitized summary must be an object')
state = summary.get('result')
if state not in {'READY', 'NO_OP', 'WAIT', 'BLOCKED'}:
    raise SystemExit('unsupported Gate A state')
if state == 'BLOCKED':
    if runner_rc != 30:
        raise SystemExit('BLOCKED runner exit mismatch')
elif runner_rc != 0:
    raise SystemExit('non-BLOCKED runner exit mismatch')
for key, expected in {
    'audit': 'lidl-weekly-gate-a',
    'registered_commit': commit_sha,
    'registered_image_id': image_id,
    'target': target,
    'as_of': as_of,
    'dry_run': True,
    'corpus_write_authorized': False,
    'database_write_authorized': False,
    'review_write_authorized': False,
    'production_publish_authorized': False,
    'production_deploy_authorized': False,
    'systemd_change_authorized': False,
    'bounded_retry_authorized': False,
}.items():
    if summary.get(key) != expected:
        raise SystemExit(f'sanitized summary mismatch: {key}')
fingerprint = summary.get('execution_fingerprint')
if state in {'READY', 'NO_OP'}:
    if not isinstance(fingerprint, str) or not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
        raise SystemExit('completed Gate A fingerprint is invalid')
else:
    if fingerprint is not None:
        raise SystemExit('non-completed Gate A fingerprint must be null')
safety = safety_path.read_text(encoding='utf-8')
for marker in (
    'PRIMARY_WORKTREE_MODIFIED=false',
    'PRIMARY_GIT_INDEX_UNCHANGED=true',
    'AUDIT_GIT_INDEX_UNCHANGED=true',
    'CORPUS_WRITE=false',
    'PRODUCTION_DATABASE_WRITE=false',
    'REVIEW_WRITE=false',
    'PRODUCTION_PUBLISH=false',
    'PRODUCTION_DEPLOY=false',
    'SYSTEMD_CHANGE=false',
    'BOUNDED_RETRY=false',
):
    if safety.count(marker) != 1:
        raise SystemExit(f'safety marker mismatch: {marker}')
request = request_path.read_text(encoding='utf-8')
for marker in (
    f'registered_commit={commit_sha}',
    f'registered_image_id={image_id}',
    f'target={target}',
    f'as_of={as_of}',
    f'use_previous={use_previous}',
    'production_database_write=false',
    'review_write=false',
    'production_publish=false',
    'production_deploy=false',
    'systemd_change=false',
):
    if request.count(marker) != 1:
        raise SystemExit(f'run request marker mismatch: {marker}')
destination.mkdir(mode=0o700, parents=False, exist_ok=False)
for source, name in (
    (summary_path, 'gate-a-summary.json'),
    (safety_path, 'safety-result.txt'),
    (request_path, 'run-request.txt'),
    (exit_path, 'runner-exit-code.txt'),
):
    target_path = destination / name
    shutil.copy2(source, target_path, follow_symlinks=False)
    os.chmod(target_path, 0o600)
manifest = {
    'schema_version': 1,
    'audit': 'lidl-weekly-gate-a',
    'commit_sha': commit_sha,
    'image_id': image_id,
    'target': target,
    'as_of': as_of,
    'use_previous': use_previous == 'true',
    'result': state,
    'runner_exit_code': runner_rc,
    'sanitization_passed': True,
    'production_apply_authorized': False,
    'files': {},
}
for path in sorted(destination.iterdir()):
    if path.name == 'dispatcher-evidence-manifest.json':
        continue
    data = path.read_bytes()
    manifest['files'][path.name] = {
        'bytes': len(data),
        'sha256': hashlib.sha256(data).hexdigest(),
    }
manifest_path = destination / 'dispatcher-evidence-manifest.json'
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + '\n', encoding='utf-8')
os.chmod(manifest_path, 0o600)
PY

chown -R github-runner:github-runner "$DESTINATION"
find "$DESTINATION" -type d -exec chmod 0700 {} +
find "$DESTINATION" -type f -exec chmod 0600 {} +
printf 'AUDIT=lidl-weekly-gate-a\nREGISTERED_COMMIT=%s\nREGISTERED_IMAGE_ID=%s\nTARGET=%s\nAS_OF=%s\nUSE_PREVIOUS=%s\nRUNNER_EXIT_CODE=%s\nPRODUCTION_DATABASE_WRITE=false\nREVIEW_WRITE=false\nPRODUCTION_PUBLISH=false\nPRODUCTION_DEPLOY=false\nSYSTEMD_CHANGE=false\n' "$EXPECTED_SHA" "$image_id" "$TARGET" "$AS_OF" "$USE_PREVIOUS" "$RUNNER_RC"
exit "$RUNNER_RC"
