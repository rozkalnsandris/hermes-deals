"""Real provider + durable household workflow over an isolated test database."""
from datetime import date, datetime, timezone
from decimal import Decimal
import re

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.household_service import change_household, read_household
from app.main import app
from app.models import Base, HouseholdState, OfferCandidateRecord, SourceSnapshot, CanonicalProduct, OfferProductLink
from app.north_star_live_data import build_live_context

DAY = date(2026, 10, 1)


@pytest.fixture
def data(monkeypatch):
    monkeypatch.setenv("HERMES_HOUSEHOLD_ID", "test-family")
    monkeypatch.delenv("HERMES_PUBLIC_ORIGIN", raising=False)
    engine = create_engine("sqlite+pysqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool)
    Base.metadata.create_all(engine)
    def db_session():
        with Session(engine) as db:
            yield db
    app.dependency_overrides[get_db] = db_session
    with Session(engine, expire_on_commit=False) as db, TestClient(app) as client:
        yield db, client, engine
    app.dependency_overrides.clear()
    engine.dispose()


def offer(db, *, name="Piens testam", price="1.29", chain="lidl", store="one", sku="milk", collected_day=1, **values):
    collected = datetime(2026, 10, collected_day, 8, tzinfo=timezone.utc)
    snapshot = SourceSnapshot(source_chain=chain, source_url="https://example.invalid/test", collected_at=collected, strategy_hint="test", success=True)
    db.add(snapshot)
    db.flush()
    fields = dict(snapshot_id=snapshot.id, source_chain=chain, source_store_external_id=store, source_offer_id=sku,
                  product_name_raw=name, price_eur=Decimal(price), package_text_raw="1 l", brand_raw="Test",
                  unit_label="l", unit_price_eur=Decimal(price), valid_from=date(2026, 9, 28), valid_until=date(2026, 10, 4),
                  collected_at=collected, source_url="https://example.invalid/test", parser_version="test")
    fields.update(values)
    row = OfferCandidateRecord(**fields)
    db.add(row)
    db.commit()
    return row


def form_values(client, view="list"):
    page = client.get(f"/ui/home/?view={view}&date=2026-10-01")
    assert page.status_code == 200, page.text
    return {"csrf_token": re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1],
            "version": re.search(r'name="version" value="([^"]+)"', page.text)[1],
            "date": "2026-10-01", "return_view": view}


def post(client, action, **values):
    form = form_values(client)
    return client.post(f"/ui/home/actions/{action}", data={**form, **values}, headers={"Origin": "http://testserver"})


@pytest.mark.parametrize("view", ["overview", "deals", "list", "planner", "recipes", "favorites", "history", "statistics", "settings"])
def test_real_pages_never_fall_back_to_demo(data, view):
    db, client, _ = data
    offer(db)
    response = client.get(f"/ui/home/?view={view}&date=2026-10-01")
    assert response.status_code == 200, response.text
    assert response.headers["Referrer-Policy"] == "same-origin"
    assert "SAGLABĀTIE DATI" in response.text
    assert "DEMONSTRĀCIJAS DATI" not in response.text
    assert "2,46 € / porcija" not in response.text
    assert 'href="/ui/home/static/north-star.css"' in response.text
    assert db.scalar(select(func.count()).select_from(HouseholdState)) == 0  # GET does not create state.


def test_two_clients_share_persistent_list_and_reject_stale_form(data):
    db, first, engine = data
    milk = offer(db)
    stale = form_values(first)
    with TestClient(app) as second:
        response = post(second, "add", product_id=str(milk.id))
        assert response.status_code == 200
        assert "Piens testam" in first.get("/ui/home/?view=list&date=2026-10-01").text
        response = first.post("/ui/home/actions/add", data={**stale, "name": "Stale write"}, headers={"Origin": "http://testserver"})
        assert response.status_code == 409
        assert "citā ierīcē" in response.text
        state, version = read_household(db, "test-family")
        assert len(state["shopping"]) == 1 and version == 1
    # New browser / DB session has the same state without carrying the previous cookie.
    with Session(engine) as fresh_db, TestClient(app) as third:
        state, _ = read_household(fresh_db, "test-family")
        item_id = state["shopping"][0]["item_id"]
        post(third, "quantity", item_id=item_id, quantity="3")
        post(third, "toggle", item_id=item_id)
        context = build_live_context(fresh_db, "test-family", DAY)
        assert context["shopping"]["total_label"] == "0,00 €"
        assert context["shopping"]["checked_count"] == 1
        post(third, "clear_checked")
        assert not read_household(fresh_db, "test-family")[0]["shopping"]
    assert db.scalar(select(func.count()).select_from(OfferCandidateRecord)) == 1


