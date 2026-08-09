#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any

STRATEGY = "netto_heldout_independent_source_truth_ledger_v1"
EXPECTED_CAMPAIGN = "hz33_hasb"
EXPECTED_STORE = "5659"
EXPECTED_SCOPE = "family_primary_netto"
SOURCE_SCOPES = ("in_scope", "excluded_non_target")
BOUNDARY_STATES = ("clear_single_card", "partial_single_card")
PREDICTION_OUTCOMES = ("single_source", "mixed_source", "excluded_control")


class SourceTruthLedgerError(ValueError):
    pass


def sha_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise SourceTruthLedgerError(f"required input is missing or unsafe: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise SourceTruthLedgerError(f"invalid JSON: {path}") from exc
    if not isinstance(value, dict):
        raise SourceTruthLedgerError(f"JSON root must be an object: {path}")
    return value


def write_create_only(path: Path, payload: dict[str, Any]) -> str:
    data = (json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except FileExistsError as exc:
        raise SourceTruthLedgerError(f"output already exists: {path}") from exc
    return sha256(data).hexdigest()


def require_sha(value: object, label: str) -> str:
    text = str(value or "").strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise SourceTruthLedgerError(f"{label} is not a SHA256")
    return text


def build_source_truth_ledger(
    review_pack_root: Path,
    output: Path,
    *,
    expected_pack_manifest_sha256: str,
    expected_blank_ledger_sha256: str,
    expected_page_count: int,
) -> dict[str, Any]:
    if output.exists() or output.is_symlink():
        raise SourceTruthLedgerError("output directory must be create-only")
    if review_pack_root.is_symlink() or not review_pack_root.is_dir():
        raise SourceTruthLedgerError("review pack root must be a regular directory")

    expected_pack_manifest_sha256 = require_sha(
        expected_pack_manifest_sha256, "expected pack manifest"
    )
    expected_blank_ledger_sha256 = require_sha(
        expected_blank_ledger_sha256, "expected old blank ledger"
    )
    manifest_path = review_pack_root / "manifest.json"
    old_ledger_path = review_pack_root / "independent-source-card-review-ledger.json"
    if sha_file(manifest_path) != expected_pack_manifest_sha256:
        raise SourceTruthLedgerError("review-pack manifest SHA mismatch")
    if sha_file(old_ledger_path) != expected_blank_ledger_sha256:
        raise SourceTruthLedgerError("old blank-ledger SHA mismatch")

    manifest = load_json(manifest_path)
    old_ledger = load_json(old_ledger_path)
    if manifest.get("campaign_key") != EXPECTED_CAMPAIGN:
        raise SourceTruthLedgerError("campaign mismatch")
    if manifest.get("store_external_id") != EXPECTED_STORE:
        raise SourceTruthLedgerError("store mismatch")
    if manifest.get("scope") != EXPECTED_SCOPE:
        raise SourceTruthLedgerError("scope mismatch")
    if manifest.get("page_count") != expected_page_count:
        raise SourceTruthLedgerError("manifest page-count mismatch")
    contract = manifest.get("blind_review_contract") or {}
    if contract.get("parser_predictions_included") is not False:
        raise SourceTruthLedgerError("review pack exposed parser predictions")
    if contract.get("expected_truth_included") is not False:
        raise SourceTruthLedgerError("review pack exposed expected truth")
    if contract.get("presegmented_review_units") is not False:
        raise SourceTruthLedgerError("review pack contains presegmented units")

    pages = old_ledger.get("pages")
    if not isinstance(pages, list) or len(pages) != expected_page_count:
        raise SourceTruthLedgerError("old blank ledger pages are incomplete")
    if any(not isinstance(row, dict) or row.get("source_cards") != [] for row in pages):
        raise SourceTruthLedgerError("old ledger is no longer blank")

    source_pages = []
    for row in pages:
        page_number = int(row["page_number"])
        source_pages.append(
            {
                "page_number": page_number,
                "page_width_points": row["page_width_points"],
                "page_height_points": row["page_height_points"],
                "source_regions": [],
            }
        )

    ledger = {
        "schema_version": 1,
        "strategy": STRATEGY,
        "campaign_key": manifest["campaign_key"],
        "campaign_window": manifest["campaign_window"],
        "store_external_id": manifest["store_external_id"],
        "scope": manifest["scope"],
        "source_sha256": manifest["source_sha256"],
        "source_pdf_sha256": manifest["source_pdf_sha256"],
        "freeze_manifest_sha256": manifest["freeze_manifest_sha256"],
        "review_pack_manifest_sha256": expected_pack_manifest_sha256,
        "supersedes_blank_ledger_sha256": expected_blank_ledger_sha256,
        "coordinate_space": "unrotated_page_points",
        "page_count": expected_page_count,
        "review_state": "blank_before_independent_source_truth_review",
        "truth_unit": "independent_source_region",
        "source_scope_classes": list(SOURCE_SCOPES),
        "boundary_states": list(BOUNDARY_STATES),
        "source_region_schema": {
            "source_region_id": "reviewer-assigned stable pNNN-rNNN identifier",
            "rect_points": ["x0", "y0", "x1", "y1"],
            "scope_classification": list(SOURCE_SCOPES),
            "boundary_state": list(BOUNDARY_STATES),
            "observed_label": "optional source-only label",
            "reviewer_confidence": ["high", "medium", "low"],
            "reviewer_note": "optional source-only note",
        },
        "prediction_ownership_derivation": {
            "performed_during_source_review": False,
            "allowed_only_after_completed_truth_sha_is_frozen": True,
            "outcome_classes": list(PREDICTION_OUTCOMES),
            "single_source": "frozen prediction region maps to exactly one independent in-scope source region",
            "mixed_source": "frozen prediction region maps to multiple independent in-scope source regions",
            "excluded_control": "frozen prediction region maps only to excluded/non-target source area",
        },
        "parser_predictions_included": False,
        "expected_truth_included": False,
        "adjudication_started": False,
        "pages": source_pages,
    }

    output.mkdir(parents=True, mode=0o700)
    ledger_sha = write_create_only(output / "independent-source-truth-ledger.json", ledger)
    receipt = {
        "schema_version": 1,
        "strategy": STRATEGY,
        "campaign_key": ledger["campaign_key"],
        "page_count": expected_page_count,
        "review_pack_manifest_sha256": expected_pack_manifest_sha256,
        "superseded_blank_ledger_sha256": expected_blank_ledger_sha256,
        "source_truth_ledger_sha256": ledger_sha,
        "parser_predictions_included": False,
        "expected_truth_included": False,
        "adjudication_started": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "deployment_performed": False,
        "promotion_ready": False,
    }
    receipt_sha = write_create_only(output / "source-truth-ledger-receipt.json", receipt)
    sums = (
        f"{ledger_sha}  independent-source-truth-ledger.json\n"
        f"{receipt_sha}  source-truth-ledger-receipt.json\n"
    )
    (output / "SHA256SUMS").write_text(sums, encoding="utf-8")
    return {**receipt, "receipt_sha256": receipt_sha}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--review-pack-root", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--expected-pack-manifest-sha256", required=True)
    parser.add_argument("--expected-blank-ledger-sha256", required=True)
    parser.add_argument("--expected-page-count", type=int, required=True)
    args = parser.parse_args()
    payload = build_source_truth_ledger(
        args.review_pack_root,
        args.output,
        expected_pack_manifest_sha256=args.expected_pack_manifest_sha256,
        expected_blank_ledger_sha256=args.expected_blank_ledger_sha256,
        expected_page_count=args.expected_page_count,
    )
    print(json.dumps(payload, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
