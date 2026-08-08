#!/usr/bin/env bash
set -Eeuo pipefail

ROOT="${1:-$(git rev-parse --show-toplevel)}"
GITLEAKS_IMAGE='ghcr.io/gitleaks/gitleaks:v8.30.0@sha256:691af3c7c5a48b16f187ce3446d5f194838f91238f27270ed36eef6359a574d9'
ALLOWLIST="${ROOT}/security/gitleaks-history-allowlist.json"

fail() {
  printf 'GITLEAKS_HISTORY_SCAN=FAIL reason=%s\n' "$1" >&2
  exit 1
}

[[ -d "$ROOT/.git" ]] || fail 'not-a-git-repository'
[[ -f "$ROOT/.gitleaks.toml" ]] || fail 'missing-config'
[[ -f "$ALLOWLIST" ]] || fail 'missing-history-allowlist'
command -v docker >/dev/null 2>&1 || fail 'docker-not-available'
command -v python3 >/dev/null 2>&1 || fail 'python3-not-available'

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

if [[ "$status" -gt 1 ]]; then
  sed -n '1,120p' "$work/stderr" >&2
  fail "scanner-exit-${status}"
fi

if [[ ! -s "$work/history.json" ]]; then
  if [[ "$status" -ne 0 ]]; then
    sed -n '1,120p' "$work/stderr" >&2
    fail 'scanner-reported-findings-without-report'
  fi
  printf 'GITLEAKS_FINDING_COUNT=0\n'
  printf 'GITLEAKS_KNOWN_FALSE_POSITIVE_COUNT=0\n'
  printf 'GITLEAKS_HISTORY_SCAN=PASS\n'
  exit 0
fi

set +e
python3 - "$work/history.json" "$ALLOWLIST" <<'PY'
from __future__ import annotations

import json
from pathlib import Path
import sys

report_path = Path(sys.argv[1])
allowlist_path = Path(sys.argv[2])
rows = json.loads(report_path.read_text(encoding="utf-8"))
allowed_rows = json.loads(allowlist_path.read_text(encoding="utf-8"))

if not isinstance(rows, list) or not isinstance(allowed_rows, list):
    raise SystemExit("Gitleaks report or allowlist is not a JSON list")


def identity(row: dict[str, object]) -> tuple[str, str, int, str]:
    try:
        return (
            str(row["RuleID"]),
            str(row["File"]),
            int(row.get("StartLine", row.get("Line"))),
            str(row["Commit"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise SystemExit(f"invalid Gitleaks finding identity: {error}") from error


def allowed_identity(row: dict[str, object]) -> tuple[str, str, int, str]:
    try:
        return (
            str(row["rule_id"]),
            str(row["file"]),
            int(row["line"]),
            str(row["commit"]),
        )
    except (KeyError, TypeError, ValueError) as error:
        raise SystemExit(f"invalid allowlist identity: {error}") from error

allowed = {allowed_identity(row) for row in allowed_rows}
if len(allowed) != len(allowed_rows):
    raise SystemExit("duplicate exact identities in Gitleaks history allowlist")

actual = [identity(row) for row in rows]
unknown = [item for item in actual if item not in allowed]
known = [item for item in actual if item in allowed]

print(f"GITLEAKS_FINDING_COUNT={len(actual)}")
print(f"GITLEAKS_KNOWN_FALSE_POSITIVE_COUNT={len(known)}")
print(f"GITLEAKS_UNKNOWN_FINDING_COUNT={len(unknown)}")

if unknown:
    for rule_id, file_name, line, commit in unknown[:50]:
        print(
            "unknown-finding"
            f" rule={rule_id}"
            f" file={file_name}"
            f" line={line}"
            f" commit={commit}"
        )
    raise SystemExit(3)

for rule_id, file_name, line, commit in known:
    print(
        "verified-false-positive"
        f" rule={rule_id}"
        f" file={file_name}"
        f" line={line}"
        f" commit={commit}"
    )
PY
review_status=$?
set -e

if [[ "$review_status" -ne 0 ]]; then
  sed -n '1,120p' "$work/stderr" >&2
  fail 'unreviewed-history-findings'
fi

if [[ "$status" -eq 0 ]]; then
  fail 'scanner-status-zero-with-nonempty-report'
fi

printf 'GITLEAKS_HISTORY_SCAN=PASS\n'
