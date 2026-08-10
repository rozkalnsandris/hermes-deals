from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.parsers.edeka import EdekaParserContext, parse_edeka_html
from app.schemas import SourceChain

FIXTURE = Path(__file__).parent / "fixtures" / "edeka_offers.html"
SNAPSHOT_ID = UUID("11111111-2222-4333-8444-555555555555")


class EdekaParserTest(unittest.TestCase):
    def setUp(self) -> None:
        self.html = FIXTURE.read_bytes()
        self.context = EdekaParserContext(
            snapshot_id=SNAPSHOT_ID,
            source_url="https://www.edeka.de/maerkte/071897/angebote/",
            collected_at=datetime(
                2026, 7, 24, 17, 0, tzinfo=timezone.utc
            ),
            public_market_id="071897",
            internal_market_id="587881",
            store_name="EDEKA Patzer",
        )

    def test_parses_uuid_bound_offers(self) -> None:
        offers = parse_edeka_html(self.html, self.context)

        self.assertEqual(len(offers), 2)
        self.assertEqual(
            [offer.source_offer_id for offer in offers],
            [
                "41e0594d-3617-45e4-a1f2-9f2503c0669b",
                "39943e55-da2c-444b-abe4-4922d5b12a07",
            ],
        )
        self.assertTrue(
            all(offer.source_chain is SourceChain.EDEKA for offer in offers)
        )
        self.assertTrue(
            all(offer.parser_version == "edeka-v1" for offer in offers)
        )

    def test_public_id_is_offer_store_external_id(self) -> None:
        offer = parse_edeka_html(self.html, self.context)[0]

        self.assertEqual(offer.source_store_external_id, "071897")
        self.assertEqual(offer.source_store_name, "EDEKA Patzer")
        self.assertEqual(offer.raw_payload["public_market_id"], "071897")
        self.assertEqual(offer.raw_payload["internal_market_id"], "587881")
        self.assertNotEqual(
            offer.source_store_external_id,
            offer.raw_payload["internal_market_id"],
        )

    def test_live_patzer_validity_contract(self) -> None:
        offers = parse_edeka_html(self.html, self.context)

        for offer in offers:
            self.assertEqual(str(offer.valid_from), "2026-07-20")
            self.assertEqual(str(offer.valid_until), "2026-07-25")

    def test_festpreis_and_app_preis_are_conservative(self) -> None:
        offer = parse_edeka_html(self.html, self.context)[1]

        self.assertEqual(str(offer.price_eur), "1.99")
        self.assertEqual(str(offer.app_price_eur), "1.79")
        self.assertFalse(offer.requires_app)
        self.assertIsNone(offer.regular_price_eur)
        self.assertIsNone(offer.discount_percent)

    def test_product_image_beats_logo_asset(self) -> None:
        offer = parse_edeka_html(self.html, self.context)[1]

        self.assertIsNotNone(offer.source_image_url)
        image_url = str(offer.source_image_url)
        self.assertIn(
            "f42c94a6-8d1e-4872-9bc3-89bcd4eced5d_",
            image_url,
        )
        self.assertNotIn("Logo_Final", image_url)

    def test_rejects_fragment_without_matching_dialog(self) -> None:
        broken = self.html.decode("utf-8").replace(
            'id="dialog-angebot-41e0594d-3617-45e4-a1f2-9f2503c0669b"',
            'id="dialog-angebot-broken"',
            1,
        )

        with self.assertRaisesRegex(ValueError, "no matching dialog"):
            parse_edeka_html(broken, self.context)

    def test_rejects_wrong_public_market_binding(self) -> None:
        wrong = EdekaParserContext(
            snapshot_id=SNAPSHOT_ID,
            source_url=self.context.source_url,
            collected_at=self.context.collected_at,
            public_market_id="999999",
            internal_market_id="587881",
            store_name="EDEKA Patzer",
        )

        with self.assertRaisesRegex(
            ValueError,
            "not bound to the configured public market",
        ):
            parse_edeka_html(self.html, wrong)

    def test_rabattierter_preis_live_examples_are_non_app_sale_prices(self) -> None:
        live_examples = "\n".join(
            [
                "<!doctype html>",
                "<html lang=\"de\">",
                "<head><title>Angebote EDEKA Patzer</title></head>",
                "<body>",
                "<article><h3><a href=\"#angebot-b6c3df00-b607-4a68-82c6-33b616f2d6fb\">Angebot: Original Wagner Steinofen Pizza, Pizzies oder Flammkuchen</a></h3><div class=\"sr-only\">App-Preis von 1.59 €</div><div class=\"sr-only\">Rabattierter Preis von 1.79 € (Insgesamt -47 % Rabatt)</div></article>",
                "<dialog id=\"dialog-angebot-b6c3df00-b607-4a68-82c6-33b616f2d6fb\"><strong>Gültig ab 20.07.2026</strong><p>Alle Angebote gültig bis Samstag, den 25.07.2026, KW 30.</p></dialog>",
                "<article><h3><a href=\"#angebot-75547dc1-44b8-4564-9ba7-ff0ec4a0272c\">Angebot: Mövenpick Eis</a></h3><div class=\"sr-only\">App-Preis von 1.49 €</div><div class=\"sr-only\">Rabattierter Preis von 1.69 € (Insgesamt -58 % Rabatt)</div></article>",
                "<dialog id=\"dialog-angebot-75547dc1-44b8-4564-9ba7-ff0ec4a0272c\"><strong>Gültig ab 20.07.2026</strong><p>Alle Angebote gültig bis Samstag, den 25.07.2026, KW 30.</p></dialog>",
                "<article><h3><a href=\"#angebot-1b852a70-a2aa-4449-9b02-01a5e6559a1a\">Angebot: Coca-Cola Cola oder Limonade</a></h3><div class=\"sr-only\">App-Preis von 10.99 €</div><div class=\"sr-only\">Rabattierter Preis von 11.69 € (Insgesamt -27 % Rabatt)</div></article>",
                "<dialog id=\"dialog-angebot-1b852a70-a2aa-4449-9b02-01a5e6559a1a\"><strong>Gültig ab 20.07.2026</strong><p>Alle Angebote gültig bis Samstag, den 25.07.2026, KW 30.</p></dialog>",
                "</body>",
                "</html>",
            ]
        )

        offers = parse_edeka_html(live_examples, self.context)
        by_id = {offer.source_offer_id: offer for offer in offers}

        expected = {
            "b6c3df00-b607-4a68-82c6-33b616f2d6fb": ("1.79", "1.59"),
            "75547dc1-44b8-4564-9ba7-ff0ec4a0272c": ("1.69", "1.49"),
            "1b852a70-a2aa-4449-9b02-01a5e6559a1a": ("11.69", "10.99"),
        }

        self.assertEqual(len(offers), 3)
        for offer_id, (sale_price, app_price) in expected.items():
            offer = by_id[offer_id]
            self.assertEqual(str(offer.price_eur), sale_price)
            self.assertEqual(str(offer.app_price_eur), app_price)
            self.assertFalse(offer.requires_app)
            self.assertIsNone(offer.discount_percent)
            self.assertIsNone(offer.regular_price_eur)

    def test_payback_points_only_card_is_not_inferred_as_price_offer(self) -> None:
        html = """
        <!doctype html>
        <html lang="de">
          <head><title>Angebote EDEKA Patzer</title></head>
          <body>
            <article>
              <h3>
                <a href="#angebot-aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa">
                  Angebot: PAYBACK Produkt
                </a>
              </h3>
              <span>20 Extra°Punkte Mit PAYBACK 20 Extra Punkte sammeln.</span>
              <p>versch. Sorten, Normalpreis: € 0,99</p>
            </article>
            <dialog id="dialog-angebot-aaaaaaaa-1111-4111-8111-aaaaaaaaaaaa">
              <strong>Gültig ab 20.07.2026</strong>
              <p>Alle Angebote gültig bis Samstag, den 25.07.2026, KW 30.</p>
            </dialog>
            <article>
              <h3>
                <a href="#angebot-bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb">
                  Angebot: Preis Produkt
                </a>
              </h3>
              <div class="sr-only">Festpreis von 1.49 €</div>
            </article>
            <dialog id="dialog-angebot-bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb">
              <strong>Gültig ab 20.07.2026</strong>
              <p>Alle Angebote gültig bis Samstag, den 25.07.2026, KW 30.</p>
            </dialog>
          </body>
        </html>
        """

        offers = parse_edeka_html(html, self.context)

        self.assertEqual(len(offers), 1)
        self.assertEqual(
            offers[0].source_offer_id,
            "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb",
        )
        self.assertEqual(str(offers[0].price_eur), "1.49")

    def test_unknown_price_semantic_still_fails_closed_with_diagnostic(self) -> None:
        html = """
        <!doctype html>
        <html lang="de">
          <head><title>Angebote EDEKA Patzer</title></head>
          <body>
            <article>
              <h3>
                <a href="#angebot-cccccccc-3333-4333-8333-cccccccccccc">
                  Angebot: Unbekannter Preis
                </a>
              </h3>
              <div class="sr-only">Sonderpreis von 2.49 €</div>
            </article>
            <dialog id="dialog-angebot-cccccccc-3333-4333-8333-cccccccccccc">
              <strong>Gültig ab 20.07.2026</strong>
              <p>Alle Angebote gültig bis Samstag, den 25.07.2026, KW 30.</p>
            </dialog>
          </body>
        </html>
        """

        with self.assertRaisesRegex(
            ValueError,
            r"Sonderpreis von 2\.49 €",
        ):
            parse_edeka_html(html, self.context)


if __name__ == "__main__":
    unittest.main()
