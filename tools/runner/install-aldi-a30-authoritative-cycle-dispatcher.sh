#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
[[ $# -eq 1 && "$1" =~ ^[0-9a-f]{40}$ ]] || { echo "usage: $0 <merged-sha>" >&2; exit 2; }

SHA="$1"
REPO="/home/andris/hermes-deals-audit-source"
AUDIT_USER="andris"
AUDIT_HOME="/home/andris"
RUNNER_SRC="$REPO/tools/run-hermes-deals-aldi-a30-authoritative-cycle-v01.sh"
RUNNER_DST="/usr/local/libexec/hermes-deals-audits/aldi-a30-authoritative-cycle.sh"
DISPATCH="/usr/local/sbin/hermes-deals-aldi-a30-authoritative-cycle-dispatch"
CONF="/etc/hermes-deals-audits.d/aldi-a30-authoritative-cycle.conf"
INDEX="$REPO/.git/index"
INDEX_LOCK="$REPO/.git/index.lock"

[[ -d "$REPO/.git" && ! -L "$REPO/.git" ]] || {
  echo "audit repo git directory missing or unsafe" >&2
  exit 1
}
[[ -f "$INDEX" && ! -L "$INDEX" && ! -e "$INDEX_LOCK" ]] || {
  echo "audit repo index missing, unsafe, or locked" >&2
  exit 1
}
[[ "$(stat -c '%U:%G' "$INDEX")" == "$AUDIT_USER:$AUDIT_USER" ]] || {
  echo "audit repo index owner mismatch" >&2
  exit 1
}
[[ -r "$INDEX" && -w "$INDEX" ]] || {
  echo "audit repo index is not readable and writable by installer owner" >&2
  exit 1
}
[[ -x /usr/sbin/runuser ]] || {
  echo "runuser missing" >&2
  exit 1
}

tmp_dir="$(mktemp -d)"
trap 'rm -rf "$tmp_dir"' EXIT

audit_git() {
  /usr/sbin/runuser -u "$AUDIT_USER" -- /usr/bin/env -i \
    HOME="$AUDIT_HOME" \
    USER="$AUDIT_USER" \
    LOGNAME="$AUDIT_USER" \
    PATH=/usr/local/bin:/usr/bin:/bin \
    LANG=C.UTF-8 \
    GIT_OPTIONAL_LOCKS=0 \
    /usr/bin/git -C "$REPO" "$@"
}

audit_git_to_file() {
  local label="$1"
  local output="$2"
  shift 2
  local stderr_file="$tmp_dir/${label}.stderr"
  local rc

  : > "$output"
  : > "$stderr_file"
  set +e
  audit_git "$@" > "$output" 2> "$stderr_file"
  rc=$?
  set -e
  if [[ "$rc" -ne 0 ]]; then
    cat "$stderr_file" >&2 || true
    echo "audit repo git command failed: $label rc=$rc" >&2
    exit 1
  fi
  if [[ -s "$stderr_file" ]]; then
    cat "$stderr_file" >&2 || true
    echo "audit repo git command emitted stderr: $label" >&2
    exit 1
  fi
}

INDEX_OWNER_BEFORE="$(stat -c '%U:%G' "$INDEX")"
INDEX_MODE_BEFORE="$(stat -c '%a' "$INDEX")"
INDEX_BYTES_BEFORE="$(stat -c '%s' "$INDEX")"
INDEX_SHA256_BEFORE="$(sha256sum "$INDEX" | awk '{print $1}')"

audit_git_to_file branch "$tmp_dir/branch.stdout" branch --show-current
audit_git_to_file head "$tmp_dir/head.stdout" rev-parse HEAD
audit_git_to_file status "$tmp_dir/status.stdout" status --porcelain=v1 -z --untracked-files=all

[[ "$(cat "$tmp_dir/branch.stdout")" == main ]] || {
  echo "audit repo branch mismatch" >&2
  exit 1
}
[[ "$(cat "$tmp_dir/head.stdout")" == "$SHA" ]] || {
  echo "audit repo SHA mismatch" >&2
  exit 1
}
[[ ! -s "$tmp_dir/status.stdout" ]] || {
  echo "audit repo dirty" >&2
  exit 1
}

INDEX_OWNER_AFTER_GIT="$(stat -c '%U:%G' "$INDEX")"
INDEX_MODE_AFTER_GIT="$(stat -c '%a' "$INDEX")"
INDEX_BYTES_AFTER_GIT="$(stat -c '%s' "$INDEX")"
INDEX_SHA256_AFTER_GIT="$(sha256sum "$INDEX" | awk '{print $1}')"

[[ "$INDEX_OWNER_AFTER_GIT" == "$INDEX_OWNER_BEFORE" ]] || {
  echo "audit repo index owner changed during git verification" >&2
  exit 1
}
[[ "$INDEX_MODE_AFTER_GIT" == "$INDEX_MODE_BEFORE" ]] || {
  echo "audit repo index mode changed during git verification" >&2
  exit 1
}
[[ "$INDEX_BYTES_AFTER_GIT" == "$INDEX_BYTES_BEFORE" ]] || {
  echo "audit repo index size changed during git verification" >&2
  exit 1
}
[[ "$INDEX_SHA256_AFTER_GIT" == "$INDEX_SHA256_BEFORE" ]] || {
  echo "audit repo index content changed during git verification" >&2
  exit 1
}

install -d -o root -g root -m 0755 /usr/local/libexec/hermes-deals-audits /etc/hermes-deals-audits.d
install -o root -g root -m 0755 "$RUNNER_SRC" "$RUNNER_DST"
runner_sha="$(sha256sum "$RUNNER_DST" | awk '{print $1}')"
cat > "$CONF" <<EOF
audit_name='aldi-a30-authoritative-cycle'
commit_sha='$SHA'
script_path='$RUNNER_DST'
script_sha256='$runner_sha'
EOF
chmod 0600 "$CONF"
chown root:root "$CONF"
cat > "$DISPATCH" <<'DISPATCH'
#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
[[ ${EUID:-$(id -u)} -eq 0 && $# -eq 2 ]] || { echo "dispatcher usage error" >&2; exit 2; }
SHA="$1"
EXPORT="$(readlink -f "$2")"
CONF="/etc/hermes-deals-audits.d/aldi-a30-authoritative-cycle.conf"
[[ "$EXPORT" == /home/github-runner/_work/_temp/hermes-deals-aldi-a30-authoritative-cycle-* ]] || { echo "artifact path rejected" >&2; exit 1; }
source "$CONF"
[[ "$audit_name" == aldi-a30-authoritative-cycle && "$commit_sha" == "$SHA" && "$(sha256sum "$script_path" | awk '{print $1}')" == "$script_sha256" ]] || { echo "registration drift" >&2; exit 1; }
staging="/home/andris/hermes-deals-runner-evidence/$(basename "$EXPORT")"
install -d -o andris -g andris -m 0700 "$staging"
install -o andris -g andris -m 0600 /dev/null "$staging/audit-execution.log"
set +e
runuser -u andris -- /usr/bin/env -i HOME=/home/andris USER=andris LOGNAME=andris PATH=/usr/local/bin:/usr/bin:/bin LANG=C.UTF-8 \
  /bin/bash --noprofile --norc "$script_path" "$SHA" > "$staging/audit-execution.log" 2>&1
rc=$?
set -e
mkdir -m 0700 "$EXPORT/audit-evidence"
cp "$staging/audit-execution.log" "$EXPORT/audit-evidence/"
evidence_dir="$(grep -E '^EVIDENCE_DIR=' "$staging/audit-execution.log" | tail -1 | cut -d= -f2- || true)"
if [[ -n "$evidence_dir" && -d "$evidence_dir" && "$evidence_dir" == /home/andris/.local/state/hermes-deals/aldi-perfect-shadow/a30-authoritative-cycle-github/*/evidence ]]; then
  cp -a "$evidence_dir" "$EXPORT/audit-evidence/evidence"
fi
python3 - "$EXPORT/audit-evidence" "$SHA" "$rc" <<'PY'
import hashlib
import json
import pathlib
import stat
import sys
root = pathlib.Path(sys.argv[1])
sha = sys.argv[2]
rc = int(sys.argv[3])
files = []
for path in sorted(root.rglob("*")):
    info = path.lstat()
    if stat.S_ISLNK(info.st_mode) or not (stat.S_ISDIR(info.st_mode) or stat.S_ISREG(info.st_mode)):
        raise SystemExit("unsafe evidence type")
    if path.is_file():
        files.append({
            "path": path.relative_to(root).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        })
(root / "dispatcher-evidence-manifest.json").write_text(
    json.dumps({
        "schema_version": 1,
        "audit": "aldi-a30-authoritative-cycle",
        "commit_sha": sha,
        "audit_exit_code": rc,
        "files": files,
        "production_apply_authorized": False,
        "sanitization_passed": True,
    }, indent=2, sort_keys=True) + "\n"
)
PY
chown -R github-runner:github-runner "$EXPORT/audit-evidence"
rm -rf "$staging"
exit "$rc"
DISPATCH
chmod 0755 "$DISPATCH"
chown root:root "$DISPATCH"
tmp="$(mktemp)"
echo "github-runner ALL=(root) NOPASSWD: $DISPATCH" > "$tmp"
visudo -cf "$tmp" >/dev/null
install -o root -g root -m 0440 "$tmp" /etc/sudoers.d/hermes-deals-aldi-a30-authoritative-cycle
rm -f "$tmp"
systemctl is-active --quiet actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-audit.service
[[ "$(id -nG github-runner | tr ' ' '\n' | grep -Fxq docker && echo true || echo false)" == false ]]

INDEX_OWNER_AFTER="$(stat -c '%U:%G' "$INDEX")"
INDEX_MODE_AFTER="$(stat -c '%a' "$INDEX")"
INDEX_BYTES_AFTER="$(stat -c '%s' "$INDEX")"
INDEX_SHA256_AFTER="$(sha256sum "$INDEX" | awk '{print $1}')"

[[ "$INDEX_OWNER_AFTER" == "$INDEX_OWNER_BEFORE" ]] || {
  echo "audit repo index owner changed during installer execution" >&2
  exit 1
}
[[ "$INDEX_MODE_AFTER" == "$INDEX_MODE_BEFORE" ]] || {
  echo "audit repo index mode changed during installer execution" >&2
  exit 1
}
[[ "$INDEX_BYTES_AFTER" == "$INDEX_BYTES_BEFORE" ]] || {
  echo "audit repo index size changed during installer execution" >&2
  exit 1
}
[[ "$INDEX_SHA256_AFTER" == "$INDEX_SHA256_BEFORE" ]] || {
  echo "audit repo index content changed during installer execution" >&2
  exit 1
}

printf 'INSTALL_RESULT=PASS\nAUDIT=aldi-a30-authoritative-cycle\nREGISTERED_COMMIT=%s\nRUNNER_HAS_DOCKER_GROUP=false\nINSTALLER_INDEX_OWNERSHIP_PRESERVED=true\nPRODUCTION_APPLY_AUTHORIZED=false\n' "$SHA"
