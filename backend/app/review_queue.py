from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    OfferCandidateRecord,
    OfferReviewItem,
    OfferReviewRevision,
    SourceSnapshot,
)
from app.offer_store import save_offer_candidates
from app.schemas import OfferCandidate, SourceChain


EDITABLE_FIELDS = {
    "product_name",
    "brand",
    "package_text",
    "price_eur",
    "regular_price_eur",
    "unit_price_eur",
    "unit_label",
    "pricing_mode",
    "regular_unit_price_eur",
    "example_weight_g",
    "discount_percent",
    "app_price_eur",
    "requires_app",
    "coupon_required",
    "valid_from",
    "valid_until",
    "app_valid_from",
    "app_valid_until",
    "scope",
    "channel",
    "source_store_external_id",
    "source_store_name",
    "source_image_url",
}
OPEN_STATES = {"pending", "draft", "needs_followup"}


class ReviewDraftRequest(BaseModel):
    corrections: dict[str, Any] = Field(default_factory=dict)
    note: str | None = Field(default=None, max_length=2000)
    needs_followup: bool = False


class ReviewDecisionRequest(BaseModel):
    note: str | None = Field(default=None, max_length=2000)


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _review_id(source_chain: str, flyer_key: str, row_key: str) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"hermes-deals:offer-review:{source_chain}:{flyer_key}:{row_key}",
    )


def _manual_snapshot_id(review_id: UUID) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"hermes-deals:manual-review-snapshot:{review_id}",
    )


def _source_offer_id(item: OfferReviewItem) -> str:
    stable = sha256(
        f"{item.source_chain}|{item.source_flyer_key}|{item.source_row_key}".encode()
    ).hexdigest()[:32]
    return f"manual-review-{stable}"


def _next_revision_no(db: Session, item_id: UUID) -> int:
    current = db.scalar(
        select(func.max(OfferReviewRevision.revision_no)).where(
            OfferReviewRevision.review_item_id == item_id
        )
    )
    return int(current or 0) + 1


def _revision(
    db: Session,
    item: OfferReviewItem,
    *,
    action: str,
    payload: dict[str, Any],
    note: str | None,
) -> None:
    db.add(
        OfferReviewRevision(
            review_item_id=item.id,
            revision_no=_next_revision_no(db, item.id),
            action=action,
            payload_json=payload,
            note=note,
        )
    )


def _assert_same_immutable(
    existing: OfferReviewItem,
    incoming: dict[str, Any],
) -> None:
    comparisons = {
        "source_chain": incoming["source_chain"],
        "source_snapshot_id": incoming.get("source_snapshot_id"),
        "source_flyer_key": incoming["source_flyer_key"],
        "source_row_key": incoming["source_row_key"],
        "page_number": incoming.get("page_number"),
        "parser_version": incoming["parser_version"],
        "reason_codes": incoming.get("reason_codes") or [],
        "original_payload": incoming.get("original_payload") or {},
        "provenance_json": incoming.get("provenance_json") or {},
    }
    for key, value in comparisons.items():
        if getattr(existing, key) != value:
            raise ValueError(f"Review seed conflicts with immutable field: {key}")


def seed_review_item(
    db: Session,
    *,
    source_chain: str,
    source_flyer_key: str,
    source_row_key: str,
    parser_version: str,
    original_payload: dict[str, Any],
    provenance_json: dict[str, Any],
    reason_codes: list[str],
    source_snapshot_id: UUID | None = None,
    page_number: int | None = None,
) -> OfferReviewItem:
    item_id = _review_id(source_chain, source_flyer_key, source_row_key)
    existing = db.get(OfferReviewItem, item_id)
    incoming = {
        "source_chain": source_chain,
        "source_snapshot_id": source_snapshot_id,
        "source_flyer_key": source_flyer_key,
        "source_row_key": source_row_key,
        "page_number": page_number,
        "parser_version": parser_version,
        "reason_codes": list(reason_codes),
        "original_payload": original_payload,
        "provenance_json": provenance_json,
    }
    if existing is not None:
        _assert_same_immutable(existing, incoming)
        return existing

    item = OfferReviewItem(
        id=item_id,
        source_chain=source_chain,
        source_snapshot_id=source_snapshot_id,
        source_flyer_key=source_flyer_key,
        source_row_key=source_row_key,
        page_number=page_number,
        parser_version=parser_version,
        status="pending",
        reason_codes=list(reason_codes),
        original_payload=dict(original_payload),
        corrected_payload={},
        provenance_json=dict(provenance_json),
    )
    db.add(item)
    db.flush()
    _revision(
        db,
        item,
        action="seed",
        payload={
            "reason_codes": list(reason_codes),
            "original_payload": dict(original_payload),
            "provenance_json": dict(provenance_json),
        },
        note=None,
    )
    db.commit()
    db.refresh(item)
    return item


