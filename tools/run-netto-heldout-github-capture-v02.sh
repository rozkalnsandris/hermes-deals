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
RESULT="$RUN_ROOT/github-capture-result-v2.json"
CANDIDATE_COMMIT="17ceedf0fdb0342acb594ed20679519ec4910e3c"
CANDIDATE_PATH="tools/netto_local_span_auto_single_candidate.py"

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
git -C "$REPO" cat-file -e "$CANDIDATE_COMMIT^{commit}" || fail "candidate implementation commit is unavailable"
git -C "$REPO" merge-base --is-ancestor "$CANDIDATE_COMMIT" "$EXPECTED_SHA" || fail "candidate implementation commit is not in reviewed history"
git -C "$REPO" diff --quiet "$CANDIDATE_COMMIT" -- "$CANDIDATE_PATH" || fail "candidate implementation file drifted from pinned commit"
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

python3 "$REPO/tools/netto_heldout_page_capture_v2.py" \
  "$BINDING" \
  --candidate-implementation-commit "$CANDIDATE_COMMIT" \
  --output "$CAPTURE_ROOT"

python3 - "$EXPECTED_SHA" "$AS_OF" "$LIVE_SUMMARY" "$BINDING" "$CAPTURE_ROOT" "$RESULT" <<'PY'
import json
from pathlib import Path
import sys
sha, as_of = sys.argv[1:3]
live = json.loads(Path(sys.argv[3]).read_text(encoding="utf-8"))
selected = json.loads(Path(sys.argv[4]).read_text(encoding="utf-8"))
root = Path(sys.argv[5])
v1 = json.loads((root / "freeze-receipt.json").read_text(encoding="utf-8"))
v2 = json.loads((root / "freeze-receipt-v2.json").read_text(encoding="utf-8"))
candidate = json.loads((root / "candidate-provenance.json").read_text(encoding="utf-8"))
review = json.loads((root / "blind-review-template.json").read_text(encoding="utf-8"))
if live["campaign_key"] != selected["campaign_key"] or selected["campaign_key"] != v1["campaign_key"] or v1["campaign_key"] != v2["campaign_key"]:
    raise SystemExit("campaign identity changed across live source, selector, v1 and v2 freeze")
if v1.get("truth_available_at_freeze") is not False or v2.get("truth_available_at_freeze") is not False:
    raise SystemExit("truth blindness was not preserved")
if v2.get("review_only") is not True or v2.get("promotion_ready") is not False:
    raise SystemExit("v2 freeze safety state is invalid")
if candidate.get("truth_used_for_candidate_construction") is not False or candidate.get("automatic_candidate_decisions_frozen") is not True:
    raise SystemExit("candidate was not frozen truth-free")
if candidate.get("candidate_provenance_sha256") != v2.get("candidate_provenance_sha256"):
    raise SystemExit("candidate provenance changed across v2 freeze")
if review.get("parser_predictions_included") is not False or review.get("expected_truth_included") is not False:
    raise SystemExit("blind review template contains forbidden truth/predictions")
payload = {
    "schema_version": 2,
    "result": "PASS",
    "strategy": "netto_heldout_github_capture_v2",
    "registered_commit": sha,
    "as_of": as_of,
    "campaign_key": v2["campaign_key"],
    "base_freeze_manifest_sha256": v2["base_freeze_manifest_sha256"],
    "v2_freeze_manifest_sha256": v2["v2_freeze_manifest_sha256"],
    "candidate_implementation_commit": v2["candidate_implementation_commit"],
    "candidate_file_sha256": v2["candidate_file_sha256"],
    "candidate_provenance_sha256": v2["candidate_provenance_sha256"],
    "candidate_decisions_sha256": v2["candidate_decisions_sha256"],
    "candidate_auto_single_count": v2["candidate_auto_single_count"],
    "automatic_candidate_parent_reuse_count": v2["automatic_candidate_parent_reuse_count"],
    "parent_reuse_metric": v2["parent_reuse_metric"],
    "network_fetch_performed": True,
    "candidate_decisions_frozen_before_truth": True,
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

echo "GITHUB_HELDOUT_CAPTURE_V2_RESULT=PASS"
echo "REGISTERED_COMMIT=$EXPECTED_SHA"
echo "AS_OF=$AS_OF"
echo "RUN_ROOT=$RUN_ROOT"
echo "CANDIDATE_IMPLEMENTATION_COMMIT=$CANDIDATE_COMMIT"
echo "CANDIDATE_FROZEN_BEFORE_TRUTH=true"
echo "DATABASE_WRITE=false"
echo "REVIEW_WRITE=false"
echo "PRODUCTION_DEPLOY=false"
echo "PROMOTION_READY=false"
