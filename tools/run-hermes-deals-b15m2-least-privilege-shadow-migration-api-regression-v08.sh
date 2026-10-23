#!/usr/bin/env bash
set -Eeuo pipefail
umask 077
[[ $# -eq 0 ]] || { echo "B15M2_V08_FAIL: unexpected arguments" >&2; exit 1; }
exec /usr/bin/python3 /home/andris/hermes-deals/tools/b15m2_v08_shadow.py
