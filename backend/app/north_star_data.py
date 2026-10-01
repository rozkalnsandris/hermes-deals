"""Explicitly synthetic north-star data and calculations, isolated from live services.

All prices belong to this demonstration household/week. A future live adapter can
return the same context; it must never silently mix these fixtures with live data.
"""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal, ROUND_HALF_UP, ROUND_CEILING
from secrets import token_urlsafe

D = Decimal
WEEK_START = date(2026, 9, 28)
WEEK_END = date(2026, 10, 4)
DEFAULT_DATE = date(2026, 10, 1)
RETAILERS = [
    {"id": "lidl", "name": "LIDL", "short": "LIDL", "color": "#245bd7"},
    {"id": "netto", "name": "Netto", "short": "Netto", "color": "#c78b00"},
    {"id": "aldi_nord", "name": "ALDI Nord", "short": "ALDI", "color": "#2266a0"},
    {"id": "edeka", "name": "EDEKA", "short": "E", "color": "#d3a312"},
    {"id": "kaufland", "name": "Kaufland", "short": "K", "color": "#bd343d"},
]
# id, name, package, emoji, category, package base quantity, base unit, reference
_PRODUCT_ROWS = [
    ("chicken", "Vistas fileja", "1 kg", "🍗", "Gaļa un zivis", "1", "kg", "9.99"),
    ("milk", "Piens 3,5%", "1 l", "🥛", "Piena produkti", "1", "l", "1.19"),
    ("butter", "Sviests", "250 g", "🧈", "Piena produkti", ".25", "kg", "2.29"),
    ("peppers", "Paprika mix", "500 g", "🫑", "Augļi un dārzeņi", ".5", "kg", "1.79"),
    ("gouda", "Gouda siers", "1 kg", "🧀", "Piena produkti", "1", "kg", "8.49"),
    ("coffee", "Malta kafija", "500 g", "☕", "Pieliekamais", ".5", "kg", "6.49"),
    ("tortillas", "Tortiljas", "320 g · 8 gab.", "🫓", "Pieliekamais", ".32", "kg", "1.69"),
    ("salad", "Ledussalāti", "1 gab.", "🥬", "Augļi un dārzeņi", "1", "gab.", ".89"),
    ("pasta", "Makaroni", "500 g", "🍝", "Pieliekamais", ".5", "kg", "1.29"),
    ("tomatoes", "Tomāti", "500 g", "🍅", "Augļi un dārzeņi", ".5", "kg", "1.99"),
    ("potatoes", "Kartupeļi", "2 kg", "🥔", "Augļi un dārzeņi", "2", "kg", "2.99"),
    ("eggs", "Olas", "10 gab.", "🥚", "Piena produkti", "10", "gab.", "2.99"),
]
PRODUCTS = {
    row[0]: dict(zip(("id", "name", "package", "emoji", "category", "amount", "unit", "reference"), row))
    for row in _PRODUCT_ROWS
}
# Every column denotes an identical demonstration product/package at one retailer.
_PRICES = {
    "chicken": ("6.49", "7.29", "7.49", "8.49", "7.99"),
    "milk": (".95", ".89", ".99", "1.09", ".99"),
    "butter": ("1.49", "1.69", "1.59", "1.79", "1.89"),
    "peppers": ("1.49", "1.29", "1.39", "1.59", "1.69"),
    "gouda": ("5.99", "6.49", "6.99", "7.49", "7.29"),
    "coffee": ("4.99", "4.79", "4.49", "5.49", "5.29"),
    "tortillas": ("1.29", "1.39", "1.49", "1.59", "1.49"),
    "salad": (".69", ".79", ".75", ".89", ".85"),
    "pasta": (".79", ".89", ".85", "1.09", ".99"),
    "tomatoes": ("1.39", "1.49", "1.59", "1.69", "1.79"),
    "potatoes": ("1.99", "2.19", "2.29", None, "2.49"),
    "eggs": ("2.29", "2.39", "2.49", "2.69", None),
}
RECIPE_ROWS = [
    {"id": "tacos", "name": "Vistas tortiljas", "emoji": "🌮", "minutes": 30, "servings": 4,
     "ingredients": [("chicken", ".5"), ("tortillas", "1"), ("salad", ".5"), ("peppers", ".5")], "steps": ["Sagriez un apcep vistu.", "Sagriez papriku un salātus.", "Uzsildi tortiljas un piepildi."]},
    {"id": "pasta", "name": "Pasta ar vistu un papriku", "emoji": "🍝", "minutes": 25, "servings": 4,
     "ingredients": [("chicken", ".4"), ("pasta", "1"), ("peppers", "1"), ("tomatoes", ".5")], "steps": ["Novāri makaronus.", "Apcep vistu un dārzeņus.", "Sajauc un pasniedz."]},
    {"id": "roast", "name": "Cepta vista ar kartupeļiem", "emoji": "🍗", "minutes": 45, "servings": 4,
     "ingredients": [("chicken", ".6"), ("potatoes", ".5"), ("butter", ".1"), ("salad", ".5")], "steps": ["Sagriez kartupeļus, liec cepamtraukā.", "Pievieno vistu un sviestu, cep līdz gatavs.", "Pasniedz ar salātiem."]},
    {"id": "omelette", "name": "Omlete ar sieru un tomātiem", "emoji": "🍳", "minutes": 20, "servings": 4,
     "ingredients": [("eggs", ".6"), ("gouda", ".15"), ("tomatoes", "1"), ("milk", ".1")], "steps": ["Sakul olas ar pienu.", "Apcep tomātus un pievieno olas.", "Pārkaisi sieru un cep līdz gatavs."]},
]
NAV = [{"id": key, "label": label, "icon": icon} for key, label, icon in [
    ("overview", "Pārskats", "grid"), ("deals", "Piedāvājumi", "tag"),
    ("list", "Iepirkumu saraksts", "list"), ("planner", "Ēdienkarte", "calendar"),
    ("recipes", "Receptes", "chef"), ("favorites", "Mīļākie produkti", "heart"),
    ("history", "Cenu vēsture", "history"), ("statistics", "Statistika", "chart"),
    ("settings", "Iestatījumi", "settings"),
]]


