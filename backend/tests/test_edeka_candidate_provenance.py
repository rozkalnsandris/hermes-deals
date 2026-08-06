from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
FIXTURE = ROOT / "backend/tests/fixtures/edeka/candidate_provenance_v1.json"

for name in ("edeka_market_binding", "edeka_regional_source_manifest"):
    spec = importlib.util.spec_from_file_location(name, TOOLS / f"{name}.py")
    assert spec is not None and spec.loader is not None
    loaded = importlib.util.module_from_spec(spec)
    sys.modules[name] = loaded
    spec.loader.exec_module(loaded)

spec = importlib.util.spec_from_file_location(
    "edeka_candidate_provenance", TOOLS / "edeka_candidate_provenance.py"
)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def fixture_payload() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_exact_candidate_provenance_passes() -> None:
    result = module.validate_candidate_provenance(fixture_payload())
    assert result["campaign_id"] == "synthetic-contract-2026-08-03"
    assert result["candidate_count"] == 2
    assert result["route_counts"] == {
        "automatic_candidate": 1,
        "excluded": 0,
        "review_required": 1,
    }
    assert result["all_candidates_provenance_bound"] is True
    assert result["promotion_ready"] is False


@pytest.mark.parametrize(
    "field",
    ["campaign_id", "source_sha256", "manifest_sha256", "parser_identity"],
)
def test_candidate_manifest_drift_fails_closed(field: str) -> None:
    payload = fixture_payload()
    payload["candidates"][0][field] = "mismatch"
    with pytest.raises(module.EdekaCandidateProvenanceError):
        module.validate_candidate_provenance(payload)


def test_ambiguous_candidate_cannot_be_automatic() -> None:
    payload = fixture_payload()
    payload["candidates"][1]["route"] = "automatic_candidate"
    with pytest.raises(module.EdekaCandidateProvenanceError):
        module.validate_candidate_provenance(payload)


def test_automatic_candidate_requires_complete_provenance() -> None:
    payload = fixture_payload()
    payload["candidates"][0]["provenance_complete"] = False
    with pytest.raises(module.EdekaCandidateProvenanceError):
        module.validate_candidate_provenance(payload)


def test_duplicate_candidate_and_missing_card_fail_closed() -> None:
    duplicate = fixture_payload()
    duplicate["candidates"][1]["candidate_id"] = duplicate["candidates"][0]["candidate_id"]
    with pytest.raises(module.EdekaCandidateProvenanceError):
        module.validate_candidate_provenance(duplicate)

    missing_card = fixture_payload()
    missing_card["candidates"][0]["card_id"] = ""
    with pytest.raises(module.EdekaCandidateProvenanceError):
        module.validate_candidate_provenance(missing_card)


def test_non_shadow_ready_manifest_is_blocked() -> None:
    payload = copy.deepcopy(fixture_payload())
    payload["manifest"]["source_state"] = "source_unavailable"
    with pytest.raises(module.EdekaCandidateProvenanceError):
        module.validate_candidate_provenance(payload)


@pytest.mark.parametrize(
    "key",
    [
        "database_write_authorized",
        "review_write_authorized",
        "automatic_approval_enabled",
        "automatic_publish_enabled",
        "production_apply_authorized",
    ],
)
def test_unsafe_authorization_flags_fail_closed(key: str) -> None:
    payload = fixture_payload()
    payload[key] = True
    with pytest.raises(module.EdekaCandidateProvenanceError):
        module.validate_candidate_provenance(payload)