def get_review_item(db: Session, item_id: UUID) -> OfferReviewItem:
    item = db.get(OfferReviewItem, item_id)
    if item is None:
        raise KeyError(str(item_id))
    return item


def list_review_items(
    db: Session,
    *,
    status: str | None,
    source_chain: str | None,
    limit: int,
) -> list[OfferReviewItem]:
    query = select(OfferReviewItem)
    if status:
        query = query.where(OfferReviewItem.status == status)
    if source_chain:
        query = query.where(OfferReviewItem.source_chain == source_chain)
    query = query.order_by(
        OfferReviewItem.source_flyer_key.desc(),
        OfferReviewItem.page_number.is_(None),
        OfferReviewItem.page_number.asc(),
        OfferReviewItem.created_at.asc(),
        OfferReviewItem.id.asc(),
    ).limit(limit)
    return list(db.scalars(query).all())


def review_summary(
    db: Session,
    *,
    source_chain: str | None,
) -> dict[str, Any]:
    query = select(OfferReviewItem.status, func.count()).group_by(
        OfferReviewItem.status
    )
    if source_chain:
        query = query.where(OfferReviewItem.source_chain == source_chain)
    counts = {
        str(status): int(count)
        for status, count in db.execute(query).all()
    }
    return {
        "source_chain": source_chain,
        "counts": counts,
        "open_count": sum(
            counts.get(key, 0)
            for key in ("pending", "draft", "needs_followup")
        ),
    }


def save_review_draft(
    db: Session,
    *,
    item_id: UUID,
    corrections: dict[str, Any],
    note: str | None,
    needs_followup: bool = False,
) -> OfferReviewItem:
    item = get_review_item(db, item_id)
    if item.status not in OPEN_STATES:
        raise ValueError(f"Review item is not editable in status={item.status}")

    unknown = sorted(set(corrections) - EDITABLE_FIELDS)
    if unknown:
        raise ValueError(f"Unsupported correction fields: {unknown}")

    merged = dict(item.corrected_payload or {})
    merged.update(corrections)
    item.corrected_payload = merged
    item.reviewer_note = note if note is not None else item.reviewer_note
    item.status = "needs_followup" if needs_followup else "draft"
    item.updated_at = _now()
    _revision(
        db,
        item,
        action="needs_followup" if needs_followup else "draft",
        payload={"corrections": dict(corrections)},
        note=note,
    )
    db.commit()
    db.refresh(item)
    return item


def reject_review_item(
    db: Session,
    *,
    item_id: UUID,
    note: str | None,
) -> OfferReviewItem:
    item = get_review_item(db, item_id)
    if item.status not in OPEN_STATES:
        if item.status == "rejected":
            return item
        raise ValueError(
            f"Review item cannot be rejected from status={item.status}"
        )

    now = _now()
    item.status = "rejected"
    item.reviewer_note = note if note is not None else item.reviewer_note
    item.decided_at = now
    item.updated_at = now
    _revision(db, item, action="reject", payload={}, note=note)
    db.commit()
    db.refresh(item)
    return item


