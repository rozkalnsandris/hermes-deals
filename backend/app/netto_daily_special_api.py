from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal, ROUND_HALF_UP
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from typing import Any
from uuid import NAMESPACE_URL, UUID, uuid5
from zoneinfo import ZoneInfo
import json

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select, text
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import SourceSnapshot
from app.parsers.netto_daily_special import (
    extract_pdf_daily_special_candidates,
)
from app.retailer_targeted_shadow import (
    publication_page_paths,
    publitas_page_image_url,
)
from app.schemas import OfferCandidate, SourceChain


router = APIRouter()

_PARSER_VERSION = "netto-daily-special-v4-geometry"
_SOURCE_STORE_EXTERNAL_ID = "5659"
_SOURCE_STORE_NAME = (
    "Netto Marken-Discount — Dortmund, Rauschenbuschstr. 1"
)


class DailySpecialDealOut(BaseModel):
    offer_candidate_id: UUID
    source_chain: str
    source_store_external_id: str | None
    source_store_name: str | None
    source_offer_id: str
    product_name_raw: str
    brand_raw: str | None
    package_text_raw: str | None
    price_eur: Decimal
    regular_price_eur: Decimal | None
    unit_price_eur: Decimal | None
    unit_label: str | None
    pricing_mode: str | None
    discount_percent: int | None
    app_price_eur: Decimal | None
    requires_app: bool
    coupon_required: bool
    valid_from: date
    valid_until: date
    app_valid_from: date | None
    app_valid_until: date | None
    base_price_current: bool
    app_price_current: bool
    source_url: str
    source_image_url: str | None
    collected_at: datetime
    canonical_product_id: UUID | None
    canonical_comparable: bool
    is_daily_special: bool
    special_valid_on: date
    special_type: str
    special_source_text: str
    special_source_kind: str
    special_source_page: int
    special_confidence: str
    bundle_quantity: int | None
    single_price_eur: Decimal | None
    shadow_only: bool
    source_snapshot_id: UUID
    source_snapshot_sha256: str


class DailySpecialDealsOut(BaseModel):
    as_of: date
    timezone: str
    available_count: int
    count: int
    retailer_counts: dict[str, int]
    source_contract: str
    deals: list[DailySpecialDealOut]


def _discount_percent(
    price: Decimal,
    regular_price: Decimal | None,
) -> int | None:
    if regular_price is None or regular_price <= price:
        return None
    value = (
        (regular_price - price)
        / regular_price
        * Decimal("100")
    )
    return int(value.quantize(Decimal("1"), rounding=ROUND_HALF_UP))


def _verify_file(
    path_value: str | None,
    expected_sha: str | None,
    label: str,
) -> Path | None:
    if not path_value:
        return None
    if not isinstance(path_value, str):
        raise RuntimeError(f"{label} path is invalid")
    if expected_sha is not None and not isinstance(expected_sha, str):
        raise RuntimeError(f"{label} SHA is invalid")
    path = Path(path_value)
    if not path.is_file():
        raise RuntimeError(f"{label} file is missing: {path}")
    actual = sha256(path.read_bytes()).hexdigest()
    if expected_sha and actual != expected_sha:
        raise RuntimeError(
            f"{label} SHA mismatch: expected={expected_sha} actual={actual}"
        )
    return path


def _publication_images(manifest: dict[str, Any]) -> dict[int, str]:
    publication_path = _verify_file(
        manifest.get("publication_path"),
        manifest.get("publication_sha256"),
        "Netto publication JSON",
    )
    if publication_path is None:
        return {}
    payload = json.loads(publication_path.read_text(encoding="utf-8"))
    result: dict[int, str] = {}
    for page_number, page_path in enumerate(
        publication_page_paths(payload),
        start=1,
    ):
        result[page_number] = publitas_page_image_url(
            page_path,
            "at1600",
        )
    return result


