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
    cases = (
        ("projection.marker_price_classes must be sorted and unique", "SANITIZER_PRICE_CLASS_REJECTED"),
        ("projection.marker_locator is not a bounded rawpath locator", "SANITIZER_LOCATOR_REJECTED"),
        ("diagnostic result identity mismatch", "SANITIZER_IDENTITY_REJECTED"),
        ("diagnostic PASS field set mismatch", "SANITIZER_SCHEMA_REJECTED"),
        ("projection marker sample bound exceeded", "SANITIZER_COLLECTION_BOUND_REJECTED"),
        ("projection marker truncation flag is inconsistent", "SANITIZER_SAMPLE_CONSISTENCY_REJECTED"),
        ("projection marker count smaller than samples", "SANITIZER_SAMPLE_CONSISTENCY_REJECTED"),
        ("projection.public_amount_candidate_samples[0].candidate_amount_count must be exactly one", "SANITIZER_EXACT_CARDINALITY_REJECTED"),
        ("unclassified private detail", "SANITIZER_OUTPUT_REJECTED"),
    )
    for message, expected in cases:
        assert validator._sanitizer_failure_reason(validator.BridgeValidationError(message)) == expected


def test_split_bound_classes_do_not_export_private_detail(tmp_path: Path) -> None:
    private = "PRIVATE_PRODUCT_TEXT_1.99/rawpath:/secret"
    for index, message in enumerate(
        (
            f"projection marker sample bound exceeded {private}",
            f"projection marker truncation flag is inconsistent {private}",
            f"candidate_amount_count must be exactly one {private}",
        )
    ):
        reason = validator._sanitizer_failure_reason(validator.BridgeValidationError(message))
        artifact, summary = validator._sanitizer_blocked_receipt(expected_sha=str(index + 3) * 40, reason=reason)
        exported = json.dumps(artifact, sort_keys=True) + json.dumps(summary, sort_keys=True)
        assert private not in exported
        assert "rawpath:/secret" not in exported


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
