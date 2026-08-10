from __future__ import annotations

import unittest
from datetime import datetime, timezone
from uuid import UUID

from app.parsers.edeka import EdekaParserContext, parse_edeka_html


class EdekaDialogPriceFallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context = EdekaParserContext(
            snapshot_id=UUID("11111111-2222-4333-8444-555555555555"),
            source_url="https://www.edeka.de/maerkte/071897/angebote/",
            collected_at=datetime(2026, 7, 24, 17, 0, tzinfo=timezone.utc),
            public_market_id="071897",
            internal_market_id="587881",
            store_name="EDEKA Patzer",
        )

    def test_non_price_sr_only_label_allows_exact_dialog_fallback(self) -> None:
        html = """
        <!doctype html>
        <html lang="de">
          <head><title>Angebote EDEKA Patzer</title></head>
          <body>
            <article>
              <h3>
                <a href="#angebot-68aa5875-e4e1-4a5b-8d6c-221a2319dc2b">
                  Angebot: granini Die Limo
                </a>
              </h3>
              <span class="sr-only">Produktabbildung granini Die Limo</span>
              <p>versch. Sorten, je 1 l Flasche zzgl. € 0.25 Pfand</p>
            </article>
            <dialog id="dialog-angebot-68aa5875-e4e1-4a5b-8d6c-221a2319dc2b">
              <div class="sr-only">Festpreis von 1.49 €</div>
              <strong>Gültig ab 20.07.2026</strong>
              <p>Alle Angebote gültig bis Samstag, den 25.07.2026, KW 30.</p>
            </dialog>
          </body>
        </html>
        """

        offers = parse_edeka_html(html, self.context)

        self.assertEqual(len(offers), 1)
        offer = offers[0]
        self.assertEqual(
            offer.source_offer_id,
            "68aa5875-e4e1-4a5b-8d6c-221a2319dc2b",
        )
        self.assertEqual(str(offer.price_eur), "1.49")
        self.assertIsNone(offer.app_price_eur)
        self.assertFalse(offer.requires_app)
        self.assertIsNone(offer.regular_price_eur)
        self.assertEqual(offer.raw_payload["price_labels"], ["Festpreis von 1.49 €"])

    def test_unknown_price_like_sr_only_label_still_blocks_dialog_fallback(self) -> None:
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
              <span class="sr-only">Produktabbildung Test</span>
              <div class="sr-only">Sonderpreis von 2.49 €</div>
            </article>
            <dialog id="dialog-angebot-cccccccc-3333-4333-8333-cccccccccccc">
              <div class="sr-only">Festpreis von 2.29 €</div>
              <strong>Gültig ab 20.07.2026</strong>
              <p>Alle Angebote gültig bis Samstag, den 25.07.2026, KW 30.</p>
            </dialog>
          </body>
        </html>
        """

        with self.assertRaisesRegex(ValueError, r"Sonderpreis von 2\.49 €"):
            parse_edeka_html(html, self.context)


if __name__ == "__main__":
    unittest.main()
