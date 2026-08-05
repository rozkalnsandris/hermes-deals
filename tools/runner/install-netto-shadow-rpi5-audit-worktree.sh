#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "run with sudo"
[[ $# -eq 2 ]] || fail "usage: sudo bash tools/runner/install-netto-shadow-rpi5-audit-worktree.sh <main-commit-sha> <clean-source-worktree>"
EXPECTED_SHA="$1"
SOURCE_REPO="$(readlink -f -- "$2")"
EXPECTED_SOURCE_REPO='/home/andris/hermes-deals-worktrees/netto-shadow-audit-install'
PRIMARY_GIT_COMMON_DIR='/home/andris/hermes-deals/.git'

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "commit SHA is invalid"
[[ "$SOURCE_REPO" == "$EXPECTED_SOURCE_REPO" ]] || fail "source worktree must be $EXPECTED_SOURCE_REPO"

for command in git install python3 readlink sha256sum stat sudo visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
[[ "$(git -C "$SOURCE_REPO" rev-parse --is-inside-work-tree 2>/dev/null)" == 'true' ]] || fail "source path is not a Git worktree"
[[ "$(git -C "$SOURCE_REPO" branch --show-current)" == 'main' ]] || fail "source worktree branch must be main"
[[ "$(git -C "$SOURCE_REPO" rev-parse HEAD)" == "$EXPECTED_SHA" ]] || fail "source worktree HEAD mismatch"
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

BASE_INSTALLER="$SOURCE_REPO/tools/runner/install-netto-shadow-rpi5-audit.sh"
SOURCE_RUNNER="$SOURCE_REPO/tools/run-hermes-deals-netto-shadow-evidence-v01.sh"
SOURCE_TOOL="$SOURCE_REPO/tools/netto_rpi5_shadow_audit.py"
for relative in \
  tools/runner/install-netto-shadow-rpi5-audit.sh \
  tools/runner/install-netto-shadow-rpi5-audit-worktree.sh \
  tools/run-hermes-deals-netto-shadow-evidence-v01.sh \
  tools/netto_rpi5_shadow_audit.py; do
  git -C "$SOURCE_REPO" ls-files --error-unmatch "$relative" >/dev/null || fail "required source is not tracked: $relative"
done
for source in "$BASE_INSTALLER" "$SOURCE_RUNNER" "$SOURCE_TOOL"; do
  [[ -f "$source" && ! -L "$source" ]] || fail "required source is missing or unsafe: $source"
done

TMPDIR_INSTALL="$(mktemp -d /tmp/hermes-deals-netto-shadow-worktree-installer.XXXXXX)"
cleanup() {
  rm -rf -- "$TMPDIR_INSTALL"
}
trap cleanup EXIT
PATCHED_INSTALLER="$TMPDIR_INSTALL/install-netto-shadow-rpi5-audit.sh"
PATCHED_RUNNER="$TMPDIR_INSTALL/netto-shadow-v1.sh"
PATCHED_TOOL="$TMPDIR_INSTALL/netto-shadow-v1.py"
cp -- "$BASE_INSTALLER" "$PATCHED_INSTALLER"
cp -- "$SOURCE_RUNNER" "$PATCHED_RUNNER"
cp -- "$SOURCE_TOOL" "$PATCHED_TOOL"

python3 - "$PATCHED_INSTALLER" "$PATCHED_RUNNER" "$PATCHED_TOOL" "$SOURCE_REPO" <<'PY'
from pathlib import Path
import shlex
import sys

installer = Path(sys.argv[1])
runner = Path(sys.argv[2])
tool = Path(sys.argv[3])
source_repo = sys.argv[4]


def replace_once(path: Path, old: str, new: str) -> None:
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(f"expected exactly one replacement in {path.name}, found {count}: {old}")
    path.write_text(text.replace(old, new), encoding="utf-8")

quoted_repo = shlex.quote(source_repo)
replace_once(installer, "REPO='/home/andris/hermes-deals'", f"REPO={quoted_repo}")
replace_once(
    installer,
    '[[ -d "$REPO/.git" ]] || fail "registration source is not a Git checkout"',
    '[[ "$(git -C "$REPO" rev-parse --is-inside-work-tree 2>/dev/null)" == "true" ]] || fail "registration source is not a Git checkout"',
)
replace_once(runner, "REPO='/home/andris/hermes-deals'", f"REPO={quoted_repo}")
replace_once(
    runner,
    '[[ -d "$REPO/.git" ]] || fail "Hermes Deals repository is unavailable"',
    '[[ "$(git -C "$REPO" rev-parse --is-inside-work-tree 2>/dev/null)" == "true" ]] || fail "Hermes Deals repository is unavailable"',
)
replace_once(
    tool,
    'if resolved != Path("/home/andris/hermes-deals") and os.environ.get("HERMES_AUDIT_TEST_MODE") != "1":',
    f'if resolved != Path({source_repo!r}) and os.environ.get("HERMES_AUDIT_TEST_MODE") != "1":',
)
PY

/bin/bash -n "$PATCHED_INSTALLER"
/bin/bash -n "$PATCHED_RUNNER"
/usr/bin/python3 - "$PATCHED_TOOL" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
compile(path.read_text(encoding="utf-8"), str(path), "exec")
PY

# The reviewed base installer creates the dedicated dispatcher, sudo rule and
# root-owned registry. Its registration-source checks are deterministically
# narrowed to the exact clean worktree above.
/bin/bash "$PATCHED_INSTALLER" "$EXPECTED_SHA"

INSTALLED_RUNNER='/usr/local/libexec/hermes-deals-audits/netto-shadow-v1.sh'
INSTALLED_TOOL='/usr/local/libexec/hermes-deals-audits/netto-shadow-v1.py'
CONFIG='/etc/hermes-deals-audits.d/netto-shadow-v1.conf'
DISPATCHER='/usr/local/sbin/hermes-deals-netto-shadow-audit-dispatch'

install -o root -g root -m 0755 "$PATCHED_RUNNER" "$INSTALLED_RUNNER"
install -o root -g root -m 0644 "$PATCHED_TOOL" "$INSTALLED_TOOL"
RUNNER_SHA="$(sha256sum "$INSTALLED_RUNNER" | awk '{print $1}')"
TOOL_SHA="$(sha256sum "$INSTALLED_TOOL" | awk '{print $1}')"
cat > "$TMPDIR_INSTALL/config" <<EOF
audit_name='netto-shadow-v1'
commit_sha='$EXPECTED_SHA'
runner_path='$INSTALLED_RUNNER'
runner_sha256='$RUNNER_SHA'
tool_path='$INSTALLED_TOOL'
tool_sha256='$TOOL_SHA'
source_repo='$SOURCE_REPO'
EOF
install -o root -g root -m 0644 "$TMPDIR_INSTALL/config" "$CONFIG"

[[ -f "$DISPATCHER" && ! -L "$DISPATCHER" ]] || fail "dedicated dispatcher is missing or unsafe"
[[ "$(stat -c '%U:%G' "$DISPATCHER")" == 'root:root' ]] || fail "dispatcher ownership is invalid"
sudo -l -U github-runner | grep -Fq "$DISPATCHER" || fail "dedicated dispatcher sudo rule is missing"

printf 'INSTALL_RESULT=PASS\nAUDIT=netto-shadow-v1\nCOMMIT_SHA=%s\nSOURCE_REPO=%s\nRUNNER_SHA256=%s\nTOOL_SHA256=%s\nDISPATCHER_SHA256=%s\nRUNNER_HAS_DOCKER_GROUP=false\nPRODUCTION_APPLY_AUTHORIZED=false\n' \
  "$EXPECTED_SHA" "$SOURCE_REPO" "$RUNNER_SHA" "$TOOL_SHA" "$(sha256sum "$DISPATCHER" | awk '{print $1}')"