def test_favorite_tracks_same_source_product_without_recycled_package(data):
    db, client, _ = data
    old = offer(db, price="1.49", collected_day=1)
    post(client, "favorite", product_id=str(old.id))
    current = offer(db, price="1.19", collected_day=2)
    offer(db, price="0.01", collected_day=3, package_text_raw="100 ml")
    context = build_live_context(db, "test-family", date(2026, 10, 3), view="favorites")
    assert context["favorites"][0]["id"] == str(current.id)
    assert context["favorites"][0]["favorite_id"] == str(old.id)
    assert context["favorites"][0]["price_label"] == "1,19 €"
    overview = build_live_context(db, "test-family", date(2026, 10, 3))
    assert overview["history_product_id"] == str(current.id)
    assert len(overview["overview_history"]["series"][0]["observations"]) == 2
    post(client, "favorite", product_id=str(old.id))
    assert not read_household(db, "test-family")[0]["favorites"]


def test_unmapped_offer_detail_renders_source_history(data):
    db, client, _ = data
    row = offer(db)
    response = client.get(f"/ui/home/?view=deals&date=2026-10-01&product={row.id}")
    assert response.status_code == 200, response.text
    assert "Cenu novērojumi" in response.text
    assert "01.10.2026 10:00" in response.text
    assert "vēl nav apstiprinātu salīdzināmu cenu" in response.text
    assert 'action="/ui/home/actions/add"' in response.text
    assert 'href="https://example.invalid/test"' in response.text


def test_unknown_and_conditional_prices_do_not_become_free_or_unrestricted(data):
    db, client, _ = data
    app_offer = offer(db, requires_app=True)
    post(client, "add", product_id=str(app_offer.id))
    post(client, "add", name="Brīvi ierakstīts produkts")
    context = build_live_context(db, "test-family", DAY)
    assert context["shopping"]["unknown_count"] == 2
    assert context["best_store"] is None
    assert all(item["price_label"] == "—" for item in context["shopping"]["rows"])


def test_basket_keeps_different_branches_separate(data):
    db, client, _ = data
    one = offer(db, store="one")
    two = offer(db, name="Maize", sku="bread", store="two")
    post(client, "add", product_id=str(one.id))
    post(client, "add", product_id=str(two.id))
    context = build_live_context(db, "test-family", DAY)
    assert context["best_store"] is None
    assert len(context["ranked_stores"]) == 2
    assert all(row["coverage"] == 1 and row["required"] == 2 for row in context["ranked_stores"])


def test_complete_single_store_basket_and_free_text_are_preserved(data):
    db, client, _ = data
    row = offer(db)
    post(client, "add", product_id=str(row.id))
    context = build_live_context(db, "test-family", DAY)
    assert context["best_store"]["id"] == "lidl"
    assert context["best_store"]["total_label"] == "1,29 €"
    post(client, "add", name="<script>new</script>")
    response = client.get("/ui/home/?view=list&date=2026-10-01")
    assert "&lt;script&gt;new&lt;/script&gt;" in response.text
    assert "<script>new</script>" not in response.text
    assert build_live_context(db, "test-family", DAY)["best_store"] is None


def test_post_origin_csrf_and_server_owned_household(data):
    db, client, _ = data
    form = form_values(client)
    assert client.post("/ui/home/actions/add", data={**form, "name": "attack"}, headers={"Origin": "https://other.invalid"}).status_code == 403
    assert client.post("/ui/home/actions/add", data={**form, "name": "attack", "csrf_token": "invalid"}, headers={"Origin": "http://testserver"}).status_code == 403
    assert client.post("/ui/home/actions/add", data={**form, "name": "ok", "household_id": "other"}, headers={"Origin": "http://testserver"}).status_code == 200
    assert db.get(HouseholdState, "other") is None
    assert read_household(db, "test-family")[0]["shopping"][0]["name"] == "ok"


def test_missing_migration_is_honest_503_not_demo(data):
    db, client, engine = data
    HouseholdState.__table__.drop(engine)
    response = client.get("/ui/home/")
    assert response.status_code == 503
    assert "Dati pašlaik nav pieejami" in response.text
    assert "Vistas fileja" not in response.text


