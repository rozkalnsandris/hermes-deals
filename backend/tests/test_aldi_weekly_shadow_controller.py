from __future__ import annotations

from copy import deepcopy
import importlib.util
from pathlib import Path
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
MODULE_PATH = ROOT / "tools" / "aldi_weekly_shadow_controller.py"
SPEC = importlib.util.spec_from_file_location("aldi_weekly_shadow_controller", MODULE_PATH)
assert SPEC is not None and SPEC.loader is not None
module = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = module
SPEC.loader.exec_module(module)

AldiWeeklyError = module.AldiWeeklyError
decide = module.decide


def manifest() -> dict[str, object]:
    return {
        "schema_version": 1,
        "retailer": "aldi_nord",
        "scope": "physical_store_flyer",
        "region": "aldi_nord",
        "campaign_id": "aldi-nord-2026-kw32",
        "valid_from": "2026-08-03",
        "valid_to": "2026-08-08",
        "source_url": "https://www.aldi-nord.de/angebote/aktion-mo-03-08.html",
        "source_state": "available",
        "source_sha256": "1" * 64,
        "page_manifest_sha256": "2" * 64,
        "parser_identity": "aldi-a21-frozen-v1",
        "ledger_identity": "aldi-a31-parity-v1",
        "ledger_sha256": "3" * 64,
        "automatic_candidate_count": 346,
        "review_required_count": 54,
        "unexplained_card_count": 0,
        "promotion_ready": False,
        "immutable_evidence": True,
    }


def test_new_verified_identity_is_ready_and_read_only() -> None:
    result = decide(manifest())
    assert result["decision"] == "READY"
    assert result["reasons"] == ["new_verified_identity"]
    assert result["safety"] == {
        "dry_run": True,
        "source_fetch_authorized": False,
        "corpus_write_authorized": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "automatic_approval_authorized": False,
        "production_publish_authorized": False,
        "scheduler_change_authorized": False,
        "production_canary_authorized": False,
    }


def test_exact_unchanged_identity_is_deterministic_noop() -> None:
    first = decide(manifest())
    second = decide(manifest(), {"schema_version": 1, "fingerprint": first["fingerprint"]})
    assert second["decision"] == "NO_OP"
    assert second["fingerprint"] == first["fingerprint"]


@pytest.mark.parametrize("state", ["not_published_yet", "source_unavailable", "review_pending"])
def test_wait_states_never_look_like_zero_offers(state: str) -> None:
    raw = manifest()
    raw["source_state"] = state
    result = decide(raw)
    assert result["decision"] == "WAIT"
    assert result["source_state"] == state


@pytest.mark.parametrize("state", ["evidence_mismatch", "parser_failed"])
def test_failure_states_block(state: str) -> None:
    raw = manifest()
    raw["source_state"] = state
    assert decide(raw)["decision"] == "BLOCKED"


def test_unexplained_cards_fail_closed() -> None:
    raw = manifest()
    raw["unexplained_card_count"] = 1
    result = decide(raw)
    assert result["decision"] == "BLOCKED"
    assert "unexplained_cards" in result["reasons"]


def test_parser_or_ledger_change_requires_new_shadow_run() -> None:
    first = decide(manifest())
    changed = deepcopy(manifest())
    changed["parser_identity"] = "aldi-a21-frozen-v2"
    result = decide(changed, {"schema_version": 1, "fingerprint": first["fingerprint"]})
    assert result["decision"] == "READY"
    assert result["fingerprint"] != first["fingerprint"]


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("retailer", "aldi_sued"),
        ("region", "aldi_sued"),
        ("source_url", "https://example.invalid/flyer"),
        ("source_sha256", "bad"),
        ("promotion_ready", True),
        ("immutable_evidence", False),
    ],
)
def test_identity_and_safety_drift_is_rejected(field: str, value: object) -> None:
    raw = manifest()
    raw[field] = value
    with pytest.raises(AldiWeeklyError):
        decide(raw)
