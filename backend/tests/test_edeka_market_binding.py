from __future__ import annotations

import copy
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "edeka_market_binding.py"
FIXTURE = ROOT / "backend" / "tests" / "fixtures" / "edeka" / "market_binding_v1.json"

spec = importlib.util.spec_from_file_location("edeka_market_binding", MODULE_PATH)
assert spec is not None and spec.loader is not None
module = importlib.util.module_from_spec(spec)
sys.modules[spec.name] = module
spec.loader.exec_module(module)


def test_authoritative_family_market_binding_passes() -> None:
    payload = module.load_market_binding(FIXTURE)
    assert payload["public_market_code"] == "071897"
    assert payload["source_market_id"] == "587881"
    assert payload["scope"] == "family_primary_edeka"
    assert payload["fallback_allowed"] is False
    assert payload["ambiguous_rows_route"] == "review_required"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("public_market_code", "071898"),
        ("source_market_id", "587882"),
        ("scope", "another_market"),
        ("fallback_allowed", True),
        ("source_manifest_required", False),
        ("campaign_window_required", False),
        ("source_sha256_required", False),
        ("parser_identity_required", False),
        ("ambiguous_rows_route", "automatic_candidate"),
        ("automatic_approval_enabled", True),
        ("automatic_publish_enabled", True),
        ("database_write_authorized", True),
        ("production_apply_authorized", True),
    ],
)
def test_binding_drift_fails_closed(field: str, value: object) -> None:
    payload = module.load_market_binding(FIXTURE)
    changed = copy.deepcopy(payload)
    changed[field] = value
    with pytest.raises(module.EdekaMarketBindingError):
        module.validate_market_binding(changed)
