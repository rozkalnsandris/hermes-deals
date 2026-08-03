from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import tempfile
from types import SimpleNamespace
from unittest.mock import patch
from uuid import UUID, uuid4
import unittest

from fastapi import HTTPException

from app.main import app
from app.netto_daily_special_api import (
    _assert_read_only_session,
    _discount_percent,
    _to_output,
    _cached_snapshot_offers,
    daily_specials,
)
from app.parsers.netto_daily_special import (
    NettoDailySpecialCandidate,
    NettoDailySpecialPage,
)
from app.schemas import OfferCandidate, SourceChain


class _FakeBind:
    class _Dialect:
        name = "sqlite"

    dialect = _Dialect()


class _FakeDb:
    def get_bind(self):
        return _FakeBind()


class _PostgresDb:
    class _Bind:
        class _Dialect:
            name = "postgresql"

        dialect = _Dialect()

    def get_bind(self):
        return self._Bind()

    def __init__(self, values: list[str] | None = None):
        self.values = list(values or ["on"])
        self.statements: list[str] = []

    def execute(self, statement):
        class _Result:
            def __init__(self, value):
                self.value = value

            def scalar_one(self):
                return self.value

        self.statements.append(str(statement))
        if "SHOW transaction_read_only" in str(statement):
            return _Result(self.values.pop(0))
        return _Result(None)


def _offer(valid_on: date = date(2026, 8, 1)) -> OfferCandidate:
    return OfferCandidate(
        source_chain=SourceChain.NETTO,
        source_store_external_id="5659",
        source_store_name=(
            "Netto Marken-Discount — Dortmund, Rauschenbuschstr. 1"
        ),
        source_offer_id="netto-daily-test",
        product_name_raw="Gutes Land Haltbare Weidemilch 3.5% Fett",
        brand_raw="Gutes Land",
        description_raw="Netto explicit one-day prospect offer",
        package_text_raw="12 x 1 Liter",
        price_eur=Decimal("9.00"),
        regular_price_eur=Decimal("11.40"),
        unit_price_eur=Decimal("0.75"),
        unit_label="l",
        pricing_mode="fixed_package",
        discount_percent=21,
        valid_from=valid_on,
        valid_until=valid_on,
        source_url="https://example.test/prospect",
        source_image_url="https://example.test/page-17.jpg",
        snapshot_id=UUID("4c482513-97b4-4b16-b976-d6e2c3e46d4d"),
        collected_at=datetime(2026, 8, 1, 7, 17, tzinfo=timezone.utc),
        parser_version="netto-daily-special-v3",
        raw_payload={
            "is_daily_special": True,
            "special_valid_on": valid_on.isoformat(),
            "special_type": "saturday_special",
            "special_source_text": (
                "SAMSTAGS | KRACHER | gültig am Samstag, | 01.08.26"
            ),
            "special_source_kind": "prospect_pdf_page",
            "special_source_page": 17,
            "special_confidence": "high",
            "bundle_quantity": 12,
            "single_price_eur": "0.95",
            "source_snapshot_sha256": "a" * 64,
            "shadow_only": True,
            "db_write_eligible": False,
        },
    )


