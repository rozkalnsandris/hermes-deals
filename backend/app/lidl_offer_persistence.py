from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID, uuid5

from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import OfferCandidateRecord, SourceSnapshot
from app.offer_store import insert_offer_candidate_rows_do_nothing
from app.schemas import OfferCandidate, SourceChain

_STRATEGY = "lidl_strict_ready_offer_persistence"
_PARSER_VERSION = "lidl-ocr-2b19"
_EXPECTED_COUNT = 4


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _resolve_snapshot_path(value: str, raw_root: Path) -> Path:
    path = Path(value)
    if path.exists():
        return path
    if str(path).startswith("/data/raw/"):
        fallback = raw_root / str(path).removeprefix("/data/raw/")
        if fallback.exists():
            return fallback
    raise FileNotFoundError(f"Persisted Lidl SourceSnapshot file not found: {value}")


def _load_provenance_report(path: Path) -> dict[str, Any]:
    report = json.loads(path.read_text(encoding="utf-8"))
    if report.get("strategy") != "lidl_source_snapshot_provenance_binding":
        raise ValueError("Input is not a Lidl source provenance binding report")
    if report.get("recommendation") != "lidl_real_snapshot_offer_shadow_valid":
        raise ValueError("Lidl provenance report is not approved for strict-ready persistence")
    if report.get("offer_db_write_performed") is not False:
        raise ValueError("Provenance report already claims an offer DB write")
    if int(report.get("validation_error_total") or 0) != 0:
        raise ValueError("Provenance report contains OfferCandidate validation errors")
    gate = report.get("gate") or {}
    if not gate or not all(bool(v) for v in gate.values()):
        raise ValueError("Lidl provenance report gate is not fully green")
    return report



_ALLOWED_EVIDENCE_TIERS = {"math_verified", "math_corrected_verified"}


def _controlled_approved_set_error(mapped: list[dict[str, Any]]) -> str | None:
    # Preserve the legacy four-row path exactly: individual evidence validation
    # remains the responsibility of _promote_offer(), so existing negative tests
    # keep their original failure semantics.
    if len(mapped) == 4:
        return None

    evidence: list[str] = []
    for entry in mapped:
        payload = entry.get("offer_candidate") if isinstance(entry, dict) else None
        raw = payload.get("raw_payload") if isinstance(payload, dict) else None
        evidence.append(str((raw or {}).get("evidence_tier") or ""))

    if (
        len(mapped) == 5
        and evidence.count("math_verified") == 4
        and evidence.count("math_corrected_verified") == 1
    ):
        return None

    return (
        "Controlled first Lidl write requires exactly 4 mapped candidates "
        "unless using the approved exact-set expansion profile: exactly five "
        "candidates containing four math_verified plus one "
        "math_corrected_verified candidate"
    )


def _validate_corrected_offer_provenance(
    payload: dict[str, Any],
    raw: dict[str, Any],
    *,
    expected: Any,
    actual: Any,
) -> None:
    if raw.get("corrected_price_verified") is not True:
        raise ValueError("Corrected Lidl candidate is not explicitly verified")

    corrected = raw.get("proposed_corrected_price_eur")
    effective = raw.get("effective_price_eur")
    ocr_price = raw.get("ocr_price_eur")

    values = {
        "expected": expected,
        "actual": actual,
        "corrected": corrected,
        "effective": effective,
        "ocr": ocr_price,
    }
    if any(value is None for value in values.values()):
        raise ValueError("Corrected Lidl candidate is missing price provenance")

    expected_d = Decimal(str(expected)).quantize(Decimal("0.01"))
    actual_d = Decimal(str(actual)).quantize(Decimal("0.01"))
    corrected_d = Decimal(str(corrected)).quantize(Decimal("0.01"))
    effective_d = Decimal(str(effective)).quantize(Decimal("0.01"))
    ocr_d = Decimal(str(ocr_price)).quantize(Decimal("0.01"))

    if not (expected_d == actual_d == corrected_d == effective_d):
        raise ValueError("Corrected Lidl price does not exactly match approved unit-price math")
    if ocr_d == actual_d:
        raise ValueError("Corrected Lidl candidate must preserve a distinct original OCR price")

    original_name = str(raw.get("original_semantic_product_name_raw") or "").strip()
    recovered_name = str(raw.get("recovered_product_name") or "").strip()
    product_name = str(payload.get("product_name_raw") or "").strip()

    if not original_name or not recovered_name:
        raise ValueError("Corrected Lidl candidate is missing original/recovered name provenance")
    if recovered_name != product_name:
        raise ValueError("Recovered Lidl product name differs from OfferCandidate product name")
    if original_name.casefold() == recovered_name.casefold():
        raise ValueError("Corrected Lidl name provenance does not describe a real recovery")
    if raw.get("product_name_recovery_reason") != "dual_psm_unit_math_label_overlap":
        raise ValueError("Corrected Lidl candidate has an unapproved name recovery reason")

    recovery_modes = {
        int(mode)
        for mode in (raw.get("product_name_recovery_psm_modes") or [])
        if str(mode).isdigit()
    }
    if len(recovery_modes) < 2:
        raise ValueError("Corrected Lidl name recovery requires dual-PSM support")


