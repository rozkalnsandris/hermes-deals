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

[[ ${EUID:-$(id -u)} -ne 0 ]] || fail "run as the unprivileged andris user, not root"
[[ "$(id -un)" == 'andris' ]] || fail "runtime builder must run as andris"
[[ $# -eq 1 ]] || fail "usage: bash tools/runner/build-kaufland-k3c-python-runtime.sh <registration-merge-sha>"

REGISTRATION_SHA="$1"
REPO='/home/andris/hermes-deals'
CACHE_ROOT='/home/andris/.cache/hermes-deals-kaufland-k3c-python-runtime'
PROVISIONER_REL='tools/runner/build-kaufland-k3c-python-runtime.sh'
RUNTIME_CONTRACT_REL='tools/runner/kaufland_k3c_python_runtime_contract.py'
LOCK_MANIFEST_REL='backend/locks/manifest.json'
LOCK_VERIFIER_REL='scripts/verify-python-lock-environment.py'
RUNTIME_PY311_REL='backend/locks/runtime-py311.txt'
RUNTIME_PY313_REL='backend/locks/runtime-py313.txt'

[[ "$REGISTRATION_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "registration SHA is invalid"
for command in awk basename git grep id mkdir mv python3 readlink sha256sum stat; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
[[ -d "$REPO" && ! -L "$REPO" && -d "$REPO/.git" && ! -L "$REPO/.git" ]] || fail "source checkout is missing or unsafe"
[[ "$(readlink -f -- "$REPO")" == "$REPO" ]] || fail "source checkout path drift"
[[ "$(stat -c '%U:%G' "$REPO")" == 'andris:andris' ]] || fail "source checkout owner drift"
[[ "$(git -C "$REPO" rev-parse --is-shallow-repository)" == 'false' ]] || fail "shallow source checkout is unsupported"
[[ "$(git -C "$REPO" branch --show-current)" == 'main' ]] || fail "source checkout branch must be main"
CURRENT_HEAD="$(git -C "$REPO" rev-parse HEAD)"
[[ "$CURRENT_HEAD" =~ ^[0-9a-f]{40}$ ]] || fail "source checkout HEAD is invalid"
[[ -z "$(git -C "$REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail "source checkout is not clean"
git -C "$REPO" cat-file -e "${REGISTRATION_SHA}^{commit}" || fail "registration SHA is unavailable"
git -C "$REPO" merge-base --is-ancestor "$REGISTRATION_SHA" "$CURRENT_HEAD" || fail "registration SHA is not an ancestor of current main"
REMOTE="$(git -C "$REPO" remote get-url origin)"
case "$REMOTE" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git)
    ;;
  *) fail "source checkout origin mismatch" ;;
esac

source_matches_registration() {
  local relative="$1"
  local registration_blob current_blob
  git -C "$REPO" ls-files --error-unmatch "$relative" >/dev/null || fail "required runtime source is not tracked: $relative"
  [[ -f "$REPO/$relative" && ! -L "$REPO/$relative" ]] || fail "required runtime source is missing or unsafe: $relative"
  registration_blob="$(git -C "$REPO" rev-parse "${REGISTRATION_SHA}:${relative}")" || fail "required runtime source missing at registration SHA: $relative"
  current_blob="$(git -C "$REPO" rev-parse "HEAD:${relative}")" || fail "required runtime source missing at current HEAD: $relative"
  [[ "$registration_blob" == "$current_blob" ]] || fail "runtime source changed after registration SHA: $relative"
}

for relative in \
  "$PROVISIONER_REL" "$RUNTIME_CONTRACT_REL" "$LOCK_MANIFEST_REL" "$LOCK_VERIFIER_REL" \
  "$RUNTIME_PY311_REL" "$RUNTIME_PY313_REL"; do
  source_matches_registration "$relative"
done

PROVISIONER_SHA="$(sha256sum "$REPO/$PROVISIONER_REL" | awk '{print $1}')"
RUNTIME_CONTRACT_SHA="$(sha256sum "$REPO/$RUNTIME_CONTRACT_REL" | awk '{print $1}')"
LOCK_MANIFEST_SHA="$(sha256sum "$REPO/$LOCK_MANIFEST_REL" | awk '{print $1}')"
LOCK_VERIFIER_SHA="$(sha256sum "$REPO/$LOCK_VERIFIER_REL" | awk '{print $1}')"
for digest in "$PROVISIONER_SHA" "$RUNTIME_CONTRACT_SHA" "$LOCK_MANIFEST_SHA" "$LOCK_VERIFIER_SHA"; do
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || fail "runtime source SHA-256 is invalid"
done

PYTHON_IMPLEMENTATION="$(/usr/bin/python3 -c 'import platform; print(platform.python_implementation())')"
PYTHON_VERSION="$(/usr/bin/python3 -c 'import platform; print(platform.python_version())')"
PYTHON_LINE="$(/usr/bin/python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
[[ "$PYTHON_IMPLEMENTATION" == 'CPython' ]] || fail "K3C audit runtime requires CPython"
case "$PYTHON_LINE" in
  3.11) RUNTIME_LOCK_REL="$RUNTIME_PY311_REL" ;;
  3.13) RUNTIME_LOCK_REL="$RUNTIME_PY313_REL" ;;
  *) fail "unsupported K3C audit CPython line: $PYTHON_LINE" ;;
esac
RUNTIME_LOCK="$REPO/$RUNTIME_LOCK_REL"

MANIFEST_RECORD="$(/usr/bin/python3 - "$REPO/$LOCK_MANIFEST_REL" "$(basename "$RUNTIME_LOCK_REL")" <<'PY'
import json
import pathlib
import re
import sys
manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
entry = (manifest.get("locks") or {}).get(sys.argv[2])
if not isinstance(entry, dict):
    raise SystemExit("selected runtime lock is absent from manifest")
python_line = entry.get("python")
sha256 = entry.get("sha256")
if not isinstance(python_line, str) or not re.fullmatch(r"[0-9]+\.[0-9]+", python_line):
    raise SystemExit("runtime lock manifest python identity is invalid")
if not isinstance(sha256, str) or not re.fullmatch(r"[0-9a-f]{64}", sha256):
    raise SystemExit("runtime lock manifest SHA-256 is invalid")
print(f"{python_line} {sha256}")
PY
)" || fail "cannot resolve selected runtime lock from manifest"
read -r MANIFEST_PYTHON_LINE RUNTIME_LOCK_SHA <<<"$MANIFEST_RECORD"
[[ "$MANIFEST_PYTHON_LINE" == "$PYTHON_LINE" ]] || fail "selected runtime lock Python line mismatch"
[[ "$(sha256sum "$RUNTIME_LOCK" | awk '{print $1}')" == "$RUNTIME_LOCK_SHA" ]] || fail "selected runtime lock content drift"
/usr/bin/python3 -m venv --help >/dev/null 2>&1 || fail "system Python venv module is unavailable"

