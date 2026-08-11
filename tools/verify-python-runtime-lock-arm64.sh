#!/usr/bin/env bash
set -Eeuo pipefail

EXPECTED_SHA="${1:-}"
if [[ ! "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]]; then
  echo "usage: $0 <exact-commit-sha>" >&2
  exit 64
fi

REPO_ROOT="$(git rev-parse --show-toplevel)"
cd "$REPO_ROOT"

ACTUAL_SHA="$(git rev-parse HEAD)"
if [[ "$ACTUAL_SHA" != "$EXPECTED_SHA" ]]; then
  echo "expected HEAD $EXPECTED_SHA, got $ACTUAL_SHA" >&2
  exit 65
fi
if [[ -n "$(git status --porcelain --untracked-files=all)" ]]; then
  echo "checkout must be clean" >&2
  exit 66
fi

ARCH="$(uname -m)"
case "$ARCH" in
  aarch64|arm64) ;;
  *)
    echo "ARM64 preflight requires aarch64/arm64, got $ARCH" >&2
    exit 67
    ;;
esac

PYTHON_VERSION="$(python3 -c 'import platform; print(platform.python_version())')"
PYTHON_LINE="$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$PYTHON_LINE" != "3.11" ]]; then
  echo "runtime-py311 lock requires Python 3.11, got $PYTHON_VERSION" >&2
  exit 68
fi

LOCK_REL="backend/locks/runtime-py311.txt"
MANIFEST_REL="backend/locks/manifest.json"
EXPECTED_LOCK_SHA="$(python3 - "$MANIFEST_REL" <<'PY'
import json
import pathlib
import sys
manifest = json.loads(pathlib.Path(sys.argv[1]).read_text(encoding="utf-8"))
identity = manifest["locks"]["runtime-py311.txt"]
if identity["python"] != "3.11":
    raise SystemExit("manifest Python identity mismatch")
print(identity["sha256"])
PY
)"
ACTUAL_LOCK_SHA="$(sha256sum "$LOCK_REL" | awk '{print $1}')"
if [[ "$ACTUAL_LOCK_SHA" != "$EXPECTED_LOCK_SHA" ]]; then
  echo "runtime-py311 lock SHA256 does not match manifest" >&2
  exit 69
fi

TMP_BASE="${HERMES_LOCK_TMPDIR:-/var/tmp}"
if [[ ! -d "$TMP_BASE" || ! -w "$TMP_BASE" ]]; then
  echo "ARM64 preflight temp base must exist and be writable: $TMP_BASE" >&2
  exit 70
fi
MIN_TMP_KIB=$((1024 * 1024))
AVAILABLE_TMP_KIB="$(LC_ALL=C df -Pk -- "$TMP_BASE" | awk 'NR == 2 {print $4}')"
if [[ ! "$AVAILABLE_TMP_KIB" =~ ^[0-9]+$ ]]; then
  echo "could not determine available space for temp base: $TMP_BASE" >&2
  exit 71
fi
if (( AVAILABLE_TMP_KIB < MIN_TMP_KIB )); then
  echo "ARM64 preflight requires at least ${MIN_TMP_KIB} KiB free in $TMP_BASE; available=${AVAILABLE_TMP_KIB} KiB" >&2
  exit 72
fi

TMP_ROOT="$(mktemp -d -- "$TMP_BASE/hermes-python-lock-arm64.XXXXXX")"
cleanup() {
  rm -rf "$TMP_ROOT"
}
trap cleanup EXIT

python3 -m venv "$TMP_ROOT/venv"
VENV_PYTHON="$TMP_ROOT/venv/bin/python"
PIP_VERSION="$($VENV_PYTHON -m pip --version | awk '{print $2}')"

"$VENV_PYTHON" -m pip install \
  --disable-pip-version-check \
  --require-hashes \
  --only-binary=:all: \
  -r "$LOCK_REL"
"$VENV_PYTHON" -m pip check

printf '%s\n' \
  "ARM64_PYTHON_LOCK_PREFLIGHT=PASS" \
  "REGISTERED_COMMIT=$ACTUAL_SHA" \
  "ARCHITECTURE=$ARCH" \
  "PYTHON_IMPLEMENTATION=CPython" \
  "PYTHON_VERSION=$PYTHON_VERSION" \
  "PIP_VERSION=$PIP_VERSION" \
  "LOCK_FILE=$LOCK_REL" \
  "LOCK_SHA256=$ACTUAL_LOCK_SHA" \
  "TEMP_BASE=$TMP_BASE" \
  "TEMP_AVAILABLE_KIB_BEFORE=$AVAILABLE_TMP_KIB" \
  "PRODUCTION_DATABASE_WRITE=false" \
  "PRODUCTION_DEPLOYMENT=false" \
  "SCHEDULER_ACTIVATION=false" \
  "SYSTEMD_MUTATION=false" \
  "DOCKER_MUTATION=false"
