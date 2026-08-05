#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "run with sudo"
[[ $# -eq 1 ]] || fail "usage: sudo bash tools/runner/install-lidl-semantic-corpus-audit-dispatcher.sh <merged-commit-sha>"

EXPECTED_SHA="$1"
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid merged commit SHA"

REPO="/home/andris/hermes-deals"
RELATIVE_SCRIPT="tools/run-hermes-deals-lidl-semantic-corpus-audit-v01.sh"
RUNNER_SERVICE="actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service"
DISPATCHER="/usr/local/sbin/hermes-deals-lidl-semantic-corpus-audit-dispatch"
INSTALLED_SCRIPT="/usr/local/libexec/hermes-deals-audits/lidl-semantic-corpus.sh"
CONF="/etc/hermes-deals-audits.d/lidl-semantic-corpus.conf"
SUDOERS="/etc/sudoers.d/hermes-deals-lidl-semantic-corpus-audit"
STAGING_ROOT="/home/andris/hermes-deals-runner-evidence"

for user in andris github-runner; do
  id "$user" >/dev/null 2>&1 || fail "required user is missing: $user"
done
for command in git install mktemp readlink runuser sha256sum stat systemctl visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

[[ -d "$REPO/.git" ]] || fail "Hermes Deals repository is missing"
[[ "$(git -C "$REPO" branch --show-current)" == "main" ]] || fail "registration source branch must be main"
[[ -z "$(git -C "$REPO" status --porcelain)" ]] || fail "registration source worktree is not clean"
git -C "$REPO" cat-file -e "$EXPECTED_SHA^{commit}" || fail "merged commit is missing"
git -C "$REPO" merge-base --is-ancestor "$EXPECTED_SHA" main || fail "merged commit is not reachable from main"

origin="$(git -C "$REPO" remote get-url origin)"
case "$origin" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail "registration source origin is not allowlisted" ;;
esac

tmp="$(mktemp -d /tmp/hermes-deals-lidl-semantic-audit-install.XXXXXX)"
cleanup() {
  rm -rf -- "$tmp"
}
trap cleanup EXIT

git -C "$REPO" show "$EXPECTED_SHA:$RELATIVE_SCRIPT" > "$tmp/lidl-semantic-corpus.sh"
[[ -s "$tmp/lidl-semantic-corpus.sh" ]] || fail "registered audit script is empty"
head -n 1 "$tmp/lidl-semantic-corpus.sh" | grep -Fxq '#!/usr/bin/env bash' || fail "registered audit script header is invalid"
chmod 0755 "$tmp/lidl-semantic-corpus.sh"

cat > "$tmp/hermes-deals-lidl-semantic-corpus-audit-dispatch" <<'DISPATCH'
#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() {
  printf 'ERROR: %s\n' "$*" >&2
  exit 1
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "dispatcher must run as root through sudo"
[[ $# -eq 2 ]] || fail "usage: hermes-deals-lidl-semantic-corpus-audit-dispatch <registered-sha> <artifact-dir>"

EXPECTED_SHA="$1"
EXPORT_DIR="$2"
CONF='/etc/hermes-deals-audits.d/lidl-semantic-corpus.conf'
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid commit SHA"
[[ -f "$CONF" && ! -L "$CONF" ]] || fail "audit registration is missing"
[[ "$(stat -c '%U:%G' "$CONF")" == 'root:root' ]] || fail "audit registration ownership is invalid"
[[ "$(stat -c '%a' "$CONF")" =~ ^(600|640|644)$ ]] || fail "audit registration permissions are invalid"
# shellcheck disable=SC1090
source "$CONF"
[[ "${audit_name:-}" == 'lidl-semantic-corpus' ]] || fail "audit registration name mismatch"
[[ "${commit_sha:-}" == "$EXPECTED_SHA" ]] || fail "requested SHA is not registered"
[[ "${script_path:-}" == '/usr/local/libexec/hermes-deals-audits/lidl-semantic-corpus.sh' ]] || fail "registered script path is invalid"
[[ "${script_sha256:-}" =~ ^[0-9a-f]{64}$ ]] || fail "registered script SHA is invalid"
[[ -f "$script_path" && ! -L "$script_path" ]] || fail "registered script is missing or unsafe"
[[ "$(stat -c '%U:%G' "$script_path")" == 'root:root' ]] || fail "registered script ownership is invalid"
[[ "$(sha256sum "$script_path" | awk '{print $1}')" == "$script_sha256" ]] || fail "registered script content drift"

EXPORT_DIR="$(readlink -f -- "$EXPORT_DIR")"
[[ -d "$EXPORT_DIR" && ! -L "$EXPORT_DIR" ]] || fail "artifact directory is missing or unsafe"
[[ "$EXPORT_DIR" == /home/github-runner/_work/_temp/hermes-deals-lidl-semantic-audit-* ]] || fail "artifact directory is outside the runner temp allowlist"
[[ "$(stat -c '%U:%G' "$EXPORT_DIR")" == 'github-runner:github-runner' ]] || fail "artifact directory ownership is invalid"
[[ "$(stat -c '%a' "$EXPORT_DIR")" == '700' ]] || fail "artifact directory permissions must be 0700"

run_key="$(basename -- "$EXPORT_DIR")"
[[ "$run_key" =~ ^hermes-deals-lidl-semantic-audit-[0-9]+-[0-9]+$ ]] || fail "unexpected artifact directory name"
staging="$STAGING_ROOT/$run_key"
install -d -o andris -g andris -m 0700 "$STAGING_ROOT"
[[ ! -e "$staging" ]] || fail "staging directory already exists"
install -d -o andris -g andris -m 0700 "$staging"
cleanup() {
  rm -rf -- "$staging"
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
  HERMES_AUDIT_TRIGGER=github-actions \
  HERMES_AUDIT_EXPECTED_BRANCH=main \
  HERMES_AUDIT_EXPECTED_HEAD="$EXPECTED_SHA" \
  HERMES_AUDIT_EXPORT_DIR="$staging" \
  /bin/bash --noprofile --norc "$script_path" \
  > "$staging/audit-execution.log" 2>&1
audit_rc=$?
set -e

python3 - "$staging" "$EXPORT_DIR/audit-evidence" "$EXPECTED_SHA" "$audit_rc" <<'PY'
import hashlib
import json
import os
import pathlib
import re
import shutil
import stat
import sys

source = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
commit_sha = sys.argv[3]
audit_rc = int(sys.argv[4])
if not source.is_dir():
    raise SystemExit("audit staging directory is missing")

sensitive_name = re.compile(
    r"(?:^|/)(?:\.env(?:\..*)?|production\.dump|admin\.password|runtime\.password|[^/]+\.(?:pgpass|pem|key))$",
    re.IGNORECASE,
)
sensitive_content = re.compile(
    rb"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:ghp|gho|ghu|ghs|github_pat)_[A-Za-z0-9_]{20,}|PGPASSWORD=|--token[ =]|postgresql(?:\+[^:]+)?://[^\s:/]+:[^\s@]+@)",
    re.IGNORECASE,
)

files = []
total = 0
for path in sorted(source.rglob("*")):
    relative = path.relative_to(source)
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        raise SystemExit(f"unsafe evidence member type: {relative}")
    if sensitive_name.search(relative.as_posix()):
        raise SystemExit(f"sensitive evidence filename rejected: {relative}")
    if stat.S_ISREG(info.st_mode):
        total += info.st_size
        if total > 250 * 1024 * 1024:
            raise SystemExit("evidence exceeds 250 MiB")
        if info.st_size <= 8 * 1024 * 1024 and sensitive_content.search(path.read_bytes()):
            raise SystemExit(f"sensitive evidence content rejected: {relative}")
        files.append((path, relative, info.st_size))
if not files:
    raise SystemExit("audit created no evidence")

destination.mkdir(mode=0o700, parents=False, exist_ok=False)
manifest = []
for path, relative, size in files:
    target = destination / relative
    target.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    shutil.copy2(path, target, follow_symlinks=False)
    os.chmod(target, 0o600)
    manifest.append({
        "path": relative.as_posix(),
        "bytes": size,
        "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
    })
manifest_path = destination / "dispatcher-evidence-manifest.json"
manifest_path.write_text(json.dumps({
    "schema_version": 1,
    "audit": "lidl-semantic-corpus",
    "audit_exit_code": audit_rc,
    "commit_sha": commit_sha,
    "files": manifest,
    "total_bytes": total,
    "sanitization_passed": True,
    "production_apply_authorized": False,
}, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.chmod(manifest_path, 0o600)
PY

printf '%s\n' "$audit_rc" > "$EXPORT_DIR/audit-evidence/audit-exit-code.txt"
chown -R github-runner:github-runner "$EXPORT_DIR/audit-evidence"
find "$EXPORT_DIR/audit-evidence" -type d -exec chmod 0700 {} +
find "$EXPORT_DIR/audit-evidence" -type f -exec chmod 0600 {} +
printf 'AUDIT=lidl-semantic-corpus\nREGISTERED_COMMIT=%s\nAUDIT_EXIT_CODE=%s\nPRODUCTION_APPLY_AUTHORIZED=false\n' "$EXPECTED_SHA" "$audit_rc"
exit "$audit_rc"
DISPATCH

cat > "$tmp/sudoers" <<'SUDOERS'
Defaults!/usr/local/sbin/hermes-deals-lidl-semantic-corpus-audit-dispatch env_reset,secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-lidl-semantic-corpus-audit-dispatch
SUDOERS
chmod 0755 "$tmp/hermes-deals-lidl-semantic-corpus-audit-dispatch"
chmod 0440 "$tmp/sudoers"
visudo -cf "$tmp/sudoers" >/dev/null

install -d -o root -g root -m 0755 /usr/local/libexec/hermes-deals-audits /etc/hermes-deals-audits.d
install -d -o andris -g andris -m 0700 "$STAGING_ROOT"
install -o root -g root -m 0755 "$tmp/lidl-semantic-corpus.sh" "$INSTALLED_SCRIPT"
script_sha="$(sha256sum "$INSTALLED_SCRIPT" | awk '{print $1}')"

conf_tmp="$(mktemp /etc/hermes-deals-audits.d/.lidl-semantic-corpus.conf.XXXXXX)"
cat > "$conf_tmp" <<EOF
audit_name='lidl-semantic-corpus'
commit_sha='$EXPECTED_SHA'
script_sha256='$script_sha'
script_path='$INSTALLED_SCRIPT'
EOF
chown root:root "$conf_tmp"
chmod 0644 "$conf_tmp"
mv -f -- "$conf_tmp" "$CONF"

install -o root -g root -m 0755 "$tmp/hermes-deals-lidl-semantic-corpus-audit-dispatch" "$DISPATCHER"
install -o root -g root -m 0440 "$tmp/sudoers" "$SUDOERS"
visudo -cf "$SUDOERS" >/dev/null
systemctl is-active --quiet "$RUNNER_SERVICE" || fail "GitHub Actions runner service is not active"
sudo -l -U github-runner | grep -Fq "$DISPATCHER" || fail "github-runner sudo rule is missing"
runner_has_docker="$(id -nG github-runner | tr ' ' '\n' | grep -Fxq docker && echo true || echo false)"
[[ "$runner_has_docker" == false ]] || fail "github-runner must not belong to docker group"

printf 'INSTALL_RESULT=PASS\nAUDIT=lidl-semantic-corpus\nREGISTERED_COMMIT=%s\nSCRIPT_SHA256=%s\nDISPATCHER_SHA256=%s\nSUDOERS_VALID=true\nRUNNER_HAS_DOCKER_GROUP=false\nPRODUCTION_APPLY_AUTHORIZED=false\n' \
  "$EXPECTED_SHA" "$script_sha" "$(sha256sum "$DISPATCHER" | awk '{print $1}')"
