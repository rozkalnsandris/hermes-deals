"""Household-selected ingredient offers; quantities reuse the package normalizer."""
from decimal import Decimal, ROUND_CEILING
import re

from app.meal_service import RECIPES
from app.product_normalizer import parse_package_text

INGREDIENTS = {key: {"id": key, "name": name, "unit": unit}
               for recipe in RECIPES for key, name, amount, unit in recipe["ingredients"]}
# Reject ranges, alternative sizes and combined bases rather than choosing the
# first number from an ambiguous label. Existing normalizer owns conversion.
SIMPLE_PACKAGE = re.compile(r"(?:(?:\d+\s*[x×]\s*)?\d+(?:[.,]\d+)?\s*(?:kg|g|mg|l|ml|cl)|\d+\s*(?:stück|stueck|stk\.?|er\s*[-–—]?\s*packung)|stück|stueck)", re.I)


def package_amount(row, unit):
    if row.pricing_mode not in {None, "fixed_package"}:
        return None
    text = (row.package_text_raw or "").strip()
    if not SIMPLE_PACKAGE.fullmatch(text):
        return None
    parsed = parse_package_text(text)
    expected = {"g": "g", "ml": "ml", "gab.": "piece"}.get(unit)
    if parsed.item_quantity_unit != expected:
        return None
    count = parsed.pack_count or 1
    return Decimal(count) if expected == "piece" else parsed.item_quantity_value * count if parsed.item_quantity_value else None


def requirement_price(row, amount, unit, pack_price):
    size = package_amount(row, unit)
    if not size or pack_price is None:
        return None
    ratio = Decimal(amount) / size
    packs = int(ratio.to_integral_value(rounding=ROUND_CEILING))
    return {"packs": packs, "used_cost": ratio * pack_price, "purchase_cost": packs * pack_price}
