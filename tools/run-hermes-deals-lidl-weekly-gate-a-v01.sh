#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

RUNNER_VERSION='lidl-weekly-gate-a-rpi5-v01'
AUDIT_REPO='/home/andris/hermes-deals-audit-source'
PRIMARY_REPO='/home/andris/hermes-deals'
CORPUS_ROOT='/home/andris/hermes-deals-lidl-corpus'
EVIDENCE_ROOT='/home/andris/hermes-deals-lidl-gate-a-evidence'
EXPECTED_ORIGIN_HTTPS='https://github.com/rozkalnsandris/hermes-deals'
EXPECTED_ORIGIN_SSH='git@github.com:rozkalnsandris/hermes-deals.git'

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

git_read() {
  local repo="$1"
  shift
  runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 git -C "$repo" "$@"
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'runner must execute as root through the fixed dispatcher'
[[ $# -eq 6 ]] || fail 'usage: runner <sha> <image-id> <target> <as-of> <use-previous> <run-dir>'
EXPECTED_SHA="$1"
IMAGE_ID="$2"
TARGET="$3"
AS_OF="$4"
USE_PREVIOUS="$5"
RUN_DIR="$6"

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail 'invalid registered commit SHA'
[[ "$IMAGE_ID" =~ ^sha256:[0-9a-f]{64}$ ]] || fail 'invalid registered image ID'
[[ "$TARGET" == current || "$TARGET" == next ]] || fail 'target must be current or next'
[[ "$AS_OF" =~ ^[0-9]{4}-[0-9]{2}-[0-9]{2}$ ]] || fail 'as-of must be YYYY-MM-DD'
[[ "$USE_PREVIOUS" == true || "$USE_PREVIOUS" == false ]] || fail 'use-previous must be true or false'
python3 - "$AS_OF" <<'PY'
from datetime import date
import sys
value = date.fromisoformat(sys.argv[1])
if value.isoformat() != sys.argv[1]:
    raise SystemExit('non-canonical as-of date')
PY

for command in date docker find install python3 readlink runuser sha256sum sort stat; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
for repo in "$AUDIT_REPO" "$PRIMARY_REPO"; do
  [[ -d "$repo/.git" && ! -L "$repo/.git" ]] || fail "repository is missing or unsafe: $repo"
  [[ "$(stat -c '%U:%G' "$repo")" == andris:andris ]] || fail "repository ownership mismatch: $repo"
done
[[ -d "$CORPUS_ROOT/flyers" && ! -L "$CORPUS_ROOT" && ! -L "$CORPUS_ROOT/flyers" ]] || fail 'authoritative corpus root is missing or unsafe'
[[ "$(readlink -f -- "$CORPUS_ROOT")" == "$CORPUS_ROOT" ]] || fail 'corpus root path drift'

for index in "$AUDIT_REPO/.git/index" "$PRIMARY_REPO/.git/index"; do
  [[ -f "$index" && ! -L "$index" ]] || fail "repository index is missing or unsafe: $index"
  [[ "$(stat -c '%U:%G' "$index")" == andris:andris ]] || fail "repository index ownership mismatch: $index"
  [[ ! -e "$index.lock" ]] || fail "repository index lock exists: $index.lock"
done
AUDIT_INDEX_SHA_BEFORE="$(sha256sum "$AUDIT_REPO/.git/index" | awk '{print $1}')"
AUDIT_INDEX_STAT_BEFORE="$(stat -c '%U:%G:%a:%s:%Y' "$AUDIT_REPO/.git/index")"
PRIMARY_INDEX_SHA_BEFORE="$(sha256sum "$PRIMARY_REPO/.git/index" | awk '{print $1}')"
PRIMARY_INDEX_STAT_BEFORE="$(stat -c '%U:%G:%a:%s:%Y' "$PRIMARY_REPO/.git/index")"

AUDIT_BRANCH="$(git_read "$AUDIT_REPO" branch --show-current)" || fail 'cannot read audit branch'
AUDIT_HEAD="$(git_read "$AUDIT_REPO" rev-parse HEAD)" || fail 'cannot read audit HEAD'
AUDIT_STATUS="$(git_read "$AUDIT_REPO" status --porcelain=v1 --untracked-files=all)" || fail 'cannot read audit status'
[[ "$AUDIT_BRANCH" == main && "$AUDIT_HEAD" == "$EXPECTED_SHA" && -z "$AUDIT_STATUS" ]] || fail 'audit clone is not exact clean main at registered SHA'
ORIGIN="$(git_read "$AUDIT_REPO" remote get-url origin)" || fail 'cannot read audit origin'
case "$ORIGIN" in
  "$EXPECTED_ORIGIN_HTTPS"|"$EXPECTED_ORIGIN_HTTPS.git"|"$EXPECTED_ORIGIN_SSH") ;;
  *) fail 'audit origin is not allowlisted' ;;
esac
for path in \
  backend/Dockerfile \
  backend/requirements.txt \
  tools/lidl_weekly_shadow_controller.py \
  tools/lidl_weekly_one_shot.py \
  tools/lidl-weekly-completeness.py; do
  git_read "$AUDIT_REPO" cat-file -e "$EXPECTED_SHA:$path" || fail "registered file is missing: $path"
done

PRIMARY_BRANCH_BEFORE="$(git_read "$PRIMARY_REPO" branch --show-current)" || fail 'cannot read primary branch'
PRIMARY_HEAD_BEFORE="$(git_read "$PRIMARY_REPO" rev-parse HEAD)" || fail 'cannot read primary HEAD'
PRIMARY_STATUS_BEFORE="$(git_read "$PRIMARY_REPO" status --porcelain=v1 -z --untracked-files=all | sha256sum | awk '{print $1}')" || fail 'cannot read primary status'

[[ "$(docker image inspect --format '{{.Id}}' "$IMAGE_ID")" == "$IMAGE_ID" ]] || fail 'registered audit image is unavailable or drifted'
IMAGE_LABEL="$(docker image inspect --format '{{index .Config.Labels "net.rozkalns.hermes-deals.commit"}}' "$IMAGE_ID")"
[[ "$IMAGE_LABEL" == "$EXPECTED_SHA" ]] || fail 'registered audit image commit label mismatch'

RUN_DIR="$(readlink -m -- "$RUN_DIR")"
[[ "$RUN_DIR" == "$EVIDENCE_ROOT"/lidl-gate-a-* ]] || fail 'run directory is outside Gate A evidence root'
[[ ! -e "$RUN_DIR" ]] || fail 'run directory already exists'
install -d -o andris -g andris -m 0700 "$EVIDENCE_ROOT" "$RUN_DIR" "$RUN_DIR/controller"

PREVIOUS_MANIFEST=''
if [[ "$USE_PREVIOUS" == true ]]; then
  PREVIOUS_MANIFEST="$(find "$EVIDENCE_ROOT" -mindepth 3 -maxdepth 3 -type f -path '*/controller/controller-manifest.json' ! -path "$RUN_DIR/*" -printf '%T@ %p\n' | sort -nr | awk 'NR==1{sub(/^[^ ]+ /, ""); print; exit}')"
  [[ -n "$PREVIOUS_MANIFEST" ]] || fail 'use-previous requested but no prior Gate A manifest exists'
  PREVIOUS_MANIFEST="$(readlink -f -- "$PREVIOUS_MANIFEST")"
  [[ "$PREVIOUS_MANIFEST" == "$EVIDENCE_ROOT"/lidl-gate-a-*/controller/controller-manifest.json ]] || fail 'previous manifest path is outside evidence root'
  [[ -f "$PREVIOUS_MANIFEST" && ! -L "$PREVIOUS_MANIFEST" ]] || fail 'previous manifest is missing or unsafe'
