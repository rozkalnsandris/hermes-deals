"""Choose at most two evidenced branches, without travel-cost or distance guesses."""
from decimal import Decimal
from itertools import combinations


def best_two_store_plan(lines, stores, best_single_total=None):
    if not lines or any(not line["prices"] for line in lines):
        return None, "missing_prices"
    keys = sorted({key for line in lines for key in line["prices"]})
    if len(keys) > 30:
        return None, "too_many_branches"
    best = None
    for pair in combinations(keys, 2):
        assignments, total = [], Decimal(0)
        for line in lines:
            options = [(line["prices"][key], key) for key in pair if key in line["prices"]]
            if not options:
                break
            price, key = min(options)
            assignments.append({"item_id": line["item_id"], "name": line["name"], "store_key": key, "price": price, **line.get("details", {}).get(key, {})})
            total += price
        else:
            if len({row["store_key"] for row in assignments}) != 2:
                continue
            if best_single_total is not None and total >= best_single_total:
                continue  # A second trip must improve the known item total.
            if best is None or (total, pair) < (best["total"], best["keys"]):
                best = {"keys": pair, "total": total, "lines": assignments,
                        "stores": [stores[key] for key in pair],
                        "savings": best_single_total - total if best_single_total is not None else None}
    return best, "available" if best else "no_benefit"
