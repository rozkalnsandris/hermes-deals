from __future__ import annotations

from decimal import Decimal
import unittest
import uuid

from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session, sessionmaker
from sqlalchemy.pool import StaticPool

from app.db import get_db
from app.main import app
from app.models import Base, CanonicalProduct


class CanonicalProductReadApiTest(unittest.TestCase):
    def setUp(self) -> None:
        self.engine = create_engine(
            "sqlite+pysqlite:///:memory:",
            connect_args={"check_same_thread": False},
            poolclass=StaticPool,
            future=True,
        )
        Base.metadata.create_all(self.engine)
        self.Session = sessionmaker(
            bind=self.engine,
            class_=Session,
            expire_on_commit=False,
        )

        def override_get_db():
            db = self.Session()
            try:
                yield db
            finally:
                db.close()

        app.dependency_overrides[get_db] = override_get_db
        self.client = TestClient(app)

    def tearDown(self) -> None:
        self.client.close()
        app.dependency_overrides.clear()
        self.engine.dispose()

    def _seed(self) -> tuple[uuid.UUID, uuid.UUID]:
        with self.Session.begin() as db:
            almette = CanonicalProduct(
                id=uuid.uuid4(),
                display_name="Almette Alpenfrischkäse",
                normalized_name="alpenfrischkäse",
                brand_display="Almette",
                brand_normalized="almette",
                item_quantity_value=Decimal("150"),
                item_quantity_unit="g",
                pack_count=1,
                gtin14=None,
                category_key=None,
            )
            oatly = CanonicalProduct(
                id=uuid.uuid4(),
                display_name="Oatly Haferdrink",
                normalized_name="haferdrink",
                brand_display="Oatly",
                brand_normalized="oatly",
                item_quantity_value=Decimal("1000"),
                item_quantity_unit="ml",
                pack_count=1,
                gtin14=None,
                category_key=None,
            )
            db.add_all([oatly, almette])
            db.flush()
            return almette.id, oatly.id

    def test_list_returns_canonical_products_in_stable_order(self) -> None:
        almette_id, oatly_id = self._seed()

        response = self.client.get("/api/v1/canonical-products")
        self.assertEqual(response.status_code, 200)

        body = response.json()
        self.assertEqual(len(body), 2)
        self.assertEqual(
            [row["display_name"] for row in body],
            ["Almette Alpenfrischkäse", "Oatly Haferdrink"],
        )
        self.assertEqual(body[0]["id"], str(almette_id))
        self.assertEqual(body[1]["id"], str(oatly_id))

    def test_detail_returns_exact_canonical_product(self) -> None:
        almette_id, _ = self._seed()

        response = self.client.get(
            f"/api/v1/canonical-products/{almette_id}"
        )
        self.assertEqual(response.status_code, 200)

        body = response.json()
        self.assertEqual(body["id"], str(almette_id))
        self.assertEqual(body["display_name"], "Almette Alpenfrischkäse")
        self.assertEqual(body["brand_normalized"], "almette")
        self.assertEqual(body["item_quantity_value"], "150.0000")
        self.assertEqual(body["item_quantity_unit"], "g")
        self.assertEqual(body["pack_count"], 1)

    def test_detail_missing_product_returns_404(self) -> None:
        response = self.client.get(
            f"/api/v1/canonical-products/{uuid.uuid4()}"
        )
        self.assertEqual(response.status_code, 404)

    def test_list_limit_is_enforced(self) -> None:
        self._seed()

        response = self.client.get("/api/v1/canonical-products?limit=1")
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.json()), 1)


if __name__ == "__main__":
    unittest.main()
