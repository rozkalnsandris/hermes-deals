from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

from app.edeka_shadow_ledger import (
    _cycle_record,
    build_two_cycle_shadow_ledger,
)
from app.edeka_source_card_accounting import audit_edeka_source_card_manifest


ACCOUNTED_LEDGER_SCHEMA_VERSION = 1
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _stable_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return sha256(_stable_json_bytes(value)).hexdigest()


def _required_sha256(value: object, label: str) -> str:
    if not isinstance(value, str) or _SHA256_RE.fullmatch(value) is None:
        raise ValueError(f"EDEKA accounted ledger {label} must be lowercase SHA-256")
    return value


def _accounted_cycle(
    legacy_record: Mapping[str, Any],
    accounting: Mapping[str, Any],
) -> tuple[dict[str, object], set[str]]:
    summary = accounting.get("summary")
    excluded_cards = accounting.get("excluded_cards")
    if not isinstance(summary, Mapping):
        raise ValueError("EDEKA accounted ledger accounting summary is missing")
    if not isinstance(excluded_cards, list):
        raise ValueError("EDEKA accounted ledger exclusions are missing")

    source_card_count = summary.get("source_card_count")
    parsed_offer_count = summary.get("parsed_offer_count")
    excluded_count = summary.get("excluded_count")
    if not all(isinstance(value, int) and not isinstance(value, bool) for value in (
        source_card_count,
        parsed_offer_count,
        excluded_count,
    )):
        raise ValueError("EDEKA accounted ledger accounting counts are invalid")
    if summary.get("accounting_complete") is not True:
        raise ValueError("EDEKA accounted ledger accounting is incomplete")
    if summary.get("unexplained_source_card_loss") is not False:
        raise ValueError("EDEKA accounted ledger has unexplained source-card loss")
    if source_card_count != parsed_offer_count + excluded_count:
        raise ValueError("EDEKA accounted ledger count invariant failed")

    parsed_ids_sha = _required_sha256(
        summary.get("parsed_offer_ids_sha256"),
        "parsed_offer_ids_sha256",
    )
    excluded_ids_sha = _required_sha256(
        summary.get("excluded_source_offer_ids_sha256"),
        "excluded_source_offer_ids_sha256",
    )
    accounting_sha = _required_sha256(
        accounting.get("report_sha256"),
        "source_card_accounting_sha256",
    )

    legacy_offer_count = legacy_record.get("offer_count")
    parsed_ids_raw = legacy_record.get("source_offer_ids")
    if legacy_offer_count != parsed_offer_count:
        raise ValueError("EDEKA accounted ledger parsed offer count mismatch")
    if not isinstance(parsed_ids_raw, list):
        raise ValueError("EDEKA accounted ledger parsed offer IDs are missing")
    parsed_ids = {str(value) for value in parsed_ids_raw}
    if len(parsed_ids) != parsed_offer_count:
        raise ValueError("EDEKA accounted ledger parsed offer IDs are not unique")
    if _sha256(sorted(parsed_ids)) != parsed_ids_sha:
        raise ValueError("EDEKA accounted ledger parsed offer ID hash mismatch")

    excluded_rows: list[dict[str, str]] = []
    excluded_ids: set[str] = set()
    for raw in excluded_cards:
        if not isinstance(raw, Mapping):
            raise ValueError("EDEKA accounted ledger exclusion must be an object")
        source_offer_id = raw.get("source_offer_id")
        reason = raw.get("exclusion_reason")
        dialog_id = raw.get("dialog_id")
        if not isinstance(source_offer_id, str) or not source_offer_id:
            raise ValueError("EDEKA accounted ledger excluded ID is missing")
        if source_offer_id in parsed_ids or source_offer_id in excluded_ids:
            raise ValueError("EDEKA accounted ledger source-card IDs overlap")
        if dialog_id != f"dialog-angebot-{source_offer_id}":
            raise ValueError("EDEKA accounted ledger dialog provenance mismatch")
        if not isinstance(reason, str) or not reason:
            raise ValueError("EDEKA accounted ledger exclusion reason is missing")
        excluded_ids.add(source_offer_id)
        excluded_rows.append(
            {
                "source_offer_id": source_offer_id,
                "dialog_id": dialog_id,
                "exclusion_reason": reason,
            }
        )

    if len(excluded_ids) != excluded_count:
        raise ValueError("EDEKA accounted ledger excluded count mismatch")
    if _sha256(sorted(excluded_ids)) != excluded_ids_sha:
        raise ValueError("EDEKA accounted ledger excluded offer ID hash mismatch")
    source_ids = parsed_ids | excluded_ids
    if len(source_ids) != source_card_count:
        raise ValueError("EDEKA accounted ledger source-card total mismatch")

    cycle = {
        "source_card_count": source_card_count,
        "parsed_offer_count": parsed_offer_count,
        "excluded_count": excluded_count,
        "source_card_ids_sha256": _sha256(sorted(source_ids)),
        "parsed_offer_ids_sha256": parsed_ids_sha,
        "excluded_source_offer_ids_sha256": excluded_ids_sha,
        "source_card_accounting_sha256": accounting_sha,
        "accounting_complete": True,
        "unexplained_source_card_loss": False,
        "excluded_cards": sorted(
            excluded_rows,
            key=lambda row: row["source_offer_id"],
        ),
    }
    return cycle, source_ids


