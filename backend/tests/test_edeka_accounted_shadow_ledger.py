from __future__ import annotations

from hashlib import sha256
import json

import pytest

from app.edeka_accounted_shadow_ledger import augment_two_cycle_ledger


FIRST_PARSED = "aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa"
SECOND_PARSED = "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"
EXCLUDED = "68aa5875-e4e1-4a5b-8d6c-221a2319dc2b"


def _sha(value: object) -> str:
    data = json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(data).hexdigest()


def _legacy_ledger() -> dict[str, object]:
    return {
        "schema_version": 1,
        "audit_type": "edeka_two_cycle_shadow_ledger",
        "result": "pass",
        "gates": {
            "cycle_start_delta_days": 7,
            "same_parser_version": True,
            "same_normalizer_version": True,
        },
        "delta": {
            "retained_count": 0,
            "added_count": 1,
            "removed_count": 1,
            "unexplained_data_loss": False,
        },
        "ledger_sha256": "f" * 64,
    }


def _legacy_record(source_offer_id: str) -> dict[str, object]:
    return {
        "offer_count": 1,
        "source_offer_ids": [source_offer_id],
    }


def _accounting(
    parsed_id: str,
    *,
    include_excluded: bool,
) -> dict[str, object]:
    excluded = []
    excluded_ids: list[str] = []
    if include_excluded:
        excluded = [
            {
                "source_offer_id": EXCLUDED,
                "dialog_id": f"dialog-angebot-{EXCLUDED}",
                "route": "excluded",
                "exclusion_reason": "source_card_missing_offer_price_pfand_only",
            }
        ]
        excluded_ids = [EXCLUDED]
    return {
        "report_sha256": "c" * 64,
        "summary": {
            "source_card_count": 1 + len(excluded),
            "parsed_offer_count": 1,
            "excluded_count": len(excluded),
            "accounting_complete": True,
            "unexplained_source_card_loss": False,
            "parsed_offer_ids_sha256": _sha([parsed_id]),
            "excluded_source_offer_ids_sha256": _sha(excluded_ids),
        },
        "excluded_cards": excluded,
    }


def test_accounted_ledger_enumerates_source_card_transition() -> None:
    ledger = augment_two_cycle_ledger(
        _legacy_ledger(),
        _legacy_record(FIRST_PARSED),
        _legacy_record(SECOND_PARSED),
        _accounting(FIRST_PARSED, include_excluded=False),
        _accounting(SECOND_PARSED, include_excluded=True),
    )

    assert ledger["gates"]["source_card_accounting_complete"] is True
    assert ledger["gates"]["zero_unexplained_source_card_loss"] is True
    assert ledger["source_card_accounting"]["cycle_one"]["source_card_count"] == 1
    assert ledger["source_card_accounting"]["cycle_two"]["source_card_count"] == 2
    assert ledger["source_card_delta"] == {
        "retained_count": 0,
        "added_count": 2,
        "removed_count": 1,
        "retained_source_offer_ids": [],
        "added_source_offer_ids": [EXCLUDED, SECOND_PARSED],
        "removed_source_offer_ids": [FIRST_PARSED],
        "removed_ids_fully_enumerated": True,
        "unexplained_data_loss": False,
        "unexplained_data_loss_basis": (
            "parsed_plus_explicit_excluded_equals_source_cards_for_both_cycles"
        ),
    }
    assert ledger["delta"]["unexplained_data_loss_basis"] == (
        "source_card_accounting"
    )
    assert len(ledger["ledger_sha256"]) == 64


def test_accounted_ledger_rejects_unexplained_loss_marker() -> None:
    accounting = _accounting(SECOND_PARSED, include_excluded=True)
    accounting["summary"]["unexplained_source_card_loss"] = True

    with pytest.raises(ValueError, match="unexplained source-card loss"):
        augment_two_cycle_ledger(
            _legacy_ledger(),
            _legacy_record(FIRST_PARSED),
            _legacy_record(SECOND_PARSED),
            _accounting(FIRST_PARSED, include_excluded=False),
            accounting,
        )


def test_accounted_ledger_rejects_count_mismatch() -> None:
    accounting = _accounting(SECOND_PARSED, include_excluded=True)
    accounting["summary"]["source_card_count"] = 3

    with pytest.raises(ValueError, match="count invariant failed"):
        augment_two_cycle_ledger(
            _legacy_ledger(),
            _legacy_record(FIRST_PARSED),
            _legacy_record(SECOND_PARSED),
            _accounting(FIRST_PARSED, include_excluded=False),
            accounting,
        )


def test_accounted_ledger_rejects_malformed_accounting_hash() -> None:
    accounting = _accounting(SECOND_PARSED, include_excluded=True)
    accounting["report_sha256"] = "not-a-sha"

    with pytest.raises(ValueError, match="must be lowercase SHA-256"):
        augment_two_cycle_ledger(
            _legacy_ledger(),
            _legacy_record(FIRST_PARSED),
            _legacy_record(SECOND_PARSED),
            _accounting(FIRST_PARSED, include_excluded=False),
            accounting,
        )
