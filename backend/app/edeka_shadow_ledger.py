from __future__ import annotations

import argparse
from datetime import date
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from typing import Any

from app.edeka_normalization_audit import audit_edeka_manifest


LEDGER_SCHEMA_VERSION = 1
EXPECTED_SOURCE_URL = "https://www.edeka.de/maerkte/071897/angebote/"
EXPECTED_PUBLIC_MARKET_ID = "071897"
EXPECTED_INTERNAL_MARKET_ID = "587881"
EXPECTED_STORE_NAME = "EDEKA Patzer"
EXPECTED_SCOPE = "family_primary_edeka"
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


def _verified_manifest_payload(
    manifest_path: Path,
    expected_sha256: str,
) -> dict[str, object]:
    if _SHA256_RE.fullmatch(expected_sha256) is None:
        raise ValueError("EDEKA shadow ledger requires lowercase SHA-256")
    data = manifest_path.read_bytes()
    if sha256(data).hexdigest() != expected_sha256:
        raise ValueError("EDEKA shadow ledger manifest SHA mismatch")
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("EDEKA shadow ledger manifest must be a JSON object")
    return payload


def _cycle_record(
    manifest_path: Path,
    manifest_sha256: str,
) -> dict[str, object]:
    manifest = _verified_manifest_payload(manifest_path, manifest_sha256)
    report = audit_edeka_manifest(manifest_path, manifest_sha256)

    source = report.get("source")
    summary = report.get("summary")
    rows = report.get("rows")
    if not isinstance(source, dict):
        raise ValueError("EDEKA shadow normalization source is missing")
    if not isinstance(summary, dict):
        raise ValueError("EDEKA shadow normalization summary is missing")
    if not isinstance(rows, list):
        raise ValueError("EDEKA shadow normalization rows are missing")

    expected_source = {
        "source_chain": "edeka",
        "scope": EXPECTED_SCOPE,
        "public_market_id": EXPECTED_PUBLIC_MARKET_ID,
        "internal_market_id": EXPECTED_INTERNAL_MARKET_ID,
        "store_name": EXPECTED_STORE_NAME,
        "source_url": EXPECTED_SOURCE_URL,
    }
    for key, expected in expected_source.items():
        if source.get(key) != expected:
            raise ValueError(f"EDEKA shadow cycle source {key} mismatch")

    source_offer_ids: list[str] = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("EDEKA shadow normalization row must be an object")
        source_offer_id = row.get("source_offer_id")
        if not isinstance(source_offer_id, str) or not source_offer_id:
            raise ValueError("EDEKA shadow row source_offer_id is missing")
        source_offer_ids.append(source_offer_id)
    if len(source_offer_ids) != len(set(source_offer_ids)):
        raise ValueError("EDEKA shadow cycle contains duplicate source_offer_id")

    offer_count = summary.get("offer_count")
    if not isinstance(offer_count, int) or offer_count != len(source_offer_ids):
        raise ValueError("EDEKA shadow cycle offer count mismatch")

    valid_from = source.get("valid_from")
    valid_until = source.get("valid_until")
    if not isinstance(valid_from, str) or not isinstance(valid_until, str):
        raise ValueError("EDEKA shadow cycle validity window is missing")
    start = date.fromisoformat(valid_from)
    end = date.fromisoformat(valid_until)
    if end < start:
        raise ValueError("EDEKA shadow cycle validity window is inverted")
    if (end - start).days > 13:
        raise ValueError("EDEKA shadow cycle validity window is implausibly long")

    manifest_raw_sha = manifest.get("raw_html_sha256")
    if (
        not isinstance(manifest_raw_sha, str)
        or _SHA256_RE.fullmatch(manifest_raw_sha) is None
    ):
        raise ValueError("EDEKA shadow cycle raw HTML SHA is missing")

    snapshot_id = source.get("snapshot_id")
    collected_at = source.get("collected_at")
    parser_version = source.get("parser_version")
    normalizer_version = report.get("normalizer_version")
    rows_sha256 = summary.get("rows_sha256")
    report_sha256 = report.get("report_sha256")
    for name, value in {
        "snapshot_id": snapshot_id,
        "collected_at": collected_at,
        "parser_version": parser_version,
        "normalizer_version": normalizer_version,
        "rows_sha256": rows_sha256,
        "report_sha256": report_sha256,
    }.items():
        if not isinstance(value, str) or not value:
            raise ValueError(f"EDEKA shadow cycle {name} is missing")

    resolved_count = summary.get("resolved_count")
    review_required_count = summary.get("review_required_count")
    if not isinstance(resolved_count, int) or not isinstance(
        review_required_count,
        int,
    ):
        raise ValueError("EDEKA shadow cycle normalization counts are invalid")
    if resolved_count + review_required_count != offer_count:
        raise ValueError("EDEKA shadow cycle normalization totals mismatch")

    sorted_ids = sorted(source_offer_ids)
    return {
        "manifest_path": str(manifest_path),
        "manifest_sha256": manifest_sha256,
        "raw_html_sha256": manifest_raw_sha,
        "snapshot_id": snapshot_id,
        "collected_at": collected_at,
        "valid_from": valid_from,
        "valid_until": valid_until,
        "offer_count": offer_count,
        "resolved_count": resolved_count,
        "review_required_count": review_required_count,
        "parser_version": parser_version,
        "normalizer_version": normalizer_version,
        "source_offer_ids_sha256": _sha256(sorted_ids),
        "normalization_rows_sha256": rows_sha256,
        "normalization_report_sha256": report_sha256,
        "source_offer_ids": sorted_ids,
    }


