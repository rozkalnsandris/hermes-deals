from __future__ import annotations

from pathlib import Path
import sys

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from netto_hz37_v2_prediction_group_adjudication import build_metrics  # noqa: E402
from netto_heldout_ownership_protocol import ACCEPTANCE  # noqa: E402


def metric_row(outcome: str, *, automatic: bool = False, index: int = 1) -> dict:
    return {
        "prediction_unit_id": f"p001-g{index:03d}",
        "outcome": outcome,
        "candidate_auto_single": automatic,
    }


def test_v2_metrics_use_frozen_candidate_auto_single_and_evaluable_parent_reuse() -> None:
    rows = [metric_row("single_source", automatic=True, index=index) for index in range(1, 51)]
    rows += [metric_row("mixed_source", index=50 + index) for index in range(1, 6)]
    metrics, overall = build_metrics(rows, automatic_candidate_parent_reuse_count=0)
    assert metrics["minimum_reviewed_cells"]["status"] == "PASS"
    assert metrics["minimum_mixed_source_cells"]["status"] == "PASS"
    assert metrics["maximum_mixed_source_auto_single"]["status"] == "PASS"
    assert metrics["maximum_excluded_control_auto_eligible"]["status"] == "PASS"
    assert metrics["minimum_auto_single_precision"]["status"] == "PASS"
    assert metrics["minimum_auto_single_precision"]["observed"] == 1.0
    assert metrics["maximum_cross_cell_group_reuse"]["status"] == "PASS"
    assert metrics["maximum_cross_cell_group_reuse"]["observed"] == 0
    assert overall is True


def test_v2_metrics_fail_literal_auto_mixed_source_and_parent_reuse() -> None:
    rows = [metric_row("single_source", automatic=True, index=1), metric_row("mixed_source", automatic=True, index=2)]
    metrics, overall = build_metrics(rows, automatic_candidate_parent_reuse_count=1)
    assert metrics["maximum_mixed_source_auto_single"]["status"] == "FAIL"
    assert metrics["minimum_auto_single_precision"]["observed"] == 0.5
    assert metrics["maximum_cross_cell_group_reuse"]["status"] == "FAIL"
    assert overall is False


def test_v2_metrics_keep_zero_candidate_precision_not_evaluable() -> None:
    rows = [metric_row("single_source", index=index) for index in range(1, 51)]
    rows += [metric_row("mixed_source", index=50 + index) for index in range(1, 6)]
    metrics, overall = build_metrics(rows, automatic_candidate_parent_reuse_count=0)
    assert metrics["minimum_auto_single_precision"]["status"] == "NOT_EVALUABLE"
    assert overall is False


def test_hz37_adjudicator_binds_exact_frozen_evidence_and_has_no_product_semantics() -> None:
    source = (TOOLS / "netto_hz37_v2_prediction_group_adjudication.py").read_text(encoding="utf-8")
    for required in (
        'EXPECTED_CAMPAIGN = "hz37_hasb"',
        'EXPECTED_ARTIFACT_ID = 10022687292',
        'EXPECTED_RUN_ID = 34132489970',
        'EXPECTED_ARTIFACT_ZIP_SHA256 = "6a6394e91df0aab2681f7c042397cc4c572f4254e3f7df008840165f97cae2dc"',
        'EXPECTED_CANDIDATE_FILE_SHA256 = "60c57d7474464b66349cc9761eb4d4dd7895a470bf7634f1d091f73bf00718b6"',
        'EXPECTED_CANDIDATE_PROVENANCE_SHA256 = "adb4581a45423e5cb093fb49037a8e9a1448ecc13940318d5ee455cff825ee9f"',
        'EXPECTED_CANDIDATE_DECISIONS_SHA256 = "ed406f6cb0e5f1a3ed2e6355aba9dd90fa2f9d59aaee99192307c5448e34225a"',
        'EXPECTED_TRUTH_SHA256 = "ee859fc903012a8c617caa63446ad889a4b4f237c324b9e6a43f2a792b43d52c"',
        'row["candidate_auto_single"]',
        'automatic_candidate_parent_reuse_count',
        'adjudicate_group(',
    ):
        assert required in source
    for forbidden in (
        "expected_title",
        "expected_primary_price_eur",
        "selected_title",
        "selected_normal_price",
        "product override",
        "campaign override",
    ):
        assert forbidden not in source
    assert ACCEPTANCE["maximum_cross_cell_group_reuse"] == 0
