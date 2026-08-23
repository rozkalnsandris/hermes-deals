#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH PYTHONDONTWRITEBYTECODE=1

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "run with sudo"
[[ $# -eq 1 ]] || fail "usage: sudo bash tools/runner/install-kaufland-k3c-promo-structure-rpi5-bridge.sh <merged-main-sha>"

EXPECTED_SHA="$1"
REPO='/home/andris/hermes-deals'
RETAINED_ROOT='/home/andris/hermes-deals-retained-evidence'
RUNTIME_ROOT='/usr/local/libexec/hermes-deals-audits/kaufland-k3c-promo-structure'
VALIDATOR="$RUNTIME_ROOT/validator.py"
DISPATCHER='/usr/local/sbin/hermes-deals-kaufland-k3c-promo-structure-dispatch'
CONFIG='/etc/hermes-deals-audits.d/kaufland-k3c-promo-structure.conf'
SUDOERS='/etc/sudoers.d/hermes-deals-kaufland-k3c-promo-structure'
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'
VALIDATOR_REL='tools/runner/kaufland_k3c_promo_structure_bridge_validator.py'
DIAGNOSTIC_REL='backend/app/kaufland_k3c_promo_structure_diagnostic.py'
HELPER_REL='backend/app/kaufland_real_k2_v2_derivation.py'
FREEZE_REL='backend/app/kaufland_evidence_freeze.py'
CARD_REL='backend/app/kaufland_source_card_contract.py'
DISCOVERY_REL='backend/app/kaufland_source_discovery.py'

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "commit SHA is invalid"
for user in github-runner andris; do
  id "$user" >/dev/null 2>&1 || fail "required local user is missing: $user"
done
for command in git install mktemp python3 readlink runuser sha256sum stat sudo visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done

git_as_andris() {
  runuser -u andris -- /usr/bin/env -i \
    HOME=/home/andris USER=andris LOGNAME=andris \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    GIT_OPTIONAL_LOCKS=0 \
    /usr/bin/git "$@"
}

[[ -d "$REPO/.git" ]] || fail "primary source checkout is missing"
[[ "$(git_as_andris -C "$REPO" branch --show-current)" == 'main' ]] || fail "source checkout branch must be main"
[[ "$(git_as_andris -C "$REPO" rev-parse HEAD)" == "$EXPECTED_SHA" ]] || fail "source checkout HEAD mismatch"
[[ -z "$(git_as_andris -C "$REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail "source checkout is not clean"
REMOTE="$(git_as_andris -C "$REPO" remote get-url origin)"
case "$REMOTE" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git)
    ;;
  *)
    fail "source checkout origin is not the Hermes Deals repository"
    ;;
esac

for relative in "$VALIDATOR_REL" "$DIAGNOSTIC_REL" "$HELPER_REL" "$FREEZE_REL" "$CARD_REL" "$DISCOVERY_REL"; do
  git_as_andris -C "$REPO" ls-files --error-unmatch "$relative" >/dev/null || fail "required source is not tracked: $relative"
  [[ -f "$REPO/$relative" && ! -L "$REPO/$relative" ]] || fail "required source is missing or unsafe: $relative"
done
[[ -d "$RETAINED_ROOT" && ! -L "$RETAINED_ROOT" ]] || fail "retained evidence root is unavailable or unsafe"

VALIDATOR_SHA="$(sha256sum "$REPO/$VALIDATOR_REL" | awk '{print $1}')"
DIAGNOSTIC_SHA="$(sha256sum "$REPO/$DIAGNOSTIC_REL" | awk '{print $1}')"
HELPER_SHA="$(sha256sum "$REPO/$HELPER_REL" | awk '{print $1}')"
FREEZE_SHA="$(sha256sum "$REPO/$FREEZE_REL" | awk '{print $1}')"
CARD_SHA="$(sha256sum "$REPO/$CARD_REL" | awk '{print $1}')"
DISCOVERY_SHA="$(sha256sum "$REPO/$DISCOVERY_REL" | awk '{print $1}')"

TMP="$(mktemp -d /tmp/hermes-deals-kaufland-k3c-bridge.XXXXXX)"
cleanup() {
  rm -rf -- "$TMP"
}
trap cleanup EXIT

install -d -o root -g root -m 0755 "$RUNTIME_ROOT" "$(dirname "$CONFIG")"
install -d -o andris -g andris -m 0700 "$STAGING_ROOT"
install -o root -g root -m 0644 "$REPO/$VALIDATOR_REL" "$VALIDATOR"

cat > "$TMP/config" <<EOF
audit_name='kaufland-k3c-promo-structure'
commit_sha='$EXPECTED_SHA'
repo='$REPO'
retained_root='$RETAINED_ROOT'
validator='$VALIDATOR'
validator_sha256='$VALIDATOR_SHA'
diagnostic_relative='$DIAGNOSTIC_REL'
diagnostic_sha256='$DIAGNOSTIC_SHA'
helper_relative='$HELPER_REL'
helper_sha256='$HELPER_SHA'
freeze_relative='$FREEZE_REL'
freeze_sha256='$FREEZE_SHA'
card_relative='$CARD_REL'
card_sha256='$CARD_SHA'
discovery_relative='$DISCOVERY_REL'
discovery_sha256='$DISCOVERY_SHA'
EOF
install -o root -g root -m 0644 "$TMP/config" "$CONFIG"

cat > "$TMP/dispatcher" <<'DISPATCH'
#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH PYTHONDONTWRITEBYTECODE=1

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ ${EUID:-$(id -u)} -eq 0 ]] || fail "dispatcher must run as root through sudo"
[[ $# -eq 2 ]] || fail "usage: hermes-deals-kaufland-k3c-promo-structure-dispatch <registered-commit-sha> <artifact-dir>"

EXPECTED_SHA="$1"
EXPORT_DIR="$(readlink -f -- "$2")"
CONFIG='/etc/hermes-deals-audits.d/kaufland-k3c-promo-structure.conf'
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid commit SHA"
[[ -f "$CONFIG" && ! -L "$CONFIG" ]] || fail "Kaufland K3C bridge is not registered"
[[ "$(stat -c '%U:%G %a' "$CONFIG")" == 'root:root 644' ]] || fail "bridge config metadata invalid"
# shellcheck disable=SC1090
source "$CONFIG"

[[ "${audit_name:-}" == 'kaufland-k3c-promo-structure' ]] || fail "bridge audit identity mismatch"
[[ "${commit_sha:-}" == "$EXPECTED_SHA" ]] || fail "registered commit identity mismatch"
[[ "${repo:-}" == '/home/andris/hermes-deals' ]] || fail "registered repo path mismatch"
[[ "${retained_root:-}" == '/home/andris/hermes-deals-retained-evidence' ]] || fail "registered retained root mismatch"
[[ "${validator:-}" == '/usr/local/libexec/hermes-deals-audits/kaufland-k3c-promo-structure/validator.py' ]] || fail "registered validator path mismatch"

for digest in \
  "$validator_sha256" "$diagnostic_sha256" "$helper_sha256" \
  "$freeze_sha256" "$card_sha256" "$discovery_sha256"; do
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || fail "registered source SHA-256 is invalid"
done

[[ -f "$validator" && ! -L "$validator" ]] || fail "registered validator is missing or unsafe"
[[ "$(stat -c '%U:%G %a' "$validator")" == 'root:root 644' ]] || fail "registered validator metadata invalid"
[[ "$(sha256sum "$validator" | awk '{print $1}')" == "$validator_sha256" ]] || fail "registered validator content drift"

git_as_andris() {
  runuser -u andris -- /usr/bin/env -i \
    HOME=/home/andris USER=andris LOGNAME=andris \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    GIT_OPTIONAL_LOCKS=0 \
    /usr/bin/git "$@"
}

[[ -d "$repo/.git" ]] || fail "source checkout is missing"
[[ "$(git_as_andris -C "$repo" branch --show-current)" == 'main' ]] || fail "source checkout branch must be main"
[[ "$(git_as_andris -C "$repo" rev-parse HEAD)" == "$EXPECTED_SHA" ]] || fail "source checkout HEAD mismatch"
[[ -z "$(git_as_andris -C "$repo" status --porcelain=v1 --untracked-files=all)" ]] || fail "source checkout is not clean"
REMOTE="$(git_as_andris -C "$repo" remote get-url origin)"
case "$REMOTE" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git)
    ;;
  *)
    fail "source checkout origin mismatch"
    ;;
