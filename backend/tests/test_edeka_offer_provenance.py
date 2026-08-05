from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from uuid import UUID

from app.parsers.edeka import EdekaParserContext, parse_edeka_html

FIXTURE = Path(__file__).parent / "fixtures" / "edeka_offers.html"
SNAPSHOT_ID = UUID("11111111-2222-4333-8444-555555555555")
OFFER_ID = "41e0594d-3617-45e4-a1f2-9f2503c0669b"
SOURCE_URL = "https://www.edeka.de/maerkte/071897/angebote/"


class EdekaOfferProvenanceTest(unittest.TestCase):
    def setUp(self) -> None:
        self.html = FIXTURE.read_text(encoding="utf-8")
        self.context = EdekaParserContext(
            snapshot_id=SNAPSHOT_ID,
            source_url=SOURCE_URL,
            collected_at=datetime(
                2026, 7, 24, 17, 0, tzinfo=timezone.utc
            ),
            public_market_id="071897",
            internal_market_id="587881",
            store_name="EDEKA Patzer",
        )

    def _replace_first_offer_href(self, href: str) -> str:
        original = (
            'href="/maerkte/071897/angebote/'
            f'#angebot-{OFFER_ID}"'
        )
        replacement = f'href="{href}"'
        self.assertIn(original, self.html)
        return self.html.replace(original, replacement, 1)

    def test_accepts_absolute_offer_link_on_exact_source_page(self) -> None:
        href = f"{SOURCE_URL}#angebot-{OFFER_ID}"
        offers = parse_edeka_html(
            self._replace_first_offer_href(href),
            self.context,
        )

        offer = next(
            item for item in offers if item.source_offer_id == OFFER_ID
        )
        self.assertEqual(str(offer.source_url), SOURCE_URL)
        self.assertEqual(offer.raw_payload["fragment_href"], href)
        self.assertEqual(offer.snapshot_id, SNAPSHOT_ID)

    def test_rejects_offer_link_to_external_page(self) -> None:
        href = f"https://example.invalid/#angebot-{OFFER_ID}"

        with self.assertRaisesRegex(
            ValueError,
            "outside the configured source page",
        ):
            parse_edeka_html(
                self._replace_first_offer_href(href),
                self.context,
            )

    def test_rejects_offer_link_to_other_edeka_market(self) -> None:
        href = f"/maerkte/999999/angebote/#angebot-{OFFER_ID}"

        with self.assertRaisesRegex(
            ValueError,
            "outside the configured source page",
        ):
            parse_edeka_html(
                self._replace_first_offer_href(href),
                self.context,
            )

    def test_rejects_offer_link_with_query(self) -> None:
        href = f"{SOURCE_URL}?tracking=1#angebot-{OFFER_ID}"

        with self.assertRaisesRegex(
            ValueError,
            "outside the configured source page",
        ):
            parse_edeka_html(
                self._replace_first_offer_href(href),
                self.context,
            )

    def test_rejects_offer_link_with_downgraded_scheme(self) -> None:
        href = (
            "http://www.edeka.de/maerkte/071897/angebote/"
            f"#angebot-{OFFER_ID}"
        )

        with self.assertRaisesRegex(
            ValueError,
            "outside the configured source page",
        ):
            parse_edeka_html(
                self._replace_first_offer_href(href),
                self.context,
            )

    def test_rejects_source_context_with_query_or_fragment(self) -> None:
        for suffix in ("?tracking=1", "#angebot-test"):
            with self.subTest(suffix=suffix):
                context = EdekaParserContext(
                    snapshot_id=self.context.snapshot_id,
                    source_url=f"{SOURCE_URL}{suffix}",
                    collected_at=self.context.collected_at,
                    public_market_id=self.context.public_market_id,
                    internal_market_id=self.context.internal_market_id,
                    store_name=self.context.store_name,
                )

                with self.assertRaisesRegex(
                    ValueError,
                    "not bound to the configured public market",
                ):
                    parse_edeka_html(self.html, context)


if __name__ == "__main__":
    unittest.main()
