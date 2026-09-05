from __future__ import annotations

import unittest

import httpx

from app.kaufland_source_discovery import (
    STORE_NAME,
    STORE_PAGE_URL,
    KauflandSourceDiscoveryError,
    discover_kaufland_source,
    fetch_html_bounded,
    parse_store_page,
)


STORE_HTML = """
<!doctype html>
<html>
  <body>
    <h1>Kaufland Dortmund-Aplerbeck</h1>
    <div>Aplerbecker Marktplatz 7-10</div>
    <div>44287 Dortmund</div>
    <h3>Unsere Knüller der Woche</h3>
    <h3>Gültig vom 13.08.2026 bis 19.08.2026</h3>
    <a href="/angebote/uebersicht.html?kloffer-articleID=01227288&amp;kloffer-category=135_Foodknueller">
      Artikel A
    </a>
    <a href="/angebote/uebersicht.html?kloffer-articleID=20909926&amp;kloffer-category=135_Foodknueller">
      Artikel B
    </a>
    <a href="/angebote/uebersicht.html?kloffer-category=135_Foodknueller">Zeige alle Angebote</a>
    <h3>Aktuelle Prospekte</h3>
    <a href="https://leaflets.kaufland.com/de-DE/DE1503/short">
      Gültig vom 17.08. bis 19.08. Jetzt blättern
    </a>
    <a href="https://leaflets.kaufland.com/de-DE/DE1503/current">
      Gültig vom 13.08. bis 19.08. Jetzt blättern
    </a>
    <h3>Prospekt-Vorschau</h3>
    <a href="https://leaflets.kaufland.com/de-DE/DE1503/preview">
      Gültig vom 20.08. bis 26.08. Jetzt blättern
    </a>
  </body>
</html>
"""

OVERVIEW_PATH = "/angebote/uebersicht.html"


class KauflandStorePageTest(unittest.TestCase):
    def test_exact_store_page_extracts_main_window_articles_and_leaflets(self):
        evidence = parse_store_page(STORE_HTML, STORE_PAGE_URL)

        self.assertEqual(evidence.store_id, "1503")
        self.assertEqual(evidence.store_name, STORE_NAME)
        self.assertEqual(evidence.main_valid_from, "2026-08-13")
        self.assertEqual(evidence.main_valid_to, "2026-08-19")
        self.assertEqual(evidence.article_id_count, 2)
        self.assertEqual(evidence.article_id_sample, ("01227288", "20909926"))
        self.assertEqual(len(evidence.leaflets), 3)
        self.assertEqual([item.preview for item in evidence.leaflets], [False, False, True])
        self.assertEqual(
            [item.validity_label for item in evidence.leaflets],
            [
                "Gültig vom 17.08. bis 19.08.",
                "Gültig vom 13.08. bis 19.08.",
                "Gültig vom 20.08. bis 26.08.",
            ],
        )
        self.assertIn("kloffer-category=135_Foodknueller", evidence.offer_overview_url)
        self.assertNotIn("kloffer-articleID", evidence.offer_overview_url)

    def test_wrong_store_path_fails_closed(self):
        with self.assertRaises(KauflandSourceDiscoveryError) as caught:
            parse_store_page(
                STORE_HTML,
                "https://filiale.kaufland.de/service/filiale/dortmund-hombruch-4420.html",
            )
        self.assertEqual(caught.exception.code, "STORE_BINDING_NOT_PROVEN")

    def test_wrong_store_heading_fails_closed(self):
        wrong = STORE_HTML.replace(
            "<h1>Kaufland Dortmund-Aplerbeck</h1>",
            "<h1>Kaufland Dortmund-Hombruch</h1>",
        )
        with self.assertRaises(KauflandSourceDiscoveryError) as caught:
            parse_store_page(wrong, STORE_PAGE_URL)
        self.assertEqual(caught.exception.code, "STORE_BINDING_NOT_PROVEN")


