#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

DISPATCHER_VERSION='lidl-gate-b-family-scan-554-dispatcher-v01'
AUDIT_REPO='/home/andris/hermes-deals-audit-source-lidl'
PRIMARY_REPO='/home/andris/hermes-deals'
CORPUS_ROOT='/home/andris/hermes-deals-lidl-corpus'
EVIDENCE_ROOT='/home/andris/hermes-deals-lidl-gate-b-scan-evidence'
PUBLIC_ROOT='/var/lib/hermes-deals/lidl-gate-b-scan-554'

EXPECTED_SHA='f53b58ec2ba05bb6f8ca02fd07ccbbed380e8b4e'
EXPECTED_IMAGE='sha256:898dbfaba981ca7f583dcf2d6c623f9f407ce606760ebdb08f4e4be2f093174d'
FLYER='aktionsprospekt-10-08-2026-15-08-2026-71933b'
ROUTE_REGION='10'
EXPECTED_PDF_SHA='ce84a4996f5c709620b8becc44c4e2a23e23d24b28694679903490efc91ce728'
EXPECTED_RAW_SHA='12322c9989ea4038c7fb1e6d11e2728b6090e44958619b8cf4e5b22792f098fc'
EXPECTED_STABLE_SHA='bf94419e77dcef693490df5e6dd43ff40fbf04847061843a7d17ef65087ad304'
EXPECTED_PARSER_SHA='7191e910f07bb0a14ece3f398f1ba73e3ea250fc4bec1aeafea3afa8ce6dda90'
EXPECTED_SCAN='scan-v631-7191e910f07b'
EXPECTED_SCAN_TOOL_BLOB='13d9a6f8db1279a90ea1eff6a08f7942fa4a35aa'
EXPECTED_PROMOTION_TOOL_BLOB='4870c7f3cd3ba07f540fc7dd3b437b671d4fae17'
EXPECTED_STAGING_TOOL_BLOB='763f87d488a589489a2b3ff3cba35c86e1963894'
EXPECTED_RUNTIME_BLOB='88478af30124e03e13c194666838f4db06c0f79e'

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

git_read() {
  local repo="$1"
  shift
  runuser -u andris -- env HOME=/home/andris GIT_OPTIONAL_LOCKS=0 git -C "$repo" "$@"
}

