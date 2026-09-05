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
BOOTSTRAP_REL='tools/runner/kaufland-k3c-python-bootstrap.json'
LOCK_MANIFEST_REL='backend/locks/manifest.json'
LOCK_VERIFIER_REL='scripts/verify-python-lock-environment.py'
RUNTIME_LOCK_REL='backend/locks/runtime-py313.txt'
EXPECTED_PYTHON_LINE='3.13'
EXPECTED_PYTHON_VERSION='3.13.14'
EXPECTED_ARCH='aarch64'

[[ "$REGISTRATION_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "registration SHA is invalid"
for command in awk basename chmod curl find flock git grep id mkdir mv python3 readlink rm sha256sum stat uname wc; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
[[ "$(uname -s)" == 'Linux' ]] || fail "K3C CPython bootstrap requires Linux"
[[ "$(uname -m)" == "$EXPECTED_ARCH" ]] || fail "K3C CPython bootstrap requires $EXPECTED_ARCH"
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
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail "source checkout origin mismatch" ;;
esac

source_matches_registration() {
  local relative="$1" registration_blob current_blob
  git -C "$REPO" ls-files --error-unmatch "$relative" >/dev/null || fail "required runtime source is not tracked: $relative"
  [[ -f "$REPO/$relative" && ! -L "$REPO/$relative" ]] || fail "required runtime source is missing or unsafe: $relative"
  registration_blob="$(git -C "$REPO" rev-parse "${REGISTRATION_SHA}:${relative}")" || fail "required runtime source missing at registration SHA: $relative"
  current_blob="$(git -C "$REPO" rev-parse "HEAD:${relative}")" || fail "required runtime source missing at current HEAD: $relative"
  [[ "$registration_blob" == "$current_blob" ]] || fail "runtime source changed after registration SHA: $relative"
}

for relative in "$PROVISIONER_REL" "$RUNTIME_CONTRACT_REL" "$BOOTSTRAP_REL" "$LOCK_MANIFEST_REL" "$LOCK_VERIFIER_REL" "$RUNTIME_LOCK_REL"; do
  source_matches_registration "$relative"
done

PROVISIONER_SHA="$(sha256sum "$REPO/$PROVISIONER_REL" | awk '{print $1}')"
RUNTIME_CONTRACT_SHA="$(sha256sum "$REPO/$RUNTIME_CONTRACT_REL" | awk '{print $1}')"
BOOTSTRAP_MANIFEST_SHA="$(sha256sum "$REPO/$BOOTSTRAP_REL" | awk '{print $1}')"
LOCK_MANIFEST_SHA="$(sha256sum "$REPO/$LOCK_MANIFEST_REL" | awk '{print $1}')"
LOCK_VERIFIER_SHA="$(sha256sum "$REPO/$LOCK_VERIFIER_REL" | awk '{print $1}')"
for digest in "$PROVISIONER_SHA" "$RUNTIME_CONTRACT_SHA" "$BOOTSTRAP_MANIFEST_SHA" "$LOCK_MANIFEST_SHA" "$LOCK_VERIFIER_SHA"; do
  [[ "$digest" =~ ^[0-9a-f]{64}$ ]] || fail "runtime source SHA-256 is invalid"
done

BOOTSTRAP_RECORD="$(/usr/bin/python3 - "$REPO/$BOOTSTRAP_REL" <<'PY'
import json, pathlib, re, sys
payload = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
if payload.get('schema_version') != 1 or payload.get('contract_version') != 'kaufland-k3c-python-bootstrap-v1':
    raise SystemExit('bootstrap manifest contract mismatch')
release = payload.get('release') or {}
asset = payload.get('asset') or {}
python = payload.get('python') or {}
platform = payload.get('platform') or {}
if release.get('immutable') is not True:
    raise SystemExit('bootstrap release is not immutable')
values = [
    asset.get('download_url'), str(asset.get('asset_id')), asset.get('name'), str(asset.get('size')),
    asset.get('sha256'), python.get('implementation'), python.get('version'), python.get('line'),
    python.get('executable'), platform.get('os'), platform.get('architecture'),
]
if any(not isinstance(value, str) or '\n' in value for value in values):
    raise SystemExit('bootstrap manifest contains invalid scalar')
if not values[0].startswith('https://github.com/astral-sh/python-build-standalone/releases/download/20260805/'):
    raise SystemExit('bootstrap download URL mismatch')
if not re.fullmatch(r'[0-9a-f]{64}', values[4]):
    raise SystemExit('bootstrap asset SHA-256 is invalid')
print('\t'.join(values))
PY
)" || fail "cannot resolve bootstrap manifest"
IFS=$'\t' read -r BOOTSTRAP_URL BOOTSTRAP_ASSET_ID BOOTSTRAP_ASSET_NAME BOOTSTRAP_ASSET_SIZE BOOTSTRAP_ASSET_SHA PYTHON_IMPLEMENTATION PYTHON_VERSION PYTHON_LINE PYTHON_RELATIVE BOOTSTRAP_OS BOOTSTRAP_ARCH <<<"$BOOTSTRAP_RECORD"
IFS=$'\n\t'
[[ "$BOOTSTRAP_ASSET_ID" == '502923386' ]] || fail "bootstrap asset ID mismatch"
[[ "$BOOTSTRAP_ASSET_SIZE" == '89958991' ]] || fail "bootstrap asset size mismatch"
[[ "$PYTHON_IMPLEMENTATION" == 'CPython' && "$PYTHON_VERSION" == "$EXPECTED_PYTHON_VERSION" && "$PYTHON_LINE" == "$EXPECTED_PYTHON_LINE" ]] || fail "bootstrap Python identity mismatch"
[[ "$PYTHON_RELATIVE" == 'python/bin/python3.13' ]] || fail "bootstrap Python executable mismatch"
[[ "$BOOTSTRAP_OS" == 'linux' && "$BOOTSTRAP_ARCH" == "$EXPECTED_ARCH" ]] || fail "bootstrap platform mismatch"

RUNTIME_LOCK="$REPO/$RUNTIME_LOCK_REL"
RUNTIME_LOCK_SHA="$(/usr/bin/python3 - "$REPO/$LOCK_MANIFEST_REL" "$(basename "$RUNTIME_LOCK_REL")" "$EXPECTED_PYTHON_LINE" <<'PY'
import json, pathlib, re, sys
manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding='utf-8'))
entry = (manifest.get('locks') or {}).get(sys.argv[2])
if not isinstance(entry, dict) or entry.get('python') != sys.argv[3]:
    raise SystemExit('runtime lock manifest Python identity mismatch')
