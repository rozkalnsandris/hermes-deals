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

def test_real_netto_html_and_pdf_parsers_execute_without_mocking(tmp_path):
    """Exercise the actual store HTML parser and PDF reader with local fixtures."""
    import fitz

    root, selector, manifest = evidence(tmp_path)
    fixture = Path(__file__).parent / "fixtures" / "netto_offers.html"
    store = root / "store.html"
    store.write_bytes(fixture.read_bytes())
    prospect = root / "prospect.html"
    prospect.write_text(
        '<meta name="description" content="Montag, 19.10.2026 - Samstag, 24.10.2026">',
        encoding="utf-8",
    )
    pdf = root / "prospect.pdf"
    document = fitz.open()
    try:
        page = document.new_page()
        page.insert_text((72, 72), "Netto Wochenprospekt - keine Tagesaktion")
        pdf.write_bytes(document.tobytes())
    finally:
        document.close()

    manifest.update(
        store_sha256=sha(store),
        prospect_sha256=sha(prospect),
        prospect_pdf_sha256=sha(pdf),
        prospect_url="https://www.netto-online.de/prospekte/hz-test",
        validity_text="Montag, 19.10.2026 - Samstag, 24.10.2026",
        validity_source_type="prospect_html_meta",
    )
    manifest_file = root / "manifest.json"
    manifest_file.write_text(json.dumps(manifest), encoding="utf-8")
    selector["binding"].update(
        manifest_sha256=sha(manifest_file),
        html_sha256=sha(store),
        pdf_sha256=sha(pdf),
    )
    selector["evidence_identity_sha256"] = EvidenceBinding.from_mapping(selector["binding"]).identity_sha256()
    report = shadow.build_shadow_report(selector, root)
    assert report["html_extracted_offer_count"] == 5
    assert report["pdf_daily_special_page_count"] == 0
    assert report["source_card_accounting"] == "unknown"
    assert report["shadow_acceptance_passed"] is False
    assert report["issue_28_two_real_transitions_ready"] is False


def test_outside_root_evidence_rejected_before_generic_verifier(tmp_path, monkeypatch):
    root, selector, _ = evidence(tmp_path)
    outside = tmp_path / "outside.pdf"
    outside.write_bytes((root / "prospect.pdf").read_bytes())
    selector["binding"].update(pdf_path=str(outside), pdf_sha256=sha(outside))
    selector["evidence_identity_sha256"] = EvidenceBinding.from_mapping(selector["binding"]).identity_sha256()
    def forbidden(*args, **kwargs):
        raise AssertionError("generic verifier must not read out-of-root paths")
    monkeypatch.setattr(shadow, "verify_binding_files", forbidden)
    with pytest.raises(ValueError, match="escaped raw evidence root"):
        shadow.build_shadow_report(selector, root)


def test_in_root_symlink_and_verified_no_pdf_fail_closed(tmp_path, monkeypatch):
    root, selector, _ = evidence(tmp_path)
    symlink = root / "indirect.pdf"
    symlink.symlink_to(root / "prospect.pdf")
    selector["binding"].update(pdf_path=str(symlink))
    selector["evidence_identity_sha256"] = EvidenceBinding.from_mapping(selector["binding"]).identity_sha256()
    monkeypatch.setattr(shadow, "verify_binding_files",
                        lambda binding: (_ for _ in ()).throw(AssertionError("unexpected read")))
    with pytest.raises(ValueError, match="non-symlink"):
        shadow.build_shadow_report(selector, root)
    selector["binding"].update(
        evidence_status="verified_no_pdf", pdf_path=None, pdf_sha256=None,
        no_pdf_reason="source explicitly has no PDF",
    )
    selector["evidence_identity_sha256"] = EvidenceBinding.from_mapping(selector["binding"]).identity_sha256()
    with pytest.raises(ValueError, match="requires verified bound PDF evidence"):
        shadow.build_shadow_report(selector, root)

