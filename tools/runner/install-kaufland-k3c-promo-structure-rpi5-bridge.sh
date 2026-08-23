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
[[ $# -eq 1 ]] || fail "usage: sudo bash tools/runner/install-kaufland-k3c-promo-structure-rpi5-bridge.sh <registration-merge-sha>"

REGISTRATION_SHA="$1"
# V1 coupled this role under the legacy name EXPECTED_SHA; v2 keeps registration and execution identities separate.
REPO='/home/andris/hermes-deals'
RETAINED_ROOT='/home/andris/hermes-deals-retained-evidence'
RUNTIME_ROOT='/usr/local/libexec/hermes-deals-audits/kaufland-k3c-promo-structure'
VALIDATOR="$RUNTIME_ROOT/validator.py"
DISPATCHER='/usr/local/sbin/hermes-deals-kaufland-k3c-promo-structure-dispatch'
CONFIG='/etc/hermes-deals-audits.d/kaufland-k3c-promo-structure.conf'
SUDOERS='/etc/sudoers.d/hermes-deals-kaufland-k3c-promo-structure'
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'
WORKFLOW_REL='.github/workflows/kaufland-k3c-promo-structure-rpi5.yml'
INSTALLER_REL='tools/runner/install-kaufland-k3c-promo-structure-rpi5-bridge.sh'
VALIDATOR_REL='tools/runner/kaufland_k3c_promo_structure_bridge_validator.py'
DIAGNOSTIC_REL='backend/app/kaufland_k3c_promo_structure_diagnostic.py'
HELPER_REL='backend/app/kaufland_real_k2_v2_derivation.py'
FREEZE_REL='backend/app/kaufland_evidence_freeze.py'
CARD_REL='backend/app/kaufland_source_card_contract.py'
DISCOVERY_REL='backend/app/kaufland_source_discovery.py'

[[ "$REGISTRATION_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "registration SHA is invalid"
for user in github-runner andris; do
  id "$user" >/dev/null 2>&1 || fail "required local user is missing: $user"
done
for command in bash git grep id install mktemp python3 readlink runuser sha256sum stat sudo visudo; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
if id -nG github-runner | tr ' ' '\n' | grep -Fxq docker; then
  fail "github-runner must not hold container-engine group membership"
fi

git_as_andris() {
  runuser -u andris -- /usr/bin/env -i \
    HOME=/home/andris USER=andris LOGNAME=andris \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    GIT_OPTIONAL_LOCKS=0 GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false \
    GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null \
    /usr/bin/git "$@"
}

[[ -d "$REPO" && ! -L "$REPO" ]] || fail "primary source checkout is missing or unsafe"
[[ "$(readlink -f -- "$REPO")" == "$REPO" ]] || fail "primary source checkout path drift"
[[ "$(stat -c '%U:%G' "$REPO")" == 'andris:andris' ]] || fail "primary source checkout owner drift"
[[ -d "$REPO/.git" && ! -L "$REPO/.git" ]] || fail "primary source checkout .git is missing or unsafe"
[[ "$(git_as_andris -C "$REPO" rev-parse --is-inside-work-tree)" == 'true' ]] || fail "primary source checkout is not a Git worktree"
[[ "$(git_as_andris -C "$REPO" rev-parse --is-shallow-repository)" == 'false' ]] || fail "shallow checkout is unsupported"
[[ "$(git_as_andris -C "$REPO" branch --show-current)" == 'main' ]] || fail "source checkout branch must be main"
CURRENT_HEAD="$(git_as_andris -C "$REPO" rev-parse HEAD)"
[[ "$CURRENT_HEAD" =~ ^[0-9a-f]{40}$ ]] || fail "source checkout HEAD is invalid"
[[ -z "$(git_as_andris -C "$REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail "source checkout is not clean"
REMOTE="$(git_as_andris -C "$REPO" remote get-url origin)"
case "$REMOTE" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git)
    ;;
  *) fail "source checkout origin is not the Hermes Deals repository" ;;
esac

git_as_andris -C "$REPO" cat-file -e "${REGISTRATION_SHA}^{commit}" || fail "registration SHA is not available as a commit"
git_as_andris -C "$REPO" merge-base --is-ancestor "$REGISTRATION_SHA" "$CURRENT_HEAD" || fail "registration SHA is not an ancestor of current main"
REGISTRATION_LINE="$(git_as_andris -C "$REPO" rev-list --parents -n 1 "$REGISTRATION_SHA")"
REGISTRATION_PARENT_RE='^([0-9a-f]{40}) ([0-9a-f]{40})$'
[[ "$REGISTRATION_LINE" =~ $REGISTRATION_PARENT_RE ]] || fail "registration SHA must be a single-parent reviewed merge"
REGISTRATION_COMMIT="${BASH_REMATCH[1]}"
REGISTRATION_PARENT="${BASH_REMATCH[2]}"
[[ "$REGISTRATION_COMMIT" == "$REGISTRATION_SHA" ]] || fail "registration SHA must be a single-parent reviewed merge"
REGISTRATION_INSTALLER_BLOB="$(git_as_andris -C "$REPO" rev-parse "${REGISTRATION_SHA}:${INSTALLER_REL}")" || fail "registration SHA does not contain bridge installer"
REGISTRATION_WORKFLOW_BLOB="$(git_as_andris -C "$REPO" rev-parse "${REGISTRATION_SHA}:${WORKFLOW_REL}")" || fail "registration SHA does not contain bridge workflow"
PARENT_INSTALLER_BLOB="$(git_as_andris -C "$REPO" rev-parse "${REGISTRATION_PARENT}:${INSTALLER_REL}" 2>/dev/null || printf MISSING)"
PARENT_WORKFLOW_BLOB="$(git_as_andris -C "$REPO" rev-parse "${REGISTRATION_PARENT}:${WORKFLOW_REL}" 2>/dev/null || printf MISSING)"
REGISTRATION_INSTALLER_CHANGED=false
REGISTRATION_WORKFLOW_CHANGED=false
if [[ "$REGISTRATION_INSTALLER_BLOB" != "$PARENT_INSTALLER_BLOB" ]]; then
  REGISTRATION_INSTALLER_CHANGED=true
fi
if [[ "$REGISTRATION_WORKFLOW_BLOB" != "$PARENT_WORKFLOW_BLOB" ]]; then
  REGISTRATION_WORKFLOW_CHANGED=true
fi
if [[ "$REGISTRATION_INSTALLER_CHANGED" != true && "$REGISTRATION_WORKFLOW_CHANGED" != true ]]; then
  fail "registration SHA did not introduce or update the K3C bridge control plane"
fi

trusted_source_matches_registration() {
  local relative="$1"
  local registration_blob current_blob
  git_as_andris -C "$REPO" ls-files --error-unmatch "$relative" >/dev/null || fail "required source is not tracked: $relative"
  [[ -f "$REPO/$relative" && ! -L "$REPO/$relative" ]] || fail "required source is missing or unsafe: $relative"
  registration_blob="$(git_as_andris -C "$REPO" rev-parse "${REGISTRATION_SHA}:${relative}")" || fail "required source missing at registration SHA: $relative"
  current_blob="$(git_as_andris -C "$REPO" rev-parse "HEAD:${relative}")" || fail "required source missing at current HEAD: $relative"
  [[ "$registration_blob" == "$current_blob" ]] || fail "trusted source changed after registration SHA: $relative"
}

for relative in \
  "$WORKFLOW_REL" "$INSTALLER_REL" "$VALIDATOR_REL" "$DIAGNOSTIC_REL" \
  "$HELPER_REL" "$FREEZE_REL" "$CARD_REL" "$DISCOVERY_REL"; do
  trusted_source_matches_registration "$relative"
done
[[ -d "$RETAINED_ROOT" && ! -L "$RETAINED_ROOT" ]] || fail "retained evidence root is unavailable or unsafe"

WORKFLOW_SHA="$(sha256sum "$REPO/$WORKFLOW_REL" | awk '{print $1}')"
INSTALLER_SHA="$(sha256sum "$REPO/$INSTALLER_REL" | awk '{print $1}')"
VALIDATOR_SHA="$(sha256sum "$REPO/$VALIDATOR_REL" | awk '{print $1}')"
DIAGNOSTIC_SHA="$(sha256sum "$REPO/$DIAGNOSTIC_REL" | awk '{print $1}')"
HELPER_SHA="$(sha256sum "$REPO/$HELPER_REL" | awk '{print $1}')"
FREEZE_SHA="$(sha256sum "$REPO/$FREEZE_REL" | awk '{print $1}')"
CARD_SHA="$(sha256sum "$REPO/$CARD_REL" | awk '{print $1}')"
DISCOVERY_SHA="$(sha256sum "$REPO/$DISCOVERY_REL" | awk '{print $1}')"
for digest in "$WORKFLOW_SHA" "$INSTALLER_SHA" "$VALIDATOR_SHA" "$DIAGNOSTIC_SHA" "$HELPER_SHA" "$FREEZE_SHA" "$CARD_SHA" "$DISCOVERY_SHA"; do
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || fail "trusted source SHA-256 is invalid"
done
/usr/bin/bash -n "$REPO/$INSTALLER_REL" || fail "installer source syntax check failed"

TMP="$(mktemp -d /tmp/hermes-deals-kaufland-k3c-bridge.XXXXXX)"
KEEP_TMP=true
cleanup() {
  if [[ "$KEEP_TMP" == false ]]; then
    rm -rf -- "$TMP"
  else
    printf 'INSTALL_STAGING_PRESERVED=%s\n' "$TMP" >&2
  fi
}
trap cleanup EXIT

cat > "$TMP/config" <<EOF_CONFIG
audit_name='kaufland-k3c-promo-structure'
bridge_contract_version='kaufland-k3c-promo-structure-rpi5-bridge-v2'
registration_sha='$REGISTRATION_SHA'
registration_checkout_sha='$CURRENT_HEAD'
repo='$REPO'
retained_root='$RETAINED_ROOT'
validator='$VALIDATOR'
workflow_relative='$WORKFLOW_REL'
workflow_sha256='$WORKFLOW_SHA'
installer_relative='$INSTALLER_REL'
installer_sha256='$INSTALLER_SHA'
validator_relative='$VALIDATOR_REL'
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
EOF_CONFIG
chmod 0600 "$TMP/config"

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
[[ $# -eq 3 ]] || fail "usage: hermes-deals-kaufland-k3c-promo-structure-dispatch <registration-sha> <execution-checkout-sha> <artifact-dir>"

REGISTRATION_SHA="$1"
EXECUTION_SHA="$2"
EXPORT_DIR="$(readlink -f -- "$3")"
CONFIG='/etc/hermes-deals-audits.d/kaufland-k3c-promo-structure.conf'
STAGING_ROOT='/home/andris/hermes-deals-runner-evidence'

[[ "$REGISTRATION_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid registration SHA"
[[ "$EXECUTION_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid execution SHA"
[[ -f "$CONFIG" && ! -L "$CONFIG" ]] || fail "Kaufland K3C bridge is not registered"
[[ "$(stat -c '%U:%G %a' "$CONFIG")" == 'root:root 644' ]] || fail "bridge config metadata invalid"
# shellcheck disable=SC1090
source "$CONFIG"

[[ "${audit_name:-}" == 'kaufland-k3c-promo-structure' ]] || fail "bridge audit identity mismatch"
[[ "${bridge_contract_version:-}" == 'kaufland-k3c-promo-structure-rpi5-bridge-v2' ]] || fail "bridge contract identity mismatch"
[[ "${registration_sha:-}" == "$REGISTRATION_SHA" ]] || fail "registered bridge identity mismatch"
[[ "${registration_checkout_sha:-}" =~ ^[0-9a-f]{40}$ ]] || fail "registration checkout identity invalid"
[[ "${repo:-}" == '/home/andris/hermes-deals' ]] || fail "registered repo path mismatch"
[[ "${retained_root:-}" == '/home/andris/hermes-deals-retained-evidence' ]] || fail "registered retained root mismatch"
[[ "${validator:-}" == '/usr/local/libexec/hermes-deals-audits/kaufland-k3c-promo-structure/validator.py' ]] || fail "registered validator path mismatch"

for digest in \
  "$workflow_sha256" "$installer_sha256" "$validator_sha256" "$diagnostic_sha256" \
  "$helper_sha256" "$freeze_sha256" "$card_sha256" "$discovery_sha256"; do
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || fail "registered source SHA-256 is invalid"
done

[[ -f "$validator" && ! -L "$validator" ]] || fail "registered validator is missing or unsafe"
[[ "$(stat -c '%U:%G %a' "$validator")" == 'root:root 644' ]] || fail "registered validator metadata invalid"
[[ "$(sha256sum "$validator" | awk '{print $1}')" == "$validator_sha256" ]] || fail "registered validator content drift"

git_as_andris() {
  runuser -u andris -- /usr/bin/env -i \
    HOME=/home/andris USER=andris LOGNAME=andris \
    PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
    LANG=C.UTF-8 LC_ALL=C.UTF-8 \
    GIT_OPTIONAL_LOCKS=0 GIT_TERMINAL_PROMPT=0 GIT_ASKPASS=/bin/false \
    GIT_CONFIG_GLOBAL=/dev/null GIT_CONFIG_SYSTEM=/dev/null \
    /usr/bin/git "$@"
}

[[ -d "$repo" && ! -L "$repo" && -d "$repo/.git" && ! -L "$repo/.git" ]] || fail "source checkout is missing or unsafe"
[[ "$(git_as_andris -C "$repo" rev-parse --is-shallow-repository)" == 'false' ]] || fail "shallow source checkout is unsupported"
[[ "$(git_as_andris -C "$repo" branch --show-current)" == 'main' ]] || fail "source checkout branch must be main"
[[ "$(git_as_andris -C "$repo" rev-parse HEAD)" == "$EXECUTION_SHA" ]] || fail "source checkout execution SHA mismatch"
[[ -z "$(git_as_andris -C "$repo" status --porcelain=v1 --untracked-files=all)" ]] || fail "source checkout is not clean"
REMOTE="$(git_as_andris -C "$repo" remote get-url origin)"
case "$REMOTE" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git)
    ;;
  *) fail "source checkout origin mismatch" ;;
esac

git_as_andris -C "$repo" cat-file -e "${REGISTRATION_SHA}^{commit}" || fail "registration SHA is unavailable"
git_as_andris -C "$repo" merge-base --is-ancestor "$REGISTRATION_SHA" "$EXECUTION_SHA" || fail "execution checkout is not a registration descendant"

verify_source() {
  local relative="$1"
  local expected="$2"
  local registration_blob execution_blob
  git_as_andris -C "$repo" ls-files --error-unmatch "$relative" >/dev/null || fail "required source is not tracked: $relative"
  [[ -f "$repo/$relative" && ! -L "$repo/$relative" ]] || fail "required source is missing or unsafe: $relative"
  [[ "$(sha256sum "$repo/$relative" | awk '{print $1}')" == "$expected" ]] || fail "required source content drift: $relative"
  registration_blob="$(git_as_andris -C "$repo" rev-parse "${REGISTRATION_SHA}:${relative}")" || fail "required source missing at registration SHA: $relative"
  execution_blob="$(git_as_andris -C "$repo" rev-parse "HEAD:${relative}")" || fail "required source missing at execution SHA: $relative"
  [[ "$registration_blob" == "$execution_blob" ]] || fail "required source changed after registration SHA: $relative"
}
verify_source "$workflow_relative" "$workflow_sha256"
verify_source "$installer_relative" "$installer_sha256"
verify_source "$validator_relative" "$validator_sha256"
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
  /usr/bin/python3 - "$STAGING_DIR" "$REGISTRATION_SHA" "$EXECUTION_SHA" <<'PY'
import hashlib
import json
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
registration_sha = sys.argv[2]
execution_sha = sys.argv[3]
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
            "schema_version": 2,
            "audit": "kaufland-k3c-promo-structure",
            "registered_commit_sha": registration_sha,
            "execution_checkout_sha": execution_sha,
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
  /usr/bin/python3 - "$STAGING_DIR/kaufland-k3c-promo-structure-summary.json" "$REGISTRATION_SHA" "$EXECUTION_SHA" "$reason" "$diagnostic_rc" <<'PY'
import json
import pathlib
import re
import sys

path = pathlib.Path(sys.argv[1])
registration_sha = sys.argv[2]
execution_sha = sys.argv[3]
reason = sys.argv[4]
diagnostic_rc = sys.argv[5] or None
if not re.fullmatch(r"[A-Z0-9_]{1,96}", reason):
    reason = "BRIDGE_BLOCKED"
payload = {
    "bridge_schema_version": 2,
    "bridge_contract_version": "kaufland-k3c-promo-structure-rpi5-bridge-v2",
    "bridge_execution_status": "BLOCKED",
    "registered_commit_sha": registration_sha,
    "execution_checkout_sha": execution_sha,
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
  printf 'BRIDGE_EXECUTION_STATUS=BLOCKED\nREASON_CODE=%s\nREGISTERED_COMMIT_SHA=%s\nEXECUTION_CHECKOUT_SHA=%s\nPRODUCTION_DEPLOY_AUTHORIZED=false\n' \
    "$reason" "$REGISTRATION_SHA" "$EXECUTION_SHA"
  exit 30
}

HEAD_BEFORE="$(git_as_andris -C "$repo" rev-parse HEAD)"
STATUS_BEFORE="$(git_as_andris -C "$repo" status --porcelain=v1 --untracked-files=all)"
[[ "$HEAD_BEFORE" == "$EXECUTION_SHA" && -z "$STATUS_BEFORE" ]] || bridge_block "SOURCE_PRECONDITION_DRIFT"

RAW="$STAGING_DIR/diagnostic-raw.json"
STDERR_PRIVATE="$STAGING_DIR/diagnostic-stderr.private"
set +e
runuser -u andris -- /usr/bin/env -i \
  HOME=/home/andris USER=andris LOGNAME=andris \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 \
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
  --expected-sha "$REGISTRATION_SHA" \
  --diagnostic-rc "$DIAGNOSTIC_RC" \
  >/dev/null 2>&1
VALIDATOR_RC=$?
set -e
if [[ "$VALIDATOR_RC" -ne 0 ]]; then
  bridge_block "SANITIZED_OUTPUT_VALIDATION_FAILED" "$DIAGNOSTIC_RC"
fi

set +e
/usr/bin/python3 - "$SANITIZED" "$SUMMARY" "$REGISTRATION_SHA" "$EXECUTION_SHA" <<'PY'
import json
import pathlib
import re
import sys

registration_sha = sys.argv[3]
execution_sha = sys.argv[4]
if not re.fullmatch(r"[0-9a-f]{40}", registration_sha) or not re.fullmatch(r"[0-9a-f]{40}", execution_sha):
    raise SystemExit("invalid bridge identity")
for raw_path in sys.argv[1:3]:
    path = pathlib.Path(raw_path)
    payload = json.loads(path.read_text(encoding="utf-8"))
    if payload.get("bridge_schema_version") != 1:
        raise SystemExit("unexpected validator bridge schema")
    if payload.get("bridge_contract_version") != "kaufland-k3c-promo-structure-rpi5-bridge-v1":
        raise SystemExit("unexpected validator bridge contract")
    if payload.get("registered_commit_sha") != registration_sha:
        raise SystemExit("validator registration identity mismatch")
    if "execution_checkout_sha" in payload:
        raise SystemExit("validator payload already contains execution identity")
    payload["bridge_schema_version"] = 2
    payload["bridge_contract_version"] = "kaufland-k3c-promo-structure-rpi5-bridge-v2"
    payload["execution_checkout_sha"] = execution_sha
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
PY
STAMP_RC=$?
set -e
if [[ "$STAMP_RC" -ne 0 ]]; then
  bridge_block "EXECUTION_IDENTITY_STAMP_FAILED" "$DIAGNOSTIC_RC"
fi

HEAD_AFTER="$(git_as_andris -C "$repo" rev-parse HEAD)"
STATUS_AFTER="$(git_as_andris -C "$repo" status --porcelain=v1 --untracked-files=all)"
if [[ "$HEAD_AFTER" != "$EXECUTION_SHA" || -n "$STATUS_AFTER" ]]; then
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
printf 'BRIDGE_EXECUTION_STATUS=PASS\nDIAGNOSTIC_STATUS=%s\nREGISTERED_COMMIT_SHA=%s\nEXECUTION_CHECKOUT_SHA=%s\nPRODUCTION_DEPLOY_AUTHORIZED=false\n' \
  "$DIAGNOSTIC_STATUS" "$REGISTRATION_SHA" "$EXECUTION_SHA"
DISPATCH

/usr/bin/bash -n "$TMP/dispatcher" || fail "dispatcher syntax validation failed"

cat > "$TMP/sudoers" <<EOF_SUDOERS
Defaults!$DISPATCHER env_reset,secure_path=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin
github-runner ALL=(root) NOPASSWD: $DISPATCHER
EOF_SUDOERS
chmod 0440 "$TMP/sudoers"
visudo -cf "$TMP/sudoers" >/dev/null || fail "Kaufland K3C sudoers validation failed"

# Persistent host registration begins here. No Git or diagnostic execution occurs below.
install -d -o root -g root -m 0755 "$RUNTIME_ROOT" "$(dirname "$CONFIG")"
install -d -o andris -g andris -m 0700 "$STAGING_ROOT"
install -o root -g root -m 0644 "$REPO/$VALIDATOR_REL" "$VALIDATOR"
install -o root -g root -m 0644 "$TMP/config" "$CONFIG"
install -o root -g root -m 0755 "$TMP/dispatcher" "$DISPATCHER"
install -o root -g root -m 0440 "$TMP/sudoers" "$SUDOERS"

visudo -cf "$SUDOERS" >/dev/null || fail "installed K3C sudoers validation failed"
[[ "$(sha256sum "$VALIDATOR" | awk '{print $1}')" == "$VALIDATOR_SHA" ]] || fail "installed validator hash mismatch"
[[ "$(stat -c '%U:%G %a' "$VALIDATOR")" == 'root:root 644' ]] || fail "installed validator metadata mismatch"
[[ "$(stat -c '%U:%G %a' "$CONFIG")" == 'root:root 644' ]] || fail "installed config metadata mismatch"
[[ "$(stat -c '%U:%G %a' "$DISPATCHER")" == 'root:root 755' ]] || fail "installed dispatcher metadata mismatch"
[[ "$(stat -c '%U:%G %a' "$SUDOERS")" == 'root:root 440' ]] || fail "installed sudoers metadata mismatch"
sudo -l -U github-runner | grep -Fq "$DISPATCHER" || fail "github-runner dispatcher sudo rule was not installed"
[[ "$(git_as_andris -C "$REPO" rev-parse HEAD)" == "$CURRENT_HEAD" ]] || fail "source checkout changed during registration"
[[ -z "$(git_as_andris -C "$REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail "source checkout became dirty during registration"

KEEP_TMP=false
printf 'INSTALL_RESULT=PASS\n'
printf 'REGISTERED_BRIDGE_SHA=%s\n' "$REGISTRATION_SHA"
printf 'REGISTRATION_CHECKOUT_SHA=%s\n' "$CURRENT_HEAD"
printf 'VALIDATOR_SHA256=%s\n' "$VALIDATOR_SHA"
printf 'DIAGNOSTIC_SHA256=%s\n' "$DIAGNOSTIC_SHA"
printf 'RUNNER_HAS_DOCKER_GROUP=false\n'
printf 'SOURCE_CHECKOUT_MUTATED=false\n'
printf 'SOURCE_SYNC_EXECUTED=false\n'
printf 'DIAGNOSTIC_EXECUTED=false\n'
printf 'RETAINED_EVIDENCE_READ_PERFORMED=false\n'
printf 'DATABASE_WRITE_PERFORMED=false\n'
printf 'PRODUCTION_DEPLOY_PERFORMED=false\n'