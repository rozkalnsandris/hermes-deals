from __future__ import annotations

import hashlib
import json
import unicodedata
from dataclasses import dataclass
from decimal import Decimal
from pathlib import Path
from typing import Any

IDENTITY_WORKFLOW_VERSION = "lidl-corpus-source-id-reconciliation-v1"
IDENTITY_DECISION = (
    "reuse_exact_previous_corpus_ids_and_allocate_semantic_v2_for_new_rows"
)
IMPORT_APPROVAL_WORKFLOW_VERSION = "lidl-controlled-safe-import-approval-v2-read-dedup"
IMPORT_APPROVAL_DECISION = "approve_reconciled_safe_import"
FAMILY_STORE_EXTERNAL_ID = "DE06664"


@dataclass(frozen=True)
class ReconciliationPlan:
    sha256: str
    entries: tuple[dict[str, Any], ...]
    payload: dict[str, Any]


def sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _normalize_text(value: Any) -> str | None:
    text = unicodedata.normalize("NFKC", str(value or ""))
    return " ".join(text.casefold().split()) or None


def _normalize_decimal(value: Any) -> str | None:
    if value in (None, ""):
        return None
    return format(
        Decimal(str(value).replace(",", ".")).quantize(Decimal("0.01")),
        "f",
    )


def semantic_material_from_row(
    row: dict[str, str],
    *,
    store_external_id: str = FAMILY_STORE_EXTERNAL_ID,
) -> dict[str, Any]:
    return {
        "page": int(row["page"]),
        "product_name": _normalize_text(row.get("product_name")),
        "package_text": _normalize_text(row.get("package_text")),
        "price_eur": _normalize_decimal(row.get("price_eur")),
        "regular_price_eur": _normalize_decimal(row.get("regular_price_eur")),
        "app_price_eur": _normalize_decimal(row.get("app_price_eur")),
        "requires_app": bool(str(row.get("app_price_eur") or "").strip()),
        "valid_from": str(row.get("valid_from") or ""),
        "valid_until": str(row.get("valid_until") or ""),
        "source_store_external_id": str(store_external_id),
    }


def semantic_digest(material: dict[str, Any]) -> str:
    encoded = json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _load_exact_json(path: Path, expected_sha256: str) -> tuple[bytes, dict[str, Any]]:
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise ValueError(
            f"JSON SHA mismatch for {path}: expected {expected_sha256}, got {actual}"
        )
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return raw, payload


