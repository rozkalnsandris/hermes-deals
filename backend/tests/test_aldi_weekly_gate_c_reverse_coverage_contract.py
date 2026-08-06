from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "aldi_weekly_gate_c_shadow_replay_preflight.py"
SPEC = importlib.util.spec_from_file_location(
    "aldi_weekly_gate_c_reverse_coverage_contract", TOOL
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def _legacy_bundle() -> dict[str, object]:
    mappings: list[dict[str, object]] = []
    reverse: list[dict[str, object]] = []
    for index in range(400):
        status = "auto_candidate" if index < 346 else "review_required"
        page = (index % 41) + 1
        card_id = f"preview:p{page:03d}:c{index + 1:03d}"
        offer_key = f"preview:{1000000 + index}"
        mappings.append(
            {
                "offer_key": offer_key,
                "publication_status": status,
                "match_status": "matched",
                "match_method": "explicit_offer_id",
                "card_id": card_id,
                "score": None,
                "candidate_card_ids": [card_id],
                "display_title": f"Offer {index}",
                "price_eur": "1.00",
                "review_reasons": ["frozen_review"]
                if status == "review_required"
                else [],
                "source_offer_id": str(1000000 + index),
                "source_page": "preview",
                "title_tokens": ["offer", str(index)],
                "brand_tokens": [],
            }
        )
        reverse.append(
            {
                "card_id": card_id,
                "source_page": "preview",
                "page_number": page,
                "scope": "in_scope" if status == "auto_candidate" else "review",
                "matched_offer_keys": [offer_key],
                "unmatched_reason": "",
                "unexplained": False,
            }
        )

    summary = {
        "schema_version": 1,
        "strategy": "aldi_a31_deterministic_bidirectional_parity_v1",
        "target_counts": dict(MODULE.EXPECTED_TARGET_COUNTS),
        "target_candidate_count": 400,
        "matched_candidate_count": 400,
        "review_unmatched_count": 0,
        "blocked_candidate_count": 0,
        "card_count": 400,
        "in_scope_or_review_card_count": 400,
        "unexplained_card_count": 0,
        "blocker_count": 0,
        "mapping_sha256": MODULE.canonical_sha(mappings),
        "reverse_coverage_sha256": MODULE.canonical_sha(reverse),
        "result": "pass",
        "shadow_only": True,
        "production_eligible": False,
        "production_apply_authorized": False,
        "database_write_performed": False,
        "deployment_performed": False,
        "collector_executed": False,
        "automatic_approval_count": 0,
        "automatic_publication_count": 0,
    }
    return {
        "schema_version": 1,
        "mode": MODULE.LEGACY_BUNDLE_MODE,
        "input_projection_sha256": MODULE.EXPECTED_A21_PROJECTION_SHA256,
        "summary": summary,
        "offer_to_card_mapping": mappings,
        "reverse_card_coverage": reverse,
        "blockers": [],
    }


def test_legacy_reverse_coverage_cannot_omit_a_mapped_card() -> None:
    bundle = _legacy_bundle()
    reverse = bundle["reverse_card_coverage"]
    assert isinstance(reverse, list)
    reverse.pop()

    summary = bundle["summary"]
    assert isinstance(summary, dict)
    summary["card_count"] = len(reverse)
    summary["in_scope_or_review_card_count"] = len(reverse)
    summary["reverse_coverage_sha256"] = MODULE.canonical_sha(reverse)

    with pytest.raises(
        MODULE.GateCError,
        match="legacy reverse coverage missing mapped cards",
    ):
        MODULE.validate_legacy_parity_bundle(
            bundle,
            file_sha256=MODULE.canonical_sha(bundle),
        )