def test_dates_filters_pagination_and_settings(data):
    db, client, _ = data
    for i in range(61):
        offer(db, name=f"Piens {i:02}", sku=str(i))
    page = client.get("/ui/home/?view=deals&date=2026-10-01")
    assert "Nākamā lapa" in page.text
    assert "Piens 60" not in page.text
    assert "Piens 60" in client.get("/ui/home/?view=deals&date=2026-10-01&offset=60").text
    assert "Piens 02" not in client.get("/ui/home/?view=deals&date=2026-10-01&q=Piens%2001").text
    assert client.get("/ui/home/?date=9999-12-31").status_code == 422
    assert client.get("/ui/home/?offset=-1").status_code == 422
    post(client, "settings", household="Mūsu ģimene", location="Dortmunde", people="6")
    assert read_household(db, "test-family")[0]["settings"]["people"] == 6


@pytest.mark.parametrize("values", [{"package_text_raw": None}, {"collected_day": 2}])
def test_unknown_package_and_future_observation_are_not_basket_prices(data, values):
    db, client, _ = data
    row = offer(db, **values)
    post(client, "add", product_id=str(row.id))
    context = build_live_context(db, "test-family", DAY)
    assert context["shopping"]["unknown_count"] == 1
    assert context["best_store"] is None


def test_unknown_branch_is_not_a_verified_single_store_basket(data):
    db, client, _ = data
    row = offer(db, store=None)
    post(client, "add", product_id=str(row.id))
    assert build_live_context(db, "test-family", DAY)["best_store"] is None


def test_reviewed_cross_store_basket_uses_server_comparison(data):
    db, client, _ = data
    a = offer(db, price="1.29")
    b = offer(db, chain="netto", store="netto-one", price="0.99")
    product = CanonicalProduct(display_name="Milk test", normalized_name="milk test", item_quantity_value=1000, item_quantity_unit="ml", pack_count=1)
    db.add(product)
    db.flush()
    for row in (a, b):
        db.add(OfferProductLink(offer_candidate_id=row.id, canonical_product_id=product.id, link_method="reviewed-test", confidence=Decimal("1")))
    db.commit()
    post(client, "add", product_id=str(a.id))
    context = build_live_context(db, "test-family", DAY)
    assert context["best_store"]["id"] == "netto"
    assert context["best_store"]["total_label"] == "0,99 €"


def test_migration_adds_only_household_table_and_matches_model():
    import importlib.util
    from pathlib import Path
    from alembic.migration import MigrationContext
    from alembic.operations import Operations
    from sqlalchemy import inspect
    spec = importlib.util.spec_from_file_location("household_migration", Path(__file__).parents[1] / "alembic/versions/0008_household_state.py")
    migration = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(migration)
    engine = create_engine("sqlite://")
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.upgrade()
        columns = {c["name"] for c in inspect(connection).get_columns("household_states")}
        assert columns == {"id", "version", "state", "updated_at"}
        assert inspect(connection).get_table_names() == ["household_states"]
    with Session(engine) as db:
        change_household(db, "family", 0, "add", {"name": "Piens"})
        assert read_household(db, "family")[0]["shopping"][0]["name"] == "Piens"
    with engine.begin() as connection:
        with Operations.context(MigrationContext.configure(connection)):
            migration.downgrade()
        assert inspect(connection).get_table_names() == []
    engine.dispose()


def test_public_https_origin_survives_tls_termination(data, monkeypatch):
    db, client, _ = data
    monkeypatch.setenv("HERMES_PUBLIC_ORIGIN", "https://deals.example.test")
    response = client.get("/ui/home/?view=list&date=2026-10-01")
    cookie = response.headers["set-cookie"]
    assert "__Host-hermes_home_csrf=" in cookie
    assert "Secure" in cookie and "HttpOnly" in cookie
    csrf = re.search(r'name="csrf_token" value="([^"]+)"', response.text)[1]
    # The proxy forwards the browser's secure cookie over its internal connection.
    response = client.post("/ui/home/actions/add", data={"csrf_token": csrf, "version": "0", "name": "Proxy test"},
                           headers={"Origin": "https://deals.example.test", "Cookie": f"__Host-hermes_home_csrf={csrf}"}, follow_redirects=False)
    assert response.status_code == 303
    assert read_household(db, "test-family")[0]["shopping"][0]["name"] == "Proxy test"


