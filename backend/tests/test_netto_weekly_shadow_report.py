from __future__ import annotations

from datetime import date
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace
import sys

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import netto_weekly_shadow_report as shadow
from netto_shadow_promotion import EvidenceBinding


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def evidence(tmp_path: Path):
    root = tmp_path / "raw"
    root.mkdir()
    store, prospect, pdf = (root / name for name in ("store.html", "prospect.html", "prospect.pdf"))
    store.write_text("fixture HTML", encoding="utf-8")
    prospect.write_text("fixture viewer", encoding="utf-8")
    pdf.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
    manifest = root / "manifest.json"
    payload = {
        "schema_version": 3, "strategy": "netto_store_page_plus_current_prospect_pdf_v3",
        "selected_store_cookie_present": True, "store_external_id": "5659",
        "scope": "family_primary_netto", "prospect_slug": "hz-test",
        "valid_from": "2026-10-19", "valid_until": "2026-10-24",
        "collected_at": "2026-10-19T00:12:00+00:00",
        "store_url": "https://www.netto-online.de/filialen/test/5659",
        "store_name": "Netto 5659",
        "store_path": str(store), "store_sha256": sha(store),
        "prospect_path": str(prospect), "prospect_sha256": sha(prospect),
        "prospect_pdf_path": str(pdf), "prospect_pdf_sha256": sha(pdf),
    }
    manifest.write_text(json.dumps(payload), encoding="utf-8")
    binding = {
        "manifest_path": str(manifest), "manifest_sha256": sha(manifest),
        "html_path": str(store), "html_sha256": sha(store),
        "pdf_path": str(pdf), "pdf_sha256": sha(pdf),
        "evidence_status": "pdf_bound", "parser_identity": payload["strategy"],
        "store_external_id": "5659", "scope": "family_primary_netto",
        "valid_from": "2026-10-19", "valid_until": "2026-10-24",
    }
    identity = EvidenceBinding.from_mapping(binding).identity_sha256()
    selector = {
        "strategy": "netto_weekly_verified_source_selector_v1",
        "campaign_key": "hz-test", "campaign_window": {"start": "2026-10-19", "end": "2026-10-24"},
        "evidence_identity_sha256": identity, "binding": binding,
        "selection": {"fallback_to_older_campaign_allowed": False},
        "review_only": True, "promotion_ready": False,
    }
    return root, selector, payload


def test_offline_shadow_receipt_is_nonpromoting_and_hash_bound(tmp_path, monkeypatch):
    root, selector, _ = evidence(tmp_path)
    monkeypatch.setattr(shadow, "parse_netto_store_prospect_snapshot",
                        lambda path, context: [SimpleNamespace(source_store_external_id="5659")])
    monkeypatch.setattr(shadow, "extract_pdf_daily_special_candidates",
                        lambda path, snapshot_id: [(
                            SimpleNamespace(page_number=1, special_valid_on=date(2026, 10, 20)),
                            [SimpleNamespace(special_source_page=1, valid_from=date(2026, 10, 20), valid_until=date(2026, 10, 20))],
                            "page-sha",
                        )])
    receipt = shadow.build_shadow_report(selector, root)
    assert receipt["html_extracted_offer_count"] == 1
    assert receipt["pdf_daily_special_candidate_count"] == 1
    assert receipt["source_card_accounting"] == "unknown"
    assert receipt["shadow_extraction_completed"] is True
    assert receipt["shadow_acceptance_passed"] is False
    assert receipt["issue_28_two_real_transitions_ready"] is False
    assert receipt["promotion_ready"] is False


def test_shadow_fails_closed_on_manifest_or_pdf_drift(tmp_path, monkeypatch):
    root, selector, payload = evidence(tmp_path)
    monkeypatch.setattr(shadow, "parse_netto_store_prospect_snapshot",
                        lambda path, context: [SimpleNamespace(source_store_external_id="5659")])
    monkeypatch.setattr(shadow, "extract_pdf_daily_special_candidates",
                        lambda path, snapshot_id: [])
    pdf = root / "prospect.pdf"
    pdf.write_bytes(pdf.read_bytes() + b"tampered")
    with pytest.raises(ValueError, match="SHA"):
        shadow.build_shadow_report(selector, root)
    pdf.write_bytes(b"%PDF-1.4\nfixture\n%%EOF\n")
    payload["prospect_slug"] = "other-campaign"
    (root / "manifest.json").write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError, match="SHA"):
        shadow.build_shadow_report(selector, root)


def test_shadow_does_not_misclassify_failed_or_cross_store_parse(tmp_path, monkeypatch):
    root, selector, _ = evidence(tmp_path)
    monkeypatch.setattr(shadow, "parse_netto_store_prospect_snapshot",
                        lambda path, context: [SimpleNamespace(source_store_external_id="other")])
    with pytest.raises(ValueError, match="crossed store"):
        shadow.build_shadow_report(selector, root)
    monkeypatch.setattr(shadow, "parse_netto_store_prospect_snapshot",
                        lambda path, context: (_ for _ in ()).throw(ValueError("parser failed")))
    with pytest.raises(ValueError, match="parser failed"):
        shadow.build_shadow_report(selector, root)


def test_shadow_rejects_daily_special_outside_campaign(tmp_path, monkeypatch):
    root, selector, _ = evidence(tmp_path)
    monkeypatch.setattr(shadow, "parse_netto_store_prospect_snapshot",
                        lambda path, context: [SimpleNamespace(source_store_external_id="5659")])
    monkeypatch.setattr(shadow, "extract_pdf_daily_special_candidates",
                        lambda path, snapshot_id: [(
                            SimpleNamespace(page_number=3, special_valid_on=date(2026, 10, 25)),
                            [], "page-sha",
                        )])
    with pytest.raises(ValueError, match="outside verified campaign"):
        shadow.build_shadow_report(selector, root)
