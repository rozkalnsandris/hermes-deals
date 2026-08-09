#!/usr/bin/env bash
set -Eeuo pipefail
IFS=$'\n\t'
umask 077

fail() { echo "ERROR: $*" >&2; exit 1; }
[[ $# -eq 3 ]] || fail "usage: $0 <exact-sha> <as-of YYYY-MM-DD> <output-root>"
EXPECTED_SHA="$1"
AS_OF="$2"
RUN_ROOT="$3"
REPO="$(git rev-parse --show-toplevel)"
RAW_ROOT="$RUN_ROOT/source"
LIVE_SUMMARY="$RUN_ROOT/live-source.json"
BINDING="$RUN_ROOT/selected-binding.json"
CAPTURE_ROOT="$RUN_ROOT/capture"
RESULT="$RUN_ROOT/github-capture-result.json"

[[ "$EXPECTED_SHA" =~ ^[0-9a-f]{40}$ ]] || fail "invalid exact SHA"
python3 - "$AS_OF" <<'PY'
from datetime import date
import sys
value = date.fromisoformat(sys.argv[1])
if value.isoformat() != sys.argv[1]:
    raise SystemExit("as-of must be canonical YYYY-MM-DD")
PY
[[ "$(git -C "$REPO" rev-parse HEAD)" == "$EXPECTED_SHA" ]] || fail "checkout HEAD mismatch"
[[ -z "$(git -C "$REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail "checkout must be clean"
REMOTE="$(git -C "$REPO" remote get-url origin)"
case "$REMOTE" in
  https://github.com/rozkalnsandris/hermes-deals|https://github.com/rozkalnsandris/hermes-deals.git|git@github.com:rozkalnsandris/hermes-deals.git) ;;
  *) fail "unexpected repository origin" ;;
esac
[[ ! -e "$RUN_ROOT" && ! -L "$RUN_ROOT" ]] || fail "output root must be create-only"
mkdir -m 0700 -p -- "$RUN_ROOT"

python3 - <<'PY'
import importlib.metadata
version = importlib.metadata.version("PyMuPDF")
if version != "1.28.0":
    raise SystemExit(f"PyMuPDF 1.28.0 required, found {version}")
PY

DATABASE_URL='sqlite+pysqlite:///:memory:' \
python3 "$REPO/tools/netto_heldout_live_source.py" \
  --repo "$REPO" \
  --raw-root "$RAW_ROOT" \
  --as-of "$AS_OF" \
  --output "$LIVE_SUMMARY"

python3 "$REPO/tools/netto_heldout_source_selector.py" \
  --raw-root "$RAW_ROOT" \
  --as-of "$AS_OF" \
  --output "$BINDING"

python3 "$REPO/tools/netto_heldout_page_capture.py" \
  "$BINDING" \
  --output "$CAPTURE_ROOT"

python3 - "$EXPECTED_SHA" "$AS_OF" "$LIVE_SUMMARY" "$BINDING" "$CAPTURE_ROOT" "$RESULT" <<'PY'
import json
from pathlib import Path
import sys
sha, as_of = sys.argv[1:3]
live = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
selected = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
root = Path(sys.argv[5])
receipt = json.loads((root / "freeze-receipt.json").read_text(encoding="utf-8"))
review = json.loads((root / "blind-review-template.json").read_text(encoding="utf-8"))
if live["campaign_key"] != selected["campaign_key"] or selected["campaign_key"] != receipt["campaign_key"]:
    raise SystemExit("campaign identity changed across live source, selector and freeze")
if receipt.get("truth_available_at_freeze") is not False:
    raise SystemExit("truth blindness was not preserved")
if receipt.get("review_only") is not True or receipt.get("promotion_ready") is not False:
    raise SystemExit("freeze safety state is invalid")
if review.get("parser_predictions_included") is not False or review.get("expected_truth_included") is not False:
    raise SystemExit("blind review template contains forbidden truth/predictions")
payload = {
    "schema_version": 1,
    "result": "PASS",
    "strategy": "netto_heldout_github_capture_v1",
    "registered_commit": sha,
    "as_of": as_of,
    "campaign_key": receipt["campaign_key"],
    "freeze_manifest_sha256": receipt["freeze_manifest_sha256"],
    "evidence_sha256": receipt["evidence_sha256"],
    "predictions_sha256": receipt["predictions_sha256"],
    "network_fetch_performed": True,
    "database_write_performed": False,
    "review_write_performed": False,
    "deployment_performed": False,
    "scheduler_change_performed": False,
    "truth_available_at_freeze": False,
    "review_only": True,
    "promotion_ready": False,
}
Path(sys.argv[6]).write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
print(json.dumps(payload, sort_keys=True))
PY

(
  cd "$RUN_ROOT"
  find . -type f ! -path './SHA256SUMS' -print0 | sort -z |
    while IFS= read -r -d '' path; do sha256sum -- "$path"; done
) > "$RUN_ROOT/SHA256SUMS"
[[ -z "$(git -C "$REPO" status --porcelain=v1 --untracked-files=all)" ]] || fail "capture changed repository checkout"

echo "GITHUB_HELDOUT_CAPTURE_RESULT=PASS"
echo "REGISTERED_COMMIT=$EXPECTED_SHA"
echo "AS_OF=$AS_OF"
echo "RUN_ROOT=$RUN_ROOT"
echo "DATABASE_WRITE=false"
echo "REVIEW_WRITE=false"
echo "PRODUCTION_DEPLOY=false"
echo "PROMOTION_READY=false"
