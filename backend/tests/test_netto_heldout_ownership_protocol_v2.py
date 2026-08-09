from __future__ import annotations

import copy
from pathlib import Path
import sys

import pytest

TOOLS_DIR = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from netto_heldout_ownership_protocol import ACCEPTANCE, freeze_receipt
from netto_heldout_ownership_protocol_v2 import (
    EXPECTED_CANDIDATE_CONFIG,
    FORBIDDEN_HELDOUT_CAMPAIGNS,
    HeldoutV2Error,
    PARENT_REUSE_METRIC,
    PROTOCOL_NAME,
    automatic_candidate_parent_reuse_count,
    prepare_v2_freeze,
)
from netto_local_span_auto_single_candidate import STRATEGY, payload_sha256


SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64


def _base_manifest(campaign: str = "hz34_hasb") -> dict:
    return {
        "schema_version": 1,
        "protocol": "netto-heldout-ownership-v1",
        "store_external_id": "5659",
        "campaign_key": campaign,
        "campaign_window": {"start": "2026-08-17", "end": "2026-08-22"},
        "source_sha256": SHA_A,
        "parser_identity": "netto-visual-geometry-shadow-v3-unrotated-page-space",
        "evidence_sha256": SHA_B,
        "predictions_sha256": SHA_C,
        "truth_sha256": None,
        "adjudication_sha256": None,
        "acceptance": dict(ACCEPTANCE),
        "ownership_classes": ["single_source", "mixed_source", "excluded_control"],
        "review_only": True,
        "promotion_ready": False,
    }


def _candidate() -> dict:
    payload = {
        "schema_version": 1,
        "strategy": STRATEGY,
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "campaign_key": "hz34_hasb",
        "campaign_window": {"start": "2026-08-17", "end": "2026-08-22"},
        "source_identity_sha256": SHA_A,
        "source_pdf_sha256": SHA_D,
        "prediction_parser_identity": "netto-visual-geometry-shadow-v3-unrotated-page-space",
        "page_count": 1,
        "source_evidence_sha256": SHA_B,
        "predictions_sha256": SHA_C,
        "config": copy.deepcopy(EXPECTED_CANDIDATE_CONFIG),
        "prediction_group_count": 2,
        "parent_unit_count": 2,
        "candidate_auto_single_count": 1,
        "cross_parent_group_reuse_count": 0,
        "truth_used_for_candidate_construction": False,
        "automatic_candidate_decisions_frozen": True,
        "review_only": True,
        "promotion_ready": False,
        "parser_behavior_changed": False,
        "pages": [
            {
                "page_number": 1,
                "parent_units": [
                    {
                        "parent_unit_id": "p001-c001",
                        "prediction_unit_ids": ["p001-g001"],
                    },
                    {
                        "parent_unit_id": "p001-c002",
                        "prediction_unit_ids": ["p001-g002"],
                    },
                ],
                "groups": [
                    {
                        "prediction_unit_id": "p001-g001",
                        "parent_unit_ids": ["p001-c001"],
                        "primary_parent_unit_id": "p001-c001",
                        "candidate_auto_single": True,
                        "candidate_reasons": ["conservative_local_span_component_candidate"],
                    },
                    {
                        "prediction_unit_id": "p001-g002",
                        "parent_unit_ids": ["p001-c002"],
                        "primary_parent_unit_id": "p001-c002",
                        "candidate_auto_single": False,
                        "candidate_reasons": ["owned_node_fraction_below_minimum"],
                    },
                ],
            }
        ],
    }
    payload["candidate_provenance_sha256"] = payload_sha256(payload)
    return payload


def test_v2_freezes_candidate_provenance_without_changing_v1_acceptance() -> None:
    base = _base_manifest()
    manifest, receipt = prepare_v2_freeze(
        base,
        freeze_receipt(base),
        _candidate(),
        candidate_file_sha256=SHA_E,
        candidate_implementation_commit="1" * 40,
    )

    assert manifest["protocol"] == PROTOCOL_NAME
    assert manifest["acceptance"] == ACCEPTANCE
    assert manifest["candidate_strategy"] == STRATEGY
    assert manifest["candidate_auto_single_count"] == 1
    assert manifest["automatic_candidate_parent_reuse_count"] == 0
    assert manifest["parent_reuse_metric"] == PARENT_REUSE_METRIC
    assert manifest["truth_sha256"] is None
    assert manifest["adjudication_sha256"] is None
    assert manifest["truth_available_at_freeze"] is False
    assert manifest["review_only"] is True
    assert manifest["promotion_ready"] is False
    assert receipt["candidate_provenance_sha256"] == manifest["candidate_provenance_sha256"]
    assert receipt["candidate_decisions_sha256"] == manifest["candidate_decisions_sha256"]
    assert receipt["automatic_candidate_parent_reuse_count"] == 0


def test_v2_forbids_all_exposed_campaigns_and_rejects_hz33_after_valid_v1_freeze() -> None:
    assert {"hz31_hasb_4", "hz32_hasb", "hz33_hasb"} <= FORBIDDEN_HELDOUT_CAMPAIGNS

    # hz31/hz32 are already rejected by v1. hz33 is the important new v2
    # exclusion because v1 legitimately froze it before its truth was exposed.
    base = _base_manifest("hz33_hasb")
    candidate = _candidate()
    candidate["campaign_key"] = "hz33_hasb"
    candidate["candidate_provenance_sha256"] = payload_sha256(
        {key: value for key, value in candidate.items() if key != "candidate_provenance_sha256"}
    )
    with pytest.raises(HeldoutV2Error, match="overlaps exposed"):
        prepare_v2_freeze(
            base,
            freeze_receipt(base),
            candidate,
            candidate_file_sha256=SHA_E,
            candidate_implementation_commit="1" * 40,
        )


def test_v2_rejects_post_freeze_candidate_tampering_and_config_drift() -> None:
    base = _base_manifest()
    candidate = _candidate()
    candidate["candidate_auto_single_count"] = 2
    with pytest.raises(HeldoutV2Error, match="provenance digest mismatch"):
        prepare_v2_freeze(
            base,
            freeze_receipt(base),
            candidate,
            candidate_file_sha256=SHA_E,
            candidate_implementation_commit="1" * 40,
        )

    candidate = _candidate()
    candidate["config"]["graph_gap_multiplier"] = 0.75
    candidate["candidate_provenance_sha256"] = payload_sha256(
        {key: value for key, value in candidate.items() if key != "candidate_provenance_sha256"}
    )
    with pytest.raises(HeldoutV2Error, match="config drift"):
        prepare_v2_freeze(
            base,
            freeze_receipt(base),
            candidate,
            candidate_file_sha256=SHA_E,
            candidate_implementation_commit="1" * 40,
        )


def test_parent_reuse_metric_is_specific_to_automatic_candidates() -> None:
    candidate = _candidate()
    candidate["cross_parent_group_reuse_count"] = 208
    candidate["candidate_provenance_sha256"] = payload_sha256(
        {key: value for key, value in candidate.items() if key != "candidate_provenance_sha256"}
    )
    assert automatic_candidate_parent_reuse_count(candidate) == 0

    candidate["pages"][0]["parent_units"][0]["prediction_unit_ids"].append("p001-g002")
    assert automatic_candidate_parent_reuse_count(candidate) == 1