def reopen_review_item(
    db: Session,
    *,
    item_id: UUID,
    note: str | None,
) -> OfferReviewItem:
    item = get_review_item(db, item_id)
    if item.status == "approved":
        raise ValueError(
            "Approved item cannot be reopened without an explicit "
            "unpublish workflow"
        )
    if item.status == "pending":
        return item
    if item.status not in {"rejected", "draft", "needs_followup"}:
        raise ValueError(
            f"Review item cannot be reopened from status={item.status}"
        )

    item.status = "pending"
    item.decided_at = None
    item.updated_at = _now()
    item.reviewer_note = note if note is not None else item.reviewer_note
    _revision(db, item, action="reopen", payload={}, note=note)
    db.commit()
    db.refresh(item)
    return item


def _decimal(value: Any) -> Decimal | None:
    if value is None or value == "":
        return None
    return Decimal(str(value))


def _date(value: Any) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, date):
        return value
    return date.fromisoformat(str(value))


def _merged_payload(item: OfferReviewItem) -> dict[str, Any]:
    merged = dict(item.original_payload or {})
    merged.update(item.corrected_payload or {})
    return merged


def _build_offer(
    *,
    item: OfferReviewItem,
    manual_snapshot: SourceSnapshot,
    original_snapshot: SourceSnapshot,
) -> OfferCandidate:
    merged = _merged_payload(item)

    if merged.get("scope") != "in_scope":
        raise ValueError("Approval requires scope=in_scope")
    if merged.get("channel") != "physical_store":
        raise ValueError("Approval requires channel=physical_store")

    product_name = str(
        merged.get("product_name")
        or merged.get("product_name_raw")
        or ""
    ).strip()
    if not product_name:
        raise ValueError("Approval requires a product name")

    price = _decimal(merged.get("price_eur"))
    if price is None:
        raise ValueError("Approval requires price_eur")

    pricing_mode = str(merged.get("pricing_mode") or "").strip() or None
    variable_weight = "variable_weight_requires_review" in {
        str(value) for value in (item.reason_codes or [])
    }
    unit_basis_modes = {
        "unit_price_only",
        "example_total_plus_unit",
        "app_example_total_plus_unit",
    }
    if variable_weight:
        if pricing_mode not in unit_basis_modes:
            raise ValueError(
                "Variable-weight approval requires explicit unit-basis pricing_mode"
            )
        if _decimal(merged.get("unit_price_eur")) is None:
            raise ValueError("Variable-weight approval requires unit_price_eur")
        if not str(merged.get("unit_label") or "").strip():
            raise ValueError("Variable-weight approval requires unit_label")
        if (
            pricing_mode in {"example_total_plus_unit", "app_example_total_plus_unit"}
            and _decimal(merged.get("example_weight_g")) is None
        ):
            raise ValueError(
                "Variable-weight example pricing requires example_weight_g"
            )
        if pricing_mode == "app_example_total_plus_unit" and not bool(
            merged.get("requires_app")
        ):
            raise ValueError(
                "App example unit-basis pricing requires requires_app=true"
            )

    source_url = str(
        merged.get("source_url")
        or item.provenance_json.get("source_url")
        or original_snapshot.final_url
        or original_snapshot.source_url
    )
    app_price = _decimal(merged.get("app_price_eur"))

    raw_payload = {
        "review_source": "manual",
        "review_item_id": str(item.id),
        "review_source_flyer_key": item.source_flyer_key,
        "review_source_row_key": item.source_row_key,
        "review_page_number": item.page_number,
        "review_original_source_snapshot_id": str(original_snapshot.id),
        "review_original_parser_version": item.parser_version,
        "review_reason_codes": list(item.reason_codes or []),
        "pricing_mode": pricing_mode,
        "price_basis": merged.get("price_basis"),
        "regular_unit_price_eur": merged.get("regular_unit_price_eur"),
        "example_weight_g": merged.get("example_weight_g"),
        "review_original_payload": dict(item.original_payload or {}),
        "review_corrected_payload": dict(item.corrected_payload or {}),
        "review_provenance": dict(item.provenance_json or {}),
    }

    return OfferCandidate(
        source_chain=SourceChain(item.source_chain),
        source_store_external_id=(
            merged.get("source_store_external_id")
            or item.provenance_json.get("source_store_external_id")
        ),
        source_store_name=(
            merged.get("source_store_name")
            or item.provenance_json.get("source_store_name")
            or "Lidl"
        ),
        source_offer_id=_source_offer_id(item),
        product_name_raw=product_name,
        brand_raw=merged.get("brand") or merged.get("brand_raw"),
        description_raw=merged.get("description_raw"),
        package_text_raw=(
            merged.get("package_text")
            or merged.get("package_text_raw")
        ),
        price_eur=price,
        regular_price_eur=_decimal(merged.get("regular_price_eur")),
        unit_price_eur=_decimal(merged.get("unit_price_eur")),
        unit_label=merged.get("unit_label"),
        pricing_mode=pricing_mode,
        regular_unit_price_eur=_decimal(merged.get("regular_unit_price_eur")),
        example_weight_g=_decimal(merged.get("example_weight_g")),
        discount_percent=(
            None
            if merged.get("discount_percent") in (None, "")
            else int(merged["discount_percent"])
        ),
        app_price_eur=app_price,
        requires_app=bool(
            merged.get("requires_app") or app_price is not None
        ),
        coupon_required=bool(merged.get("coupon_required", False)),
        valid_from=_date(merged.get("valid_from")),
        valid_until=_date(merged.get("valid_until")),
        app_valid_from=_date(merged.get("app_valid_from")),
        app_valid_until=_date(merged.get("app_valid_until")),
        source_url=source_url,
        source_image_url=merged.get("source_image_url"),
        snapshot_id=manual_snapshot.id,
        collected_at=manual_snapshot.collected_at,
        parser_version="lidl-manual-review-v1",
        raw_payload=raw_payload,
    )


