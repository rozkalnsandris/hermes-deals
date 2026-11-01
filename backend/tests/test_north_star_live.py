"""Real provider + durable household workflow over an isolated test database."""
from datetime import date, datetime, timezone
from decimal import Decimal
from html import unescape
import re
from urllib.parse import parse_qs, urlsplit

from fastapi.testclient import TestClient
import pytest
from sqlalchemy import create_engine, select, func
from sqlalchemy.orm import Session
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.household_service import change_household, read_household
from app.main import app
import app.north_star_live as north_star_live
from app.models import Base, HouseholdState, OfferCandidateRecord, SourceSnapshot, CanonicalProduct, OfferProductLink
from app.north_star_live_data import build_live_context
from app.runtime import app as runtime_app

DAY = date(2026, 10, 1)


@pytest.fixture
def data(monkeypatch):
    monkeypatch.setenv("HERMES_HOUSEHOLD_UI_ENABLED", "1")
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


def test_household_ui_requires_explicit_server_opt_in(monkeypatch):
    monkeypatch.delenv("HERMES_HOUSEHOLD_UI_ENABLED", raising=False)
    with TestClient(runtime_app) as client:
        for value in (None, "", "0", "true", " 1", "1 "):
            if value is None:
                monkeypatch.delenv("HERMES_HOUSEHOLD_UI_ENABLED", raising=False)
            else:
                monkeypatch.setenv("HERMES_HOUSEHOLD_UI_ENABLED", value)
            assert client.get("/ui/home").status_code == 404
            assert client.get("/ui/home/").status_code == 404
            assert client.post("/ui/home/actions/add").status_code == 404
            assert client.get("/ui/home/static/north-star.css").status_code == 404
        assert client.get("/api/openapi.json").status_code == 200
        assert client.get("/ui").status_code == 200
        assert client.get("/api/health").status_code == 200
        monkeypatch.setenv("HERMES_HOUSEHOLD_UI_ENABLED", "1")
        assert client.get("/ui/home/static/north-star.css").status_code == 200
        monkeypatch.setenv("HERMES_HOUSEHOLD_UI_ENABLED", "0")
        assert client.get("/ui/home/static/north-star.css").status_code == 404


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
    timings = response.headers["Server-Timing"]
    assert re.search(r"home-context;dur=\d+\.\d", timings)
    assert re.search(r"home-render;dur=\d+\.\d", timings)
    assert "SAGLABĀTIE DATI" in response.text
    assert "DEMONSTRĀCIJAS DATI" not in response.text
    assert "2,46 € / porcija" not in response.text
    assert 'href="/ui/home/static/north-star.css"' in response.text
    assert db.scalar(select(func.count()).select_from(HouseholdState)) == 0  # GET does not create state.


def test_live_offer_image_does_not_layer_cart_behind_transparent_image(data):
    db, client, _ = data
    offer(db, source_image_url="https://example.invalid/transparent-product.png")
    page = client.get("/ui/home/?view=deals&date=2026-10-01")
    assert page.status_code == 200
    assert re.search(
        r'class="product-picture category-food" aria-hidden="true"><img '
        r'src="https://example.invalid/transparent-product.png"',
        page.text,
    )
    assert "🛒" not in page.text


def test_live_offer_without_image_shows_neutral_placeholder_not_cart(data):
    db, client, _ = data
    offer(db)
    page = client.get("/ui/home/?view=deals&date=2026-10-01")
    assert page.status_code == 200
    assert 'class="product-picture category-food" aria-hidden="true">📦</span>' in page.text
    assert "🛒" not in page.text


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



def test_berlin_today_uses_europe_berlin(monkeypatch):
    class FixedClock:
        @classmethod
        def now(cls, tz):
            assert tz.key == "Europe/Berlin"
            return datetime(2026, 10, 22, 0, 30, tzinfo=tz)

    monkeypatch.setattr(north_star_live, "datetime", FixedClock)
    assert north_star_live._berlin_today() == date(2026, 10, 22)


def test_day_picker_preserves_filters_resets_offset_and_changes_effective_day(data, monkeypatch):
    db, client, _ = data
    row = offer(
        db,
        name="Ceturtdienas prece",
        sku="thursday-only",
        collected_day=20,
        valid_from=date(2026, 10, 22),
        valid_until=date(2026, 10, 22),
    )
    monkeypatch.setattr(north_star_live, "_berlin_today", lambda: date(2026, 10, 22))
    tuesday_url = (
        "/ui/home/?view=deals&date=2026-10-20&q=Ceturtdienas"
        "&retailer=lidl&sort=retailer&offset=60"
    )
    tuesday = client.get(tuesday_url)
    assert tuesday.status_code == 200
    assert "Otrdiena, 20.10.2026" in tuesday.text
    assert "Ceturtdienas prece" not in tuesday.text
    thursday_href = (
        'href="/ui/home/?view=deals&amp;date=2026-10-22'
        '&amp;q=Ceturtdienas&amp;retailer=lidl&amp;sort=retailer"'
    )
    assert thursday_href in tuesday.text
    assert "Šodien" in tuesday.text
    assert 'aria-current="date"' in tuesday.text

    thursday_url = (
        "/ui/home/?view=deals&date=2026-10-22&q=Ceturtdienas"
        "&retailer=lidl&sort=retailer"
    )
    thursday = client.get(thursday_url, headers={"HX-Request": "true"})
    assert thursday.status_code == 200
    assert "<!doctype" not in thursday.text
    assert "Ceturtdiena, 22.10.2026" in thursday.text
    assert row.product_name_raw in thursday.text


def test_day_picker_crosses_year_boundary_and_has_responsive_touch_contract(data):
    _, client, _ = data
    page = client.get("/ui/home/?view=deals&date=2026-12-31")
    assert page.status_code == 200
    for selected in (
        "2026-12-28",
        "2026-12-29",
        "2026-12-30",
        "2026-12-31",
        "2027-01-01",
        "2027-01-02",
        "2027-01-03",
    ):
        assert f"date={selected}" in page.text
    assert 'href="/ui/home/?view=deals&amp;date=2026-12-24"' in page.text
    assert 'href="/ui/home/?view=deals&amp;date=2027-01-07"' in page.text

    css = client.get("/ui/home/static/modern.css")
    assert css.status_code == 200
    assert ".day-option { min-height: 44px;" in css.text
    assert "@media (max-width:760px)" in css.text
    assert "@media (max-width:380px)" in css.text
    assert "grid-template-columns: repeat(7,minmax(44px,1fr)); overflow-x: auto;" in css.text



def test_empty_search_is_filter_state_not_source_failure(data):
    db, client, _ = data
    offer(db, name="Piens", chain="lidl")
    page = client.get("/ui/home/?view=deals&date=2026-10-01&q=NavTada&retailer=lidl")
    assert page.status_code == 200
    assert 'data-state="filtered_empty"' in page.text
    assert "Filtrs neatdeva rezultātus" in page.text
    assert "Pārbaudē piedāvājumi netika atrasti" not in page.text


def test_explicit_verified_empty_snapshot_is_the_only_no_offers_claim(data):
    db, client, _ = data
    db.add(SourceSnapshot(
        source_chain="edeka",
        source_url="https://example.invalid/edeka",
        scope="family_primary_edeka",
        collected_at=datetime(2026, 10, 1, 8, tzinfo=timezone.utc),
        strategy_hint="edeka_store_offers_manifest_v1",
        success=True,
        keyword_hits={"offer_count": 0},
    ))
    db.commit()

    page = client.get("/ui/home/?view=deals&date=2026-10-01&retailer=edeka")
    assert page.status_code == 200
    assert 'data-state="no_offers"' in page.text
    assert "Pārbaudē piedāvājumi netika atrasti" in page.text
    assert "Pēdējā avota pārbaude: 01.10.2026 10:00 (Berlīne)" in page.text
    assert "Dienas piedāvājumi" in page.text


def test_failed_current_source_attempt_is_unavailable_not_empty(data):
    db, client, _ = data
    db.add(SourceSnapshot(
        source_chain="edeka",
        source_url="https://example.invalid/edeka",
        scope="family_primary_edeka",
        collected_at=datetime(2026, 10, 1, 8, tzinfo=timezone.utc),
        strategy_hint="edeka_store_offers_manifest_v1_error",
        success=False,
        error="fixture failure",
    ))
    db.commit()

    page = client.get("/ui/home/?view=deals&date=2026-10-01&retailer=edeka")
    assert page.status_code == 200
    assert 'data-state="source_unavailable"' in page.text
    assert "Avots pašlaik nav pieejams" in page.text
    assert "Tas nenozīmē, ka akciju nav" in page.text


def test_expired_known_window_is_stale_not_verified_empty(data):
    db, client, _ = data
    offer(
        db,
        chain="netto",
        valid_from=date(2026, 9, 28),
        valid_until=date(2026, 9, 30),
    )
    page = client.get("/ui/home/?view=deals&date=2026-10-01&retailer=netto")
    assert page.status_code == 200
    assert 'data-state="stale_data"' in page.text
    assert "Pieejamie dati ir novecojuši" in page.text
    assert "30.09.2026" in page.text
    assert "Pārbaudē piedāvājumi netika atrasti" not in page.text


def test_future_day_without_verified_coverage_is_not_published_yet(data):
    _, client, _ = data
    page = client.get("/ui/home/?view=deals&date=2099-01-01&retailer=lidl")
    assert page.status_code == 200
    assert 'data-state="not_published_yet"' in page.text
    assert "Šai dienai dati vēl nav pārbaudīti" in page.text
    assert "Pārbaudē piedāvājumi netika atrasti" not in page.text


def test_short_period_snapshot_does_not_define_current_lidl_chain_status(data):
    db, client, _ = data
    db.add(SourceSnapshot(
        source_chain="lidl",
        source_url="https://example.invalid/lidl-specials",
        scope="short_period_specials",
        collected_at=datetime(2026, 10, 1, 8, tzinfo=timezone.utc),
        strategy_hint="weekly_special_fixture",
        success=True,
        keyword_hits={"offer_count": 0},
    ))
    db.commit()

    page = client.get("/ui/home/?view=deals&date=2026-10-01&retailer=lidl")
    assert page.status_code == 200
    assert 'data-state="verification_pending"' in page.text
    assert "Pārbaude vēl nav pabeigta" in page.text
    assert "Īso periodu pierādījumi tiek vērtēti atsevišķi" in page.text
    assert 'data-state="no_offers"' not in page.text