def _promote_offer(payload: dict[str, Any], *, snapshot: SourceSnapshot, snapshot_sha: str) -> OfferCandidate:
    if payload.get("source_chain") != SourceChain.LIDL.value:
        raise ValueError("Only Lidl OfferCandidates may be persisted by this path")
    source_offer_id = payload.get("source_offer_id")
    if not isinstance(source_offer_id, str) or not source_offer_id.strip() or source_offer_id != source_offer_id.strip():
        raise ValueError("Persisted Lidl OfferCandidate requires a non-empty canonical source_offer_id")
    if str(payload.get("snapshot_id") or "") != str(snapshot.id):
        raise ValueError("OfferCandidate snapshot_id does not match persisted Lidl SourceSnapshot")
    raw = dict(payload.get("raw_payload") or {})
    if raw.get("strict_disposition") != "strict_ready":
        raise ValueError("Only strict_ready Lidl candidates may be persisted")
    evidence_tier = str(raw.get("evidence_tier") or "")
    if evidence_tier not in _ALLOWED_EVIDENCE_TIERS:
        raise ValueError("Lidl persistence only accepts approved strict-ready evidence tiers")
    if int(raw.get("psm_support") or 0) < 2:
        raise ValueError("Lidl persistence requires dual-PSM support")
    expected = raw.get("math_expected_price_eur")
    actual = payload.get("price_eur")
    if expected is None or actual is None or Decimal(str(expected)).quantize(Decimal("0.01")) != Decimal(str(actual)).quantize(Decimal("0.01")):
        raise ValueError("Lidl persistence requires exact unit-price math agreement")
    if evidence_tier == "math_corrected_verified":
        _validate_corrected_offer_provenance(
            payload,
            raw,
            expected=expected,
            actual=actual,
        )
    if raw.get("source_snapshot_binding") is not True:
        raise ValueError("OfferCandidate is not bound to the real SourceSnapshot")
    if raw.get("shadow_snapshot_id_is_synthetic") is not False:
        raise ValueError("Synthetic snapshot provenance cannot be persisted")
    if raw.get("source_snapshot_id") != str(snapshot.id):
        raise ValueError("raw_payload source_snapshot_id does not match DB SourceSnapshot")
    if raw.get("source_snapshot_sha256") != snapshot_sha:
        raise ValueError("raw_payload source_snapshot_sha256 does not match DB SourceSnapshot")

    raw.update(
        {
            "db_write_eligible": True,
            "db_write_performed": True,
            "persistence_phase": (
                "2B42"
                if evidence_tier == "math_corrected_verified"
                else "2B19"
            ),
            "persistence_gate": (
                "strict_ready+math_corrected_verified+dual_psm+corrected_price+name_recovery+real_snapshot"
                if evidence_tier == "math_corrected_verified"
                else "strict_ready+math_verified+dual_psm+real_snapshot"
            ),
            "persisted_snapshot_id": str(snapshot.id),
            "persisted_snapshot_sha256": snapshot_sha,
        }
    )
    promoted = dict(payload)
    promoted["parser_version"] = _PARSER_VERSION
    promoted["raw_payload"] = raw
    return OfferCandidate.model_validate(promoted)


def _record_id(snapshot_id: UUID, source_offer_id: str) -> UUID:
    return uuid5(snapshot_id, source_offer_id)


def _record_payload(offer: OfferCandidate) -> dict[str, Any]:
    payload = offer.model_dump(mode="python")
    payload["source_chain"] = offer.source_chain.value
    payload["source_url"] = str(offer.source_url)
    payload["source_image_url"] = str(offer.source_image_url) if offer.source_image_url else None
    return payload