sha256 = entry.get('sha256')
if not isinstance(sha256, str) or not re.fullmatch(r'[0-9a-f]{64}', sha256):
    raise SystemExit('runtime lock manifest SHA-256 is invalid')
print(sha256)
PY
)" || fail "cannot resolve selected runtime lock from manifest"
[[ "$(sha256sum "$RUNTIME_LOCK" | awk '{print $1}')" == "$RUNTIME_LOCK_SHA" ]] || fail "selected runtime lock content drift"

RUNTIME_IDENTITY_SHA="$(printf '%s\n' \
  'kaufland-k3c-hash-locked-python-runtime-v2' "$REGISTRATION_SHA" "$PYTHON_IMPLEMENTATION" "$PYTHON_VERSION" "$PYTHON_LINE" \
  "$BOOTSTRAP_MANIFEST_SHA" "$BOOTSTRAP_ASSET_ID" "$BOOTSTRAP_ASSET_SHA" "$RUNTIME_LOCK_REL" "$RUNTIME_LOCK_SHA" \
  "$LOCK_MANIFEST_SHA" "$LOCK_VERIFIER_SHA" "$PROVISIONER_SHA" "$RUNTIME_CONTRACT_SHA" | sha256sum | awk '{print $1}')"
[[ "$RUNTIME_IDENTITY_SHA" =~ ^[0-9a-f]{64}$ ]] || fail "runtime identity SHA-256 is invalid"
FINAL_DIR="$CACHE_ROOT/candidate-$RUNTIME_IDENTITY_SHA"
STAGING_DIR="$CACHE_ROOT/.staging-${RUNTIME_IDENTITY_SHA}-$$"
[[ ! -e "$FINAL_DIR" ]] || fail "K3C audit runtime candidate already exists"

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
[[ "$(stat -c '%U:%G %a' "$CACHE_ROOT")" == 'andris:andris 700' ]] || fail "K3C runtime cache metadata drift"
exec 9>"$CACHE_ROOT/.build.lock"
flock -n 9 || fail "another K3C runtime build is already active"
[[ ! -e "$FINAL_DIR" && ! -e "$STAGING_DIR" ]] || fail "K3C runtime candidate/staging path appeared while acquiring build lock"
mkdir -m 0700 "$STAGING_DIR"
BOOTSTRAP_ARCHIVE="$STAGING_DIR/bootstrap.tar.gz"
curl --fail --location --silent --show-error --proto '=https' --tlsv1.2 --retry 0 --output "$BOOTSTRAP_ARCHIVE" "$BOOTSTRAP_URL"
[[ -f "$BOOTSTRAP_ARCHIVE" && ! -L "$BOOTSTRAP_ARCHIVE" ]] || fail "bootstrap archive is missing or unsafe"
[[ "$(wc -c < "$BOOTSTRAP_ARCHIVE")" == "$BOOTSTRAP_ASSET_SIZE" ]] || fail "bootstrap asset size mismatch"
[[ "$(sha256sum "$BOOTSTRAP_ARCHIVE" | awk '{print $1}')" == "$BOOTSTRAP_ASSET_SHA" ]] || fail "bootstrap asset SHA-256 mismatch"
/usr/bin/python3 "$REPO/$RUNTIME_CONTRACT_REL" safe-extract --archive "$BOOTSTRAP_ARCHIVE" --destination "$STAGING_DIR" | grep -Fxq 'BOOTSTRAP_EXTRACTION=PASS' || fail "bootstrap archive extraction failed"
STAGING_PYTHON="$STAGING_DIR/$PYTHON_RELATIVE"
[[ -f "$STAGING_PYTHON" && ! -L "$STAGING_PYTHON" && -x "$STAGING_PYTHON" ]] || fail "bootstrapped Python is missing or unsafe"
BOOTSTRAP_IDENTITY="$($STAGING_PYTHON -c 'import platform,sys; print(platform.python_implementation()+"\t"+platform.python_version()+"\t"+f"{sys.version_info.major}.{sys.version_info.minor}")')" || fail "bootstrapped Python identity probe failed"
[[ "$BOOTSTRAP_IDENTITY" == $'CPython\t3.13.14\t3.13' ]] || fail "bootstrapped Python identity mismatch"