fi

cat > "$RUN_DIR/run-request.txt" <<REQUEST
runner_version=$RUNNER_VERSION
registered_commit=$EXPECTED_SHA
registered_image_id=$IMAGE_ID
target=$TARGET
as_of=$AS_OF
use_previous=$USE_PREVIOUS
previous_manifest=${PREVIOUS_MANIFEST:-none}
corpus_root=$CORPUS_ROOT
production_database_write=false
review_write=false
production_publish=false
production_deploy=false
systemd_change=false
REQUEST
chown andris:andris "$RUN_DIR/run-request.txt"
chmod 0600 "$RUN_DIR/run-request.txt"

ANDRIS_UID="$(id -u andris)"
ANDRIS_GID="$(id -g andris)"
DOCKER_ARGS=(
  run --rm
  --network bridge
  --read-only
  --cap-drop ALL
  --security-opt no-new-privileges:true
  --pids-limit 256
  --memory 1536m
  --cpus 2
  --user "$ANDRIS_UID:$ANDRIS_GID"
  --env HOME=/tmp
  --env PYTHONDONTWRITEBYTECODE=1
  --tmpfs /tmp:rw,nosuid,nodev,noexec,size=128m,mode=1777
  --mount "type=bind,src=$AUDIT_REPO,dst=/repo,readonly"
  --mount "type=bind,src=$CORPUS_ROOT,dst=/corpus,readonly"
  --mount "type=bind,src=$RUN_DIR,dst=/out"
)
CONTROLLER_ARGS=(
  python /repo/tools/lidl_weekly_shadow_controller.py
  --corpus /corpus
  --output-dir /out/controller
  --target "$TARGET"
  --today "$AS_OF"
)
if [[ -n "$PREVIOUS_MANIFEST" ]]; then
  DOCKER_ARGS+=(--mount "type=bind,src=$PREVIOUS_MANIFEST,dst=/previous/controller-manifest.json,readonly")
  CONTROLLER_ARGS+=(--previous-manifest /previous/controller-manifest.json)
