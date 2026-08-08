#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${1:-$(git rev-parse --show-toplevel)}"
GITLEAKS_IMAGE='ghcr.io/gitleaks/gitleaks:v8.30.0@sha256:691af3c7c5a48b16f187ce3446d5f194838f91238f27270ed36eef6359a574d9'

fail() {
  printf 'GITLEAKS_HISTORY_SCAN=FAIL reason=%s\n' "$1" >&2
  exit 1
}

[[ -d "$ROOT/.git" ]] || fail 'not-a-git-repository'
[[ -f "$ROOT/.gitleaks.toml" ]] || fail 'missing-config'
command -v docker >/dev/null 2>&1 || fail 'docker-not-available'

if [[ "$(git -C "$ROOT" rev-parse --is-shallow-repository)" == true ]]; then
  fail 'shallow-history'
fi

work="$(mktemp -d)"
cleanup() {
  rm -rf -- "$work"
}
trap cleanup EXIT
chmod 0700 "$work"

set +e
docker run --rm \
  --network none \
  --read-only \
  --cap-drop ALL \
  --security-opt no-new-privileges \
  --user "$(id -u):$(id -g)" \
  --mount "type=bind,src=$ROOT,dst=/repo,readonly" \
  --mount "type=bind,src=$work,dst=/output" \
  --workdir /repo \
  "$GITLEAKS_IMAGE" \
  git --no-banner --redact --config /repo/.gitleaks.toml \
  --log-opts='--all' --report-format json --report-path /output/history.json \
  /repo \
  >"$work/stdout" 2>"$work/stderr"
status=$?
set -e

if [[ "$status" -ne 0 ]]; then
  printf 'Gitleaks full-history scan returned status %s. Findings remain redacted.\n' "$status" >&2
  sed -n '1,120p' "$work/stderr" >&2
  if [[ -s "$work/history.json" ]]; then
    python3 - "$work/history.json" <<'PY' >&2
from __future__ import annotations

import json
from pathlib import Path
import sys

rows = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
print(f"GITLEAKS_FINDING_COUNT={len(rows)}")
for row in rows[:50]:
    print(
        "finding"
        f" rule={row.get('RuleID', 'unknown')}"
        f" file={row.get('File', 'unknown')}"
        f" line={row.get('StartLine', row.get('Line', 'unknown'))}"
        f" commit={row.get('Commit', 'unknown')}"
    )
PY
  fi
  fail 'history-findings-or-scan-error'
fi

if [[ -s "$work/history.json" ]]; then
  python3 - "$work/history.json" <<'PY'
from pathlib import Path
import json
import sys

rows = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
if rows:
    raise SystemExit("successful Gitleaks scan unexpectedly produced findings")
PY
fi

printf 'GITLEAKS_HISTORY_SCAN=PASS\n'
