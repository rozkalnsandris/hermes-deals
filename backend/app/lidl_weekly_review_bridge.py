from __future__ import annotations

from datetime import date
from hashlib import blake2s
from typing import Any, Iterable, Mapping
from uuid import UUID

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.lidl_weekly_completeness_contract import plausible_same_title
from app.models import OfferCandidateRecord, OfferReviewItem, SourceSnapshot
from app.review_queue import get_review_item, seed_review_item


PAGE_ALERT_REASON = "weekly_page_review_alert"
NATIVE_GAP_REASON = "weekly_native_unowned_price"
PAGE_HINT_REASON = "weekly_page_alert_manual_product"
SCOPE_REVIEW_REASON = "scope_requires_review"


def _flyer_validity(flyer_key: str) -> tuple[str | None, str | None]:
    parts = str(flyer_key or "").split("-")
    if len(parts) < 2:
        return None, None
    try:
        start = date(int(parts[0][0:4]), int(parts[0][4:6]), int(parts[0][6:8]))
        end = date(int(parts[1][0:4]), int(parts[1][4:6]), int(parts[1][6:8]))
    except (ValueError, IndexError):
        return None, None
    if end < start:
        return None, None
    return start.isoformat(), end.isoformat()


def _effective_name(item: OfferReviewItem) -> str:
    payload = dict(item.original_payload or {})
    payload.update(item.corrected_payload or {})
    return str(payload.get("product_name") or payload.get("product_name_raw") or "").strip()


def _same_review_product(name: object, item: OfferReviewItem) -> bool:
    current = _effective_name(item)
    return bool(current) and plausible_same_title(name, current)


def _review_rows_on_page(db: Session, *, flyer_key: str, page: int) -> list[OfferReviewItem]:
    return list(
        db.scalars(
            select(OfferReviewItem)
            .where(
                OfferReviewItem.source_chain == "lidl",
                OfferReviewItem.source_flyer_key == flyer_key,
                OfferReviewItem.page_number == int(page),
            )
            .order_by(OfferReviewItem.created_at.asc(), OfferReviewItem.id.asc())
        ).all()
    )


def resolve_original_lidl_snapshot(db: Session, *, source_raw_sha256: str) -> SourceSnapshot:
    sha = str(source_raw_sha256 or "").strip().lower()
    if len(sha) != 64:
        raise ValueError("Weekly Review bridge requires exact source_raw_sha256")

    snapshots = list(
        db.scalars(
            select(SourceSnapshot).where(
                SourceSnapshot.source_chain == "lidl",
                SourceSnapshot.sha256 == sha,
                SourceSnapshot.success.is_(True),
            )
        ).all()
    )
    snapshots = [
        row
        for row in snapshots
        if str(row.strategy_hint or "") != "manual_review_v1"
        and not str(row.scope or "").startswith("manual_review:")
    ]
    if not snapshots:
        raise RuntimeError("No provenance-bound original Lidl snapshot for weekly bridge")

    ranked: list[tuple[int, SourceSnapshot]] = []
    for row in snapshots:
        offer_count = int(
            db.scalar(
                select(func.count())
                .select_from(OfferCandidateRecord)
                .where(OfferCandidateRecord.snapshot_id == row.id)
            )
            or 0
        )
        ranked.append((offer_count, row))
    ranked.sort(key=lambda pair: (-pair[0], pair[1].collected_at, str(pair[1].id)))
    if len(ranked) > 1 and ranked[0][0] == ranked[1][0]:
        raise RuntimeError(
            "Ambiguous original Lidl snapshot for weekly bridge "
            f"(top offer_count={ranked[0][0]})"
        )
    return ranked[0][1]


def _validate_artifact_identity(
    candidates: list[dict[str, Any]],
    page_alerts: list[dict[str, Any]],
) -> tuple[str, str, str]:
    rows = [*candidates, *page_alerts]
    if not rows:
        raise ValueError("Weekly Review bridge received no artifacts")
    flyer_keys = {str(row.get("flyer_key") or "") for row in rows}
    raw_shas = {str(row.get("source_raw_sha256") or "") for row in rows}
    parser_versions = {str(row.get("parser_version") or "") for row in rows}
    if len(flyer_keys) != 1 or "" in flyer_keys:
        raise ValueError("Weekly artifacts disagree on flyer_key")
    if len(raw_shas) != 1 or "" in raw_shas:
        raise ValueError("Weekly artifacts disagree on source_raw_sha256")
    if len(parser_versions) != 1 or "" in parser_versions:
        raise ValueError("Weekly artifacts disagree on parser_version")
    return next(iter(flyer_keys)), next(iter(raw_shas)), next(iter(parser_versions))


