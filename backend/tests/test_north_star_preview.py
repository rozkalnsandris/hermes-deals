"""Exercise the complete synthetic workflow without importing production DB code."""
import re
from datetime import date
from decimal import Decimal

import pytest

pytest.importorskip("jinja2")
from fastapi.testclient import TestClient
from app.north_star_preview import app, SESSIONS
from app.north_star_data import NAV, new_state, build_context, apply_action


def token(response):
    return re.search(r'name="csrf_token" value="([^"]+)"', response.text)[1]


def post(client, action, **values):
    csrf = token(client.get("/"))
    return client.post(f"/actions/{action}", data={"csrf_token": csrf, "date": "2026-10-01", **values})


@pytest.fixture
def client():
    SESSIONS.clear()
    with TestClient(app) as client:
        yield client


@pytest.mark.parametrize("view", [item["id"] for item in NAV])
def test_every_view_renders_including_dates_without_offers(client, view):
    for day in ("2026-10-01", "2026-10-12", "2026-01-01"):
        response = client.get("/", params={"view": view, "date": day})
        assert response.status_code == 200
        assert "DEMONSTRĀCIJAS DATI" in response.text
        assert 'lang="lv"' in response.text
        assert "None" not in response.text


def test_product_detail_has_real_table_values_and_conditional_price(client):
    response = client.get("/?product=coffee")
    assert response.status_code == 200
    assert "4,29 €" in response.text
    assert "Lidl Plus kuponu" in response.text
    assert "Skatīt diagrammu" not in response.text
    assert "4,99 €" in response.text
    assert client.get("/?product=coffee&date=2026-10-12").status_code == 200


def test_list_workflow_is_session_scoped_and_escapes_free_text(client):
    response = post(client, "add", name="<script>custom</script>", return_view="list")
    assert "&lt;script&gt;custom&lt;/script&gt;" in response.text
    assert "<script>custom</script>" not in response.text
    state = next(iter(SESSIONS.values()))["state"]
    item_id = state["shopping"][-1]["item_id"]
    post(client, "toggle", item_id=item_id)
    assert state["shopping"][-1]["checked"] is True
    post(client, "clear_checked")
    assert all(item["item_id"] != item_id for item in state["shopping"])
    post(client, "add", name="Only in my session")
    with TestClient(app) as other:
        assert "Only in my session" not in other.get("/?view=list").text
    assert client.post("/actions/reset", data={"csrf_token": "wrong"}).status_code == 403
    assert "Only in my session" in client.get("/?view=list").text


def test_favorites_search_and_week_scoped_planner(client):
    state = next(iter(SESSIONS.values()))["state"] if SESSIONS else None
    page = post(client, "favorite", product_id="coffee", return_view="favorites")
    assert "Malta kafija" in page.text
    post(client, "favorite", product_id="coffee")
    assert "Malta kafija" not in client.get("/?view=favorites").text
    assert "Vistas fileja" not in client.get("/?view=deals&q=piens").text
    post(client, "plan", day="1", recipe_id="omelette")
    assert "Omlete ar sieru" in client.get("/?view=planner").text
    assert "planner-dish" not in client.get("/?view=planner&date=2026-10-12").text


def test_server_calculates_basket_and_partial_coverage_honestly():
    state = new_state()
    context = build_context(state)
    assert context["shopping"]["total"] == Decimal("12.64")
    assert context["best_store"]["name"] == "LIDL"
    assert context["best_store"]["total"] == Decimal("12.90")
    assert context["ranked_stores"][-1]["complete"] is False
    apply_action(state, "add", {"name": "unknown item"})
    context = build_context(state)
    assert context["best_store"] is None
    assert context["shopping"]["unknown_count"] == 1
    assert build_context(state, date(2026, 10, 12))["offers"] == []


def test_recipe_portions_and_settings_drive_purchase_quantities(client):
    post(client, "settings", household="Test family", location="Berlin", people="12")
    post(client, "recipe_add", recipe_id="tacos")
    state = next(iter(SESSIONS.values()))["state"]
    context = build_context(state)
    assert context["recipes"][0]["servings"] == 12
    tortillas = next(item for item in state["shopping"] if item["product_id"] == "tortillas")
    assert tortillas["quantity"] == 4  # existing package + three for 12 portions
    assert "Test family" in client.get("/").text


def test_malformed_forms_and_no_production_connection(client):
    assert client.get("/health").json()["database"] is False
    assert client.post("/actions/add", data="x", headers={"content-length": "bad"}).status_code == 400
    fields = "&".join(f"x{i}=1" for i in range(31))
    assert client.post("/actions/add", content=fields, headers={"content-type": "application/x-www-form-urlencoded"}).status_code == 400