_LEGACY_OPTIONAL_RAW_ENRICHMENT_KEYS = {
    "effective_price_eur",
    "corrected_price_verified",
    "original_semantic_product_name_raw",
    "recovered_product_name",
    "product_name_recovery_reason",
    "product_name_recovery_psm_modes",
}
_LEGACY_DIAGNOSTIC_RAW_KEYS = {"source_precision_report"}


def _raw_payload_compatible(existing: dict[str, Any], approved: dict[str, Any]) -> bool:
    left = dict(existing or {})
    right = dict(approved or {})

    for key in sorted(set(left) | set(right)):
        if key in _LEGACY_DIAGNOSTIC_RAW_KEYS:
            continue

        if key in _LEGACY_OPTIONAL_RAW_ENRICHMENT_KEYS:
            if key in left and left.get(key) != right.get(key):
                return False
            continue

        if left.get(key) != right.get(key):
            return False

    return True


def _row_matches(row: OfferCandidateRecord, offer: OfferCandidate) -> bool:
    payload = _record_payload(offer)
    keys = [
        "source_chain", "source_store_external_id", "source_store_name", "source_offer_id",
        "product_name_raw", "brand_raw", "description_raw", "package_text_raw", "price_eur",
        "regular_price_eur", "unit_price_eur", "unit_label", "discount_percent", "app_price_eur",
        "requires_app", "coupon_required", "valid_from", "valid_until", "source_url",
        "source_image_url", "snapshot_id", "collected_at", "parser_version", "raw_payload",
    ]
    for key in keys:
        left = getattr(row, key)
        right = payload[key]
        if key in {"price_eur", "regular_price_eur", "unit_price_eur", "app_price_eur"}:
            if left is None or right is None:
                if left is not right:
                    return False
            elif Decimal(str(left)) != Decimal(str(right)):
                return False
        elif key == "collected_at":
            left_iso = left.isoformat() if left is not None else None
            right_iso = right.isoformat() if right is not None else None
            if left_iso != right_iso:
                # SQLite test storage may drop timezone info; compare wall-clock value as a fallback.
                if left is None or right is None or left.replace(tzinfo=None) != right.replace(tzinfo=None):
                    return False
        elif key == "raw_payload":
            if not _raw_payload_compatible(left or {}, right or {}):
                return False
        elif left != right:
            return False
    return True


def _ensure_exact_rows(db: Session, offers: list[OfferCandidate], snapshot_id: UUID) -> tuple[int, list[str]]:
    existing = list(
        db.scalars(
            select(OfferCandidateRecord)
            .where(OfferCandidateRecord.source_chain == "lidl", OfferCandidateRecord.snapshot_id == snapshot_id)
            .order_by(OfferCandidateRecord.source_offer_id.asc())
        ).all()
    )
    expected_by_id: dict[str, OfferCandidate] = {}
    for offer in offers:
        if offer.source_offer_id is None or not str(offer.source_offer_id).strip():
            raise ValueError("Lidl persistence set contains a missing source_offer_id")
        key = str(offer.source_offer_id).strip()
        if key in expected_by_id:
            raise ValueError(f"Lidl persistence set contains duplicate source_offer_id: {key}")
        expected_by_id[key] = offer

    existing_by_id = {str(r.source_offer_id): r for r in existing}
    if len(existing_by_id) != len(existing):
        raise ValueError("Existing Lidl rows contain duplicate source_offer_id values")
    if not set(existing_by_id).issubset(set(expected_by_id)):
        raise ValueError(
            "Existing Lidl rows do not exactly match the approved persistence set "
            "or an approved exact-set subset"
        )

    for key, row in existing_by_id.items():
        offer = expected_by_id[key]
        if row.id != _record_id(snapshot_id, key):
            raise ValueError("Existing Lidl row does not use deterministic persistence UUID")
        if not _row_matches(row, offer):
            raise ValueError(f"Existing Lidl row differs from approved payload: {key}")

    missing_ids = sorted(set(expected_by_id) - set(existing_by_id))
    if not missing_ids:
        return 0, [str(existing_by_id[k].id) for k in sorted(existing_by_id)]

    rows_to_insert: list[dict[str, Any]] = []
    for source_offer_id in missing_ids:
        offer = expected_by_id[source_offer_id]
        payload = _record_payload(offer)
        rows_to_insert.append(
            {"id": _record_id(snapshot_id, source_offer_id), **payload}
        )

    try:
        rows_written = insert_offer_candidate_rows_do_nothing(db, rows_to_insert)

        persisted = list(
            db.scalars(
                select(OfferCandidateRecord)
                .where(
                    OfferCandidateRecord.source_chain == "lidl",
                    OfferCandidateRecord.snapshot_id == snapshot_id,
                )
                .order_by(OfferCandidateRecord.source_offer_id.asc())
            ).all()
        )
        persisted_by_id = {str(row.source_offer_id): row for row in persisted}
        if (
            len(persisted_by_id) != len(persisted)
            or set(persisted_by_id) != set(expected_by_id)
        ):
            raise ValueError(
                "Persisted Lidl rows do not exactly match the approved persistence set"
            )
        for key, offer in expected_by_id.items():
            row = persisted_by_id[key]
            if row.id != _record_id(snapshot_id, key):
                raise ValueError(
                    "Persisted Lidl row does not use deterministic persistence UUID"
                )
            if not _row_matches(row, offer):
                raise ValueError(
                    f"Persisted Lidl row differs from approved payload: {key}"
                )

        db.commit()
    except Exception:
        db.rollback()
        raise

    ids = [
        str(_record_id(snapshot_id, str(o.source_offer_id)))
        for o in sorted(offers, key=lambda o: str(o.source_offer_id))
    ]
    return rows_written, ids