def plan_weekly_review_bridge(
    db: Session,
    *,
    candidates: Iterable[Mapping[str, Any]],
    page_alerts: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    candidate_rows = [dict(row) for row in candidates]
    alert_rows = [dict(row) for row in page_alerts]
    flyer_key, raw_sha, parser_version = _validate_artifact_identity(candidate_rows, alert_rows)
    snapshot = resolve_original_lidl_snapshot(db, source_raw_sha256=raw_sha)

    planned_candidates: list[dict[str, Any]] = []
    suppressed_candidates: list[dict[str, Any]] = []
    for row in candidate_rows:
        page = int(row["page"])
        existing = _review_rows_on_page(db, flyer_key=flyer_key, page=page)
        matched = next(
            (item for item in existing if _same_review_product(row.get("product_name"), item)),
            None,
        )
        if matched is not None:
            suppressed_candidates.append({
                "candidate_key": row["candidate_key"],
                "product_name": row.get("product_name"),
                "page": page,
                "reason": "existing_review_product",
                "existing_review_item_id": str(matched.id),
                "existing_status": matched.status,
            })
        else:
            planned_candidates.append(row)

    planned_alerts: list[dict[str, Any]] = []
    suppressed_alerts: list[dict[str, Any]] = []
    for row in alert_rows:
        page = int(row["page"])
        existing = _review_rows_on_page(db, flyer_key=flyer_key, page=page)
        unresolved: list[dict[str, Any]] = []
        resolved: list[dict[str, Any]] = []
        for hint in row.get("hints") or []:
            hint_row = dict(hint)
            matched = next(
                (
                    item
                    for item in existing
                    if _same_review_product(hint_row.get("product_name_hint"), item)
                    or _same_review_product(hint_row.get("native_title"), item)
                ),
                None,
            )
            if matched is None:
                unresolved.append(hint_row)
            else:
                resolved.append({
                    **hint_row,
                    "existing_review_item_id": str(matched.id),
                    "existing_status": matched.status,
                })
        if not unresolved:
            suppressed_alerts.append({
                "alert_key": row["alert_key"],
                "page": page,
                "reason": "all_hints_already_in_review_history",
                "resolved_hints": resolved,
            })
        else:
            planned = dict(row)
            planned["hints"] = unresolved
            planned["hint_count"] = len(unresolved)
            planned["resolved_hint_count"] = len(resolved)
            planned_alerts.append(planned)

    return {
        "schema_version": 1,
        "source_chain": "lidl",
        "flyer_key": flyer_key,
        "source_raw_sha256": raw_sha,
        "parser_version": parser_version,
        "source_snapshot_id": str(snapshot.id),
        "candidate_seed_count": len(planned_candidates),
        "candidate_suppressed_count": len(suppressed_candidates),
        "page_alert_seed_count": len(planned_alerts),
        "page_alert_suppressed_count": len(suppressed_alerts),
        "planned_candidates": planned_candidates,
        "suppressed_candidates": suppressed_candidates,
        "planned_page_alerts": planned_alerts,
        "suppressed_page_alerts": suppressed_alerts,
    }


def _candidate_seed_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    valid_from, valid_until = _flyer_validity(str(row["flyer_key"]))
    return {
        "review_kind": "product",
        "product_name": row.get("product_name"),
        "price_eur": row.get("price_eur"),
        "valid_from": valid_from,
        "valid_until": valid_until,
        "scope": "review",
        "channel": "physical_store",
        "weekly_evidence_kind": row.get("evidence_kind"),
    }


def _page_alert_seed_payload(row: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "review_kind": "page_alert",
        "title": f"Lidl bukleta lapa {int(row['page'])}",
        "hint_count": int(row.get("hint_count") or 0),
        "hints": [dict(value) for value in (row.get("hints") or [])],
        "manual_completion_expected": True,
        "scope": "review",
        "channel": "physical_store",
    }


def apply_weekly_review_bridge(
    db: Session,
    *,
    candidates: Iterable[Mapping[str, Any]],
    page_alerts: Iterable[Mapping[str, Any]],
) -> dict[str, Any]:
    candidate_rows = [dict(row) for row in candidates]
    alert_rows = [dict(row) for row in page_alerts]
    plan = plan_weekly_review_bridge(db, candidates=candidate_rows, page_alerts=alert_rows)
    snapshot_id = UUID(plan["source_snapshot_id"])

    seeded_candidates: list[str] = []
    for row in plan["planned_candidates"]:
        item = seed_review_item(
            db,
            source_chain="lidl",
            source_snapshot_id=snapshot_id,
            source_flyer_key=str(row["flyer_key"]),
            source_row_key=str(row["candidate_key"]),
            page_number=int(row["page"]),
            parser_version=str(row["parser_version"]),
            reason_codes=[NATIVE_GAP_REASON, SCOPE_REVIEW_REASON],
            original_payload=_candidate_seed_payload(row),
            provenance_json={
                "source_pdf_sha256": row.get("source_pdf_sha256"),
                "source_raw_sha256": row.get("source_raw_sha256"),
                "title_bbox": row.get("title_bbox"),
                "weekly_candidate_key": row.get("candidate_key"),
                "weekly_workflow_version": row.get("workflow_version"),
            },
        )
        seeded_candidates.append(str(item.id))

    seeded_alerts: list[str] = []
    for row in plan["planned_page_alerts"]:
        item = seed_review_item(
            db,
            source_chain="lidl",
            source_snapshot_id=snapshot_id,
            source_flyer_key=str(row["flyer_key"]),
            source_row_key=str(row["alert_key"]),
            page_number=int(row["page"]),
            parser_version=str(row["parser_version"]),
            reason_codes=[PAGE_ALERT_REASON],
            original_payload=_page_alert_seed_payload(row),
            provenance_json={
                "source_pdf_sha256": row.get("source_pdf_sha256"),
                "source_raw_sha256": row.get("source_raw_sha256"),
                "weekly_alert_key": row.get("alert_key"),
                "weekly_workflow_version": row.get("workflow_version"),
                "page_gate": row.get("page_gate"),
                "page_gate_source": row.get("page_gate_source"),
            },
        )
        seeded_alerts.append(str(item.id))

    return {
        **plan,
        "seeded_candidate_ids": seeded_candidates,
        "seeded_page_alert_ids": seeded_alerts,
    }


def create_review_from_page_alert_hint(
    db: Session,
    *,
    alert_item_id: UUID,
    hint_index: int,
) -> OfferReviewItem:
    alert = get_review_item(db, alert_item_id)
    payload = dict(alert.original_payload or {})
    if payload.get("review_kind") != "page_alert":
        raise ValueError("Review item is not a page alert")
    if alert.status not in {"pending", "draft", "needs_followup"}:
        raise ValueError("Page alert is already closed")
    if alert.source_snapshot_id is None:
        raise ValueError("Page alert is not provenance-bound")

    hints = payload.get("hints") or []
    if isinstance(hint_index, bool) or hint_index < 0 or hint_index >= len(hints):
        raise ValueError("Page alert hint index is out of range")
    hint = dict(hints[hint_index])
    stable = blake2s(
        (
            str(alert.source_row_key)
            + "|"
            + str(hint_index)
            + "|"
            + str(hint.get("product_name_hint") or "")
            + "|"
            + repr(hint.get("title_bbox"))
        ).encode("utf-8"),
        digest_size=12,
    ).hexdigest()
    source_row_key = f"page-alert-hint-{stable}"
    valid_from, valid_until = _flyer_validity(alert.source_flyer_key)

    return seed_review_item(
        db,
        source_chain=alert.source_chain,
        source_snapshot_id=alert.source_snapshot_id,
        source_flyer_key=alert.source_flyer_key,
        source_row_key=source_row_key,
        page_number=alert.page_number,
        parser_version=alert.parser_version,
        reason_codes=[PAGE_HINT_REASON, SCOPE_REVIEW_REASON],
        original_payload={
            "review_kind": "product",
            "product_name": hint.get("product_name_hint") or hint.get("native_title"),
            "price_eur": None,
            "valid_from": valid_from,
            "valid_until": valid_until,
            "scope": "review",
            "channel": "physical_store",
            "weekly_page_alert_parent_id": str(alert.id),
        },
        provenance_json={
            **dict(alert.provenance_json or {}),
            "parent_page_alert_id": str(alert.id),
            "parent_page_alert_key": alert.source_row_key,
            "hint_index": int(hint_index),
            "title_bbox": hint.get("title_bbox"),
            "native_title": hint.get("native_title"),
            "product_name_hint": hint.get("product_name_hint"),
            "evidence_kind": hint.get("evidence_kind"),
        },
    )