def money(value):
    return f"{D(value).quantize(D('.01'), rounding=ROUND_HALF_UP):.2f}".replace(".", ",") + " €"


def new_state():
    return {"csrf_token": token_urlsafe(24), "settings": {"household": "Andra ģimene", "location": "Dortmunde", "people": 4},
            "favorites": ["chicken", "milk", "butter", "gouda"],
            "shopping": [{"item_id": token_urlsafe(8), "product_id": key, "name": PRODUCTS[key]["name"], "quantity": 1, "checked": False}
                         for key in ("chicken", "milk", "peppers", "tortillas", "salad", "potatoes")],
            "planner": {WEEK_START.isoformat(): {"0": "tacos", "2": "pasta", "4": "roast"}}, "notice": ""}


def offer_rows(selected_date, state):
    if not WEEK_START <= selected_date <= WEEK_END:
        return []
    rows = []
    for product_id, prices in _PRICES.items():
        product = PRODUCTS[product_id]
        for store, value in zip(RETAILERS, prices):
            if value is None:
                continue
            price, reference = D(value), D(product["reference"])
            rows.append({**product, "price": price, "price_label": money(price), "reference_label": money(reference),
                         "savings": reference - price, "savings_label": money(reference - price),
                         "discount": int((1 - price / reference) * 100),
                         "retailer": store["name"], "retailer_id": store["id"], "retailer_color": store["color"],
                         "unit_price_label": money(price / D(product["amount"])) + "/" + product["unit"],
                         "favorite": product_id in state["favorites"], "condition": "",
                         "valid_label": "28.09.–04.10.2026.", "available": True, "app_price_label": None,
                         "source_label": "Mākslīgs demonstrācijas piemērs"})
    # Conditional promotion is supplemental; it never affects base-price ranking.
    for row in rows:
        if row["id"] == "coffee" and row["retailer_id"] == "lidl":
            row["app_price_label"] = "4,29 €"
            row["app_condition"] = "Ar Lidl Plus kuponu (demo)"
    return rows


