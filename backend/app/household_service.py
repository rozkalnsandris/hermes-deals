"""Shared list, favorites and settings. No writes to offers or source evidence.

The household key is server configuration, never a request parameter. One private
family deployment shares one document. Version checks prevent lost updates and
make repeated submission of an already applied form harmless (409, not a retry).
"""
from copy import deepcopy
from datetime import datetime, timezone
from uuid import UUID, uuid4

from sqlalchemy import select, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import HouseholdState, OfferCandidateRecord
from app.meal_service import change_meals
from app.meal_pricing import INGREDIENTS, package_amount


class HouseholdConflict(ValueError):
    pass


def empty_household():
    return {"settings": {"household": "Mana ģimene", "location": "Dortmunde", "people": 4},
            "shopping": [], "favorites": []}


def read_household(db: Session, household_id: str):
    row = db.get(HouseholdState, household_id, populate_existing=True)
    return (deepcopy(row.state), row.version) if row else (empty_household(), 0)


def _offer(db, value):
    try:
        offer_id = UUID(value)
    except (ValueError, TypeError, AttributeError):
        raise ValueError("Piedāvājums nav atrasts.")
    row = db.get(OfferCandidateRecord, offer_id)
    if row is None:
        raise ValueError("Piedāvājums nav atrasts.")
    return row


def change_household(db: Session, household_id: str, expected_version: int, action: str, form: dict):
    state, version = read_household(db, household_id)
    if expected_version != version:
        raise HouseholdConflict("Sarakstu tikko mainīja citā ierīcē. Pārlādē lapu un atkārto savu darbību.")
    items = state["shopping"]
    if action == "store_preferences":
        state["preferred_retailers"] = [key for key in ("lidl", "netto", "aldi_nord", "edeka") if form.get("store_" + key) == "1"]
    elif action == "shopping_bind":
        item = next((item for item in items if item["item_id"] == form.get("item_id")), None)
        if item is None or item.get("meal_week") or item["checked"]:
            raise ValueError("Izvēlies nenopirktu saraksta ierakstu. Ēdienkartes produktus izvēlas pie sastāvdaļām.")
        item["product_id"] = str(_offer(db, form.get("product_id")).id)
    elif action == "price_eligibility":
        offer = _offer(db, form.get("product_id"))
        eligibility = state.setdefault("price_eligibility", {})
        flags = {key: True for key in ("app", "coupon") if form.get(key) == "1"}
        if flags:
            eligibility[str(offer.id)] = flags
        else:
            eligibility.pop(str(offer.id), None)
    elif action == "branch_preference":
        chain, store = form.get("chain", ""), form.get("store", "")
        key = f"{chain}:{store}"
        excluded = set(state.get("excluded_branches", []))
        known = db.scalar(select(OfferCandidateRecord.id).where(
            OfferCandidateRecord.source_chain == chain,
            OfferCandidateRecord.source_store_external_id == store).limit(1))
        if not store or (known is None and key not in excluded):
            raise ValueError("Filiāle nav atrasta avota datos.")
        if form.get("enabled") == "1":
            excluded.discard(key)
        else:
            excluded.add(key)
        state["excluded_branches"] = sorted(excluded)
    elif action == "ingredient_bind":
        key = form.get("ingredient_id", "")
        if key not in INGREDIENTS:
            raise ValueError("Sastāvdaļa nav atrasta.")
        bindings = state.setdefault("ingredient_offers", {})
        if form.get("product_id"):
            offer = _offer(db, form["product_id"])
            if package_amount(offer, INGREDIENTS[key]["unit"]) is None:
                raise ValueError("Šī iepakojuma daudzumu nevar droši pārrēķināt sastāvdaļas vienībā.")
            bindings[key] = str(offer.id)
        else:
            bindings.pop(key, None)
        for item in items:
            if item.get("ingredient_id") == key:
                item["checked"] = False
    elif action in {"meal_plan", "meal_sync"}:
        change_meals(state, action, form)
    elif action == "add":
        name = str(form.get("name", "")).strip()[:120]
        offer_id = form.get("product_id", "")
        if offer_id:
            offer = _offer(db, offer_id)
            offer_id, name = str(offer.id), offer.product_name_raw
        if not name:
            raise ValueError("Ieraksti produkta nosaukumu.")
        item = next((item for item in items if offer_id and item["product_id"] == offer_id and not item["checked"]), None)
        if item:
            item["quantity"] = min(item["quantity"] + 1, 99)
        elif len(items) < 200:
            items.append({"item_id": str(uuid4()), "product_id": offer_id or None,
                          "name": name, "quantity": 1, "checked": False})
        else:
            raise ValueError("Sarakstā jau ir 200 ieraksti. Noņem nevajadzīgos.")
    elif action in {"toggle", "remove", "quantity"}:
        item = next((item for item in items if item["item_id"] == form.get("item_id")), None)
        if item is None:
            raise ValueError("Saraksta ieraksts nav atrasts.")
        if action == "toggle":
            item["checked"] = not item["checked"]
        elif action == "remove":
            items.remove(item)
        else:
            if item.get("meal_week"):
                raise ValueError("Sastāvdaļu daudzumu maini ēdienkartē, izvēloties porcijas un atjaunojot sarakstu.")
            try:
                quantity = int(form.get("quantity", ""))
            except (ValueError, TypeError):
                raise ValueError("Norādi daudzumu no 1 līdz 99.")
            if not 1 <= quantity <= 99:
                raise ValueError("Norādi daudzumu no 1 līdz 99.")
            item["quantity"] = quantity
    elif action == "clear_checked":
        state["shopping"] = [item for item in items if not item["checked"]]
    elif action == "favorite":
        key = str(_offer(db, form.get("product_id")).id)
        if key in state["favorites"]:
            state["favorites"].remove(key)
        elif len(state["favorites"]) < 100:
            state["favorites"].append(key)
        else:
            raise ValueError("Saglabāti jau 100 favorīti.")
    elif action == "settings":
        try:
            people = int(form.get("people", ""))
        except (ValueError, TypeError):
            raise ValueError("Norādi cilvēku skaitu no 1 līdz 12.")
        if not 1 <= people <= 12:
            raise ValueError("Norādi cilvēku skaitu no 1 līdz 12.")
        state["settings"] = {"household": str(form.get("household", "")).strip()[:60] or "Mana ģimene",
                             "location": str(form.get("location", "")).strip()[:80], "people": people}
    else:
        raise ValueError("Šī darbība vēl nav pieejama.")
    now = datetime.now(timezone.utc)
    if version == 0:
        db.add(HouseholdState(id=household_id, version=1, state=state, updated_at=now))
    else:
        result = db.execute(update(HouseholdState).where(
            HouseholdState.id == household_id, HouseholdState.version == version,
        ).values(state=state, version=version + 1, updated_at=now),
            execution_options={"synchronize_session": False})
        if result.rowcount != 1:
            db.rollback()
            raise HouseholdConflict("Dati mainījušies. Pārlādē lapu pirms nākamās darbības.")
    try:
        db.commit()
    except IntegrityError as exc:
        db.rollback()
        raise HouseholdConflict("Dati mainījušies. Pārlādē lapu pirms nākamās darbības.") from exc
    db.expire_all()
    return version + 1
