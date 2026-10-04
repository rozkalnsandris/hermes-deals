"""Project existing offer services into the north-star UI. No demo imports/data."""
from datetime import date, datetime, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from urllib.parse import urlsplit
from uuid import UUID
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.basket_plan import best_two_store_plan
from app.current_deals_service import build_current_deals
from app.current_deals_sql_loader import load_sql_ranked_state_rows, materialize_only
from app.household_service import read_household
from app.meal_service import meal_context, quantity_label
from app.meal_pricing import INGREDIENTS, requirement_price
from app.models import OfferCandidateRecord
from app.price_intelligence import build_offer_price_intelligence, summarize_price_history, _series_predicate

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


def offer_view(row, day, *, favorite_id=None, eligibility=None):
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
    approved = (eligibility or {}).get(str(getattr(row, "offer_candidate_id", None) or row.id), {})
    coupon_ok = not row.coupon_required or approved.get("coupon", False)
    candidates = []
    if base_current and coupon_ok and (not row.requires_app or approved.get("app")) and row.price_eur is not None:
        candidates.append((row.price_eur, bool(row.requires_app or row.coupon_required)))
    if app_current and coupon_ok and approved.get("app"):
        candidates.append((row.app_price_eur, True))
    usable = min(candidates) if candidates and fixed and (row.package_text_raw or "").strip() else None
    # Keep source display and history separate from household eligibility.
    regular = row.regular_price_eur if fixed and base_current else None
    savings = regular - amount if regular is not None and amount is not None and regular > amount and not conditions else None
    row_id = getattr(row, "offer_candidate_id", None) or row.id
    return {"is_current": bool((base_current or app_current) and amount is not None), "id": str(row_id), "name": row.product_name_raw, "package": row.package_text_raw or "Iepakojums nav norādīts",
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
            "pack_price": usable[0] if usable else None,
            "household_price_label": money(usable[0]) if usable else "—",
            "conditional_price_used": bool(usable and usable[1]),
            "has_price_conditions": bool(row.requires_app or row.coupon_required or row.app_price_eur is not None),
            "needs_app": bool(row.requires_app or row.app_price_eur is not None), "needs_coupon": bool(row.coupon_required),
            "app_approved": bool(approved.get("app")), "coupon_approved": bool(approved.get("coupon")),
            "regular_price": regular, "collected_label": observed.astimezone(ZoneInfo("Europe/Berlin")).strftime("%d.%m.%Y %H:%M") + " (Berlīne)"}


def latest_series(db, original, day):
    end = datetime.combine(day + timedelta(days=1), time.min, tzinfo=ZoneInfo("Europe/Berlin")).astimezone(timezone.utc)
    return db.scalar(select(OfferCandidateRecord).where(
        _series_predicate(original), OfferCandidateRecord.collected_at < end,
    ).order_by(OfferCandidateRecord.collected_at.desc(), OfferCandidateRecord.id.asc()).limit(1)) or original


