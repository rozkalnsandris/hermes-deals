from __future__ import annotations

import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import edeka_accounted_live_provenance_derivation as derivation  # noqa: E402


COMMIT = "a" * 40
ACCOUNTING_REPORT_SHA = "b" * 64
MANIFEST_SHA = "c" * 64


def _accounted_payload() -> dict[str, object]:
    return {
        "manifest": {
            "campaign_id": "edeka-071897-2026-08-10-2026-08-15-deadbeefdeadbeef",
        },
        "candidates": [
            {"candidate_id": "parsed", "route": "automatic_candidate"},
            {"candidate_id": "excluded", "route": "excluded"},
        ],
        "live_evidence": {
            "source_card_count": 2,
            "parsed_offer_count": 1,
            "excluded_count": 1,
            "unexplained_source_card_loss": False,
            "source_card_accounting_sha256": ACCOUNTING_REPORT_SHA,
        },
    }


def _accounting_report() -> dict[str, object]:
    return {
        "schema_version": 1,
        "audit_type": "edeka_source_card_accounting",
        "report_sha256": ACCOUNTING_REPORT_SHA,
        "summary": {
            "source_card_count": 2,
            "parsed_offer_count": 1,
            "excluded_count": 1,
            "accounting_complete": True,
            "unexplained_source_card_loss": False,
        },
        "excluded_cards": [
            {
                "source_offer_id": "excluded",
                "route": "excluded",
                "exclusion_reason": "source_card_missing_offer_price_pfand_only",
            }
        ],
    }


def _install_stubs(monkeypatch: pytest.MonkeyPatch, *, legacy_count: int = 1) -> None:
    def fake_legacy(
        artifact_dir: Path,
        output_dir: Path,
        **kwargs: object,
    ) -> dict[str, object]:
        del artifact_dir, kwargs
        cycle = output_dir / "extracted" / "archive-root" / "cycle"
        cycle.mkdir(parents=True)
        return {
            "result": "pass",
            "registered_commit": COMMIT,
            "campaign_id": "legacy-campaign",
            "candidate_count": legacy_count,
            "provenance_sha256": "d" * 64,
            "attestation_sha256": "e" * 64,
        }

    monkeypatch.setattr(
        derivation,
        "derive_live_provenance_from_artifact",
        fake_legacy,
    )
    monkeypatch.setattr(
        derivation,
        "build_accounted_live_candidate_provenance",
        lambda cycle_dir: _accounted_payload(),
    )
    monkeypatch.setattr(
        derivation,
        "validate_candidate_provenance",
        lambda payload: {
            "candidate_count": 2,
            "route_counts": {
                "automatic_candidate": 1,
                "review_required": 0,
                "excluded": 1,
            },
            "all_candidates_provenance_bound": True,
            "promotion_ready": False,
        },
    )
    monkeypatch.setattr(
        derivation,
        "_safe_cycle_manifest",
        lambda cycle_dir: (cycle_dir / "manifest.json", MANIFEST_SHA),
    )
    monkeypatch.setattr(
        derivation,
        "audit_edeka_source_card_manifest",
        lambda path, sha: _accounting_report(),
    )


def test_accounted_derivation_emits_only_sanitized_outputs(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stubs(monkeypatch)
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    output = tmp_path / "out"

    result = derivation.derive_accounted_live_provenance_from_artifact(
        artifact,
        output,
        source_run_id=123,
        source_run_attempt=1,
        artifact_id=456,
        artifact_name=f"edeka-shadow-cycle-{COMMIT}-run-123",
        artifact_digest="sha256:" + "f" * 64,
        derivation_commit=COMMIT,
    )

    assert result["result"] == "pass"
    assert result["source_card_count"] == 2
    assert result["parsed_offer_count"] == 1
    assert result["excluded_count"] == 1
    assert result["candidate_count"] == 2
    assert result["automatic_candidate_count"] == 1
    assert result["review_required_count"] == 0
    assert result["production_database_write"] is False
    assert result["production_deployment"] is False

    assert sorted(path.name for path in output.iterdir()) == [
        "SHA256SUMS",
        "derivation-attestation.json",
        "edeka-live-candidate-provenance.json",
        "source-card-accounting.json",
    ]
    assert not (output / "extracted").exists()
    assert not any(path.suffix == ".sqlite3" for path in output.rglob("*"))
    attestation = json.loads(
        (output / "derivation-attestation.json").read_text(encoding="utf-8")
    )
    assert attestation["safety"]["source_refetch"] is False
    assert attestation["safety"]["raw_source_uploaded"] is False
    assert attestation["safety"]["isolated_database_uploaded"] is False
    assert attestation["derivation"]["excluded_count"] == 1
    assert attestation["derivation"]["unexplained_source_card_loss"] is False


def test_accounted_derivation_rejects_legacy_parsed_count_drift(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    _install_stubs(monkeypatch, legacy_count=2)
    artifact = tmp_path / "artifact"
    artifact.mkdir()

    with pytest.raises(ValueError, match="legacy parsed count mismatch"):
        derivation.derive_accounted_live_provenance_from_artifact(
            artifact,
            tmp_path / "out",
            source_run_id=123,
            source_run_attempt=1,
            artifact_id=456,
            artifact_name=f"edeka-shadow-cycle-{COMMIT}-run-123",
            artifact_digest="sha256:" + "f" * 64,
            derivation_commit=COMMIT,
        )