fi

set +e
docker "${DOCKER_ARGS[@]}" "$IMAGE_ID" "${CONTROLLER_ARGS[@]}" > "$RUN_DIR/controller-execution.log" 2>&1
CONTROLLER_RC=$?
set -e
chown andris:andris "$RUN_DIR/controller-execution.log"
chmod 0600 "$RUN_DIR/controller-execution.log"
printf '%s\n' "$CONTROLLER_RC" > "$RUN_DIR/controller-exit-code.txt"
chown andris:andris "$RUN_DIR/controller-exit-code.txt"
chmod 0600 "$RUN_DIR/controller-exit-code.txt"

MANIFEST="$RUN_DIR/controller/controller-manifest.json"
ONE_SHOT="$RUN_DIR/controller/one-shot/one-shot-status.json"
[[ -f "$MANIFEST" && ! -L "$MANIFEST" ]] || fail 'controller manifest is missing or unsafe'
[[ -f "$ONE_SHOT" && ! -L "$ONE_SHOT" ]] || fail 'one-shot status is missing or unsafe'

python3 - "$MANIFEST" "$ONE_SHOT" "$RUN_DIR/sanitized-summary.json" "$EXPECTED_SHA" "$IMAGE_ID" "$TARGET" "$AS_OF" "$CONTROLLER_RC" <<'PY'
from __future__ import annotations
import json
from pathlib import Path
import re
import sys

manifest_path, one_shot_path, output_path = map(Path, sys.argv[1:4])
commit_sha, image_id, target, as_of = sys.argv[4:8]
controller_rc = int(sys.argv[8])
manifest = json.loads(manifest_path.read_text(encoding='utf-8'))
one_shot = json.loads(one_shot_path.read_text(encoding='utf-8'))
if not isinstance(manifest, dict) or not isinstance(one_shot, dict):
    raise SystemExit('Gate A evidence roots must be objects')
state = manifest.get('result')
expected_rc = {'READY': 0, 'NO_OP': 0, 'WAIT': 20, 'BLOCKED': 30}
if state not in expected_rc or controller_rc != expected_rc[state]:
    raise SystemExit('controller state/exit-code contract mismatch')
for key, expected in {
    'dry_run': True,
    'corpus_write_authorized': False,
    'database_write_authorized': False,
    'review_write_authorized': False,
    'production_publish_authorized': False,
    'systemd_change_authorized': False,
    'bounded_retry_authorized': False,
}.items():
    if manifest.get(key) is not expected:
        raise SystemExit(f'controller safety mismatch: {key}')