def history_for(product_ids, selected_date):
    colors = ["#32895d", "#d29c24", "#6282ca"]
    dates = [WEEK_START - timedelta(days=7 * n) for n in reversed(range(8))]
    dates = [day for day in dates if day <= selected_date]
    offsets = (".80", ".65", ".70", ".45", ".40", ".30", ".15", "0")
    raw = []
    for product_id, color in zip(product_ids, colors):
        product = PRODUCTS[product_id]
        base = D(_PRICES[product_id][0])
        values = [base + D(offsets[i]) for i in range(len(dates))]
        raw.append((product, color, values))
    maximum = max((max(values) for _, _, values in raw if values), default=D("1"))
    ceiling = max(D("1"), maximum * D("1.15"))
    series = []
    for product, color, values in raw:
        points = " ".join(f"{i * 600 / max(1, len(values)-1):.1f},{160-float(value / ceiling)*140:.1f}" for i, value in enumerate(values))
        observations = [{"date": day.strftime("%d.%m.%Y"), "price_label": money(value), "price": value,
                         "retailer": "LIDL", "package": product["package"]} for day, value in zip(dates, values)]
        series.append({"id": product["id"], "name": product["name"], "package": product["package"], "color": color,
                       "points": points, "price_label": money(values[-1]) if values else "—", "observations": observations})
    return {"series": series, "labels": [d.strftime("%d.%m.") for d in dates], "min_label": "0 €", "max_label": money(ceiling),
            "source_label": "8 nedēļu mākslīgi cenu novērojumi · LIDL · identisks iepakojums"}