esac

verify_source() {
  local relative="$1"
  local expected="$2"
  git_as_andris -C "$repo" ls-files --error-unmatch "$relative" >/dev/null || fail "required source is not tracked: $relative"
  [[ -f "$repo/$relative" && ! -L "$repo/$relative" ]] || fail "required source is missing or unsafe: $relative"
  [[ "$(sha256sum "$repo/$relative" | awk '{print $1}')" == "$expected" ]] || fail "required source content drift: $relative"
}
verify_source "$diagnostic_relative" "$diagnostic_sha256"
verify_source "$helper_relative" "$helper_sha256"
verify_source "$freeze_relative" "$freeze_sha256"
verify_source "$card_relative" "$card_sha256"
verify_source "$discovery_relative" "$discovery_sha256"

[[ -d "$retained_root" && ! -L "$retained_root" ]] || fail "retained evidence root is unavailable or unsafe"
[[ -d "$EXPORT_DIR" && ! -L "$EXPORT_DIR" ]] || fail "artifact directory is missing or unsafe"
[[ "$EXPORT_DIR" == /home/github-runner/_work/_temp/hermes-deals-kaufland-k3c-promo-structure-* ]] || fail "artifact directory outside runner temp allowlist"
[[ "$(stat -c '%U:%G %a' "$EXPORT_DIR")" == 'github-runner:github-runner 700' ]] || fail "artifact directory metadata invalid"

