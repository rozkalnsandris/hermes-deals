from decimal import Decimal as D
from app.basket_plan import best_two_store_plan


def lines(*prices):
    return [{"item_id":str(i),"name":str(i),"prices":{key:D(value) for key,value in options.items()}} for i,options in enumerate(prices)]


def test_split_is_complete_and_cheaper_than_best_single():
    plan,status=best_two_store_plan(lines({"a":"1","b":"3"},{"a":"4","b":"2"}),{"a":{},"b":{}},D(5))
    assert status=="available" and plan["total"]==3 and plan["savings"]==2
    assert [r["store_key"] for r in plan["lines"]]==["a","b"]


def test_complementary_branches_can_complete_missing_single_basket():
    plan,status=best_two_store_plan(lines({"a":"2"},{"b":"3"}),{"a":{},"b":{}})
    assert plan["total"]==5 and plan["savings"] is None


def test_missing_prices_never_become_zero():
    assert best_two_store_plan(lines({"a":"1"},{}),{"a":{}})==(None,"missing_prices")


def test_no_extra_trip_for_tie_or_three_branch_requirement():
    assert best_two_store_plan(lines({"a":"1","b":"1"},{"a":"1","b":"1"}),{"a":{},"b":{}},D(2))[0] is None
    assert best_two_store_plan(lines({"a":"1"},{"b":"1"},{"c":"1"}),{"a":{},"b":{},"c":{}})[0] is None


def test_branch_limit_is_explicit_instead_of_partial_recommendation():
    values={str(i):"1" for i in range(31)}
    assert best_two_store_plan(lines(values),{})==(None,"too_many_branches")
