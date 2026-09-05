#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH PYTHONDONTWRITEBYTECODE=1

DISPATCHER_VERSION='lidl-gate-b-frozen-review-pack-603-dispatcher-v01'
PRIMARY_REPO='/home/andris/hermes-deals'
AUDIT_REPO='/home/andris/hermes-deals-audit-source-lidl'
CORPUS_ROOT='/home/andris/hermes-deals-lidl-corpus'
FLYER='aktionsprospekt-10-08-2026-15-08-2026-71933b'
FAMILY="$CORPUS_ROOT/flyers/$FLYER"
SOURCE_PDF="$FAMILY/source.pdf"
EXPECTED_PDF_SHA='ce84a4996f5c709620b8becc44c4e2a23e23d24b28694679903490efc91ce728'
EXPECTED_PAGE_COUNT='73'
EXPECTED_SCAN_TREE_SHA='dd4ef887a72d6942bbade1adf8f2e2e29c229675c8c28bb1f0b41c1082d4f4c1'
PRIVATE_ROOT='/home/andris/hermes-deals-lidl-review-pack-evidence'
PUBLIC_ROOT='/var/lib/hermes-deals/lidl-gate-b-frozen-review-pack-603'

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

repo_snapshot() {
  local repo="$1"
  local prefix="$2"
  local branch head status
  branch="$(git_read "$repo" branch --show-current)"
  head="$(git_read "$repo" rev-parse HEAD)"
  status="$(git_read "$repo" status --porcelain=v1 -z --untracked-files=all | sha256sum | awk '{print $1}')"
  printf -v "${prefix}_BRANCH" '%s' "$branch"
  printf -v "${prefix}_HEAD" '%s' "$head"
  printf -v "${prefix}_STATUS" '%s' "$status"
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail 'dispatcher must execute as root via fixed sudoers entry'
[[ $# -eq 2 ]] || fail 'usage: dispatcher <github-run-id> <github-run-attempt>'
RUN_ID="$1"
RUN_ATTEMPT="$2"
[[ "$RUN_ID" =~ ^[1-9][0-9]*$ ]] || fail 'GitHub run ID must be a positive integer'
[[ "$RUN_ATTEMPT" =~ ^[1-9][0-9]*$ ]] || fail 'GitHub run attempt must be a positive integer'

for user in andris github-runner; do
  id "$user" >/dev/null 2>&1 || fail "required local user is missing: $user"
done
for command in cmp diff find git grep id install pdfinfo pdftoppm python3 readlink runuser sha256sum sort stat tr xargs; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
if id -nG github-runner | tr ' ' '\n' | grep -Fxq docker; then
  fail 'github-runner must not belong to the Docker group'
fi

[[ -d "$PRIMARY_REPO/.git" && ! -L "$PRIMARY_REPO/.git" ]] || fail 'primary repository is missing or unsafe'
[[ -d "$AUDIT_REPO/.git" && ! -L "$AUDIT_REPO/.git" ]] || fail 'Lidl audit repository is missing or unsafe'
[[ -d "$CORPUS_ROOT/flyers" && ! -L "$CORPUS_ROOT" && ! -L "$CORPUS_ROOT/flyers" ]] || fail 'corpus root is missing or unsafe'
[[ "$(readlink -f -- "$CORPUS_ROOT")" == "$CORPUS_ROOT" ]] || fail 'corpus root path drift'
[[ -d "$FAMILY" && ! -L "$FAMILY" ]] || fail 'exact frozen family is missing or unsafe'
[[ "$(readlink -f -- "$FAMILY")" == "$FAMILY" ]] || fail 'frozen family path drift'
[[ "$(stat -c '%U:%G %a' "$FAMILY")" == 'andris:andris 700' ]] || fail 'frozen family metadata drift'
[[ -f "$SOURCE_PDF" && ! -L "$SOURCE_PDF" ]] || fail 'frozen source PDF is missing or unsafe'
[[ "$(readlink -f -- "$SOURCE_PDF")" == "$SOURCE_PDF" ]] || fail 'frozen source PDF path drift'
[[ "$(stat -c '%U:%G %a' "$SOURCE_PDF")" == 'andris:andris 600' ]] || fail 'frozen source PDF metadata drift'
[[ "$(sha256sum "$SOURCE_PDF" | awk '{print $1}')" == "$EXPECTED_PDF_SHA" ]] || fail 'frozen source PDF SHA mismatch'

PAGE_COUNT="$(runuser -u andris -- pdfinfo "$SOURCE_PDF" | awk -F: '/^Pages:/ {gsub(/[[:space:]]/, "", $2); print $2; exit}')"
[[ "$PAGE_COUNT" == "$EXPECTED_PAGE_COUNT" ]] || fail 'frozen source PDF page count mismatch'
RENDERER_VERSION="$(runuser -u andris -- pdftoppm -v 2>&1 | head -n 1 | tr -d '\r')"
[[ -n "$RENDERER_VERSION" ]] || fail 'unable to identify pdftoppm renderer version'

repo_snapshot "$PRIMARY_REPO" PRIMARY_BEFORE
repo_snapshot "$AUDIT_REPO" AUDIT_BEFORE
[[ "$PRIMARY_BEFORE_BRANCH" == main ]] || fail 'primary repository is not on main'
FAMILY_TREE_BEFORE="$(tree_sha "$FAMILY")"
SOURCE_STAT_BEFORE="$(stat -Lc '%d:%i:%s:%Y:%Z' "$SOURCE_PDF")"

RUN_ROOT="$PRIVATE_ROOT/lidl-gate-b-frozen-review-pack-603-${RUN_ID}-${RUN_ATTEMPT}"
STAGE_A="$RUN_ROOT/a"
STAGE_B="$RUN_ROOT/b"
PUBLIC_DIR="$PUBLIC_ROOT/${RUN_ID}-${RUN_ATTEMPT}"
ARTIFACT_DIR="$PUBLIC_DIR/artifact"
[[ ! -e "$RUN_ROOT" ]] || fail 'private review-pack evidence path already exists'
[[ ! -e "$PUBLIC_DIR" ]] || fail 'sanitized review-pack output path already exists'
install -d -o andris -g andris -m 0700 "$PRIVATE_ROOT" "$RUN_ROOT" "$STAGE_A" "$STAGE_B"
install -d -o root -g root -m 0755 "$PUBLIC_ROOT" "$PUBLIC_DIR" "$ARTIFACT_DIR" "$ARTIFACT_DIR/pages"

render_stage() {
  local stage="$1"
  local prefix="$stage/raw-page"
  runuser -u andris -- pdftoppm \
    -f 1 \
    -l "$EXPECTED_PAGE_COUNT" \
    -r 110 \
    -jpeg \
    -jpegopt quality=88,optimize=y \
    "$SOURCE_PDF" \
    "$prefix"
  runuser -u andris -- python3 - "$stage" "$EXPECTED_PAGE_COUNT" <<'PY'
import re
import sys
from pathlib import Path
root = Path(sys.argv[1])
expected = int(sys.argv[2])
rows = []
for path in root.glob('raw-page-*.jpg'):
    match = re.search(r'-(\d+)\.jpg$', path.name)
    if match:
        rows.append((int(match.group(1)), path))
rows.sort()
if [page for page, _ in rows] != list(range(1, expected + 1)):
    raise SystemExit('rendered page sequence mismatch')
for page, path in rows:
    path.rename(root / f'page-{page:03d}.jpg')
PY
  [[ "$(find "$stage" -maxdepth 1 -type f -name 'page-*.jpg' | wc -l)" == "$EXPECTED_PAGE_COUNT" ]] \
    || fail 'rendered page image count mismatch'
  find "$stage" -maxdepth 1 -type f -name 'page-*.jpg' -exec chmod 0600 {} +
}

render_stage "$STAGE_A"
render_stage "$STAGE_B"
diff -qr "$STAGE_A" "$STAGE_B" >/dev/null || fail 'independent page renders are not byte-identical'

RENDER_TREE_A="$(tree_sha "$STAGE_A")"
RENDER_TREE_B="$(tree_sha "$STAGE_B")"
[[ "$RENDER_TREE_A" == "$RENDER_TREE_B" ]] || fail 'render tree SHA replay mismatch'

SOURCE_STAT_AFTER="$(stat -Lc '%d:%i:%s:%Y:%Z' "$SOURCE_PDF")"
[[ "$SOURCE_STAT_AFTER" == "$SOURCE_STAT_BEFORE" ]] || fail 'frozen source PDF metadata changed during render'
[[ "$(sha256sum "$SOURCE_PDF" | awk '{print $1}')" == "$EXPECTED_PDF_SHA" ]] || fail 'frozen source PDF changed during render'
FAMILY_TREE_AFTER="$(tree_sha "$FAMILY")"
[[ "$FAMILY_TREE_AFTER" == "$FAMILY_TREE_BEFORE" ]] || fail 'frozen family changed during render'

repo_snapshot "$PRIMARY_REPO" PRIMARY_AFTER
repo_snapshot "$AUDIT_REPO" AUDIT_AFTER
[[ "$PRIMARY_AFTER_BRANCH" == "$PRIMARY_BEFORE_BRANCH" && "$PRIMARY_AFTER_HEAD" == "$PRIMARY_BEFORE_HEAD" && "$PRIMARY_AFTER_STATUS" == "$PRIMARY_BEFORE_STATUS" ]] \
  || fail 'primary repository changed during render'
[[ "$AUDIT_AFTER_BRANCH" == "$AUDIT_BEFORE_BRANCH" && "$AUDIT_AFTER_HEAD" == "$AUDIT_BEFORE_HEAD" && "$AUDIT_AFTER_STATUS" == "$AUDIT_BEFORE_STATUS" ]] \
  || fail 'Lidl audit repository changed during render'

for image in "$STAGE_A"/page-*.jpg; do
  install -o root -g root -m 0644 "$image" "$ARTIFACT_DIR/pages/$(basename "$image")"
done
(
  cd "$ARTIFACT_DIR"
  find pages -maxdepth 1 -type f -name 'page-*.jpg' -print0 \
    | sort -z \
    | xargs -0 sha256sum > PAGE_SHA256SUMS
)
chmod 0644 "$ARTIFACT_DIR/PAGE_SHA256SUMS"

python3 - \
  "$ARTIFACT_DIR/PAGE_SHA256SUMS" \
  "$ARTIFACT_DIR/manifest.json" \
  "$PUBLIC_DIR/summary.json" \
  "$DISPATCHER_VERSION" \
  "$FLYER" \
  "$EXPECTED_PDF_SHA" \
  "$EXPECTED_PAGE_COUNT" \
  "$EXPECTED_SCAN_TREE_SHA" \
  "$RENDERER_VERSION" \
  "$RENDER_TREE_A" \
  "$RUN_ID" \
  "$RUN_ATTEMPT" <<'PY'
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
(
    sums_path,
    manifest_path,
    summary_path,
    dispatcher_version,
    flyer,
    pdf_sha,
    page_count,
    scan_tree_sha,
    renderer_version,
    render_tree_sha,
    run_id,
    run_attempt,
) = sys.argv[1:]
sums = Path(sums_path).read_text(encoding='utf-8').splitlines()
expected = int(page_count)
if len(sums) != expected:
    raise SystemExit('page checksum count mismatch')
pages = []
for index, line in enumerate(sums, 1):
    match = re.fullmatch(r'([0-9a-f]{64})  (pages/page-([0-9]{3})\.jpg)', line)
    if not match or int(match.group(3)) != index:
        raise SystemExit('page checksum sequence mismatch')
    path = Path(manifest_path).parent / match.group(2)
    data = path.read_bytes()
    if sha256(data).hexdigest() != match.group(1):
        raise SystemExit('page checksum mismatch')
    pages.append({'page': index, 'file': match.group(2), 'bytes': len(data), 'sha256': match.group(1)})
manifest = {
    'schema_version': 1,
    'audit': 'lidl-gate-b-frozen-review-pack-603',
    'result': 'PASS',
    'dispatcher_version': dispatcher_version,
    'flyer_key': flyer,
    'source_pdf_sha256': pdf_sha,
    'page_count': expected,
    'staging_scan_tree_sha256': scan_tree_sha,
    'renderer': renderer_version,
    'render_dpi': 110,
    'jpeg_quality': 88,
    'independent_render_replay': 'BYTE_IDENTICAL_PASS',
    'render_tree_sha256': render_tree_sha,
    'pages': pages,
    'safety': {
        'private_evidence_write': True,
        'artifact_write': True,
        'source_content_exported': False,
        'raw_pdf_uploaded': False,
        'corpus_write': False,
        'corpus_replacement': False,
        'production_database_write': False,
        'review_write': False,
        'production_publish': False,
        'production_deploy': False,
        'systemd_change': False,
        'automatic_retry': False,
        'gate_c_d_authorized': False,
    },
}
encoded = (json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + '\n').encode()
Path(manifest_path).write_bytes(encoded)
manifest_sha = sha256(encoded).hexdigest()
summary = {
    'schema_version': 1,
    'audit': 'lidl-gate-b-frozen-review-pack-603',
    'result': 'PASS',
    'github_run_id': int(run_id),
    'github_run_attempt': int(run_attempt),
    'flyer_key': flyer,
    'source_pdf_sha256': pdf_sha,
    'page_count': expected,
    'staging_scan_tree_sha256': scan_tree_sha,
    'renderer': renderer_version,
    'render_tree_sha256': render_tree_sha,
    'manifest_sha256': manifest_sha,
    'independent_render_replay': 'BYTE_IDENTICAL_PASS',
    'safety': manifest['safety'],
}
Path(summary_path).write_text(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True) + '\n', encoding='utf-8')
print(manifest_sha)
PY
chmod 0644 "$ARTIFACT_DIR/manifest.json" "$PUBLIC_DIR/summary.json"

[[ "$(find "$ARTIFACT_DIR/pages" -maxdepth 1 -type f -name 'page-*.jpg' | wc -l)" == "$EXPECTED_PAGE_COUNT" ]] || fail 'public artifact page count mismatch'
[[ ! -e "$ARTIFACT_DIR/source.pdf" ]] || fail 'raw PDF leaked into public artifact'

printf 'RESULT=PASS\n'
printf 'FLYER=%s\n' "$FLYER"
printf 'SOURCE_PDF_SHA256=%s\n' "$EXPECTED_PDF_SHA"
printf 'PAGE_COUNT=%s\n' "$EXPECTED_PAGE_COUNT"
printf 'STAGING_SCAN_TREE_SHA256=%s\n' "$EXPECTED_SCAN_TREE_SHA"
printf 'RENDERER=%s\n' "$RENDERER_VERSION"
printf 'RENDER_TREE_SHA256=%s\n' "$RENDER_TREE_A"
printf 'PUBLIC_ARTIFACT_DIR=%s\n' "$ARTIFACT_DIR"
printf 'SUMMARY_PATH=%s\n' "$PUBLIC_DIR/summary.json"
printf 'PRIVATE_EVIDENCE_WRITE=true\n'
printf 'CORPUS_WRITE=false\n'
printf 'CORPUS_REPLACEMENT=false\n'
printf 'PRODUCTION_DATABASE_WRITE=false\n'
printf 'REVIEW_WRITE=false\n'
printf 'PRODUCTION_PUBLISH=false\n'
printf 'PRODUCTION_DEPLOY=false\n'
printf 'SYSTEMD_CHANGE=false\n'
printf 'AUTOMATIC_RETRY=false\n'
printf 'GATE_C_D_AUTHORIZED=false\n'
printf 'LIDL_GATE_B_FROZEN_REVIEW_PACK_603=PASS\n'