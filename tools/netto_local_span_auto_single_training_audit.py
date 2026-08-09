from __future__ import annotations

import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path
import sys
from typing import Any

TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from netto_heldout_completed_source_truth import EXPECTED_LEDGER_SHA, validate_file as validate_truth_file
from netto_heldout_prediction_group_adjudication import adjudicate_group
from netto_local_span_auto_single_candidate import candidate_rows, freeze_candidate

STRATEGY = "local_span_component_auto_single_hz33_training_audit_v1"
EXPECTED_SOURCE_EVIDENCE_SHA = "49e22d29b16eacf0d316f20105de2c25e3d9b3c2ae231d0bd24d0d18036f5fd4"
EXPECTED_PREDICTIONS_SHA = "70c3c8abace632f6be298abb5d02b398b3e8b91e8d53565b21eface536ed7b94"
EXPECTED_CAMPAIGN = "hz33_hasb"
EXPECTED_CANDIDATE_COUNT = 25
EXPECTED_SINGLE_COUNT = 25


class LocalSpanTrainingAuditError(ValueError):
    pass


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path, expected_sha: str, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise LocalSpanTrainingAuditError(f"{label} must be a regular file")
    if _sha(path) != expected_sha:
        raise LocalSpanTrainingAuditError(f"{label} SHA mismatch")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise LocalSpanTrainingAuditError(f"{label} must contain an object")
    return payload


def run_training_audit(source_path: Path, predictions_path: Path, truth_path: Path) -> dict[str, Any]:
    source = _load(source_path, EXPECTED_SOURCE_EVIDENCE_SHA, "hz33 source evidence")
    predictions = _load(predictions_path, EXPECTED_PREDICTIONS_SHA, "hz33 predictions")

    # Candidate construction is completed and SHA-frozen before truth is loaded.
    candidate = freeze_candidate(
        source,
        predictions,
        source_evidence_sha256=EXPECTED_SOURCE_EVIDENCE_SHA,
        predictions_sha256=EXPECTED_PREDICTIONS_SHA,
    )
    candidate_sha = candidate["candidate_provenance_sha256"]
    if candidate.get("campaign_key") != EXPECTED_CAMPAIGN:
        raise LocalSpanTrainingAuditError("training campaign mismatch")
    if candidate.get("truth_used_for_candidate_construction") is not False:
        raise LocalSpanTrainingAuditError("candidate construction used truth")

    truth, receipt = validate_truth_file(truth_path)
    if receipt.get("completed_source_truth_sha256") != EXPECTED_LEDGER_SHA:
        raise LocalSpanTrainingAuditError("completed truth SHA mismatch")
    truth_pages = {int(page["page_number"]): page for page in truth["pages"]}
    prediction_pages = {int(page["page_number"]): page for page in predictions["pages"]}

    outcome_by_unit: dict[str, str] = {}
    for page_number, prediction_page in sorted(prediction_pages.items()):
        analysis = prediction_page["analysis"]
        spans = {int(row["index"]): row for row in analysis["spans"]}
        anchors = {str(row["anchor_id"]): row for row in analysis["price_anchors"]}
        source_regions = truth_pages[page_number]["source_regions"]
        for group in analysis["groups"]:
            adjudicated = adjudicate_group(
                page_number=page_number,
                group=group,
                spans=spans,
                anchors=anchors,
                source_regions=source_regions,
            )
            outcome_by_unit[adjudicated["prediction_unit_id"]] = adjudicated["outcome"]

    candidates = candidate_rows(candidate)
    outcomes = Counter(outcome_by_unit[row["prediction_unit_id"]] for row in candidates)
    if len(candidates) != EXPECTED_CANDIDATE_COUNT:
        raise LocalSpanTrainingAuditError(
            f"training candidate count drift: expected {EXPECTED_CANDIDATE_COUNT}, got {len(candidates)}"
        )
    if outcomes != Counter({"single_source": EXPECTED_SINGLE_COUNT}):
        raise LocalSpanTrainingAuditError(f"training candidate outcome drift: {dict(outcomes)}")

    cross_parent_reuse = int(candidate["cross_parent_group_reuse_count"])
    auto_precision = outcomes["single_source"] / len(candidates)
    return {
        "schema_version": 1,
        "strategy": STRATEGY,
        "candidate_strategy": candidate["strategy"],
        "campaign_key": EXPECTED_CAMPAIGN,
        "source_evidence_sha256": EXPECTED_SOURCE_EVIDENCE_SHA,
        "predictions_sha256": EXPECTED_PREDICTIONS_SHA,
        "completed_source_truth_sha256": EXPECTED_LEDGER_SHA,
        "candidate_provenance_sha256": candidate_sha,
        "prediction_group_count": candidate["prediction_group_count"],
        "parent_unit_count": candidate["parent_unit_count"],
        "candidate_auto_single_count": len(candidates),
        "candidate_outcome_counts": dict(sorted(outcomes.items())),
        "candidate_auto_single_precision": round(auto_precision, 6),
        "candidate_mixed_source_count": outcomes["mixed_source"],
        "candidate_excluded_control_count": outcomes["excluded_control"],
        "candidate_unresolved_count": sum(
            count for outcome, count in outcomes.items() if str(outcome).startswith("unresolved_")
        ),
        "cross_parent_group_reuse_count": cross_parent_reuse,
        "truth_loaded_only_after_candidate_freeze": True,
        "training_only": True,
        "next_heldout_campaign_must_not_equal_training_campaign": True,
        "review_only": True,
        "promotion_ready": False,
        "parser_behavior_changed": False,
    }


def _json_bytes(payload: Any) -> bytes:
    return (json.dumps(payload, ensure_ascii=False, sort_keys=True, indent=2) + "\n").encode("utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="Evaluate the frozen local-span candidate on exposed hz33 training truth.")
    parser.add_argument("--source-evidence", type=Path, required=True)
    parser.add_argument("--predictions", type=Path, required=True)
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    if args.output.exists() or args.output.is_symlink():
        raise LocalSpanTrainingAuditError("training output must be create-only")
    payload = run_training_audit(args.source_evidence, args.predictions, args.truth)
    encoded = _json_bytes(payload)
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_bytes(encoded)
    print(
        json.dumps(
            {
                "training_audit_sha256": hashlib.sha256(encoded).hexdigest(),
                "candidate_provenance_sha256": payload["candidate_provenance_sha256"],
                "candidate_auto_single_count": payload["candidate_auto_single_count"],
                "candidate_auto_single_precision": payload["candidate_auto_single_precision"],
                "candidate_mixed_source_count": payload["candidate_mixed_source_count"],
                "candidate_excluded_control_count": payload["candidate_excluded_control_count"],
                "candidate_unresolved_count": payload["candidate_unresolved_count"],
                "promotion_ready": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
