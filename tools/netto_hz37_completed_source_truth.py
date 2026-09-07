#!/usr/bin/env python3
from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any
import zipfile

import netto_hz34_completed_source_card_truth as base

CAMPAIGN = "hz37_hasb"
STORE = "5659"
SCOPE = "family_primary_netto"
VALID_FROM = "2026-09-07"
VALID_UNTIL = "2026-09-12"
SOURCE_SHA256 = "7b5b04bcf4af5c51f6ddfbd40096595e8a6da9cd7dd701c2d11b2916e0cd7951"
PDF_SHA256 = "7da859b19345891538521d2ec3b0be75fb9b2a2675626a6dbd942f15f1356322"
FREEZE_MANIFEST_SHA256 = "4f8381892d3b4e3847267c34c27a3b52131331b42c660ecb812cb5756f79617a"
V2_FREEZE_MANIFEST_SHA256 = "77da6e4ed772d3a513df8dafa6d20c6882ca7ad3da729ac3d76d0ece7b7d4922"
UPSTREAM_ARTIFACT_ID = 10022687292
UPSTREAM_RUN_ID = 34132489970
UPSTREAM_ARTIFACT_SHA256 = "6a6394e91df0aab2681f7c042397cc4c572f4254e3f7df008840165f97cae2dc"
REGISTERED_COMMIT = "fbe3cfa143788607446d0095ae1f887354d10eb3"
EXPECTED_PAGES = 73
STRATEGY = "netto_hz37_independent_source_truth_v1"
RECEIPT_STRATEGY = "netto_hz37_completed_source_truth_receipt_v1"

Hz37CompletedTruthError = base.Hz34CompletedTruthError


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def _read_json_member(archive: zipfile.ZipFile, name: str) -> tuple[dict[str, Any], bytes]:
    try:
        raw = archive.read(name)
    except KeyError as exc:
        raise Hz37CompletedTruthError(f"required review-pack member missing: {name}") from exc
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeError, json.JSONDecodeError) as exc:
        raise Hz37CompletedTruthError(f"invalid review-pack JSON: {name}") from exc
    if not isinstance(payload, dict):
        raise Hz37CompletedTruthError(f"review-pack JSON root must be object: {name}")
    return payload, raw