RUNTIME_IDENTITY_SHA="$(printf '%s\n' \
  'kaufland-k3c-hash-locked-python-runtime-v1' \
  "$REGISTRATION_SHA" "$PYTHON_IMPLEMENTATION" "$PYTHON_VERSION" "$PYTHON_LINE" \
  "$RUNTIME_LOCK_REL" "$RUNTIME_LOCK_SHA" "$LOCK_MANIFEST_SHA" \
  "$LOCK_VERIFIER_SHA" "$PROVISIONER_SHA" "$RUNTIME_CONTRACT_SHA" | sha256sum | awk '{print $1}')"
[[ "$RUNTIME_IDENTITY_SHA" =~ ^[0-9a-f]{64}$ ]] || fail "runtime identity SHA-256 is invalid"
FINAL_DIR="$CACHE_ROOT/candidate-$RUNTIME_IDENTITY_SHA"
[[ ! -e "$FINAL_DIR" ]] || fail "K3C audit runtime candidate already exists"

STAGING_DIR="$CACHE_ROOT/.staging-${RUNTIME_IDENTITY_SHA}-$$"
MUTATION_STARTED=false
PRESERVED_PATH="$STAGING_DIR"
build_exit() {
  if [[ "${MUTATION_STARTED:-false}" == true ]]; then
    printf 'RUNTIME_BUILD_EVIDENCE_PRESERVED=%s\n' "$PRESERVED_PATH" >&2
  fi
}
trap build_exit EXIT

