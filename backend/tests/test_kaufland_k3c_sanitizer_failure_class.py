from __future__ import annotations

import importlib.util
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR_PATH = ROOT / "tools/runner/kaufland_k3c_promo_structure_bridge_validator.py"

_spec = importlib.util.spec_from_file_location("kaufland_k3c_bridge_validator", VALIDATOR_PATH)
assert _spec is not None and _spec.loader is not None
validator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validator)


def test_sanitizer_failure_classes_are_fixed_and_allowlisted() -> None:
    assert validator._sanitizer_failure_reason(
        validator.BridgeValidationError("projection.marker_price_classes must be sorted and unique")
    ) == "SANITIZER_PRICE_CLASS_REJECTED"
    assert validator._sanitizer_failure_reason(
        validator.BridgeValidationError("projection.marker_locator is not a bounded rawpath locator")
    ) == "SANITIZER_LOCATOR_REJECTED"
    assert validator._sanitizer_failure_reason(
        validator.BridgeValidationError("diagnostic result identity mismatch")
    ) == "SANITIZER_IDENTITY_REJECTED"
    assert validator._sanitizer_failure_reason(
        validator.BridgeValidationError("diagnostic PASS field set mismatch")
    ) == "SANITIZER_SCHEMA_REJECTED"
    assert validator._sanitizer_failure_reason(
        validator.BridgeValidationError("projection marker sample bound exceeded")
    ) == "SANITIZER_BOUND_REJECTED"
    assert validator._sanitizer_failure_reason(
        validator.BridgeValidationError("unclassified private detail")
    ) == "SANITIZER_OUTPUT_REJECTED"


def test_main_exports_only_bounded_schema_rejection(tmp_path: Path) -> None:
    raw = tmp_path / "raw.json"
    artifact = tmp_path / "artifact.json"
    summary = tmp_path / "summary.json"
    secret = "PRIVATE_PRODUCT_TEXT_1.99"
    raw.write_text(
        json.dumps({"status": "PASS", "raw_html": secret}),
        encoding="utf-8",
    )

    rc = validator.main(
        [
            "--raw",
            str(raw),
            "--artifact",
            str(artifact),
            "--summary",
            str(summary),
            "--expected-sha",
            "1" * 40,
            "--diagnostic-rc",
            "0",
        ]
    )

    assert rc == 0
    artifact_payload = json.loads(artifact.read_text(encoding="utf-8"))
    summary_payload = json.loads(summary.read_text(encoding="utf-8"))
    assert artifact_payload["diagnostic_status"] == "BLOCKED"
    assert summary_payload["bridge_execution_status"] == "PASS"
    assert summary_payload["diagnostic_status"] == "BLOCKED"
    assert summary_payload["reason_code"] == "SANITIZER_SCHEMA_REJECTED"
    exported = artifact.read_text(encoding="utf-8") + summary.read_text(encoding="utf-8")
    assert secret not in exported
    assert "field set mismatch" not in exported


def test_main_exports_bounded_input_read_rejection_for_invalid_json(tmp_path: Path) -> None:
    raw = tmp_path / "raw.json"
    artifact = tmp_path / "artifact.json"
    summary = tmp_path / "summary.json"
    raw.write_text('{"private": "unterminated', encoding="utf-8")

    rc = validator.main(
        [
            "--raw",
            str(raw),
            "--artifact",
            str(artifact),
            "--summary",
            str(summary),
            "--expected-sha",
            "2" * 40,
            "--diagnostic-rc",
            "0",
        ]
    )

    assert rc == 0
    summary_payload = json.loads(summary.read_text(encoding="utf-8"))
    assert summary_payload["reason_code"] == "SANITIZER_INPUT_READ_REJECTED"
    assert summary_payload["diagnostic_status"] == "BLOCKED"