def augment_two_cycle_ledger(
    legacy_ledger: Mapping[str, Any],
    first_legacy_record: Mapping[str, Any],
    second_legacy_record: Mapping[str, Any],
    first_accounting: Mapping[str, Any],
    second_accounting: Mapping[str, Any],
) -> dict[str, Any]:
    ledger = json.loads(json.dumps(dict(legacy_ledger)))
    ledger.pop("ledger_sha256", None)

    first_cycle, first_ids = _accounted_cycle(
        first_legacy_record,
        first_accounting,
    )
    second_cycle, second_ids = _accounted_cycle(
        second_legacy_record,
        second_accounting,
    )

    retained = sorted(first_ids & second_ids)
    added = sorted(second_ids - first_ids)
    removed = sorted(first_ids - second_ids)

    ledger["accounted_schema_version"] = ACCOUNTED_LEDGER_SCHEMA_VERSION
    gates = ledger.get("gates")
    if not isinstance(gates, dict):
        raise ValueError("EDEKA accounted ledger legacy gates are missing")
    gates["source_card_accounting_complete"] = True
    gates["zero_unexplained_source_card_loss"] = True

    ledger["source_card_accounting"] = {
        "cycle_one": first_cycle,
        "cycle_two": second_cycle,
    }
    ledger["source_card_delta"] = {
        "retained_count": len(retained),
        "added_count": len(added),
        "removed_count": len(removed),
        "retained_source_offer_ids": retained,
        "added_source_offer_ids": added,
        "removed_source_offer_ids": removed,
        "removed_ids_fully_enumerated": True,
        "unexplained_data_loss": False,
        "unexplained_data_loss_basis": (
            "parsed_plus_explicit_excluded_equals_source_cards_for_both_cycles"
        ),
    }

    legacy_delta = ledger.get("delta")
    if not isinstance(legacy_delta, dict):
        raise ValueError("EDEKA accounted ledger legacy delta is missing")
    legacy_delta["unexplained_data_loss"] = False
    legacy_delta["unexplained_data_loss_basis"] = "source_card_accounting"

    ledger["ledger_sha256"] = _sha256(ledger)
    return ledger


def build_accounted_two_cycle_shadow_ledger(
    cycle_one: tuple[Path, str],
    cycle_two: tuple[Path, str],
) -> dict[str, Any]:
    legacy = build_two_cycle_shadow_ledger(cycle_one, cycle_two)
    first_legacy = _cycle_record(*cycle_one)
    second_legacy = _cycle_record(*cycle_two)
    first_accounting = audit_edeka_source_card_manifest(*cycle_one)
    second_accounting = audit_edeka_source_card_manifest(*cycle_two)
    return augment_two_cycle_ledger(
        legacy,
        first_legacy,
        second_legacy,
        first_accounting,
        second_accounting,
    )


def write_accounted_shadow_ledger(path: Path, ledger: Mapping[str, Any]) -> None:
    data = _stable_json_bytes(ledger) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError(
                "Refusing to replace a different accounted EDEKA shadow ledger"
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify two EDEKA cycles with explicit source-card accounting"
    )
    parser.add_argument("--cycle-one-manifest", type=Path, required=True)
    parser.add_argument("--cycle-one-sha256", required=True)
    parser.add_argument("--cycle-two-manifest", type=Path, required=True)
    parser.add_argument("--cycle-two-sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        ledger = build_accounted_two_cycle_shadow_ledger(
            (args.cycle_one_manifest, args.cycle_one_sha256),
            (args.cycle_two_manifest, args.cycle_two_sha256),
        )
        write_accounted_shadow_ledger(args.output, ledger)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "result": "pass",
                "output": str(args.output),
                "ledger_sha256": ledger["ledger_sha256"],
                "source_card_delta": ledger["source_card_delta"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