# Host/network mutation is bounded to this K3C-specific candidate directory.
MUTATION_STARTED=true
mkdir -p -m 0700 "$CACHE_ROOT"
mkdir -m 0700 "$STAGING_DIR"
/usr/bin/python3 -m venv --copies "$STAGING_DIR/venv"
STAGING_PYTHON="$STAGING_DIR/venv/bin/python"
[[ -f "$STAGING_PYTHON" && ! -L "$STAGING_PYTHON" && -x "$STAGING_PYTHON" ]] || fail "staged venv Python is missing or unsafe"
/usr/bin/env -i \
  HOME=/home/andris USER=andris LOGNAME=andris \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 LC_ALL=C.UTF-8 PIP_CONFIG_FILE=/dev/null PIP_NO_INPUT=1 \
  "$STAGING_PYTHON" -m pip install \
    --disable-pip-version-check \
    --no-cache-dir \
    --require-hashes \
    --only-binary=:all: \
    -r "$RUNTIME_LOCK"
/usr/bin/env -i \
  HOME=/home/andris USER=andris LOGNAME=andris \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 LC_ALL=C.UTF-8 PIP_CONFIG_FILE=/dev/null \
  "$STAGING_PYTHON" -m pip check >/dev/null
RUNTIME_ENVIRONMENT_REPORT="$(/usr/bin/env -i \
  HOME=/home/andris USER=andris LOGNAME=andris \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 \
  "$STAGING_PYTHON" "$REPO/$LOCK_VERIFIER_REL" "$RUNTIME_LOCK")" || fail "staged runtime environment does not match reviewed lock"
printf '%s\n' "$RUNTIME_ENVIRONMENT_REPORT" | grep -Fxq 'PYTHON_LOCK_ENVIRONMENT=PASS' || fail "runtime lock verifier did not report PASS"
RUNTIME_INVENTORY_SHA="$(printf '%s\n' "$RUNTIME_ENVIRONMENT_REPORT" | awk -F= '$1 == "LOCKED_INVENTORY_SHA256" { print $2 }')"
[[ "$RUNTIME_INVENTORY_SHA" =~ ^[0-9a-f]{64}$ ]] || fail "runtime inventory SHA-256 is invalid"
/usr/bin/env -i \
  HOME=/home/andris USER=andris LOGNAME=andris \
  PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin \
  LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 \
  "$STAGING_PYTHON" -c 'import bs4, httpx' >/dev/null 2>&1 || fail "staged runtime third-party import verification failed"
RUNTIME_PYTHON_BINARY_SHA="$(sha256sum "$STAGING_PYTHON" | awk '{print $1}')"
[[ "$RUNTIME_PYTHON_BINARY_SHA" =~ ^[0-9a-f]{64}$ ]] || fail "runtime Python binary SHA-256 is invalid"
RUNTIME_TREE_SHA="$(/usr/bin/python3 "$REPO/$RUNTIME_CONTRACT_REL" tree-sha --root "$STAGING_DIR/venv")" || fail "cannot fingerprint staged runtime tree"
[[ "$RUNTIME_TREE_SHA" =~ ^[0-9a-f]{64}$ ]] || fail "runtime tree SHA-256 is invalid"

