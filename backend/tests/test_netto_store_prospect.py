from __future__ import annotations

from datetime import date, datetime, timezone
from decimal import Decimal
import unittest
from uuid import uuid4

from app.netto_store_prospect import (
    NettoStoreProspectBundle,
    apply_prospect_validity,
    extract_prospect_validity,
)
from app.schemas import OfferCandidate, SourceChain


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
        self.assertEqual(out.parser_version,"netto-v1.2-store-prospect")

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
