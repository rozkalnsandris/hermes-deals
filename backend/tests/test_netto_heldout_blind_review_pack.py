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


def canonical_sha(payload: dict[str, object]) -> str:
    raw = (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()
    return sha256(raw).hexdigest()


def make_pdf(path: Path) -> str:
    document = pymupdf.open()
    for page_number in (1, 2):
        page = document.new_page(width=300, height=400)
        page.insert_text(
            (36, 72),
            f"SOURCE CARD PAGE {page_number} 1.99 EUR",
            fontsize=12,
        )
    document.save(path)
    document.close()
    return sha256(path.read_bytes()).hexdigest()


def fixture_capture(tmp_path: Path, *, nonblank: bool = False) -> dict[str, object]:
    root = tmp_path / "safe-capture"
    source_dir = root / "source" / "netto"
    source_dir.mkdir(parents=True)

    temporary_pdf = source_dir / "source.pdf"
    pdf_sha = make_pdf(temporary_pdf)
    campaign = "hz33_fixture"
    pdf = source_dir / f"5659-{campaign}-{pdf_sha}.pdf"
    temporary_pdf.rename(pdf)

    commit = "c" * 40
    source_sha = "a" * 64
    valid_from = "2026-08-10"
    valid_until = "2026-08-15"
    window = {"start": valid_from, "end": valid_until}

    freeze = {
        "schema_version": 1,
        "protocol": "netto-heldout-ownership-v1",
        "store_external_id": "5659",
        "campaign_key": campaign,
        "campaign_window": window,
        "source_sha256": source_sha,
        "parser_identity": "frozen-parser",
        "evidence_sha256": "b" * 64,
        "predictions_sha256": "d" * 64,
        "truth_sha256": None,
        "adjudication_sha256": None,
        "acceptance": {"fixture": True},
        "ownership_classes": ["single_source", "mixed_source", "excluded_control"],
        "review_only": True,
        "promotion_ready": False,
    }
    freeze_path = root / "capture" / "freeze-manifest.json"
    write_json(freeze_path, freeze)
    freeze_sha = canonical_sha(freeze)
    assert sha256(freeze_path.read_bytes()).hexdigest() != freeze_sha

    write_json(
        root / "github-capture-result.json",
        {
            "schema_version": 1,
            "strategy": "netto_heldout_github_capture_v1",
            "result": "PASS",
            "registered_commit": commit,
            "campaign_key": campaign,
            "truth_available_at_freeze": False,
            "review_only": True,
            "promotion_ready": False,
            "database_write_performed": False,
            "review_write_performed": False,
            "deployment_performed": False,
            "scheduler_change_performed": False,
        },
    )
    write_json(
        root / "live-source.json",
        {
            "schema_version": 1,
            "strategy": "netto_heldout_github_live_source_v1",
            "store_external_id": "5659",
            "scope": "family_primary_netto",
            "campaign_key": campaign,
            "campaign_window": window,
            "review_only": True,
            "promotion_ready": False,
            "database_write_performed": False,
            "review_write_performed": False,
            "deployment_performed": False,
            "scheduler_change_performed": False,
        },
    )
    write_json(
        root / "selected-binding.json",
        {
            "schema_version": 1,
            "strategy": "netto_heldout_verified_source_selector_v1",
            "campaign_key": campaign,
            "campaign_window": window,
            "evidence_identity_sha256": source_sha,
            "review_only": True,
            "promotion_ready": False,
            "binding": {
                "store_external_id": "5659",
                "scope": "family_primary_netto",
                "valid_from": valid_from,
                "valid_until": valid_until,
                "evidence_status": "pdf_bound",
                "pdf_sha256": pdf_sha,
            },
        },
    )
    write_json(
        root / "capture" / "freeze-receipt.json",
        {
            "schema_version": 1,
            "protocol": "netto-heldout-ownership-v1",
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
            "schema_version": 1,
            "campaign_key": campaign,
            "source_sha256": source_sha,
            "freeze_manifest_sha256": freeze_sha,
            "page_count": 2,
            "parser_predictions_included": False,
            "expected_truth_included": False,
            "pages": [
                {
                    "page_number": 1,
                    "source_cards": [{"leak": True}] if nonblank else [],
                },
                {"page_number": 2, "source_cards": []},
            ],
        },
    )

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
        upstream_run_id=12345,
        upstream_artifact_name="fixture-heldout-artifact",
        upstream_artifact_digest="sha256:" + "f" * 64,
    )
    return output, payload


