#!/usr/bin/env bash
# Compatibility wrapper kept for old operator muscle memory.
set -Eeuo pipefail
exec "$(dirname "$0")/verify.sh" "$@"
