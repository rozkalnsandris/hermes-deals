#!/usr/bin/env bash
set -Eeuo pipefail

PYTHON_LINE="${1:-}"
case "$PYTHON_LINE" in
  3.11|3.13) ;;
  *)
    echo "usage: $0 {3.11|3.13}" >&2
    exit 64
    ;;
esac

PIP_VERSION="26.0.1"
PIP_TOOLS_VERSION="7.6.0"
EXPECTED_INPUT="backend/requirements.in"
CI_INPUT="backend/requirements-ci.in"

repo_root="$(git rev-parse --show-toplevel)"
cd "$repo_root"

actual_python="$(python -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')"
if [[ "$actual_python" != "$PYTHON_LINE" ]]; then
  echo "expected Python $PYTHON_LINE, got $actual_python" >&2
  exit 65
fi

python -m pip install --disable-pip-version-check --only-binary=:all: "pip==$PIP_VERSION"
python -m pip install --disable-pip-version-check --only-binary=:all: "pip-tools==$PIP_TOOLS_VERSION"
python -m pip --version
python -m piptools compile --version

mkdir -p backend/locks

compile_lock() {
  local input="$1"
  local output="$2"
  CUSTOM_COMPILE_COMMAND="scripts/compile-python-locks.sh $PYTHON_LINE" \
    python -m piptools compile \
      --resolver=backtracking \
      --generate-hashes \
      --no-emit-index-url \
      --no-emit-trusted-host \
      --no-allow-unsafe \
      --pip-args="--only-binary=:all:" \
      --output-file "$output" \
      "$input"
}

case "$PYTHON_LINE" in
  3.11)
    compile_lock "$EXPECTED_INPUT" "backend/locks/runtime-py311.txt"
    compile_lock "$CI_INPUT" "backend/locks/ci-py311.txt"
    ;;
  3.13)
    compile_lock "$EXPECTED_INPUT" "backend/locks/runtime-py313.txt"
    ;;
esac

for lock in backend/locks/*.txt; do
  [[ -f "$lock" ]] || continue
  sha256sum "$lock"
done
