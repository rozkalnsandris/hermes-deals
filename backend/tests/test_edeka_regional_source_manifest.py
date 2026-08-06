from __future__ import annotations

import copy
import importlib.util
import json
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
BINDING_PATH = ROOT / "tools" / "edeka_market_binding.py"
MODULE_PATH = ROOT / "tools" / "edeka_regional_source_manifest.py"
FIXTURE = (
    ROOT
    / "backend"
    / "tests"
    / "fixtures"
    / "edeka"
    / "regional_source_manifest_v1.json"
)

binding_spec = importlib.util.spec_from_file_location("edeka_market_binding", BINDING_PATH)
assert binding_spec is not None and binding_spec.loader is not None
binding_module = importlib.util.module_from_spec(binding_spec)
sys.modules[binding_spec.name] = binding_module
binding_spec.loader.exec_module(binding_module)

spec = importlib.util.spec_from_file_location("edeka_regional_source_manifest", MODULE_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def fixture_payload() -> dict[str, object]:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_authoritative_regional_source_manifest_passes() -> None:
    result = module.validate_regional_source_manifest(fixture_payload())
    assert result["public_market_code"] == "071897"
    assert result["source_market_id"] == "587881"
    assert result["campaign_window_days"] == 6
    assert result["shadow_ready"] is True
    assert result["fallback_allowed"] is False
    assert result["ambiguous_rows_route"] == "review_required"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("public_market_code", "071898"),
        ("source_market_id", "587882"),
        ("scope", "another_market"),
        ("source_url", "https://example.com/offers"),
        ("source_sha256", "not-a-sha"),
        ("manifest_sha256", "ABC"),
        ("parser_identity", ""),
        ("source_state", "no_offers_verified"),
        ("fallback_allowed", True),
        ("ambiguous_rows_route", "automatic_candidate"),
        ("database_write_authorized", True),
        ("review_write_authorized", True),
        ("automatic_approval_enabled", True),
        ("automatic_publish_enabled", True),
        ("production_apply_authorized", True),
    ],
)
def test_manifest_drift_fails_closed(field: str, value: object) -> None:
    payload = fixture_payload()
    payload[field] = value
    with pytest.raises(module.EdekaRegionalSourceManifestError):
        module.validate_regional_source_manifest(payload)


def test_inverted_or_unbounded_campaign_windows_fail_closed() -> None:
    inverted = fixture_payload()
    inverted["valid_from"] = "2026-08-09"
    with pytest.raises(module.EdekaRegionalSourceManifestError):
        module.validate_regional_source_manifest(inverted)

    broad = fixture_payload()
    broad["valid_to"] = "2026-10-01"
    with pytest.raises(module.EdekaRegionalSourceManifestError):
        module.validate_regional_source_manifest(broad)


def test_unavailable_source_is_observable_but_not_shadow_ready() -> None:
    payload = copy.deepcopy(fixture_payload())
    payload["source_state"] = "source_unavailable"
    result = module.validate_regional_source_manifest(payload)
    assert result["shadow_ready"] is False
