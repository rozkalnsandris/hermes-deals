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

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "run with sudo"
[[ $# -eq 2 ]] || fail "usage: sudo bash tools/runner/install-netto-object-card-graph-rpi5-audit.sh <merged-main-sha> <clean-detached-source-worktree>"

EXPECTED_SHA="$1"
SOURCE_REPO="$(readlink -f -- "$2")"
EXPECTED_SOURCE_REPO='/home/andris/hermes-deals-worktrees/netto-object-card-graph-audit-v1'
PRIMARY_GIT_COMMON_DIR='/home/andris/hermes-deals/.git'
RUNTIME_ROOT='/usr/local/libexec/hermes-deals-audits/netto-object-card-graph-audit-v1'
OBJECT_GRAPH_TOOL="$RUNTIME_ROOT/tools/netto_object_card_graph_audit.py"
TOPOLOGY_TOOL="$RUNTIME_ROOT/tools/netto_card_region_topology_audit.py"
OWNERSHIP_AUDIT_TOOL="$RUNTIME_ROOT/tools/netto_ownership_separator_audit.py"
BASE_REPLAY_TOOL="$RUNTIME_ROOT/tools/netto_visual_geometry_corpus_replay.py"
PARSER_TOOL="$RUNTIME_ROOT/tools/netto_visual_geometry_shadow.py"
OWNERSHIP_TRUTH="$RUNTIME_ROOT/backend/tests/fixtures/netto/n2_independent_ownership_summary_v1.json"
DISPATCHER='/usr/local/sbin/hermes-deals-netto-object-card-graph-audit-dispatch'
SUDOERS='/etc/sudoers.d/hermes-deals-netto-object-card-graph-audit'
REGISTRY_DIR='/etc/hermes-deals-audits.d'
CONFIG="$REGISTRY_DIR/netto-object-card-graph-audit-v1.conf"
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'
N9_MANIFEST='/home/andris/hermes-deals-audits/netto-n9-visual-cell-validation-pack-v1-20260802T202304Z/generated/fixture-manifest.json'
CORPUS_ROOT='/home/andris/hermes-deals-netto-corpus/flyers'
EXPECTED_N9_SHA='2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147'

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "commit SHA is invalid"
[[ "$SOURCE_REPO" == "$EXPECTED_SOURCE_REPO" ]] || fail "source worktree must be $EXPECTED_SOURCE_REPO"

for user in github-runner andris; do
  id "$user" >/dev/null 2>&1 || fail "required local user is missing: $user"
done
for command in git grep id install mktemp python3 readlink runuser sha256sum stat sudo tr visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
if id -nG github-runner | tr ' ' '\n' | grep -Fxq docker; then
  fail "github-runner must not belong to the Docker group"
fi

git_source() {
  runuser -u andris -- /usr/bin/env -i \
    HOME=/home/andris USER=andris LOGNAME=andris \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    GIT_OPTIONAL_LOCKS=0 /usr/bin/git "$@"
}

[[ "$(git_source -C "$SOURCE_REPO" rev-parse --is-inside-work-tree 2>/dev/null)" == 'true' ]] || fail "source path is not a Git worktree"
[[ "$(git_source -C "$SOURCE_REPO" rev-parse HEAD)" == "$EXPECTED_SHA" ]] || fail "source worktree HEAD mismatch"
[[ -z "$(git_source -C "$SOURCE_REPO" branch --show-current)" ]] || fail "source worktree must be detached at the registered SHA"
[[ -z "$(git_source -C "$SOURCE_REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail "source worktree is not clean"

COMMON_DIR="$(git_source -C "$SOURCE_REPO" rev-parse --git-common-dir)"
case "$COMMON_DIR" in
  /*) COMMON_DIR="$(readlink -f -- "$COMMON_DIR")" ;;
  *) COMMON_DIR="$(readlink -f -- "$SOURCE_REPO/$COMMON_DIR")" ;;
esac
[[ "$COMMON_DIR" == "$PRIMARY_GIT_COMMON_DIR" ]] || fail "source is not a worktree of /home/andris/hermes-deals"

REMOTE="$(git_source -C "$SOURCE_REPO" remote get-url origin)"
case "$REMOTE" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail "source origin is not the Hermes Deals repository" ;;
esac
git_source -C "$SOURCE_REPO" show-ref --verify --quiet refs/remotes/origin/main || fail "origin/main is unavailable"
git_source -C "$SOURCE_REPO" merge-base --is-ancestor "$EXPECTED_SHA" refs/remotes/origin/main || fail "registered SHA is not reachable from origin/main"

SOURCE_OBJECT_GRAPH_TOOL="$SOURCE_REPO/tools/netto_object_card_graph_audit.py"
SOURCE_TOPOLOGY_TOOL="$SOURCE_REPO/tools/netto_card_region_topology_audit.py"
SOURCE_OWNERSHIP_AUDIT_TOOL="$SOURCE_REPO/tools/netto_ownership_separator_audit.py"
SOURCE_BASE_REPLAY_TOOL="$SOURCE_REPO/tools/netto_visual_geometry_corpus_replay.py"
SOURCE_PARSER_TOOL="$SOURCE_REPO/tools/netto_visual_geometry_shadow.py"
SOURCE_OWNERSHIP_TRUTH="$SOURCE_REPO/backend/tests/fixtures/netto/n2_independent_ownership_summary_v1.json"

for relative in \
  tools/netto_object_card_graph_audit.py \
  tools/netto_card_region_topology_audit.py \
  tools/netto_ownership_separator_audit.py \
  tools/netto_visual_geometry_corpus_replay.py \
  tools/netto_visual_geometry_shadow.py \
  backend/tests/fixtures/netto/n2_independent_ownership_summary_v1.json \
  tools/runner/install-netto-object-card-graph-rpi5-audit.sh; do
  git_source -C "$SOURCE_REPO" ls-files --error-unmatch "$relative" >/dev/null || fail "required source is not tracked: $relative"
done

for source in \
  "$SOURCE_OBJECT_GRAPH_TOOL" \
  "$SOURCE_TOPOLOGY_TOOL" \
  "$SOURCE_OWNERSHIP_AUDIT_TOOL" \
  "$SOURCE_BASE_REPLAY_TOOL" \
  "$SOURCE_PARSER_TOOL" \
  "$SOURCE_OWNERSHIP_TRUTH"; do
  [[ -f "$source" && ! -L "$source" ]] || fail "required source is missing or unsafe: $source"
done

/usr/bin/python3 - \
  "$SOURCE_OBJECT_GRAPH_TOOL" \
  "$SOURCE_TOPOLOGY_TOOL" \
  "$SOURCE_OWNERSHIP_AUDIT_TOOL" \
  "$SOURCE_BASE_REPLAY_TOOL" \
  "$SOURCE_PARSER_TOOL" <<'PY'
from pathlib import Path
import sys
for value in sys.argv[1:]:
    path = Path(value)
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
PY

PYMUPDF_VERSION="$(
  runuser -u andris -- /usr/bin/env -i \
    HOME=/home/andris USER=andris LOGNAME=andris \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 - <<'PY'
import pymupdf
print(pymupdf.pymupdf_version)
PY
)"
[[ "$PYMUPDF_VERSION" == '1.28.0' ]] || fail "PyMuPDF 1.28.0 required, found $PYMUPDF_VERSION"
[[ -f "$N9_MANIFEST" && ! -L "$N9_MANIFEST" ]] || fail "N9 manifest is unavailable or unsafe"
[[ "$(sha256sum "$N9_MANIFEST" | awk '{print $1}')" == "$EXPECTED_N9_SHA" ]] || fail "N9 manifest SHA256 mismatch"
[[ -d "$CORPUS_ROOT" && ! -L "$CORPUS_ROOT" ]] || fail "immutable Netto corpus root is unavailable or unsafe"

TMPDIR_INSTALL="$(mktemp -d /tmp/hermes-deals-netto-object-card-graph-installer.XXXXXX)"
cleanup() { rm -rf -- "$TMPDIR_INSTALL"; }
trap cleanup EXIT

install -d -o root -g root -m 0755 \
  "$RUNTIME_ROOT" "$RUNTIME_ROOT/tools" "$RUNTIME_ROOT/backend" \
  "$RUNTIME_ROOT/backend/tests" "$RUNTIME_ROOT/backend/tests/fixtures" \
  "$RUNTIME_ROOT/backend/tests/fixtures/netto" "$REGISTRY_DIR"
install -d -o andris -g andris -m 0700 "$STAGING_ROOT"

install -o root -g root -m 0644 "$SOURCE_OBJECT_GRAPH_TOOL" "$OBJECT_GRAPH_TOOL"
install -o root -g root -m 0644 "$SOURCE_TOPOLOGY_TOOL" "$TOPOLOGY_TOOL"
install -o root -g root -m 0644 "$SOURCE_OWNERSHIP_AUDIT_TOOL" "$OWNERSHIP_AUDIT_TOOL"
install -o root -g root -m 0644 "$SOURCE_BASE_REPLAY_TOOL" "$BASE_REPLAY_TOOL"
install -o root -g root -m 0644 "$SOURCE_PARSER_TOOL" "$PARSER_TOOL"
install -o root -g root -m 0644 "$SOURCE_OWNERSHIP_TRUTH" "$OWNERSHIP_TRUTH"

OBJECT_GRAPH_SHA="$(sha256sum "$OBJECT_GRAPH_TOOL" | awk '{print $1}')"
TOPOLOGY_SHA="$(sha256sum "$TOPOLOGY_TOOL" | awk '{print $1}')"
OWNERSHIP_AUDIT_SHA="$(sha256sum "$OWNERSHIP_AUDIT_TOOL" | awk '{print $1}')"
BASE_REPLAY_SHA="$(sha256sum "$BASE_REPLAY_TOOL" | awk '{print $1}')"
PARSER_SHA="$(sha256sum "$PARSER_TOOL" | awk '{print $1}')"
OWNERSHIP_TRUTH_SHA="$(sha256sum "$OWNERSHIP_TRUTH" | awk '{print $1}')"

cat > "$TMPDIR_INSTALL/config" <<EOF_CONFIG
audit_name='netto-object-card-graph-audit-v1'
commit_sha='$EXPECTED_SHA'
runtime_root='$RUNTIME_ROOT'
object_graph_tool_path='$OBJECT_GRAPH_TOOL'
object_graph_tool_sha256='$OBJECT_GRAPH_SHA'
topology_tool_path='$TOPOLOGY_TOOL'
topology_tool_sha256='$TOPOLOGY_SHA'
ownership_audit_tool_path='$OWNERSHIP_AUDIT_TOOL'
ownership_audit_tool_sha256='$OWNERSHIP_AUDIT_SHA'
base_replay_tool_path='$BASE_REPLAY_TOOL'
base_replay_tool_sha256='$BASE_REPLAY_SHA'
parser_tool_path='$PARSER_TOOL'
parser_tool_sha256='$PARSER_SHA'
ownership_truth_path='$OWNERSHIP_TRUTH'
ownership_truth_sha256='$OWNERSHIP_TRUTH_SHA'
n9_manifest='$N9_MANIFEST'
n9_manifest_sha256='$EXPECTED_N9_SHA'
corpus_root='$CORPUS_ROOT'
EOF_CONFIG
install -o root -g root -m 0644 "$TMPDIR_INSTALL/config" "$CONFIG"

cat > "$TMPDIR_INSTALL/dispatcher" <<'DISPATCH'
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

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "dispatcher must run as root through sudo"
[[ $# -eq 2 ]] || fail "usage: hermes-deals-netto-object-card-graph-audit-dispatch <registered-commit-sha> <artifact-dir>"
EXPECTED_SHA="$1"
EXPORT_DIR="$2"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "requested commit SHA is invalid"

CONFIG='/etc/hermes-deals-audits.d/netto-object-card-graph-audit-v1.conf'
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'
[[ -f "$CONFIG" && ! -L "$CONFIG" ]] || fail "object-card graph audit is not registered"
[[ "$(stat -c '%U:%G' "$CONFIG")" == 'root:root' ]] || fail "audit config ownership is invalid"
[[ "$(stat -c '%a' "$CONFIG")" == '644' ]] || fail "audit config permissions are invalid"

# shellcheck disable=SC1090
source "$CONFIG"

[[ "${audit_name:-}" == 'netto-object-card-graph-audit-v1' ]] || fail "audit config name mismatch"
[[ "${commit_sha:-}" == "$EXPECTED_SHA" ]] || fail "requested commit is not the registered audit commit"
[[ "${runtime_root:-}" == '/usr/local/libexec/hermes-deals-audits/netto-object-card-graph-audit-v1' ]] || fail "runtime root mismatch"
[[ "${n9_manifest:-}" == '/home/andris/hermes-deals-audits/netto-n9-visual-cell-validation-pack-v1-20260802T202304Z/generated/fixture-manifest.json' ]] || fail "N9 path drift"
[[ "${corpus_root:-}" == '/home/andris/hermes-deals-netto-corpus/flyers' ]] || fail "corpus root drift"

for pair in \
  "$object_graph_tool_path:$object_graph_tool_sha256" \
  "$topology_tool_path:$topology_tool_sha256" \
  "$ownership_audit_tool_path:$ownership_audit_tool_sha256" \
  "$base_replay_tool_path:$base_replay_tool_sha256" \
  "$parser_tool_path:$parser_tool_sha256" \
  "$ownership_truth_path:$ownership_truth_sha256" \
  "$n9_manifest:$n9_manifest_sha256"; do
  path="${pair%%:*}"
  expected_hash="${pair#*:}"
  [[ "$expected_hash" =~ ^[0-9a-f]{64}$ ]] || fail "registered SHA256 is invalid"
  [[ -f "$path" && ! -L "$path" ]] || fail "registered member is missing or unsafe: $path"
  [[ "$(stat -c '%U:%G' "$path")" == 'root:root' || "$path" == "$n9_manifest" ]] || fail "registered member ownership drift: $path"
  [[ "$(sha256sum "$path" | awk '{print $1}')" == "$expected_hash" ]] || fail "registered member content drift: $path"
done
[[ -d "$corpus_root" && ! -L "$corpus_root" ]] || fail "immutable corpus root is unavailable or unsafe"

PYMUPDF_VERSION="$(
  runuser -u andris -- /usr/bin/env -i \
    HOME=/home/andris USER=andris LOGNAME=andris \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    PYTHONDONTWRITEBYTECODE=1 /usr/bin/python3 - <<'PY'
import pymupdf
print(pymupdf.pymupdf_version)
PY
)"
[[ "$PYMUPDF_VERSION" == '1.28.0' ]] || fail "PyMuPDF version drift"

EXPORT_DIR="$(readlink -f -- "$EXPORT_DIR")"
[[ -d "$EXPORT_DIR" && ! -L "$EXPORT_DIR" ]] || fail "artifact directory does not exist or is unsafe"
[[ "$EXPORT_DIR" == /home/github-runner/_work/_temp/hermes-deals-netto-object-card-graph-audit-* ]] || fail "artifact directory is outside runner temp allowlist"
[[ "$(stat -c '%U:%G' "$EXPORT_DIR")" == 'github-runner:github-runner' ]] || fail "artifact directory ownership is invalid"
[[ "$(stat -c '%a' "$EXPORT_DIR")" == '700' ]] || fail "artifact directory permissions must be 0700"

RUN_KEY="$(basename -- "$EXPORT_DIR")"
[[ "$RUN_KEY" =~ ^hermes-deals-netto-object-card-graph-audit-[0-9]+-[0-9]+$ ]] || fail "artifact directory name is invalid"
STAGING_DIR="$STAGING_ROOT/$RUN_KEY"
[[ ! -e "$STAGING_DIR" ]] || fail "staging directory already exists"
install -d -o andris -g andris -m 0700 "$STAGING_DIR"

LOG_FILE="$STAGING_ROOT/.${RUN_KEY}.audit-execution.log"
[[ ! -e "$LOG_FILE" ]] || fail "audit execution log already exists"
install -o root -g root -m 0600 /dev/null "$LOG_FILE"

cleanup() {
  rm -rf -- "$STAGING_DIR"
  rm -f -- "$LOG_FILE"
}
trap cleanup EXIT

set +e
runuser -u andris -- /usr/bin/env -i \
  HOME=/home/andris USER=andris LOGNAME=andris SHELL=/bin/bash \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 TZ=Europe/Berlin PYTHONDONTWRITEBYTECODE=1 \
  /usr/bin/python3 "$object_graph_tool_path" \
    --n9-manifest "$n9_manifest" \
    --corpus-root "$corpus_root" \
    --ownership-truth "$ownership_truth_path" \
    --output "$STAGING_DIR/object-card-graph-audit.json" \
    > "$LOG_FILE" 2>&1
AUDIT_RC=$?
set -e

install -o andris -g andris -m 0600 "$LOG_FILE" "$STAGING_DIR/audit-execution.log"
rm -f -- "$LOG_FILE"
printf '%s\n' "$AUDIT_RC" > "$STAGING_DIR/audit-exit-code.txt"
chown andris:andris "$STAGING_DIR/audit-exit-code.txt"
chmod 0600 "$STAGING_DIR/audit-exit-code.txt"

if [[ $AUDIT_RC -eq 0 ]]; then
  /usr/bin/python3 - "$STAGING_DIR/object-card-graph-audit.json" <<'PY'
import json
from pathlib import Path
import sys

payload = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
checks = {
    "cell_count": payload.get("cell_count") == 100,
    "image_binary_retained": payload.get("image_binary_retained") is False,
    "ocr_used": payload.get("ocr_used") is False,
    "classification_performed": payload.get("classification_performed") is False,
    "parser_behavior_changed": payload.get("parser_behavior_changed") is False,
    "review_only": payload.get("review_only") is True,
    "promotion_ready": payload.get("promotion_ready") is False,
    "automatic_approval_enabled": payload.get("automatic_approval_enabled") is False,
    "automatic_publish_enabled": payload.get("automatic_publish_enabled") is False,
    "database_write_performed": payload.get("database_write_performed") is False,
    "deployment_performed": payload.get("deployment_performed") is False,
}
failed = [name for name, passed in checks.items() if not passed]
if failed:
    raise SystemExit(f"object-card graph safety contract violated: {failed}")
PY
fi

/usr/bin/python3 - \
  "$STAGING_DIR/runtime-identity.json" \
  "$EXPECTED_SHA" \
  "$object_graph_tool_sha256" \
  "$topology_tool_sha256" \
  "$ownership_audit_tool_sha256" \
  "$base_replay_tool_sha256" \
  "$parser_tool_sha256" \
  "$ownership_truth_sha256" \
  "$n9_manifest_sha256" \
  "$PYMUPDF_VERSION" <<'PY'
import json
from pathlib import Path
import sys

Path(sys.argv[1]).write_text(
    json.dumps(
        {
            "audit": "netto-object-card-graph-audit-v1",
            "commit_sha": sys.argv[2],
            "object_graph_tool_sha256": sys.argv[3],
            "topology_tool_sha256": sys.argv[4],
            "ownership_audit_tool_sha256": sys.argv[5],
            "base_replay_tool_sha256": sys.argv[6],
            "parser_tool_sha256": sys.argv[7],
            "ownership_truth_sha256": sys.argv[8],
            "n9_manifest_sha256": sys.argv[9],
            "pymupdf_version": sys.argv[10],
            "production_deploy": False,
            "database_write": False,
            "review_write": False,
            "approval_publish": False,
            "ocr_used": False,
            "image_binary_retained": False,
        },
        sort_keys=True,
        indent=2,
    )
    + "\n",
    encoding="utf-8",
)
PY
chown andris:andris "$STAGING_DIR/runtime-identity.json"
chmod 0600 "$STAGING_DIR/runtime-identity.json"

install -d -o github-runner -g github-runner -m 0700 "$EXPORT_DIR/audit-evidence"
for name in audit-execution.log audit-exit-code.txt runtime-identity.json; do
  install -o github-runner -g github-runner -m 0600 \
    "$STAGING_DIR/$name" "$EXPORT_DIR/audit-evidence/$name"
done
if [[ -f "$STAGING_DIR/object-card-graph-audit.json" ]]; then
  install -o github-runner -g github-runner -m 0600 \
    "$STAGING_DIR/object-card-graph-audit.json" \
    "$EXPORT_DIR/audit-evidence/object-card-graph-audit.json"
fi

(
  cd "$EXPORT_DIR/audit-evidence"
  sha256sum ./* > manifest.sha256
)
chown github-runner:github-runner "$EXPORT_DIR/audit-evidence/manifest.sha256"
chmod 0600 "$EXPORT_DIR/audit-evidence/manifest.sha256"

exit "$AUDIT_RC"
DISPATCH

install -o root -g root -m 0755 "$TMPDIR_INSTALL/dispatcher" "$DISPATCHER"

cat > "$TMPDIR_INSTALL/sudoers" <<EOF_SUDOERS
github-runner ALL=(root) NOPASSWD: $DISPATCHER
EOF_SUDOERS
chmod 0440 "$TMPDIR_INSTALL/sudoers"
visudo -cf "$TMPDIR_INSTALL/sudoers" >/dev/null
install -o root -g root -m 0440 "$TMPDIR_INSTALL/sudoers" "$SUDOERS"
visudo -cf "$SUDOERS" >/dev/null

echo "INSTALL_RESULT=PASS"
echo "REGISTERED_SHA=$EXPECTED_SHA"
echo "PYMUPDF_VERSION=$PYMUPDF_VERSION"
echo "N9_MANIFEST_SHA256=$EXPECTED_N9_SHA"
echo "RUNNER_HAS_DOCKER_GROUP=false"
echo "AUDIT_EXECUTED=false"
echo "DATABASE_WRITE=false"
echo "REVIEW_WRITE=false"
echo "APPROVAL_PUBLICATION=false"
echo "PRODUCTION_DEPLOY=false"
