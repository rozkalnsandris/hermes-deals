from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
TOOL = TOOLS / "netto_hz33_disagreement_taxonomy.py"
SPEC = importlib.util.spec_from_file_location("netto_hz33_disagreement_taxonomy", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)

TRUTH = ROOT / "evidence/netto/heldout/hz33/completed-independent-source-truth-ledger.json.gz.b64"
TRUTH_RECEIPT = ROOT / "evidence/netto/heldout/hz33/completed-source-truth-receipt.json"
ADJUDICATION = ROOT / "audit/netto/hz33/heldout-adjudication.json"
ADJUDICATION_RECEIPT = ROOT / "audit/netto/hz33/heldout-adjudication-receipt.json"


def _report() -> dict:
    return MODULE.diagnose(TRUTH, TRUTH_RECEIPT, ADJUDICATION, ADJUDICATION_RECEIPT)


def test_primary_taxonomy_separates_unsafe_review_and_evidence_gap_states() -> None:
    cases = {
        ("mixed_source", "single_center_group", True): "unsafe_auto_single",
        ("excluded_control", "single_center_group", True): "unsafe_auto_single",
        ("excluded_control", "review_required", False): "missed_excluded",
        ("single_source", "excluded_control", False): "over_excluded",
        ("mixed_source", "excluded_control", False): "over_excluded",
        ("single_source", "review_required", False): "conservative_review",
        ("mixed_source", "review_required", False): "mixed_held_review",
        ("unresolved_unmapped_atoms", "review_required", False): "unmatched_evidence_gap",
        ("unresolved_cross_scope", "review_required", False): "scope_overlap_evidence_gap",
        ("single_source", "single_center_group", True): "correct_auto_single",
        ("excluded_control", "excluded_control", False): "correct_excluded_control",
    }
    for args, expected in cases.items():
        assert MODULE.primary_class(*args) == expected


def test_repository_evidence_produces_exact_v2_taxonomy() -> None:
    report = _report()
    assert report["row_count"] == 612
    assert report["primary_counts"] == {
        "unsafe_auto_single": 0,
        "conservative_review": 391,
        "missed_excluded": 82,
        "over_excluded": 0,
        "mixed_held_review": 90,
        "unmatched_evidence_gap": 48,
        "scope_overlap_evidence_gap": 1,
        "correct_auto_single": 0,
        "correct_excluded_control": 0,
    }
    assert report["route_counts"] == {"review_required": 612}
    assert report["unsafe_or_evidence_gap_count"] == 131
    assert report["conservative_review_count"] == 391
    assert report["mixed_held_review_count"] == 90
    assert report["cross_cell_group_reuse"]["status"] == "NOT_EVALUABLE"
    assert report["cross_cell_group_reuse"]["observed"] is None
    assert sum(page["row_count"] for page in report["page_summaries"]) == 612
    assert len(report["rows"]) == len({row["row_id"] for row in report["rows"]}) == 612
    assert all(row["row_id"].startswith(f"p{row['page_number']:03d}-") for row in report["rows"])
    assert report["source_review_reopened"] is False
    assert report["threshold_tuning_performed"] is False
    assert report["parser_behavior_changed"] is False
    assert report["review_only"] is True
    assert report["promotion_ready"] is False


def test_repository_report_is_byte_deterministic() -> None:
    first = MODULE.canonical_json(_report())
    second = MODULE.canonical_json(_report())
    assert first == second
    payload = json.loads(first)
    assert payload["strategy"] == "netto_hz33_heldout_disagreement_taxonomy_v2"


def test_truth_receipt_tamper_is_rejected(tmp_path: Path) -> None:
    payload = json.loads(TRUTH_RECEIPT.read_text(encoding="utf-8"))
    payload["in_scope_region_count"] = 308
    tampered = tmp_path / "truth-receipt.json"
    tampered.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(MODULE.Hz33TaxonomyError, match="truth receipt mismatch"):
        MODULE.diagnose(TRUTH, tampered, ADJUDICATION, ADJUDICATION_RECEIPT)


def test_adjudication_byte_tamper_is_rejected(tmp_path: Path) -> None:
    tampered = tmp_path / "adjudication.json"
    tampered.write_bytes(ADJUDICATION.read_bytes() + b"\n")
    with pytest.raises(MODULE.Hz33TaxonomyError, match="adjudication SHA mismatch"):
        MODULE.diagnose(TRUTH, TRUTH_RECEIPT, tampered, ADJUDICATION_RECEIPT)


def test_taxonomy_does_not_use_forbidden_semantics() -> None:
    source = TOOL.read_text(encoding="utf-8").lower()
    for forbidden in (
        "expected_title",
        "selected_title",
        "expected_price",
        "selected_price",
        "product_name",
        "n9",
        "n10",
    ):
        assert forbidden not in source