class KauflandNetworkBoundaryTest(unittest.TestCase):
    def test_redirect_to_unallowlisted_host_is_rejected_before_follow(self):
        calls: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            calls.append(str(request.url))
            return httpx.Response(
                302,
                headers={"location": "https://example.invalid/offers"},
                request=request,
            )

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(KauflandSourceDiscoveryError) as caught:
                fetch_html_bounded(client, STORE_PAGE_URL)

        self.assertEqual(caught.exception.code, "UNSAFE_SOURCE_HOST")
        self.assertEqual(calls, [STORE_PAGE_URL])

    def test_documented_store_name_cookie_can_prove_overview_binding(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("dortmund-aplerbeck-1503.html"):
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text=STORE_HTML,
                    request=request,
                )
            if request.url.path == OVERVIEW_PATH:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text="<html><body><h1>Alle Angebote</h1></body></html>",
                    request=request,
                )
            return httpx.Response(404, request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            client.cookies.set(
                "storeName",
                "DE1503",
                domain="filiale.kaufland.de",
                path="/",
            )
            report = discover_kaufland_source(client)

        self.assertTrue(report.store_binding_proven)
        self.assertEqual(report.binding_method, "same_session_exact_store_cookie")
        self.assertIn("storeName", report.session_cookie_names)
        self.assertTrue(report.session_cookie_has_store_id)
        self.assertTrue(report.overview_request_cookie_has_store_id)
        public = report.as_public_dict()
        self.assertNotIn("request_cookie_header", str(public))

    def test_other_store_name_cookie_does_not_prove_aplerbeck_binding(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("dortmund-aplerbeck-1503.html"):
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text=STORE_HTML,
                    request=request,
                )
            if request.url.path == OVERVIEW_PATH:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text="<html><body><h1>Alle Angebote</h1></body></html>",
                    request=request,
                )
            return httpx.Response(404, request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            client.cookies.set(
                "storeName",
                "DE4420",
                domain="filiale.kaufland.de",
                path="/",
            )
            with self.assertRaises(KauflandSourceDiscoveryError) as caught:
                discover_kaufland_source(client)

        self.assertEqual(caught.exception.code, "STORE_BINDING_NOT_PROVEN")

    def test_exact_store_name_in_overview_can_prove_binding_without_store_cookie(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("dortmund-aplerbeck-1503.html"):
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text=STORE_HTML,
                    request=request,
                )
            if request.url.path == OVERVIEW_PATH:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text=f"<html><body>Deine Filiale: {STORE_NAME}</body></html>",
                    request=request,
                )
            return httpx.Response(404, request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            report = discover_kaufland_source(client)

        self.assertEqual(report.binding_method, "overview_body_exact_store_name")
        self.assertFalse(report.overview_request_cookie_has_store_id)
        self.assertTrue(report.overview_body_has_store_name)

    def test_recent_store_list_containing_1503_does_not_prove_binding(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("dortmund-aplerbeck-1503.html"):
                return httpx.Response(
                    200,
                    headers={
                        "content-type": "text/html; charset=utf-8",
                        "set-cookie": "recentStores=DE1503%2CDE4420; Path=/; Secure",
                    },
                    text=STORE_HTML,
                    request=request,
                )
            if request.url.path == OVERVIEW_PATH:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text="<html><body><h1>Alle Angebote</h1></body></html>",
                    request=request,
                )
            return httpx.Response(404, request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(KauflandSourceDiscoveryError) as caught:
                discover_kaufland_source(client)

        self.assertEqual(caught.exception.code, "STORE_BINDING_NOT_PROVEN")

    def test_unbound_generic_overview_fails_closed(self):
        def handler(request: httpx.Request) -> httpx.Response:
            if request.url.path.endswith("dortmund-aplerbeck-1503.html"):
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text=STORE_HTML,
                    request=request,
                )
            if request.url.path == OVERVIEW_PATH:
                return httpx.Response(
                    200,
                    headers={"content-type": "text/html; charset=utf-8"},
                    text="<html><body><h1>Alle Angebote</h1></body></html>",
                    request=request,
                )
            return httpx.Response(404, request=request)

        with httpx.Client(transport=httpx.MockTransport(handler)) as client:
            with self.assertRaises(KauflandSourceDiscoveryError) as caught:
                discover_kaufland_source(client)

        self.assertEqual(caught.exception.code, "STORE_BINDING_NOT_PROVEN")


if __name__ == "__main__":
    unittest.main()