def build_context(state, selected_date=DEFAULT_DATE, view="overview", product_id=None, query="", retailer="", category="", sort=""):
    offers = offer_rows(selected_date, state)
    best = {}
    for row in sorted(offers, key=lambda item: item["price"]):
        best.setdefault(row["id"], row)
    products = [{**product, "price_label": "—", "retailer": "Nav aktuālas cenas", "retailer_id": "", **best.get(key, {}), "favorite": key in state["favorites"]} for key, product in PRODUCTS.items()]
    shopping_rows = []
    for item in state["shopping"]:
        offer = best.get(item["product_id"])
        row = {**item, "package": PRODUCTS.get(item["product_id"], {}).get("package", "Brīvs ieraksts"),
               "emoji": PRODUCTS.get(item["product_id"], {}).get("emoji", "🛒"), "retailer": offer["retailer"] if offer else "Cena nav zināma",
               "price_label": money(offer["price"] * item["quantity"]) if offer else "—",
               "unit_price_label": offer["unit_price_label"] if offer else "—"}
        shopping_rows.append(row)
    total = sum((best[item["product_id"]]["price"] * item["quantity"] for item in state["shopping"] if item["product_id"] in best), D(0))
    savings = sum((best[item["product_id"]]["savings"] * item["quantity"] for item in state["shopping"] if item["product_id"] in best), D(0))
    unknown_count = sum(1 for item in state["shopping"] if item["product_id"] not in best)
    shopping = {"rows": shopping_rows, "count": len(shopping_rows), "checked_count": sum(item["checked"] for item in shopping_rows),
                "total_label": money(total), "savings_label": money(savings), "unknown_count": unknown_count,
                "total": total, "savings": savings}
    ranked_stores = []
    required = len(state["shopping"])
    for store in RETAILERS:
        matched = {row["id"]: row for row in offers if row["retailer_id"] == store["id"]}
        covered = [item for item in state["shopping"] if item["product_id"] in matched]
        store_total = sum((matched[item["product_id"]]["price"] * item["quantity"] for item in covered), D(0))
        store_savings = sum((matched[item["product_id"]]["savings"] * item["quantity"] for item in covered), D(0))
        ranked_stores.append({**store, "coverage": len(covered), "required": required, "complete": bool(required) and len(covered) == required,
                              "total": store_total, "total_label": money(store_total), "savings_label": money(store_savings),
                              "score": round(100 * len(covered) / required) if required else 0})
    ranked_stores.sort(key=lambda row: (not row["complete"], -row["coverage"], row["total"]))
    recipes = []
    for recipe in RECIPE_ROWS:
        scale = D(state["settings"]["people"]) / D(recipe["servings"])
        ingredients = [{**PRODUCTS[key], "quantity": D(qty) * scale, "quantity_label": str(D(qty) * scale), "in_list": any(i["product_id"] == key for i in state["shopping"])} for key, qty in recipe["ingredients"]]
        covered = [item for item in ingredients if item["id"] in best]
        cost = sum((best[item["id"]]["price"] * D(item["quantity"]) for item in covered), D(0))
        recipes.append({**recipe, "servings": state["settings"]["people"], "ingredients": ingredients, "ingredient_count": len(ingredients), "deal_count": len(covered),
                        "cost_label": money(cost / state["settings"]["people"]) if len(covered) == len(ingredients) else "—",
                        "total_label": money(cost), "cost_note": "Izlietoto daudzumu aplēse; sāls, eļļa un garšvielas nav iekļautas."})
    recipe_map = {recipe["id"]: recipe for recipe in recipes}
    start = selected_date - timedelta(days=selected_date.weekday())
    planner = [{"id": str(i), "label": label, "date": (start + timedelta(days=i)).strftime("%d.%m."), "recipe": recipe_map.get(state["planner"].get(start.isoformat(), {}).get(str(i)))}
               for i, label in enumerate(("Pirmdiena", "Otrdiena", "Trešdiena", "Ceturtdiena", "Piektdiena", "Sestdiena", "Svētdiena"))]
    selected = None
    if product_id in PRODUCTS:
        comparison = sorted([row for row in offers if row["id"] == product_id], key=lambda item: item["price"])
        selected = {**PRODUCTS[product_id], **best.get(product_id, {}), "comparison": comparison,
                    "history": history_for([product_id], selected_date), "favorite": product_id in state["favorites"]}
    filtered = [row for row in offers if (not query or query.casefold() in row["name"].casefold()) and
                (not retailer or row["retailer_id"] == retailer) and (not category or row["category"] == category)]
    if view == "favorites":
        filtered = [row for row in filtered if row["favorite"]]
    if sort == "price":
        filtered.sort(key=lambda row: row["price"])
    elif sort == "savings":
        filtered.sort(key=lambda row: -row["savings"])
    relevant = sorted(best.values(), key=lambda row: (not row["favorite"], -row["savings"]))
    return {"demo": True, "view": view, "nav": NAV, "selected_date": selected_date.isoformat(),
            "week_label": f"{selected_date.isocalendar().week}. nedēļa ({start:%d.%m.} – {start + timedelta(days=6):%d.%m.%Y})",
            "prev_date": (selected_date - timedelta(days=7)).isoformat(), "next_date": (selected_date + timedelta(days=7)).isoformat(),
            "settings": deepcopy(state["settings"]), "csrf_token": state["csrf_token"], "products": products, "offers": filtered,
            "relevant_deals": relevant, "ranked_stores": ranked_stores, "best_store": next((row for row in ranked_stores if row["complete"]), None), "has_offers": bool(offers), "retailers": RETAILERS, "recipes": recipes,
            "shopping": shopping, "selected_product": selected, "history": history_for(["chicken", "butter", "milk"], selected_date),
            "planner": planner, "notice": state["notice"], "query": query, "retailer": retailer, "category": category, "sort": sort,
            "categories": sorted({product["category"] for product in PRODUCTS.values()}),
            "favorites": [product for product in products if product["favorite"]],
            "stats": {"savings_label": money(savings), "basket_label": money(total), "offer_count": len(offers),
                      "favorites_count": len(state["favorites"]), "recipe_count": len(recipes), "planned_count": len(state["planner"].get(start.isoformat(), {})),
                      "unknown_count": unknown_count, "note": "Aplēse no demo saraksta; faktiskie pirkumi netiek reģistrēti."}}


