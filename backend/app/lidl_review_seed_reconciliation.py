from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

REVIEW_SEED_WORKFLOW_VERSION = "lidl-reconciled-review-seed-plan-v1"
REVIEW_SEED_DECISION = "ready_for_controlled_filtered_review_seed"


@dataclass(frozen=True)
class ReviewSeedPlan:
    sha256: str
    entries: tuple[dict[str, Any], ...]
    payload: dict[str, Any]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def canonical_row_material(row: dict[str, Any]) -> str:
    return json.dumps(
        {key: row.get(key, "") for key in sorted(row)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def row_digest(row: dict[str, Any]) -> str:
    return hashlib.sha256(canonical_row_material(row).encode("utf-8")).hexdigest()


def source_row_key(scan_name: str, ordinal: int, row: dict[str, Any]) -> str:
    return f"{scan_name}:row{ordinal:03d}:{row_digest(row)[:12]}"


def _none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _decimal_text(value: Any) -> str | None:
    text = _none(value)
    if text is None:
        return None
    return format(
        Decimal(text.replace(",", ".")).quantize(Decimal("0.01")),
        "f",
    )


def review_entry_from_row(
    *,
    scan_name: str,
    ordinal: int,
    row: dict[str, str],
) -> dict[str, Any]:
    return {
        "review_row_ordinal": ordinal,
        "source_row_key": source_row_key(scan_name, ordinal, row),
        "row_digest_sha256": row_digest(row),
        "page": int(row["page"]),
        "product_name": str(row.get("product_name") or ""),
        "package_text": _none(row.get("package_text")),
        "price_eur": _decimal_text(row.get("price_eur")),
        "regular_price_eur": _decimal_text(row.get("regular_price_eur")),
        "app_price_eur": _decimal_text(row.get("app_price_eur")),
        "valid_from": str(row.get("valid_from") or ""),
        "valid_until": str(row.get("valid_until") or ""),
        "scope": str(row.get("scope") or ""),
        "channel": str(row.get("channel") or ""),
        "price_basis": str(row.get("price_basis") or ""),
        "reason_codes": ["scope_requires_review"],
    }


def _load_exact_json(path: Path, expected_sha256: str) -> dict[str, Any]:
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise ValueError(
            f"Review seed plan SHA mismatch: expected {expected_sha256}, got {actual}"
        )
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Review seed plan root must be an object")
    return payload


def load_review_seed_plan(
    *,
    path: Path,
    expected_sha256: str,
    flyer_key: str,
    scan_name: str,
    raw_sha256: str,
    pdf_sha256: str,
    snapshot_id: str,
    review_rows: list[dict[str, str]],
) -> ReviewSeedPlan:
    payload = _load_exact_json(path, expected_sha256)
    expected_top = {
        "schema_version",
        "workflow_version",
        "decision",
        "flyer_key",
        "scan",
        "source",
        "counts",
        "permissions",
        "entries",
    }
    if set(payload) != expected_top:
        raise ValueError("Review seed plan field set drift")
    if payload["schema_version"] != 1:
        raise ValueError("Unsupported review seed plan schema")
    if payload["workflow_version"] != REVIEW_SEED_WORKFLOW_VERSION:
        raise ValueError("Unexpected review seed workflow version")
    if payload["decision"] != REVIEW_SEED_DECISION:
        raise ValueError("Review seed is not approved")
    if payload["flyer_key"] != flyer_key or payload["scan"] != scan_name:
        raise ValueError("Review seed plan flyer or scan mismatch")
    if payload["source"] != {
        "raw_sha256": raw_sha256,
        "pdf_sha256": pdf_sha256,
        "snapshot_id": snapshot_id,
    }:
        raise ValueError("Review seed plan source identity mismatch")
    if payload["counts"] != {
        "authoritative_review_rows": 148,
        "scope_excluded_rows": 44,
        "review_seed_candidates_before_reconciliation": 104,
        "suppressed_existing_approved_rows": 47,
        "new_review_items": 57,
        "new_variable_weight_rows": 0,
    }:
        raise ValueError("Review seed plan count contract mismatch")
    if payload["permissions"] != {
        "review_seed": True,
        "offer_candidate_write": False,
        "auto_approve": False,
        "auto_publish": False,
        "delete_existing_rows": False,
        "update_existing_rows": False,
        "systemd_change": False,
        "timer_install": False,
    }:
        raise ValueError("Review seed plan permissions mismatch")
    if len(review_rows) != 148:
        raise ValueError("Authoritative review row count mismatch")

    excluded_ordinals = {
        ordinal
        for ordinal, row in enumerate(review_rows, start=1)
        if row.get("scope") == "excluded"
    }
    eligible_ordinals = {
        ordinal
        for ordinal, row in enumerate(review_rows, start=1)
        if row.get("scope") in {"review", "in_scope"}
    }
    if len(excluded_ordinals) != 44 or len(eligible_ordinals) != 104:
        raise ValueError("Authoritative review scope partition mismatch")
    if excluded_ordinals | eligible_ordinals != set(range(1, 149)):
        raise ValueError("Authoritative review scope partition is incomplete")
    if any(row.get("channel") != "physical_store" for row in review_rows):
        raise ValueError("Review seed plan contains non-physical row")

    entries = payload["entries"]
    if not isinstance(entries, list) or len(entries) != 57:
        raise ValueError("Review seed plan entry count mismatch")
    allowed_fields = {
        "review_row_ordinal",
        "source_row_key",
        "row_digest_sha256",
        "page",
        "product_name",
        "package_text",
        "price_eur",
        "regular_price_eur",
        "app_price_eur",
        "valid_from",
        "valid_until",
        "scope",
        "channel",
        "price_basis",
        "reason_codes",
    }
    ordinals: list[int] = []
    keys: list[str] = []
    for entry in entries:
        if not isinstance(entry, dict) or set(entry) != allowed_fields:
            raise ValueError("Review seed plan entry field set drift")
        ordinal = entry["review_row_ordinal"]
        if not isinstance(ordinal, int) or ordinal not in eligible_ordinals:
            raise ValueError("Review seed plan ordinal is not eligible")
        row = review_rows[ordinal - 1]
        expected = review_entry_from_row(
            scan_name=scan_name,
            ordinal=ordinal,
            row=row,
        )
        if entry != expected:
            raise ValueError(f"Review seed row drift at ordinal {ordinal}")
        if entry["scope"] != "review":
            raise ValueError("Filtered review seed rows must stay scope=review")
        if entry["price_basis"] != "fixed_or_explicit":
            raise ValueError("Filtered review seed rows must have fixed pricing")
        if entry["reason_codes"] != ["scope_requires_review"]:
            raise ValueError("Filtered review seed reason contract mismatch")
        ordinals.append(ordinal)
        keys.append(entry["source_row_key"])

    if len(set(ordinals)) != 57 or len(set(keys)) != 57:
        raise ValueError("Review seed plan contains duplicate identities")
    omitted_eligible = eligible_ordinals - set(ordinals)
    if len(omitted_eligible) != 47:
        raise ValueError("Review seed suppressed-row count mismatch")
    if any(
        review_rows[ordinal - 1].get("price_basis") == "variable_weight_example"
        for ordinal in ordinals
    ):
        raise ValueError("Variable-weight rows cannot enter filtered review seed")

    return ReviewSeedPlan(
        sha256=expected_sha256,
        entries=tuple(entries),
        payload=payload,
    )