RUN_KEY="$(basename -- "$EXPORT_DIR")"
[[ "$RUN_KEY" =~ ^hermes-deals-kaufland-k3c-promo-structure-[1-9][0-9]*-[1-9][0-9]*$ ]] || fail "unexpected runner artifact directory name"
STAGING_DIR="$STAGING_ROOT/$RUN_KEY"
[[ ! -e "$STAGING_DIR" ]] || fail "private staging directory already exists"
install -d -o andris -g andris -m 0700 "$STAGING_DIR"

cleanup_staging() {
  rm -rf -- "$STAGING_DIR"
}
trap cleanup_staging EXIT

publish_manifest() {
  /usr/bin/python3 - "$STAGING_DIR" <<'PY'
import hashlib
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
allowed = {
    "kaufland-k3c-promo-structure-diagnostic.json",
    "kaufland-k3c-promo-structure-summary.json",
}
files = {}
for path in sorted(root.iterdir()):
    if path.name in allowed and path.is_file() and not path.is_symlink():
        files[path.name] = {
            "bytes": path.stat().st_size,
            "sha256": hashlib.sha256(path.read_bytes()).hexdigest(),
        }
(root / "artifact-manifest.json").write_text(
    json.dumps(
        {
            "schema_version": 1,
            "audit": "kaufland-k3c-promo-structure",
            "files": files,
            "production_deploy_authorized": False,
            "host_mutation_authorized": False,
        },
        indent=2,
        sort_keys=True,
    )
    + "\n",
    encoding="utf-8",
)
PY
}

copy_exports() {
  publish_manifest
  local name
  for name in \
    kaufland-k3c-promo-structure-diagnostic.json \
    kaufland-k3c-promo-structure-summary.json \
    artifact-manifest.json; do
    if [[ -f "$STAGING_DIR/$name" && ! -L "$STAGING_DIR/$name" ]]; then
      install -o github-runner -g github-runner -m 0600 "$STAGING_DIR/$name" "$EXPORT_DIR/$name"
    fi
  done
}

bridge_block() {
  local reason="$1"
  local diagnostic_rc="${2:-}"
  rm -f -- "$STAGING_DIR/kaufland-k3c-promo-structure-diagnostic.json"
  /usr/bin/python3 - "$STAGING_DIR/kaufland-k3c-promo-structure-summary.json" "$EXPECTED_SHA" "$reason" "$diagnostic_rc" <<'PY'
import json
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
sha = sys.argv[2]
reason = sys.argv[3]
diagnostic_rc = sys.argv[4] or None
if not re.fullmatch(r"[A-Z0-9_]{1,96}", reason):
    reason = "BRIDGE_BLOCKED"
payload = {
    "bridge_schema_version": 1,
    "bridge_contract_version": "kaufland-k3c-promo-structure-rpi5-bridge-v1",
    "bridge_execution_status": "BLOCKED",
    "registered_commit_sha": sha,
    "diagnostic_status": "UNAVAILABLE",
    "reason_code": reason,
    "diagnostic_exit_code": int(diagnostic_rc) if diagnostic_rc and diagnostic_rc.lstrip("-").isdigit() else None,
    "evidence_only": True,
    "promo_role_promoted": False,
    "production_deploy_authorized": False,
    "host_mutation_authorized": False,
}
path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
  copy_exports
  printf 'BRIDGE_EXECUTION_STATUS=BLOCKED\nREASON_CODE=%s\nPRODUCTION_DEPLOY_AUTHORIZED=false\n' "$reason"
  exit 30
}