def _bind_hz37(
    review_pack_zip: Path,
    *,
    review_pack_artifact_id: int,
    review_pack_workflow_run_id: int,
    review_pack_artifact: str,
    review_pack_artifact_digest: str,
) -> None:
    if review_pack_artifact_id <= 0 or review_pack_workflow_run_id <= 0:
        raise Hz37CompletedTruthError("review-pack artifact/run IDs must be positive")
    if not review_pack_artifact.startswith("netto-hz37-blind-review-pack-"):
        raise Hz37CompletedTruthError("unexpected review-pack artifact name")
    if not re.fullmatch(r"sha256:[0-9a-f]{64}", review_pack_artifact_digest):
        raise Hz37CompletedTruthError("review-pack artifact digest must be sha256:<hex>")
    if review_pack_zip.is_symlink() or not review_pack_zip.is_file():
        raise Hz37CompletedTruthError("review-pack ZIP must be regular non-symlink file")

    with zipfile.ZipFile(review_pack_zip) as archive:
        manifest, manifest_raw = _read_json_member(archive, "manifest.json")
        ledger, ledger_raw = _read_json_member(archive, "independent-source-card-review-ledger.json")
        source_receipt, source_receipt_raw = _read_json_member(archive, "artifact-source-receipt.json")

    expected_manifest = {
        "campaign_key": CAMPAIGN,
        "campaign_window": {"start": VALID_FROM, "end": VALID_UNTIL},
        "store_external_id": STORE,
        "scope": SCOPE,
        "source_sha256": SOURCE_SHA256,
        "source_pdf_sha256": PDF_SHA256,
        "freeze_manifest_sha256": FREEZE_MANIFEST_SHA256,
        "page_count": EXPECTED_PAGES,
    }
    for key, value in expected_manifest.items():
        if manifest.get(key) != value:
            raise Hz37CompletedTruthError(f"review-pack manifest mismatch: {key}")
    if ledger.get("review_state") != "blank_before_independent_source_card_review":
        raise Hz37CompletedTruthError("review-pack ledger is not blank")
    if ledger.get("page_count") != EXPECTED_PAGES:
        raise Hz37CompletedTruthError("review-pack ledger page count mismatch")

    expected_source_receipt = {
        "artifact_id": UPSTREAM_ARTIFACT_ID,
        "workflow_run_id": UPSTREAM_RUN_ID,
        "artifact_zip_sha256": UPSTREAM_ARTIFACT_SHA256,
        "registered_commit": REGISTERED_COMMIT,
        "campaign_key": CAMPAIGN,
        "source_sha256": SOURCE_SHA256,
        "source_pdf_sha256": PDF_SHA256,
        "freeze_manifest_sha256": FREEZE_MANIFEST_SHA256,
        "v2_freeze_manifest_sha256": V2_FREEZE_MANIFEST_SHA256,
        "page_count": EXPECTED_PAGES,
        "prediction_payload_parsed": False,
        "candidate_provenance_payload_parsed": False,
        "parser_predictions_included": False,
        "candidate_provenance_included": False,
        "expected_truth_included": False,
        "live_source_refetch_performed": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "publication_write_performed": False,
        "deployment_performed": False,
    }
    for key, value in expected_source_receipt.items():
        if source_receipt.get(key) != value:
            raise Hz37CompletedTruthError(f"artifact-source receipt mismatch: {key}")

    base.CAMPAIGN = CAMPAIGN
    base.STORE = STORE
    base.SCOPE = SCOPE
    base.VALID_FROM = VALID_FROM
    base.VALID_UNTIL = VALID_UNTIL
    base.SOURCE_SHA256 = SOURCE_SHA256
    base.PDF_SHA256 = PDF_SHA256
    base.FREEZE_MANIFEST_SHA256 = FREEZE_MANIFEST_SHA256
    base.REVIEW_PACK_MANIFEST_SHA256 = sha256_bytes(manifest_raw)
    base.BLANK_LEDGER_SHA256 = sha256_bytes(ledger_raw)
    base.ARTIFACT_SOURCE_RECEIPT_SHA256 = sha256_bytes(source_receipt_raw)
    base.REVIEW_PACK_ARTIFACT_ID = review_pack_artifact_id
    base.REVIEW_PACK_RUN_ID = review_pack_workflow_run_id
    base.REVIEW_PACK_ARTIFACT = review_pack_artifact
    base.REVIEW_PACK_ARTIFACT_DIGEST = review_pack_artifact_digest
    base.EXPECTED_PAGES = EXPECTED_PAGES
    base.STRATEGY = STRATEGY
    base.RECEIPT_STRATEGY = RECEIPT_STRATEGY


def validate_truth_file(
    truth_path: Path,
    review_pack_zip: Path,
    *,
    review_pack_artifact_id: int,
    review_pack_workflow_run_id: int,
    review_pack_artifact: str,
    review_pack_artifact_digest: str,
):
    _bind_hz37(
        review_pack_zip,
        review_pack_artifact_id=review_pack_artifact_id,
        review_pack_workflow_run_id=review_pack_workflow_run_id,
        review_pack_artifact=review_pack_artifact,
        review_pack_artifact_digest=review_pack_artifact_digest,
    )
    return base.validate_truth_file(truth_path, review_pack_zip)


def receipt_bytes(receipt: dict[str, Any]) -> bytes:
    return base.receipt_bytes(receipt)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate independently completed Netto hz37 source truth before candidate exposure."
    )
    parser.add_argument("--truth", type=Path, required=True)
    parser.add_argument("--review-pack-zip", type=Path, required=True)
    parser.add_argument("--review-pack-artifact-id", type=int, required=True)
    parser.add_argument("--review-pack-run-id", type=int, required=True)
    parser.add_argument("--review-pack-artifact", required=True)
    parser.add_argument("--review-pack-digest", required=True)
    parser.add_argument("--write-receipt", type=Path)
    args = parser.parse_args()
    _, receipt, _ = validate_truth_file(
        args.truth,
        args.review_pack_zip,
        review_pack_artifact_id=args.review_pack_artifact_id,
        review_pack_workflow_run_id=args.review_pack_run_id,
        review_pack_artifact=args.review_pack_artifact,
        review_pack_artifact_digest=args.review_pack_digest,
    )
    encoded = receipt_bytes(receipt)
    if args.write_receipt:
        if args.write_receipt.exists() or args.write_receipt.is_symlink():
            raise Hz37CompletedTruthError("receipt output must be create-only")
        args.write_receipt.parent.mkdir(parents=True, exist_ok=True)
        args.write_receipt.write_bytes(encoded)
    print(json.dumps({**receipt, "receipt_sha256": sha256_bytes(encoded)}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