def approve_review_item(
    db: Session,
    *,
    item_id: UUID,
    note: str | None,
) -> OfferReviewItem:
    item = get_review_item(db, item_id)
    if item.status == "approved":
        return item
    if item.status not in OPEN_STATES:
        raise ValueError(
            f"Review item cannot be approved from status={item.status}"
        )
    if item.source_snapshot_id is None:
        raise ValueError(
            "Approval requires provenance-bound source_snapshot_id"
        )

    original_snapshot = db.get(SourceSnapshot, item.source_snapshot_id)
    if original_snapshot is None:
        raise ValueError("Original source snapshot does not exist")
    if original_snapshot.source_chain != item.source_chain:
        raise ValueError(
            "Review source chain does not match original snapshot"
        )

    manual_id = _manual_snapshot_id(item.id)
    manual_snapshot = db.get(SourceSnapshot, manual_id)
    if manual_snapshot is None:
        manual_snapshot = SourceSnapshot(
            id=manual_id,
            source_chain=item.source_chain,
            source_url=original_snapshot.source_url,
            final_url=original_snapshot.final_url,
            scope=f"manual_review:{item.source_flyer_key}"[:64],
            collected_at=_now(),
            http_status=None,
            elapsed_ms=None,
            content_type="application/json",
            content_bytes=0,
            sha256=original_snapshot.sha256,
            snapshot_path=original_snapshot.snapshot_path,
            keyword_hits={},
            json_ld_blocks=0,
            strategy_hint="manual_review_v1",
            success=True,
            error=None,
        )
        db.add(manual_snapshot)
        db.flush()

    offer = _build_offer(
        item=item,
        manual_snapshot=manual_snapshot,
        original_snapshot=original_snapshot,
    )

    # The common persistence path enforces an exact immutable offer-set per
    # snapshot. The derived manual-review snapshot contains exactly this one
    # reviewed offer, so the invariant remains intact.
    save_offer_candidates(db, [offer])

    persisted = db.scalar(
        select(OfferCandidateRecord).where(
            OfferCandidateRecord.snapshot_id == manual_snapshot.id,
            OfferCandidateRecord.source_offer_id == offer.source_offer_id,
        )
    )
    if persisted is None:
        raise RuntimeError("Approved offer was not persisted")

    # save_offer_candidates commits. Re-read the review row so a retry after a
    # process interruption remains idempotent.
    item = get_review_item(db, item_id)
    if item.status == "approved":
        return item

    now = _now()
    item.status = "approved"
    item.published_offer_candidate_id = persisted.id
    item.reviewer_note = note if note is not None else item.reviewer_note
    item.decided_at = now
    item.updated_at = now
    _revision(
        db,
        item,
        action="approve",
        payload={
            "published_offer_candidate_id": str(persisted.id),
            "manual_snapshot_id": str(manual_snapshot.id),
            "source_offer_id": offer.source_offer_id,
        },
        note=note,
    )
    db.commit()
    db.refresh(item)
    return item