tree_sha() {
  python3 - "$1" <<'PY'
from hashlib import sha256
from pathlib import Path
import sys
root = Path(sys.argv[1])
rows = []
for path in sorted(p for p in root.rglob('*') if p.is_file()):
    data = path.read_bytes()
    rows.append(f"{path.relative_to(root).as_posix()}|{len(data)}|{sha256(data).hexdigest()}")
print(sha256(("\n".join(rows) + "\n").encode()).hexdigest())
PY
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'dispatcher must execute as root via fixed sudoers entry'
[[ $# -eq 2 ]] || fail 'usage: dispatcher <github-run-id> <github-run-attempt>'
RUN_ID="$1"
RUN_ATTEMPT="$2"
[[ "$RUN_ID" =~ ^[1-9][0-9]*$ ]] || fail 'GitHub run ID must be a positive integer'
[[ "$RUN_ATTEMPT" =~ ^[1-9][0-9]*$ ]] || fail 'GitHub run attempt must be a positive integer'

for command in cmp diff docker find git id install python3 readlink runuser sha256sum stat; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

FAMILY="$CORPUS_ROOT/flyers/$FLYER"
RUN_ROOT="$EVIDENCE_ROOT/lidl-gate-b-scan-554-${RUN_ID}-${RUN_ATTEMPT}"
STAGE_A="$RUN_ROOT/a"
STAGE_B="$RUN_ROOT/b"
PUBLIC_DIR="$PUBLIC_ROOT/${RUN_ID}-${RUN_ATTEMPT}"

[[ -d "$AUDIT_REPO/.git" && ! -L "$AUDIT_REPO/.git" ]] || fail 'Lidl audit repository is missing or unsafe'
[[ -d "$PRIMARY_REPO/.git" && ! -L "$PRIMARY_REPO/.git" ]] || fail 'primary repository is missing or unsafe'
[[ -d "$CORPUS_ROOT/flyers" && ! -L "$CORPUS_ROOT" && ! -L "$CORPUS_ROOT/flyers" ]] || fail 'corpus root is missing or unsafe'
[[ "$(readlink -f -- "$CORPUS_ROOT")" == "$CORPUS_ROOT" ]] || fail 'corpus root path drift'
[[ -d "$FAMILY" && ! -L "$FAMILY" ]] || fail 'exact frozen family is missing or unsafe'

AUDIT_BRANCH="$(git_read "$AUDIT_REPO" branch --show-current)"
AUDIT_HEAD="$(git_read "$AUDIT_REPO" rev-parse HEAD)"
AUDIT_STATUS="$(git_read "$AUDIT_REPO" status --porcelain=v1 --untracked-files=all)"
[[ "$AUDIT_BRANCH" == main && "$AUDIT_HEAD" == "$EXPECTED_SHA" && -z "$AUDIT_STATUS" ]] || fail 'audit clone is not exact clean registered runtime'

PRIMARY_BRANCH_BEFORE="$(git_read "$PRIMARY_REPO" branch --show-current)"
PRIMARY_HEAD_BEFORE="$(git_read "$PRIMARY_REPO" rev-parse HEAD)"
PRIMARY_STATUS_BEFORE="$(git_read "$PRIMARY_REPO" status --porcelain=v1 -z --untracked-files=all | sha256sum | awk '{print $1}')"
[[ "$PRIMARY_BRANCH_BEFORE" == main ]] || fail 'primary repository is not on main'

[[ "$(git_read "$AUDIT_REPO" hash-object tools/lidl_gate_b_family_scan.py)" == "$EXPECTED_SCAN_TOOL_BLOB" ]] || fail 'family scan tool blob drift'
[[ "$(git_read "$AUDIT_REPO" hash-object tools/lidl_gate_b_family_promotion.py)" == "$EXPECTED_PROMOTION_TOOL_BLOB" ]] || fail 'family promotion helper blob drift'
[[ "$(git_read "$AUDIT_REPO" hash-object tools/lidl_weekly_staging.py)" == "$EXPECTED_STAGING_TOOL_BLOB" ]] || fail 'weekly staging helper blob drift'
[[ "$(git_read "$AUDIT_REPO" hash-object tools/lidl_parser_provenance/lidl_v631_runtime.py)" == "$EXPECTED_RUNTIME_BLOB" ]] || fail 'V6.3.1 runtime blob drift'

[[ "$(docker image inspect --format '{{.Id}}' "$EXPECTED_IMAGE")" == "$EXPECTED_IMAGE" ]] || fail 'registered audit image is unavailable or drifted'
[[ "$(docker image inspect --format '{{index .Config.Labels "net.rozkalns.hermes-deals.commit"}}' "$EXPECTED_IMAGE")" == "$EXPECTED_SHA" ]] || fail 'registered image commit label mismatch'

[[ -f "$FAMILY/source.pdf" && ! -L "$FAMILY/source.pdf" ]] || fail 'frozen source PDF is missing or unsafe'
[[ -f "$FAMILY/source.json" && ! -L "$FAMILY/source.json" ]] || fail 'frozen source JSON is missing or unsafe'
[[ -f "$FAMILY/gate-b-freeze-receipt.json" && ! -L "$FAMILY/gate-b-freeze-receipt.json" ]] || fail 'freeze receipt is missing or unsafe'
[[ "$(sha256sum "$FAMILY/source.pdf" | awk '{print $1}')" == "$EXPECTED_PDF_SHA" ]] || fail 'frozen PDF SHA mismatch'
[[ "$(sha256sum "$FAMILY/source.json" | awk '{print $1}')" == "$EXPECTED_RAW_SHA" ]] || fail 'frozen raw JSON SHA mismatch'

python3 - "$FAMILY/gate-b-freeze-receipt.json" "$EXPECTED_PDF_SHA" "$EXPECTED_RAW_SHA" "$EXPECTED_STABLE_SHA" <<'PY'
import json
from pathlib import Path
import sys
path = Path(sys.argv[1])
pdf_sha, raw_sha, stable_sha = sys.argv[2:]
receipt = json.loads(path.read_text(encoding='utf-8'))
if receipt.get('result') != 'FROZEN':
    raise SystemExit('freeze receipt result mismatch')
source = receipt.get('source') or {}
if source.get('pdf_sha256') != pdf_sha:
    raise SystemExit('freeze receipt PDF SHA mismatch')
if source.get('raw_sha256') != raw_sha:
    raise SystemExit('freeze receipt raw SHA mismatch')
if source.get('stable_source_identity_sha256') != stable_sha:
    raise SystemExit('freeze receipt stable source identity mismatch')
PY

FAMILY_TREE_BEFORE="$(tree_sha "$FAMILY")"
[[ ! -e "$RUN_ROOT" ]] || fail 'private scan evidence path already exists'
[[ ! -e "$PUBLIC_DIR" ]] || fail 'sanitized output path already exists'
install -d -o andris -g andris -m 0700 "$EVIDENCE_ROOT" "$RUN_ROOT" "$STAGE_A" "$STAGE_B"
install -d -o root -g root -m 0755 "$PUBLIC_ROOT" "$PUBLIC_DIR"

ANDRIS_UID="$(id -u andris)"
ANDRIS_GID="$(id -g andris)"
run_scan() {
  local stage="$1"
  local result_file="$2"
  docker run --rm \
    --network none \
    --read-only \
    --cap-drop ALL \
    --security-opt no-new-privileges:true \
    --pids-limit 256 \
    --memory 1536m \
    --cpus 2 \
    --user "$ANDRIS_UID:$ANDRIS_GID" \
    --env HOME=/tmp \
    --env PYTHONDONTWRITEBYTECODE=1 \
    --tmpfs /tmp:rw,nosuid,nodev,noexec,size=256m,mode=1777 \
    --mount "type=bind,src=$AUDIT_REPO,dst=/repo,readonly" \
    --mount "type=bind,src=$FAMILY,dst=/frozen-family/$FLYER,readonly" \
    --mount "type=bind,src=$stage,dst=/out" \
    "$EXPECTED_IMAGE" \
    python /repo/tools/lidl_gate_b_family_scan.py \
      --frozen-family "/frozen-family/$FLYER" \
      --output-root /out \
      --route-region "$ROUTE_REGION" \
      --target next > "$result_file"
  chown andris:andris "$result_file"
  chmod 0600 "$result_file"
}

run_scan "$STAGE_A" "$RUN_ROOT/scan-a-result.json"
run_scan "$STAGE_B" "$RUN_ROOT/scan-b-result.json"

SCAN_A="$STAGE_A/flyers/$FLYER/scans/$EXPECTED_SCAN"
SCAN_B="$STAGE_B/flyers/$FLYER/scans/$EXPECTED_SCAN"
[[ -d "$SCAN_A" && ! -L "$SCAN_A" ]] || fail 'scan A tree missing or unsafe'
[[ -d "$SCAN_B" && ! -L "$SCAN_B" ]] || fail 'scan B tree missing or unsafe'
(cd "$SCAN_A" && sha256sum -c SHA256SUMS >/dev/null)
(cd "$SCAN_B" && sha256sum -c SHA256SUMS >/dev/null)

diff -qr "$STAGE_A" "$STAGE_B" >/dev/null || fail 'independent staging trees are not byte-identical'
cmp -s "$RUN_ROOT/scan-a-result.json" "$RUN_ROOT/scan-b-result.json" || fail 'independent scan result payloads are not byte-identical'

SCAN_TREE_A="$(tree_sha "$SCAN_A")"
SCAN_TREE_B="$(tree_sha "$SCAN_B")"
[[ "$SCAN_TREE_A" == "$SCAN_TREE_B" ]] || fail 'scan tree SHA replay mismatch'

FAMILY_TREE_AFTER="$(tree_sha "$FAMILY")"
[[ "$FAMILY_TREE_AFTER" == "$FAMILY_TREE_BEFORE" ]] || fail 'frozen family changed during staging scan'

AUDIT_BRANCH_AFTER="$(git_read "$AUDIT_REPO" branch --show-current)"
AUDIT_HEAD_AFTER="$(git_read "$AUDIT_REPO" rev-parse HEAD)"
AUDIT_STATUS_AFTER="$(git_read "$AUDIT_REPO" status --porcelain=v1 --untracked-files=all)"
[[ "$AUDIT_BRANCH_AFTER" == "$AUDIT_BRANCH" && "$AUDIT_HEAD_AFTER" == "$AUDIT_HEAD" && "$AUDIT_STATUS_AFTER" == "$AUDIT_STATUS" ]] || fail 'audit repository changed during scan'

PRIMARY_BRANCH_AFTER="$(git_read "$PRIMARY_REPO" branch --show-current)"
PRIMARY_HEAD_AFTER="$(git_read "$PRIMARY_REPO" rev-parse HEAD)"
PRIMARY_STATUS_AFTER="$(git_read "$PRIMARY_REPO" status --porcelain=v1 -z --untracked-files=all | sha256sum | awk '{print $1}')"
[[ "$PRIMARY_BRANCH_AFTER" == "$PRIMARY_BRANCH_BEFORE" && "$PRIMARY_HEAD_AFTER" == "$PRIMARY_HEAD_BEFORE" && "$PRIMARY_STATUS_AFTER" == "$PRIMARY_STATUS_BEFORE" ]] || fail 'primary repository changed during scan'

python3 - \
  "$RUN_ROOT/scan-a-result.json" \
  "$SCAN_A/summary.json" \
  "$PUBLIC_DIR/summary.json" \
  "$DISPATCHER_VERSION" \
  "$EXPECTED_SHA" \
  "$EXPECTED_IMAGE" \
  "$FLYER" \
  "$ROUTE_REGION" \
  "$EXPECTED_PDF_SHA" \
  "$EXPECTED_RAW_SHA" \
  "$EXPECTED_STABLE_SHA" \
  "$EXPECTED_PARSER_SHA" \
  "$EXPECTED_SCAN" \
  "$SCAN_TREE_A" <<'PY'
import json
from pathlib import Path
import sys
(
    result_path,
    scan_summary_path,
    output_path,
    dispatcher_version,
    runtime_sha,
    image_id,
    flyer,
    route_region,
    pdf_sha,
    raw_sha,
    stable_sha,
    parser_sha,
    scan_name,
    scan_tree_sha,
) = sys.argv[1:]
result = json.loads(Path(result_path).read_text(encoding='utf-8'))
summary = json.loads(Path(scan_summary_path).read_text(encoding='utf-8'))
if result.get('result') != 'STAGED_SCAN_READY':
    raise SystemExit('staging result mismatch')
for key, expected in {
    'flyer_key': flyer,
    'scan': scan_name,
    'parser_sha256': parser_sha,
    'scan_tree_sha256': scan_tree_sha,
}.items():
    if result.get(key) != expected:
        raise SystemExit(f'staging result identity mismatch: {key}')
if result.get('parser_version') != 'lidl-pdf-v08c-r61-shadow-v631':
    raise SystemExit('parser version mismatch')
for key, expected in {
    'staging_write': True,
    'corpus_write': False,
    'db_write': False,
    'review_write': False,
    'auto_approve': False,
    'auto_publish': False,
    'production_deploy': False,
    'systemd_change': False,
}.items():
    if result.get(key) is not expected:
        raise SystemExit(f'unsafe staging flag: {key}')
source = summary.get('source') or {}
if source.get('pdf_sha256') != pdf_sha or source.get('raw_sha256') != raw_sha:
    raise SystemExit('scan summary source identity mismatch')
if summary.get('parser_sha256') != parser_sha or summary.get('scan') != scan_name:
    raise SystemExit('scan summary parser identity mismatch')
output = {
    'schema_version': 1,
    'audit': 'lidl-gate-b-family-scan-554',
    'result': 'PASS',
    'dispatcher_version': dispatcher_version,
    'registered_commit': runtime_sha,
    'registered_image_id': image_id,
    'flyer_key': flyer,
    'route_region': route_region,
    'source_pdf_sha256': pdf_sha,
    'source_raw_sha256': raw_sha,
    'stable_source_identity_sha256': stable_sha,
    'parser_version': 'lidl-pdf-v08c-r61-shadow-v631',
    'parser_sha256': parser_sha,
    'scan': scan_name,
    'scan_tree_sha256': scan_tree_sha,
    'observed_at': result.get('observed_at'),
    'scan_member_count': sum(1 for p in Path(scan_summary_path).parent.rglob('*') if p.is_file()),
    'rows': summary.get('rows'),
    'physical_rows': summary.get('physical_rows'),
    'in_scope_rows': summary.get('in_scope_rows'),
    'accepted_physical_rows': summary.get('accepted_physical_rows'),
    'review_required_rows': summary.get('review_required_rows'),
    'online_only_rows': summary.get('online_only_rows'),
    'byte_identical_replay': True,
    'frozen_family_unchanged': True,
    'primary_repository_unchanged': True,
    'audit_repository_unchanged': True,
    'staging_write_performed': True,
    'corpus_write_performed': False,
    'database_write_performed': False,
    'review_write_performed': False,
    'production_publish_performed': False,
    'production_deploy_performed': False,
    'systemd_change_performed': False,
    'automatic_retry_performed': False,
    'gate_c_d_authorized': False,
}
Path(output_path).write_text(json.dumps(output, indent=2, sort_keys=True) + '\n', encoding='utf-8')
PY
chmod 0644 "$PUBLIC_DIR/summary.json"

printf 'RESULT=PASS\n'
printf 'SANITIZED_SUMMARY=%s\n' "$PUBLIC_DIR/summary.json"