for key, expected in {
    'dry_run': True,
    'corpus_write': False,
    'db_write': False,
    'review_seed': False,
    'auto_approve': False,
    'auto_publish': False,
    'systemd_change': False,
}.items():
    if one_shot.get(key) is not expected:
        raise SystemExit(f'one-shot safety mismatch: {key}')
if manifest.get('target') != target or manifest.get('today_berlin') != as_of:
    raise SystemExit('controller request binding mismatch')
if one_shot.get('target') != target or one_shot.get('today_berlin') != as_of:
    raise SystemExit('one-shot request binding mismatch')
fingerprint = manifest.get('execution_fingerprint')
if state in {'READY', 'NO_OP'}:
    if not isinstance(fingerprint, str) or not re.fullmatch(r'[0-9a-f]{64}', fingerprint):
        raise SystemExit('completed Gate A state has invalid fingerprint')
else:
    if fingerprint is not None:
        raise SystemExit('non-completed Gate A state unexpectedly has fingerprint')
if state == 'READY':
    if manifest.get('new_immutable_snapshot_required') is not True or manifest.get('shadow_execution_required') is not True:
        raise SystemExit('READY action flags mismatch')
if state == 'NO_OP':
    if manifest.get('unchanged_exact_input') is not True or manifest.get('new_immutable_snapshot_required') is not False or manifest.get('shadow_execution_required') is not False:
        raise SystemExit('NO_OP action flags mismatch')
source = one_shot.get('source') if isinstance(one_shot.get('source'), dict) else {}
corpus = one_shot.get('corpus_match') if isinstance(one_shot.get('corpus_match'), dict) else {}
summary = {
    'schema_version': 1,
    'audit': 'lidl-weekly-gate-a',
    'registered_commit': commit_sha,
    'registered_image_id': image_id,
    'result': state,
    'reason': manifest.get('reason'),
    'one_shot_result': manifest.get('one_shot_result'),
    'one_shot_reason': manifest.get('one_shot_reason'),
    'target': target,
    'as_of': as_of,
    'execution_fingerprint': fingerprint,
    'previous_execution_fingerprint': manifest.get('previous_execution_fingerprint'),
    'unchanged_exact_input': manifest.get('unchanged_exact_input'),
    'new_immutable_snapshot_required': manifest.get('new_immutable_snapshot_required'),
    'shadow_execution_required': manifest.get('shadow_execution_required'),
    'source': {
        'valid_from': source.get('valid_from'),
        'valid_until': source.get('valid_until'),
        'route_region': source.get('route_region'),
        'pdf_sha256': source.get('pdf_sha256'),
        'raw_sha256': source.get('raw_sha256'),
        'page_count': source.get('page_count'),
        'readiness': source.get('readiness'),
    },
    'corpus_match': {
        'flyer_key': corpus.get('flyer_key'),
        'scan': corpus.get('scan'),
        'source_pdf_sha256': corpus.get('source_pdf_sha256'),
        'stable_source_identity_sha256': corpus.get('stable_source_identity_sha256'),
        'raw_refresh': corpus.get('raw_refresh'),
    },
    'parser_version': one_shot.get('parser_version'),
    'parser_sha256': one_shot.get('parser_sha256'),
    'dry_run': True,
    'corpus_write_authorized': False,
    'database_write_authorized': False,
    'review_write_authorized': False,
    'production_publish_authorized': False,
    'production_deploy_authorized': False,
    'systemd_change_authorized': False,
    'bounded_retry_authorized': False,
}
output_path.write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n', encoding='utf-8')
PY
chown andris:andris "$RUN_DIR/sanitized-summary.json"
chmod 0600 "$RUN_DIR/sanitized-summary.json"

