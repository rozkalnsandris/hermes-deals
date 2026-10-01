"""Project existing offer services into the north-star UI. No demo imports/data."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.current_deals_service import build_current_deals
from app.current_deals_sql_loader import load_sql_ranked_state_rows, materialize_only
from app.household_service import read_household
from app.models import OfferCandidateRecord
from app.price_intelligence import build_offer_price_intelligence, _series_predicate

D = Decimal
STORES = [("lidl", "LIDL"), ("netto", "Netto"), ("aldi_nord", "ALDI Nord"), ("edeka", "EDEKA")]
NAV = ["overview", "deals", "list", "planner", "recipes", "favorites", "history", "statistics", "settings"]
UNIT_MODES = {"unit_price_only", "example_total_plus_unit", "app_example_total_plus_unit"}


def money(value):
    return f"{D(value).quantize(D('.01'), rounding=ROUND_HALF_UP):.2f}".replace(".", ",") + " €" if value is not None else "—"


def safe_url(value):
    try:
        parsed = urlsplit(value or "")
        return value if parsed.scheme in {"https", "http"} and parsed.netloc and not parsed.username else None
    except ValueError:
        return None


def valid_window(start, end, day):
    return bool(start and end and start <= day <= end)


def offer_view(row, day, *, favorite_id=None):
    fixed = row.pricing_mode in {None, "fixed_package"}
    observed = row.collected_at.replace(tzinfo=timezone.utc) if row.collected_at.tzinfo is None else row.collected_at
    known = observed.astimezone(ZoneInfo("Europe/Berlin")).date() <= day
    base_current = known and valid_window(row.valid_from, row.valid_until, day)
    app_current = known and row.app_price_eur is not None and valid_window(row.app_valid_from, row.app_valid_until, day)
    conditions = []
    if row.requires_app or (not base_current and app_current):
        conditions.append("Nepieciešama veikala lietotne")
    if row.coupon_required:
        conditions.append("Nepieciešams kupons")
    if not fixed:
        conditions.append("Cena par vienību; iepakojuma summa nav salīdzināma" if row.pricing_mode in UNIT_MODES else "Cenas bāze nav apstiprināta")
    if not base_current and not app_current:
        conditions.append("Šajā datumā piedāvājums nav spēkā")
    amount = row.price_eur if base_current else row.app_price_eur if app_current else None
    if row.pricing_mode in UNIT_MODES:
        amount = row.unit_price_eur if base_current or app_current else None
    regular = row.regular_price_eur if fixed and base_current else None
    savings = regular - amount if regular is not None and amount is not None and regular > amount and not conditions else None
    row_id = getattr(row, "offer_candidate_id", None) or row.id
    return {"id": str(row_id), "name": row.product_name_raw, "package": row.package_text_raw or "Iepakojums nav norādīts",
            "category": "food", "emoji": "🛒", "image_url": safe_url(row.source_image_url), "source_url": safe_url(row.source_url),
            "retailer_id": row.source_chain, "retailer": dict(STORES).get(row.source_chain, row.source_chain),
            "store_name": row.source_store_name, "store_id": row.source_store_external_id,
            "price_label": money(amount) + (f"/{row.unit_label}" if not fixed and row.unit_label and amount is not None else ""),
            "reference_label": money(regular) if regular else None,
            "savings_label": money(savings), "discount": int(savings / regular * 100) if savings else None,
            "unit_price_label": money(row.unit_price_eur) + "/" + row.unit_label if row.unit_price_eur is not None and row.unit_label else "",
            "condition": " · ".join(conditions), "favorite": bool(favorite_id), "favorite_id": favorite_id or str(row_id),
            "valid_label": f"{row.valid_from:%d.%m.%Y}–{row.valid_until:%d.%m.%Y}" if row.valid_from and row.valid_until else "Derīgums nav norādīts",
            "app_price_label": money(row.app_price_eur) if app_current else None, "app_condition": "Ar veikala lietotni / kuponu",
            "pack_price": amount if fixed and base_current and row.package_text_raw and row.package_text_raw.strip() and not row.requires_app and not row.coupon_required else None,
            "regular_price": regular, "collected_label": observed.astimezone(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y %H:%M") + " (Berlīne)"}


def latest_series(db, original, day):
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=ZoneInfo("Europe/Berlin")).astimezone(timezone.utc)
    return db.scalar(select(OfferCandidateRecord).where(
        _series_predicate(original), OfferCandidateRecord.collected_at < end,
    ).order_by(OfferCandidateRecord.collected_at.desc(), OfferCandidateRecord.id.asc()).limit(1)) or original


def history_view(details):
    def local_stamp(value):
        aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        return aware.astimezone(ZoneInfo("Europe/Berlin"))
    rows = sorted((r for r in details.observations if r.comparison_price_eur is not None), key=lambda r: r.collected_at)
    maximum = max((r.comparison_price_eur for r in rows), default=D(1)) * D("1.15")
    maximum = max(maximum, D(1))
    first = rows[0].collected_at if rows else None
    span = max(1, (rows[-1].collected_at - first).total_seconds()) if rows else 1
    observations, points = [], []
    for row in rows:
        x = (row.collected_at - first).total_seconds() / span * 600
        y = 160 - float(row.comparison_price_eur / maximum) * 140
        points.append(f"{x:.1f},{y:.1f}")
        observations.append({"date": local_stamp(row.collected_at).strftime("%d.%m.%Y %H:%M") + " (Berlīne)", "price_label": money(row.comparison_price_eur),
                             "package": row.package_text_raw, "source_url": safe_url(row.source_url),
                             "valid_label": f"{row.valid_from}–{row.valid_until}", "requires_app": row.requires_app, "coupon_required": row.coupon_required})
    labels = [local_stamp(rows[0].collected_at).strftime("%d.%m.%Y"), local_stamp(rows[-1].collected_at).strftime("%d.%m.%Y")] if rows else []
    return {"series": [{"name": rows[-1].product_name_raw, "color": "#32895d", "points": " ".join(points),
                         "price_label": money(rows[-1].comparison_price_eur), "observations": observations}] if rows else [],
            "labels": labels, "max_label": money(maximum), "min_label": "0 €", "basis": details.history_basis,
            "truncated": details.history_truncated}


def build_live_context(db: Session, household_id: str, day: date, *, view="overview", query="", retailer="", product=None, offset=0):
    state, version = read_household(db, household_id)
    # Same Python service as JSON; no HTTP call to our own API and no browser pricing rules.
    with materialize_only("current"):
        current = build_current_deals(db=db, effective_date=day, q=query or None, retailer=retailer or None,
                                     view="current", app_only=False, coupon_only=False, discount_only=False, image_only=False,
                                     sort="name", offset=offset, limit=60, state_row_loader=load_sql_ranked_state_rows)
    references = set(state["favorites"]) | {item["product_id"] for item in state["shopping"] if item["product_id"]}
    originals = {str(row.id): row for row in db.scalars(select(OfferCandidateRecord).where(OfferCandidateRecord.id.in_([UUID(key) for key in references])))} if references else {}
    latest = {key: latest_series(db, row, day) for key, row in originals.items()}
    favorite_latest = {str(latest[key].id): key for key in state["favorites"] if key in latest}
    offers = [offer_view(row, day, favorite_id=favorite_latest.get(str(row.offer_candidate_id))) for row in current.deals]
    favorites = [offer_view(latest[key], day, favorite_id=key) for key in state["favorites"] if key in latest]
    shopping_rows, total, unknown = [], D(0), 0
    buckets = {key: {"id": key, "name": name, "total": D(0), "coverage": 0} for key, name in STORES}
    required = sum(not item["checked"] for item in state["shopping"])
    intelligence = {}

    def detail(row):
        key = str(row.id)
        if key not in intelligence:
            intelligence[key] = build_offer_price_intelligence(db, row.id, as_of=day)
        return intelligence[key]

    for item in state["shopping"]:
        row = latest.get(item["product_id"])
        quote = offer_view(row, day) if row else None
        amount = quote["pack_price"] if quote else None
        shopping_rows.append({**item, "package": quote["package"] if quote else "Brīvs ieraksts",
                              "retailer": quote["retailer"] if quote else "Cena nav zināma",
                              "price_label": money(amount * item["quantity"]) if amount is not None else "—"})
        if item["checked"]:
            continue
        if amount is None:
            unknown += 1
        else:
            total += amount * item["quantity"]
        if row and amount is not None:
            comparisons = detail(row).offers
            by_store = {}
            # Selected source price remains useful even without a cross-store link.
            candidates = [(row.source_chain, row.source_store_external_id, amount)]
            candidates += [(o.source_chain, o.source_store_external_id, o.price_eur) for o in comparisons if not o.requires_app and not o.coupon_required]
            for chain, store_id, price in candidates:
                key = (chain, store_id)
                by_store[key] = min(by_store.get(key, price), price)
            # Do not blend branches of a chain into an imaginary single-store basket.
            for (chain, store_id), price in by_store.items():
                if not store_id:
                    continue
                key = f"{chain}:{store_id or ''}"
                bucket = buckets.setdefault(key, {"id": chain, "name": dict(STORES).get(chain, chain), "store_id": store_id,
                                                   "total": D(0), "coverage": 0})
                bucket["total"] += price * item["quantity"]
                bucket["coverage"] += 1
    ranked = [value for key, value in buckets.items() if ":" in key]
    for bucket in ranked:
        bucket.update(required=required, complete=bool(required) and bucket["coverage"] == required,
                      total_label=money(bucket["total"]), savings_label="—", short="")
    ranked.sort(key=lambda s: (not s["complete"], -s["coverage"], s["total"]))
    selected = None
    if product:
        try:
            selected_row = db.get(OfferCandidateRecord, UUID(product))
        except (ValueError, TypeError):
            selected_row = None
        if selected_row:
            data = detail(selected_row)
            selected = {**offer_view(selected_row, day, favorite_id=favorite_latest.get(str(selected_row.id))),
                        "comparison": [offer_view(db.get(OfferCandidateRecord, o.offer_candidate_id), day) for o in data.offers],
                        "comparison_status": data.comparison_status, "history": history_view(data)}
    history_product = next((latest[key] for key in state["favorites"] if key in latest), None) if view == "overview" else None
    overview_history = history_view(detail(history_product)) if history_product else None
    start = day - timedelta(days=day.weekday())
    return {"demo": False, "base_path": "/ui/home", "view": view, "state_version": version,
            "selected_date": day.isoformat(), "week_label": f"{day.isocalendar().week}. nedēļa ({start:%d.%m.} – {start + timedelta(days=6):%d.%m.%Y})",
            "prev_date": (day - timedelta(days=7)).isoformat(), "next_date": (day + timedelta(days=7)).isoformat(),
            "settings": state["settings"], "offers": offers, "favorites": favorites, "retailers": [{"id": key, "name": name} for key, name in STORES],
            "shopping": {"rows": shopping_rows, "count": len(shopping_rows), "checked_count": sum(item["checked"] for item in shopping_rows),
                         "total_label": money(total), "unknown_count": unknown, "required": required},
            "ranked_stores": ranked, "best_store": next((s for s in ranked if s["complete"]), None),
            "selected_product": selected, "overview_history": overview_history, "history_product_id": str(history_product.id) if history_product else None, "has_offers": bool(current.available_count), "available_count": current.available_count,
            "query": query, "retailer": retailer, "offset": offset, "next_offset": offset + 60 if offset + 60 < current.available_count else None,
            "previous_offset": max(0, offset - 60) if offset else None, "total_count": current.available_count,
            "notice": "", "read_error": False}