HEAD_BEFORE="$(git_as_andris -C "$repo" rev-parse HEAD)"
STATUS_BEFORE="$(git_as_andris -C "$repo" status --porcelain=v1 --untracked-files=all)"
[[ "$HEAD_BEFORE" == "$EXPECTED_SHA" && -z "$STATUS_BEFORE" ]] || bridge_block "SOURCE_PRECONDITION_DRIFT"

RAW="$STAGING_DIR/diagnostic-raw.json"
STDERR_PRIVATE="$STAGING_DIR/diagnostic-stderr.private"
set +e
runuser -u andris -- /usr/bin/env -i \
  HOME=/home/andris USER=andris LOGNAME=andris \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONHASHSEED=0 \
  /bin/bash --noprofile --norc -c \
  'cd /home/andris/hermes-deals/backend && exec /usr/bin/python3 -m app.kaufland_k3c_promo_structure_diagnostic --retained-root /home/andris/hermes-deals-retained-evidence' \
  >"$RAW" 2>"$STDERR_PRIVATE"
DIAGNOSTIC_RC=$?
set -e

if [[ "$DIAGNOSTIC_RC" -ne 0 && "$DIAGNOSTIC_RC" -ne 20 ]]; then
  bridge_block "DIAGNOSTIC_PROCESS_EXIT_UNEXPECTED" "$DIAGNOSTIC_RC"
fi

SANITIZED="$STAGING_DIR/kaufland-k3c-promo-structure-diagnostic.json"
SUMMARY="$STAGING_DIR/kaufland-k3c-promo-structure-summary.json"
set +e
/usr/bin/python3 "$validator" \
  --raw "$RAW" \
  --artifact "$SANITIZED" \
  --summary "$SUMMARY" \
  --expected-sha "$EXPECTED_SHA" \
  --diagnostic-rc "$DIAGNOSTIC_RC" \
  >/dev/null 2>&1
VALIDATOR_RC=$?
set -e
if [[ "$VALIDATOR_RC" -ne 0 ]]; then
  bridge_block "SANITIZED_OUTPUT_VALIDATION_FAILED" "$DIAGNOSTIC_RC"
fi

HEAD_AFTER="$(git_as_andris -C "$repo" rev-parse HEAD)"
STATUS_AFTER="$(git_as_andris -C "$repo" status --porcelain=v1 --untracked-files=all)"
if [[ "$HEAD_AFTER" != "$HEAD_BEFORE" || -n "$STATUS_AFTER" ]]; then
  bridge_block "SOURCE_CHECKOUT_CHANGED_DURING_DIAGNOSTIC" "$DIAGNOSTIC_RC"
fi

rm -f -- "$RAW" "$STDERR_PRIVATE"
copy_exports
DIAGNOSTIC_STATUS="$(/usr/bin/python3 - "$SUMMARY" <<'PY'
import json
import pathlib
import sys
payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
print(payload["diagnostic_status"])
PY
)"
printf 'BRIDGE_EXECUTION_STATUS=PASS\nDIAGNOSTIC_STATUS=%s\nPRODUCTION_DEPLOY_AUTHORIZED=false\n' "$DIAGNOSTIC_STATUS"
DISPATCH

install -o root -g root -m 0755 "$TMP/dispatcher" "$DISPATCHER"

cat > "$TMP/sudoers" <<EOF
Defaults!$DISPATCHER env_reset,secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
github-runner ALL=(root) NOPASSWD: $DISPATCHER
EOF
chmod 0440 "$TMP/sudoers"
visudo -cf "$TMP/sudoers" >/dev/null
install -o root -g root -m 0440 "$TMP/sudoers" "$SUDOERS"
visudo -cf "$SUDOERS" >/dev/null

sudo -l -U github-runner | grep -Fq "$DISPATCHER" || fail "github-runner dispatcher sudo rule was not installed"

printf 'INSTALL_RESULT=PASS\nREGISTERED_SHA=%s\nVALIDATOR_SHA256=%s\nDIAGNOSTIC_SHA256=%s\nDIAGNOSTIC_EXECUTED=false\nPRODUCTION_DEPLOY_AUTHORIZED=false\n' \
  "$EXPECTED_SHA" "$VALIDATOR_SHA" "$DIAGNOSTIC_SHA"