PRIMARY_BRANCH_AFTER="$(git_read "$PRIMARY_REPO" branch --show-current)" || fail 'cannot re-read primary branch'
PRIMARY_HEAD_AFTER="$(git_read "$PRIMARY_REPO" rev-parse HEAD)" || fail 'cannot re-read primary HEAD'
PRIMARY_STATUS_AFTER="$(git_read "$PRIMARY_REPO" status --porcelain=v1 -z --untracked-files=all | sha256sum | awk '{print $1}')" || fail 'cannot re-read primary status'
[[ "$PRIMARY_BRANCH_AFTER" == "$PRIMARY_BRANCH_BEFORE" && "$PRIMARY_HEAD_AFTER" == "$PRIMARY_HEAD_BEFORE" && "$PRIMARY_STATUS_AFTER" == "$PRIMARY_STATUS_BEFORE" ]] || fail 'primary worktree changed'
[[ "$(git_read "$AUDIT_REPO" branch --show-current)" == "$AUDIT_BRANCH" ]] || fail 'audit branch changed'
[[ "$(git_read "$AUDIT_REPO" rev-parse HEAD)" == "$AUDIT_HEAD" ]] || fail 'audit HEAD changed'
[[ -z "$(git_read "$AUDIT_REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail 'audit status changed'
[[ "$(sha256sum "$AUDIT_REPO/.git/index" | awk '{print $1}')" == "$AUDIT_INDEX_SHA_BEFORE" ]] || fail 'audit index content changed'
[[ "$(stat -c '%U:%G:%a:%s:%Y' "$AUDIT_REPO/.git/index")" == "$AUDIT_INDEX_STAT_BEFORE" ]] || fail 'audit index metadata changed'
[[ "$(sha256sum "$PRIMARY_REPO/.git/index" | awk '{print $1}')" == "$PRIMARY_INDEX_SHA_BEFORE" ]] || fail 'primary index content changed'
[[ "$(stat -c '%U:%G:%a:%s:%Y' "$PRIMARY_REPO/.git/index")" == "$PRIMARY_INDEX_STAT_BEFORE" ]] || fail 'primary index metadata changed'

cat > "$RUN_DIR/safety-result.txt" <<SAFETY
PRIMARY_WORKTREE_MODIFIED=false
PRIMARY_GIT_INDEX_UNCHANGED=true
AUDIT_GIT_INDEX_UNCHANGED=true
CORPUS_WRITE=false
PRODUCTION_DATABASE_WRITE=false
REVIEW_WRITE=false
PRODUCTION_PUBLISH=false
PRODUCTION_DEPLOY=false
SYSTEMD_CHANGE=false
BOUNDED_RETRY=false
SAFETY
chown andris:andris "$RUN_DIR/safety-result.txt"
chmod 0600 "$RUN_DIR/safety-result.txt"
(
  cd "$RUN_DIR"
  find . -type f ! -name SHA256SUMS -print0 | sort -z | xargs -0 sha256sum > SHA256SUMS
  sha256sum --check --strict SHA256SUMS >/dev/null
)
chown andris:andris "$RUN_DIR/SHA256SUMS"
chmod 0600 "$RUN_DIR/SHA256SUMS"

STATE="$(python3 -c 'import json,sys; print(json.load(open(sys.argv[1]))["result"])' "$MANIFEST")"
printf 'AUDIT=lidl-weekly-gate-a\n'
printf 'RUNNER_VERSION=%s\n' "$RUNNER_VERSION"
printf 'REGISTERED_COMMIT=%s\n' "$EXPECTED_SHA"
printf 'REGISTERED_IMAGE_ID=%s\n' "$IMAGE_ID"
printf 'GATE_A_STATE=%s\n' "$STATE"
printf 'EVIDENCE_DIR=%s\n' "$RUN_DIR"
printf 'PRIMARY_WORKTREE_MODIFIED=false\nPRIMARY_GIT_INDEX_UNCHANGED=true\nAUDIT_GIT_INDEX_UNCHANGED=true\n'
printf 'CORPUS_WRITE=false\nPRODUCTION_DATABASE_WRITE=false\nREVIEW_WRITE=false\nPRODUCTION_PUBLISH=false\nPRODUCTION_DEPLOY=false\nSYSTEMD_CHANGE=false\nBOUNDED_RETRY=false\n'
[[ "$STATE" != BLOCKED ]] || exit 30
exit 0