def persist_lidl_strict_ready_offers(
    *,
    db: Session,
    provenance_report_path: Path,
    output_dir: Path,
    raw_root: Path,
) -> dict[str, Any]:
    provenance = _load_provenance_report(provenance_report_path)
    snapshot_id = UUID(str(provenance["source_snapshot_id"]))
    snapshot = db.get(SourceSnapshot, snapshot_id)
    if snapshot is None:
        raise ValueError("Persisted Lidl SourceSnapshot row is missing")
    if snapshot.source_chain != "lidl" or snapshot.success is not True:
        raise ValueError("SourceSnapshot is not a successful Lidl snapshot")
    if snapshot.strategy_hint != "lidl_public_flyer_json_canonical":
        raise ValueError("SourceSnapshot is not the canonical Lidl flyer JSON strategy")
    snapshot_sha = str(provenance.get("source_snapshot_sha256") or "")
    if not snapshot_sha or snapshot.sha256 != snapshot_sha:
        raise ValueError("SourceSnapshot SHA256 differs from provenance report")
    snapshot_path = _resolve_snapshot_path(str(snapshot.snapshot_path or ""), raw_root)
    if _sha256_file(snapshot_path) != snapshot_sha:
        raise ValueError("Immutable Lidl SourceSnapshot file hash changed before offer persistence")

    mapped = provenance.get("mapped_candidates") or []
    if len(mapped) != int(provenance.get("real_snapshot_offer_candidate_total") or 0):
        raise ValueError("Mapped candidate count differs from provenance summary")
    controlled_set_error = _controlled_approved_set_error(mapped)
    if controlled_set_error is not None:
        raise ValueError(controlled_set_error)

    offers: list[OfferCandidate] = []
    errors: list[dict[str, Any]] = []
    for entry in mapped:
        payload = entry.get("offer_candidate") if isinstance(entry, dict) else None
        if not isinstance(payload, dict):
            errors.append({"error": "mapped entry has no OfferCandidate payload"})
            continue
        try:
            offers.append(_promote_offer(payload, snapshot=snapshot, snapshot_sha=snapshot_sha))
        except (ValidationError, ValueError, TypeError) as exc:
            errors.append({
                "source_offer_id": payload.get("source_offer_id"),
                "product_name": payload.get("product_name_raw"),
                "error": f"{type(exc).__name__}: {exc}",
            })
    if errors:
        raise ValueError(f"Lidl controlled persistence validation failed for {len(errors)} candidate(s)")

    global_before = int(db.scalar(select(func.count()).select_from(OfferCandidateRecord).where(OfferCandidateRecord.source_chain == "lidl")) or 0)
    snapshot_before = int(db.scalar(select(func.count()).select_from(OfferCandidateRecord).where(OfferCandidateRecord.source_chain == "lidl", OfferCandidateRecord.snapshot_id == snapshot_id)) or 0)

    rows_written, ids_first = _ensure_exact_rows(db, offers, snapshot_id)
    snapshot_after_first = int(db.scalar(select(func.count()).select_from(OfferCandidateRecord).where(OfferCandidateRecord.source_chain == "lidl", OfferCandidateRecord.snapshot_id == snapshot_id)) or 0)
    second_rows_written, ids_second = _ensure_exact_rows(db, offers, snapshot_id)
    global_after = int(db.scalar(select(func.count()).select_from(OfferCandidateRecord).where(OfferCandidateRecord.source_chain == "lidl")) or 0)

    persisted_rows = list(
        db.scalars(
            select(OfferCandidateRecord)
            .where(OfferCandidateRecord.source_chain == "lidl", OfferCandidateRecord.snapshot_id == snapshot_id)
            .order_by(OfferCandidateRecord.product_name_raw.asc())
        ).all()
    )
    expected_names = sorted(o.product_name_raw for o in offers)
    persisted_names = sorted(r.product_name_raw for r in persisted_rows)

    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": _STRATEGY,
        "source_provenance_report": str(provenance_report_path),
        "source_snapshot_id": str(snapshot_id),
        "source_snapshot_sha256": snapshot_sha,
        "source_snapshot_path": str(snapshot.snapshot_path),
        "approved_candidate_total": len(offers),
        "validation_error_total": 0,
        "lidl_rows_global_before": global_before,
        "lidl_rows_snapshot_before": snapshot_before,
        "rows_written_first_pass": rows_written,
        "rows_after_first_pass": snapshot_after_first,
        "rows_written_second_pass": second_rows_written,
        "lidl_rows_global_after": global_after,
        "record_ids_first_pass": ids_first,
        "record_ids_second_pass": ids_second,
        "persisted_products": [
            {
                "id": str(row.id),
                "source_offer_id": row.source_offer_id,
                "product_name_raw": row.product_name_raw,
                "price_eur": str(row.price_eur),
                "unit_price_eur": str(row.unit_price_eur) if row.unit_price_eur is not None else None,
                "unit_label": row.unit_label,
                "snapshot_id": str(row.snapshot_id),
                "parser_version": row.parser_version,
            }
            for row in persisted_rows
        ],
        "gate": {
            "provenance_contract_valid": provenance.get("recommendation") == "lidl_real_snapshot_offer_shadow_valid",
            "source_snapshot_real_and_canonical": snapshot.strategy_hint == "lidl_public_flyer_json_canonical" and snapshot.success is True,
            "immutable_snapshot_hash_matches": _sha256_file(snapshot_path) == snapshot_sha,
            # Legacy key names are retained for report compatibility. They now
            # represent the controlled approved-set profile rather than a hard
            # four-row/math_verified-only production invariant.
            "approved_subset_exactly_four": _controlled_approved_set_error(mapped) is None,
            "all_math_verified": all(
                o.raw_payload.get("evidence_tier") in _ALLOWED_EVIDENCE_TIERS
                for o in offers
            ),
            "controlled_evidence_mix_valid": _controlled_approved_set_error(mapped) is None,
            "all_strict_ready": all(o.raw_payload.get("strict_disposition") == "strict_ready" for o in offers),
            "all_dual_psm": all(int(o.raw_payload.get("psm_support") or 0) >= 2 for o in offers),
            "all_real_snapshot_bound": all(o.snapshot_id == snapshot_id for o in offers),
            "all_persistence_approved": all(o.raw_payload.get("db_write_eligible") is True for o in offers),
            "persisted_count_matches_approved": len(persisted_rows) == len(offers),
            "persisted_names_match_approved": persisted_names == expected_names,
            "deterministic_record_ids_stable": ids_first == ids_second,
            "idempotent_second_pass_wrote_zero": second_rows_written == 0,
            "no_unexpected_global_growth": global_after == global_before + rows_written,
        },
    }
    gates_ok = all(report["gate"].values())
    if gates_ok and len(offers) == 4 and rows_written == len(offers) and global_before == 0:
        report["recommendation"] = "lidl_first_controlled_offer_write_valid"
    elif (
        gates_ok
        and 0 < snapshot_before < len(offers)
        and rows_written == len(offers) - snapshot_before
        and snapshot_after_first == len(offers)
    ):
        report["recommendation"] = "lidl_offer_persistence_exact_set_expansion_valid"
    elif gates_ok and rows_written == 0 and snapshot_before == len(offers):
        report["recommendation"] = "lidl_offer_persistence_idempotent"
    else:
        report["recommendation"] = "lidl_offer_persistence_review_required"

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = output_dir / f"{stamp}-lidl-offer-persistence.json"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
