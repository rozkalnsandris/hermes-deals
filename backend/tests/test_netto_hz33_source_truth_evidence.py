from __future__ import annotations

import base64
from collections import Counter
import gzip
from hashlib import sha256
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
EVIDENCE = ROOT / "evidence" / "netto" / "hz33"
LEDGER_PARTS = sorted(EVIDENCE.glob("independent-source-truth-ledger.part-*.b64"))
RECEIPT = EVIDENCE / "independent-source-truth-review-receipt.json"
EXPECTED_LEDGER_SHA = "4bb9f6f54bb7431cf19eabac3167958ec330faa3aa5874a776eebb460f97a2a5"
EXPECTED_GZIP_SHA = "0df5d30195b6f095784c4fce7e70f679e9d30057cfb826cdd392db9366b07c76"
EXPECTED_RECEIPT_SHA = "c208daecd0fbbb798336b482f0f0298b5d1bb2e3fcc00db731d496fc30da8fa3"


def _ledger_bytes() -> bytes:
    assert len(LEDGER_PARTS) == 5
    encoded = "".join(part.read_text(encoding="ascii").strip() for part in LEDGER_PARTS)
    compressed = base64.b64decode(encoded, validate=True)
    assert sha256(compressed).hexdigest() == EXPECTED_GZIP_SHA
    return gzip.decompress(compressed)


def test_hz33_source_truth_is_complete_source_only_and_content_addressed() -> None:
    raw = _ledger_bytes()
    assert sha256(raw).hexdigest() == EXPECTED_LEDGER_SHA
    assert sha256(RECEIPT.read_bytes()).hexdigest() == EXPECTED_RECEIPT_SHA

    ledger = json.loads(raw)
    receipt = json.loads(RECEIPT.read_text(encoding="utf-8"))

    assert ledger["strategy"] == "netto_heldout_independent_source_truth_ledger_v1"
    assert ledger["review_state"] == "completed_independent_source_truth_review"
    assert ledger["campaign_key"] == "hz33_hasb"
    assert ledger["campaign_window"] == {"start": "2026-08-10", "end": "2026-08-15"}
    assert ledger["store_external_id"] == "5659"
    assert ledger["scope"] == "family_primary_netto"
    assert ledger["source_sha256"] == "e38bfa550ce64aae0d2cefcec307ca4126c8753374a64d76cc2684a98b788bcb"
    assert ledger["source_pdf_sha256"] == "7e9ac8c87b6a1c0f25f1832def945bfbe0c2be9b3371d897d98079d88789c0ba"
    assert ledger["freeze_manifest_sha256"] == "38bb9445ad5f2c3cc0159bd4332a4138f1d81cab03591de0542825b3f88db087"
    assert ledger["review_pack_manifest_sha256"] == "e47e1acc337f55dcdbbbfbbb5c200b3c100427ee5e022ad7d0e5e947e2f7274c"
    assert ledger["supersedes_blank_ledger_sha256"] == "bc7170d05f075bcd7d90d12952b5811b14a51e69da60304337fcb4aeec557f55"
    assert ledger["page_count"] == 77
    assert ledger["parser_predictions_included"] is False
    assert ledger["expected_truth_included"] is False
    assert ledger["adjudication_started"] is False

    pages = ledger["pages"]
    assert [page["page_number"] for page in pages] == list(range(1, 78))
    regions = []
    for page_number, page in enumerate(pages, 1):
        page_regions = page["source_regions"]
        assert page_regions
        width = page["page_width_points"]
        height = page["page_height_points"]
        for region_number, region in enumerate(page_regions, 1):
            assert region["source_region_id"] == f"p{page_number:03d}-r{region_number:03d}"
            x0, y0, x1, y1 = region["rect_points"]
            assert 0 <= x0 < x1 <= width
            assert 0 <= y0 < y1 <= height
            assert region["scope_classification"] in {"in_scope", "excluded_non_target"}
            assert region["boundary_state"] in {"clear_single_card", "partial_single_card"}
            assert region["reviewer_confidence"] in {"high", "medium", "low"}
            assert region["observed_label"].strip()
            assert "ownership_class" not in region
            regions.append(region)

    assert len(regions) == 405
    assert Counter(region["scope_classification"] for region in regions) == {
        "in_scope": 274,
        "excluded_non_target": 131,
    }
    assert Counter(region["boundary_state"] for region in regions) == {"clear_single_card": 405}
    assert Counter(region["reviewer_confidence"] for region in regions) == {"high": 394, "medium": 11}

    text = raw.decode("utf-8")
    for forbidden in (
        "predictions_sha256",
        "70c3c8abace632f6be298abb5d02b398b3e8b91e8d53565b21eface536ed7b94",
        "netto-visual-geometry-shadow-v3-unrotated-page-space",
        "truth_sha256",
        "adjudication_sha256",
    ):
        assert forbidden not in text

    assert receipt["completed_source_truth_ledger_sha256"] == EXPECTED_LEDGER_SHA
    assert receipt["repository_evidence_encoding"] == "gzip+base64-concatenated-parts"
    assert receipt["repository_evidence_parts"] == [
        f"evidence/netto/hz33/independent-source-truth-ledger.part-{index:03d}.b64"
        for index in range(1, 6)
    ]
    assert receipt["repository_evidence_gzip_sha256"] == EXPECTED_GZIP_SHA
    assert receipt["page_order"] == "strict_ascending_1_to_77"
    assert receipt["pages_reviewed"] == 77
    assert receipt["source_region_count"] == 405
    assert receipt["scope_counts"] == {"excluded_non_target": 131, "in_scope": 274}
    assert receipt["predictions_opened"] is False
    assert receipt["prediction_payload_used"] is False
    assert receipt["adjudication_started"] is False
    assert receipt["parser_or_threshold_changed"] is False
    assert receipt["database_write_performed"] is False
    assert receipt["review_write_performed"] is False
    assert receipt["deployment_performed"] is False
    assert receipt["scheduler_or_host_change_performed"] is False
    assert receipt["b15m2_issue_20_touched"] is False
