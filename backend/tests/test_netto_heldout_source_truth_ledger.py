from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "netto_heldout_source_truth_ledger.py"
SPEC = importlib.util.spec_from_file_location("netto_heldout_source_truth_ledger", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def write_json(path: Path, payload: object) -> str:
    path.parent.mkdir(parents=True, exist_ok=True)
    data = (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode()
    path.write_bytes(data)
    return sha256(data).hexdigest()


def fixture_pack(tmp_path: Path, *, nonblank: bool = False):
    root = tmp_path / "review-pack"
    manifest = {
        "campaign_key": "hz33_hasb",
        "campaign_window": {"start": "2026-08-10", "end": "2026-08-15"},
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "source_sha256": "a" * 64,
        "source_pdf_sha256": "b" * 64,
        "freeze_manifest_sha256": "c" * 64,
        "page_count": 2,
        "blind_review_contract": {
            "presegmented_review_units": False,
            "parser_predictions_included": False,
            "expected_truth_included": False,
        },
    }
    ledger = {
        "page_count": 2,
        "pages": [
            {
                "page_number": 1,
                "page_width_points": 567.0,
                "page_height_points": 737.5,
                "source_cards": [{"leak": True}] if nonblank else [],
            },
            {
                "page_number": 2,
                "page_width_points": 567.0,
                "page_height_points": 737.5,
                "source_cards": [],
            },
        ],
    }
    manifest_sha = write_json(root / "manifest.json", manifest)
    ledger_sha = write_json(root / "independent-source-card-review-ledger.json", ledger)
    return root, manifest_sha, ledger_sha


def test_corrected_ledger_records_source_truth_not_prediction_outcomes(tmp_path: Path) -> None:
    root, manifest_sha, old_ledger_sha = fixture_pack(tmp_path)
    output = tmp_path / "out"
    result = MODULE.build_source_truth_ledger(
        root,
        output,
        expected_pack_manifest_sha256=manifest_sha,
        expected_blank_ledger_sha256=old_ledger_sha,
        expected_page_count=2,
    )
    ledger = json.loads(
        (output / "independent-source-truth-ledger.json").read_text(encoding="utf-8")
    )
    schema = ledger["source_region_schema"]
    assert "ownership_class" not in schema
    assert schema["scope_classification"] == ["in_scope", "excluded_non_target"]
    assert schema["boundary_state"] == ["clear_single_card", "partial_single_card"]
    assert [row["source_regions"] for row in ledger["pages"]] == [[], []]
    derivation = ledger["prediction_ownership_derivation"]
    assert derivation["performed_during_source_review"] is False
    assert derivation["allowed_only_after_completed_truth_sha_is_frozen"] is True
    assert derivation["outcome_classes"] == [
        "single_source",
        "mixed_source",
        "excluded_control",
    ]
    assert ledger["parser_predictions_included"] is False
    assert ledger["expected_truth_included"] is False
    assert ledger["adjudication_started"] is False
    assert result["promotion_ready"] is False


def test_nonblank_superseded_ledger_fails_closed(tmp_path: Path) -> None:
    root, manifest_sha, old_ledger_sha = fixture_pack(tmp_path, nonblank=True)
    with pytest.raises(MODULE.SourceTruthLedgerError, match="no longer blank"):
        MODULE.build_source_truth_ledger(
            root,
            tmp_path / "out",
            expected_pack_manifest_sha256=manifest_sha,
            expected_blank_ledger_sha256=old_ledger_sha,
            expected_page_count=2,
        )


def test_wrong_review_pack_manifest_hash_fails_closed(tmp_path: Path) -> None:
    root, _, old_ledger_sha = fixture_pack(tmp_path)
    with pytest.raises(MODULE.SourceTruthLedgerError, match="manifest SHA mismatch"):
        MODULE.build_source_truth_ledger(
            root,
            tmp_path / "out",
            expected_pack_manifest_sha256="e" * 64,
            expected_blank_ledger_sha256=old_ledger_sha,
            expected_page_count=2,
        )


def test_source_truth_tool_never_reads_predictions() -> None:
    text = TOOL.read_text(encoding="utf-8")
    assert "predictions.json" not in text
    assert "predictions_sha256" not in text
    assert "parser_identity" not in text
    assert "/home/andris" not in text
    assert "sudo " not in text
    assert "psql " not in text
