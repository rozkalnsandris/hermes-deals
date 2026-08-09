from __future__ import annotations

from datetime import date
import hashlib
import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools/netto_heldout_source_selector.py"
SPEC = importlib.util.spec_from_file_location("netto_heldout_source_selector_tested", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

select_verified_source = MODULE.select_verified_source
HeldoutSourceSelectionError = MODULE.HeldoutSourceSelectionError


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def source_manifest(
    raw_root: Path,
    name: str,
    campaign: str,
    start: str,
    end: str,
    *,
    pdf_bytes: bytes | None = None,
    html_text: str | None = None,
    include_html_binding: bool = True,
    include_pdf_binding: bool = True,
) -> tuple[Path, Path, Path]:
    root = raw_root / name
    root.mkdir(parents=True)
    html = root / "source.html"
    pdf = root / "source.pdf"
    manifest = root / "source-manifest.json"
    html.write_text(html_text or f"<html>{campaign}</html>\n", encoding="utf-8")
    pdf.write_bytes(pdf_bytes or f"%PDF-1.7\n{campaign}\n".encode())
    payload = {
        "strategy": "netto-heldout-source-fixture-v1",
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "prospect_slug": campaign,
        "valid_from": start,
        "valid_until": end,
        "parser_identity": "netto-source-fixture-v1",
    }
    if include_html_binding:
        payload.update({"store_path": "source.html", "store_sha256": sha(html)})
    if include_pdf_binding:
        payload.update({"prospect_pdf_path": "source.pdf", "prospect_pdf_sha256": sha(pdf)})
    manifest.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    return manifest, html, pdf


def test_selects_latest_nonexpired_verified_heldout_source(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    source_manifest(raw, "old-evaluation", "hz32_hasb", "2026-08-03", "2026-08-08")
    source_manifest(raw, "older-independent", "heldout_hz32b", "2026-08-04", "2026-08-09")
    latest_manifest, _, latest_pdf = source_manifest(
        raw,
        "new-week",
        "heldout_hz33",
        "2026-08-10",
        "2026-08-15",
    )

    result = select_verified_source(raw, date(2026, 8, 9))

    assert result["campaign_key"] == "heldout_hz33"
    assert result["campaign_window"] == {"start": "2026-08-10", "end": "2026-08-15"}
    assert result["binding"]["manifest_path"] == str(latest_manifest)
    assert result["binding"]["pdf_sha256"] == sha(latest_pdf)
    assert result["selection"]["fallback_to_older_campaign_allowed"] is False
    assert result["review_only"] is True
    assert result["promotion_ready"] is False


def test_latest_corrupt_source_fails_closed_instead_of_falling_back(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    source_manifest(raw, "older-good", "heldout_hz32b", "2026-08-04", "2026-08-09")
    _, _, latest_pdf = source_manifest(raw, "latest-bad", "heldout_hz33", "2026-08-10", "2026-08-15")
    latest_pdf.write_bytes(b"tampered after manifest freeze")

    with pytest.raises(HeldoutSourceSelectionError, match="contains unverified source manifests"):
        select_verified_source(raw, date(2026, 8, 9))


def test_latest_missing_pdf_fails_closed_instead_of_falling_back(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    source_manifest(raw, "older-good", "heldout_hz32b", "2026-08-04", "2026-08-09")
    source_manifest(
        raw,
        "latest-not-yet-pdf-bound",
        "heldout_hz33",
        "2026-08-10",
        "2026-08-15",
        include_pdf_binding=False,
    )

    with pytest.raises(HeldoutSourceSelectionError, match="contains unverified source manifests") as error:
        select_verified_source(raw, date(2026, 8, 9))
    assert "missing a PDF binding" in str(error.value)


def test_latest_missing_html_fails_closed_instead_of_falling_back(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    source_manifest(raw, "older-good", "heldout_hz32b", "2026-08-04", "2026-08-09")
    source_manifest(
        raw,
        "latest-incomplete",
        "heldout_hz33",
        "2026-08-10",
        "2026-08-15",
        include_html_binding=False,
    )

    with pytest.raises(HeldoutSourceSelectionError, match="contains unverified source manifests") as error:
        select_verified_source(raw, date(2026, 8, 9))
    assert "missing an HTML binding" in str(error.value)


def test_latest_window_with_two_campaigns_is_ambiguous(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    source_manifest(raw, "campaign-a", "heldout_hz33_a", "2026-08-10", "2026-08-15")
    source_manifest(raw, "campaign-b", "heldout_hz33_b", "2026-08-10", "2026-08-15")

    with pytest.raises(HeldoutSourceSelectionError, match="ambiguous across campaigns"):
        select_verified_source(raw, date(2026, 8, 9))


def test_same_campaign_with_conflicting_verified_source_identities_fails_closed(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    source_manifest(
        raw,
        "campaign-a",
        "heldout_hz33",
        "2026-08-10",
        "2026-08-15",
        pdf_bytes=b"%PDF-1.7\nvariant-a\n",
    )
    source_manifest(
        raw,
        "campaign-b",
        "heldout_hz33",
        "2026-08-10",
        "2026-08-15",
        pdf_bytes=b"%PDF-1.7\nvariant-b\n",
    )

    with pytest.raises(HeldoutSourceSelectionError, match="conflicting verified source identities"):
        select_verified_source(raw, date(2026, 8, 9))


def test_old_evaluation_or_expired_sources_cannot_satisfy_selector(tmp_path: Path) -> None:
    raw = tmp_path / "raw"
    raw.mkdir()
    source_manifest(raw, "old-eval", "hz31_hasb_4", "2026-07-27", "2026-08-01")
    source_manifest(raw, "expired", "heldout_old", "2026-08-02", "2026-08-08")

    with pytest.raises(HeldoutSourceSelectionError, match="no non-expired held-out"):
        select_verified_source(raw, date(2026, 8, 9))


def test_raw_root_must_be_real_directory(tmp_path: Path) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(HeldoutSourceSelectionError, match="existing regular directory"):
        select_verified_source(missing, date(2026, 8, 9))
