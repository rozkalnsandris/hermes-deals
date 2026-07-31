from __future__ import annotations

import argparse
import hashlib
import json
from dataclasses import dataclass
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import (
    OfferCandidateRecord,
    OfferNormalization,
    OfferProductLink,
    OfferReviewItem,
    OfferReviewRevision,
    ProductMatchCandidate,
    SourceSnapshot,
)

REPAIR_WORKFLOW_VERSION = "lidl-review-scope-repair-v1"
SCOPE_CONTRACT = {
    "include": ["food", "drinks", "household_consumables"],
    "exclude": [
        "flowers_and_plants",
        "durable_nonfood",
        "clothing",
        "electronics",
        "tools",
        "furniture",
        "camping_equipment",
        "personal_care",
    ],
}
REPAIR_DECISION = "repair_required_after_manual_canary"
REPAIR_NOTE = (
    "B15I1 scope repair: outside Hermes Deals target "
    "(food, drinks, household consumables only)."
)


@dataclass(frozen=True)
class ScopeRepairManifest:
    sha256: str
    payload: dict[str, Any]
    approved_in_scope_keep: tuple[dict[str, str], ...]
    approved_out_of_scope_retract: tuple[dict[str, str], ...]
    pending_out_of_scope_cleanup: tuple[dict[str, str], ...]
    rejected_out_of_scope_keep_closed: tuple[dict[str, str], ...]