def load_reconciliation_plan(
    *,
    path: Path,
    expected_sha256: str,
    flyer_key: str,
    scan_name: str,
    parser_version: str,
    parser_sha256: str,
    raw_sha256: str,
    pdf_sha256: str,
    safe_rows: list[dict[str, str]],
) -> ReconciliationPlan:
    _, payload = _load_exact_json(path, expected_sha256)
    expected_top = {
        "schema_version",
        "workflow_version",
        "decision",
        "flyer_key",
        "scan",
        "source",
        "parser_version",
        "parser_sha256",
        "previous_corpus_snapshot",
        "protected_manual_publications",
        "counts",
        "permissions",
        "entries",
    }
    if set(payload) != expected_top:
        raise ValueError("Reconciliation plan field set drift")
    if payload["schema_version"] != 1:
        raise ValueError("Unsupported reconciliation plan schema")
    if payload["workflow_version"] != IDENTITY_WORKFLOW_VERSION:
        raise ValueError("Unexpected reconciliation workflow version")
    if payload["decision"] != IDENTITY_DECISION:
        raise ValueError("Unexpected reconciliation decision")
    if payload["flyer_key"] != flyer_key or payload["scan"] != scan_name:
        raise ValueError("Reconciliation plan flyer or scan mismatch")
    if payload["parser_version"] != parser_version:
        raise ValueError("Reconciliation plan parser version mismatch")
    if payload["parser_sha256"] != parser_sha256:
        raise ValueError("Reconciliation plan parser SHA mismatch")
    if payload["source"] != {
        "raw_sha256": raw_sha256,
        "pdf_sha256": pdf_sha256,
    }:
        raise ValueError("Reconciliation plan source identity mismatch")
    if payload["permissions"] != {
        "db_write": False,
        "review_seed": False,
        "auto_approve": False,
        "auto_publish": False,
        "systemd_change": False,
        "timer_install": False,
    }:
        raise ValueError("Reconciliation identity plan has unsafe permissions")

    counts = payload["counts"]
    if counts != {
        "planned_safe_rows": 204,
        "reused_exact_previous_corpus_ids": 134,
        "new_semantic_v2_ids": 70,
        "identity_collisions": 0,
        "manual_identity_collisions": 0,
    }:
        raise ValueError("Reconciliation plan count contract mismatch")
    if len(safe_rows) != counts["planned_safe_rows"]:
        raise ValueError("Safe row count does not match reconciliation plan")

    protected = payload["protected_manual_publications"]
    protected_ids = protected.get("source_offer_ids")
    if (
        protected.get("database_rows") != 58
        or protected.get("distinct_source_offer_ids") != 54
        or protected.get("revision_rows_collapsed_by_source_offer_id") != 4
        or not isinstance(protected_ids, list)
        or len(protected_ids) != 54
        or len(set(protected_ids)) != 54
    ):
        raise ValueError("Protected manual publication contract mismatch")

    previous = payload["previous_corpus_snapshot"]
    if previous != {
        "snapshot_id": "7fc04436-ad76-58ab-ab73-5bc7f6de7bbf",
        "raw_sha256": "a54d233f9ea5a44bf80655572d0c5d76797cb7fbf07842eeb7aabdacce9218d0",
        "rows": 134,
    }:
        raise ValueError("Previous corpus snapshot contract mismatch")

    entries = payload["entries"]
    if not isinstance(entries, list) or len(entries) != len(safe_rows):
        raise ValueError("Reconciliation plan entries do not match safe rows")
    allowed_entry_fields = {
        "ordinal",
        "source_offer_id",
        "identity_origin",
        "previous_offer_candidate_id",
        "previous_snapshot_id",
        "semantic_digest_sha256",
        "semantic_material",
    }
    source_ids: list[str] = []
    origins: list[str] = []
    for ordinal, (entry, row) in enumerate(zip(entries, safe_rows), start=1):
        if not isinstance(entry, dict) or set(entry) != allowed_entry_fields:
            raise ValueError("Reconciliation plan entry field set drift")
        if entry["ordinal"] != ordinal:
            raise ValueError("Reconciliation plan ordinal mismatch")
        material = semantic_material_from_row(row)
        digest = semantic_digest(material)
        if entry["semantic_material"] != material:
            raise ValueError(f"Reconciliation semantic material mismatch at {ordinal}")
        if entry["semantic_digest_sha256"] != digest:
            raise ValueError(f"Reconciliation semantic digest mismatch at {ordinal}")
        source_id = entry["source_offer_id"]
        if not isinstance(source_id, str) or not source_id or len(source_id) > 255:
            raise ValueError("Invalid reconciled source_offer_id")
        origin = entry["identity_origin"]
        if origin == "new_semantic_v2_identity":
            expected_id = f"lidl:flyer:{flyer_key}:semantic-v2:{digest[:24]}"
            if source_id != expected_id:
                raise ValueError("New semantic-v2 source_offer_id mismatch")
            if entry["previous_offer_candidate_id"] is not None:
                raise ValueError("New semantic identity references previous offer")
            if entry["previous_snapshot_id"] is not None:
                raise ValueError("New semantic identity references previous snapshot")
        elif origin == "reused_exact_previous_corpus_identity":
            if not source_id.startswith(f"lidl:corpus:{flyer_key}:"):
                raise ValueError("Reused corpus source_offer_id prefix mismatch")
            if not entry["previous_offer_candidate_id"]:
                raise ValueError("Reused identity lacks previous offer candidate")
            if entry["previous_snapshot_id"] != previous["snapshot_id"]:
                raise ValueError("Reused identity previous snapshot mismatch")
        else:
            raise ValueError("Unknown reconciliation identity origin")
        source_ids.append(source_id)
        origins.append(origin)

    if len(set(source_ids)) != len(source_ids):
        raise ValueError("Reconciled source_offer_id collision")
    if set(source_ids) & set(protected_ids):
        raise ValueError("Reconciled source IDs collide with manual publications")
    if origins.count("reused_exact_previous_corpus_identity") != 134:
        raise ValueError("Reused identity count mismatch")
    if origins.count("new_semantic_v2_identity") != 70:
        raise ValueError("New semantic identity count mismatch")

    return ReconciliationPlan(
        sha256=expected_sha256,
        entries=tuple(entries),
        payload=payload,
    )


def validate_import_approval(
    *,
    path: Path,
    expected_sha256: str,
    flyer_key: str,
    scan_name: str,
    raw_sha256: str,
    pdf_sha256: str,
    identity_plan_sha256: str,
) -> dict[str, Any]:
    _, payload = _load_exact_json(path, expected_sha256)
    expected_top = {
        "schema_version",
        "workflow_version",
        "decision",
        "flyer_key",
        "scan",
        "source",
        "identity_plan_sha256",
        "counts",
        "permissions",
    }
    if set(payload) != expected_top:
        raise ValueError("Safe import approval field set drift")
    if payload["schema_version"] != 1:
        raise ValueError("Unsupported safe import approval schema")
    if payload["workflow_version"] != IMPORT_APPROVAL_WORKFLOW_VERSION:
        raise ValueError("Unexpected safe import approval workflow")
    if payload["decision"] != IMPORT_APPROVAL_DECISION:
        raise ValueError("Safe import is not approved")
    if payload["flyer_key"] != flyer_key or payload["scan"] != scan_name:
        raise ValueError("Safe import approval flyer or scan mismatch")
    if payload["source"] != {
        "raw_sha256": raw_sha256,
        "pdf_sha256": pdf_sha256,
    }:
        raise ValueError("Safe import approval source identity mismatch")
    if payload["identity_plan_sha256"] != identity_plan_sha256:
        raise ValueError("Safe import approval identity-plan SHA mismatch")
    if payload["counts"] != {
        "new_source_snapshots": 1,
        "safe_offer_candidates": 204,
        "reused_previous_source_offer_ids": 134,
        "new_semantic_v2_source_offer_ids": 70,
        "protected_manual_database_rows": 58,
        "protected_manual_distinct_source_offer_ids": 54,
        "database_target_distinct_source_offer_ids": 258,

        "expected_visible_target_flyer_rows": 257,

        "completeness_rescue_precedence_suppressions": 1,
    }:
        raise ValueError("Safe import approval count contract mismatch")
    if payload["permissions"] != {
        "db_write": True,
        "source_snapshot_write": True,
        "offer_candidate_write": True,
        "delete_existing_rows": False,
        "update_existing_rows": False,
        "review_seed": False,
        "auto_approve": False,
        "auto_publish": False,
        "systemd_change": False,
        "timer_install": False,
    }:
        raise ValueError("Safe import approval permissions mismatch")
    return payload