def history_view(*details_list):
    """Build one small chart from one to three saved product histories.

    The overview deliberately keeps the series separate: the chart helps follow
    each saved product's own package price, it does not assert that differently
    packaged products are directly comparable.
    """
    details_list = tuple(details for details in details_list if details)
    summary = summarize_price_history(details_list[0]) if len(details_list) == 1 else None
    if summary:
        change = summary["change"]
        summary = {**summary, "price_label": money(summary["price"]), "minimum_label": money(summary["minimum"]),
                   "maximum_label": money(summary["maximum"]), "change_label": money(abs(change)) if change is not None else None,
                   "start_label": summary["start"].strftime("%d.%m.%Y"), "end_label": summary["end"].strftime("%d.%m.%Y"),
                   "previous_day_label": summary["previous_day"].strftime("%d.%m.%Y") if summary["previous_day"] else None}
    def local_stamp(value):
        aware = value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value
        return aware.astimezone(ZoneInfo("Europe/Berlin"))
    def utc_stamp(value):
        return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)
    row_groups = [sorted((row for row in details.observations if row.comparison_price_eur is not None), key=lambda row: utc_stamp(row.collected_at))
                  for details in details_list]
    rows = [row for group in row_groups for row in group]
    maximum = max((row.comparison_price_eur for row in rows), default=D(1)) * D("1.15")
    maximum = max(maximum, D(1))
    first = min((utc_stamp(row.collected_at) for row in rows), default=None)
    last = max((utc_stamp(row.collected_at) for row in rows), default=None)
    span = max(1, (last - first).total_seconds()) if rows else 1
    colors = ("#32895d", "#3977c6", "#c98a14")
    series = []
    for index, group in enumerate(row_groups):
        if not group:
            continue
        observations, points = [], []
        for row in group:
            x = (utc_stamp(row.collected_at) - first).total_seconds() / span * 600
            y = 160 - float(row.comparison_price_eur / maximum) * 140
            points.append(f"{x:.1f},{y:.1f}")
            observations.append({"date": local_stamp(row.collected_at).strftime("%d.%m.%Y %H:%M") + " (Berlīne)", "price_label": money(row.comparison_price_eur),
                                 "package": row.package_text_raw, "source_url": safe_url(row.source_url),
                                 "valid_label": f"{row.valid_from}–{row.valid_until}", "requires_app": row.requires_app, "coupon_required": row.coupon_required})
        series.append({"name": group[-1].product_name_raw, "offer_id": str(details_list[index].offer_candidate_id),
                       "basis_label": (group[-1].package_text_raw or "Iepakojums nav norādīts") if details_list[index].history_basis == "package" else "par " + (details_list[index].history_basis or "nezināmu vienību"),
                       "color": colors[index], "points": " ".join(points),
                       "price_label": money(group[-1].comparison_price_eur) + ("/" + details_list[index].history_basis if details_list[index].history_basis not in {None, "package"} else ""), "observations": observations})
    labels = [local_stamp(first).strftime("%d.%m.%Y"), local_stamp(last).strftime("%d.%m.%Y")] if rows else []
    return {"series": series, "labels": labels, "max_label": money(maximum), "min_label": "0 €",
            "basis": details_list[0].history_basis if len(details_list) == 1 else None,
            "truncated": any(details.history_truncated for details in details_list), "summary": summary}