def test_meal_plan_persists_portions_and_aggregates_without_duplicate_purchases(data):
    db, first, engine = data
    assert post(first, "meal_plan", day="0", recipe_id="tortillas", servings="4").status_code == 200
    assert post(first, "meal_plan", day="2", recipe_id="pasta", servings="2").status_code == 200
    with TestClient(app) as second:
        assert "Vistas tortiljas" in second.get("/ui/home/?view=planner&date=2026-10-01").text
        assert post(second, "meal_sync").status_code == 200
        state, _ = read_household(db, "test-family")
        chicken = next(row for row in state["shopping"] if row["ingredient_id"] == "chicken")
        assert Decimal(chicken["amount"]) == 700
        assert chicken["unit"] == "g" and chicken["product_id"] is None
        ids = [row["item_id"] for row in state["shopping"]]
        post(second, "toggle", item_id=chicken["item_id"])
        post(second, "meal_sync")
        state, _ = read_household(db, "test-family")
        assert [row["item_id"] for row in state["shopping"]] == ids
        assert next(row for row in state["shopping"] if row["ingredient_id"] == "chicken")["checked"]
        post(second, "clear_checked")
        post(second, "meal_sync")
        state, _ = read_household(db, "test-family")
        assert not any(row["ingredient_id"] == "chicken" for row in state["shopping"])
        context = build_live_context(db, "test-family", DAY, view="list")
        assert all(row["price_label"] == "—" for row in context["shopping"]["rows"])
        assert context["best_store"] is None
        assert context["shopping"]["total_label"] == "—"


def test_plan_changes_replace_only_generated_week_and_keep_manual_items(data):
    db, client, _ = data
    post(client, "add", name="Vistas fileja")
    post(client, "meal_plan", day="0", recipe_id="tortillas", servings="4")
    post(client, "meal_sync")
    post(client, "meal_plan", day="0", recipe_id="tortillas", servings="8")
    post(client, "meal_sync")
    state, _ = read_household(db, "test-family")
    chicken = next(r for r in state["shopping"] if r.get("ingredient_id") == "chicken")
    assert Decimal(chicken["amount"]) == 1000
    assert len([r for r in state["shopping"] if r["name"] == "Vistas fileja"]) == 2
    response = post(client, "quantity", item_id=chicken["item_id"], quantity="3")
    assert response.status_code == 422
    assert "porcijas" in response.text
    post(client, "meal_plan", day="0", recipe_id="", servings="4")
    post(client, "meal_sync")
    state, _ = read_household(db, "test-family")
    assert len(state["shopping"]) == 1 and not state["shopping"][0].get("meal_week")


def test_weeks_units_and_existing_households_remain_independent(data):
    db, client, _ = data
    from app.meal_service import change_meals, meal_context
    state = {"settings": {"people": 4}, "shopping": [], "favorites": []}
    assert meal_context(state, DAY)["meal_count"] == 0
    for selected in ("2026-10-01", "2026-10-08"):
        form = {"date": selected, "day": "0", "recipe_id": "omelette", "servings": "2"}
        change_meals(state, "meal_plan", form)
        change_meals(state, "meal_sync", form)
    assert len(state["shopping"]) == 8
    assert {r["meal_week"] for r in state["shopping"]} == {"2026-09-28", "2026-10-05"}
    assert {r["unit"] for r in state["shopping"]} == {"g", "ml", "gab."}
    assert all(Decimal(r["amount"]) == 4 for r in state["shopping"] if r["ingredient_id"] == "eggs")


@pytest.mark.parametrize("values", [
    {"day": "7", "recipe_id": "pasta", "servings": "4"},
    {"day": "0", "recipe_id": "made-up", "servings": "4"},
    {"day": "0", "recipe_id": "pasta", "servings": "0"},
    {"day": "0", "recipe_id": "pasta", "servings": "13"},
    {"day": "0", "recipe_id": "pasta", "servings": "NaN"},
])
def test_invalid_meal_plan_is_not_saved(data, values):
    db, client, _ = data
    assert post(client, "meal_plan", **values).status_code == 422
    assert read_household(db, "test-family")[1] == 0


def test_recipe_and_planner_forms_render_with_no_demo_price_claim(data):
    _, client, _ = data
    recipes = client.get("/ui/home/?view=recipes&date=2026-10-01")
    assert recipes.status_code == 200
    assert "500 g" in recipes.text
    assert "Cenas vēl nav piesaistītas sastāvdaļām" in recipes.text
    assert 'action="/ui/home/actions/meal_plan"' in recipes.text
    planner = client.get("/ui/home/?view=planner&date=2026-10-01")
    assert planner.status_code == 200
    assert planner.text.count('name="day"') == 7
    assert 'action="/ui/home/actions/meal_sync"' in planner.text
