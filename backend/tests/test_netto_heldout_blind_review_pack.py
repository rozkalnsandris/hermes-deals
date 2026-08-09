from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "netto_heldout_blind_review_pack.py"
SPEC = importlib.util.spec_from_file_location("netto_heldout_blind_review_pack", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def make_pdf(path: Path) -> str:
    document = pymupdf.open()
    for page_number in (1, 2):
        page = document.new_page(width=300, height=400)
        page.insert_text((36, 72), f"SOURCE CARD PAGE {page_number} 1.99 €", fontsize=12)
    document.save(path)
    document.close()
    return sha256(path.read_bytes()).hexdigest()


def fixture_capture(tmp_path: Path, *, nonblank: bool = False) -> dict[str, object]:
    root = tmp_path / "capture-root"
    source_dir = root / "source" / "netto"
    source_dir.mkdir(parents=True)
    pdf = source_dir / "source.pdf"
    pdf_sha = make_pdf(pdf)

    commit = "c" * 40
    campaign = "hz33_fixture"
    source_sha = "a" * 64
    valid_from = "2026-08-10"
    valid_until = "2026-08-15"

    freeze = {
        "schema_version": 1,
        "protocol": "netto-heldout-ownership-v1",
        "store_external_id": "5659",
        "campaign_key": campaign,
        "campaign_window": {"start": valid_from, "end": valid_until},
        "source_sha256": source_sha,
        "parser_identity": "frozen-parser",
        "evidence_sha256": "b" * 64,
        "predictions_sha256": "d" * 64,
        "truth_sha256": None,
        "adjudication_sha256": None,
        "review_only": True,
        "promotion_ready": False,
    }
    freeze_path = root / "capture" / "freeze-manifest.json"
    write_json(freeze_path, freeze)
    freeze_sha = sha256(freeze_path.read_bytes()).hexdigest()

    write_json(
        root / "github-capture-result.json",
        {
            "result": "PASS",
            "registered_commit": commit,
            "campaign_key": campaign,
            "truth_available_at_freeze": False,
            "review_only": True,
            "promotion_ready": False,
        },
    )
    write_json(
        root / "live-source.json",
        {
            "store_external_id": "5659",
            "scope": "family_primary_netto",
            "campaign_key": campaign,
            "campaign_window": {"start": valid_from, "end": valid_until},
        },
    )
    write_json(
        root / "selected-binding.json",
        {"evidence_identity_sha256": source_sha},
    )
    write_json(
        root / "capture" / "freeze-receipt.json",
        {
            "source_sha256": source_sha,
            "freeze_manifest_sha256": freeze_sha,
            "truth_available_at_freeze": False,
            "review_only": True,
            "promotion_ready": False,
        },
    )
    write_json(
        root / "capture" / "blind-review-template.json",
        {
            "campaign_key": campaign,
            "source_sha256": source_sha,
            "freeze_manifest_sha256": freeze_sha,
            "page_count": 2,
            "parser_predictions_included": False,
            "expected_truth_included": False,
            "pages": [
                {"page_number": 1, "source_cards": [{"leak": True}] if nonblank else []},
                {"page_number": 2, "source_cards": []},
            ],
        },
    )
    # This file is intentionally present. The generator must not read, copy or expose it.
    write_json(root / "capture" / "predictions.json", {"FORBIDDEN_SENTINEL": "do-not-read"})

    return {
        "root": root,
        "commit": commit,
        "campaign": campaign,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "source_sha": source_sha,
        "pdf_sha": pdf_sha,
        "freeze_sha": freeze_sha,
    }


def generate(tmp_path: Path, fixture: dict[str, object]):
    output = tmp_path / "review-pack"
    payload = MODULE.generate_pack(
        fixture["root"],
        output,
        expected_commit=str(fixture["commit"]),
        expected_campaign=str(fixture["campaign"]),
        expected_valid_from=str(fixture["valid_from"]),
        expected_valid_until=str(fixture["valid_until"]),
        expected_source_sha256=str(fixture["source_sha"]),
        expected_pdf_sha256=str(fixture["pdf_sha"]),
        expected_freeze_manifest_sha256=str(fixture["freeze_sha"]),
        expected_page_count=2,
    )
    return output, payload


def test_two_page_pack_is_source_only_and_blank(tmp_path: Path) -> None:
    fixture = fixture_capture(tmp_path)
    output, payload = generate(tmp_path, fixture)

    assert payload["page_count"] == 2
    assert payload["blind_review_contract"]["parser_predictions_included"] is False
    assert payload["blind_review_contract"]["expected_truth_included"] is False
    assert payload["blind_review_contract"]["presegmented_review_units"] is False
    assert (output / "pages/page-001.png").is_file()
    assert (output / "pages/page-002.png").is_file()
    assert (output / "pages/page-001.json").is_file()
    assert (output / "pages/page-002.json").is_file()

    ledger = json.loads(
        (output / "independent-source-card-review-ledger.json").read_text(encoding="utf-8")
    )
    assert ledger["page_count"] == 2
    assert ledger["parser_predictions_included"] is False
    assert ledger["expected_truth_included"] is False
    assert [row["source_cards"] for row in ledger["pages"]] == [[], []]

    output_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in output.rglob("*")
        if path.is_file() and path.suffix in {".json", ""}
    )
    assert "FORBIDDEN_SENTINEL" not in output_text
    assert "predictions_sha256" not in output_text
    assert not (output / "predictions.json").exists()


def test_nonblank_upstream_review_template_fails_closed(tmp_path: Path) -> None:
    fixture = fixture_capture(tmp_path, nonblank=True)
    with pytest.raises(MODULE.HeldoutBlindReviewPackError, match="not blank"):
        generate(tmp_path, fixture)


def test_wrong_source_identity_fails_closed(tmp_path: Path) -> None:
    fixture = fixture_capture(tmp_path)
    fixture["source_sha"] = "e" * 64
    with pytest.raises(MODULE.HeldoutBlindReviewPackError, match="source identity mismatch"):
        generate(tmp_path, fixture)


def test_generator_source_never_references_prediction_payload() -> None:
    text = TOOL.read_text(encoding="utf-8")
    assert "predictions.json" not in text
    assert "predictions_sha256" not in text
    assert "FORBIDDEN_SENTINEL" not in text
    assert "capture/source-evidence.json" not in text
    assert "parser_identity" not in text
