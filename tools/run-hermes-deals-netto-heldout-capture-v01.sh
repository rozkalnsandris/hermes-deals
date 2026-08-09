#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077
PATH='/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin'
export PATH
export PYTHONDONTWRITEBYTECODE=1

fail() {
  echo "ERROR: $*" >&2
  exit 1
}

[[ ${EUID:-$(id -u)} -ne 0 ]] || fail "do not run held-out capture as root"
[[ "$(id -un)" == 'andris' ]] || fail "held-out capture must run as andris"
[[ $# -eq 2 ]] || fail "usage: tools/run-hermes-deals-netto-heldout-capture-v01.sh <exact-main-sha> <as-of YYYY-MM-DD>"

EXPECTED_SHA="$1"
AS_OF="$2"
REPO='/home/andris/hermes-deals'
RAW_ROOT="$REPO/data/raw"
AUDIT_ROOT='/home/andris/hermes-deals-audits'
SELECTOR="$REPO/tools/netto_heldout_source_selector.py"
CAPTURE="$REPO/tools/netto_heldout_page_capture.py"
RUN_ROOT="$AUDIT_ROOT/netto-heldout-capture-${AS_OF}-${EXPECTED_SHA:0:12}"
BINDING="$RUN_ROOT/selected-binding.json"
CAPTURE_ROOT="$RUN_ROOT/capture"
RUN_SUMS="$RUN_ROOT/SHA256SUMS"

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "exact main SHA is invalid"
/usr/bin/python3 - "$AS_OF" <<'PY'
from datetime import date
import sys
value = date.fromisoformat(sys.argv[1])
if value.isoformat() != sys.argv[1]:
    raise SystemExit("as-of date must use canonical YYYY-MM-DD")
PY

for command in git python3 sha256sum find sort stat; do
  command -v "$command" >/dev/null 2>&1 || fail "required command is missing: $command"
done
[[ -d "$REPO/.git" ]] || fail "primary Hermes Deals checkout is missing"
[[ -d "$RAW_ROOT" && ! -L "$RAW_ROOT" ]] || fail "Netto raw evidence root is missing or unsafe"
[[ -f "$SELECTOR" && ! -L "$SELECTOR" ]] || fail "held-out source selector is missing or unsafe"
[[ -f "$CAPTURE" && ! -L "$CAPTURE" ]] || fail "held-out page capture tool is missing or unsafe"

[[ "$(git -C "$REPO" branch --show-current)" == 'main' ]] || fail "primary repository must be on main"
[[ "$(git -C "$REPO" rev-parse HEAD)" == "$EXPECTED_SHA" ]] || fail "primary repository HEAD mismatch"
git -C "$REPO" show-ref --verify --quiet refs/remotes/origin/main || fail "origin/main is unavailable"
[[ "$(git -C "$REPO" rev-parse refs/remotes/origin/main)" == "$EXPECTED_SHA" ]] || fail "local origin/main is not the exact authorized SHA"
INITIAL_STATUS="$(git -C "$REPO" status --porcelain=v1 --untracked-files=all)"
[[ -z "$INITIAL_STATUS" ]] || fail "primary repository must be clean"

/usr/bin/python3 - "$SELECTOR" "$CAPTURE" <<'PY'
from pathlib import Path
import sys
for value in sys.argv[1:]:
    path = Path(value)
    compile(path.read_text(encoding="utf-8"), str(path), "exec")
PY
/usr/bin/python3 - <<'PY'
import importlib.metadata
import pymupdf
version = importlib.metadata.version("PyMuPDF")
if version != "1.28.0":
    raise SystemExit(f"PyMuPDF 1.28.0 required, found {version}")
PY

if [[ -e "$RUN_ROOT" || -L "$RUN_ROOT" ]]; then
  fail "held-out audit output already exists: $RUN_ROOT"
fi
if [[ ! -d "$AUDIT_ROOT" ]]; then
  mkdir -m 0700 -- "$AUDIT_ROOT"
fi
[[ ! -L "$AUDIT_ROOT" && -d "$AUDIT_ROOT" ]] || fail "audit root is unsafe"
mkdir -m 0700 -- "$RUN_ROOT"

COMPLETED=0
cleanup() {
  if [[ "$COMPLETED" != '1' && -d "$RUN_ROOT" && ! -L "$RUN_ROOT" ]]; then
    rm -rf -- "$RUN_ROOT"
  fi
}
trap cleanup EXIT

/usr/bin/python3 "$SELECTOR" \
  --raw-root "$RAW_ROOT" \
  --as-of "$AS_OF" \
  --output "$BINDING"

/usr/bin/python3 "$CAPTURE" \
  "$BINDING" \
  --output "$CAPTURE_ROOT"

[[ -f "$BINDING" && ! -L "$BINDING" ]] || fail "selector binding output is missing or unsafe"
for name in source-evidence.json predictions.json freeze-manifest.json freeze-receipt.json blind-review-template.json SHA256SUMS; do
  [[ -f "$CAPTURE_ROOT/$name" && ! -L "$CAPTURE_ROOT/$name" ]] || fail "capture output is missing or unsafe: $name"
done

(
  cd "$RUN_ROOT"
  find . -type f ! -path './SHA256SUMS' -print0 \
    | sort -z \
    | while IFS= read -r -d '' path; do
        sha256sum -- "$path"
      done
) > "$RUN_SUMS"
chmod 0600 "$RUN_SUMS"

FINAL_STATUS="$(git -C "$REPO" status --porcelain=v1 --untracked-files=all)"
[[ "$FINAL_STATUS" == "$INITIAL_STATUS" ]] || fail "held-out capture changed the primary Git worktree"
[[ "$(git -C "$REPO" rev-parse HEAD)" == "$EXPECTED_SHA" ]] || fail "primary repository HEAD changed during capture"

/usr/bin/python3 - "$CAPTURE_ROOT/freeze-receipt.json" "$CAPTURE_ROOT/blind-review-template.json" <<'PY'
import json
from pathlib import Path
import sys
receipt = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
review = json.loads(Path(sys.argv[2]).read_text(encoding="utf-8"))
if receipt.get("truth_available_at_freeze") is not False:
    raise SystemExit("freeze receipt does not prove truth blindness")
if receipt.get("promotion_ready") is not False or receipt.get("review_only") is not True:
    raise SystemExit("freeze receipt safety state is invalid")
if review.get("parser_predictions_included") is not False or review.get("expected_truth_included") is not False:
    raise SystemExit("blind review template contains forbidden pre-review data")
print(f"CAMPAIGN_KEY={receipt['campaign_key']}")
print(f"FREEZE_MANIFEST_SHA256={receipt['freeze_manifest_sha256']}")
print(f"EVIDENCE_SHA256={receipt['evidence_sha256']}")
print(f"PREDICTIONS_SHA256={receipt['predictions_sha256']}")
PY

COMPLETED=1
trap - EXIT
printf '%s\n' \
  "OWNER_HELDOUT_CAPTURE_RESULT=PASS" \
  "REGISTERED_COMMIT=$EXPECTED_SHA" \
  "AS_OF=$AS_OF" \
  "RUN_ROOT=$RUN_ROOT" \
  "REPOSITORY_WRITE=false" \
  "DATABASE_WRITE=false" \
  "REVIEW_WRITE=false" \
  "PRODUCTION_DEPLOY=false" \
  "SCHEDULER_CHANGE=false" \
  "PROMOTION_READY=false"
