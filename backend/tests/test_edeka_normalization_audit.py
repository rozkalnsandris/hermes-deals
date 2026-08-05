from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from types import SimpleNamespace
import tempfile
import unittest
from unittest.mock import patch
from uuid import UUID, uuid4

from app.edeka_normalization_audit import (
    audit_edeka_manifest,
    build_edeka_normalization_report,
    write_deterministic_report,
)
from app.edeka_store_offers import EdekaFetchedPage, _write_manifest
from app.parsers.edeka import EdekaParserContext, parse_edeka_html
from app.schemas import OfferCandidate, SourceChain
from app.source_config import SourceConfig


FIXTURE = Path(__file__).parent / "fixtures" / "edeka_offers.html"
SOURCE_URL = "https://www.edeka.de/maerkte/071897/angebote/"
COLLECTED_AT = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)
SNAPSHOT_ID = UUID("11111111-2222-4333-8444-555555555555")
MANIFEST_SHA = "a" * 64


def _source() -> SourceConfig:
    return SourceConfig(
        chain="edeka",
        enabled=True,
        priority=2,
        url=SOURCE_URL,
        scope="family_primary_edeka",
        notes="",
        keywords=("Angebote",),
        store_external_id="071897",
        store_internal_id="587881",
        store_name="EDEKA Patzer",
    )


def _context(snapshot_id=SNAPSHOT_ID) -> EdekaParserContext:
    return EdekaParserContext(
        snapshot_id=snapshot_id,
        source_url=SOURCE_URL,
        collected_at=COLLECTED_AT,
        public_market_id="071897",
        internal_market_id="587881",
        store_name="EDEKA Patzer",
    )


def _offer(
    source_offer_id: str,
    *,
    product_name: str,
    package_text: str | None = None,
    image_url: str | None = None,
    description: str | None = None,
) -> OfferCandidate:
    return OfferCandidate(
        source_chain=SourceChain.EDEKA,
        source_store_external_id="071897",
        source_store_name="EDEKA Patzer",
        source_offer_id=source_offer_id,
        product_name_raw=product_name,
        brand_raw=None,
        description_raw=description,
        package_text_raw=package_text,
        price_eur=Decimal("1.99"),
        valid_from=date(2026, 8, 3),
        valid_until=date(2026, 8, 8),
        source_url=SOURCE_URL,
        source_image_url=image_url,
        snapshot_id=SNAPSHOT_ID,
        collected_at=COLLECTED_AT,
        parser_version="edeka-v1",
        raw_payload={"description": description} if description else {},
    )


def _current_html() -> bytes:
    return (
        FIXTURE.read_text(encoding="utf-8")
        .replace("20.07.2026", "03.08.2026")
        .replace("25.07.2026", "08.08.2026")
        .encode("utf-8")
    )