def build_live_context(db: Session, household_id: str, day: date, *, view="overview", query="", retailer="", product=None, offset=0):
    state, version = read_household(db, household_id)
    def quote_for(row, *, favorite_id=None):
        return offer_view(row, day, favorite_id=favorite_id, eligibility=state.get("price_eligibility", {}))

    # Same Python service as JSON; no HTTP call to our own API and no browser pricing rules.
    with materialize_only("current"):
        current = build_current_deals(db=db, effective_date=day, q=query or None, retailer=retailer or None,
                                     view="current", app_only=False, coupon_only=False, discount_only=False, image_only=False,
                                     sort="name", offset=offset, limit=60, state_row_loader=load_sql_ranked_state_rows)
    bindings = state.get("ingredient_offers", {})
    references = set(bindings.values()) | set(state["favorites"]) | {item["product_id"] for item in state["shopping"] if item["product_id"]}
    originals = {str(row.id): row for row in db.scalars(select(OfferCandidateRecord).where(OfferCandidateRecord.id.in_([UUID(key) for key in references])))} if references else {}
    latest = {key: latest_series(db, row, day) for key, row in originals.items()}
    favorite_latest = {str(latest[key].id): key for key in state["favorites"] if key in latest}
    offers = [quote_for(row, favorite_id=favorite_latest.get(str(row.offer_candidate_id))) for row in current.deals]
    favorites = [quote_for(latest[key], favorite_id=key) for key in state["favorites"] if key in latest]
    # Explicit household choices only; independent of the first catalogue page.
    personal = {}
    choices = [(item["product_id"], "Tavā sarakstā", 0) for item in state["shopping"]
               if item["product_id"] and not item["checked"] and not item.get("meal_week")]
    choices += [(key, "Saglabāts favorītos", 1) for key in state["favorites"]]
    choices += [(key, "Izvēlēts receptēm", 2) for key in bindings.values()]
    for reference, reason, priority in choices:
        row = latest.get(reference)
        if row is None:
            continue
        quote = quote_for(row, favorite_id=favorite_latest.get(str(row.id)))
        if not quote["is_current"]:
            continue
        entry = personal.setdefault(quote["id"], {**quote, "reasons": [], "priority": priority})
        if reason not in entry["reasons"]:
            entry["reasons"].append(reason)
        entry["priority"] = min(entry["priority"], priority)
    personal_offers = sorted(personal.values(), key=lambda row: (row["priority"], row["name"].casefold(), row["id"]))
    preferred = state.get("preferred_retailers", [key for key, _ in STORES])
    excluded_branches = set(state.get("excluded_branches", []))
    branch_options = {}
    for key in excluded_branches:
        chain, store_id = key.split(":", 1)
        branch_options[key] = {"chain": chain, "store_id": store_id, "name": dict(STORES).get(chain, chain), "enabled": False}
    basket_lines = []
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
        row = latest.get(bindings.get(item.get("ingredient_id")) if item.get("meal_week") else item["product_id"])
        quote = quote_for(row) if row else None
        amount = quote["pack_price"] if quote else None
        quantity = item["quantity"]
        measured = requirement_price(row, item["amount"], item["unit"], amount) if row and item.get("meal_week") else None
        if item.get("meal_week"):
            quantity = measured["packs"] if measured else 1
            amount = amount if measured else None
        shopping_rows.append({**item, "offer_id": quote["id"] if quote else None, "offer_name": quote["name"] if quote else None, "purchase_note": f"{quantity} iepak. · {quote['name']} ({quote['package']})" if measured else "", "package": quantity_label(item["amount"], item["unit"]) if item.get("meal_week") else quote["package"] if quote else "Brīvs ieraksts",
                              "retailer": quote["retailer"] if quote else "Cena nav zināma", "conditional_price_used": bool(quote and quote["conditional_price_used"]),
                              "price_label": money(amount * quantity) if amount is not None else "—"})
        if item["checked"]:
            continue
        if amount is None:
            unknown += 1
        else:
            total += amount * quantity
        basket_line = {"item_id": item["item_id"], "name": item["name"], "prices": {}, "details": {}}
        basket_lines.append(basket_line)
        if row and amount is not None:
            comparisons = detail(row).offers
            by_store = {}
            # Selected source price remains useful even without a cross-store link.
            candidates = [(row.source_chain, row.source_store_external_id, amount * quantity, f"{quantity} × {row.package_text_raw}" + (" · apstiprināta nosacītā cena" if quote["conditional_price_used"] else ""), str(row.id))]
            for compared in comparisons:
                compared_row = db.get(OfferCandidateRecord, compared.offer_candidate_id)
                compared_quote = quote_for(compared_row)
                if compared_quote["pack_price"] is None:
                    continue
                if not item.get("meal_week") and compared_row.package_text_raw != row.package_text_raw:
                    continue
                line_price = compared_quote["pack_price"] * quantity
                compared_quantity = quantity
                if item.get("meal_week"):
                    measured_comparison = requirement_price(compared_row, item["amount"], item["unit"], compared_quote["pack_price"])
                    if measured_comparison is None:
                        continue
                    line_price = measured_comparison["purchase_cost"]
                    compared_quantity = measured_comparison["packs"]
                candidates.append((compared.source_chain, compared.source_store_external_id, line_price, f"{compared_quantity} × {compared_row.package_text_raw}" + (" · apstiprināta nosacītā cena" if compared_quote["conditional_price_used"] else ""), str(compared.offer_candidate_id)))
            for chain, store_id, price, note, offer_id in candidates:
                key = (chain, store_id)
                if key not in by_store or price < by_store[key]["price"]:
                    by_store[key] = {"price": price, "purchase_note": note, "offer_id": offer_id}
            # Do not blend branches of a chain into an imaginary single-store basket.
            for (chain, store_id), option in by_store.items():
                price = option["price"]
                if not store_id:
                    continue
                key = f"{chain}:{store_id}"
                branch_options[key] = {"chain": chain, "store_id": store_id, "name": dict(STORES).get(chain, chain), "enabled": key not in excluded_branches}
                if chain not in preferred or key in excluded_branches:
                    continue
                bucket = buckets.setdefault(key, {"id": chain, "name": dict(STORES).get(chain, chain), "store_id": store_id,
                                                   "total": D(0), "coverage": 0})
                basket_line["prices"][key] = price
                basket_line["details"][key] = option
                bucket["total"] += price
                bucket["coverage"] += 1
    ranked = [value for key, value in buckets.items() if ":" in key]
    for bucket in ranked:
        bucket.update(required=required, complete=bool(required) and bucket["coverage"] == required,
                      total_label=money(bucket["total"]), savings_label="—", short="")
    ranked.sort(key=lambda s: (not s["complete"], -s["coverage"], s["total"]))
    best_single = next((s for s in ranked if s["complete"]), None)
    pair, pair_status = best_two_store_plan(basket_lines, buckets, best_single["total"] if best_single else None)
    if pair:
        pair.update(total_label=money(pair["total"]), savings_label=money(pair["savings"]))
        for line in pair["lines"]:
            line["price_label"] = money(line["price"])
            line["store"] = buckets[line["store_key"]]
    selected = None
    if product:
        try:
            selected_row = db.get(OfferCandidateRecord, UUID(product))
        except (ValueError, TypeError):
            selected_row = None
        if selected_row:
            data = detail(selected_row)
            selected = {**quote_for(selected_row, favorite_id=favorite_latest.get(str(selected_row.id))),
                        "comparison": [quote_for(db.get(OfferCandidateRecord, o.offer_candidate_id)) for o in data.offers],
                        "comparison_status": data.comparison_status, "history": history_view(data)}
    history_references = state["favorites"] + [item["product_id"] for item in state["shopping"]
                                                  if item["product_id"] and not item["checked"]]
    history_products, seen_history_products = [], set()
    for reference in history_references:
        row = latest.get(reference)
        if row and str(row.id) not in seen_history_products:
            history_products.append(row)
            seen_history_products.add(str(row.id))
        if len(history_products) == 3:
            break
    overview_history = history_view(*(detail(row) for row in history_products)) if view == "overview" else None
    start = day - timedelta(days=day.weekday())
    meals = meal_context(state, day)
    ingredient_quotes = {}
    for key, reference in bindings.items():
        row = latest.get(reference)
        if row:
            ingredient_quotes[key] = (row, quote_for(row))
    for recipe in meals["recipes"] + [d["recipe"] for d in meals["planner"] if d["recipe"]]:
        used, purchase, covered = D(0), D(0), 0
        conditional_used = False
        for ingredient in recipe["ingredients"]:
            selection = ingredient_quotes.get(ingredient["id"])
            price = requirement_price(selection[0], ingredient["amount"], ingredient["unit"], selection[1]["pack_price"]) if selection else None
            ingredient.update(product_name=selection[1]["name"] if selection else None,
                              price_label=money(price["used_cost"]) if price else "—")
            if price:
                covered += 1
                conditional_used = conditional_used or selection[1]["conditional_price_used"]
                used += price["used_cost"]
                purchase += price["purchase_cost"]
        complete = covered == len(recipe["ingredients"])
        recipe.update(cost_label=money(used / recipe["servings"]) if complete else "—",
                      purchase_label=money(purchase) if complete else "—", known_cost_label=money(used) if covered else "—",
                      price_coverage=f"{covered}/{len(recipe['ingredients'])}", price_complete=complete, conditional_price_used=conditional_used)
    return {**meals, "ingredient_choices": list(INGREDIENTS.values()), "demo": False, "base_path": "/ui/home", "view": view, "state_version": version,
            "selected_date": day.isoformat(), "week_label": f"{day.isocalendar().week}. nedēļa ({start:%d.%m.} – {start + timedelta(days=6):%d.%m.%Y})",
            "prev_date": (day - timedelta(days=7)).isoformat(), "next_date": (day + timedelta(days=7)).isoformat(),
            "settings": state["settings"], "personal_offers": personal_offers, "offers": offers, "favorites": favorites, "retailers": [{"id": key, "name": name} for key, name in STORES],
            "shopping": {"rows": shopping_rows, "count": len(shopping_rows), "checked_count": sum(item["checked"] for item in shopping_rows),
                         "total_label": money(None if required and unknown == required else total), "unknown_count": unknown, "required": required},
            "ranked_stores": ranked, "best_store": best_single, "two_store_plan": pair, "pair_status": pair_status, "preferred_retailers": preferred, "branch_options": [branch_options[key] for key in sorted(branch_options)],
            "binding_choices": [item for item in shopping_rows if not item["checked"] and not item.get("meal_week")], "selected_product": selected, "overview_history": overview_history, "history_product_id": str(history_products[0].id) if history_products else None, "history_product_ids": [str(row.id) for row in history_products], "has_offers": bool(current.available_count), "available_count": current.available_count,
            "query": query, "retailer": retailer, "offset": offset, "next_offset": offset + 60 if offset + 60 < current.available_count else None,
            "previous_offset": max(0, offset - 60) if offset else None, "total_count": current.available_count,
            "notice": "", "read_error": False}
