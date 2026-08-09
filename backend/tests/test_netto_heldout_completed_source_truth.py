from __future__ import annotations

import base64
from copy import deepcopy
import gzip
import hashlib
import json
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from netto_heldout_completed_source_truth import (  # noqa: E402
    CompletedSourceTruthError,
    EXPECTED_GZIP_SHA,
    EXPECTED_LEDGER_SHA,
    build_receipt,
    receipt_bytes,
    validate_file,
    validate_payload,
)

PAYLOAD = REPO_ROOT / "evidence/netto/heldout/hz33/completed-independent-source-truth-ledger.json.gz.b64"
RECEIPT = REPO_ROOT / "evidence/netto/heldout/hz33/completed-source-truth-receipt.json"
EXPECTED_RECEIPT_SHA = "62f8658370f1f14dd4465441a2f31789272dad761d181fb9419b1f44470f8b46"


def test_repository_completed_source_truth_is_exact_and_frozen() -> None:
    encoded = PAYLOAD.read_text(encoding="ascii").strip()
    compressed = base64.b64decode(encoded, validate=True)
    assert hashlib.sha256(compressed).hexdigest() == EXPECTED_GZIP_SHA
    raw = gzip.decompress(compressed)
    assert hashlib.sha256(raw).hexdigest() == EXPECTED_LEDGER_SHA

    payload, receipt = validate_file(PAYLOAD)
    assert payload["review_state"] == "completed_independent_source_truth_before_prediction_adjudication"
    assert receipt == {
        "schema_version": 1,
        "strategy": "netto_heldout_completed_source_truth_receipt_v1",
        "campaign_key": "hz33_hasb",
        "completed_source_truth_sha256": EXPECTED_LEDGER_SHA,
        "compressed_payload_sha256": EXPECTED_GZIP_SHA,
        "review_pack_manifest_sha256": "e47e1acc337f55dcdbbbfbbb5c200b3c100427ee5e022ad7d0e5e947e2f7274c",
        "source_sha256": "e38bfa550ce64aae0d2cefcec307ca4126c8753374a64d76cc2684a98b788bcb",
        "source_pdf_sha256": "7e9ac8c87b6a1c0f25f1832def945bfbe0c2be9b3371d897d98079d88789c0ba",
        "freeze_manifest_sha256": "38bb9445ad5f2c3cc0159bd4332a4138f1d81cab03591de0542825b3f88db087",
        "page_count": 77,
        "source_region_count": 341,
        "in_scope_region_count": 309,
        "excluded_non_target_region_count": 32,
        "partial_single_card_count": 9,
        "frozen_predictions_opened": False,
        "adjudication_started": False,
        "review_only": True,
        "promotion_ready": False,
    }
    expected_receipt_bytes = receipt_bytes(receipt)
    assert hashlib.sha256(expected_receipt_bytes).hexdigest() == EXPECTED_RECEIPT_SHA
    assert RECEIPT.read_bytes() == expected_receipt_bytes


def test_source_truth_rejects_prediction_ownership_leak() -> None:
    payload, _ = validate_file(PAYLOAD)
    tampered = deepcopy(payload)
    tampered["pages"][0]["source_regions"][0]["ownership_class"] = "single_source"
    with pytest.raises(CompletedSourceTruthError, match="prediction fields leaked"):
        validate_payload(tampered)


def test_source_truth_rejects_positive_area_overlap() -> None:
    payload, _ = validate_file(PAYLOAD)
    tampered = deepcopy(payload)
    first = tampered["pages"][0]["source_regions"][0]
    second = tampered["pages"][0]["source_regions"][1]
    second["rect_points"] = list(first["rect_points"])
    with pytest.raises(CompletedSourceTruthError, match="rectangles overlap"):
        validate_payload(tampered)


def test_source_truth_rejects_prediction_exposure_process_state() -> None:
    payload, _ = validate_file(PAYLOAD)
    tampered = deepcopy(payload)
    tampered["reviewer_process"]["frozen_predictions_opened"] = True
    with pytest.raises(CompletedSourceTruthError, match="exposed to frozen predictions"):
        validate_payload(tampered)


def test_source_truth_receipt_is_deterministic() -> None:
    payload, _ = validate_file(PAYLOAD)
    summary = validate_payload(payload)
    first = receipt_bytes(build_receipt(summary))
    second = receipt_bytes(build_receipt(summary))
    assert first == second
    assert hashlib.sha256(first).hexdigest() == EXPECTED_RECEIPT_SHA
