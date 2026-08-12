from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, InvalidOperation
import hashlib
import json
from typing import Any, Mapping, Sequence
from uuid import UUID, uuid5

from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import OfferCandidateRecord, SourceSnapshot
from app.offer_store import insert_offer_candidate_rows_do_nothing
from app.schemas import OfferCandidate, SourceChain

CONTRACT_VERSION = "lidl-v631-reviewed-semantic-persistence-v1"
SOURCE_PARSER_ID = "lidl-pdf-v08c-r61-shadow-v631"
SNAPSHOT_STRATEGY = "lidl_v631_frozen_semantic"
_SNAPSHOT_NAMESPACE = UUID("b6437dcc-eb35-5c23-97fe-8d813e305a8d")
_APPLY_DECISION = "approve_lidl_v631_one_row_canary_apply"
_APPLY_SCOPE = "exact_one_row_production_db_canary"
_SOURCE_FIELDS = (
    "family", "source_pdf_sha256", "source_raw_sha256", "scan_tree_sha256",
    "review_profile_sha256", "semantic_tree_sha256", "semantic_manifest_sha256",
    "semantic_rows_sha256", "valid_from", "valid_until",
)
_REQUIRED_BINDING = set(_SOURCE_FIELDS) | {
    "schema_version", "reviewed_canary_receipt_sha256", "source_url",
    "source_collected_at", "source_content_bytes", "snapshot_path",
}
_OPTIONAL_BINDING = {"final_url"}
_DECIMAL_FIELDS = {
    "price_eur", "regular_price_eur", "unit_price_eur",
    "regular_unit_price_eur", "example_weight_g", "app_price_eur",
}
_APPLY_PERMISSIONS = {
    "production_database_write": True,
    "max_source_snapshot_writes": 1,
    "max_offer_candidate_writes": 1,
    "review_write": False,
    "production_publish": False,
    "production_deploy": False,
    "corpus_write": False,
    "source_replacement": False,
    "systemd_change": False,
    "scheduler_change": False,
}


class LidlSemanticPersistenceError(ValueError):
    pass


def _jsonable(value: Any) -> Any:
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, Decimal):
        return format(value, "f")
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, Mapping):
        return {str(k): _jsonable(v) for k, v in sorted(value.items(), key=lambda item: str(item[0]))}
    if isinstance(value, (list, tuple)):
        return [_jsonable(v) for v in value]
    return value


