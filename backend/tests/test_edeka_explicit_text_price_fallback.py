from __future__ import annotations

import unittest
from datetime import datetime, timezone
from uuid import UUID

from app.parsers.edeka import EdekaParserContext, parse_edeka_html


SNAPSHOT_ID = UUID("11111111-2222-4333-8444-555555555555")


class EdekaExplicitTextPriceFallbackTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context = EdekaParserContext(
            snapshot_id=SNAPSHOT_ID,
            source_url="https://www.edeka.de/maerkte/071897/angebote/",
            collected_at=datetime(2026, 7, 24, 17, 0, tzinfo=timezone.utc),
            public_market_id="071897",
            internal_market_id="587881",
            store_name="EDEKA Patzer",
        )

    def test_dialog_visible_explicit_festpreis_is_accepted(self) -> None:
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
              <div class="sr-only">Produktbild granini Die Limo</div>
              <p>versch. Sorten, je 1 l Flasche zzgl. € 0.25 Pfand</p>
            </article>
            <dialog id="dialog-angebot-68aa5875-e4e1-4a5b-8d6c-221a2319dc2b">
              <button><span class="sr-only">Dialog schließen</span></button>
              <div class="sr-only">Angebot:</div>
              <div><span>Festpreis von 1.49 €</span></div>
              <strong>Gültig ab 20.07.2026</strong>
              <p>Alle Angebote gültig bis Samstag, den 25.07.2026, KW 30.</p>
            </dialog>
          </body>
        </html>
        """

        offers = parse_edeka_html(html, self.context)

        self.assertEqual(len(offers), 1)
        offer = offers[0]
        self.assertEqual(offer.product_name_raw, "granini Die Limo")
        self.assertEqual(str(offer.price_eur), "1.49")
        self.assertIsNone(offer.app_price_eur)
        self.assertFalse(offer.requires_app)
        self.assertEqual(
            offer.raw_payload["price_labels"],
            ["Festpreis von 1.49 €"],
        )

    def test_bare_dialog_digits_are_not_inferred_as_price(self) -> None:
        html = """
        <!doctype html>
        <html lang="de">
          <head><title>Angebote EDEKA Patzer</title></head>
          <body>
            <article>
              <h3>
                <a href="#angebot-eeeeeeee-5555-4555-8555-eeeeeeeeeeee">
                  Angebot: Bare Digits Produkt
                </a>
              </h3>
              <div class="sr-only">Produktbild Bare Digits Produkt</div>
              <p>je 1 l Flasche zzgl. € 0.25 Pfand</p>
            </article>
            <dialog id="dialog-angebot-eeeeeeee-5555-4555-8555-eeeeeeeeeeee">
              <button><span class="sr-only">Dialog schließen</span></button>
              <div class="sr-only">Angebot:</div>
              <span>1.</span><span>49</span>
              <strong>Gültig ab 20.07.2026</strong>
              <p>Alle Angebote gültig bis Samstag, den 25.07.2026, KW 30.</p>
            </dialog>
          </body>
        </html>
        """

        with self.assertRaisesRegex(
            ValueError,
            "unsupported offer price semantics",
        ):
            parse_edeka_html(html, self.context)


if __name__ == "__main__":
    unittest.main()