cat > "$STAGING_DIR/candidate-receipt.json" <<EOF_RECEIPT
{
  "schema_version": 1,
  "contract_version": "kaufland-k3c-hash-locked-python-runtime-v1",
  "registration_sha": "$REGISTRATION_SHA",
  "runtime_identity_sha256": "$RUNTIME_IDENTITY_SHA",
  "python_implementation": "$PYTHON_IMPLEMENTATION",
  "python_version": "$PYTHON_VERSION",
  "python_line": "$PYTHON_LINE",
  "python_binary_sha256": "$RUNTIME_PYTHON_BINARY_SHA",
  "runtime_lock_relative": "$RUNTIME_LOCK_REL",
  "runtime_lock_sha256": "$RUNTIME_LOCK_SHA",
  "runtime_inventory_sha256": "$RUNTIME_INVENTORY_SHA",
  "runtime_tree_sha256": "$RUNTIME_TREE_SHA",
  "lock_manifest_sha256": "$LOCK_MANIFEST_SHA",
  "lock_verifier_sha256": "$LOCK_VERIFIER_SHA",
  "provisioner_sha256": "$PROVISIONER_SHA",
  "runtime_contract_sha256": "$RUNTIME_CONTRACT_SHA",
  "diagnostic_executed": false,
  "retained_evidence_read_performed": false,
  "retained_evidence_write_performed": false,
  "production_database_write_performed": false,
  "production_deploy_performed": false
}
EOF_RECEIPT

mv -- "$STAGING_DIR" "$FINAL_DIR"
PRESERVED_PATH="$FINAL_DIR"
FINAL_VERIFICATION="$(/usr/bin/python3 "$REPO/$RUNTIME_CONTRACT_REL" verify \
  --runtime-root "$FINAL_DIR" \
  --repo "$REPO" \
  --registration-sha "$REGISTRATION_SHA" \
  --expected-provisioner-sha "$PROVISIONER_SHA" \
  --expected-runtime-contract-sha "$RUNTIME_CONTRACT_SHA" \
  --expected-lock-manifest-sha "$LOCK_MANIFEST_SHA" \
  --expected-lock-verifier-sha "$LOCK_VERIFIER_SHA")" || fail "final runtime candidate verification failed"
printf '%s\n' "$FINAL_VERIFICATION" | grep -Fxq 'RUNTIME_CONTRACT=PASS' || fail "final runtime contract did not report PASS"
MUTATION_STARTED=false
trap - EXIT
printf 'RUNTIME_BUILD_RESULT=PASS\n'
printf 'REGISTERED_BRIDGE_SHA=%s\n' "$REGISTRATION_SHA"
printf 'RUNTIME_CANDIDATE_DIR=%s\n' "$FINAL_DIR"
printf 'RUNTIME_IDENTITY_SHA256=%s\n' "$RUNTIME_IDENTITY_SHA"
printf 'RUNTIME_TREE_SHA256=%s\n' "$RUNTIME_TREE_SHA"
printf 'RUNTIME_PYTHON_IMPLEMENTATION=%s\n' "$PYTHON_IMPLEMENTATION"
printf 'RUNTIME_PYTHON_VERSION=%s\n' "$PYTHON_VERSION"
printf 'RUNTIME_LOCK_RELATIVE=%s\n' "$RUNTIME_LOCK_REL"
printf 'RUNTIME_LOCK_SHA256=%s\n' "$RUNTIME_LOCK_SHA"
printf 'RUNTIME_INVENTORY_SHA256=%s\n' "$RUNTIME_INVENTORY_SHA"
printf 'RUNTIME_PYTHON_BINARY_SHA256=%s\n' "$RUNTIME_PYTHON_BINARY_SHA"
printf 'HOST_MUTATION_PERFORMED=true\n'
printf 'NETWORK_PACKAGE_INSTALL_PERFORMED=true\n'
printf 'DIAGNOSTIC_EXECUTED=false\n'
printf 'RETAINED_EVIDENCE_READ_PERFORMED=false\n'
printf 'RETAINED_EVIDENCE_WRITE_PERFORMED=false\n'
printf 'DATABASE_WRITE_PERFORMED=false\n'
printf 'PRODUCTION_DEPLOY_PERFORMED=false\n'