@lru_cache(maxsize=8)
def _cached_snapshot_offers(
    snapshot_id: str,
    snapshot_path: str,
    snapshot_sha256: str,
    source_url: str,
    final_url: str,
    collected_at: str,
) -> tuple[OfferCandidate, ...]:
    manifest_path = _verify_file(
        snapshot_path,
        snapshot_sha256,
        "Netto manifest",
    )
    if manifest_path is None:
        raise RuntimeError("Netto manifest path is missing")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    if not isinstance(manifest, dict):
        raise RuntimeError("Netto manifest must be a JSON object")
    pdf_path = _verify_file(
        manifest.get("prospect_pdf_path"),
        manifest.get("prospect_pdf_sha256"),
        "Netto prospect PDF",
    )
    if pdf_path is None:
        raise RuntimeError("Netto prospect PDF path is missing")
    if str(manifest.get("store_external_id")) != _SOURCE_STORE_EXTERNAL_ID:
        raise RuntimeError("Netto daily-special manifest store mismatch")
    if manifest.get("scope") != "family_primary_netto":
        raise RuntimeError("Netto daily-special manifest scope mismatch")
    prospect_slug = manifest.get("prospect_slug")
    if not isinstance(prospect_slug, str) or not prospect_slug:
        raise RuntimeError("Netto daily-special manifest prospect slug is missing")

    image_by_page = _publication_images(manifest)
    offers: list[OfferCandidate] = []
    for special_page, page_candidates, page_text_sha in (
        extract_pdf_daily_special_candidates(
            pdf_path,
            snapshot_id=snapshot_id,
        )
    ):
        for candidate in page_candidates:
            regular_price = candidate.regular_price_eur
            if regular_price is not None and regular_price <= candidate.price_eur:
                regular_price = None
            raw_payload = {
                "is_daily_special": True,
                "special_valid_on": candidate.special_valid_on.isoformat(),
                "special_type": candidate.special_type,
                "special_source_text": candidate.special_source_text,
                "special_source_kind": candidate.special_source_kind,
                "special_source_page": candidate.special_source_page,
                "special_confidence": candidate.special_confidence,
                "special_source_geometry": list(
                    special_page.special_source_geometry
                ),
                "bundle_quantity": candidate.bundle_quantity,
                "single_price_eur": (
                    str(candidate.single_price_eur)
                    if candidate.single_price_eur is not None
                    else None
                ),
                "source_text_excerpt": candidate.source_text_excerpt,
                "source_geometry": list(candidate.source_geometry),
                "source_page_text_sha256": page_text_sha,
                "source_snapshot_binding": True,
                "source_snapshot_id": snapshot_id,
                "source_snapshot_sha256": snapshot_sha256,
                "source_pdf_sha256": manifest["prospect_pdf_sha256"],
                "campaign_prospect_slug": prospect_slug,
                "shadow_only": True,
                "db_write_eligible": False,
            }
            offers.append(
                OfferCandidate(
                    source_chain=SourceChain.NETTO,
                    source_store_external_id=_SOURCE_STORE_EXTERNAL_ID,
                    source_store_name=_SOURCE_STORE_NAME,
                    source_offer_id=candidate.source_offer_id,
                    product_name_raw=candidate.product_name_raw,
                    brand_raw=None,
                    description_raw=(
                        "Netto explicit one-day prospect offer"
                    ),
                    package_text_raw=candidate.package_text_raw,
                    price_eur=candidate.price_eur,
                    regular_price_eur=regular_price,
                    unit_price_eur=candidate.unit_price_eur,
                    unit_label=candidate.unit_label,
                    pricing_mode=candidate.pricing_mode,
                    discount_percent=_discount_percent(
                        candidate.price_eur,
                        regular_price,
                    ),
                    requires_app=False,
                    coupon_required=False,
                    valid_from=candidate.valid_from,
                    valid_until=candidate.valid_until,
                    source_url=final_url or source_url,
                    source_image_url=image_by_page.get(
                        candidate.special_source_page
                    ),
                    snapshot_id=UUID(snapshot_id),
                    collected_at=datetime.fromisoformat(collected_at),
                    parser_version=_PARSER_VERSION,
                    raw_payload=raw_payload,
                )
            )
    return tuple(offers)


def _assert_read_only_session(db: Session) -> None:
    bind = db.get_bind()
    if bind.dialect.name != "postgresql":
        return
    try:
        # This is the first database statement in the request. Scope the
        # endpoint's own transaction as read-only instead of requiring the
        # whole production database to be read-only; collectors still need
        # normal write transactions outside this route.
        db.execute(text("SET TRANSACTION READ ONLY"))
        transaction_mode = db.execute(
            text("SHOW transaction_read_only")
        ).scalar_one()
    except Exception as exc:
        raise HTTPException(
            status_code=503,
            detail="Daily-special endpoint could not enforce a read-only session",
        ) from exc
    if transaction_mode != "on":
        raise HTTPException(
            status_code=503,
            detail=(
                "Daily-special endpoint requires a read-only "
                "database session"
            ),
        )


def _latest_snapshot(db: Session) -> SourceSnapshot:
    snapshot = db.scalar(
        select(SourceSnapshot)
        .where(
            SourceSnapshot.source_chain == "netto",
            SourceSnapshot.scope == "family_primary_netto",
            SourceSnapshot.success.is_(True),
        )
        .order_by(SourceSnapshot.collected_at.desc())
        .limit(1)
    )
    if snapshot is None or not snapshot.snapshot_path or not snapshot.sha256:
        raise HTTPException(
            status_code=503,
            detail="Latest immutable Netto snapshot is unavailable",
        )
    return snapshot


