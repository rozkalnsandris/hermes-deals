from __future__ import annotations

from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import edeka_accounted_live_provenance_bridge as accounted  # noqa: E402
import edeka_candidate_provenance as gate_c  # noqa: E402


RAW_SHA = "a" * 64
MANIFEST_SHA = "b" * 64
ACCOUNTING_SHA = "c" * 64
SNAPSHOT_ID = "11111111-2222-4333-8444-555555555555"
PARSED_ID = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
EXCLUDED_ID = "68aa5875-e4e1-4a5b-8d6c-221a2319dc2b"


def _base() -> dict[str, object]:
    manifest = {
        "schema_version": 1,
        "strategy": "edeka_regional_source_manifest_v1",
        "retailer": "edeka",
        "public_market_code": "071897",
        "source_market_id": "587881",
        "scope": "family_primary_edeka",
        "campaign_id": "edeka-071897-2026-08-10-2026-08-15-aaaaaaaaaaaaaaaa",
        "valid_from": "2026-08-10",
        "valid_to": "2026-08-15",
        "source_url": "https://www.edeka.de/maerkte/071897/angebote/",
        "source_sha256": RAW_SHA,
        "manifest_sha256": MANIFEST_SHA,
        "parser_identity": "edeka-v1",
        "source_state": "available",
        "fallback_allowed": False,
        "ambiguous_rows_route": "review_required",
        "database_write_authorized": False,
        "review_write_authorized": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "production_apply_authorized": False,
    }
    return {
        "schema_version": 1,
        "strategy": "edeka_candidate_provenance_v1",
        "manifest": manifest,
        "candidates": [
            {
                "candidate_id": PARSED_ID,
                "campaign_id": manifest["campaign_id"],
                "source_sha256": RAW_SHA,
                "manifest_sha256": MANIFEST_SHA,
                "parser_identity": "edeka-v1",
                "page_number": 1,
                "card_id": f"dialog-angebot-{PARSED_ID}",
                "route": "automatic_candidate",
                "ambiguous": False,
                "provenance_complete": True,
            }
        ],
        "database_write_authorized": False,
        "review_write_authorized": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "production_apply_authorized": False,
        "live_evidence": {
            "source_snapshot_id": SNAPSHOT_ID,
            "offer_count": 1,
            "production_database_write": False,
            "production_deployment": False,
            "scheduler_activation": False,
        },
    }


def _accounting() -> dict[str, object]:
    return {
        "schema_version": 1,
        "audit_type": "edeka_source_card_accounting",
        "manifest_sha256": MANIFEST_SHA,
        "raw_html_sha256": RAW_SHA,
        "parser_version": "edeka-v1",
        "report_sha256": ACCOUNTING_SHA,
        "source": {
            "snapshot_id": SNAPSHOT_ID,
        },
        "summary": {
            "source_card_count": 2,
            "parsed_offer_count": 1,
            "excluded_count": 1,
            "accounting_complete": True,
            "unexplained_source_card_loss": False,
        },
        "excluded_cards": [
            {
                "source_offer_id": EXCLUDED_ID,
                "product_name_raw": "granini Die Limo",
                "fragment_href": f"#angebot-{EXCLUDED_ID}",
                "dialog_id": f"dialog-angebot-{EXCLUDED_ID}",
                "route": "excluded",
                "exclusion_reason": "source_card_missing_offer_price_pfand_only",
            }
        ],
    }


def test_accounted_bridge_adds_explicit_excluded_candidate() -> None:
    payload = accounted.augment_live_candidate_provenance(_base(), _accounting())
    validated = gate_c.validate_candidate_provenance(payload)

    assert validated["candidate_count"] == 2
    assert validated["route_counts"] == {
        "automatic_candidate": 1,
        "excluded": 1,
        "review_required": 0,
    }
    assert payload["live_evidence"]["source_card_count"] == 2
    assert payload["live_evidence"]["parsed_offer_count"] == 1
    assert payload["live_evidence"]["excluded_count"] == 1
    assert payload["live_evidence"]["unexplained_source_card_loss"] is False
    excluded = [row for row in payload["candidates"] if row["route"] == "excluded"]
    assert excluded == [
        {
            "candidate_id": EXCLUDED_ID,
            "campaign_id": _base()["manifest"]["campaign_id"],
            "source_sha256": RAW_SHA,
            "manifest_sha256": MANIFEST_SHA,
            "parser_identity": "edeka-v1",
            "page_number": 1,
            "card_id": f"dialog-angebot-{EXCLUDED_ID}",
            "route": "excluded",
            "ambiguous": False,
            "provenance_complete": True,
            "exclusion_reason": "source_card_missing_offer_price_pfand_only",
        }
    ]


def test_accounted_bridge_rejects_candidate_id_overlap() -> None:
    accounting = _accounting()
    accounting["excluded_cards"][0]["source_offer_id"] = PARSED_ID
    accounting["excluded_cards"][0]["dialog_id"] = f"dialog-angebot-{PARSED_ID}"

    with pytest.raises(ValueError, match="candidate IDs overlap"):
        accounted.augment_live_candidate_provenance(_base(), accounting)
