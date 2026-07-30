from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from app.netto_store_prospect import (
    NettoStoreProspectBundle,
    _write_bundle,
    apply_prospect_validity,
    extract_pdf_prospect_validity,
    extract_prospect_validity,
)
from app.schemas import OfferCandidate, SourceChain
from app.source_config import SourceConfig


def candidate() -> OfferCandidate:
    return OfferCandidate(
        source_chain=SourceChain.NETTO,
        source_store_external_id="5659",
        source_store_name="Netto Marken-Discount — Dortmund, Rauschenbuschstr. 1",
        source_offer_id="x",
        product_name_raw="Test",
        price_eur=Decimal("1.00"),
        source_url="https://www.netto-online.de/filialen/test/5659",
        snapshot_id=uuid4(),
        collected_at=datetime(2026,7,25,8,0,tzinfo=timezone.utc),
        parser_version="netto-v1",
        raw_payload={"card_index":1},
    )


class NettoStoreProspectTest(unittest.TestCase):
    def test_meta_validity_two_digit_year(self):
        html=b'<meta name="description" content="Montag, 20.07.26 \xe2\x80\x93 Samstag, 25.07.26 Test">'
        self.assertEqual(
            extract_prospect_validity(html)[:2],
            (date(2026,7,20),date(2026,7,25)),
        )

    def test_meta_validity_four_digit_year(self):
        html=b'<meta name="description" content="Montag, 20.07.2026 - Samstag, 25.07.2026">'
        self.assertEqual(
            extract_prospect_validity(html)[:2],
            (date(2026,7,20),date(2026,7,25)),
        )

    def test_missing_validity_rejected(self):
        with self.assertRaises(ValueError):
            extract_prospect_validity(b"<html>No dates</html>")

    def test_conflicting_validity_rejected(self):
        html=(
            b'<meta name="description" content="20.07.26 - 25.07.26 '
            b'27.07.26 - 01.08.26">'
        )
        with self.assertRaises(ValueError):
            extract_prospect_validity(html)

    @patch("app.netto_store_prospect.PdfReader")
    def test_pdf_validity_uses_first_three_pages(self, reader):
        pages = []
        for text in (
            "gültig von Donnerstag, 30.07.26 – Samstag, 01.08.26",
            "30.07.26 - 01.08.26",
            "30.07.26 - 01.08.26",
            "Montag, 27.07.26 - Samstag, 01.08.26",
        ):
            page = Mock()
            page.extract_text.return_value = text
            pages.append(page)
        reader.return_value.pages = pages

        self.assertEqual(
            extract_pdf_prospect_validity(b"%PDF-test")[:2],
            (date(2026,7,30),date(2026,8,1)),
        )
        pages[3].extract_text.assert_not_called()

    def test_pdf_provenance_is_written_into_v2_manifest(self):
        source = SourceConfig(
            chain="netto",
            enabled=True,
            priority=1,
            url="https://example.invalid/store/5659",
            scope="family_primary_netto",
            notes="fixture",
            keywords=(),
            store_external_id="5659",
            store_name="Netto fixture",
        )
        bundle = NettoStoreProspectBundle(
            store_url=source.url,
            prospect_url="https://example.invalid/hz31/",
            prospect_slug="hz31",
            store_html=b"<html>offers</html>",
            prospect_html=b"<html>viewer</html>",
            valid_from=date(2026,7,30),
            valid_until=date(2026,8,1),
            validity_text="30.07.26 - 01.08.26",
            selected_store_cookie_present=True,
            elapsed_ms=1,
            validity_source_url="https://example.invalid/publication.pdf",
            validity_source_type="prospect_pdf_text",
            publication_api_url="https://example.invalid/publication.json",
            publication_json=b'{"config":{}}',
            prospect_pdf_url="https://example.invalid/publication.pdf",
            prospect_pdf=b"%PDF-fixture",
        )
        with tempfile.TemporaryDirectory() as tmp, patch(
            "app.netto_store_prospect.get_settings",
            return_value=Mock(raw_snapshot_dir=Path(tmp)),
        ):
            path, digest = _write_bundle(
                bundle,
                source=source,
                collected_at=datetime(2026,7,30,8,0,tzinfo=timezone.utc),
            )
            manifest = json.loads(path.read_text(encoding="utf-8"))

        self.assertEqual(manifest["schema_version"], 2)
        self.assertEqual(
            manifest["strategy"],
            "netto_store_page_plus_current_prospect_pdf_v2",
        )
        self.assertEqual(
            manifest["validity_source_type"],
            "prospect_pdf_text",
        )
        self.assertTrue(manifest["publication_sha256"])
        self.assertTrue(manifest["prospect_pdf_sha256"])
        self.assertEqual(len(digest), 64)

    def test_apply_validity(self):
        bundle=NettoStoreProspectBundle(
            store_url="store",
            prospect_url="prospect",
            prospect_slug="hz30_hasb_4",
            store_html=b"x",
            prospect_html=b"y",
            valid_from=date(2026,7,20),
            valid_until=date(2026,7,25),
            validity_text="20.07.26 - 25.07.26",
            selected_store_cookie_present=True,
            elapsed_ms=1,
        )
        out=apply_prospect_validity([candidate()],bundle=bundle)[0]
        self.assertEqual(out.valid_from,date(2026,7,20))
        self.assertEqual(out.valid_until,date(2026,7,25))
        self.assertEqual(out.parser_version,"netto-v1.3-store-prospect")

    def test_apply_preserves_card_payload(self):
        bundle=NettoStoreProspectBundle(
            store_url="store",
            prospect_url="prospect",
            prospect_slug="hz30_hasb_4",
            store_html=b"x",
            prospect_html=b"y",
            valid_from=date(2026,7,20),
            valid_until=date(2026,7,25),
            validity_text="20.07.26 - 25.07.26",
            selected_store_cookie_present=True,
            elapsed_ms=1,
        )
        out=apply_prospect_validity([candidate()],bundle=bundle)[0]
        self.assertEqual(out.raw_payload["card_index"],1)
        self.assertEqual(out.raw_payload["campaign_prospect_slug"],"hz30_hasb_4")


if __name__=="__main__":
    unittest.main()
