from __future__ import annotations

from copy import deepcopy
import hashlib
import json
from pathlib import Path
import sys

import pytest

REPO_ROOT = Path(__file__).resolve().parents[2]
TOOLS = REPO_ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import netto_hz37_v2_prediction_group_adjudication as hz37  # noqa: E402
from netto_hz37_v2_prediction_group_adjudication import build_metrics  # noqa: E402
from netto_heldout_ownership_protocol import ACCEPTANCE  # noqa: E402

TRUTH_PATH = REPO_ROOT / "audit/netto/hz37/completed-source-truth.json"


def metric_row(outcome: str, *, automatic: bool = False, index: int = 1) -> dict:
    return {
        "prediction_unit_id": f"p001-g{index:03d}",
        "outcome": outcome,
        "candidate_auto_single": automatic,
    }


def _write_bound_truth(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, payload: dict, name: str) -> Path:
    path = tmp_path / name
    path.write_bytes((json.dumps(payload, ensure_ascii=False, sort_keys=True) + "\n").encode("utf-8"))
    monkeypatch.setattr(hz37, "EXPECTED_TRUTH_SHA256", hashlib.sha256(path.read_bytes()).hexdigest())
    return path


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


def test_hz37_truth_validator_accepts_canonical_reviewer_process_schema() -> None:
    truth = hz37._validate_truth(TRUTH_PATH)
    reviewer_process = truth["reviewer_process"]
    assert reviewer_process["frozen_predictions_opened"] is False
    assert reviewer_process["candidate_provenance_opened"] is False
    assert reviewer_process["adjudication_started"] is False
    assert truth["adjudication_started"] is False


def test_hz37_truth_validator_requires_exact_false_reviewer_flags(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    canonical = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    for key in ("frozen_predictions_opened", "candidate_provenance_opened", "adjudication_started"):
        payload = deepcopy(canonical)
        payload["reviewer_process"][key] = True
        path = _write_bound_truth(tmp_path, monkeypatch, payload, f"truth-{key}.json")
        with pytest.raises(hz37.Hz37V2AdjudicationError, match=f"completed truth reviewer process mismatch: {key}"):
            hz37._validate_truth(path)

    payload = deepcopy(canonical)
    payload["reviewer_process"]["frozen_predictions_opened"] = 0
    path = _write_bound_truth(tmp_path, monkeypatch, payload, "truth-false-like-int.json")
    with pytest.raises(
        hz37.Hz37V2AdjudicationError,
        match="completed truth reviewer process mismatch: frozen_predictions_opened",
    ):
        hz37._validate_truth(path)


def test_hz37_truth_validator_requires_reviewer_process_mapping(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    payload["reviewer_process"] = None
    path = _write_bound_truth(tmp_path, monkeypatch, payload, "truth-no-reviewer-process.json")
    with pytest.raises(hz37.Hz37V2AdjudicationError, match="completed truth reviewer process missing"):
        hz37._validate_truth(path)


def test_hz37_truth_validator_preserves_top_level_adjudication_guard(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    payload = json.loads(TRUTH_PATH.read_text(encoding="utf-8"))
    payload["adjudication_started"] = True
    path = _write_bound_truth(tmp_path, monkeypatch, payload, "truth-adjudication-started.json")
    with pytest.raises(hz37.Hz37V2AdjudicationError, match="completed truth contract mismatch: adjudication_started"):
        hz37._validate_truth(path)


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
        'reviewer_process = truth.get("reviewer_process")',
        'reviewer_process.get(key) is not False',
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