def test_household_offer_sorting_is_server_owned(data):
    db, client, _ = data
    offer(db, name="A Netto", chain="netto", sku="netto", collected_day=1)
    offer(db, name="Z Lidl", chain="lidl", sku="lidl", collected_day=2)
    offer(db, name="M Edeka", chain="edeka", sku="edeka", collected_day=1)
    base = "/ui/home/?view=deals&date=2026-10-03"
    default = client.get(base)
    assert default.status_code == 200
    assert re.findall(r'class="offer-title"[^>]*><h3>([^<]+)</h3>', default.text) == ["A Netto", "M Edeka", "Z Lidl"]
    by_store = client.get(base + "&sort=retailer")
    assert by_store.status_code == 200
    assert re.findall(r'class="offer-title"[^>]*><h3>([^<]+)</h3>', by_store.text) == ["M Edeka", "Z Lidl", "A Netto"]
    newest = client.get(base + "&sort=newest", headers={"HX-Request": "true"})
    assert newest.status_code == 200
    assert re.findall(r'class="offer-title"[^>]*><h3>([^<]+)</h3>', newest.text)[0] == "Z Lidl"
    assert 'name="sort"' in newest.text and 'value="newest" selected' in newest.text
    assert "1–3 no 3 piedāvājumiem" in newest.text
    assert client.get(base + "&sort=price_asc").status_code == 422


def test_household_offer_sort_pagination_preserves_filters(data):
    db, client, _ = data
    for i in range(61):
        offer(db, name=f"Piens {i:02}", sku=str(i), chain="lidl")
    base = "/ui/home/?view=deals&date=2026-10-01&q=Piens&retailer=lidl&sort=retailer"
    first = client.get(base)
    assert first.status_code == 200
    assert "1–60 no 61 piedāvājumiem" in first.text
    assert "sort=retailer&amp;offset=60" in first.text
    second = client.get(base + "&offset=60")
    assert second.status_code == 200
    assert "61–61 no 61 piedāvājumiem" in second.text
    assert "Iepriekšējā lapa" in second.text
    assert "Notīrīt filtrus" in second.text
    assert "q=Piens&amp;retailer=lidl&amp;sort=retailer&amp;offset=0" in second.text


def test_product_detail_preserves_filtered_second_page_context_for_full_and_htmx(data):
    db, client, _ = data
    rows = [offer(db, name=f"Piens {i:02}", sku=str(i), chain="lidl") for i in range(61)]
    target = rows[-1]
    base = "/ui/home/?view=deals&date=2026-10-01&q=Piens&retailer=lidl&sort=retailer&offset=60"
    page = client.get(base)
    assert page.status_code == 200 and "61–61 no 61 piedāvājumiem" in page.text

    href = unescape(re.search(r'class="offer-title" href="([^"]+)"', page.text)[1])
    expected = {
        "view": ["deals"],
        "date": ["2026-10-01"],
        "q": ["Piens"],
        "retailer": ["lidl"],
        "sort": ["retailer"],
        "offset": ["60"],
        "product": [str(target.id)],
    }
    assert parse_qs(urlsplit(href).query) == expected

    for headers in ({}, {"HX-Request": "true"}):
        detail = client.get(href, headers=headers)
        assert detail.status_code == 200 and 'role="dialog"' in detail.text
        close_href = unescape(re.search(r'data-dialog-close href="([^"]+)"', detail.text)[1])
        close_params = parse_qs(urlsplit(close_href).query)
        assert close_params == {key: value for key, value in expected.items() if key != "product"}
        restored = client.get(close_href, headers=headers)
        assert restored.status_code == 200
        assert "Piens 60" in restored.text and "61–61 no 61 piedāvājumiem" in restored.text