def review_item_dict(
    db: Session,
    item: OfferReviewItem,
    *,
    include_revisions: bool = False,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "id": str(item.id),
        "source_chain": item.source_chain,
        "source_snapshot_id": (
            None
            if item.source_snapshot_id is None
            else str(item.source_snapshot_id)
        ),
        "source_flyer_key": item.source_flyer_key,
        "source_row_key": item.source_row_key,
        "page_number": item.page_number,
        "parser_version": item.parser_version,
        "status": item.status,
        "reason_codes": list(item.reason_codes or []),
        "original_payload": dict(item.original_payload or {}),
        "corrected_payload": dict(item.corrected_payload or {}),
        "effective_payload": _merged_payload(item),
        "provenance": dict(item.provenance_json or {}),
        "reviewer_note": item.reviewer_note,
        "published_offer_candidate_id": (
            None
            if item.published_offer_candidate_id is None
            else str(item.published_offer_candidate_id)
        ),
        "created_at": item.created_at.isoformat(),
        "updated_at": item.updated_at.isoformat(),
        "decided_at": (
            None
            if item.decided_at is None
            else item.decided_at.isoformat()
        ),
    }
    if include_revisions:
        revisions = list(
            db.scalars(
                select(OfferReviewRevision)
                .where(
                    OfferReviewRevision.review_item_id == item.id
                )
                .order_by(OfferReviewRevision.revision_no.asc())
            ).all()
        )
        payload["revisions"] = [
            {
                "revision_no": row.revision_no,
                "action": row.action,
                "payload": dict(row.payload_json or {}),
                "note": row.note,
                "created_at": row.created_at.isoformat(),
            }
            for row in revisions
        ]
    return payload


def scope_only_fast_review_eligible(item: OfferReviewItem) -> bool:
    # Complete physical-store row whose only fast-path blocker is scope.
    if item.status not in {"pending", "draft", "needs_followup"}:
        return False

    reasons = {str(value) for value in (item.reason_codes or [])}
    if "scope_requires_review" not in reasons:
        return False
    if "variable_weight_requires_review" in reasons:
        return False

    payload = dict(item.original_payload or {})
    payload.update(item.corrected_payload or {})

    if str(payload.get("price_basis") or "") == "variable_weight_example":
        return False
    if str(payload.get("channel") or "") != "physical_store":
        return False

    product = payload.get("product_name") or payload.get("product_name_raw")
    required = (
        product,
        payload.get("price_eur"),
        payload.get("valid_from"),
        payload.get("valid_until"),
    )
    return all(value is not None and str(value).strip() for value in required)


def approve_scope_only_review_item(
    db: Session,
    *,
    item_id: UUID,
) -> OfferReviewItem:
    # Explicit human action; uses the normal auditable draft + approval path.
    item = get_review_item(db, item_id)
    if not scope_only_fast_review_eligible(item):
        raise ValueError("Review item is not eligible for scope-only fast approval")

    corrected = dict(item.corrected_payload or {})
    corrected["scope"] = "in_scope"

    save_review_draft(
        db,
        item_id=item_id,
        corrections=corrected,
        note="Scope-only fast review: human confirmed in-scope.",
        needs_followup=False,
    )
    return approve_review_item(
        db,
        item_id=item_id,
        note="Scope-only fast review: human confirmed in-scope.",
    )