def _sha256_file(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _load_exact_json(path: Path, expected_sha256: str) -> dict[str, Any]:
    raw = path.read_bytes()
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected_sha256:
        raise ValueError(
            f"Repair manifest SHA mismatch: expected {expected_sha256}, got {actual}"
        )
    payload = json.loads(raw)
    if not isinstance(payload, dict):
        raise ValueError("Repair manifest root must be an object")
    return payload


def load_scope_repair_manifest(
    *,
    path: Path,
    expected_sha256: str,
) -> ScopeRepairManifest:
    payload = _load_exact_json(path, expected_sha256)
    expected_fields = {
        "approved_in_scope_keep",
        "approved_out_of_scope_retract",
        "counts",
        "decision",
        "pending_out_of_scope_cleanup",
        "rejected_out_of_scope_keep_closed",
        "scope_contract",
    }
    if set(payload) != expected_fields:
        raise ValueError("Repair manifest field set drift")
    if payload["decision"] != REPAIR_DECISION:
        raise ValueError("Repair manifest decision mismatch")
    if payload["scope_contract"] != SCOPE_CONTRACT:
        raise ValueError("Repair manifest scope contract mismatch")
    if payload["counts"] != {
        "approved_in_scope_keep": 6,
        "approved_out_of_scope_retract": 7,
        "pending_out_of_scope_cleanup": 38,
        "rejected_out_of_scope_keep_closed": 6,
    }:
        raise ValueError("Repair manifest count contract mismatch")

    groups: dict[str, tuple[dict[str, str], ...]] = {}
    for name, expected_count, with_offer in (
        ("approved_in_scope_keep", 6, True),
        ("approved_out_of_scope_retract", 7, True),
        ("pending_out_of_scope_cleanup", 38, False),
        ("rejected_out_of_scope_keep_closed", 6, False),
    ):
        rows = payload[name]
        if not isinstance(rows, list) or len(rows) != expected_count:
            raise ValueError(f"Repair manifest {name} count mismatch")
        expected_row_fields = {
            "product_name",
            "published_offer_candidate_id",
            "review_item_id",
            "source_row_key",
        } if with_offer else {
            "product_name",
            "review_item_id",
            "source_row_key",
        }
        normalized: list[dict[str, str]] = []
        for row in rows:
            if not isinstance(row, dict) or set(row) != expected_row_fields:
                raise ValueError(f"Repair manifest {name} row field drift")
            normalized_row = {
                key: str(value).strip()
                for key, value in row.items()
            }
            if any(not value for value in normalized_row.values()):
                raise ValueError(f"Repair manifest {name} has empty field")
            UUID(normalized_row["review_item_id"])
            if with_offer:
                UUID(normalized_row["published_offer_candidate_id"])
            normalized.append(normalized_row)
        groups[name] = tuple(normalized)

    all_review_ids = [
        row["review_item_id"]
        for name in groups
        for row in groups[name]
    ]
    all_source_keys = [
        row["source_row_key"]
        for name in groups
        for row in groups[name]
    ]
    if len(all_review_ids) != 57 or len(set(all_review_ids)) != 57:
        raise ValueError("Repair manifest Review identities are not unique")
    if len(all_source_keys) != 57 or len(set(all_source_keys)) != 57:
        raise ValueError("Repair manifest source-row identities are not unique")

    offer_ids = [
        row["published_offer_candidate_id"]
        for name in ("approved_in_scope_keep", "approved_out_of_scope_retract")
        for row in groups[name]
    ]
    if len(offer_ids) != 13 or len(set(offer_ids)) != 13:
        raise ValueError("Repair manifest offer identities are not unique")

    return ScopeRepairManifest(
        sha256=expected_sha256,
        payload=payload,
        approved_in_scope_keep=groups["approved_in_scope_keep"],
        approved_out_of_scope_retract=groups["approved_out_of_scope_retract"],
        pending_out_of_scope_cleanup=groups["pending_out_of_scope_cleanup"],
        rejected_out_of_scope_keep_closed=groups[
            "rejected_out_of_scope_keep_closed"
        ],
    )


def _review_ids(manifest: ScopeRepairManifest) -> list[UUID]:
    return [
        UUID(row["review_item_id"])
        for group in (
            manifest.approved_in_scope_keep,
            manifest.approved_out_of_scope_retract,
            manifest.pending_out_of_scope_cleanup,
            manifest.rejected_out_of_scope_keep_closed,
        )
        for row in group
    ]


def _next_revision_no(db: Session, item_id: UUID) -> int:
    current = db.scalar(
        select(func.max(OfferReviewRevision.revision_no)).where(
            OfferReviewRevision.review_item_id == item_id
        )
    )
    return int(current or 0) + 1


def _iso_datetime(value: datetime | None) -> str | None:
    return None if value is None else value.isoformat()


def _review_state(item: OfferReviewItem) -> dict[str, Any]:
    return {
        "status": item.status,
        "corrected_payload": dict(item.corrected_payload or {}),
        "reviewer_note": item.reviewer_note,
        "published_offer_candidate_id": (
            None
            if item.published_offer_candidate_id is None
            else str(item.published_offer_candidate_id)
        ),
        "decided_at": _iso_datetime(item.decided_at),
        "updated_at": _iso_datetime(item.updated_at),
    }


def _offer_payload(offer: OfferCandidateRecord) -> dict[str, Any]:
    decimal_fields = {
        "price_eur",
        "regular_price_eur",
        "unit_price_eur",
        "regular_unit_price_eur",
        "example_weight_g",
        "app_price_eur",
    }
    date_fields = {
        "valid_from",
        "valid_until",
        "app_valid_from",
        "app_valid_until",
    }
    datetime_fields = {"collected_at"}
    uuid_fields = {"id", "snapshot_id"}
    result: dict[str, Any] = {}
    for column in OfferCandidateRecord.__table__.columns:
        value = getattr(offer, column.name)
        if value is None:
            result[column.name] = None
        elif column.name in decimal_fields:
            result[column.name] = str(value)
        elif column.name in date_fields:
            result[column.name] = value.isoformat()
        elif column.name in datetime_fields:
            result[column.name] = value.isoformat()
        elif column.name in uuid_fields:
            result[column.name] = str(value)
        elif column.name == "raw_payload":
            result[column.name] = dict(value or {})
        else:
            result[column.name] = value
    return result


def _offer_from_payload(payload: dict[str, Any]) -> OfferCandidateRecord:
    expected = {column.name for column in OfferCandidateRecord.__table__.columns}
    if set(payload) != expected:
        raise ValueError("Retracted offer backup field set drift")
    values = dict(payload)
    for key in (
        "price_eur",
        "regular_price_eur",
        "unit_price_eur",
        "regular_unit_price_eur",
        "example_weight_g",
        "app_price_eur",
    ):
        values[key] = None if values[key] is None else Decimal(values[key])
    for key in ("valid_from", "valid_until", "app_valid_from", "app_valid_until"):
        values[key] = None if values[key] is None else date.fromisoformat(values[key])
    values["collected_at"] = datetime.fromisoformat(values["collected_at"])
    values["id"] = UUID(values["id"])
    values["snapshot_id"] = UUID(values["snapshot_id"])
    return OfferCandidateRecord(**values)


def _assert_item_identity(
    *,
    item: OfferReviewItem,
    row: dict[str, str],
    flyer_key: str,
    plan_sha256: str,
) -> None:
    if item.source_chain != "lidl":
        raise ValueError("Repair Review item source chain mismatch")
    if item.source_flyer_key != flyer_key:
        raise ValueError("Repair Review item flyer mismatch")
    if item.source_row_key != row["source_row_key"]:
        raise ValueError("Repair Review item source-row mismatch")
    if item.provenance_json.get("review_seed_plan_sha256") != plan_sha256:
        raise ValueError("Repair Review item plan SHA mismatch")
    product = str(
        (item.original_payload or {}).get("product_name")
        or (item.original_payload or {}).get("product_name_raw")
        or ""
    )
    if product != row["product_name"]:
        raise ValueError("Repair Review item product-name mismatch")


def _assert_offer_identity(
    *,
    offer: OfferCandidateRecord,
    row: dict[str, str],
    item: OfferReviewItem,
    plan_sha256: str,
) -> None:
    if str(offer.id) != row["published_offer_candidate_id"]:
        raise ValueError("Repair offer ID mismatch")
    if offer.source_chain != "lidl":
        raise ValueError("Repair offer source chain mismatch")
    raw = dict(offer.raw_payload or {})
    if raw.get("review_item_id") != str(item.id):
        raise ValueError("Repair offer Review identity mismatch")
    provenance = raw.get("review_provenance")
    if not isinstance(provenance, dict):
        raise ValueError("Repair offer provenance missing")
    if provenance.get("review_seed_plan_sha256") != plan_sha256:
        raise ValueError("Repair offer plan SHA mismatch")


def _repair_revisions(
    db: Session,
    *,
    manifest_sha256: str,
) -> list[OfferReviewRevision]:
    rows = list(
        db.scalars(
            select(OfferReviewRevision).where(
                OfferReviewRevision.payload_json[
                    "repair_manifest_sha256"
                ].as_string()
                == manifest_sha256
            )
        ).all()
    )
    return rows


def _load_items_for_update(
    db: Session,
    manifest: ScopeRepairManifest,
) -> dict[UUID, OfferReviewItem]:
    rows = list(
        db.scalars(
            select(OfferReviewItem)
            .where(OfferReviewItem.id.in_(_review_ids(manifest)))
            .with_for_update()
        ).all()
    )
    if len(rows) != 57:
        raise ValueError("Repair live Review item count mismatch")
    return {row.id: row for row in rows}


def _assert_original_state(
    db: Session,
    *,
    manifest: ScopeRepairManifest,
    flyer_key: str,
    plan_sha256: str,
) -> dict[str, Any]:
    items = _load_items_for_update(db, manifest)
    if _repair_revisions(db, manifest_sha256=manifest.sha256):
        raise ValueError("Repair revisions already exist in original state")

    groups = (
        (manifest.approved_in_scope_keep, "approved", True),
        (manifest.approved_out_of_scope_retract, "approved", True),
        (manifest.pending_out_of_scope_cleanup, "pending", False),
        (manifest.rejected_out_of_scope_keep_closed, "rejected", False),
    )
    offers: dict[UUID, OfferCandidateRecord] = {}
    for rows, expected_status, expects_offer in groups:
        for row in rows:
            item = items[UUID(row["review_item_id"])]
            _assert_item_identity(
                item=item,
                row=row,
                flyer_key=flyer_key,
                plan_sha256=plan_sha256,
            )
            if item.status != expected_status:
                raise ValueError(
                    f"Repair Review status mismatch for {item.id}: "
                    f"expected {expected_status}, got {item.status}"
                )
            if expects_offer:
                expected_offer_id = UUID(row["published_offer_candidate_id"])
                if item.published_offer_candidate_id != expected_offer_id:
                    raise ValueError("Repair published offer reference mismatch")
                offer = db.get(OfferCandidateRecord, expected_offer_id)
                if offer is None:
                    raise ValueError("Repair published offer is missing")
                _assert_offer_identity(
                    offer=offer,
                    row=row,
                    item=item,
                    plan_sha256=plan_sha256,
                )
                offers[expected_offer_id] = offer
            elif item.published_offer_candidate_id is not None:
                raise ValueError("Repair non-approved row has published offer")

    invalid_offer_ids = [
        UUID(row["published_offer_candidate_id"])
        for row in manifest.approved_out_of_scope_retract
    ]
    dependency_counts = {
        "offer_normalizations": int(
            db.scalar(
                select(func.count())
                .select_from(OfferNormalization)
                .where(OfferNormalization.offer_candidate_id.in_(invalid_offer_ids))
            )
            or 0
        ),
        "product_match_candidates": int(
            db.scalar(
                select(func.count())
                .select_from(ProductMatchCandidate)
                .where(ProductMatchCandidate.offer_candidate_id.in_(invalid_offer_ids))
            )
            or 0
        ),
        "offer_product_links": int(
            db.scalar(
                select(func.count())
                .select_from(OfferProductLink)
                .where(OfferProductLink.offer_candidate_id.in_(invalid_offer_ids))
            )
            or 0
        ),
    }
    if any(dependency_counts.values()):
        raise ValueError(
            f"Repair invalid publications have downstream dependencies: "
            f"{dependency_counts}"
        )

    snapshot_ids = {
        offers[offer_id].snapshot_id
        for offer_id in invalid_offer_ids
    }
    if len(snapshot_ids) != 7:
        raise ValueError("Repair invalid publications do not have unique snapshots")
    for snapshot_id in snapshot_ids:
        snapshot = db.get(SourceSnapshot, snapshot_id)
        if (
            snapshot is None
            or snapshot.source_chain != "lidl"
            or snapshot.strategy_hint != "manual_review_v1"
        ):
            raise ValueError("Repair invalid publication snapshot contract mismatch")
        count = int(
            db.scalar(
                select(func.count())
                .select_from(OfferCandidateRecord)
                .where(OfferCandidateRecord.snapshot_id == snapshot_id)
            )
            or 0
        )
        if count != 1:
            raise ValueError("Repair manual snapshot offer count mismatch")

    return {
        "items": items,
        "offers": offers,
        "dependency_counts": dependency_counts,
        "invalid_snapshot_ids": sorted(str(value) for value in snapshot_ids),
    }


def _repair_revision_for_item(
    db: Session,
    *,
    item_id: UUID,
    manifest_sha256: str,
) -> OfferReviewRevision | None:
    rows = list(
        db.scalars(
            select(OfferReviewRevision)
            .where(
                OfferReviewRevision.review_item_id == item_id,
                OfferReviewRevision.payload_json[
                    "repair_manifest_sha256"
                ].as_string()
                == manifest_sha256,
            )
            .order_by(OfferReviewRevision.revision_no.asc())
        ).all()
    )
    if len(rows) > 1:
        raise ValueError("Duplicate scope-repair revisions")
    return rows[0] if rows else None


def _assert_repaired_state(
    db: Session,
    *,
    manifest: ScopeRepairManifest,
    flyer_key: str,
    plan_sha256: str,
) -> dict[str, Any]:
    items = _load_items_for_update(db, manifest)
    repair_revision_count = 0

    for row in manifest.approved_in_scope_keep:
        item = items[UUID(row["review_item_id"])]
        _assert_item_identity(
            item=item,
            row=row,
            flyer_key=flyer_key,
            plan_sha256=plan_sha256,
        )
        if (
            item.status != "approved"
            or str(item.published_offer_candidate_id)
            != row["published_offer_candidate_id"]
        ):
            raise ValueError("Valid drink publication changed during repair")
        offer = db.get(
            OfferCandidateRecord,
            UUID(row["published_offer_candidate_id"]),
        )
        if offer is None:
            raise ValueError("Valid drink publication is missing")

    for rows, had_repair_revision in (
        (manifest.approved_out_of_scope_retract, True),
        (manifest.pending_out_of_scope_cleanup, True),
        (manifest.rejected_out_of_scope_keep_closed, False),
    ):
        for row in rows:
            item = items[UUID(row["review_item_id"])]
            _assert_item_identity(
                item=item,
                row=row,
                flyer_key=flyer_key,
                plan_sha256=plan_sha256,
            )
            if item.status != "rejected":
                raise ValueError("Out-of-scope Review item is not rejected")
            if item.published_offer_candidate_id is not None:
                raise ValueError("Rejected out-of-scope item remains published")
            revision = _repair_revision_for_item(
                db,
                item_id=item.id,
                manifest_sha256=manifest.sha256,
            )
            if had_repair_revision:
                if revision is None or revision.action != "reject":
                    raise ValueError("Scope-repair revision is missing")
                repair_revision_count += 1
            elif revision is not None:
                raise ValueError("Already-rejected row received repair revision")

    for row in manifest.approved_out_of_scope_retract:
        if db.get(
            OfferCandidateRecord,
            UUID(row["published_offer_candidate_id"]),
        ) is not None:
            raise ValueError("Retracted out-of-scope offer still exists")

    if repair_revision_count != 45:
        raise ValueError("Scope-repair revision count mismatch")
    return {"items": items, "repair_revision_count": repair_revision_count}


def validate_scope_repair(
    db: Session,
    *,
    manifest: ScopeRepairManifest,
    flyer_key: str,
    plan_sha256: str,
) -> dict[str, Any]:
    try:
        state = _assert_original_state(
            db,
            manifest=manifest,
            flyer_key=flyer_key,
            plan_sha256=plan_sha256,
        )
    except ValueError as original_error:
        db.rollback()
        try:
            repaired = _assert_repaired_state(
                db,
                manifest=manifest,
                flyer_key=flyer_key,
                plan_sha256=plan_sha256,
            )
        except ValueError:
            db.rollback()
            raise original_error
        db.rollback()
        return {
            "result": "LIDL_REVIEW_SCOPE_REPAIR_VALID",
            "state": "repaired",
            "repair_manifest_sha256": manifest.sha256,
            "out_of_scope_rows": 51,
            "valid_drinks": 6,
            "repair_revisions": repaired["repair_revision_count"],
        }
    db.rollback()
    return {
        "result": "LIDL_REVIEW_SCOPE_REPAIR_VALID",
        "state": "original",
        "repair_manifest_sha256": manifest.sha256,
        "out_of_scope_rows": 51,
        "valid_drinks": 6,
        "dependency_counts": state["dependency_counts"],
    }


def apply_scope_repair(
    db: Session,
    *,
    manifest: ScopeRepairManifest,
    flyer_key: str,
    plan_sha256: str,
) -> dict[str, Any]:
    try:
        original = _assert_original_state(
            db,
            manifest=manifest,
            flyer_key=flyer_key,
            plan_sha256=plan_sha256,
        )
    except ValueError as original_error:
        db.rollback()
        try:
            repaired = _assert_repaired_state(
                db,
                manifest=manifest,
                flyer_key=flyer_key,
                plan_sha256=plan_sha256,
            )
        except ValueError:
            db.rollback()
            raise original_error
        db.rollback()
        return {
            "result": "LIDL_REVIEW_SCOPE_REPAIR_COMPLETE",
            "repair_manifest_sha256": manifest.sha256,
            "newly_rejected": 0,
            "already_rejected": 51,
            "retracted_offers": 0,
            "valid_drinks_preserved": 6,
            "reused": True,
            "repair_revisions": repaired["repair_revision_count"],
        }

    items: dict[UUID, OfferReviewItem] = original["items"]
    offers: dict[UUID, OfferCandidateRecord] = original["offers"]
    now = datetime.now(timezone.utc)

    rows_to_reject = [
        *manifest.approved_out_of_scope_retract,
        *manifest.pending_out_of_scope_cleanup,
    ]
    for row in rows_to_reject:
        item = items[UUID(row["review_item_id"])]
        payload: dict[str, Any] = {
            "repair_workflow_version": REPAIR_WORKFLOW_VERSION,
            "repair_manifest_sha256": manifest.sha256,
            "scope_contract": SCOPE_CONTRACT,
            "classification": "remove_definite_out_of_scope",
            "review_item_before": _review_state(item),
        }
        if "published_offer_candidate_id" in row:
            offer_id = UUID(row["published_offer_candidate_id"])
            payload["retracted_offer_candidate"] = _offer_payload(offers[offer_id])

        db.add(
            OfferReviewRevision(
                review_item_id=item.id,
                revision_no=_next_revision_no(db, item.id),
                action="reject",
                payload_json=payload,
                note=REPAIR_NOTE,
            )
        )
        item.status = "rejected"
        item.published_offer_candidate_id = None
        item.reviewer_note = REPAIR_NOTE
        item.decided_at = now
        item.updated_at = now

    db.flush()
    for row in manifest.approved_out_of_scope_retract:
        db.delete(offers[UUID(row["published_offer_candidate_id"])])
    db.commit()

    repaired = _assert_repaired_state(
        db,
        manifest=manifest,
        flyer_key=flyer_key,
        plan_sha256=plan_sha256,
    )
    db.rollback()
    return {
        "result": "LIDL_REVIEW_SCOPE_REPAIR_COMPLETE",
        "repair_manifest_sha256": manifest.sha256,
        "newly_rejected": 45,
        "already_rejected": 6,
        "retracted_offers": 7,
        "valid_drinks_preserved": 6,
        "reused": False,
        "repair_revisions": repaired["repair_revision_count"],
        "preserved_manual_snapshots": 7,
    }


def _parse_datetime(value: str | None) -> datetime | None:
    return None if value is None else datetime.fromisoformat(value)


def rollback_scope_repair(
    db: Session,
    *,
    manifest: ScopeRepairManifest,
    flyer_key: str,
    plan_sha256: str,
) -> dict[str, Any]:
    repaired = _assert_repaired_state(
        db,
        manifest=manifest,
        flyer_key=flyer_key,
        plan_sha256=plan_sha256,
    )
    items: dict[UUID, OfferReviewItem] = repaired["items"]

    revisions: list[OfferReviewRevision] = []
    for row in (
        *manifest.approved_out_of_scope_retract,
        *manifest.pending_out_of_scope_cleanup,
    ):
        item = items[UUID(row["review_item_id"])]
        revision = _repair_revision_for_item(
            db,
            item_id=item.id,
            manifest_sha256=manifest.sha256,
        )
        if revision is None:
            raise ValueError("Scope-repair rollback revision is missing")
        before = revision.payload_json.get("review_item_before")
        if not isinstance(before, dict):
            raise ValueError("Scope-repair rollback item backup is missing")
        if "published_offer_candidate_id" in row:
            offer_payload = revision.payload_json.get(
                "retracted_offer_candidate"
            )
            if not isinstance(offer_payload, dict):
                raise ValueError("Scope-repair rollback offer backup is missing")
            offer_id = UUID(row["published_offer_candidate_id"])
            if db.get(OfferCandidateRecord, offer_id) is not None:
                raise ValueError("Scope-repair rollback offer already exists")
            db.add(_offer_from_payload(offer_payload))
        revisions.append(revision)

    db.flush()
    for row in (
        *manifest.approved_out_of_scope_retract,
        *manifest.pending_out_of_scope_cleanup,
    ):
        item = items[UUID(row["review_item_id"])]
        revision = _repair_revision_for_item(
            db,
            item_id=item.id,
            manifest_sha256=manifest.sha256,
        )
        assert revision is not None
        before = revision.payload_json["review_item_before"]
        item.status = before["status"]
        item.corrected_payload = dict(before["corrected_payload"] or {})
        item.reviewer_note = before["reviewer_note"]
        item.published_offer_candidate_id = (
            None
            if before["published_offer_candidate_id"] is None
            else UUID(before["published_offer_candidate_id"])
        )
        item.decided_at = _parse_datetime(before["decided_at"])
        item.updated_at = _parse_datetime(before["updated_at"])

    for revision in revisions:
        db.delete(revision)
    db.commit()

    original = _assert_original_state(
        db,
        manifest=manifest,
        flyer_key=flyer_key,
        plan_sha256=plan_sha256,
    )
    db.rollback()
    return {
        "result": "LIDL_REVIEW_SCOPE_REPAIR_ROLLBACK_COMPLETE",
        "repair_manifest_sha256": manifest.sha256,
        "restored_review_items": 45,
        "restored_offers": 7,
        "valid_drinks_preserved": 6,
        "dependency_counts": original["dependency_counts"],
    }


def _run(args: argparse.Namespace) -> int:
    # Keep database configuration lazy so CLI discovery and --help do not
    # require DATABASE_URL. Actual validate/apply/rollback commands still
    # initialize the normal production SessionLocal.
    from app.db import SessionLocal

    manifest = load_scope_repair_manifest(
        path=Path(args.manifest),
        expected_sha256=args.manifest_sha,
    )
    with SessionLocal() as db:
        if args.command == "validate":
            result = validate_scope_repair(
                db,
                manifest=manifest,
                flyer_key=args.flyer_key,
                plan_sha256=args.plan_sha,
            )
        elif args.command == "apply":
            result = apply_scope_repair(
                db,
                manifest=manifest,
                flyer_key=args.flyer_key,
                plan_sha256=args.plan_sha,
            )
        elif args.command == "rollback":
            result = rollback_scope_repair(
                db,
                manifest=manifest,
                flyer_key=args.flyer_key,
                plan_sha256=args.plan_sha,
            )
        else:
            raise AssertionError(args.command)
    print(json.dumps(result, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lidl-review-scope-repair")
    sub = parser.add_subparsers(dest="command", required=True)
    for command in ("validate", "apply", "rollback"):
        child = sub.add_parser(command)
        child.add_argument("--manifest", required=True)
        child.add_argument("--manifest-sha", required=True)
        child.add_argument("--flyer-key", required=True)
        child.add_argument("--plan-sha", required=True)
        child.set_defaults(func=_run)
    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
