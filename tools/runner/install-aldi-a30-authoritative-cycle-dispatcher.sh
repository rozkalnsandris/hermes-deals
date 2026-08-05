#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
[[ ${EUID:-$(id -u)} -eq 0 ]] || { echo "run with sudo" >&2; exit 1; }
[[ $# -eq 1 && "$1" =~ ^[0-9a-f]{40}$ ]] || { echo "usage: $0 <merged-sha>" >&2; exit 2; }
SHA="$1"
REPO="/home/andris/hermes-deals-audit-source"
RUNNER_SRC="$REPO/tools/run-hermes-deals-aldi-a30-authoritative-cycle-v01.sh"
RUNNER_DST="/usr/local/libexec/hermes-deals-audits/aldi-a30-authoritative-cycle.sh"
DISPATCH="/usr/local/sbin/hermes-deals-aldi-a30-authoritative-cycle-dispatch"
CONF="/etc/hermes-deals-audits.d/aldi-a30-authoritative-cycle.conf"
[[ "$(git -C "$REPO" branch --show-current)" == main && "$(git -C "$REPO" rev-parse HEAD)" == "$SHA" ]] || { echo "audit repo SHA mismatch" >&2; exit 1; }
[[ -z "$(git -C "$REPO" status --porcelain=v1 --untracked-files=all)" ]] || { echo "audit repo dirty" >&2; exit 1; }
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
printf 'INSTALL_RESULT=PASS\nAUDIT=aldi-a30-authoritative-cycle\nREGISTERED_COMMIT=%s\nRUNNER_HAS_DOCKER_GROUP=false\nPRODUCTION_APPLY_AUTHORIZED=false\n' "$SHA"
