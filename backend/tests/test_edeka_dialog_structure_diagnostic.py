from __future__ import annotations

import unittest
from datetime import datetime, timezone
from uuid import UUID

from app.parsers.edeka import EdekaParserContext, parse_edeka_html


class EdekaDialogStructureDiagnosticTest(unittest.TestCase):
    def setUp(self) -> None:
        self.context = EdekaParserContext(
            snapshot_id=UUID("11111111-2222-4333-8444-555555555555"),
            source_url="https://www.edeka.de/maerkte/071897/angebote/",
            collected_at=datetime(2026, 7, 24, 17, 0, tzinfo=timezone.utc),
            public_market_id="071897",
            internal_market_id="587881",
            store_name="EDEKA Patzer",
        )

    def test_split_numeric_dialog_stays_fail_closed_with_bounded_structure(self) -> None:
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
              <span class="sr-only">Produktbild granini Die Limo</span>
              <p>versch. Sorten, je 1 l Flasche zzgl. € 0.25 Pfand</p>
            </article>
            <dialog id="dialog-angebot-68aa5875-e4e1-4a5b-8d6c-221a2319dc2b">
              <span class="sr-only">Dialog schließen</span>
              <span class="sr-only">Angebot:</span>
              <strong>Gültig ab 20.07.2026</strong>
              <div class="price-shell" data-price="1.49">
                <span class="price-major">1.</span>
                <span class="price-minor">49</span>
              </div>
              <p>Alle Angebote gültig bis Samstag, den 25.07.2026, KW 30.</p>
            </dialog>
          </body>
        </html>
        """

        with self.assertRaises(ValueError) as caught:
            parse_edeka_html(html, self.context)

        message = str(caught.exception)
        self.assertIn(
            "source_offer_id=68aa5875-e4e1-4a5b-8d6c-221a2319dc2b",
            message,
        )
        self.assertIn("granini Die Limo", message)
        self.assertIn("dialog_price_attributes=['div.data-price=1.49']", message)
        self.assertIn("text='1.'", message)
        self.assertIn("text='49'", message)
        self.assertIn("parent=div.class=price-shell", message)
        self.assertIn("dialog_fragments=", message)
        self.assertNotIn("<dialog", message)
        self.assertNotIn("<article", message)


if __name__ == "__main__":
    unittest.main()