class EdekaNormalizationReportTest(unittest.TestCase):
    def test_report_counts_resolved_and_review_rows(self) -> None:
        offers = [
            _offer(
                "offer-image",
                product_name="Image package",
                image_url=(
                    "https://offer-images.api.edeka/"
                    "example_product_500g_card.png"
                ),
            ),
            _offer(
                "offer-description",
                product_name="Description package",
                description="600 g Packung",
            ),
            _offer(
                "offer-review",
                product_name="Unresolved package",
                description="verschiedene Sorten",
            ),
        ]

        report = build_edeka_normalization_report(
            offers,
            manifest_sha256=MANIFEST_SHA,
        )

        self.assertEqual(report["summary"]["offer_count"], 3)
        self.assertEqual(report["summary"]["resolved_count"], 2)
        self.assertEqual(report["summary"]["review_required_count"], 1)
        self.assertEqual(report["summary"]["resolved_percent"], "66.67")
        self.assertEqual(
            [row["source_offer_id"] for row in report["rows"]],
            ["offer-description", "offer-image", "offer-review"],
        )
        review = report["rows"][2]
        self.assertEqual(review["status"], "review_required")
        self.assertEqual(
            review["review_reasons"],
            ["description_unresolved"],
        )
        self.assertEqual(len(report["summary"]["rows_sha256"]), 64)
        self.assertEqual(len(report["report_sha256"]), 64)

    def test_report_is_stable_across_input_order(self) -> None:
        offers = [
            _offer(
                "b",
                product_name="Second",
                description="500 g",
            ),
            _offer(
                "a",
                product_name="First",
                description="ohne Mengenangabe",
            ),
        ]

        first = build_edeka_normalization_report(
            offers,
            manifest_sha256=MANIFEST_SHA,
        )
        second = build_edeka_normalization_report(
            list(reversed(offers)),
            manifest_sha256=MANIFEST_SHA,
        )

        self.assertEqual(first, second)
        self.assertEqual(
            first["report_sha256"],
            second["report_sha256"],
        )

    def test_wrong_market_and_duplicate_ids_fail_closed(self) -> None:
        wrong_market = _offer(
            "wrong-market",
            product_name="Wrong market",
            description="500 g",
        ).model_copy(update={"source_store_external_id": "999999"})
        with self.assertRaisesRegex(ValueError, "public market mismatch"):
            build_edeka_normalization_report(
                [wrong_market],
                manifest_sha256=MANIFEST_SHA,
            )

        duplicate = _offer(
            "duplicate",
            product_name="Duplicate",
            description="500 g",
        )
        with self.assertRaisesRegex(ValueError, "duplicate"):
            build_edeka_normalization_report(
                [duplicate, duplicate.model_copy()],
                manifest_sha256=MANIFEST_SHA,
            )


class EdekaNormalizationManifestAuditTest(unittest.TestCase):
    def test_manifest_round_trip_produces_bound_report(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            settings = SimpleNamespace(raw_snapshot_dir=Path(temporary))
            fetched = EdekaFetchedPage(
                final_url=SOURCE_URL,
                content=_current_html(),
                content_type="text/html; charset=utf-8",
                http_status=200,
                elapsed_ms=1,
            )
            offers = parse_edeka_html(fetched.content, _context())
            with patch(
                "app.edeka_store_offers.get_settings",
                return_value=settings,
            ):
                manifest_path, manifest_sha = _write_manifest(
                    source=_source(),
                    snapshot_id=SNAPSHOT_ID,
                    collected_at=COLLECTED_AT,
                    fetched=fetched,
                    offers=offers,
                )

            report = audit_edeka_manifest(manifest_path, manifest_sha)

        self.assertEqual(report["manifest_sha256"], manifest_sha)
        self.assertEqual(report["source"]["snapshot_id"], str(SNAPSHOT_ID))
        self.assertEqual(report["source"]["public_market_id"], "071897")
        self.assertEqual(report["summary"]["offer_count"], len(offers))
        self.assertEqual(
            report["summary"]["offer_count"],
            report["summary"]["resolved_count"]
            + report["summary"]["review_required_count"],
        )

    def test_tampered_manifest_sha_is_rejected_before_parse(self) -> None:
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "manifest.json"
            path.write_text("{}", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "SHA mismatch"):
                audit_edeka_manifest(path, "0" * 64)

    def test_report_writer_is_idempotent_and_immutable(self) -> None:
        report = build_edeka_normalization_report(
            [
                _offer(
                    "offer",
                    product_name="Product",
                    description="500 g",
                )
            ],
            manifest_sha256=MANIFEST_SHA,
        )
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "report.json"
            write_deterministic_report(path, report)
            original = path.read_bytes()
            write_deterministic_report(path, report)
            self.assertEqual(path.read_bytes(), original)

            changed = dict(report)
            changed["report_sha256"] = "0" * 64
            with self.assertRaisesRegex(ValueError, "different"):
                write_deterministic_report(path, changed)

    def test_audit_module_has_no_database_write_dependencies(self) -> None:
        root = Path(__file__).resolve().parents[1]
        source = (
            root / "app" / "edeka_normalization_audit.py"
        ).read_text(encoding="utf-8")

        self.assertNotIn("SessionLocal", source)
        self.assertNotIn("save_offer_candidates", source)
        self.assertNotIn("sqlalchemy", source)
        self.assertNotIn("db.commit", source)


if __name__ == "__main__":
    unittest.main()