def apply_action(state, action, form):
    """Mutate only the isolated demo session. Return a human-facing status."""
    if action == "add":
        key = form.get("product_id", "")
        name = form.get("name", "").strip()[:120]
        if key not in PRODUCTS:
            key = next((pid for pid, p in PRODUCTS.items() if p["name"].casefold() == name.casefold()), "")
        if not key and not name:
            raise ValueError("Ieraksti produkta nosaukumu.")
        existing = next((item for item in state["shopping"] if key and item["product_id"] == key), None)
        if existing:
            existing["quantity"] = min(99, existing["quantity"] + 1)
        else:
            state["shopping"].append({"item_id": token_urlsafe(8), "product_id": key, "name": PRODUCTS[key]["name"] if key else name, "quantity": 1, "checked": False})
        return "Pievienots demo sarakstam."
    if action in ("toggle", "remove"):
        item = next((item for item in state["shopping"] if item["item_id"] == form.get("item_id")), None)
        if item is None:
            raise ValueError("Saraksta ieraksts nav atrasts.")
        if action == "toggle":
            item["checked"] = not item["checked"]
        else:
            state["shopping"].remove(item)
        return "Demo saraksts atjaunināts."
    if action == "clear_checked":
        state["shopping"] = [item for item in state["shopping"] if not item["checked"]]
        return "Iegādātie produkti noņemti."
    if action == "favorite":
        key = form.get("product_id")
        if key not in PRODUCTS:
            raise ValueError("Produkts nav atrasts.")
        if key in state["favorites"]:
            state["favorites"].remove(key)
        else:
            state["favorites"].append(key)
        return "Mīļākie produkti atjaunināti."
    if action == "plan":
        day, recipe_id = form.get("day"), form.get("recipe_id")
        if day not in [str(n) for n in range(7)] or (recipe_id and recipe_id not in {r["id"] for r in RECIPE_ROWS}):
            raise ValueError("Izvēlies dienu un recepti.")
        selected = date.fromisoformat(form.get("date") or DEFAULT_DATE.isoformat())
        week = (selected - timedelta(days=selected.weekday())).isoformat()
        planned = state["planner"].setdefault(week, {})
        if recipe_id:
            planned[day] = recipe_id
        else:
            planned.pop(day, None)
        return "Demo ēdienkarte saglabāta."
    if action == "recipe_add":
        recipe = next((row for row in RECIPE_ROWS if row["id"] == form.get("recipe_id")), None)
        if recipe is None:
            raise ValueError("Recepte nav atrasta.")
        # Shopping lists contain whole packages, not the fractions used in recipe cost.
        for key, quantity in recipe["ingredients"]:
            packages = int((D(quantity) * D(state["settings"]["people"]) / D(recipe["servings"])).to_integral_value(rounding=ROUND_CEILING))
            for _ in range(packages):
                apply_action(state, "add", {"product_id": key})
        return "Receptes produkti pievienoti sarakstam (veseli iepakojumi)."
    if action == "settings":
        try:
            people = int(form.get("people", "4"))
        except ValueError as exc:
            raise ValueError("Norādi cilvēku skaitu no 1 līdz 12.") from exc
        if not 1 <= people <= 12:
            raise ValueError("Norādi cilvēku skaitu no 1 līdz 12.")
        state["settings"] = {"household": form.get("household", "").strip()[:80] or "Mana ģimene", "location": form.get("location", "").strip()[:80] or "Dortmunde", "people": people}
        return "Demo iestatījumi saglabāti; veikalu piemēri paliek nemainīgi."
    if action == "reset":
        state.update(new_state())
        return "Demonstrācija sākta no jauna."
    raise ValueError("Nezināma darbība.")
