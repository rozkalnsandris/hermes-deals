from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch
from types import SimpleNamespace
from uuid import uuid4

from app.netto_store_prospect import (
    NettoStoreProspectBundle,
    _write_bundle,
    apply_prospect_validity,
    extract_pdf_prospect_validity,
    extract_prospect_validity,
    fetch_netto_store_prospect,
    _validate_prospect_pdf,
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

    def test_non_pdf_download_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "not a PDF"):
            _validate_prospect_pdf(b"<html>not a prospect</html>")

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

    @patch("app.netto_store_prospect._validate_prospect_pdf")
    def test_pdf_provenance_is_written_into_v3_manifest(self, validate_pdf):
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

        self.assertEqual(manifest["schema_version"], 3)
        self.assertEqual(
            manifest["strategy"],
            "netto_store_page_plus_current_prospect_pdf_v3",
        )
        self.assertEqual(
            manifest["validity_source_type"],
            "prospect_pdf_text",
        )
        self.assertTrue(manifest["publication_sha256"])
        self.assertTrue(manifest["prospect_pdf_sha256"])
        self.assertEqual(len(digest), 64)
        validate_pdf.assert_called_once_with(b"%PDF-fixture")

    @patch("app.netto_store_prospect.extract_pdf_prospect_validity")
    @patch("app.netto_store_prospect._validate_prospect_pdf")
    @patch("app.netto_store_prospect.extract_netto_direct_viewers")
    @patch("app.netto_store_prospect.httpx.Client")
    def test_html_validity_still_captures_official_pdf(
        self,
        client_class,
        viewers,
        validate_pdf,
        pdf_validity,
    ):
        source = SourceConfig(
            chain="netto", enabled=True, priority=1,
            url="https://example.invalid/store/5659",
            scope="family_primary_netto", notes="fixture", keywords=(),
            store_external_id="5659", store_name="Netto fixture",
        )
        store = Mock(url=source.url, content=b"<html>store</html>")
        viewer = Mock(
            url="https://viewer.invalid/hz32/",
            content=(
                b'<meta name="description" content="Montag, 03.08.26 - '
                b'Samstag, 08.08.26"><script>{"groupSlug":"netto"}</script>'
            ),
            text='viewer {"groupSlug":"netto"}',
        )
        publication = Mock(
            url="https://api.publitas.invalid/hz32.json",
            content=b'{"config":{"downloadPdfUrl":"/hz32.pdf"}}',
        )
        publication.json.return_value = {
            "config": {"downloadPdfUrl": "/hz32.pdf"}
        }
        pdf = Mock(url="https://viewer.invalid/hz32.pdf", content=b"%PDF-fixture")
        client = client_class.return_value.__enter__.return_value
        client.cookies = SimpleNamespace(
            jar=[SimpleNamespace(name="netto_user_stores_id", value="5659")]
        )
        client.get.side_effect = [store, viewer, publication, pdf]
        viewers.return_value = {"hz32": "https://viewer.invalid/hz32/"}
        pdf_validity.return_value = (
            date(2026, 8, 3), date(2026, 8, 8), "03.08.26 - 08.08.26"
        )

        bundle = fetch_netto_store_prospect(source)

        self.assertEqual(bundle.validity_source_type, "prospect_html_meta")
        self.assertEqual(bundle.prospect_pdf, b"%PDF-fixture")
        self.assertEqual(bundle.prospect_pdf_url, "https://viewer.invalid/hz32.pdf")
        self.assertEqual(bundle.publication_json, publication.content)
        validate_pdf.assert_called_once_with(pdf.content)
        self.assertEqual(client.get.call_count, 4)

    @patch("app.netto_store_prospect._validate_prospect_pdf")
    def test_content_addressed_pdf_write_is_idempotent(self, validate_pdf):
        source = SourceConfig(
            chain="netto", enabled=True, priority=1,
            url="https://example.invalid/store/5659",
            scope="family_primary_netto", notes="fixture", keywords=(),
            store_external_id="5659", store_name="Netto fixture",
        )
        bundle = NettoStoreProspectBundle(
            store_url=source.url, prospect_url="https://example.invalid/hz32/",
            prospect_slug="hz32", store_html=b"store", prospect_html=b"prospect",
            valid_from=date(2026, 8, 3), valid_until=date(2026, 8, 8),
            validity_text="03.08.26 - 08.08.26", selected_store_cookie_present=True,
            elapsed_ms=1, publication_json=b"{}",
            prospect_pdf_url="https://example.invalid/hz32.pdf",
            prospect_pdf=b"%PDF-fixture",
        )
        collected_at = datetime(2026, 8, 3, 8, 0, tzinfo=timezone.utc)
        with tempfile.TemporaryDirectory() as tmp, patch(
            "app.netto_store_prospect.get_settings",
            return_value=Mock(raw_snapshot_dir=Path(tmp)),
        ):
            first_path, first_digest = _write_bundle(
                bundle, source=source, collected_at=collected_at
            )
            second_path, second_digest = _write_bundle(
                bundle, source=source, collected_at=collected_at
            )
            first_manifest = json.loads(first_path.read_text(encoding="utf-8"))
            pdf_files = list((Path(tmp) / "netto").glob("*.pdf"))

        self.assertEqual(first_path, second_path)
        self.assertEqual(first_digest, second_digest)
        self.assertEqual(len(pdf_files), 1)
        self.assertEqual(
            pdf_files[0].name,
            f"5659-hz32-{first_manifest['prospect_pdf_sha256']}.pdf",
        )

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