/usr/bin/env -i HOME=/home/andris USER=andris LOGNAME=andris PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PIP_CONFIG_FILE=/dev/null PIP_NO_INPUT=1 \
  "$STAGING_PYTHON" -m pip install --disable-pip-version-check --no-cache-dir --require-hashes --only-binary=:all: -r "$RUNTIME_LOCK"
/usr/bin/env -i HOME=/home/andris USER=andris LOGNAME=andris PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PIP_CONFIG_FILE=/dev/null \
  "$STAGING_PYTHON" -m pip check >/dev/null
RUNTIME_ENVIRONMENT_REPORT="$(/usr/bin/env -i HOME=/home/andris USER=andris LOGNAME=andris PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 \
  "$STAGING_PYTHON" "$REPO/$LOCK_VERIFIER_REL" "$RUNTIME_LOCK")" || fail "staged runtime environment does not match reviewed lock"
printf '%s\n' "$RUNTIME_ENVIRONMENT_REPORT" | grep -Fxq 'PYTHON_LOCK_ENVIRONMENT=PASS' || fail "runtime lock verifier did not report PASS"
RUNTIME_INVENTORY_SHA="$(printf '%s\n' "$RUNTIME_ENVIRONMENT_REPORT" | awk -F= '$1 == "LOCKED_INVENTORY_SHA256" { print $2 }')"
[[ "$RUNTIME_INVENTORY_SHA" =~ ^[0-9a-f]{64}$ ]] || fail "runtime inventory SHA-256 is invalid"
/usr/bin/env -i HOME=/home/andris USER=andris LOGNAME=andris PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin LANG=C.UTF-8 LC_ALL=C.UTF-8 PYTHONDONTWRITEBYTECODE=1 PYTHONNOUSERSITE=1 PYTHONHASHSEED=0 \
  "$STAGING_PYTHON" -c 'import bs4, httpx' >/dev/null 2>&1 || fail "staged runtime third-party import verification failed"