def test_two_page_pack_is_source_only_blank_and_upstream_bound(tmp_path: Path) -> None:
    fixture = fixture_capture(tmp_path)
    output, payload = generate(tmp_path, fixture)

    assert payload["page_count"] == 2
    assert payload["render_dpi"] == 144
    assert payload["coordinate_space"] == "unrotated_page_points"
    assert payload["upstream_capture"] == {
        "workflow_run_id": 12345,
        "artifact_name": "fixture-heldout-artifact",
        "artifact_digest": "sha256:" + "f" * 64,
        "registered_commit": "c" * 40,
    }
    contract = payload["blind_review_contract"]
    assert contract["parser_predictions_included"] is False
    assert contract["expected_truth_included"] is False
    assert contract["presegmented_review_units"] is False

    for page_number in (1, 2):
        assert (output / f"pages/page-{page_number:03d}.png").is_file()
        evidence = json.loads(
            (output / f"pages/page-{page_number:03d}.json").read_text(encoding="utf-8")
        )
        assert evidence["page_number"] == page_number
        assert evidence["coordinate_space"] == "unrotated_page_points"
        assert evidence["text_spans"]

    ledger_path = output / "source-card-review-ledger.blank.json"
    ledger = json.loads(ledger_path.read_text(encoding="utf-8"))
    assert ledger["review_state"] == "blank_independent_source_card_review"
    assert [row["source_cards"] for row in ledger["pages"]] == [[], []]
    assert ledger["reviewer_card_contract"]["scope_classification"] == [
        "in_scope",
        "excluded",
        "ambiguous",
    ]
    assert ledger["parser_predictions_included"] is False
    assert ledger["expected_truth_included"] is False

    output_text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in output.rglob("*")
        if path.is_file() and path.suffix in {".json", ""}
    )
    assert "predictions_sha256" not in output_text
    assert "frozen-parser" not in output_text
    assert not (output / "predictions.json").exists()


def test_canonical_freeze_digest_is_used_not_pretty_file_hash(tmp_path: Path) -> None:
    fixture = fixture_capture(tmp_path)
    output, payload = generate(tmp_path, fixture)
    assert output.is_dir()
    assert payload["freeze_manifest_sha256"] == fixture["freeze_sha"]


def test_nonblank_upstream_review_template_fails_closed(tmp_path: Path) -> None:
    fixture = fixture_capture(tmp_path, nonblank=True)
    with pytest.raises(MODULE.HeldoutBlindReviewPackError, match="not blank"):
        generate(tmp_path, fixture)


def test_extra_safe_capture_member_fails_closed(tmp_path: Path) -> None:
    fixture = fixture_capture(tmp_path)
    write_json(Path(fixture["root"]) / "capture" / "extra.json", {"unexpected": True})
    with pytest.raises(MODULE.HeldoutBlindReviewPackError, match="member set mismatch"):
        generate(tmp_path, fixture)


def test_wrong_source_identity_fails_closed(tmp_path: Path) -> None:
    fixture = fixture_capture(tmp_path)
    fixture["source_sha"] = "e" * 64
    with pytest.raises(MODULE.HeldoutBlindReviewPackError, match="source identity mismatch"):
        generate(tmp_path, fixture)


def test_output_is_create_only(tmp_path: Path) -> None:
    fixture = fixture_capture(tmp_path)
    output, _ = generate(tmp_path, fixture)
    assert output.exists()
    with pytest.raises(MODULE.HeldoutBlindReviewPackError, match="create-only"):
        MODULE.generate_pack(
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
            upstream_run_id=12345,
            upstream_artifact_name="fixture-heldout-artifact",
            upstream_artifact_digest="sha256:" + "f" * 64,
        )


def test_generator_source_never_references_prediction_payload() -> None:
    text = TOOL.read_text(encoding="utf-8")
    for forbidden in (
        "predictions.json",
        "predictions_sha256",
        "capture/source-evidence.json",
        "parser_identity",
    ):
        assert forbidden not in text
