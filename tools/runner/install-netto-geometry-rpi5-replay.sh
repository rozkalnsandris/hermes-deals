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
[[ $# -eq 2 ]] || fail "usage: sudo bash tools/runner/install-netto-geometry-rpi5-replay.sh <merged-main-sha> <clean-detached-source-worktree>"
EXPECTED_SHA="$1"
SOURCE_REPO="$(readlink -f -- "$2")"
EXPECTED_SOURCE_REPO='/home/andris/hermes-deals-worktrees/netto-geometry-replay-v1'
PRIMARY_GIT_COMMON_DIR='/home/andris/hermes-deals/.git'
RUNNER_SERVICE='actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service'
RUNTIME_ROOT='/usr/local/libexec/hermes-deals-audits/netto-geometry-replay-v1'
INSTALLED_RUNNER="$RUNTIME_ROOT/run.sh"
INSTALLED_REPLAY_TOOL="$RUNTIME_ROOT/tools/netto_visual_geometry_corpus_replay.py"
INSTALLED_PARSER_TOOL="$RUNTIME_ROOT/tools/netto_visual_geometry_shadow.py"
INSTALLED_N10="$RUNTIME_ROOT/backend/tests/fixtures/netto/n10_full_visual_review_v1.json"
DISPATCHER='/usr/local/sbin/hermes-deals-netto-geometry-replay-dispatch'
SUDOERS='/etc/sudoers.d/hermes-deals-netto-geometry-replay'
REGISTRY_DIR='/etc/hermes-deals-audits.d'
CONFIG="$REGISTRY_DIR/netto-geometry-replay-v1.conf"
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "commit SHA is invalid"
[[ "$SOURCE_REPO" == "$EXPECTED_SOURCE_REPO" ]] || fail "source worktree must be $EXPECTED_SOURCE_REPO"

for user in github-runner andris; do
  id "$user" >/dev/null 2>&1 || fail "required local user is missing: $user"
done
for command in git install python3 readlink runuser sha256sum stat sudo systemctl visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
if id -nG github-runner | tr ' ' '\n' | grep -Fxq docker; then
  fail "github-runner must not belong to the Docker group"
fi

[[ "$(git -C "$SOURCE_REPO" rev-parse --is-inside-work-tree 2>/dev/null)" == 'true' ]] || fail "source path is not a Git worktree"
[[ "$(git -C "$SOURCE_REPO" rev-parse HEAD)" == "$EXPECTED_SHA" ]] || fail "source worktree HEAD mismatch"
[[ -z "$(git -C "$SOURCE_REPO" branch --show-current)" ]] || fail "source worktree must be detached at the registered SHA"
[[ -z "$(git -C "$SOURCE_REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail "source worktree is not clean"

COMMON_DIR="$(git -C "$SOURCE_REPO" rev-parse --git-common-dir)"
case "$COMMON_DIR" in
  /*) COMMON_DIR="$(readlink -f -- "$COMMON_DIR")" ;;
  *) COMMON_DIR="$(readlink -f -- "$SOURCE_REPO/$COMMON_DIR")" ;;
esac
[[ "$COMMON_DIR" == "$PRIMARY_GIT_COMMON_DIR" ]] || fail "source is not a worktree of /home/andris/hermes-deals"

REMOTE="$(git -C "$SOURCE_REPO" remote get-url origin)"
case "$REMOTE" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail "source origin is not the Hermes Deals repository" ;;
esac
git -C "$SOURCE_REPO" show-ref --verify --quiet refs/remotes/origin/main || fail "origin/main is unavailable in source worktree"
git -C "$SOURCE_REPO" merge-base --is-ancestor "$EXPECTED_SHA" refs/remotes/origin/main || fail "registered SHA is not reachable from fetched origin/main"

SOURCE_RUNNER="$SOURCE_REPO/tools/run-hermes-deals-netto-geometry-replay-v01.sh"
SOURCE_REPLAY_TOOL="$SOURCE_REPO/tools/netto_visual_geometry_corpus_replay.py"
SOURCE_PARSER_TOOL="$SOURCE_REPO/tools/netto_visual_geometry_shadow.py"
SOURCE_N10="$SOURCE_REPO/backend/tests/fixtures/netto/n10_full_visual_review_v1.json"

for relative in \
  tools/run-hermes-deals-netto-geometry-replay-v01.sh \
  tools/netto_visual_geometry_corpus_replay.py \
  tools/netto_visual_geometry_shadow.py \
  backend/tests/fixtures/netto/n10_full_visual_review_v1.json \
  tools/runner/install-netto-geometry-rpi5-replay.sh; do
  git -C "$SOURCE_REPO" ls-files --error-unmatch "$relative" >/dev/null || fail "required source is not tracked: $relative"
done
for source in "$SOURCE_RUNNER" "$SOURCE_REPLAY_TOOL" "$SOURCE_PARSER_TOOL" "$SOURCE_N10"; do
  [[ -f "$source" && ! -L "$source" ]] || fail "required source is missing or unsafe: $source"
done

/bin/bash -n "$SOURCE_RUNNER"
/usr/bin/python3 - "$SOURCE_REPLAY_TOOL" "$SOURCE_PARSER_TOOL" <<'PY'
from pathlib import Path
import sys
for value in sys.argv[1:]:
    path = Path(value)
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
PY
# PyMuPDF belongs to the unprivileged replay runtime. Validate the exact
# interpreter as the exact OS user that will execute the workload; root's
# Python environment is intentionally irrelevant here.
runuser -u andris -- /usr/bin/env -i \
  HOME=/home/andris \
  USER=andris \
  LOGNAME=andris \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  PYTHONDONTWRITEBYTECODE=1 \
  /usr/bin/python3 - <<'PY'
import importlib.metadata
import pymupdf
version = importlib.metadata.version("PyMuPDF")
if version != "1.28.0":
    raise SystemExit(f"PyMuPDF 1.28.0 required, found {version}")
PY

N10_SHA="$(sha256sum "$SOURCE_N10" | awk '{print $1}')"
[[ "$N10_SHA" == 'bf35bff323d76a2b29a7248df067641e5b9f2a7d29329cf53bf9fc0ae832734a' ]] || fail "N10 ledger SHA256 mismatch"

TMPDIR_INSTALL="$(mktemp -d /tmp/hermes-deals-netto-geometry-replay-installer.XXXXXX)"
cleanup() {
  rm -rf -- "$TMPDIR_INSTALL"
}
trap cleanup EXIT

install -d -o root -g root -m 0755 \
  "$RUNTIME_ROOT" \
  "$RUNTIME_ROOT/tools" \
  "$RUNTIME_ROOT/backend" \
  "$RUNTIME_ROOT/backend/tests" \
  "$RUNTIME_ROOT/backend/tests/fixtures" \
  "$RUNTIME_ROOT/backend/tests/fixtures/netto" \
  "$REGISTRY_DIR"
install -d -o andris -g andris -m 0700 "$STAGING_ROOT"

install -o root -g root -m 0755 "$SOURCE_RUNNER" "$INSTALLED_RUNNER"
install -o root -g root -m 0644 "$SOURCE_REPLAY_TOOL" "$INSTALLED_REPLAY_TOOL"
install -o root -g root -m 0644 "$SOURCE_PARSER_TOOL" "$INSTALLED_PARSER_TOOL"
install -o root -g root -m 0644 "$SOURCE_N10" "$INSTALLED_N10"

RUNNER_SHA="$(sha256sum "$INSTALLED_RUNNER" | awk '{print $1}')"
REPLAY_TOOL_SHA="$(sha256sum "$INSTALLED_REPLAY_TOOL" | awk '{print $1}')"
PARSER_TOOL_SHA="$(sha256sum "$INSTALLED_PARSER_TOOL" | awk '{print $1}')"
INSTALLED_N10_SHA="$(sha256sum "$INSTALLED_N10" | awk '{print $1}')"
[[ "$INSTALLED_N10_SHA" == "$N10_SHA" ]] || fail "installed N10 content drift"

cat > "$TMPDIR_INSTALL/config" <<EOF
audit_name='netto-geometry-replay-v1'
commit_sha='$EXPECTED_SHA'
runtime_root='$RUNTIME_ROOT'
runner_path='$INSTALLED_RUNNER'
runner_sha256='$RUNNER_SHA'
replay_tool_path='$INSTALLED_REPLAY_TOOL'
replay_tool_sha256='$REPLAY_TOOL_SHA'
parser_tool_path='$INSTALLED_PARSER_TOOL'
parser_tool_sha256='$PARSER_TOOL_SHA'
n10_path='$INSTALLED_N10'
n10_sha256='$INSTALLED_N10_SHA'
source_repo='$SOURCE_REPO'
EOF
install -o root -g root -m 0644 "$TMPDIR_INSTALL/config" "$CONFIG"

cat > "$TMPDIR_INSTALL/dispatcher" <<'DISPATCH'
#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() { echo "ERROR: $*" >&2; exit 1; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "dispatcher must run as root through sudo"
[[ $# -eq 2 ]] || fail "usage: hermes-deals-netto-geometry-replay-dispatch <registered-commit-sha> <artifact-dir>"
EXPECTED_SHA="$1"
EXPORT_DIR="$2"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "requested commit SHA is invalid"

CONFIG='/etc/hermes-deals-audits.d/netto-geometry-replay-v1.conf'
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'
[[ -f "$CONFIG" && ! -L "$CONFIG" ]] || fail "Netto geometry replay is not registered"
[[ "$(stat -c '%U:%G' "$CONFIG")" == 'root:root' ]] || fail "replay config ownership is invalid"
[[ "$(stat -c '%a' "$CONFIG")" =~ ^(600|640|644)$ ]] || fail "replay config permissions are invalid"
# shellcheck disable=SC1090
source "$CONFIG"

[[ "${audit_name:-}" == 'netto-geometry-replay-v1' ]] || fail "replay config name mismatch"
[[ "${commit_sha:-}" == "$EXPECTED_SHA" ]] || fail "requested commit is not the registered replay commit"
[[ "${runtime_root:-}" == '/usr/local/libexec/hermes-deals-audits/netto-geometry-replay-v1' ]] || fail "registered runtime root is invalid"
[[ "${runner_path:-}" == "$runtime_root/run.sh" ]] || fail "registered runner path is invalid"
[[ "${replay_tool_path:-}" == "$runtime_root/tools/netto_visual_geometry_corpus_replay.py" ]] || fail "registered replay tool path is invalid"
[[ "${parser_tool_path:-}" == "$runtime_root/tools/netto_visual_geometry_shadow.py" ]] || fail "registered parser tool path is invalid"
[[ "${n10_path:-}" == "$runtime_root/backend/tests/fixtures/netto/n10_full_visual_review_v1.json" ]] || fail "registered N10 path is invalid"

for pair in \
  "$runner_path:$runner_sha256" \
  "$replay_tool_path:$replay_tool_sha256" \
  "$parser_tool_path:$parser_tool_sha256" \
  "$n10_path:$n10_sha256"; do
  path="${pair%%:*}"
  expected_hash="${pair#*:}"
  [[ "$expected_hash" =~ ^[0-9a-f]{64}$ ]] || fail "registered runtime SHA is invalid"
  [[ -f "$path" && ! -L "$path" ]] || fail "registered runtime member is missing or unsafe: $path"
  [[ "$(stat -c '%U:%G' "$path")" == 'root:root' ]] || fail "registered runtime member ownership is invalid: $path"
  [[ "$(sha256sum "$path" | awk '{print $1}')" == "$expected_hash" ]] || fail "registered runtime member content drift: $path"
done

# The dispatcher is root-owned, but the PDF workload is not. Dependency
# validation must therefore run as andris with the same clean runtime identity
# used below for the replay itself.
runuser -u andris -- /usr/bin/env -i \
  HOME=/home/andris \
  USER=andris \
  LOGNAME=andris \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  PYTHONDONTWRITEBYTECODE=1 \
  /usr/bin/python3 - <<'PY'
import importlib.metadata
import pymupdf
version = importlib.metadata.version("PyMuPDF")
if version != "1.28.0":
    raise SystemExit(f"PyMuPDF 1.28.0 required, found {version}")
PY

EXPORT_DIR="$(readlink -f -- "$EXPORT_DIR")"
[[ -d "$EXPORT_DIR" && ! -L "$EXPORT_DIR" ]] || fail "artifact directory does not exist or is unsafe"
[[ "$EXPORT_DIR" == /home/github-runner/_work/_temp/hermes-deals-netto-geometry-replay-* ]] || fail "artifact directory is outside runner temp allowlist"
[[ "$(stat -c '%U:%G' "$EXPORT_DIR")" == 'github-runner:github-runner' ]] || fail "artifact directory ownership is invalid"
[[ "$(stat -c '%a' "$EXPORT_DIR")" == '700' ]] || fail "artifact directory permissions must be 0700"
RUN_KEY="$(basename -- "$EXPORT_DIR")"
[[ "$RUN_KEY" =~ ^hermes-deals-netto-geometry-replay-[0-9]+-[0-9]+$ ]] || fail "artifact directory name is invalid"

STAGING_DIR="$STAGING_ROOT/$RUN_KEY"
[[ ! -e "$STAGING_DIR" ]] || fail "staging directory already exists"
install -d -o andris -g andris -m 0700 "$STAGING_DIR"
LOG_FILE="$STAGING_ROOT/.${RUN_KEY}.replay-execution.log"
[[ ! -e "$LOG_FILE" ]] || fail "replay execution log already exists"
install -o root -g root -m 0600 /dev/null "$LOG_FILE"

cleanup() {
  rm -rf -- "$STAGING_DIR"
  rm -f -- "$LOG_FILE"
}
trap cleanup EXIT

set +e
runuser -u andris -- /usr/bin/env -i \
  HOME=/home/andris \
  USER=andris \
  LOGNAME=andris \
  SHELL=/bin/bash \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 \
  TZ=Europe/Berlin \
  HERMES_NETTO_GEOMETRY_REPLAY_TRIGGER=github-actions \
  HERMES_NETTO_GEOMETRY_REPLAY_EXPECTED_HEAD="$EXPECTED_SHA" \
  HERMES_NETTO_GEOMETRY_REPLAY_EXPORT_DIR="$STAGING_DIR" \
  HERMES_NETTO_GEOMETRY_REPLAY_RUNTIME_ROOT="$runtime_root" \
  /bin/bash --noprofile --norc "$runner_path" \
  > "$LOG_FILE" 2>&1
REPLAY_RC=$?
set -e

install -o andris -g andris -m 0600 "$LOG_FILE" "$STAGING_DIR/replay-execution.log"
rm -f -- "$LOG_FILE"
printf '%s\n' "$REPLAY_RC" > "$STAGING_DIR/replay-exit-code.txt"
chown andris:andris "$STAGING_DIR/replay-exit-code.txt"
chmod 0600 "$STAGING_DIR/replay-exit-code.txt"

python3 - "$STAGING_DIR" "$EXPORT_DIR/audit-evidence" "$EXPECTED_SHA" "$REPLAY_RC" <<'PY'
import hashlib
import json
import os
import pathlib
import re
import stat
import sys

source = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
commit_sha = sys.argv[3]
replay_rc = int(sys.argv[4])
allowed = {
    "netto-geometry-corpus-replay.json",
    "replay-execution.log",
    "replay-exit-code.txt",
    "runtime-identity.json",
}
required = {"replay-execution.log", "replay-exit-code.txt"}
secret = re.compile(
    rb"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}|PGPASSWORD=|postgresql(?:\+[^:]+)?://[^\s:/]+:[^\s@]+@)",
    re.IGNORECASE,
)

members = {}
for path in sorted(source.iterdir()):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise SystemExit(f"unsafe replay output member: {path.name}")
    if path.name not in allowed:
        raise SystemExit(f"unexpected replay output member: {path.name}")
    if info.st_size > 32 * 1024 * 1024:
        raise SystemExit(f"replay output member exceeds 32 MiB: {path.name}")
    data = path.read_bytes()
    if secret.search(data):
        raise SystemExit(f"sensitive content rejected: {path.name}")
    members[path.name] = data
if not required.issubset(members):
    raise SystemExit("replay did not produce required execution evidence")
if replay_rc == 0 and {"netto-geometry-corpus-replay.json", "runtime-identity.json"} - members.keys():
    raise SystemExit("successful replay is missing result or runtime identity")

destination.mkdir(mode=0o700, parents=False, exist_ok=False)
manifest = []
for name, data in sorted(members.items()):
    target = destination / name
    target.write_bytes(data)
    os.chmod(target, 0o600)
    manifest.append({"path": name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()})

(destination / "dispatcher-evidence-manifest.json").write_text(
    json.dumps(
        {
            "audit": "netto-geometry-replay-v1",
            "replay_exit_code": replay_rc,
            "commit_sha": commit_sha,
            "files": manifest,
            "production_apply_authorized": False,
            "database_write_performed": False,
            "review_write_performed": False,
            "deployment_performed": False,
            "promotion_ready": False,
            "sanitization_passed": True,
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
os.chmod(destination / "dispatcher-evidence-manifest.json", 0o600)
PY

chown -R github-runner:github-runner "$EXPORT_DIR/audit-evidence"
printf 'AUDIT=netto-geometry-replay-v1\nREGISTERED_COMMIT=%s\nREPLAY_EXIT_CODE=%s\nPRODUCTION_APPLY_AUTHORIZED=false\n' "$EXPECTED_SHA" "$REPLAY_RC"
exit "$REPLAY_RC"
DISPATCH

cat > "$TMPDIR_INSTALL/sudoers" <<'SUDOERS'
Defaults!/usr/local/sbin/hermes-deals-netto-geometry-replay-dispatch env_reset,secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-netto-geometry-replay-dispatch
SUDOERS

chmod 0755 "$TMPDIR_INSTALL/dispatcher"
install -o root -g root -m 0755 "$TMPDIR_INSTALL/dispatcher" "$DISPATCHER"
chmod 0440 "$TMPDIR_INSTALL/sudoers"
visudo -cf "$TMPDIR_INSTALL/sudoers" >/dev/null
install -o root -g root -m 0440 "$TMPDIR_INSTALL/sudoers" "$SUDOERS"
visudo -cf "$SUDOERS" >/dev/null

systemctl is-active --quiet "$RUNNER_SERVICE" || fail "GitHub Actions audit runner service is not active"
sudo -l -U github-runner | grep -Fq "$DISPATCHER" || fail "dedicated geometry replay dispatcher sudo rule was not installed"

printf 'INSTALL_RESULT=PASS\nAUDIT=netto-geometry-replay-v1\nCOMMIT_SHA=%s\nSOURCE_REPO=%s\nRUNNER_SHA256=%s\nREPLAY_TOOL_SHA256=%s\nPARSER_TOOL_SHA256=%s\nN10_SHA256=%s\nDISPATCHER_SHA256=%s\nPYMUPDF_VERSION=1.28.0\nPYMUPDF_RUNTIME_USER=andris\nPYMUPDF_PYTHON=/usr/bin/python3\nRUNNER_HAS_DOCKER_GROUP=false\nPRODUCTION_APPLY_AUTHORIZED=false\n' \
  "$EXPECTED_SHA" \
  "$SOURCE_REPO" \
  "$RUNNER_SHA" \
  "$REPLAY_TOOL_SHA" \
  "$PARSER_TOOL_SHA" \
  "$INSTALLED_N10_SHA" \
  "$(sha256sum "$DISPATCHER" | awk '{print $1}')"