RUNTIME_PYTHON_BINARY_SHA="$(sha256sum "$STAGING_PYTHON" | awk '{print $1}')"
[[ "$RUNTIME_PYTHON_BINARY_SHA" =~ ^[0-9a-f]{64}$ ]] || fail "runtime Python binary SHA-256 is invalid"
rm -- "$BOOTSTRAP_ARCHIVE"
find "$STAGING_DIR/python" -type d -exec chmod 0755 {} +
find "$STAGING_DIR/python" -type f -exec chmod 0644 {} +
find "$STAGING_DIR/python/bin" -maxdepth 1 -type f -exec chmod 0755 {} +
RUNTIME_TREE_SHA="$(/usr/bin/python3 "$REPO/$RUNTIME_CONTRACT_REL" tree-sha --root "$STAGING_DIR/python")" || fail "cannot fingerprint staged runtime tree"
[[ "$RUNTIME_TREE_SHA" =~ ^[0-9a-f]{64}$ ]] || fail "runtime tree SHA-256 is invalid"

cat > "$STAGING_DIR/candidate-receipt.json" <<EOF_RECEIPT
{
  "schema_version": 2,
  "contract_version": "kaufland-k3c-hash-locked-python-runtime-v2",
  "registration_sha": "$REGISTRATION_SHA",
  "runtime_identity_sha256": "$RUNTIME_IDENTITY_SHA",
  "python_implementation": "$PYTHON_IMPLEMENTATION",
  "python_version": "$PYTHON_VERSION",
  "python_line": "$PYTHON_LINE",
  "python_relative": "$PYTHON_RELATIVE",
  "python_binary_sha256": "$RUNTIME_PYTHON_BINARY_SHA",
  "bootstrap_manifest_relative": "$BOOTSTRAP_REL",
  "bootstrap_manifest_sha256": "$BOOTSTRAP_MANIFEST_SHA",
  "bootstrap_asset_id": $BOOTSTRAP_ASSET_ID,
  "bootstrap_asset_name": "$BOOTSTRAP_ASSET_NAME",
  "bootstrap_asset_sha256": "$BOOTSTRAP_ASSET_SHA",
  "bootstrap_asset_size": $BOOTSTRAP_ASSET_SIZE,
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
FINAL_VERIFICATION="$(/usr/bin/python3 "$REPO/$RUNTIME_CONTRACT_REL" verify --runtime-root "$FINAL_DIR" --repo "$REPO" --registration-sha "$REGISTRATION_SHA" --expected-provisioner-sha "$PROVISIONER_SHA" --expected-runtime-contract-sha "$RUNTIME_CONTRACT_SHA" --expected-lock-manifest-sha "$LOCK_MANIFEST_SHA" --expected-lock-verifier-sha "$LOCK_VERIFIER_SHA")" || fail "final relocated runtime candidate verification failed"
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
printf 'BOOTSTRAP_MANIFEST_SHA256=%s\n' "$BOOTSTRAP_MANIFEST_SHA"
printf 'BOOTSTRAP_ASSET_ID=%s\n' "$BOOTSTRAP_ASSET_ID"
printf 'BOOTSTRAP_ASSET_SHA256=%s\n' "$BOOTSTRAP_ASSET_SHA"
printf 'HOST_MUTATION_PERFORMED=true\n'
printf 'NETWORK_PACKAGE_INSTALL_PERFORMED=true\n'
printf 'DIAGNOSTIC_EXECUTED=false\n'
printf 'RETAINED_EVIDENCE_READ_PERFORMED=false\n'
printf 'RETAINED_EVIDENCE_WRITE_PERFORMED=false\n'
printf 'DATABASE_WRITE_PERFORMED=false\n'
printf 'PRODUCTION_DEPLOY_PERFORMED=false\n'
