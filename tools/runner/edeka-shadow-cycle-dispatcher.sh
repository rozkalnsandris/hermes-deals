#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH

fail() { printf 'ERROR: %s\n' "$*" >&2; exit 1; }
[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "dispatcher must run as root through sudo"
[[ $# -eq 2 ]] || fail "usage: hermes-deals-edeka-shadow-cycle-dispatch <registered-sha> <artifact-dir>"

EXPECTED_SHA="$1"
EXPORT_DIR="$2"
CONF='/etc/hermes-deals-audits.d/edeka-shadow-cycle.conf'
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'
EVIDENCE_ROOT='/home/andris/hermes-deals-shadow-evidence/edeka'
[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid commit SHA"
[[ -f "$CONF" && ! -L "$CONF" ]] || fail "EDEKA shadow registration is missing"
[[ "$(stat -c '%U:%G' "$CONF")" == 'root:root' ]] || fail "registration ownership is invalid"
# shellcheck disable=SC1090
source "$CONF"
[[ "${audit_name:-}" == 'edeka-shadow-cycle' ]] || fail "registration name mismatch"
[[ "${commit_sha:-}" == "$EXPECTED_SHA" ]] || fail "requested SHA is not registered"
[[ "${script_path:-}" == '/usr/local/libexec/hermes-deals-audits/edeka-shadow-cycle.sh' ]] || fail "registered script path is invalid"
[[ "${script_sha256:-}" =~ ^[0-9a-f]{64}$ ]] || fail "registered script SHA is invalid"
[[ -f "$script_path" && ! -L "$script_path" ]] || fail "registered script is missing or unsafe"
[[ "$(stat -c '%U:%G' "$script_path")" == 'root:root' ]] || fail "registered script ownership is invalid"
[[ "$(sha256sum "$script_path" | awk '{print $1}')" == "$script_sha256" ]] || fail "registered script content drift"

EXPORT_DIR="$(readlink -f -- "$EXPORT_DIR")"
[[ -d "$EXPORT_DIR" && ! -L "$EXPORT_DIR" ]] || fail "artifact directory is missing or unsafe"
[[ "$EXPORT_DIR" == /home/github-runner/_work/_temp/hermes-deals-edeka-shadow-cycle-* ]] || fail "artifact directory is outside runner temp allowlist"
[[ "$(stat -c '%U:%G' "$EXPORT_DIR")" == 'github-runner:github-runner' ]] || fail "artifact directory ownership is invalid"
[[ "$(stat -c '%a' "$EXPORT_DIR")" == '700' ]] || fail "artifact directory permissions must be 0700"

run_key="$(basename -- "$EXPORT_DIR")"
[[ "$run_key" =~ ^hermes-deals-edeka-shadow-cycle-[0-9]+-[0-9]+$ ]] || fail "unexpected artifact directory name"
staging="$STAGING_ROOT/$run_key"
install -d -o andris -g andris -m 0700 "$STAGING_ROOT"
[[ ! -e "$staging" ]] || fail "staging directory already exists"
install -d -o andris -g andris -m 0700 "$staging"
cleanup() { rm -rf -- "$staging"; }
trap cleanup EXIT

set +e
runuser -u andris -- /usr/bin/env -i \
  HOME=/home/andris USER=andris LOGNAME=andris SHELL=/bin/bash \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 HERMES_AUDIT_TRIGGER=github-actions \
  /bin/bash --noprofile --norc "$script_path" "$EXPECTED_SHA" \
  > "$staging/audit-execution.log" 2>&1
audit_rc=$?
set -e

python3 - "$staging" "$EXPORT_DIR/audit-evidence" "$EXPECTED_SHA" "$audit_rc" "$EVIDENCE_ROOT" <<'PY'
import hashlib, json, os, pathlib, re, shutil, stat, sys, tarfile
source = pathlib.Path(sys.argv[1])
destination = pathlib.Path(sys.argv[2])
commit_sha = sys.argv[3]
audit_rc = int(sys.argv[4])
evidence_root = pathlib.Path(sys.argv[5]).resolve()
log = source / "audit-execution.log"
if not log.is_file() or log.is_symlink():
    raise SystemExit("audit execution log is missing or unsafe")
text = log.read_text(encoding="utf-8", errors="replace")

def marker(name: str) -> str:
    values = re.findall(rf"(?m)^{re.escape(name)}=(.+)$", text)
    if len(values) != 1:
        raise SystemExit(f"expected exactly one {name} marker")
    return values[0].strip()

manifest = {
    "schema_version": 1,
    "audit": "edeka-shadow-cycle",
    "audit_exit_code": audit_rc,
    "commit_sha": commit_sha,
    "sanitization_passed": False,
    "production_apply_authorized": False,
}
destination.mkdir(mode=0o700, parents=False, exist_ok=False)
shutil.copy2(log, destination / "audit-execution.log", follow_symlinks=False)
os.chmod(destination / "audit-execution.log", 0o600)

if audit_rc == 0:
    required = {
        "RESULT": "PASS",
        "REGISTERED_COMMIT": commit_sha,
        "PRIMARY_WORKTREE_MODIFIED": "false",
        "PRIMARY_GIT_INDEX_UNCHANGED": "true",
        "AUDIT_GIT_INDEX_UNCHANGED": "true",
        "PRODUCTION_DATABASE_WRITE": "false",
        "PRODUCTION_DEPLOYMENT": "false",
        "SCHEDULER_ACTIVATION": "false",
    }
    for key, expected in required.items():
        if marker(key) != expected:
            raise SystemExit(f"unexpected {key} marker")
    archive = pathlib.Path(marker("ARCHIVE")).resolve()
    archive_sha = marker("ARCHIVE_SHA256")
    if archive.parent != evidence_root or archive.is_symlink() or not archive.is_file():
        raise SystemExit("archive path is outside the EDEKA evidence root or unsafe")
    if not re.fullmatch(rf"hermes-deals-edeka-shadow-[0-9]{{8}}T[0-9]{{6}}Z-{commit_sha[:12]}\.tar\.gz", archive.name):
        raise SystemExit("archive name is not bound to registered commit")
    if archive.stat().st_size > 250 * 1024 * 1024:
        raise SystemExit("archive exceeds 250 MiB")
    digest = hashlib.sha256(archive.read_bytes()).hexdigest()
    if digest != archive_sha or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise SystemExit("archive SHA marker mismatch")
    sidecar = pathlib.Path(str(archive) + ".sha256")
    if not sidecar.is_file() or sidecar.is_symlink() or not sidecar.read_text().startswith(digest + "  "):
        raise SystemExit("archive SHA sidecar mismatch")

    sensitive_name = re.compile(r"(?:^|/)(?:\.env(?:\..*)?|[^/]+\.(?:pgpass|pem|key)|production\.dump)$", re.I)
    sensitive_content = re.compile(rb"(?:-----BEGIN [A-Z ]*PRIVATE KEY-----|(?:ghp|github_pat)_[A-Za-z0-9_]{20,}|PGPASSWORD=|postgresql(?:\+[^:]+)?://[^\s:/]+:[^\s@]+@)", re.I)
    small = {}
    members = []
    total = 0
    with tarfile.open(archive, "r:gz") as bundle:
        for item in bundle.getmembers():
            pure = pathlib.PurePosixPath(item.name)
            if pure.is_absolute() or ".." in pure.parts or not (item.isdir() or item.isfile()):
                raise SystemExit(f"unsafe archive member: {item.name}")
            if sensitive_name.search(item.name):
                raise SystemExit(f"sensitive archive filename: {item.name}")
            if item.isfile():
                total += item.size
                if total > 250 * 1024 * 1024:
                    raise SystemExit("archive uncompressed content exceeds 250 MiB")
                members.append(item.name)
                if item.size <= 8 * 1024 * 1024:
                    data = bundle.extractfile(item).read()
                    if sensitive_content.search(data):
                        raise SystemExit(f"sensitive archive content: {item.name}")
                    small[item.name] = data
    def unique(suffix: str) -> str:
        found = [name for name in members if name.endswith(suffix)]
        if len(found) != 1:
            raise SystemExit(f"expected one archive member ending {suffix}")
        return found[0]
    cycle_name = unique("/cycle/cycle-evidence.json")
    norm_name = unique("/cycle/normalization-report.json")
    safety_name = unique("/safety-result.txt")
    request_name = unique("/run-request.txt")
    if not any(name.endswith("/cycle/shadow.sqlite3") for name in members):
        raise SystemExit("isolated SQLite evidence is missing")
    cycle = json.loads(small[cycle_name])
    norm = json.loads(small[norm_name])
    source_info = cycle.get("source") or {}
    expected_source = {
        "public_market_id": "071897",
        "internal_market_id": "587881",
        "store_name": "EDEKA Patzer",
        "source_url": "https://www.edeka.de/maerkte/071897/angebote/",
    }
    for key, expected in expected_source.items():
        if source_info.get(key) != expected:
            raise SystemExit(f"cycle source mismatch: {key}")
    persistence = cycle.get("isolated_persistence") or {}
    parsed = persistence.get("parsed_offer_count")
    if not isinstance(parsed, int) or parsed < 150:
        raise SystemExit("parsed offer count is below 150")
    if persistence.get("first_write_offer_delta") != parsed or persistence.get("same_snapshot_replay_offer_delta") != 0:
        raise SystemExit("isolated persistence replay contract failed")
    if persistence.get("production_database_write") is not False:
        raise SystemExit("production database safety mismatch")
    norm_source = norm.get("source") or {}
    for key, expected in expected_source.items():
        if norm_source.get(key) != expected:
            raise SystemExit(f"normalization source mismatch: {key}")
    for required_text, data in (
        ("PRODUCTION_DATABASE_WRITE=false", small[safety_name]),
        (f"registered_commit={commit_sha}", small[request_name]),
    ):
        if required_text.encode() not in data:
            raise SystemExit(f"missing archive safety binding: {required_text}")

    for path in (archive, sidecar):
        target = destination / path.name
        shutil.copy2(path, target, follow_symlinks=False)
        os.chmod(target, 0o600)
    for source_name, target_name in ((cycle_name, "cycle-evidence.json"), (norm_name, "normalization-report.json"), (safety_name, "safety-result.txt"), (request_name, "run-request.txt")):
        target = destination / target_name
        target.write_bytes(small[source_name])
        os.chmod(target, 0o600)
    manifest["archive"] = {"name": archive.name, "bytes": archive.stat().st_size, "sha256": digest, "member_count": len(members), "offer_count": parsed}
    manifest["sanitization_passed"] = True

manifest_path = destination / "dispatcher-evidence-manifest.json"
manifest_path.write_text(json.dumps(manifest, indent=2, sort_keys=True) + "\n", encoding="utf-8")
os.chmod(manifest_path, 0o600)
PY

printf '%s\n' "$audit_rc" > "$EXPORT_DIR/audit-evidence/audit-exit-code.txt"
chown -R github-runner:github-runner "$EXPORT_DIR/audit-evidence"
find "$EXPORT_DIR/audit-evidence" -type d -exec chmod 0700 {} +
find "$EXPORT_DIR/audit-evidence" -type f -exec chmod 0600 {} +
printf 'AUDIT=edeka-shadow-cycle\nREGISTERED_COMMIT=%s\nAUDIT_EXIT_CODE=%s\nPRODUCTION_DATABASE_WRITE=false\nPRODUCTION_DEPLOYMENT=false\nSCHEDULER_ACTIVATION=false\n' "$EXPECTED_SHA" "$audit_rc"
exit "$audit_rc"
