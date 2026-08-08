#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH PYTHONDONTWRITEBYTECODE=1

fail() { echo "ERROR: $*" >&2; exit 1; }

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "run with sudo"
[[ $# -eq 2 ]] || fail "usage: sudo bash tools/runner/install-netto-missing-normal-price-rpi5-audit.sh <merged-main-sha> <clean-detached-source-worktree>"

EXPECTED_SHA="$1"
SOURCE_REPO="$(readlink -f -- "$2")"
EXPECTED_SOURCE_REPO='/home/andris/hermes-deals-worktrees/netto-missing-normal-price-audit-v1'
PRIMARY_GIT_COMMON_DIR='/home/andris/hermes-deals/.git'
RUNTIME_ROOT='/usr/local/libexec/hermes-deals-audits/netto-missing-normal-price-audit-v1'
DISPATCHER='/usr/local/sbin/hermes-deals-netto-missing-normal-price-audit-dispatch'
SUDOERS='/etc/sudoers.d/hermes-deals-netto-missing-normal-price-audit'
REGISTRY_DIR='/etc/hermes-deals-audits.d'
CONFIG="$REGISTRY_DIR/netto-missing-normal-price-audit-v1.conf"
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'
N9_MANIFEST='/home/andris/hermes-deals-audits/netto-n9-visual-cell-validation-pack-v1-20260802T202304Z/generated/fixture-manifest.json'
CORPUS_ROOT='/home/andris/hermes-deals-netto-corpus/flyers'
EXPECTED_N9_SHA='2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147'
EXPECTED_N10_SHA='bf35bff323d76a2b29a7248df067641e5b9f2a7d29329cf53bf9fc0ae832734a'

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "commit SHA is invalid"
[[ "$SOURCE_REPO" == "$EXPECTED_SOURCE_REPO" ]] || fail "source worktree must be $EXPECTED_SOURCE_REPO"
for user in github-runner andris; do id "$user" >/dev/null 2>&1 || fail "required local user is missing: $user"; done
for command in git grep id install mktemp python3 readlink runuser sha256sum stat sudo tr visudo; do command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"; done
if id -nG github-runner | tr ' ' '\n' | grep -Fxq docker; then fail "github-runner must not belong to the Docker group"; fi

git_source() {
  runuser -u andris -- /usr/bin/env -i HOME=/home/andris USER=andris LOGNAME=andris \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin GIT_OPTIONAL_LOCKS=0 \
    /usr/bin/git "$@"
}

[[ "$(git_source -C "$SOURCE_REPO" rev-parse --is-inside-work-tree 2>/dev/null)" == true ]] || fail "source path is not a Git worktree"
[[ "$(git_source -C "$SOURCE_REPO" rev-parse HEAD)" == "$EXPECTED_SHA" ]] || fail "source worktree HEAD mismatch"
[[ -z "$(git_source -C "$SOURCE_REPO" branch --show-current)" ]] || fail "source worktree must be detached"
[[ -z "$(git_source -C "$SOURCE_REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail "source worktree is not clean"
COMMON_DIR="$(git_source -C "$SOURCE_REPO" rev-parse --git-common-dir)"
case "$COMMON_DIR" in /*) COMMON_DIR="$(readlink -f -- "$COMMON_DIR")" ;; *) COMMON_DIR="$(readlink -f -- "$SOURCE_REPO/$COMMON_DIR")" ;; esac
[[ "$COMMON_DIR" == "$PRIMARY_GIT_COMMON_DIR" ]] || fail "source is not a worktree of /home/andris/hermes-deals"
git_source -C "$SOURCE_REPO" show-ref --verify --quiet refs/remotes/origin/main || fail "origin/main unavailable"
git_source -C "$SOURCE_REPO" merge-base --is-ancestor "$EXPECTED_SHA" refs/remotes/origin/main || fail "registered SHA not reachable from origin/main"

RELATIVE_FILES=(
  tools/netto_missing_normal_price_audit.py
  tools/netto_visual_geometry_corpus_replay.py
  tools/netto_visual_geometry_shadow.py
  backend/tests/fixtures/netto/n10_full_visual_review_v1.json
)
for relative in "${RELATIVE_FILES[@]}"; do
  git_source -C "$SOURCE_REPO" ls-files --error-unmatch "$relative" >/dev/null || fail "required source is not tracked: $relative"
  [[ -f "$SOURCE_REPO/$relative" && ! -L "$SOURCE_REPO/$relative" ]] || fail "required source is missing or unsafe: $relative"
done
[[ -f "$N9_MANIFEST" && ! -L "$N9_MANIFEST" ]] || fail "N9 manifest unavailable or unsafe"
[[ "$(sha256sum "$N9_MANIFEST" | awk '{print $1}')" == "$EXPECTED_N9_SHA" ]] || fail "N9 manifest SHA mismatch"
[[ -d "$CORPUS_ROOT" && ! -L "$CORPUS_ROOT" ]] || fail "immutable corpus root unavailable or unsafe"
[[ "$(sha256sum "$SOURCE_REPO/backend/tests/fixtures/netto/n10_full_visual_review_v1.json" | awk '{print $1}')" == "$EXPECTED_N10_SHA" ]] || fail "N10 ledger SHA mismatch"
PYMUPDF_VERSION="$(runuser -u andris -- /usr/bin/env -i HOME=/home/andris USER=andris LOGNAME=andris PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 - <<'PY'
import pymupdf
print(pymupdf.pymupdf_version)
PY
)"
[[ "$PYMUPDF_VERSION" == '1.28.0' ]] || fail "PyMuPDF 1.28.0 required, found $PYMUPDF_VERSION"

TMP="$(mktemp -d /tmp/hermes-deals-netto-missing-normal-price-installer.XXXXXX)"
cleanup() { rm -rf -- "$TMP"; }
trap cleanup EXIT
install -d -o root -g root -m 0755 "$RUNTIME_ROOT" "$RUNTIME_ROOT/tools" "$RUNTIME_ROOT/backend/tests/fixtures/netto" "$REGISTRY_DIR"
install -d -o andris -g andris -m 0700 "$STAGING_ROOT"
for relative in "${RELATIVE_FILES[@]}"; do install -o root -g root -m 0644 "$SOURCE_REPO/$relative" "$RUNTIME_ROOT/$relative"; done

MISSING_TOOL="$RUNTIME_ROOT/tools/netto_missing_normal_price_audit.py"
BASE_TOOL="$RUNTIME_ROOT/tools/netto_visual_geometry_corpus_replay.py"
PARSER_TOOL="$RUNTIME_ROOT/tools/netto_visual_geometry_shadow.py"
N10_LEDGER="$RUNTIME_ROOT/backend/tests/fixtures/netto/n10_full_visual_review_v1.json"
MISSING_SHA="$(sha256sum "$MISSING_TOOL" | awk '{print $1}')"
BASE_SHA="$(sha256sum "$BASE_TOOL" | awk '{print $1}')"
PARSER_SHA="$(sha256sum "$PARSER_TOOL" | awk '{print $1}')"
N10_SHA="$(sha256sum "$N10_LEDGER" | awk '{print $1}')"

cat > "$TMP/config" <<EOF
audit_name='netto-missing-normal-price-audit-v1'
commit_sha='$EXPECTED_SHA'
runtime_root='$RUNTIME_ROOT'
missing_tool='$MISSING_TOOL'
missing_tool_sha256='$MISSING_SHA'
base_tool='$BASE_TOOL'
base_tool_sha256='$BASE_SHA'
parser_tool='$PARSER_TOOL'
parser_tool_sha256='$PARSER_SHA'
n10_ledger='$N10_LEDGER'
n10_ledger_sha256='$N10_SHA'
n9_manifest='$N9_MANIFEST'
n9_manifest_sha256='$EXPECTED_N9_SHA'
corpus_root='$CORPUS_ROOT'
EOF
install -o root -g root -m 0644 "$TMP/config" "$CONFIG"

cat > "$TMP/dispatcher" <<'DISPATCH'
#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH PYTHONDONTWRITEBYTECODE=1
fail() { echo "ERROR: $*" >&2; exit 1; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "dispatcher must run as root through sudo"
[[ $# -eq 2 ]] || fail "usage: hermes-deals-netto-missing-normal-price-audit-dispatch <registered-commit-sha> <artifact-dir>"
EXPECTED_SHA="$1"
EXPORT_DIR="$(readlink -f -- "$2")"
CONFIG='/etc/hermes-deals-audits.d/netto-missing-normal-price-audit-v1.conf'
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'
[[ -f "$CONFIG" && ! -L "$CONFIG" ]] || fail "audit is not registered"
[[ "$(stat -c '%U:%G %a' "$CONFIG")" == 'root:root 644' ]] || fail "audit config metadata invalid"
# shellcheck disable=SC1090
source "$CONFIG"
[[ "$audit_name" == 'netto-missing-normal-price-audit-v1' && "$commit_sha" == "$EXPECTED_SHA" ]] || fail "registered audit identity mismatch"
for pair in "$missing_tool:$missing_tool_sha256" "$base_tool:$base_tool_sha256" "$parser_tool:$parser_tool_sha256" "$n10_ledger:$n10_ledger_sha256" "$n9_manifest:$n9_manifest_sha256"; do
  path="${pair%%:*}"; expected="${pair#*:}"
  [[ -f "$path" && ! -L "$path" && "$expected" =~ ^[0-9a-f]{64}$ ]] || fail "registered member unsafe: $path"
  [[ "$(sha256sum "$path" | awk '{print $1}')" == "$expected" ]] || fail "registered member content drift: $path"
done
[[ -d "$corpus_root" && ! -L "$corpus_root" ]] || fail "corpus root unavailable or unsafe"
[[ -d "$EXPORT_DIR" && ! -L "$EXPORT_DIR" ]] || fail "artifact directory unsafe"
[[ "$EXPORT_DIR" == /home/github-runner/_work/_temp/hermes-deals-netto-missing-normal-price-audit-* ]] || fail "artifact directory outside runner temp allowlist"
[[ "$(stat -c '%U:%G %a' "$EXPORT_DIR")" == 'github-runner:github-runner 700' ]] || fail "artifact directory metadata invalid"
RUN_KEY="$(basename -- "$EXPORT_DIR")"
STAGING_DIR="$STAGING_ROOT/$RUN_KEY"
[[ ! -e "$STAGING_DIR" ]] || fail "staging directory already exists"
install -d -o andris -g andris -m 0700 "$STAGING_DIR"
cleanup() { rm -rf -- "$STAGING_DIR"; }
trap cleanup EXIT
runuser -u andris -- /usr/bin/env -i HOME=/home/andris USER=andris LOGNAME=andris PATH=/usr/bin:/bin PYTHONDONTWRITEBYTECODE=1 \
  /usr/bin/python3 "$missing_tool" --n9-manifest "$n9_manifest" --corpus-root "$corpus_root" --n10-ledger "$n10_ledger" --output "$STAGING_DIR/missing-normal-price-audit.json"
/usr/bin/python3 - "$STAGING_DIR/missing-normal-price-audit.json" "$STAGING_DIR/audit-summary.json" <<'PY'
import json, sys
from pathlib import Path
src, dst = map(Path, sys.argv[1:])
p = json.loads(src.read_text(encoding='utf-8'))
assert p['strategy'] == 'netto_missing_normal_price_audit_v1'
assert p['cell_count'] == 100
assert p['review_only_default'] is True and p['promotion_ready'] is False
assert p['database_write_performed'] is False and p['deployment_performed'] is False
summary = {k: p[k] for k in ('strategy','geometry_parser_identity','source_archive_sha256','source_n9_fixture_manifest_sha256','source_n10_ledger_sha256','cell_count','diagnostic_cause_counts','missing_selected_normal_count','review_only_default','promotion_ready','automatic_approval_enabled','automatic_publish_enabled','database_write_performed','deployment_performed')}
dst.write_text(json.dumps(summary, indent=2, sort_keys=True) + '\n', encoding='utf-8')
PY
/usr/bin/python3 - "$STAGING_DIR" <<'PY'
import hashlib, json, sys
from pathlib import Path
root = Path(sys.argv[1])
files = {}
for path in sorted(root.iterdir()):
    if path.is_file(): files[path.name] = hashlib.sha256(path.read_bytes()).hexdigest()
(root / 'audit-artifact-manifest.json').write_text(json.dumps({'schema_version':1,'files':files}, indent=2, sort_keys=True) + '\n', encoding='utf-8')
PY
for file in "$STAGING_DIR"/*; do install -o github-runner -g github-runner -m 0600 "$file" "$EXPORT_DIR/$(basename -- "$file")"; done
DISPATCH
install -o root -g root -m 0755 "$TMP/dispatcher" "$DISPATCHER"
cat > "$TMP/sudoers" <<EOF
Cmnd_Alias HERMES_DEALS_NETTO_MISSING_NORMAL_PRICE_AUDIT = $DISPATCHER [0-9a-f][0-9a-f]* /home/github-runner/_work/_temp/hermes-deals-netto-missing-normal-price-audit-*
github-runner ALL=(root) NOPASSWD: HERMES_DEALS_NETTO_MISSING_NORMAL_PRICE_AUDIT
EOF
visudo -cf "$TMP/sudoers" >/dev/null
install -o root -g root -m 0440 "$TMP/sudoers" "$SUDOERS"
visudo -cf "$SUDOERS" >/dev/null
printf 'INSTALL_RESULT=PASS\nREGISTERED_SHA=%s\nPYMUPDF_VERSION=%s\n' "$EXPECTED_SHA" "$PYMUPDF_VERSION"
