from __future__ import annotations

import unittest
from datetime import datetime, timezone
from uuid import UUID

from app.parsers.edeka import EdekaParserContext, parse_edeka_html


class EdekaPfandOnlyNoPriceSkipTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context = EdekaParserContext(
            snapshot_id=UUID("11111111-2222-4333-8444-555555555555"),
            source_url="https://www.edeka.de/maerkte/071897/angebote/",
            collected_at=datetime(2026, 8, 10, 18, 0, tzinfo=timezone.utc),
            public_market_id="071897",
            internal_market_id="587881",
            store_name="EDEKA Patzer",
        )

    def _page(self, first_dialog_extra: str = "") -> str:
        return f"""
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
              <span class="sr-only">Produktbild granini Die Limo</span>
              <p class="line-clmap-2">
                versch. Sorten, je 1 l Flasche zzgl. € 0.25 Pfand
              </p>
            </article>
            <dialog id="dialog-angebot-68aa5875-e4e1-4a5b-8d6c-221a2319dc2b">
              <span class="sr-only">Dialog schließen</span>
              <span class="sr-only">Angebot:</span>
              <strong>Gültig ab 10.08.2026</strong>
              <span>versch. Sorten, je 1 l Flasche zzgl. € 0.25 Pfand</span>
              {first_dialog_extra}
              <p>
                Diese Artikel sind in den mit dieser Werbung gekennzeichneten Märkten erhältlich.
                Alle Angebote gültig bis Samstag, den 15.08.2026, KW 33.
              </p>
            </dialog>

            <article>
              <h3>
                <a href="#angebot-bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb">
                  Angebot: Kontrollprodukt
                </a>
              </h3>
              <div class="sr-only">Festpreis von 1.49 €</div>
            </article>
            <dialog id="dialog-angebot-bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb">
              <strong>Gültig ab 10.08.2026</strong>
              <p>Alle Angebote gültig bis Samstag, den 15.08.2026, KW 33.</p>
            </dialog>
          </body>
        </html>
        """

    def test_proven_pfand_only_no_price_card_is_skipped(self) -> None:
        offers = parse_edeka_html(self._page(), self.context)

        self.assertEqual(len(offers), 1)
        self.assertEqual(
            offers[0].source_offer_id,
            "bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb",
        )
        self.assertEqual(str(offers[0].price_eur), "1.49")

    def test_split_price_structure_remains_fail_closed(self) -> None:
        split_price = """
        <div class="price-shell" data-price="1.79">
          <span>1.</span><span>79</span>
        </div>
        """

        with self.assertRaises(ValueError) as caught:
            parse_edeka_html(self._page(split_price), self.context)

        message = str(caught.exception)
        self.assertIn("granini Die Limo", message)
        self.assertIn("data-price=1.79", message)


if __name__ == "__main__":
    unittest.main()
