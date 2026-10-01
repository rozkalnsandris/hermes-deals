"""Small authored recipe catalogue and household meal plan; no invented prices.

Quantities are recipe requirements in g/ml/pieces, never retailer pack counts.
The household transaction owns persistence and optimistic concurrency.
"""
from copy import deepcopy
from datetime import date, timedelta
from decimal import Decimal
from uuid import uuid4

RECIPES = [
    {"id": "tortillas", "name": "Vistas tortiljas", "emoji": "🌮", "minutes": 30,
     "ingredients": [("chicken", "Vistas fileja", 500, "g"), ("tortilla", "Tortiljas", 8, "gab."), ("pepper", "Paprika", 250, "g"), ("salad", "Salāti", 150, "g")],
     "steps": ["Sagriez vistu un apcep līdz pilnīgai gatavībai.", "Nomazgā un sagriez dārzeņus.", "Uzsildi tortiljas, piepildi ar vistu un dārzeņiem."]},
    {"id": "pasta", "name": "Pasta ar vistu un papriku", "emoji": "🍝", "minutes": 25,
     "ingredients": [("chicken", "Vistas fileja", 400, "g"), ("pasta", "Makaroni", 400, "g"), ("pepper", "Paprika", 300, "g"), ("tomato", "Tomāti", 300, "g")],
     "steps": ["Novāri makaronus pēc norādēm uz iepakojuma.", "Apcep sagrieztu vistu līdz pilnīgai gatavībai, pievieno dārzeņus.", "Sajauc ar makaroniem un pievieno garšvielas pēc izvēles."]},
    {"id": "potatoes", "name": "Kartupeļu un pupiņu panna", "emoji": "🥔", "minutes": 35,
     "ingredients": [("potato", "Kartupeļi", 800, "g"), ("beans", "Vārītas pupiņas", 400, "g"), ("pepper", "Paprika", 300, "g"), ("oil", "Eļļa", 20, "ml")],
     "steps": ["Sagriez kartupeļus un novāri līdz mīksti.", "Eļļā apcep papriku un kartupeļus.", "Pievieno notecinātas vārītas pupiņas un uzsildi."]},
    {"id": "omelette", "name": "Omlete ar sieru un tomātiem", "emoji": "🍳", "minutes": 20,
     "ingredients": [("eggs", "Olas", 8, "gab."), ("milk", "Piens", 100, "ml"), ("cheese", "Siers", 150, "g"), ("tomato", "Tomāti", 300, "g")],
     "steps": ["Sakul olas ar pienu.", "Pannā uzsildi sagrieztus tomātus un pievieno olu maisījumu.", "Pievieno sieru un cep, līdz olas sarecējušas."]},
]
BY_ID = {recipe["id"]: recipe for recipe in RECIPES}
DAYS = ["Pirmdiena", "Otrdiena", "Trešdiena", "Ceturtdiena", "Piektdiena", "Sestdiena", "Svētdiena"]


def week_start(value):
    try:
        day = date.fromisoformat(value)
        if not 1970 <= day.year <= 2100:
            raise ValueError
    except (ValueError, TypeError):
        raise ValueError("Izvēlies derīgu ēdienkartes datumu.")
    return day - timedelta(days=day.weekday())


def portions(value):
    try:
        count = int(value)
    except (ValueError, TypeError):
        raise ValueError("Norādi porciju skaitu no 1 līdz 12.")
    if not 1 <= count <= 12:
        raise ValueError("Norādi porciju skaitu no 1 līdz 12.")
    return count


def quantity_label(value, unit):
    return format(Decimal(value).normalize(), "f").replace(".", ",") + " " + unit


def recipe_view(recipe, servings):
    ingredients = [{"id": key, "name": name, "amount": str(Decimal(amount) * servings / 4), "unit": unit,
                    "label": quantity_label(Decimal(amount) * servings / 4, unit)}
                   for key, name, amount, unit in recipe["ingredients"]]
    return {**recipe, "servings": servings, "ingredients": ingredients}


def meal_context(state, day):
    start = week_start(day.isoformat())
    week = start.isoformat()
    meals = state.get("meals", {}).get(week, {})
    planner = []
    for i, label in enumerate(DAYS):
        selection = meals.get(str(i))
        recipe = recipe_view(BY_ID[selection["recipe_id"]], selection["servings"]) if selection else None
        planner.append({"id": str(i), "label": label, "date": (start + timedelta(days=i)).strftime("%d.%m."), "recipe": recipe})
    return {"recipes": [recipe_view(r, state["settings"]["people"]) for r in RECIPES], "planner": planner,
            "meal_count": len(meals), "meal_synced": state.get("meal_sync", {}).get(week) == meals and bool(meals)}


def change_meals(state, action, form):
    week = week_start(form.get("date")).isoformat()
    all_meals = state.setdefault("meals", {})
    if action == "meal_plan":
        day = str(form.get("day", ""))
        if day not in {str(i) for i in range(7)}:
            raise ValueError("Izvēlies nedēļas dienu.")
        key = form.get("recipe_id", "")
        if key and key not in BY_ID:
            raise ValueError("Recepte nav atrasta.")
        if week not in all_meals and len(all_meals) >= 104:
            raise ValueError("Saglabātas jau 104 nedēļas. Iztukšo nevajadzīgu nedēļas plānu.")
        meals = all_meals.setdefault(week, {})
        if key:
            meals[day] = {"recipe_id": key, "servings": portions(form.get("servings"))}
        else:
            meals.pop(day, None)
        if not meals:
            all_meals.pop(week, None)
        return
    if action != "meal_sync":
        raise ValueError("Ēdienkartes darbība nav pieejama.")
    meals = all_meals.get(week, {})
    saved = state.setdefault("meal_sync", {})
    if saved.get(week) == meals:
        return  # Repeated clicks, even after clearing purchased rows, add nothing.
    totals = {}
    for meal in meals.values():
        for ingredient in recipe_view(BY_ID[meal["recipe_id"]], meal["servings"])["ingredients"]:
            key = (ingredient["id"], ingredient["unit"])
            if key not in totals:
                totals[key] = {**ingredient, "amount": Decimal(0)}
            totals[key]["amount"] += Decimal(ingredient["amount"])
    old = {item["ingredient_id"]: item for item in state["shopping"] if item.get("meal_week") == week}
    remaining = [item for item in state["shopping"] if item.get("meal_week") != week]
    if len(remaining) + len(totals) > 200:
        raise ValueError("Sarakstā nepietiek vietas sastāvdaļām (ne vairāk par 200 ierakstiem).")
    for ingredient in totals.values():
        previous = old.get(ingredient["id"])
        amount = str(ingredient["amount"])
        same = previous and Decimal(previous["amount"]) == ingredient["amount"] and previous["unit"] == ingredient["unit"]
        remaining.append({"item_id": previous["item_id"] if previous else str(uuid4()), "product_id": None,
                          "name": ingredient["name"], "quantity": 1, "checked": bool(same and previous["checked"]),
                          "meal_week": week, "ingredient_id": ingredient["id"], "amount": amount, "unit": ingredient["unit"]})
    state["shopping"] = remaining
    if meals:
        saved[week] = deepcopy(meals)
    else:
        saved.pop(week, None)
