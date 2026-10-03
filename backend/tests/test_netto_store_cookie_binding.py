from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from app.netto_html_collector import fetch_pages
from app.parsers.netto_listing import STORE_PATH
from app.source_config import SourceConfig


SOURCE = SourceConfig(
    chain="netto",
    enabled=True,
    priority=1,
    url="https://www.netto-online.de" + STORE_PATH,
    scope="family_primary_netto",
    notes="",
    keywords=(),
    store_external_id="5659",
    store_name="Netto 5659",
)


class NettoStoreCookieBindingTest(unittest.TestCase):
    def test_wrong_selected_store_cookie_fails_before_listing_fetch(self) -> None:
        requested: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            requested.append(str(request.url))
            self.assertEqual(request.url.path, STORE_PATH)
            return httpx.Response(
                200,
                text="<html></html>",
                headers={
                    "content-type": "text/html",
                    "set-cookie": "netto_user_stores_id=6071; Path=/",
                },
            )

        client = httpx.Client(transport=httpx.MockTransport(handler))
        self.addCleanup(client.close)
        with patch("app.netto_html_collector.httpx.Client", return_value=client):
            with self.assertRaisesRegex(ValueError, "selected-store cookie mismatch"):
                fetch_pages(SOURCE)

        self.assertEqual(len(requested), 1)


if __name__ == "__main__":
    unittest.main()