class NettoDailySpecialApiTest(unittest.TestCase):
    def test_route_is_registered(self):
        schema = app.openapi()
        paths = schema.get("paths")
        self.assertIsInstance(paths, dict)
        endpoint = "/api/v1/deals/daily-specials"
        self.assertIn(endpoint, paths)
        operation = paths[endpoint].get("get")
        self.assertIsInstance(operation, dict)
        self.assertIn("200", operation.get("responses", {}))

    def test_discount_percent_is_rounded(self):
        self.assertEqual(
            _discount_percent(Decimal("9"), Decimal("11.40")),
            21,
        )

    def test_output_preserves_explicit_source_contract(self):
        row = _to_output(_offer(), date(2026, 8, 1))
        self.assertTrue(row.is_daily_special)
        self.assertEqual(row.special_valid_on, date(2026, 8, 1))
        self.assertEqual(row.special_source_page, 17)
        self.assertEqual(row.special_confidence, "high")
        self.assertTrue(row.shadow_only)

    def test_output_preserves_bundle_and_single_price(self):
        row = _to_output(_offer(), date(2026, 8, 1))
        self.assertEqual(row.bundle_quantity, 12)
        self.assertEqual(row.price_eur, Decimal("9.00"))
        self.assertEqual(row.single_price_eur, Decimal("0.95"))
        self.assertEqual(row.unit_price_eur, Decimal("0.75"))

    def test_shadow_offer_id_maps_to_stable_uuid(self):
        first = _to_output(_offer(), date(2026, 8, 1))
        second = _to_output(_offer(), date(2026, 8, 1))
        self.assertEqual(first.offer_candidate_id, second.offer_candidate_id)

    def test_route_returns_only_requested_explicit_date(self):
        snapshot = SimpleNamespace(
            id=uuid4(),
            snapshot_path="/tmp/manifest.json",
            sha256="b" * 64,
            source_url="https://example.test/store",
            final_url="https://example.test/prospect",
            collected_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        with (
            patch(
                "app.netto_daily_special_api._latest_snapshot",
                return_value=snapshot,
            ),
            patch(
                "app.netto_daily_special_api._cached_snapshot_offers",
                return_value=(
                    _offer(date(2026, 8, 1)),
                    _offer(date(2026, 8, 2)).model_copy(
                        update={"source_offer_id": "netto-daily-tomorrow"}
                    ),
                ),
            ),
        ):
            result = daily_specials(
                as_of=date(2026, 8, 1),
                db=_FakeDb(),
            )
        self.assertEqual(result.available_count, 1)
        self.assertEqual(result.deals[0].special_valid_on, date(2026, 8, 1))
        self.assertEqual(result.retailer_counts, {"netto": 1})

    def test_route_is_empty_when_no_explicit_evidence_matches(self):
        snapshot = SimpleNamespace(
            id=uuid4(),
            snapshot_path="/tmp/manifest.json",
            sha256="b" * 64,
            source_url="https://example.test/store",
            final_url="https://example.test/prospect",
            collected_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        with (
            patch(
                "app.netto_daily_special_api._latest_snapshot",
                return_value=snapshot,
            ),
            patch(
                "app.netto_daily_special_api._cached_snapshot_offers",
                return_value=(_offer(date(2026, 8, 1)),),
            ),
        ):
            result = daily_specials(
                as_of=date(2026, 8, 2),
                db=_FakeDb(),
            )
        self.assertEqual(result.count, 0)
        self.assertEqual(result.deals, [])

    def test_route_declares_fail_closed_source_contract(self):
        snapshot = SimpleNamespace(
            id=uuid4(),
            snapshot_path="/tmp/manifest.json",
            sha256="b" * 64,
            source_url="https://example.test/store",
            final_url="https://example.test/prospect",
            collected_at=datetime(2026, 8, 1, tzinfo=timezone.utc),
        )
        with (
            patch(
                "app.netto_daily_special_api._latest_snapshot",
                return_value=snapshot,
            ),
            patch(
                "app.netto_daily_special_api._cached_snapshot_offers",
                return_value=(),
            ),
        ):
            result = daily_specials(
                as_of=date(2026, 8, 1),
                db=_FakeDb(),
            )
        self.assertEqual(
            result.source_contract,
            "explicit_immutable_retailer_evidence_only",
        )

    def test_postgres_session_is_made_read_only(self):
        db = _PostgresDb(["on"])
        _assert_read_only_session(db)
        self.assertIn("SET TRANSACTION READ ONLY", db.statements)
        self.assertIn("SHOW transaction_read_only", db.statements)

    def test_postgres_unenforceable_session_is_rejected(self):
        db = _PostgresDb(["off"])
        with self.assertRaises(HTTPException) as raised:
            _assert_read_only_session(db)
        self.assertEqual(raised.exception.status_code, 503)

    def test_sqlite_test_session_is_allowed(self):
        _assert_read_only_session(_FakeDb())

    def test_cached_snapshot_maps_geometry_backed_offer(self) -> None:
        candidate = NettoDailySpecialCandidate(
            source_offer_id="netto-daily-geometry",
            product_name_raw="Brombeeren",
            package_text_raw="125 g Schale",
            price_eur=Decimal("1.49"),
            regular_price_eur=Decimal("1.99"),
            single_price_eur=None,
            unit_price_eur=None,
            bundle_quantity=None,
            valid_from=date(2026, 8, 4),
            valid_until=date(2026, 8, 4),
            is_daily_special=True,
            special_valid_on=date(2026, 8, 4),
            special_type="weekday_special",
            special_source_text="DIENSTAGS KRACHER | gültig am 04.08.26",
            special_source_kind="prospect_pdf_page",
            special_source_page=12,
            special_confidence="high",
            source_text_excerpt="Brombeeren | 1.49 | UVP 1.99",
            source_geometry=(
                {"role": "product", "bbox": [1, 2, 3, 4], "text": "Brombeeren"},
                {"role": "sale_price", "bbox": [5, 6, 7, 8], "text": "1.49"},
            ),
        )
        page = NettoDailySpecialPage(
            page_number=12,
            special_valid_on=date(2026, 8, 4),
            special_type="weekday_special",
            special_source_text=candidate.special_source_text,
            special_confidence="high",
            special_source_geometry=(
                {"role": "daily_banner_or_date", "bbox": [1, 2, 3, 4], "text": "04.08.26"},
            ),
        )
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            pdf_path = root / "prospect.pdf"
            pdf_path.write_bytes(b"%PDF-fixture")
            manifest = {
                "prospect_pdf_path": str(pdf_path),
                "prospect_pdf_sha256": sha256(pdf_path.read_bytes()).hexdigest(),
                "store_external_id": "5659",
                "scope": "family_primary_netto",
                "prospect_slug": "hz32_hasb",
                "publication_path": None,
                "publication_sha256": None,
            }
            manifest_path = root / "manifest.json"
            manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
            manifest_sha = sha256(manifest_path.read_bytes()).hexdigest()
            _cached_snapshot_offers.cache_clear()
            with patch(
                "app.netto_daily_special_api.extract_pdf_daily_special_candidates",
                return_value=[(page, [candidate], "c" * 64)],
            ):
                offers = _cached_snapshot_offers(
                    "4c482513-97b4-4b16-b976-d6e2c3e46d4d",
                    str(manifest_path),
                    manifest_sha,
                    "https://example.test/store",
                    "https://example.test/prospect",
                    "2026-08-03T07:12:01+00:00",
                )
            _cached_snapshot_offers.cache_clear()

        self.assertEqual(len(offers), 1)
        output = _to_output(offers[0], date(2026, 8, 4))
        self.assertEqual(output.product_name_raw, "Brombeeren")
        self.assertEqual(output.special_source_page, 12)
        self.assertEqual(output.source_snapshot_sha256, manifest_sha)
        self.assertEqual(offers[0].raw_payload["source_pdf_sha256"], manifest["prospect_pdf_sha256"])
        self.assertEqual(offers[0].raw_payload["campaign_prospect_slug"], "hz32_hasb")

        snapshot = SimpleNamespace(
            id=UUID("4c482513-97b4-4b16-b976-d6e2c3e46d4d"),
            snapshot_path=str(manifest_path),
            sha256=manifest_sha,
            source_url="https://example.test/store",
            final_url="https://example.test/prospect",
            collected_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
        )
        with (
            patch("app.netto_daily_special_api._latest_snapshot", return_value=snapshot),
            patch(
                "app.netto_daily_special_api._cached_snapshot_offers",
                return_value=offers,
            ),
        ):
            result = daily_specials(as_of=date(2026, 8, 4), db=_FakeDb())

        self.assertEqual(result.available_count, 1)
        self.assertEqual(result.deals[0].product_name_raw, "Brombeeren")
        self.assertEqual(result.deals[0].price_eur, Decimal("1.49"))


if __name__ == "__main__":
    unittest.main()
