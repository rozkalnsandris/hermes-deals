from __future__ import annotations

import importlib.util
from pathlib import Path
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
CONTROLLER = ROOT / "tools" / "lidl_weekly_shadow_controller.py"
SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64


def load_controller():
    spec = importlib.util.spec_from_file_location(
        "hermes_lidl_weekly_shadow_controller",
        CONTROLLER,
    )
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def ready_status(*, parser_sha: str = SHA_C, profile_version: int = 1) -> dict:
    return {
        "result": "READY",
        "reason": "selected_store_source_scan_profile_and_v631_ready",
        "target": "next",
        "today_berlin": "2026-08-05",
        "corpus_match": {
            "flyer_key": "20260810-20260815-r21-example",
            "scan": "scan-0001",
            "source_pdf_sha256": SHA_A,
            "stable_source_identity_sha256": SHA_B,
        },
        "review_profile": {
            "schema_version": profile_version,
            "status": "reviewed",
            "target_page_count": 23,
        },
        "parser_version": "lidl-pdf-v08c-r61-shadow-v631",
        "parser_sha256": parser_sha,
        "dry_run": True,
        "corpus_write": False,
        "db_write": False,
        "review_seed": False,
        "auto_approve": False,
        "auto_publish": False,
        "systemd_change": False,
    }


def previous_manifest(fingerprint: str, *, result: str = "READY") -> dict:
    return {
        "schema_version": 1,
        "controller_version": "lidl-weekly-shadow-controller-v1",
        "result": result,
        "execution_fingerprint": fingerprint,
        "dry_run": True,
        "corpus_write_authorized": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "production_publish_authorized": False,
        "systemd_change_authorized": False,
    }


def test_new_exact_input_is_ready_without_write_authority() -> None:
    controller = load_controller()
    result = controller.evaluate_one_shot_status(ready_status())

    assert result["result"] == "READY"
    assert result["reason"] == "new_exact_shadow_input"
    assert len(result["execution_fingerprint"]) == 64
    assert result["new_immutable_snapshot_required"] is True
    assert result["shadow_execution_required"] is True
    assert result["unchanged_exact_input"] is False
    assert result["corpus_write_authorized"] is False
    assert result["database_write_authorized"] is False
    assert result["review_write_authorized"] is False
    assert result["production_publish_authorized"] is False
    assert result["systemd_change_authorized"] is False
    assert result["bounded_retry_authorized"] is False


def test_same_exact_input_is_deterministic_safe_no_op() -> None:
    controller = load_controller()
    first = controller.evaluate_one_shot_status(ready_status())
    previous = previous_manifest(first["execution_fingerprint"])

    second = controller.evaluate_one_shot_status(
        ready_status(),
        previous_manifest=previous,
    )

    assert second["result"] == "NO_OP"
    assert second["reason"] == "unchanged_exact_shadow_input"
    assert second["execution_fingerprint"] == first["execution_fingerprint"]
    assert second["previous_execution_fingerprint"] == first["execution_fingerprint"]
    assert second["unchanged_exact_input"] is True
    assert second["new_immutable_snapshot_required"] is False
    assert second["shadow_execution_required"] is False


def test_parser_or_review_profile_change_requires_new_shadow_execution() -> None:
    controller = load_controller()
    baseline = controller.evaluate_one_shot_status(ready_status())
    previous = previous_manifest(baseline["execution_fingerprint"], result="NO_OP")

    parser_change = controller.evaluate_one_shot_status(
        ready_status(parser_sha="d" * 64),
        previous_manifest=previous,
    )
    profile_change = controller.evaluate_one_shot_status(
        ready_status(profile_version=2),
        previous_manifest=previous,
    )

    assert parser_change["result"] == "READY"
    assert profile_change["result"] == "READY"
    assert parser_change["execution_fingerprint"] != baseline["execution_fingerprint"]
    assert profile_change["execution_fingerprint"] != baseline["execution_fingerprint"]


@pytest.mark.parametrize("one_shot_result", ["WAIT_SOURCE", "WAIT_SCAN", "WAIT_PROFILE"])
def test_wait_states_are_observable_without_retry_authority(one_shot_result: str) -> None:
    controller = load_controller()
    status = ready_status()
    status["result"] = one_shot_result
    status["reason"] = "not_ready_yet"
    status["corpus_match"] = None
    status["review_profile"] = {}

    result = controller.evaluate_one_shot_status(status)

    assert result["result"] == "WAIT"
    assert result["reason"] == f"one_shot_{one_shot_result.lower()}"
    assert result["bounded_retry_authorized"] is False
    assert result["execution_fingerprint"] is None


@pytest.mark.parametrize(
    "one_shot_result",
    ["BLOCKED_SOURCE_DRIFT", "BLOCKED_PARSER_DRIFT"],
)
def test_blocked_states_fail_closed(one_shot_result: str) -> None:
    controller = load_controller()
    status = ready_status()
    status["result"] = one_shot_result
    status["reason"] = "drift_detected"

    result = controller.evaluate_one_shot_status(status)

    assert result["result"] == "BLOCKED"
    assert result["reason"] == f"one_shot_{one_shot_result.lower()}"
    assert result["shadow_execution_required"] is False


def test_unsafe_one_shot_flags_fail_closed() -> None:
    controller = load_controller()
    status = ready_status()
    status["db_write"] = True

    with pytest.raises(
        controller.LidlWeeklyShadowControllerError,
        match="one-shot safety flag mismatch: db_write",
    ):
        controller.evaluate_one_shot_status(status)


def test_ready_status_requires_complete_content_addressed_identity() -> None:
    controller = load_controller()
    status = ready_status()
    status["corpus_match"]["stable_source_identity_sha256"] = ""

    with pytest.raises(
        controller.LidlWeeklyShadowControllerError,
        match="READY fingerprint field is missing",
    ):
        controller.evaluate_one_shot_status(status)


def test_previous_manifest_validation_is_fail_closed(tmp_path: Path) -> None:
    controller = load_controller()
    path = tmp_path / "previous.json"
    path.write_text(
        '{"schema_version":1,"controller_version":"wrong","result":"READY"}\n',
        encoding="utf-8",
    )

    with pytest.raises(
        controller.LidlWeeklyShadowControllerError,
        match="previous manifest controller version mismatch",
    ):
        controller.load_previous_manifest(path)


def test_evaluation_is_deterministic() -> None:
    controller = load_controller()
    first = controller.evaluate_one_shot_status(ready_status())
    second = controller.evaluate_one_shot_status(ready_status())
    assert first == second


def test_cli_compiles_and_documents_read_only_states() -> None:
    subprocess.run(["python", "-m", "py_compile", str(CONTROLLER)], check=True)
    completed = subprocess.run(
        ["python", str(CONTROLLER), "--help"],
        check=True,
        text=True,
        capture_output=True,
    )
    for marker in ("READY", "NO_OP", "WAIT", "BLOCKED", "--previous-manifest"):
        assert marker in completed.stdout

    text = CONTROLLER.read_text(encoding="utf-8")
    assert "database_write_authorized\": False" in text
    assert "production_publish_authorized\": False" in text
    assert "systemd_change_authorized\": False" in text
    assert "bounded_retry_authorized\": False" in text