def canonical_json_bytes(value: Any) -> bytes:
    return (json.dumps(_jsonable(value), ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _require_sha(value: Any, label: str) -> str:
    text = str(value or "")
    if len(text) != 64 or any(ch not in "0123456789abcdef" for ch in text):
        raise LidlSemanticPersistenceError(f"{label} must be a lowercase SHA-256")
    return text


def _truth(value: Any) -> bool:
    return value is True or str(value or "").strip().casefold() in {"1", "true", "yes", "y"}


def _decimal(value: Any, label: str, *, required: bool = False) -> Decimal | None:
    if value in (None, ""):
        if required:
            raise LidlSemanticPersistenceError(f"{label} is required")
        return None
    try:
        result = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise LidlSemanticPersistenceError(f"{label} is not a decimal") from exc
    if result <= 0:
        raise LidlSemanticPersistenceError(f"{label} must be positive")
    return result


def _date(value: Any, label: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise LidlSemanticPersistenceError(f"{label} must be an ISO date") from exc


def _datetime(value: Any, label: str) -> datetime:
    try:
        result = datetime.fromisoformat(str(value or "").replace("Z", "+00:00"))
    except ValueError as exc:
        raise LidlSemanticPersistenceError(f"{label} must be an ISO datetime") from exc
    if result.tzinfo is None:
        raise LidlSemanticPersistenceError(f"{label} must include a timezone")
    return result


def _load_receipt(raw: bytes, expected_sha: str) -> dict[str, Any]:
    if _sha(raw) != _require_sha(expected_sha, "reviewed_canary_receipt_sha256"):
        raise LidlSemanticPersistenceError("reviewed canary receipt SHA-256 mismatch")
    try:
        receipt = json.loads(raw.decode())
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LidlSemanticPersistenceError("reviewed canary receipt is invalid JSON") from exc
    if not isinstance(receipt, dict) or receipt.get("schema_version") != 1:
        raise LidlSemanticPersistenceError("reviewed canary receipt schema mismatch")
    if receipt.get("kind") != "lidl_one_row_canary_review_receipt" or receipt.get("decision") != "selected_for_write_plan_only":
        raise LidlSemanticPersistenceError("reviewed canary receipt contract mismatch")
    if not isinstance(receipt.get("selected"), dict):
        raise LidlSemanticPersistenceError("reviewed canary receipt selected row is missing")
    for flag in ("production_database_write", "review_write", "production_publish", "production_deploy"):
        if receipt.get(flag) is not False:
            raise LidlSemanticPersistenceError(f"reviewed canary receipt safety mismatch: {flag}")
    return receipt


def _source_binding(binding: Mapping[str, Any], receipt: Mapping[str, Any]) -> dict[str, Any]:
    source = dict(binding)
    missing = sorted(_REQUIRED_BINDING - set(source))
    if missing:
        raise LidlSemanticPersistenceError("source binding missing: " + ",".join(missing))
    extra = sorted(set(source) - _REQUIRED_BINDING - _OPTIONAL_BINDING)
    if extra:
        raise LidlSemanticPersistenceError("source binding has unsupported fields: " + ",".join(extra))
    if source.get("schema_version") != 1:
        raise LidlSemanticPersistenceError("source binding schema mismatch")
    for field in _SOURCE_FIELDS:
        if source.get(field) != receipt.get(field):
            raise LidlSemanticPersistenceError(f"source binding differs from reviewed receipt: {field}")
    for field in (*_SOURCE_FIELDS[1:8], "reviewed_canary_receipt_sha256"):
        _require_sha(source.get(field), field)
    if int(source.get("source_content_bytes") or 0) <= 0:
        raise LidlSemanticPersistenceError("source_content_bytes must be positive")
    if not str(source.get("source_url") or "").startswith(("https://", "http://")):
        raise LidlSemanticPersistenceError("source_url must be absolute HTTP(S)")
    if not str(source.get("snapshot_path") or "").strip():
        raise LidlSemanticPersistenceError("snapshot_path is required")
    if _date(source["valid_until"], "valid_until") < _date(source["valid_from"], "valid_from"):
        raise LidlSemanticPersistenceError("source validity window is inverted")
    _datetime(source["source_collected_at"], "source_collected_at")
    return source


def _pick(row: Mapping[str, Any], *names: str) -> Any:
    return next((row.get(name) for name in names if name in row), None)


def _semantic_row_binding_sha256(row: Mapping[str, Any]) -> str:
    canonical = json.dumps(
        _jsonable(dict(row)),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return _sha(canonical)


def _reviewed_row(rows: Sequence[Mapping[str, Any]], row_binding_sha: str, receipt: Mapping[str, Any]) -> dict[str, Any]:
    if len(rows) != 1:
        raise LidlSemanticPersistenceError("exactly one semantic row is required")
    row = dict(rows[0])
    selected = dict(receipt["selected"])
    supplied_binding = _require_sha(row_binding_sha, "row_binding_sha256")
    reviewed_binding = _require_sha(selected.get("row_binding_sha256"), "reviewed row_binding_sha256")
    if supplied_binding != reviewed_binding:
        raise LidlSemanticPersistenceError("semantic row binding SHA-256 mismatch")
    if _semantic_row_binding_sha256(row) != supplied_binding:
        raise LidlSemanticPersistenceError("semantic row canonical binding SHA-256 mismatch")
    pairs = {
        "semantic_row_key": row.get("semantic_row_key"),
        "page": row.get("page"),
        "title": _pick(row, "product_name", "title"),
        "package_text": _pick(row, "package_text", "package_text_raw"),
        "price_eur": str(row.get("price_eur") or ""),
        "regular_price_eur": str(row.get("regular_price_eur") or ""),
        "pricing_mode": row.get("pricing_mode"),
        "channel": row.get("channel"),
        "weekly_partition": row.get("weekly_partition"),
    }
    for field, actual in pairs.items():
        if actual != selected.get(field):
            raise LidlSemanticPersistenceError(f"semantic row differs from reviewed receipt: {field}")
    bbox = _pick(row, "card_bbox", "bbox")
    if bbox is not None and list(bbox) != list(selected.get("card_bbox") or []):
        raise LidlSemanticPersistenceError("semantic row card bbox differs from reviewed receipt")
    if row.get("weekly_eligibility_state", "production_ready") != "production_ready" or row.get("production_ready_shadow") is not True:
        raise LidlSemanticPersistenceError("semantic row is not production_ready")
    if row.get("pricing_mode") != "fixed_package" or row.get("price_basis") == "variable_weight_example":
        raise LidlSemanticPersistenceError("simple canary path accepts fixed-package rows only")
    if row.get("semantic_gate_reasons") not in (None, [], ()):
        raise LidlSemanticPersistenceError("semantic row still has gate reasons")
    if row.get("app_price_eur") not in (None, "") or selected.get("app_price_present") is not False:
        raise LidlSemanticPersistenceError("simple canary path does not accept app-price rows")
    boundary_flags = ("requires_app", "coupon_required", "coupon_signal", "structured_coupon_signal", "multi_buy_signal", "structured_multi_buy_signal")
    if any(_truth(row.get(key)) for key in boundary_flags) or selected.get("coupon_signal") is not False or selected.get("multi_buy_signal") is not False:
        raise LidlSemanticPersistenceError("simple canary path does not accept app/coupon/multi-buy rows")
    price = _decimal(row.get("price_eur"), "price_eur", required=True)
    regular = _decimal(row.get("regular_price_eur"), "regular_price_eur", required=True)
    if regular is not None and price is not None and regular <= price:
        raise LidlSemanticPersistenceError("regular price must exceed offer price")
    if not str(_pick(row, "product_name", "title") or "").strip() or not str(_pick(row, "package_text", "package_text_raw") or "").strip():
        raise LidlSemanticPersistenceError("semantic row title/package must be non-empty")
    return row


def _snapshot_id(source: Mapping[str, Any]) -> UUID:
    return uuid5(_SNAPSHOT_NAMESPACE, f"{source['family']}:{source['source_raw_sha256']}")


def _source_offer_id(source: Mapping[str, Any], row: Mapping[str, Any]) -> str:
    return f"lidl:v631:{source['family']}:{row['semantic_row_key']}"


def _snapshot_payload(source: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "id": _snapshot_id(source), "source_chain": SourceChain.LIDL.value,
        "source_url": str(source["source_url"]), "final_url": str(source["final_url"]) if source.get("final_url") else None,
        "scope": "gate_b_weekly_physical_deals", "collected_at": _datetime(source["source_collected_at"], "source_collected_at"),
        "http_status": 200, "elapsed_ms": None, "content_type": "application/json",
        "content_bytes": int(source["source_content_bytes"]), "sha256": str(source["source_raw_sha256"]),
        "snapshot_path": str(source["snapshot_path"]), "keyword_hits": {}, "json_ld_blocks": 0,
        "strategy_hint": SNAPSHOT_STRATEGY, "success": True, "error": None,
    }


def _offer(source: Mapping[str, Any], row: Mapping[str, Any], receipt_sha: str, row_binding_sha: str) -> OfferCandidate:
    discount = row.get("discount_percent")
    if discount not in (None, ""):
        try:
            discount = int(discount)
        except (TypeError, ValueError) as exc:
            raise LidlSemanticPersistenceError("discount_percent is not an integer") from exc
    else:
        discount = None
    raw_payload = {
        "persistence_contract_version": CONTRACT_VERSION, "family": source["family"],
        "source_pdf_sha256": source["source_pdf_sha256"], "source_raw_sha256": source["source_raw_sha256"],
        "scan_tree_sha256": source["scan_tree_sha256"], "review_profile_sha256": source["review_profile_sha256"],
        "semantic_tree_sha256": source["semantic_tree_sha256"], "semantic_manifest_sha256": source["semantic_manifest_sha256"],
        "semantic_rows_sha256": source["semantic_rows_sha256"], "reviewed_canary_receipt_sha256": receipt_sha,
        "semantic_row_key": row["semantic_row_key"], "row_binding_sha256": row_binding_sha,
        "reviewed_page": int(row["page"]), "semantic_row": _jsonable(dict(row)),
    }
    payload = {
        "source_chain": SourceChain.LIDL, "source_store_external_id": None, "source_store_name": "Lidl",
        "source_offer_id": _source_offer_id(source, row), "product_name_raw": str(_pick(row, "product_name", "title")),
        "brand_raw": str(_pick(row, "brand", "brand_raw") or "").strip() or None,
        "description_raw": str(_pick(row, "description", "description_raw") or "").strip() or None,
        "package_text_raw": str(_pick(row, "package_text", "package_text_raw")),
        "price_eur": _decimal(row.get("price_eur"), "price_eur", required=True),
        "regular_price_eur": _decimal(row.get("regular_price_eur"), "regular_price_eur", required=True),
        "unit_price_eur": _decimal(row.get("unit_price_eur"), "unit_price_eur"), "unit_label": str(row.get("unit_label") or "").strip() or None,
        "pricing_mode": "fixed_package", "regular_unit_price_eur": _decimal(row.get("regular_unit_price_eur"), "regular_unit_price_eur"),
        "example_weight_g": _decimal(row.get("example_weight_g"), "example_weight_g"), "discount_percent": discount,
        "app_price_eur": None, "requires_app": False, "coupon_required": False,
        "valid_from": _date(source["valid_from"], "valid_from"), "valid_until": _date(source["valid_until"], "valid_until"),
        "app_valid_from": None, "app_valid_until": None, "source_url": str(source["source_url"]),
        "source_image_url": str(row.get("source_image_url")) if row.get("source_image_url") else None,
        "snapshot_id": _snapshot_id(source), "collected_at": _datetime(source["source_collected_at"], "source_collected_at"),
        "parser_version": SOURCE_PARSER_ID, "raw_payload": raw_payload,
    }
    try:
        return OfferCandidate.model_validate(payload)
    except ValidationError as exc:
        raise LidlSemanticPersistenceError(f"mapped OfferCandidate is invalid: {exc}") from exc


def _offer_payload(offer: OfferCandidate) -> dict[str, Any]:
    payload = offer.model_dump(mode="python")
    payload["source_chain"] = offer.source_chain.value
    payload["source_url"] = str(offer.source_url)
    payload["source_image_url"] = str(offer.source_image_url) if offer.source_image_url else None
    return payload


def _same_datetime(left: Any, right: Any) -> bool:
    return left == right or (isinstance(left, datetime) and isinstance(right, datetime) and left.replace(tzinfo=None) == right.replace(tzinfo=None))


def _snapshot_matches(row: SourceSnapshot, expected: Mapping[str, Any]) -> bool:
    return all(_same_datetime(getattr(row, key), value) if key == "collected_at" else getattr(row, key) == value for key, value in expected.items())


def _offer_matches(row: OfferCandidateRecord, expected: Mapping[str, Any]) -> bool:
    for key, right in expected.items():
        if key == "id":
            continue
        left = getattr(row, key)
        if key in _DECIMAL_FIELDS:
            if (left is None) != (right is None) or (left is not None and Decimal(str(left)) != Decimal(str(right))):
                return False
        elif key == "collected_at":
            if not _same_datetime(left, right):
                return False
        elif left != right:
            return False
    return True


def _actions(db: Session, snapshot: Mapping[str, Any], offer_record: Mapping[str, Any]) -> tuple[str, str, list[str]]:
    conflicts: list[str] = []
    snapshot_id = snapshot["id"]
    existing_snapshot = db.get(SourceSnapshot, snapshot_id)
    same_hash = list(db.scalars(select(SourceSnapshot).where(SourceSnapshot.source_chain == "lidl", SourceSnapshot.sha256 == snapshot["sha256"])).all())
    if any(row.id != snapshot_id for row in same_hash):
        conflicts.append("source_raw_sha256_already_bound_to_different_snapshot_id")
    snapshot_action = "CREATE" if existing_snapshot is None else "NO_OP_IDENTICAL" if _snapshot_matches(existing_snapshot, snapshot) else "CONFLICT"
    if snapshot_action == "CONFLICT":
        conflicts.append("deterministic_source_snapshot_payload_conflict")
    existing_offer = db.scalar(select(OfferCandidateRecord).where(OfferCandidateRecord.snapshot_id == snapshot_id, OfferCandidateRecord.source_offer_id == offer_record["source_offer_id"]))
    offer_action = "CREATE" if existing_offer is None else "NO_OP_IDENTICAL" if existing_offer.id == offer_record["id"] and _offer_matches(existing_offer, offer_record) else "CONFLICT"
    if offer_action == "CONFLICT":
        conflicts.append("offer_uniqueness_key_payload_conflict")
    return snapshot_action, offer_action, sorted(set(conflicts))


def build_lidl_v631_semantic_persistence_plan(*, db: Session, reviewed_receipt_bytes: bytes, semantic_rows: Sequence[Mapping[str, Any]], row_binding_sha256: str, source_binding: Mapping[str, Any]) -> dict[str, Any]:
    receipt_sha = _require_sha(source_binding.get("reviewed_canary_receipt_sha256"), "reviewed_canary_receipt_sha256")
    receipt = _load_receipt(reviewed_receipt_bytes, receipt_sha)
    source = _source_binding(source_binding, receipt)
    row = _reviewed_row(semantic_rows, row_binding_sha256, receipt)
    snapshot = _snapshot_payload(source)
    offer = _offer(source, row, receipt_sha, row_binding_sha256)
    offer_payload = _offer_payload(offer)
    offer_record = {"id": uuid5(snapshot["id"], str(offer.source_offer_id)), **offer_payload}
    snapshot_action, offer_action, conflicts = _actions(db, snapshot, offer_record)
    result = "BLOCKED_CONFLICT" if conflicts else "NO_OP_IDENTICAL" if snapshot_action == offer_action == "NO_OP_IDENTICAL" else "READY_TO_CREATE"
    bindings = {
        "family": source["family"], "reviewed_canary_receipt_sha256": receipt_sha,
        "source_binding_sha256": _sha(canonical_json_bytes(source)), "semantic_row_key": row["semantic_row_key"],
        "row_binding_sha256": row_binding_sha256, **{key: source[key] for key in _SOURCE_FIELDS[1:8]},
    }
    payload_material = {
        "contract_version": CONTRACT_VERSION, "bindings": bindings, "source_snapshot": _jsonable(snapshot),
        "offer_candidate": {"id": str(offer_record["id"]), "source_offer_id": offer_record["source_offer_id"], "payload": _jsonable(offer_payload)},
    }
    plan: dict[str, Any] = {
        "schema_version": 1, **payload_material, "payload_fingerprint": _sha(canonical_json_bytes(payload_material)),
        "result": result, "source_snapshot_action": snapshot_action, "offer_candidate_action": offer_action,
        "offer_uniqueness_constraint": "uq_offer_candidates_snapshot_offer", "conflicts": conflicts,
        "expected_deltas": {"first_apply": {"source_snapshots": int(snapshot_action == "CREATE" and not conflicts), "offer_candidates": int(offer_action == "CREATE" and not conflicts)}, "replay": {"source_snapshots": 0, "offer_candidates": 0}},
        "database_write": False, "review_write": False, "production_publish": False, "production_deploy": False,
        "corpus_write": False, "source_replacement": False, "systemd_change": False, "scheduler_change": False,
    }
    plan["plan_fingerprint"] = _sha(canonical_json_bytes(plan))
    return plan


def _authorize_apply(authorization: Mapping[str, Any], plan: Mapping[str, Any]) -> None:
    auth = dict(authorization)
    if auth.get("schema_version") != 1 or auth.get("decision") != _APPLY_DECISION or auth.get("scope") != _APPLY_SCOPE:
        raise LidlSemanticPersistenceError("apply authorization decision/scope mismatch")
    expected = {
        "payload_fingerprint": plan["payload_fingerprint"], "reviewed_canary_receipt_sha256": plan["bindings"]["reviewed_canary_receipt_sha256"],
        "semantic_row_key": plan["bindings"]["semantic_row_key"], "source_offer_id": plan["offer_candidate"]["source_offer_id"],
    }
    if any(auth.get(key) != value for key, value in expected.items()):
        raise LidlSemanticPersistenceError("apply authorization stable binding mismatch")
    if plan["result"] == "READY_TO_CREATE" and auth.get("plan_fingerprint") != plan["plan_fingerprint"]:
        raise LidlSemanticPersistenceError("apply authorization plan_fingerprint mismatch")
    if plan["result"] not in {"READY_TO_CREATE", "NO_OP_IDENTICAL"}:
        raise LidlSemanticPersistenceError("apply authorization cannot target a blocked plan")
    if auth.get("permissions") != _APPLY_PERMISSIONS:
        raise LidlSemanticPersistenceError("apply authorization permissions mismatch")


def _restore_db_types(snapshot: dict[str, Any], offer: dict[str, Any]) -> tuple[dict[str, Any], dict[str, Any]]:
    snapshot = dict(snapshot)
    snapshot["id"] = UUID(str(snapshot["id"]))
    snapshot["collected_at"] = _datetime(snapshot["collected_at"], "collected_at")
    offer = dict(offer)
    offer["snapshot_id"] = UUID(str(offer["snapshot_id"]))
    offer["collected_at"] = _datetime(offer["collected_at"], "collected_at")
    for key in ("valid_from", "valid_until", "app_valid_from", "app_valid_until"):
        if offer.get(key):
            offer[key] = _date(offer[key], key)
    for key in _DECIMAL_FIELDS:
        if offer.get(key) not in (None, ""):
            offer[key] = Decimal(str(offer[key]))
    return snapshot, offer


def apply_lidl_v631_semantic_persistence_plan(*, db: Session, reviewed_receipt_bytes: bytes, semantic_rows: Sequence[Mapping[str, Any]], row_binding_sha256: str, source_binding: Mapping[str, Any], authorization: Mapping[str, Any]) -> dict[str, Any]:
    pre = build_lidl_v631_semantic_persistence_plan(db=db, reviewed_receipt_bytes=reviewed_receipt_bytes, semantic_rows=semantic_rows, row_binding_sha256=row_binding_sha256, source_binding=source_binding)
    _authorize_apply(authorization, pre)
    if pre["result"] == "NO_OP_IDENTICAL":
        return {"schema_version": 1, "result": "APPLY_NO_OP_IDENTICAL", "authorized_plan_fingerprint": authorization["plan_fingerprint"], "payload_fingerprint": pre["payload_fingerprint"], "source_snapshot_writes": 0, "offer_candidate_writes": 0, "replay_writes": 0}
    snapshot, offer = _restore_db_types(pre["source_snapshot"], pre["offer_candidate"]["payload"])
    offer_record = {"id": UUID(str(pre["offer_candidate"]["id"])), **offer}
    snapshot_writes = offer_writes = 0
    try:
        if pre["source_snapshot_action"] == "CREATE":
            db.add(SourceSnapshot(**snapshot)); db.flush(); snapshot_writes = 1
        if pre["offer_candidate_action"] == "CREATE":
            offer_writes = insert_offer_candidate_rows_do_nothing(db, [offer_record])
            if offer_writes != 1:
                raise LidlSemanticPersistenceError("authorized offer insert did not write exactly one row")
        post = build_lidl_v631_semantic_persistence_plan(db=db, reviewed_receipt_bytes=reviewed_receipt_bytes, semantic_rows=semantic_rows, row_binding_sha256=row_binding_sha256, source_binding=source_binding)
        if post["result"] != "NO_OP_IDENTICAL":
            raise LidlSemanticPersistenceError("post-apply replay is not NO_OP_IDENTICAL")
        db.commit()
    except Exception:
        db.rollback(); raise
    return {"schema_version": 1, "result": "APPLY_PASS", "authorized_plan_fingerprint": authorization["plan_fingerprint"], "payload_fingerprint": pre["payload_fingerprint"], "source_snapshot_writes": snapshot_writes, "offer_candidate_writes": offer_writes, "replay_writes": 0, "post_apply_result": "NO_OP_IDENTICAL"}