@pytest.mark.parametrize(("action", "state_key"), [("favorite", "favorites"), ("add", "shopping")])
def test_filtered_post_action_preserves_return_context_and_mutates_once(data, action, state_key):
    db, client, _ = data
    rows = [offer(db, name=f"Piens {i:02}", sku=str(i), chain="lidl") for i in range(61)]
    target = rows[-1]
    base = "/ui/home/?view=deals&date=2026-10-01&q=Piens&retailer=lidl&sort=retailer&offset=60"
    page = client.get(base)
    form = {
        "csrf_token": re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1],
        "version": re.search(r'name="version" value="([^"]+)"', page.text)[1],
        "date": "2026-10-01",
        "return_view": "deals",
        "q": "Piens",
        "retailer": "lidl",
        "sort": "retailer",
        "offset": "60",
        "product_id": str(target.id),
    }
    assert all(f'name="{key}" value="{value}"' in page.text for key, value in {
        "q": "Piens", "retailer": "lidl", "sort": "retailer", "offset": "60"
    }.items())

    response = client.post(
        f"/ui/home/actions/{action}",
        data=form,
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    destination = parse_qs(urlsplit(response.headers["location"]).query)
    assert destination == {
        "view": ["deals"],
        "date": ["2026-10-01"],
        "q": ["Piens"],
        "retailer": ["lidl"],
        "sort": ["retailer"],
        "offset": ["60"],
        "saved": ["1"],
    }
    state, version = read_household(db, "test-family")
    assert version == 1
    assert len(state[state_key]) == 1
    restored = client.get(response.headers["location"])
    assert "Piens 60" in restored.text and "61–61 no 61 piedāvājumiem" in restored.text


@pytest.mark.parametrize(
    ("return_values", "expected"),
    [
        (
            {
                "return_view": "https://evil.invalid/path",
                "q": "Piens",
                "retailer": "lidl",
                "sort": "retailer",
                "offset": "60",
                "return_url": "https://evil.invalid/",
            },
            {"view": ["list"], "date": ["2026-10-01"], "saved": ["1"]},
        ),
        (
            {
                "return_view": "deals",
                "q": "Piens",
                "retailer": "../evil",
                "sort": "price",
                "offset": "-1",
                "return_url": "https://evil.invalid/",
            },
            {"view": ["deals"], "date": ["2026-10-01"], "q": ["Piens"], "saved": ["1"]},
        ),
    ],
)
def test_post_return_context_rejects_external_or_invalid_values(data, return_values, expected):
    db, client, _ = data
    row = offer(db)
    page = client.get("/ui/home/?view=deals&date=2026-10-01")
    form = {
        "csrf_token": re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1],
        "version": re.search(r'name="version" value="([^"]+)"', page.text)[1],
        "date": "2026-10-01",
        "product_id": str(row.id),
        **return_values,
    }
    response = client.post(
        "/ui/home/actions/favorite",
        data=form,
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert parse_qs(urlsplit(response.headers["location"]).query) == expected
    assert "evil.invalid" not in response.headers["location"]
    state, version = read_household(db, "test-family")
    assert version == 1 and len(state["favorites"]) == 1


def test_detail_htmx_focus_and_scroll_restore_contract(data):
    _, client, _ = data
    asset = client.get("/ui/home/static/north-star.js")
    assert asset.status_code == 200
    assert "dialogScrollY = opensDetail ? window.scrollY : null;" in asset.text
    assert "focus({ preventScroll: true })" in asset.text
    assert "window.scrollTo(0, dialogScrollY)" in asset.text


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
    assert "kurai sastāvdaļai to izmantot" in recipes.text
    assert 'action="/ui/home/actions/meal_plan"' in recipes.text
    planner = client.get("/ui/home/?view=planner&date=2026-10-01")
    assert planner.status_code == 200
    assert planner.text.count('name="day"') == 7
    assert 'action="/ui/home/actions/meal_sync"' in planner.text


def test_ingredient_selection_prices_used_amount_and_whole_packs(data):
    db, client, _ = data
    chicken = offer(db, name="Vista", package_text_raw="500 g", price="3.00")
    assert post(client, "ingredient_bind", ingredient_id="chicken", product_id=str(chicken.id)).status_code == 200
    post(client, "meal_plan", day="0", recipe_id="tortillas", servings="6")
    post(client, "meal_sync")
    context = build_live_context(db, "test-family", DAY)
    row = next(r for r in context["shopping"]["rows"] if r.get("ingredient_id") == "chicken")
    assert row["price_label"] == "6,00 €"  # 750 g requires two 500 g packs.
    assert row["purchase_note"].startswith("2 iepak.")
    assert context["shopping"]["total_label"] == "6,00 €"
    recipe = context["planner"][0]["recipe"]
    assert recipe["known_cost_label"] == "4,50 €"
    assert recipe["cost_label"] == "—" and recipe["price_coverage"] == "1/4"
    assert db.scalar(select(func.count()).select_from(OfferProductLink)) == 0
    assert post(client, "ingredient_bind", ingredient_id="chicken", product_id="").status_code == 200
    assert build_live_context(db, "test-family", DAY)["shopping"]["total_label"] == "—"


def test_complete_recipe_prices_use_selected_products_without_global_matching(data):
    db, client, _ = data
    for key, pack, price in [("chicken", "500 g", "3"), ("tortilla", "8 Stück", "2"), ("pepper", "250 g", "1"), ("salad", "150 g", "2")]:
        row = offer(db, name=key, sku=key, package_text_raw=pack, price=price)
        assert post(client, "ingredient_bind", ingredient_id=key, product_id=str(row.id)).status_code == 200
    context = build_live_context(db, "test-family", DAY)
    recipe = next(r for r in context["recipes"] if r["id"] == "tortillas")
    assert recipe["price_complete"] and recipe["cost_label"] == "2,00 €"
    assert recipe["purchase_label"] == "8,00 €"


@pytest.mark.parametrize("pack,mode,key", [("1 l",None,"chicken"),("400 g / 500 g",None,"chicken"),("500 g","unit_price_only","chicken"),(None,None,"chicken")])
def test_ingredient_selection_rejects_unknown_or_incompatible_package(data,pack,mode,key):
    db,client,_ = data
    row=offer(db,package_text_raw=pack,pricing_mode=mode)
    assert post(client,"ingredient_bind",ingredient_id=key,product_id=str(row.id)).status_code == 422
    assert read_household(db,"test-family")[1] == 0


def test_selected_ingredient_expiry_and_conditional_price_stay_unknown(data):
    db,client,_ = data
    row=offer(db,package_text_raw="500 g",requires_app=True)
    post(client,"ingredient_bind",ingredient_id="chicken",product_id=str(row.id))
    context=build_live_context(db,"test-family",DAY)
    assert context["recipes"][0]["price_coverage"] == "0/4"
    row.requires_app=False
    row.valid_until=date(2026,9,30)
    db.commit()
    assert build_live_context(db,"test-family",DAY)["recipes"][0]["price_coverage"] == "0/4"


def test_multipack_and_piece_conversion():
    from types import SimpleNamespace
    from app.meal_pricing import requirement_price
    row=SimpleNamespace(package_text_raw="4 x 250 g",pricing_mode="fixed_package")
    assert requirement_price(row,"1500","g",Decimal("4"))["purchase_cost"] == 8
    row.package_text_raw="6 Stück"
    assert requirement_price(row,"8","gab.",Decimal("3"))["packs"] == 2
    row.package_text_raw="1 l"
    assert requirement_price(row,"100","ml",Decimal("2"))["used_cost"] == Decimal("0.2")


def test_measured_basket_compares_whole_packs_and_selection_resets_check(data):
    db, client, _ = data
    a = offer(db, name="Chicken test", package_text_raw="500 g", price="3")
    b = offer(db, name="Chicken test", package_text_raw="1 kg", chain="netto", store="netto-one", price="2")
    canonical = CanonicalProduct(display_name="Chicken test", normalized_name="chicken test", item_quantity_value=500, item_quantity_unit="g", pack_count=1)
    db.add(canonical)
    db.flush()
    for row in (a,b):
        db.add(OfferProductLink(offer_candidate_id=row.id, canonical_product_id=canonical.id, link_method="reviewed-test", confidence=Decimal("1")))
    db.commit()
    post(client, "ingredient_bind", ingredient_id="chicken", product_id=str(a.id))
    post(client, "meal_plan", day="0", recipe_id="tortillas", servings="6")
    post(client, "meal_sync")
    context = build_live_context(db, "test-family", DAY)
    assert {s["id"]:s["total_label"] for s in context["ranked_stores"]} == {"lidl":"6,00 €", "netto":"2,00 €"}
    assert context["best_store"] is None  # Three recipe ingredients are still unknown.
    chicken = next(r for r in context["shopping"]["rows"] if r.get("ingredient_id") == "chicken")
    post(client, "toggle", item_id=chicken["item_id"])
    post(client, "ingredient_bind", ingredient_id="chicken", product_id=str(b.id))
    state, _ = read_household(db,"test-family")
    assert not next(r for r in state["shopping"] if r.get("ingredient_id") == "chicken")["checked"]


def test_household_store_preferences_limit_complete_two_store_plan(data):
    db, client, _ = data
    a=offer(db,name="Pirmais",sku="first",price="1",chain="lidl",store="L")
    b=offer(db,name="Otrais",sku="second",price="2",chain="netto",store="N")
    post(client,"add",product_id=str(a.id))
    post(client,"add",product_id=str(b.id))
    context=build_live_context(db,"test-family",DAY)
    assert context["best_store"] is None
    assert context["two_store_plan"]["total_label"]=="3,00 €"
    assert len(context["two_store_plan"]["lines"])==2
    assert all(r["purchase_note"]=="1 × 1 l" for r in context["two_store_plan"]["lines"])
    response=client.get("/ui/home/?view=list&date=2026-10-01")
    assert "Ar diviem veikaliem" in response.text and str(a.id) in response.text
    assert post(client,"store_preferences",store_lidl="1").status_code==200
    context=build_live_context(db,"test-family",DAY)
    assert context["preferred_retailers"]==["lidl"] and context["two_store_plan"] is None
    assert {s["id"] for s in context["ranked_stores"]}=={"lidl"}
    post(client,"store_preferences")
    assert not build_live_context(db,"test-family",DAY)["ranked_stores"]
    assert "Nav izvēlēts neviens veikals" in client.get("/ui/home/?view=settings&date=2026-10-01").text


def test_shared_stylesheet_is_css_not_a_template(data):
    _, client, _ = data
    response = client.get("/ui/home/static/north-star.css")
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("text/css")
    assert "{%" not in response.text and "<section" not in response.text
    assert ":root{" in response.text and ".app-layout{" in response.text


def test_branch_preferences_preserve_other_branches_and_restore(data):
    db, client, _ = data
    a = offer(db, name="First branch", sku="first-branch", store="L:one", price="1")
    b = offer(db, name="Second branch", sku="second-branch", store="L-two", price="2")
    post(client, "add", product_id=str(a.id))
    post(client, "add", product_id=str(b.id))
    assert build_live_context(db, "test-family", DAY)["two_store_plan"]
    assert post(client, "branch_preference", chain="lidl", store="L:one", enabled="0").status_code == 200
    context = build_live_context(db, "test-family", DAY)
    assert context["two_store_plan"] is None
    assert [s["store_id"] for s in context["ranked_stores"]] == ["L-two"]
    assert len(context["shopping"]["rows"]) == 2
    assert any(not b["enabled"] and b["store_id"] == "L:one" for b in context["branch_options"])
    # Excluded branches remain reversible after the shopping list is cleared.
    for item in context["shopping"]["rows"]:
        post(client, "remove", item_id=item["item_id"])
    page = client.get("/ui/home/?view=settings&date=2026-10-01")
    assert 'Iekļaut LIDL L:one' in page.text
    assert post(client, "branch_preference", chain="lidl", store="L:one", enabled="1").status_code == 200
    assert read_household(db, "test-family")[0]["excluded_branches"] == []
    assert post(client, "branch_preference", chain="lidl", store="invented", enabled="0").status_code == 422


def test_price_eligibility_requires_each_condition_and_can_be_revoked(data):
    db, client, _ = data
    row = offer(db, requires_app=True, coupon_required=True, price="2")
    post(client, "add", product_id=str(row.id))
    assert build_live_context(db, "test-family", DAY)["shopping"]["total_label"] == "—"
    post(client, "price_eligibility", product_id=str(row.id), app="1")
    assert build_live_context(db, "test-family", DAY)["shopping"]["total_label"] == "—"
    response = post(client, "price_eligibility", product_id=str(row.id), app="1", coupon="1")
    assert response.status_code == 200 and response.url.params["product"] == str(row.id)
    context = build_live_context(db, "test-family", DAY)
    assert context["shopping"]["total_label"] == "2,00 €"
    assert context["shopping"]["rows"][0]["conditional_price_used"]
    assert context["best_store"]["total_label"] == "2,00 €"
    post(client, "price_eligibility", product_id=str(row.id))
    assert build_live_context(db, "test-family", DAY)["shopping"]["total_label"] == "—"


def test_app_price_selection_respects_dates_and_does_not_transfer_to_new_observation(data):
    db, client, _ = data
    row = offer(db, price="3", app_price_eur=Decimal("2"), app_valid_from=DAY, app_valid_until=DAY)
    post(client, "add", product_id=str(row.id))
    assert build_live_context(db, "test-family", DAY)["shopping"]["total_label"] == "3,00 €"
    post(client, "price_eligibility", product_id=str(row.id), app="1")
    context = build_live_context(db, "test-family", DAY, product=str(row.id))
    assert context["shopping"]["total_label"] == "2,00 €"
    assert context["selected_product"]["price_label"] == "3,00 €"  # Source price stays intact.
    assert context["selected_product"]["history"]["series"][0]["price_label"] == "3,00 €"
    assert build_live_context(db, "test-family", date(2026,10,2))["shopping"]["total_label"] == "3,00 €"
    newer = offer(db, price="4", collected_day=2, app_price_eur=Decimal("1"), app_valid_from=DAY, app_valid_until=date(2026,10,4))
    assert build_live_context(db, "test-family", date(2026,10,2))["shopping"]["total_label"] == "4,00 €"


def test_eligible_recipe_price_still_requires_known_quantity(data):
    db, client, _ = data
    row = offer(db, package_text_raw="500 g", requires_app=True, price="3")
    post(client, "ingredient_bind", ingredient_id="chicken", product_id=str(row.id))
    post(client, "price_eligibility", product_id=str(row.id), app="1")
    context = build_live_context(db, "test-family", DAY)
    assert context["recipes"][0]["price_coverage"] == "1/4"
    row.pricing_mode = "unit_price_only"
    db.commit()
    assert build_live_context(db, "test-family", DAY)["recipes"][0]["price_coverage"] == "0/4"


def test_comparison_requires_confirmation_for_each_offer(data):
    db, client, _ = data
    a = offer(db, requires_app=True, price="3")
    b = offer(db, requires_app=True, chain="netto", store="N", price="2")
    canonical = CanonicalProduct(display_name="Test", normalized_name="test", item_quantity_value=1, item_quantity_unit="l", pack_count=1)
    db.add(canonical)
    db.flush()
    for row in (a, b):
        db.add(OfferProductLink(offer_candidate_id=row.id, canonical_product_id=canonical.id, link_method="reviewed-test", confidence=Decimal("1")))
    db.commit()
    post(client, "add", product_id=str(a.id))
    post(client, "price_eligibility", product_id=str(a.id), app="1")
    assert build_live_context(db, "test-family", DAY)["best_store"]["id"] == "lidl"
    post(client, "price_eligibility", product_id=str(b.id), app="1")
    context = build_live_context(db, "test-family", DAY)
    assert context["best_store"]["id"] == "netto"
    assert context["best_store"]["total_label"] == "2,00 €"


def test_free_text_need_can_bind_and_replace_offer_without_duplicate(data):
    db, client, _ = data
    a = offer(db, name="Piens izvēlei", price="2")
    b = offer(db, name="Cits piens", sku="other-milk", price="3")
    post(client, "add", name="Piens & maize")
    item = read_household(db, "test-family")[0]["shopping"][0]
    post(client, "quantity", item_id=item["item_id"], quantity="2")
    page = client.get("/ui/home/?view=list&date=2026-10-01")
    assert 'Atrast piedāvājumu' in page.text and 'q=Piens%20%26%20maize' in page.text
    for row, total in ((a, "4,00 €"), (b, "6,00 €")):
        response = post(client, "shopping_bind", item_id=item["item_id"], product_id=str(row.id))
        assert response.status_code == 200
        context = build_live_context(db, "test-family", DAY)
        assert len(context["shopping"]["rows"]) == 1
        selected = context["shopping"]["rows"][0]
        assert selected["item_id"] == item["item_id"] and selected["name"] == "Piens & maize"
        assert selected["quantity"] == 2 and selected["offer_name"] == row.product_name_raw
        assert context["shopping"]["total_label"] == total
        assert db.scalar(select(func.count()).select_from(OfferProductLink)) == 0
    post(client, "toggle", item_id=item["item_id"])
    assert post(client, "shopping_bind", item_id=item["item_id"], product_id=str(a.id)).status_code == 422


def test_shopping_bind_rejects_unknown_offer_and_meal_row(data):
    db, client, _ = data
    row = offer(db)
    post(client, "add", name="Need")
    item = read_household(db, "test-family")[0]["shopping"][0]
    assert post(client, "shopping_bind", item_id=item["item_id"], product_id="not-an-offer").status_code == 422
    assert read_household(db, "test-family")[0]["shopping"][0]["product_id"] is None
    post(client, "meal_plan", day="0", recipe_id="tortillas", servings="4")
    post(client, "meal_sync")
    meal = next(item for item in read_household(db, "test-family")[0]["shopping"] if item.get("meal_week"))
    assert post(client, "shopping_bind", item_id=meal["item_id"], product_id=str(row.id)).status_code == 422


def test_personal_overview_uses_explicit_choices_not_catalogue_page(data):
    db, client, _ = data
    a = offer(db, name="Z selected", sku="personal-a", package_text_raw="500 g")
    b = offer(db, name="A favorite", sku="personal-b")
    offer(db, name="Unrelated", sku="unrelated")
    post(client, "add", product_id=str(a.id))
    post(client, "favorite", product_id=str(a.id))
    post(client, "ingredient_bind", ingredient_id="chicken", product_id=str(a.id))
    post(client, "favorite", product_id=str(b.id))
    context = build_live_context(db, "test-family", DAY, offset=60)
    assert not context["offers"]
    assert [o["id"] for o in context["personal_offers"]] == [str(a.id), str(b.id)]
    assert context["personal_offers"][0]["reasons"] == ["Tavā sarakstā", "Saglabāts favorītos", "Izvēlēts receptēm"]
    page = client.get('/ui/home/?view=overview&date=2026-10-01')
    assert "Tavas ģimenes izvēlētie produkti" in page.text and "Tavā sarakstā · Saglabāts favorītos" in page.text


def test_personal_overview_excludes_expired_future_and_purchased_only_choices(data):
    db, client, _ = data
    expired = offer(db, sku="expired", valid_until=date(2026,9,30))
    future = offer(db, sku="future", collected_day=2)
    bought = offer(db, sku="bought")
    post(client, "favorite", product_id=str(expired.id))
    post(client, "favorite", product_id=str(future.id))
    post(client, "add", product_id=str(bought.id))
    item = read_household(db, "test-family")[0]["shopping"][0]
    post(client, "toggle", item_id=item["item_id"])
    assert not build_live_context(db, "test-family", DAY)["personal_offers"]
    assert "Izvēlētās dienas piedāvājumi" in client.get('/ui/home/?view=overview&date=2026-10-01').text


@pytest.mark.parametrize("view", ["overview", "deals", "list", "planner", "recipes", "favorites", "history", "statistics", "settings"])
def test_htmx_fragment_matches_full_server_projection(data, view):
    _, client, _ = data
    url = f"/ui/home/?view={view}&date=2026-10-01"
    full = client.get(url)
    partial = client.get(url, headers={"HX-Request": "true"})
    assert partial.status_code == 200
    assert "<!doctype" not in partial.text and "<body" not in partial.text
    assert "<script" not in partial.text
    assert partial.text[partial.text.index('<div id="home-content"'):].strip() == full.text[full.text.index('<div id="home-content"'):].removesuffix('</body></html>').strip()
    for response in (full, partial):
        assert response.headers["Vary"] == "HX-Request, HX-History-Restore-Request"
        assert response.headers["Cache-Control"] == "no-store"
        assert 'hx-history="false"' in response.text
    restored = client.get(url, headers={"HX-Request": "true", "HX-History-Restore-Request": "true"})
    assert "<!doctype" in restored.text


def test_htmx_filters_escape_source_and_keep_forms_unboosted(data):
    db, client, _ = data
    row = offer(db, name='<script>alert("test")</script>', requires_app=True)
    offer(db, name="Unrelated", sku="other")
    page = client.get('/ui/home/?view=deals&date=2026-10-01&q=script&retailer=lidl', headers={"HX-Request": "true"})
    assert '&lt;script&gt;' in page.text and 'Unrelated' not in page.text
    assert 'name="q" value="script"' in page.text
    assert 'value="lidl" selected' in page.text
    assert 'method="post" hx-boost="false"' in page.text
    detail = client.get(f'/ui/home/?view=deals&date=2026-10-01&product={row.id}', headers={"HX-Request": "true"})
    assert 'role="dialog"' in detail.text and 'lietotn' in detail.text.lower()
    invalid = client.post('/ui/home/actions/add', data={"product_id": str(row.id)}, headers={"HX-Request": "true"})
    assert invalid.status_code == 403
    assert read_household(db, "test-family")[1] == 0


def test_htmx_asset_is_packaged_upstream_pin(data):
    import hashlib
    _, client, _ = data
    asset = client.get('/ui/home/static/vendor/htmx-2.0.11.min.js')
    assert asset.status_code == 200
    assert hashlib.sha1(f"blob {len(asset.content)}\0".encode() + asset.content).hexdigest() == "e6b8394acb5cda3281a68b4078775ec348d8eafc"


def test_history_discovers_expired_series_without_active_deals(data):
    db, client, _ = data
    offer(db, price="1.49")
    latest = offer(db, price="1.19", collected_day=2)
    params = {"date": "2026-10-27", "q": "Piens", "retailer": "lidl"}
    deals = client.get("/ui/home/", params={**params, "view": "deals"})
    assert 'class="offer-card"' not in deals.text
    history = client.get("/ui/home/", params={**params, "view": "history"})
    assert history.status_code == 200
    assert history.text.count('class="offer-card"') == 1
    assert str(latest.id) in history.text
    assert "Pēdējā novērotā cena" in history.text
    assert "1,19 €" in history.text
    assert "02.10.2026 10:00" in history.text
    detail = client.get("/ui/home/", params={**params, "view": "history", "product": str(latest.id)})
    assert "Cenu novērojumi" in detail.text
    assert "1,49 €" in detail.text


def test_history_empty_search_differs_from_unknown_price_basis(data):
    db, client, _ = data
    row = offer(db, package_text_raw=None)
    empty = client.get('/ui/home/?view=history&date=2026-10-27&q=not-found')
    assert 'Cenu vēsturē nekas nav atrasts' in empty.text
    assert 'Notīrīt vēstures filtrus' in empty.text
    detail = client.get(f'/ui/home/?view=history&date=2026-10-27&product={row.id}')
    assert 'Cenu vēsturē nekas nav atrasts' not in detail.text
    assert 'Šim datumam vēl nav saglabātu salīdzināmu cenu novērojumu.' in detail.text
    assert '<div class="detail-price">—</div>' in detail.text


def test_history_hides_future_observations_even_by_direct_link(data):
    db, client, _ = data
    row = offer(db, collected_day=2)
    page = client.get(f'/ui/home/?view=history&date=2026-10-01&product={row.id}')
    assert 'class="offer-card"' not in page.text
    assert 'role="dialog"' not in page.text
    assert str(row.id) not in page.text


def test_history_unit_price_is_not_example_package_total(data):
    db, client, _ = data
    row = offer(db, price="4.20", pricing_mode="example_total_plus_unit", unit_price_eur=Decimal("9.99"), unit_label="kg")
    page = client.get(f'/ui/home/?view=history&date=2026-10-27&product={row.id}')
    assert '<strong class="offer-price">9,99 €/kg</strong>' in page.text
    assert '<div class="detail-price">9,99 €/kg</div>' in page.text
    assert '4,20 €' not in page.text
    assert '/actions/add' not in page.text
    assert '/actions/price_eligibility' not in page.text


def test_history_pagination_detail_close_preserves_filters(data):
    from html import unescape
    from urllib.parse import parse_qs, urlsplit
    db, client, _ = data
    for i in range(61):
        offer(db, name=f'Piens & testam {i:03}', sku=f'milk-{i}')
    params = {'view': 'history', 'date': '2026-10-27', 'q': 'Piens &', 'retailer': 'lidl', 'sort': 'name'}
    first = client.get('/ui/home/', params=params)
    assert first.text.count('class="offer-card"') == 60
    next_link = unescape(re.search(r'href="([^"]+)">Nākamā lapa', first.text)[1])
    last = client.get(next_link)
    assert last.text.count('class="offer-card"') == 1
    assert '61–61 no 61 cenu sērijām' in last.text
    link = unescape(re.search(r'class="offer-title" href="([^"]+)"', last.text)[1])
    detail = client.get(link)
    assert 'role="dialog"' in detail.text
    close = unescape(re.search(r'data-dialog-close href="([^"]+)"', detail.text)[1])
    expected = {k: [v] for k, v in params.items() if not (k == 'sort' and v == 'name')}
    assert parse_qs(urlsplit(close).query) == {**expected, 'offset': ['60']}
    assert client.get(close).text.count('class="offer-card"') == 1
    fragment = client.get(link, headers={'HX-Request': 'true'})
    assert fragment.status_code == 200
    assert 'Cenu novērojumi' in fragment.text
    assert 'no-store' in fragment.headers['cache-control']


def test_history_base_observation_does_not_inherit_current_app_conditions(data):
    db, client, _ = data
    row = offer(db, app_price_eur=Decimal('0.99'), app_valid_from=date(2026, 10, 20), app_valid_until=date(2026, 10, 30))
    page = client.get(f'/ui/home/?view=history&date=2026-10-27&product={row.id}')
    assert '<div class="detail-price">1,29 €</div>' in page.text
    assert 'Nepieciešama veikala lietotne' not in page.text
    assert 'Avota cenai nepieciešama veikala lietotne' not in page.text


def test_recipe_ingredient_context_round_trip_binds_exact_ingredient_and_returns_to_row(data):
    from html import unescape
    from urllib.parse import parse_qs, urlsplit

    db, client, _ = data
    row = offer(db, name="Vista izvēlei", package_text_raw="500 g", price="3.00")

    recipes = client.get("/ui/home/?view=recipes&date=2026-10-01")
    assert recipes.status_code == 200
    assert "id=\"ingredient-tortillas-chicken\"" in recipes.text
    assert "view=deals&amp;date=2026-10-01&amp;recipe_id=tortillas&amp;ingredient_id=chicken" in recipes.text

    params = {"view": "deals", "date": "2026-10-01", "recipe_id": "tortillas", "ingredient_id": "chicken"}
    deals = client.get("/ui/home/", params=params)
    assert deals.status_code == 200
    assert "Izvēlies produktu sastāvdaļai Vistas fileja" in deals.text
    assert "Recepte: Vistas tortiljas" in deals.text
    assert 'name="recipe_id" value="tortillas"' in deals.text
    assert 'name="ingredient_id" value="chicken"' in deals.text

    detail = client.get("/ui/home/", params={**params, "product": str(row.id)})
    assert detail.status_code == 200
    assert "Apstiprināt šo produktu" in detail.text
    assert '<select name="ingredient_id"' not in detail.text
    close = unescape(re.search(r'data-dialog-close href="([^"]+)"', detail.text)[1])
    assert parse_qs(urlsplit(close).query) == {
        "view": ["deals"],
        "date": ["2026-10-01"],
        "recipe_id": ["tortillas"],
        "ingredient_id": ["chicken"],
    }
    cancelled = client.get(close)
    assert cancelled.status_code == 200
    assert "Atgriezties receptē" in cancelled.text
    assert read_household(db, "test-family")[1] == 0

    detail = client.get("/ui/home/", params={**params, "product": str(row.id)})
    form = {
        "csrf_token": re.search(r'name="csrf_token" value="([^"]+)"', detail.text)[1],
        "version": re.search(r'name="version" value="([^"]+)"', detail.text)[1],
        "date": "2026-10-01",
        "return_view": "deals",
        "recipe_id": "tortillas",
        "ingredient_id": "chicken",
        "product_id": str(row.id),
    }
    response = client.post(
        "/ui/home/actions/ingredient_bind",
        data=form,
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    assert response.headers["location"].endswith(
        "?view=recipes&date=2026-10-01&saved=1#ingredient-tortillas-chicken"
    )
    state, version = read_household(db, "test-family")
    assert version == 1
    assert state["ingredient_offers"] == {"chicken": str(row.id)}
    restored = client.get(response.headers["location"])
    assert restored.status_code == 200
    assert 'id="ingredient-tortillas-chicken"' in restored.text


@pytest.mark.parametrize(
    "recipe_id,ingredient_id",
    [
        ("missing", "chicken"),
        ("omelette", "chicken"),
        ("tortillas", "missing"),
        ("tortillas", ""),
        ("", "chicken"),
    ],
)
def test_invalid_recipe_ingredient_navigation_context_is_rejected(data, recipe_id, ingredient_id):
    db, client, _ = data
    response = client.get(
        "/ui/home/",
        params={
            "view": "deals",
            "date": "2026-10-01",
            "recipe_id": recipe_id,
            "ingredient_id": ingredient_id,
        },
    )
    assert response.status_code == 422
    assert read_household(db, "test-family")[1] == 0


def test_invalid_recipe_context_cannot_mutate_ingredient_binding(data):
    db, client, _ = data
    row = offer(db, name="Vista", package_text_raw="500 g")
    page = client.get("/ui/home/?view=deals&date=2026-10-01")
    response = client.post(
        "/ui/home/actions/ingredient_bind",
        data={
            "csrf_token": re.search(r'name="csrf_token" value="([^"]+)"', page.text)[1],
            "version": re.search(r'name="version" value="([^"]+)"', page.text)[1],
            "date": "2026-10-01",
            "return_view": "deals",
            "recipe_id": "omelette",
            "ingredient_id": "chicken",
            "product_id": str(row.id),
        },
        headers={"Origin": "http://testserver"},
    )
    assert response.status_code == 422
    assert read_household(db, "test-family")[1] == 0


def test_ui_get_http_errors_render_html_and_keep_api_json_contract(data):
    _, client, _ = data
    cases = [
        ("/ui/home/?date=invalid", 422, "Norādi datumu formātā GGGG-MM-DD", "Pārbaudi ievadītos datus"),
        ("/ui/home/?view=unknown&date=2026-10-01", 404, "Sadaļa nav atrasta.", "Sadaļa nav atrasta"),
    ]
    for url, status, message, title in cases:
        for headers in ({}, {"HX-Request": "true"}):
            response = client.get(url, headers=headers)
            assert response.status_code == status
            assert response.headers["content-type"].startswith("text/html")
            assert "<!doctype html>" in response.text
            assert message in response.text and title in response.text
            assert 'data-error-focus' in response.text and 'role="alert"' in response.text
            assert "application/json" not in response.headers["content-type"]

    missing_id = "00000000-0000-0000-0000-000000000001"
    api = client.get(f"/api/v1/canonical-products/{missing_id}")
    assert api.status_code == 404
    assert api.headers["content-type"].startswith("application/json")
    assert api.json()["detail"] == f"Canonical product {missing_id} not found"


def test_csrf_conflict_and_validation_have_distinct_html_error_semantics(data):
    db, client, _ = data

    fresh = form_values(client, "settings")
    csrf = client.post(
        "/ui/home/actions/settings",
        data={
            **fresh,
            "csrf_token": "expired",
            "household": "Mana ģimene",
            "location": "Dortmunde",
            "people": "4",
        },
        headers={"Origin": "http://testserver"},
        follow_redirects=False,
    )
    assert csrf.status_code == 403
    assert csrf.headers["content-type"].startswith("text/html")
    assert "Veidlapas derīgums beidzies." in csrf.text
    assert "Atvērt svaigu formu" in csrf.text
    assert 'data-error-focus' in csrf.text
    assert read_household(db, "test-family")[1] == 0

    stale = form_values(client, "list")
    assert post(client, "add", name="Piens").status_code == 200
    conflict = client.post(
        "/ui/home/actions/add",
        data={**stale, "name": "Maize"},
        headers={"Origin": "http://testserver"},
    )
    assert conflict.status_code == 409
    assert conflict.headers["content-type"].startswith("text/html")
    assert 'data-notice-kind="conflict"' in conflict.text
    assert 'role="alert"' in conflict.text
    assert "Atsvaidzināt datus" in conflict.text
    assert 'data-notice-kind="success"' not in conflict.text

    invalid = post(client, "meal_plan", day="7", recipe_id="pasta", servings="4")
    assert invalid.status_code == 422
    assert invalid.headers["content-type"].startswith("text/html")
    assert 'data-notice-kind="error"' in invalid.text
    assert 'role="alert"' in invalid.text
    assert "Atgriezties pie formas" in invalid.text
    assert 'data-notice-kind="success"' not in invalid.text


def test_error_focus_and_htmx_fallback_never_retry_post(data):
    _, client, _ = data
    script = client.get("/ui/home/static/north-star.js")
    assert script.status_code == 200
    text = script.text
    assert "document.querySelector('[data-notice-focus], [data-error-focus]')" in text
    assert "urgentMessage.focus({ preventScroll: true })" in text
    assert "if (config?.verb !== 'get') return;" in text
    assert "location.assign(url.href)" in text


@pytest.mark.parametrize("headers", [{}, {"HX-Request": "true"}])
def test_empty_favorites_explains_saving_and_preserves_date(data, headers):
    _, client, _ = data
    response = client.get("/ui/home/?view=favorites&date=2026-10-03", headers=headers)
    assert response.status_code == 200
    assert "Vēl nav saglabātu produktu" in response.text
    assert "sirds pogu" in response.text
    assert "Pamēģini citu nosaukumu" not in response.text
    assert "izvēlies visus veikalus" not in response.text
    assert 'href="/ui/home/?view=deals&date=2026-10-03"' in unescape(response.text)
    assert "Atvērt piedāvājumus" in response.text


def test_populated_favorites_keeps_product_actions(data):
    db, client, _ = data
    row = offer(db)
    post(client, "favorite", product_id=str(row.id))
    page = client.get("/ui/home/?view=favorites&date=2026-10-01")
    assert page.status_code == 200
    assert "Vēl nav saglabātu produktu" not in page.text
    assert "Piens testam" in page.text
    assert "Noņemt no favorītiem: Piens testam" in page.text
    assert "Pievienot sarakstam: Piens testam" in page.text


def test_other_empty_views_do_not_show_favorite_instructions(data):
    _, client, _ = data
    for view in ("deals", "history"):
        page = client.get(f"/ui/home/?view={view}&date=2026-10-03&q=missing")
        assert page.status_code == 200
        assert "Vēl nav saglabātu produktu" not in page.text
        assert "sirds pogu" not in page.text
        assert 'name="q"' in page.text
    assert "Cenu vēsturē nekas nav atrasts" in page.text


# Booklet integration uses synthetic JSON metadata and persisted test rows only.
def booklet_source(db, tmp_path, monkeypatch, **overrides):
    from hashlib import sha256
    import json
    from types import SimpleNamespace
    import app.netto_booklets as booklets

    monkeypatch.setattr(booklets, "get_settings", lambda: SimpleNamespace(raw_snapshot_dir=tmp_path))
    publication = tmp_path / "publication.json"
    publication.write_text(json.dumps({"spreads": [{"pages": ["/test-booklet/page1", "/test-booklet/page2"]}]}))
    manifest = {
        "strategy": booklets.STRATEGIES[-1], "store_external_id": "5659",
        "store_name": "Netto · sintētiska testa filiāle", "scope": "family_primary_netto",
        "store_url": "https://www.netto-online.de/filialen/dortmund/rauschenbuschstr-1/5659",
        "selected_store_cookie_present": True,
        "valid_from": "2026-09-28", "valid_until": "2026-10-04",
        "publication_path": str(publication), "publication_sha256": sha256(publication.read_bytes()).hexdigest(),
        "prospect_url": "https://view.publitas.com/netto-marken-discount/test-booklet/",
        "prospect_pdf_sha256": "a" * 64,
    }
    manifest.update(overrides)
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    snapshot = SourceSnapshot(
        source_chain="netto", source_url=manifest["store_url"], scope="family_primary_netto",
        collected_at=datetime(2026, 10, 1, 8, tzinfo=timezone.utc),
        strategy_hint=booklets.STRATEGIES[-1], success=True,
        snapshot_path=str(path), sha256=sha256(path.read_bytes()).hexdigest(),
    )
    db.add(snapshot)
    db.commit()
    return snapshot, manifest


def booklet_offer(db, snapshot, *, page=1, raw=None, **values):
    return offer(db, chain="netto", store="5659", snapshot_id=snapshot.id,
                 name="Sintētisks testa piens", sku=None,
                 raw_payload=raw if raw is not None else {"source_pdf_sha256": "a" * 64, "special_source_page": page},
                 **values)


def test_booklet_pages_and_details_reuse_existing_ui(data, tmp_path, monkeypatch):
    from app.netto_booklets import build_netto_booklet
    db, client, _ = data
    snapshot, _ = booklet_source(db, tmp_path, monkeypatch)
    row = booklet_offer(db, snapshot, page=2)
    context = build_netto_booklet(db, DAY, 2)
    assert context["state"] == "ready" and context["offers"] == [row]
    assert context["page_count"] == 2 and context["next_href"] is None
    assert context["image_url"] == "https://view.publitas.com/test-booklet/page2-at1600.jpg"
    assert not list(tmp_path.glob("*.pdf"))
    url = "/ui/home/?view=booklets&date=2026-10-01&page=2"
    for headers in ({}, {"HX-Request": "true"}):
        response = client.get(url, headers=headers)
        assert response.status_code == 200, response.text
        assert "Nedēļas bukleti" in response.text and "Sintētisks testa piens" in response.text
        assert 'name="page" value="2"' in response.text
        assert 'id="booklet-zoom"' in response.text
        assert response.headers["Cache-Control"] == "no-store"
        assert ("<!doctype html>" in response.text.lower()) == (not headers)
        detail = client.get(url + f"&product={row.id}", headers=headers)
        assert detail.status_code == 200
        assert "Cenu novērojumi" in detail.text
        assert 'href="/ui/home/?view=booklets&amp;date=2026-10-01&amp;page=2"' in detail.text
    assert db.scalar(select(func.count()).select_from(HouseholdState)) == 0
    normal = client.get("/ui/home/?view=deals&date=2026-10-01")
    assert normal.status_code == 200 and 'class="booklet-reader"' not in normal.text
    assert 'view=booklets' in normal.text


@pytest.mark.parametrize("action,state_key", [("add", "shopping"), ("favorite", "favorites")])
def test_booklet_actions_preserve_page_and_write_existing_household(data, tmp_path, monkeypatch, action, state_key):
    db, client, _ = data
    snapshot, _ = booklet_source(db, tmp_path, monkeypatch)
    row = booklet_offer(db, snapshot, page=2)
    url = "/ui/home/?view=booklets&date=2026-10-01&page=2"
    html = client.get(url).text
    values = {"csrf_token": re.search(r'name="csrf_token" value="([^"]+)"', html)[1],
              "version": re.search(r'name="version" value="([^"]+)"', html)[1],
              "return_view": "booklets", "date": "2026-10-01", "page": "2", "product_id": str(row.id)}
    result = client.post(f"/ui/home/actions/{action}", data=values, headers={"Origin": "http://testserver"}, follow_redirects=False)
    assert result.status_code == 303
    assert parse_qs(urlsplit(result.headers["location"]).query)["page"] == ["2"]
    assert parse_qs(urlsplit(result.headers["location"]).query)["view"] == ["booklets"]
    assert len(read_household(db, "test-family")[0][state_key]) == 1
    conflict = client.post(f"/ui/home/actions/{action}", data=values, headers={"Origin": "http://testserver"})
    assert conflict.status_code == 409
    assert 'page2-at1600.jpg' in conflict.text and 'name="page" value="2"' in conflict.text


@pytest.mark.parametrize("page", ["0", "-1", "201", "bad"])
def test_booklet_invalid_page_is_422(data, page):
    _, client, _ = data
    assert client.get(f"/ui/home/?view=booklets&date=2026-10-01&page={page}").status_code == 422


def test_booklet_empty_unlinked_missing_and_date_reset(data, tmp_path, monkeypatch):
    db, client, _ = data
    url = "/ui/home/?view=booklets&date=2026-10-01"
    assert 'data-booklet-state="empty"' in client.get(url).text
    booklet_source(db, tmp_path, monkeypatch)
    html = client.get(url + "&page=2").text
    assert "Produkti vēl nav piesaistīti" in html
    assert "DEMONSTRĀCIJAS DATI" not in html
    assert 'href="/ui/home/?view=booklets&amp;date=2026-10-02"' in html
    missing = client.get(url + "&page=3").text
    assert 'data-booklet-state="missing_page"' in missing and "Atvērt pirmo lapu" in missing
    assert 'data-booklet-state="empty"' in client.get("/ui/home/?view=booklets&date=2026-10-05").text


@pytest.mark.parametrize("raw", [
    {}, [], {"source_pdf_sha256": "b" * 64, "special_source_page": 1},
    {"source_pdf_sha256": "a" * 64, "special_source_page": 2},
    {"source_pdf_sha256": "a" * 64, "special_source_page": "1"},
    {"source_pdf_sha256": "a" * 64, "special_source_page": True},
    {"source_pdf_sha256": "a" * 64, "special_source_page": 1, "shadow_only": True},
    {"source_pdf_sha256": "a" * 64, "special_source_page": 1, "db_write_eligible": False},
])
def test_booklet_never_guesses_unproven_offer_links(data, tmp_path, monkeypatch, raw):
    from app.netto_booklets import build_netto_booklet
    db, _, _ = data
    snapshot, _ = booklet_source(db, tmp_path, monkeypatch)
    booklet_offer(db, snapshot, raw=raw)
    assert build_netto_booklet(db, DAY)["offers"] == []


@pytest.mark.parametrize("field,value", [
    ("source_chain", "lidl"), ("source_store_external_id", "other"),
    ("valid_from", date(2026, 10, 2)), ("valid_until", date(2026, 9, 30)),
    ("collected_at", datetime(2026, 10, 2, 0, tzinfo=timezone.utc)),
    ("snapshot_id", None),
])
def test_booklet_excludes_wrong_offer_provenance(data, tmp_path, monkeypatch, field, value):
    from app.netto_booklets import build_netto_booklet
    db, _, _ = data
    snapshot, _ = booklet_source(db, tmp_path, monkeypatch)
    row = booklet_offer(db, snapshot)
    if field == "snapshot_id":
        value = offer(db).snapshot_id
    setattr(row, field, value)
    db.commit()
    assert build_netto_booklet(db, DAY)["offers"] == []


@pytest.mark.parametrize("overrides", [
    {"store_external_id": "other"}, {"scope": "other"}, {"selected_store_cookie_present": False},
    {"strategy": "netto_store_page_plus_current_prospect_v1"},
    {"valid_until": "2026-09-01"}, {"valid_from": "invalid"},
    {"publication_sha256": "b" * 64}, {"publication_path": "/missing/publication.json"},
    {"prospect_url": "https://attacker.invalid/booklet"}, {"prospect_url": "javascript:alert(1)"},
])
def test_booklet_rejects_unverifiable_manifest(data, tmp_path, monkeypatch, overrides):
    from app.netto_booklets import build_netto_booklet
    db, client, _ = data
    booklet_source(db, tmp_path, monkeypatch, **overrides)
    assert build_netto_booklet(db, DAY)["state"] == "unavailable"
    html = client.get("/ui/home/?view=booklets&date=2026-10-01").text
    assert "Mēģini vēlāk" in html and str(tmp_path) not in html


@pytest.mark.parametrize("paths", [
    ["//attacker.invalid/page"], ["/../page"], ["/x?evil=1"], ["/x#fragment"],
    ["https://attacker.invalid/page"], [], ["/same", "/same"], ["/page" + str(i) for i in range(201)],
])
def test_booklet_rejects_invalid_publication_paths(data, tmp_path, monkeypatch, paths):
    from hashlib import sha256
    import json
    from app.netto_booklets import build_netto_booklet
    db, _, _ = data
    snapshot, manifest = booklet_source(db, tmp_path, monkeypatch)
    publication = tmp_path / "publication.json"
    publication.write_text(json.dumps({"spreads": [{"pages": paths}]}))
    manifest["publication_sha256"] = sha256(publication.read_bytes()).hexdigest()
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    snapshot.sha256 = sha256(path.read_bytes()).hexdigest()
    db.commit()
    assert build_netto_booklet(db, DAY)["state"] == "unavailable"


def test_booklet_metadata_integrity_boundary(data, tmp_path, monkeypatch):
    from app.netto_booklets import build_netto_booklet, _verified_json, MAX_JSON
    from hashlib import sha256
    db, _, _ = data
    snapshot, _ = booklet_source(db, tmp_path, monkeypatch)
    snapshot.collected_at = datetime(2026, 10, 2, 0, tzinfo=timezone.utc)
    db.commit()
    assert build_netto_booklet(db, DAY)["state"] == "empty"
    snapshot.collected_at = datetime(2026, 10, 1, 8, tzinfo=timezone.utc)
    snapshot.sha256 = "c" * 64
    db.commit()
    assert build_netto_booklet(db, DAY)["state"] == "unavailable"
    for page in (0, 201, True):
        with pytest.raises(ValueError):
            build_netto_booklet(db, DAY, page)
    outside = tmp_path / "outside.json"
    outside.write_bytes(b"{}")
    with pytest.raises(ValueError):
        _verified_json(str(outside), sha256(b"{}").hexdigest(), tmp_path / "child")
    for content in (b"[]", b"x" * (MAX_JSON + 1)):
        outside.write_bytes(content)
        with pytest.raises(ValueError):
            _verified_json(str(outside), sha256(content).hexdigest(), tmp_path)


def test_booklet_escapes_source_labels_and_exports_ci_preview(data, tmp_path, monkeypatch):
    import os
    from pathlib import Path
    import shutil
    db, client, _ = data
    snapshot, _ = booklet_source(db, tmp_path, monkeypatch, store_name="<script>source-label</script>")
    row = booklet_offer(db, snapshot)
    html = client.get("/ui/home/?view=booklets&date=2026-10-01").text
    assert "&lt;script&gt;source-label&lt;/script&gt;" in html
    assert "<script>source-label</script>" not in html
    output = os.getenv("BOOKLET_UI_EVIDENCE_DIR")
    if not output:
        return
    target = Path(output)
    target.mkdir(parents=True, exist_ok=True)
    shutil.copytree(Path(__file__).parents[1] / "app/north_star/static", target / "static", dirs_exist_ok=True)
    # A clearly labelled synthetic sheet, never an imitation of retailer data.
    (target / "test-page.svg").write_text(
        '<svg xmlns="http://www.w3.org/2000/svg" width="840" height="1120" viewBox="0 0 840 1120">'
        '<rect width="840" height="1120" fill="#fff7ce"/><rect width="840" height="150" fill="#f7d644"/>'
        '<g font-family="sans-serif" fill="#263b30"><text x="45" y="70" font-size="40">SINTĒTISKA TESTA LAPA</text>'
        '<text x="45" y="120" font-size="25">Tikai UI pārbaudei · nav veikala piedāvājums</text>'
        '<rect x="45" y="195" width="750" height="380" rx="15" fill="white"/>'
        '<text x="85" y="265" font-size="34">Sintētisks testa piens</text>'
        '<rect x="110" y="310" width="130" height="210" rx="15" fill="#d9e9e0"/>'
        '<text x="350" y="400" font-size="76">1,29 €</text><text x="350" y="455" font-size="28">Testa iepakojums · 1 l</text>'
        '<rect x="45" y="615" width="350" height="380" rx="15" fill="white"/>'
        '<rect x="425" y="615" width="370" height="380" rx="15" fill="white"/>'
        '<text x="85" y="690" font-size="26">Lapas laukums</text><text x="465" y="690" font-size="26">Lapas laukums</text>'
        '<text x="45" y="1070" font-size="24">Produkta darbības — blakus esošajā sarakstā</text></g></svg>'
    )
    html = html.replace("/ui/home/static/", "static/").replace(
        "https://view.publitas.com/test-booklet/page1-at1600.jpg", "test-page.svg"
    ).replace("SAGLABĀTIE DATI", "SINTĒTISKI TESTA DATI").replace(
        "&lt;script&gt;source-label&lt;/script&gt;", "Sintētiska testa filiāle"
    )
    # Browser layout assertion is test-only; the application gains no JS state.
    html = html.replace("</body>", '<script src="layout-proof.js"></script></body>')
    (target / "layout-proof.js").write_text(
        'addEventListener("load",()=>{setTimeout(()=>{'
        'document.documentElement.dataset.bookletOverflow=String(document.documentElement.scrollWidth>innerWidth);'
        'document.documentElement.dataset.bookletImage=String(document.querySelector(".booklet-page-image").naturalWidth>0);'
        '},100);});'
    )
    (target / "booklets.html").write_text(html)


@pytest.mark.parametrize("selected_query", ["", "?stores_id=5659"])
def test_booklet_accepts_observed_netto_collector_urls(data, tmp_path, monkeypatch, selected_query):
    from hashlib import sha256
    import json
    from app.netto_booklets import build_netto_booklet
    db, client, _ = data
    base = "https://www.netto-online.de/filialen/dortmund/rauschenbuschstr-1/5659"
    snapshot, manifest = booklet_source(
        db, tmp_path, monkeypatch, store_url=base + selected_query,
        prospect_url="https://wochenprospekt.netto-online.de/hz39_hasb_4/?storeid=5659",
    )
    # Collector persists the requested URL separately from the redirected URL.
    snapshot.source_url = base
    publication = tmp_path / "publication.json"
    publication.write_text(json.dumps({"config": {}, "sizes": {}, "translations": {}, "spreads": [
        {"pages": [f"/100989/3378805/pages/test-page-{i}"]} for i in range(71)
    ]}))
    manifest["publication_sha256"] = sha256(publication.read_bytes()).hexdigest()
    path = tmp_path / "manifest.json"
    path.write_text(json.dumps(manifest))
    snapshot.sha256 = sha256(path.read_bytes()).hexdigest()
    db.commit()
    context = build_netto_booklet(db, DAY, 71)
    assert context["state"] == "ready" and context["page_count"] == 71
    assert context["image_url"].endswith("/test-page-70-at1600.jpg")
    response = client.get("/ui/home/?view=booklets&date=2026-10-01&page=71")
    assert response.status_code == 200
    assert "https://wochenprospekt.netto-online.de/hz39_hasb_4/?storeid=5659" in response.text


@pytest.mark.parametrize("resolved", [
    "https://www.netto-online.de/filialen/dortmund/rauschenbuschstr-1/5659?stores_id=9999",
    "https://www.netto-online.de/filialen/dortmund/rauschenbuschstr-1/5659?stores_id=5659&stores_id=5659",
    "https://www.netto-online.de/filialen/dortmund/rauschenbuschstr-1/5659?stores_id=",
    "https://www.netto-online.de/filialen/dortmund/rauschenbuschstr-1/5659?other=1",
    "https://www.netto-online.de/filialen/dortmund/other/5659?stores_id=5659",
    "https://www.netto-online.de/filialen/dortmund/rauschenbuschstr-1/9999",
    "http://www.netto-online.de/filialen/dortmund/rauschenbuschstr-1/5659",
    "https://attacker.invalid/filialen/dortmund/rauschenbuschstr-1/5659",
    "https://www.netto-online.de/filialen/dortmund/rauschenbuschstr-1/5659#fragment",
])
def test_booklet_store_redirect_rejects_identity_changes(data, tmp_path, monkeypatch, resolved):
    from app.netto_booklets import build_netto_booklet
    db, _, _ = data
    snapshot, _ = booklet_source(db, tmp_path, monkeypatch, store_url=resolved)
    snapshot.source_url = "https://www.netto-online.de/filialen/dortmund/rauschenbuschstr-1/5659"
    db.commit()
    assert build_netto_booklet(db, DAY)["state"] == "unavailable"


@pytest.mark.parametrize("viewer", [
    "https://wochenprospekt.netto-online.de.evil.invalid/hz39_hasb_4/?storeid=5659",
    "https://wochenprospekt.netto-online.de/hz39_hasb_4/?storeid=9999",
    "https://wochenprospekt.netto-online.de/hz39_hasb_4/?storeid=5659&storeid=9999",
    "https://wochenprospekt.netto-online.de/hz39_hasb_4/?stores_id=9999",
    "https://wochenprospekt.netto-online.de/hz39_hasb_4/?storeid=",
    "http://wochenprospekt.netto-online.de/hz39_hasb_4/?storeid=5659",
])
def test_booklet_official_viewer_keeps_host_and_store_checks(data, tmp_path, monkeypatch, viewer):
    from app.netto_booklets import build_netto_booklet
    db, _, _ = data
    booklet_source(db, tmp_path, monkeypatch, prospect_url=viewer)
    assert build_netto_booklet(db, DAY)["state"] == "unavailable"


def test_booklet_archive_link_changes_date_without_fabricating_current_pages(data, tmp_path, monkeypatch):
    from app.netto_booklets import build_netto_booklet
    db, client, _ = data
    snapshot, _ = booklet_source(db, tmp_path, monkeypatch)
    booklet_offer(db, snapshot)
    context = build_netto_booklet(db, date(2026, 10, 27))
    assert context["state"] == "empty" and context["offers"] == []
    assert "image_url" not in context
    assert context["latest_label"] == "28.09.2026–04.10.2026"
    assert context["latest_href"] == "/ui/home/?view=booklets&date=2026-10-01&page=1"
    response = client.get("/ui/home/?view=booklets&date=2026-10-27")
    assert "Pēdējais pieejamais buklets:" in response.text
    assert "Sintētisks testa piens" not in response.text
    archive = client.get(context["latest_href"])
    assert archive.status_code == 200 and "Sintētisks testa piens" in archive.text


def test_booklet_future_or_late_observation_never_becomes_archive_link(data, tmp_path, monkeypatch):
    from app.netto_booklets import build_netto_booklet
    db, _, _ = data
    snapshot, _ = booklet_source(db, tmp_path, monkeypatch, valid_from="2026-10-02")
    assert "latest_href" not in build_netto_booklet(db, DAY)
    snapshot.collected_at = datetime(2026, 10, 5, 8, tzinfo=timezone.utc)
    db.commit()
    assert "latest_href" not in build_netto_booklet(db, date(2026, 10, 27))


def test_booklet_production_observed_september_manifest_is_not_october_failure(data, tmp_path, monkeypatch):
    from app.netto_booklets import build_netto_booklet
    db, _, _ = data
    base = "https://www.netto-online.de/filialen/dortmund/rauschenbuschstr-1/5659"
    snapshot, _ = booklet_source(
        db, tmp_path, monkeypatch, store_url=base + "?stores_id=5659",
        prospect_url="https://wochenprospekt.netto-online.de/hz39_hasb_4/?storeid=5659",
        valid_from="2026-09-24", valid_until="2026-09-26",
    )
    snapshot.source_url = base
    snapshot.collected_at = datetime(2026, 9, 26, 7, 15, 59, tzinfo=timezone.utc)
    db.commit()
    october = build_netto_booklet(db, date(2026, 10, 27))
    assert october["state"] == "empty"
    assert october["latest_label"] == "24.09.2026–26.09.2026"
    assert october["latest_href"] == "/ui/home/?view=booklets&date=2026-09-26&page=1"
    assert build_netto_booklet(db, date(2026, 9, 26))["state"] == "ready"


@pytest.mark.parametrize("selected_day,valid_from", [
    (DAY, "2026-10-02"), (date(2026, 10, 27), "2026-09-28"),
])
def test_booklet_nonselected_missing_publication_does_not_break_date_view(
        data, tmp_path, monkeypatch, selected_day, valid_from):
    from app.netto_booklets import build_netto_booklet
    db, _, _ = data
    booklet_source(db, tmp_path, monkeypatch, valid_from=valid_from,
                   publication_path=str(tmp_path / "missing.json"))
    result = build_netto_booklet(db, selected_day)
    assert result["state"] == "empty"
    assert "latest_href" not in result


# HTML teaser-only fallback — official link without invented publication pages.
def html_booklet_source(db, tmp_path, monkeypatch, *,
                        start="ab Donnerstag, 01.10.26", slug="hz40_hasb",
                        collected=datetime(2026, 9, 30, 8, tzinfo=timezone.utc),
                        with_field=True):
    from hashlib import sha256
    from types import SimpleNamespace
    import json
    import app.netto_booklets as booklets
    monkeypatch.setattr(booklets, "get_settings", lambda: SimpleNamespace(raw_snapshot_dir=tmp_path))
    store_url = "https://www.netto-online.de/filialen/dortmund/rauschenbuschstr-1/5659"
    raw = (
        f'<div class="prospekt-teaser-item"><a href="https://wochenprospekt.netto-online.de/{slug}/?storeid=5659">Prospekt</a>'
        f'<div class="prospekt-teaser-item-container">Filial-Angebote {start} Zum Prospekt</div></div>'
    ).encode()
    store = tmp_path / "netto-html"
    store.mkdir(exist_ok=True)
    path = store / f"{sha256(raw).hexdigest()}.html"
    path.write_bytes(raw)
    snap = SourceSnapshot(
        source_chain="netto", scope="family_primary_netto",
        source_url=store_url, strategy_hint="netto_store_html_v1",
        collected_at=collected, success=True,
    )
    db.add(snap)
    db.flush()
    manifest = {
        "strategy": "netto_store_html_v1", "snapshot_id": str(snap.id),
        "source_url": store_url, "store_external_id": "5659",
        "scope": "family_primary_netto",
        "pages": [{
            "role": "store", "url": store_url + "?stores_id=5659",
            "final_url": store_url + "?stores_id=5659",
            "path": str(path), "sha256": sha256(raw).hexdigest(),
        }],
    }
    if with_field:
        from app.netto_booklet_teasers import extract_netto_booklet_teaser_starts
        starts = extract_netto_booklet_teaser_starts(raw.decode())
        manifest["booklet_teaser_evidence"] = {
            "state": "observed",
            "starts": {slug: day.isoformat() for slug, day in starts.items()},
        }
    manifest_path = store / f"{snap.id}.json"
    manifest_path.write_text(json.dumps(manifest))
    snap.snapshot_path = str(manifest_path)
    snap.sha256 = sha256(manifest_path.read_bytes()).hexdigest()
    db.commit()
    return snap, manifest, path


def attach_html_publication(snapshot, manifest, tmp_path, *,
                            start="01.10.26", end="03.10.26",
                            group="netto", paths=None, sizes=None):
    from hashlib import sha256
    import json
    root = tmp_path / "netto-html"
    viewer = (
        '<meta name="description" content="Donnerstag, '+start+
        ' - Samstag, '+end+'"><script>{"groupSlug":"'+group+
        '"}</script>'
    ).encode()
    viewer_path = root / f"{sha256(viewer).hexdigest()}.html"
    viewer_path.write_bytes(viewer)
    publication_data = {"spreads": [
        {"pages": paths if paths is not None else ["/hz40/page-1", "/hz40/page-2"]}
    ]}
    if sizes is not None:
        publication_data["sizes"] = sizes
    publication = json.dumps(publication_data).encode()
    publication_path = root / f"{sha256(publication).hexdigest()}.json"
    publication_path.write_bytes(publication)
    manifest["booklet_publications"] = [{
        "slug": "hz40_hasb", "valid_from": "2026-10-01",
        "valid_until": "2026-10-03",
        "validity_text": "01.10.26 - Samstag, 03.10.26",
        "prospect_url": "https://wochenprospekt.netto-online.de/hz40_hasb/?storeid=5659",
        "prospect_path": str(viewer_path),
        "prospect_sha256": sha256(viewer).hexdigest(),
        "publication_api_url":
            "https://api.publitas.com/v1/groups/netto/publications/hz40_hasb.json",
        "publication_path": str(publication_path),
        "publication_sha256": sha256(publication).hexdigest(),
    }]
    manifest_path = root / f"{snapshot.id}.json"
    manifest_path.write_text(json.dumps(manifest))
    snapshot.sha256 = sha256(manifest_path.read_bytes()).hexdigest()
    return viewer_path, publication_path


def test_netto_html_verified_publication_pages_without_pdf(data, tmp_path, monkeypatch):
    from app.netto_booklets import build_netto_booklet
    db, client, _ = data
    snap, manifest, _ = html_booklet_source(db, tmp_path, monkeypatch)
    attach_html_publication(snap, manifest, tmp_path)
    db.commit()
    for d in [DAY, date(2026, 10, 2), date(2026, 10, 3)]:
        selected = build_netto_booklet(db, d, 2)
        assert selected["state"] == "ready"
        assert selected["offers"] == []
        assert selected["page_count"] == 2
        assert selected["valid_label"] == "01.10.2026–03.10.2026"
        assert selected["image_url"] == "https://view.publitas.com/hz40/page-2-at1600.jpg"
        assert selected["swipeable"] is True
        assert [p["image_url"] for p in selected["pages"]] == [
            "https://view.publitas.com/hz40/page-1-at1600.jpg",
            "https://view.publitas.com/hz40/page-2-at1600.jpg",
        ]
    page = client.get("/ui/home/?view=booklets&date=2026-10-02&page=2")
    assert page.status_code == 200
    assert "booklet-page-image" in page.text
    assert "hz40/page-2-at1600.jpg" in page.text
    assert 'data-booklet-swipe="2"' in page.text
    assert 'class="booklet-slide"' not in page.text
    assert page.text.count('class="booklet-page-image"') == 1
    assert 'data-booklet-image' in page.text
    assert 'data-booklet-fullscreen' not in page.text
    assert 'Pieskaries vākam' not in page.text
    assert 'Ja attēls neielādējas' not in page.text
    assert 'data-booklet-viewer-close' in page.text
    assert 'data-booklet-viewer-prev' in page.text
    assert 'data-booklet-viewer-next' in page.text
    assert 'data-booklet-zoom-in' in page.text
    assert 'data-booklet-zoom-out' in page.text
    assert 'draggable="false"' in page.text
    assert 'data-booklet-image-url="https://view.publitas.com/hz40/page-1-at1600.jpg"' in page.text
    assert 'data-booklet-next' in page.text
    assert not list(tmp_path.rglob("*.pdf"))
    assert build_netto_booklet(db, date(2026, 10, 4))["state"] == "empty"


@pytest.mark.parametrize(
    ("sizes", "expected"),
    [
        ({"at2400": {"width": 2100, "height": 3000},
          "at2000": {"width": 1750, "height": 2500}},
         "https://view.publitas.com/hz40/page-2-at2400.jpg"),
        ({"at2000": {"width": 1750, "height": 2500}},
         "https://view.publitas.com/hz40/page-2-at2000.jpg"),
        ({"at2400": {"width": "invalid", "height": 3000}}, None),
        ({}, None),
    ],
)
def test_netto_zoom_only_uses_verified_declared_image_size(
        data, tmp_path, monkeypatch, sizes, expected):
    from app.netto_booklets import build_netto_booklet
    db, client, _ = data
    snap, manifest, _ = html_booklet_source(db, tmp_path, monkeypatch)
    attach_html_publication(snap, manifest, tmp_path, sizes=sizes)
    db.commit()
    selected = build_netto_booklet(db, date(2026, 10, 2), 2)
    assert selected["state"] == "ready"
    assert selected["pages"][1]["zoom_image_url"] == expected
    assert selected["pages"][1]["image_url"].endswith("/hz40/page-2-at1600.jpg")
    page = client.get("/ui/home/?view=booklets&date=2026-10-02&page=2")
    assert page.status_code == 200
    if expected:
        assert f'data-booklet-zoom-image-url="{expected}"' in page.text
    else:
        assert 'data-booklet-zoom-image-url' not in page.text


@pytest.mark.parametrize("tamper", [
    "wrong_end", "wrong_group", "wrong_pages", "wrong_sha",
])
def test_netto_html_publication_requires_verified_source(data, tmp_path, monkeypatch, tamper):
    from app.netto_booklets import build_netto_booklet
    db, _, _ = data
    snap, manifest, _ = html_booklet_source(db, tmp_path, monkeypatch)
    viewer_path, pub_path = attach_html_publication(snap, manifest, tmp_path)
    db.commit()
    if tamper == "wrong_end":
        manifest["booklet_publications"][0]["valid_until"] = "2026-10-04"
    elif tamper == "wrong_group":
        manifest["booklet_publications"][0]["publication_api_url"] = (
            "https://api.publitas.com/v1/groups/wrong/publications/hz40_hasb.json"
        )
    elif tamper == "wrong_pages":
        manifest["booklet_publications"][0]["publication_path"] = str(viewer_path)
        manifest["booklet_publications"][0]["publication_sha256"] = (
            manifest["booklet_publications"][0]["prospect_sha256"]
        )
    else:
        pub_path.write_bytes(b'{"spreads":[]}')
    if tamper != "wrong_sha":
        import json
        from hashlib import sha256
        path = tmp_path / "netto-html" / f"{snap.id}.json"
        path.write_text(json.dumps(manifest))
        snap.sha256 = sha256(path.read_bytes()).hexdigest()
        db.commit()
    assert build_netto_booklet(db, DAY)["state"] == "unavailable"


@pytest.mark.parametrize("with_field", [True, False])
def test_booklet_uses_verified_official_link_on_start_day_only(data, tmp_path, monkeypatch, with_field):
    from app.netto_booklets import build_netto_booklet
    db, client, _ = data
    html_booklet_source(db, tmp_path, monkeypatch, with_field=with_field)
    preview = build_netto_booklet(db, DAY)
    assert preview["state"] == "external_link"
    assert preview["offers"] == []
    assert preview["source_url"] == "https://wochenprospekt.netto-online.de/hz40_hasb/?storeid=5659"
    assert "image_url" not in preview and "page_count" not in preview
    response = client.get("/ui/home/?view=booklets&date=2026-10-01")
    assert response.status_code == 200
    assert 'data-booklet-state="external_link"' in response.text
    assert "Pilns derīguma periods nav apstiprināts" in response.text
    assert 'target="_blank"' in response.text
    assert "hz40_hasb" in response.text
    assert "booklet-page-image" not in response.text
    for other in [date(2026, 9, 30), date(2026, 10, 2)]:
        result = build_netto_booklet(db, other)
        assert result["state"] == "empty"
        assert "source_url" not in result


def test_booklet_html_teaser_tampering_and_latest_corruption_fail_closed(data, tmp_path, monkeypatch):
    from hashlib import sha256
    import json
    from app.netto_booklets import build_netto_booklet
    db, _, _ = data
    first, manifest, store_path = html_booklet_source(db, tmp_path, monkeypatch)
    store_path.write_bytes(b"changed")
    assert build_netto_booklet(db, DAY)["state"] == "unavailable"
    store_path.write_bytes(
        ('<div class="prospekt-teaser-item"><a href="https://wochenprospekt.netto-online.de/hz40_hasb/?storeid=5659">Prospekt</a>'
         '<div class="prospekt-teaser-item-container">Filial-Angebote ab Donnerstag, 01.10.26 Zum Prospekt</div></div>').encode()
    )
    manifest["booklet_teaser_evidence"]["starts"]["hz40_hasb"] = "2026-10-08"
    manifest_path = tmp_path / "netto-html" / f"{first.id}.json"
    manifest_path.write_text(json.dumps(manifest))
    first.sha256 = sha256(manifest_path.read_bytes()).hexdigest()
    db.commit()
    assert build_netto_booklet(db, DAY)["state"] == "unavailable"


def test_booklet_html_invalid_store_and_late_observation_not_shown(data, tmp_path, monkeypatch):
    import json
    from hashlib import sha256
    from app.netto_booklets import build_netto_booklet
    db, _, _ = data
    snap, manifest, _ = html_booklet_source(db, tmp_path, monkeypatch)
    manifest["pages"][0]["final_url"] = (
        "https://www.netto-online.de/filialen/dortmund/rauschenbuschstr-1/5659?stores_id=6071"
    )
    p = tmp_path / "netto-html" / f"{snap.id}.json"
    p.write_text(json.dumps(manifest))
    snap.sha256 = sha256(p.read_bytes()).hexdigest()
    db.commit()
    assert build_netto_booklet(db, DAY)["state"] == "unavailable"
    snap.collected_at = datetime(2026, 10, 2, 8, tzinfo=timezone.utc)
    db.commit()
    assert build_netto_booklet(db, DAY)["state"] == "empty"


def test_booklet_verified_publication_still_wins_over_html_teaser(data, tmp_path, monkeypatch):
    from app.netto_booklets import build_netto_booklet
    db, _, _ = data
    html_booklet_source(db, tmp_path, monkeypatch)
    booklet_source(db, tmp_path, monkeypatch)
    ready = build_netto_booklet(db, DAY)
    assert ready["state"] == "ready"
    assert ready["page_count"] == 2




def test_booklet_selector_preserves_netto_and_never_fabricates_other_pages(data, monkeypatch):
    _, client, _ = data
    base = "/ui/home/?view=booklets&date=2026-10-01"
    original = client.get(base)
    assert original.status_code == 200
    assert 'data-booklet-state="empty"' in original.text
    assert '<option value="netto" selected' in original.text
    assert "Netto piedāvājumi" in original.text

    # Unverified publishers must not be rendered from Netto records, even when
    # the visitor explicitly selects a known other retailer.
    import app.north_star_live_data as live_data
    def forbidden_netto(*args, **kwargs):
        raise AssertionError("Netto reader must not run for another retailer")
    monkeypatch.setattr(live_data, "build_netto_booklet", forbidden_netto)
    for retailer, name in live_data.BOOKLET_RETAILERS:
        if retailer == "netto":
            continue
        response = client.get(base + "&retailer=" + retailer)
        assert response.status_code == 200, response.text
        assert 'data-booklet-state="unavailable"' in response.text
        if retailer == "lidl":
            assert "nav saglabātu, publicētu un pārbaudītu Lidl" in response.text
        elif retailer == "aldi_nord":
            assert "nav reģistrētas pārbaudītas ALDI Nord" in response.text
        else:
            assert "vēl nav pieslēgtas pārbaudītam avotam" in response.text
        assert '<option value="' + retailer + '" selected' in response.text
        assert name + " piedāvājumi" in response.text
        assert "Netto piedāvājumi" not in response.text
        assert 'class="booklet-page-image"' not in response.text
        assert "Atvērt veikala bukletu" not in response.text
        assert "view=booklets&amp;date=2026-10-02&amp;retailer=" + retailer in response.text
        assert "page=1&amp;retailer=" not in response.text

    assert client.get(base + "&retailer=unknown").status_code == 422
    assert client.get(base + "&retailer=lidl%3Fpage%3D2").status_code == 422


def test_booklet_selection_keeps_day_navigation_and_resets_page(data):
    _, client, _ = data
    response = client.get("/ui/home/?view=booklets&date=2026-10-01&retailer=lidl&page=2")
    assert response.status_code == 200
    # A new day is a new publication lookup; keep the selected store, not page.
    assert "view=booklets&amp;date=2026-10-02&amp;retailer=lidl" in response.text
    assert "view=booklets&amp;date=2026-10-02&amp;page=2" not in response.text
    assert 'name="retailer"' in response.text


def test_aldi_official_links_are_not_fake_embedded_pages(data, monkeypatch):
    from datetime import date
    from app.aldi_booklets import build_aldi_nord_booklet
    import app.north_star_live_data as live_data

    _, client, _ = data
    monkeypatch.setattr(
        live_data, "build_aldi_nord_booklet",
        lambda day: build_aldi_nord_booklet(day, today=date(2026, 10, 31)),
    )
    for day in ("2026-10-29", "2026-11-02"):
        response = client.get("/ui/home/?view=booklets&retailer=aldi_nord&date=" + day)
        assert response.status_code == 200
        assert 'data-booklet-state="external_link"' in response.text
        assert 'href="https://www.aldi-nord.de/prospekte.html"' in response.text
        assert "Atvērt ALDI Nord bukletu katalogu" in response.text
        assert "Atlasītā datuma buklets un lapas nav neatkarīgi apstiprinātas" in response.text
        assert 'class="booklet-page-image"' not in response.text
        assert "Netto piedāvājumi" not in response.text

    old = client.get("/ui/home/?view=booklets&retailer=aldi_nord&date=2026-10-10")
    assert 'data-booklet-state="unavailable"' in old.text
    assert 'href="https://www.aldi-nord.de/prospekte.html"' not in old.text