def _percent(numerator: int, denominator: int) -> str:
    if denominator <= 0:
        return "0.00"
    value = (
        Decimal(numerator) * Decimal("100") / Decimal(denominator)
    ).quantize(Decimal("0.01"))
    return format(value, "f")


def build_two_cycle_shadow_ledger(
    cycle_one: tuple[Path, str],
    cycle_two: tuple[Path, str],
    *,
    min_offers_per_cycle: int = 150,
    max_offer_count_drop_percent: Decimal = Decimal("40.00"),
) -> dict[str, object]:
    if min_offers_per_cycle <= 0:
        raise ValueError("EDEKA shadow minimum offer count must be positive")
    if (
        max_offer_count_drop_percent < 0
        or max_offer_count_drop_percent > 100
    ):
        raise ValueError("EDEKA shadow drop threshold must be between 0 and 100")

    first = _cycle_record(*cycle_one)
    second = _cycle_record(*cycle_two)

    first_start = date.fromisoformat(str(first["valid_from"]))
    first_end = date.fromisoformat(str(first["valid_until"]))
    second_start = date.fromisoformat(str(second["valid_from"]))
    second_end = date.fromisoformat(str(second["valid_until"]))

    if (second_start - first_start).days != 7:
        raise ValueError(
            "EDEKA shadow cycles must start exactly seven days apart"
        )
    if second_start <= first_end:
        raise ValueError("EDEKA shadow cycles must not overlap")
    if second_end <= first_end:
        raise ValueError("EDEKA second shadow cycle must be newer")

    for key in ("snapshot_id", "manifest_sha256", "raw_html_sha256"):
        if first[key] == second[key]:
            raise ValueError(f"EDEKA shadow cycles require distinct {key}")
    for key in ("parser_version", "normalizer_version"):
        if first[key] != second[key]:
            raise ValueError(
                f"EDEKA shadow cycles require identical {key}"
            )

    for index, cycle in enumerate((first, second), start=1):
        if int(cycle["offer_count"]) < min_offers_per_cycle:
            raise ValueError(
                f"EDEKA shadow cycle {index} has only "
                f"{cycle['offer_count']} offers; minimum is "
                f"{min_offers_per_cycle}"
            )

    first_ids = set(str(value) for value in first["source_offer_ids"])
    second_ids = set(str(value) for value in second["source_offer_ids"])
    retained = sorted(first_ids & second_ids)
    added = sorted(second_ids - first_ids)
    removed = sorted(first_ids - second_ids)

    first_count = int(first["offer_count"])
    second_count = int(second["offer_count"])
    drop_count = max(first_count - second_count, 0)
    drop_percent = Decimal(_percent(drop_count, first_count))
    if drop_percent > max_offer_count_drop_percent:
        raise ValueError(
            "EDEKA shadow offer-count drop exceeds threshold: "
            f"drop={drop_percent}% limit={max_offer_count_drop_percent}%"
        )

    cycles: list[dict[str, object]] = []
    for index, record in enumerate((first, second), start=1):
        cycle = dict(record)
        cycle.pop("source_offer_ids")
        cycle["cycle_index"] = index
        cycles.append(cycle)

    ledger: dict[str, object] = {
        "schema_version": LEDGER_SCHEMA_VERSION,
        "audit_type": "edeka_two_cycle_shadow_ledger",
        "result": "pass",
        "source": {
            "source_chain": "edeka",
            "scope": EXPECTED_SCOPE,
            "public_market_id": EXPECTED_PUBLIC_MARKET_ID,
            "internal_market_id": EXPECTED_INTERNAL_MARKET_ID,
            "store_name": EXPECTED_STORE_NAME,
            "source_url": EXPECTED_SOURCE_URL,
        },
        "gates": {
            "cycle_start_delta_days": 7,
            "min_offers_per_cycle": min_offers_per_cycle,
            "max_offer_count_drop_percent": format(
                max_offer_count_drop_percent,
                "f",
            ),
            "distinct_snapshot_ids": True,
            "distinct_manifest_sha256": True,
            "distinct_raw_html_sha256": True,
            "same_parser_version": True,
            "same_normalizer_version": True,
        },
        "cycles": cycles,
        "delta": {
            "retained_count": len(retained),
            "added_count": len(added),
            "removed_count": len(removed),
            "retention_percent": _percent(len(retained), first_count),
            "offer_count_drop_percent": format(drop_percent, "f"),
            "added_source_offer_ids": added,
            "removed_source_offer_ids": removed,
            "removed_ids_fully_enumerated": True,
            "unexplained_data_loss": False,
        },
        "replay_contract": {
            "persistence_key": ["snapshot_id", "source_offer_id"],
            "cycle_one_expected_first_write": first_count,
            "cycle_two_expected_first_write": second_count,
            "same_snapshot_replay_expected_offer_delta": 0,
            "unchanged_source_expected_snapshot_delta": 0,
            "unchanged_source_expected_offer_delta": 0,
            "subset_snapshot_persistence_forbidden": True,
        },
    }
    ledger["ledger_sha256"] = _sha256(ledger)
    return ledger


def write_shadow_ledger(path: Path, ledger: dict[str, object]) -> None:
    data = _stable_json_bytes(ledger) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError(
                "Refusing to replace a different EDEKA shadow ledger"
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Verify two consecutive immutable EDEKA shadow cycles"
    )
    parser.add_argument("--cycle-one-manifest", type=Path, required=True)
    parser.add_argument("--cycle-one-sha256", required=True)
    parser.add_argument("--cycle-two-manifest", type=Path, required=True)
    parser.add_argument("--cycle-two-sha256", required=True)
    parser.add_argument("--min-offers", type=int, default=150)
    parser.add_argument(
        "--max-drop-percent",
        type=Decimal,
        default=Decimal("40.00"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        ledger = build_two_cycle_shadow_ledger(
            (args.cycle_one_manifest, args.cycle_one_sha256),
            (args.cycle_two_manifest, args.cycle_two_sha256),
            min_offers_per_cycle=args.min_offers,
            max_offer_count_drop_percent=args.max_drop_percent,
        )
        write_shadow_ledger(args.output, ledger)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "result": "pass",
                "output": str(args.output),
                "ledger_sha256": ledger["ledger_sha256"],
                "delta": ledger["delta"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
