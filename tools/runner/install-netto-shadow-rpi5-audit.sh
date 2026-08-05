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
[[ $# -eq 1 ]] || fail "usage: sudo bash tools/runner/install-netto-shadow-rpi5-audit.sh <main-commit-sha>"
EXPECTED_SHA="$1"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "commit SHA is invalid"

REPO='/home/andris/hermes-deals'
RUNNER_SERVICE='actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service'
DISPATCHER='/usr/local/sbin/hermes-deals-netto-shadow-audit-dispatch'
SUDOERS='/etc/sudoers.d/hermes-deals-netto-shadow-audit'
LIBEXEC_DIR='/usr/local/libexec/hermes-deals-audits'
REGISTRY_DIR='/etc/hermes-deals-audits.d'
CONFIG="$REGISTRY_DIR/netto-shadow-v1.conf"
INSTALLED_RUNNER="$LIBEXEC_DIR/netto-shadow-v1.sh"
INSTALLED_TOOL="$LIBEXEC_DIR/netto-shadow-v1.py"
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'
SOURCE_RUNNER="$REPO/tools/run-hermes-deals-netto-shadow-evidence-v01.sh"
SOURCE_TOOL="$REPO/tools/netto_rpi5_shadow_audit.py"

for user in github-runner andris; do
  id "$user" >/dev/null 2>&1 || fail "required local user is missing: $user"
done
for command in git install python3 readlink runuser sha256sum stat systemctl visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
if id -nG github-runner | tr ' ' '\n' | grep -Fxq docker; then
  fail "github-runner must not belong to the Docker group"
fi

[[ -d "$REPO/.git" ]] || fail "registration source is not a Git checkout"
[[ "$(git -C "$REPO" branch --show-current)" == 'main' ]] || fail "registration source branch must be main"
[[ "$(git -C "$REPO" rev-parse HEAD)" == "$EXPECTED_SHA" ]] || fail "registration source HEAD mismatch"
[[ -z "$(git -C "$REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail "registration source worktree is not clean"
REMOTE="$(git -C "$REPO" remote get-url origin)"
case "$REMOTE" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail "registration source origin is not the Hermes Deals repository" ;;
esac
for source in "$SOURCE_RUNNER" "$SOURCE_TOOL"; do
  [[ -f "$source" && ! -L "$source" ]] || fail "approved audit source is missing or unsafe: $source"
done
git -C "$REPO" ls-files --error-unmatch tools/run-hermes-deals-netto-shadow-evidence-v01.sh >/dev/null || fail "audit runner is not tracked"
git -C "$REPO" ls-files --error-unmatch tools/netto_rpi5_shadow_audit.py >/dev/null || fail "audit tool is not tracked"
/bin/bash -n "$SOURCE_RUNNER"
/usr/bin/python3 - "$SOURCE_TOOL" <<'PY'
from pathlib import Path
import sys
path = Path(sys.argv[1])
compile(path.read_text(encoding="utf-8"), str(path), "exec")
PY

TMPDIR_INSTALL="$(mktemp -d /tmp/hermes-deals-netto-shadow-installer.XXXXXX)"
cleanup() { rm -rf -- "$TMPDIR_INSTALL"; }
trap cleanup EXIT

cat > "$TMPDIR_INSTALL/dispatcher" <<'DISPATCH'
#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() { echo "ERROR: $*" >&2; exit 1; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "dispatcher must run as root through sudo"
[[ $# -eq 2 ]] || fail "usage: hermes-deals-netto-shadow-audit-dispatch <registered-commit-sha> <artifact-dir>"
EXPECTED_SHA="$1"
EXPORT_DIR="$2"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "requested commit SHA is invalid"

CONFIG='/etc/hermes-deals-audits.d/netto-shadow-v1.conf'
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'
[[ -f "$CONFIG" && ! -L "$CONFIG" ]] || fail "Netto shadow audit is not registered"
[[ "$(stat -c '%U:%G' "$CONFIG")" == 'root:root' ]] || fail "audit config ownership is invalid"
[[ "$(stat -c '%a' "$CONFIG")" =~ ^(600|640|644)$ ]] || fail "audit config permissions are invalid"
# shellcheck disable=SC1090
source "$CONFIG"
[[ "${audit_name:-}" == 'netto-shadow-v1' ]] || fail "audit config name mismatch"
[[ "${commit_sha:-}" == "$EXPECTED_SHA" ]] || fail "requested commit is not the registered audit commit"
[[ "${runner_path:-}" == '/usr/local/libexec/hermes-deals-audits/netto-shadow-v1.sh' ]] || fail "registered runner path is invalid"
[[ "${tool_path:-}" == '/usr/local/libexec/hermes-deals-audits/netto-shadow-v1.py' ]] || fail "registered tool path is invalid"
[[ "${runner_sha256:-}" =~ ^[0-9a-f]{64}$ ]] || fail "registered runner SHA is invalid"
[[ "${tool_sha256:-}" =~ ^[0-9a-f]{64}$ ]] || fail "registered tool SHA is invalid"
for path in "$runner_path" "$tool_path"; do
  [[ -f "$path" && ! -L "$path" ]] || fail "registered audit member is missing or unsafe: $path"
  [[ "$(stat -c '%U:%G' "$path")" == 'root:root' ]] || fail "registered audit member ownership is invalid: $path"
done
[[ "$(sha256sum "$runner_path" | awk '{print $1}')" == "$runner_sha256" ]] || fail "registered runner content drift"
[[ "$(sha256sum "$tool_path" | awk '{print $1}')" == "$tool_sha256" ]] || fail "registered tool content drift"

EXPORT_DIR="$(readlink -f -- "$EXPORT_DIR")"
[[ -d "$EXPORT_DIR" && ! -L "$EXPORT_DIR" ]] || fail "artifact directory does not exist or is unsafe"
[[ "$EXPORT_DIR" == /home/github-runner/_work/_temp/hermes-deals-netto-shadow-* ]] || fail "artifact directory is outside the runner temp allowlist"
[[ "$(stat -c '%U:%G' "$EXPORT_DIR")" == 'github-runner:github-runner' ]] || fail "artifact directory ownership is invalid"
[[ "$(stat -c '%a' "$EXPORT_DIR")" == '700' ]] || fail "artifact directory permissions must be 0700"
RUN_KEY="$(basename -- "$EXPORT_DIR")"
[[ "$RUN_KEY" =~ ^hermes-deals-netto-shadow-[0-9]+-[0-9]+$ ]] || fail "artifact directory name is invalid"
STAGING_DIR="$STAGING_ROOT/$RUN_KEY"
install -d -o andris -g andris -m 0700 "$STAGING_ROOT"
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
  HOME=/home/andris \
  USER=andris \
  LOGNAME=andris \
  SHELL=/bin/bash \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 \
  TZ=Europe/Berlin \
  HERMES_AUDIT_TRIGGER=github-actions \
  HERMES_AUDIT_EXPECTED_BRANCH=main \
  HERMES_AUDIT_EXPECTED_HEAD="$EXPECTED_SHA" \
  HERMES_AUDIT_EXPORT_DIR="$STAGING_DIR" \
  HERMES_NETTO_AUDIT_TOOL="$tool_path" \
  /bin/bash --noprofile --norc "$runner_path" \
  > "$LOG_FILE" 2>&1
AUDIT_RC=$?
set -e
install -o andris -g andris -m 0600 \
  "$LOG_FILE" \
  "$STAGING_DIR/audit-execution.log"
rm -f -- "$LOG_FILE"
printf '%s\n' "$AUDIT_RC" > "$STAGING_DIR/audit-exit-code.txt"
chown andris:andris "$STAGING_DIR/audit-execution.log" "$STAGING_DIR/audit-exit-code.txt"
chmod 0600 "$STAGING_DIR/audit-execution.log" "$STAGING_DIR/audit-exit-code.txt"

python3 - "$STAGING_DIR" "$EXPORT_DIR/audit-evidence" "$EXPECTED_SHA" "$AUDIT_RC" <<'PY'
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
audit_rc = int(sys.argv[4])
allowed = {
    "audit-artifact-manifest.json",
    "audit-execution.log",
    "audit-exit-code.txt",
    "audit-summary.json",
    "corpus-report.json",
    "evidence-inventory.json",
    "transition-history.json",
    "weekly-decisions.json",
}
secret = re.compile(
    rb"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}|PGPASSWORD=|postgresql(?:\+[^:]+)?://[^\s:/]+:[^\s@]+@)",
    re.IGNORECASE,
)
files = []
for path in sorted(source.iterdir()):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not stat.S_ISREG(info.st_mode):
        raise SystemExit(f"unsafe audit output member: {path.name}")
    if path.name not in allowed:
        raise SystemExit(f"unexpected audit output member: {path.name}")
    if info.st_size > 32 * 1024 * 1024:
        raise SystemExit(f"audit output member exceeds 32 MiB: {path.name}")
    data = path.read_bytes()
    if secret.search(data):
        raise SystemExit(f"sensitive content rejected: {path.name}")
    files.append((path, data))
if not files:
    raise SystemExit("audit produced no exportable evidence")

destination.mkdir(mode=0o700, parents=False, exist_ok=False)
manifest = []
for path, data in files:
    target = destination / path.name
    target.write_bytes(data)
    os.chmod(target, 0o600)
    manifest.append(
        {"path": path.name, "bytes": len(data), "sha256": hashlib.sha256(data).hexdigest()}
    )
(destination / "dispatcher-evidence-manifest.json").write_text(
    json.dumps(
        {
            "audit": "netto-shadow-v1",
            "audit_exit_code": audit_rc,
            "commit_sha": commit_sha,
            "files": manifest,
            "production_apply_authorized": False,
            "database_write_performed": False,
            "deployment_performed": False,
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
printf 'AUDIT=netto-shadow-v1\nREGISTERED_COMMIT=%s\nAUDIT_EXIT_CODE=%s\nPRODUCTION_APPLY_AUTHORIZED=false\n' "$EXPECTED_SHA" "$AUDIT_RC"
exit "$AUDIT_RC"
DISPATCH

cat > "$TMPDIR_INSTALL/sudoers" <<'SUDOERS'
Defaults!/usr/local/sbin/hermes-deals-netto-shadow-audit-dispatch env_reset,secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-netto-shadow-audit-dispatch
SUDOERS

install -d -o root -g root -m 0755 "$LIBEXEC_DIR" "$REGISTRY_DIR"
install -d -o andris -g andris -m 0700 "$STAGING_ROOT"
install -o root -g root -m 0755 "$SOURCE_RUNNER" "$INSTALLED_RUNNER"
install -o root -g root -m 0644 "$SOURCE_TOOL" "$INSTALLED_TOOL"
RUNNER_SHA="$(sha256sum "$INSTALLED_RUNNER" | awk '{print $1}')"
TOOL_SHA="$(sha256sum "$INSTALLED_TOOL" | awk '{print $1}')"
cat > "$TMPDIR_INSTALL/config" <<EOF
audit_name='netto-shadow-v1'
commit_sha='$EXPECTED_SHA'
runner_path='$INSTALLED_RUNNER'
runner_sha256='$RUNNER_SHA'
tool_path='$INSTALLED_TOOL'
tool_sha256='$TOOL_SHA'
EOF
install -o root -g root -m 0644 "$TMPDIR_INSTALL/config" "$CONFIG"
chmod 0755 "$TMPDIR_INSTALL/dispatcher"
install -o root -g root -m 0755 "$TMPDIR_INSTALL/dispatcher" "$DISPATCHER"
chmod 0440 "$TMPDIR_INSTALL/sudoers"
visudo -cf "$TMPDIR_INSTALL/sudoers" >/dev/null
install -o root -g root -m 0440 "$TMPDIR_INSTALL/sudoers" "$SUDOERS"
visudo -cf "$SUDOERS" >/dev/null

systemctl is-active --quiet "$RUNNER_SERVICE" || fail "GitHub Actions runner service is not active"
sudo -l -U github-runner | grep -Fq "$DISPATCHER" || fail "dedicated dispatcher sudo rule was not installed"
printf 'INSTALL_RESULT=PASS\nAUDIT=netto-shadow-v1\nCOMMIT_SHA=%s\nRUNNER_SHA256=%s\nTOOL_SHA256=%s\nDISPATCHER_SHA256=%s\nRUNNER_HAS_DOCKER_GROUP=false\nPRODUCTION_APPLY_AUTHORIZED=false\n' \
  "$EXPECTED_SHA" "$RUNNER_SHA" "$TOOL_SHA" "$(sha256sum "$DISPATCHER" | awk '{print $1}')"
