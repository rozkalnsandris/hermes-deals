from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
PLAN = ROOT / "config/edeka-production-canary-v01.json"


def _plan() -> dict[str, object]:
    return json.loads(PLAN.read_text(encoding="utf-8"))


def test_canary_is_preparation_only_and_exact_patzer_source() -> None:
    plan = _plan()
    assert plan["state"] == "preparation_only"
    assert plan["production_apply_authorized"] is False
    assert plan["market"] == {
        "source_chain": "edeka",
        "scope": "family_primary_edeka",
        "public_market_id": "071897",
        "internal_market_id": "587881",
        "store_name": "EDEKA Patzer",
        "source_url": "https://www.edeka.de/maerkte/071897/angebote/",
    }

    source = plan["authoritative_source"]
    assert source["workflow_run_id"] == 31157650948
    assert source["artifact_id"] == 8985771511
    assert source["campaign_valid_from"] == "2026-08-03"
    assert source["campaign_valid_until"] == "2026-08-08"
    assert source["raw_html_sha256"] == (
        "2e3a88cfb67f6dd38075ffa16ba04a7520efd5fca1230874da30cc70af0f6f20"
    )
    assert source["manifest_sha256"] == (
        "df3be62abe356c8071766d00ab988f8aef69fcdf3724f6c64269a8c427581d9a"
    )
    assert source["parser_version"] == "edeka-v1"
    assert source["normalizer_version"] == "normalizer-v1.2"
    assert source["full_offer_count"] == 203


def test_canary_names_exact_three_resolved_rows_covering_package_paths() -> None:
    rows = _plan()["canary_rows"]
    assert len(rows) == 3
    assert len({row["source_offer_id"] for row in rows}) == 3
    assert {row["source_offer_id"] for row in rows} == {
        "059d39c8-69b8-4c99-9008-61341138ca0e",
        "2e53629a-c206-44b0-9867-4922f2f1facd",
        "0b6bcd44-9b9f-459c-bdce-f3e4fcf94edd",
    }
    assert {row["package_parse_method"] for row in rows} == {
        "edeka_image_metric_single",
        "edeka_description_metric_single",
        "edeka_image_metric_multipack",
    }
    assert all(row["review_required"] is False for row in rows)
    assert all(row["valid_from"] == "2026-08-03" for row in rows)
    assert all(row["valid_until"] == "2026-08-08" for row in rows)


def test_canary_db_delta_replay_and_rollback_are_bounded() -> None:
    plan = _plan()
    assert plan["preflight"]["required_alembic_head"] == (
        "0007_comparison_family_pricing"
    )
    assert plan["expected_first_apply_delta"] == {
        "source_snapshots": 1,
        "offer_candidates": 3,
        "offer_normalizations": 3,
        "product_match_candidates": 0,
        "offer_product_links": 0,
        "canonical_products": 0,
        "offer_review_items": 0,
        "offer_review_revisions": 0,
    }
    assert set(plan["expected_exact_replay_delta"].values()) == {0}
    rollback = plan["rollback"]
    assert rollback["scope"] == "captured_canary_ids_only"
    assert rollback["delete_order"] == [
        "offer_normalizations",
        "offer_candidates",
        "source_snapshots",
    ]
    assert rollback["broad_delete_by_chain_forbidden"] is True

    forbidden = set(plan["forbidden_actions"])
    assert {
        "canonical_product_creation",
        "product_matching",
        "offer_product_linking",
        "review_queue_write",
        "approval",
        "publication",
        "scheduler_activation",
        "broad_edeka_import",
    } <= forbidden