def _to_output(
    offer: OfferCandidate,
    effective_date: date,
) -> DailySpecialDealOut:
    raw = offer.raw_payload
    if raw.get("is_daily_special") is not True:
        raise RuntimeError("Shadow offer lacks explicit daily-special evidence")
    special_valid_on = date.fromisoformat(raw["special_valid_on"])
    return DailySpecialDealOut(
        offer_candidate_id=uuid5(
            NAMESPACE_URL,
            f"hermes-deals:{offer.source_offer_id}",
        ),
        source_chain=offer.source_chain.value,
        source_store_external_id=offer.source_store_external_id,
        source_store_name=offer.source_store_name,
        source_offer_id=offer.source_offer_id or "",
        product_name_raw=offer.product_name_raw,
        brand_raw=offer.brand_raw,
        package_text_raw=offer.package_text_raw,
        price_eur=offer.price_eur,
        regular_price_eur=offer.regular_price_eur,
        unit_price_eur=offer.unit_price_eur,
        unit_label=offer.unit_label,
        pricing_mode=offer.pricing_mode,
        discount_percent=offer.discount_percent,
        app_price_eur=offer.app_price_eur,
        requires_app=offer.requires_app,
        coupon_required=offer.coupon_required,
        valid_from=offer.valid_from or special_valid_on,
        valid_until=offer.valid_until or special_valid_on,
        app_valid_from=offer.app_valid_from,
        app_valid_until=offer.app_valid_until,
        base_price_current=(special_valid_on == effective_date),
        app_price_current=False,
        source_url=str(offer.source_url),
        source_image_url=(
            str(offer.source_image_url)
            if offer.source_image_url is not None
            else None
        ),
        collected_at=offer.collected_at,
        canonical_product_id=None,
        canonical_comparable=False,
        is_daily_special=True,
        special_valid_on=special_valid_on,
        special_type=raw["special_type"],
        special_source_text=raw["special_source_text"],
        special_source_kind=raw["special_source_kind"],
        special_source_page=int(raw["special_source_page"]),
        special_confidence=raw["special_confidence"],
        bundle_quantity=raw.get("bundle_quantity"),
        single_price_eur=(
            Decimal(raw["single_price_eur"])
            if raw.get("single_price_eur") is not None
            else None
        ),
        shadow_only=True,
        source_snapshot_id=offer.snapshot_id,
        source_snapshot_sha256=raw["source_snapshot_sha256"],
    )


@router.get(
    "/api/v1/deals/daily-specials",
    response_model=DailySpecialDealsOut,
)
def daily_specials(
    as_of: date | None = Query(default=None),
    db: Session = Depends(get_db),
) -> DailySpecialDealsOut:
    _assert_read_only_session(db)
    effective_date = (
        as_of
        if as_of is not None
        else datetime.now(ZoneInfo("Europe/Berlin")).date()
    )
    snapshot = _latest_snapshot(db)
    try:
        offers = _cached_snapshot_offers(
            str(snapshot.id),
            snapshot.snapshot_path or "",
            snapshot.sha256 or "",
            snapshot.source_url,
            snapshot.final_url or "",
            snapshot.collected_at.isoformat(),
        )
    except RuntimeError as exc:
        if str(exc) == "Netto prospect PDF path is missing":
            # No PDF means there is no explicit daily-special evidence for
            # this snapshot. Preserve the explicit-evidence-only contract:
            # return an empty result instead of inferring from ordinary HTML
            # offers. All other evidence failures remain fail-closed.
            offers = ()
        else:
            raise HTTPException(
                status_code=503,
                detail=f"Netto daily-special evidence unavailable: {exc}",
            ) from exc
    except (OSError, ValueError, json.JSONDecodeError, ImportError) as exc:
        raise HTTPException(
            status_code=503,
            detail=f"Netto daily-special evidence unavailable: {exc}",
        ) from exc

    selected = [
        _to_output(offer, effective_date)
        for offer in offers
        if offer.raw_payload.get("is_daily_special") is True
        and offer.raw_payload.get("special_valid_on")
        == effective_date.isoformat()
    ]
    selected.sort(
        key=lambda row: (
            row.source_chain,
            row.product_name_raw.casefold(),
            row.price_eur,
            row.source_offer_id,
        )
    )
    retailer_counts: dict[str, int] = {}
    for row in selected:
        retailer_counts[row.source_chain] = (
            retailer_counts.get(row.source_chain, 0) + 1
        )

    return DailySpecialDealsOut(
        as_of=effective_date,
        timezone="Europe/Berlin",
        available_count=len(selected),
        count=len(selected),
        retailer_counts=retailer_counts,
        source_contract="explicit_immutable_retailer_evidence_only",
        deals=selected,
    )
