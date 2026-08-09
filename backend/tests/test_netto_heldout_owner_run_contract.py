from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import subprocess
import sys

import pymupdf
import pytest


ROOT = Path(__file__).resolve().parents[2]
CAPTURE_TOOL = ROOT / "tools/netto_heldout_page_capture.py"
OWNER_RUN = ROOT / "tools/run-hermes-deals-netto-heldout-capture-v01.sh"
SPEC = importlib.util.spec_from_file_location("netto_heldout_page_capture_owner_tested", CAPTURE_TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


SOURCE_PARSER = "netto-heldout-source-fixture-v1"


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selector_payload(tmp_path: Path) -> dict[str, object]:
    pdf = tmp_path / "source.pdf"
    html = tmp_path / "source.html"
    manifest = tmp_path / "source-manifest.json"
    document = pymupdf.open()
    try:
        page = document.new_page(width=300, height=400)
        page.insert_text((25, 50), "Heldout Produkt", fontsize=14)
        page.insert_text((25, 100), "1,99", fontsize=22)
        document.save(pdf)
    finally:
        document.close()
    html.write_text("<html>5659</html>\n", encoding="utf-8")
    manifest.write_text(
        json.dumps(
            {
                "strategy": "netto-heldout-source-fixture-v1",
                "store_external_id": "5659",
                "scope": "family_primary_netto",
                "prospect_slug": "heldout_hz33",
                "valid_from": "2026-08-10",
                "valid_until": "2026-08-15",
                "store_path": "source.html",
                "store_sha256": sha(html),
                "prospect_pdf_path": "source.pdf",
                "prospect_pdf_sha256": sha(pdf),
                "parser_identity": SOURCE_PARSER,
            },
            sort_keys=True,
        )
        + "\n",
        encoding="utf-8",
    )
    binding = {
        "manifest_path": str(manifest),
        "manifest_sha256": sha(manifest),
        "html_path": str(html),
        "html_sha256": sha(html),
        "evidence_status": "pdf_bound",
        "pdf_path": str(pdf),
        "pdf_sha256": sha(pdf),
        "parser_identity": SOURCE_PARSER,
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "valid_from": "2026-08-10",
        "valid_until": "2026-08-15",
        "no_pdf_reason": None,
    }
    identity = MODULE.EvidenceBinding.from_mapping(binding).identity_sha256()
    return {
        "schema_version": 1,
        "strategy": MODULE.SOURCE_SELECTOR_STRATEGY,
        "as_of": "2026-08-09",
        "campaign_key": "heldout_hz33",
        "campaign_window": {"start": "2026-08-10", "end": "2026-08-15"},
        "evidence_identity_sha256": identity,
        "binding": binding,
        "selection": {"fallback_to_older_campaign_allowed": False},
        "review_only": True,
        "promotion_ready": False,
    }


def test_capture_loader_accepts_exact_selector_payload(tmp_path: Path) -> None:
    payload = selector_payload(tmp_path)
    path = tmp_path / "selected-binding.json"
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    loaded = MODULE._load_binding(path)

    assert loaded == payload["binding"]
    output = tmp_path / "capture"
    summary = MODULE.capture_heldout(loaded, output)
    assert summary["campaign_key"] == "heldout_hz33"
    assert summary["truth_available_at_freeze"] is False
    assert summary["promotion_ready"] is False


def test_capture_loader_rejects_selector_identity_drift(tmp_path: Path) -> None:
    payload = selector_payload(tmp_path)
    payload["evidence_identity_sha256"] = "0" * 64
    path = tmp_path / "selected-binding.json"
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(MODULE.HeldoutCaptureError, match="evidence identity does not match"):
        MODULE._load_binding(path)


def test_capture_loader_rejects_selector_campaign_drift(tmp_path: Path) -> None:
    payload = selector_payload(tmp_path)
    payload["campaign_key"] = "invented-campaign"
    path = tmp_path / "selected-binding.json"
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")

    with pytest.raises(MODULE.HeldoutCaptureError, match="campaign identity does not match"):
        MODULE._load_binding(path)


def test_owner_wrapper_is_non_root_exact_main_and_read_only() -> None:
    subprocess.run(["bash", "-n", str(OWNER_RUN)], check=True)
    text = OWNER_RUN.read_text(encoding="utf-8")

    assert "do not run held-out capture as root" in text
    assert "held-out capture must run as andris" in text
    assert "rev-parse HEAD" in text
    assert "refs/remotes/origin/main" in text
    assert "primary repository must be clean" in text
    assert "netto_heldout_source_selector.py" in text
    assert "netto_heldout_page_capture.py" in text
    assert "/home/andris/hermes-deals/data/raw" in text
    assert "/home/andris/hermes-deals-audits" in text
    assert "PyMuPDF 1.28.0 required" in text
    assert "find . -type f ! -path './SHA256SUMS' -print0" in text
    assert "REPOSITORY_WRITE=false" in text
    assert "DATABASE_WRITE=false" in text
    assert "REVIEW_WRITE=false" in text
    assert "PRODUCTION_DEPLOY=false" in text
    assert "SCHEDULER_CHANGE=false" in text
    assert "PROMOTION_READY=false" in text
    assert "sudo" not in text
    assert "docker" not in text.casefold()
    assert "systemctl" not in text
    assert "git -C \"$REPO\" checkout" not in text
    assert "git -C \"$REPO\" reset" not in text
    assert "git -C \"$REPO\" clean" not in text
