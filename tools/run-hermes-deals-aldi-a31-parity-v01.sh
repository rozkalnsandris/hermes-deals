#!/usr/bin/env bash
set -Eeuo pipefail
umask 027

REPO="${REPO:-/home/andris/hermes-deals}"
EXPECTED_HEAD="${HERMES_AUDIT_EXPECTED_HEAD:-}"
A21_ARCHIVE="${A21_ARCHIVE:-/home/andris/.local/state/hermes-deals/aldi-perfect-shadow/hermes-deals-aldi-a21-20260801T100533Z.tar.gz}"
A30_RUN_DIR="${A30_RUN_DIR:-}"
A31_MODE="${A31_MODE:-template}"
A31_CARD_LEDGER="${A31_CARD_LEDGER:-}"
STATE_ROOT="${STATE_ROOT:-/home/andris/.local/state/hermes-deals/aldi-perfect-shadow}"
STAMP="$(date -u +%Y%m%dT%H%M%SZ)"
RUN_DIR="${RUN_DIR:-$STATE_ROOT/a31-v01-runs/$STAMP}"
INPUT_DIR="$RUN_DIR/input"
OUTPUT_DIR="$RUN_DIR/output"
LOG="$RUN_DIR/a31-v01.log"

fail() { printf 'FAIL %s\n' "$*" >&2; exit 1; }
pass() { printf 'PASS %s\n' "$*"; }

for command in git python3 sha256sum tee; do
  command -v "$command" >/dev/null 2>&1 || fail "missing command: $command"
done
[[ -n "$EXPECTED_HEAD" ]] || fail "HERMES_AUDIT_EXPECTED_HEAD is required"
[[ -n "$A30_RUN_DIR" ]] || fail "A30_RUN_DIR is required and must name one frozen A3.0 run"
[[ "$A31_MODE" == "template" || "$A31_MODE" == "verify" ]] \
  || fail "A31_MODE must be template or verify"
[[ -d "$REPO/.git" ]] || fail "repository not found: $REPO"
[[ -s "$A21_ARCHIVE" ]] || fail "pinned A2.1 archive not found: $A21_ARCHIVE"
PAGE_MANIFEST="$A30_RUN_DIR/reports/page-image-manifest.json"
[[ -s "$PAGE_MANIFEST" ]] || fail "A3.0 page manifest not found: $PAGE_MANIFEST"
if [[ "$A31_MODE" == "verify" ]]; then
  [[ -n "$A31_CARD_LEDGER" && -s "$A31_CARD_LEDGER" ]] \
    || fail "A31_CARD_LEDGER is required in verify mode"
fi

mkdir -p "$INPUT_DIR" "$OUTPUT_DIR"
exec > >(tee "$LOG") 2>&1

cd "$REPO"
[[ "$(git branch --show-current)" == "main" ]] || fail "main branch required"
[[ "$(git rev-parse HEAD)" == "$EXPECTED_HEAD" ]] || fail "HEAD mismatch"
[[ -z "$(git status --porcelain=v1 --untracked-files=all)" ]] \
  || fail "repository must be clean"

printf 'mode=ALDI_A31_DETERMINISTIC_PARITY_V01\n'
printf 'a31_mode=%s\n' "$A31_MODE"
printf 'network_fetch=false\n'
printf 'production_source_write=false\n'
printf 'production_database_write=false\n'
printf 'production_deploy=false\n'
printf 'collector_execution=false\n'
printf 'automatic_approval=false\n'
printf 'automatic_publication=false\n'

python3 - "$REPO" "$A21_ARCHIVE" "$INPUT_DIR" "$RUN_DIR/projection-path.txt" <<'PY'
from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

repo = Path(sys.argv[1])
archive = Path(sys.argv[2])
destination = Path(sys.argv[3])
output = Path(sys.argv[4])
tool = repo / "tools" / "aldi_a30_frozen_acquisition.py"
spec = importlib.util.spec_from_file_location("aldi_a30_frozen_acquisition", tool)
if spec is None or spec.loader is None:
    raise SystemExit("cannot load A3.0 integrity module")
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)
root, integrity = module.verify_a21_archive(archive, destination)
projection = root / "reports" / "a21-adjudicated-projection.jsonl"
if not projection.is_file():
    raise SystemExit("verified A2.1 projection is missing")
output.write_text(str(projection) + "\n", encoding="utf-8")
print(f"A21_PROJECTION_SHA256={integrity['projection_sha256']}")
print(f"A21_PROJECTION_ROWS={integrity['projection_rows']}")
PY
PROJECTION="$(cat "$RUN_DIR/projection-path.txt")"
pass "exact_a21_archive_and_projection_verified=true"

if [[ "$A31_MODE" == "template" ]]; then
  python3 "$REPO/tools/aldi_a31_offer_page_parity.py" \
    --projection "$PROJECTION" \
    --page-manifest "$PAGE_MANIFEST" \
    --output "$OUTPUT_DIR" \
    --commit-sha "$EXPECTED_HEAD" \
    --prepare-template
  pass "controlled_card_ledger_template_prepared=true"
  printf 'RESULT=ALDI_A31_TEMPLATE_PREPARED\n'
else
  python3 "$REPO/tools/aldi_a31_offer_page_parity.py" \
    --projection "$PROJECTION" \
    --page-manifest "$PAGE_MANIFEST" \
    --card-ledger "$A31_CARD_LEDGER" \
    --output "$OUTPUT_DIR" \
    --commit-sha "$EXPECTED_HEAD"
  pass "bidirectional_offer_card_parity_passed=true"
  printf 'RESULT=ALDI_A31_PARITY_PASS\n'
fi

[[ -z "$(git status --porcelain=v1 --untracked-files=all)" ]] \
  || fail "A3.1 changed repository worktree"
pass "production_repository_unchanged=true"
pass "production_database_unchanged_by_construction=true"
pass "production_runtime_unchanged_by_construction=true"
printf 'RUN_DIR=%s\n' "$RUN_DIR"
printf 'LOG=%s\n' "$LOG"
