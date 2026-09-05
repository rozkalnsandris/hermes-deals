from __future__ import annotations

from datetime import datetime
import unittest
from zoneinfo import ZoneInfo

import httpx

from app.kaufland_evidence_preflight import (
    KauflandSourceDiscoveryError,
    build_k2_preflight,
    validate_freeze_occupancy,
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
    <a href="/angebote/uebersicht.html?kloffer-category=135_Foodknueller">
      Zeige alle Angebote
    </a>
    <h3>Aktuelle Prospekte</h3>
    <a href="https://leaflets.kaufland.com/de-DE/DE_de_KDZ2_1503_D34-MoMi/ar/1503">
      Gültig vom 17.08. bis 19.08. Jetzt blättern
    </a>
    <a href="https://leaflets.kaufland.com/de-DE/DE_de_KDZ1_1503_D33/ar/1503">
      Gültig vom 13.08. bis 19.08. Jetzt blättern
    </a>
    <a href="https://leaflets.kaufland.com/de-DE/DE_de_Magazine2_0_sdgdv/ar/0">
      Gültig vom 13.08. bis 26.08. Jetzt blättern
    </a>
    <h3>Prospekt-Vorschau</h3>
    <a href="https://leaflets.kaufland.com/de-DE/DE_de_KDZ1_1503_D34/ar/1503">
      Gültig vom 20.08. bis 26.08. Jetzt blättern
    </a>
    <a href="https://leaflets.kaufland.com/de-DE/DE_de_leaflet2_1503_D34-EL-Schule/ar/1503">
      Gültig vom 20.08. bis 02.09. Jetzt blättern
    </a>
  </body>
</html>
"""

OVERVIEW_PATH = "/angebote/uebersicht.html"
BERLIN = ZoneInfo("Europe/Berlin")


def _client_and_calls() -> tuple[httpx.Client, list[str]]:
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(str(request.url))
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
        if request.url.host == "leaflets.kaufland.com":
            body = f"<html><body>{request.url.path}</body></html>"
            return httpx.Response(
                200,
                headers={"content-type": "text/html; charset=utf-8"},
                text=body,
                request=request,
            )
        return httpx.Response(404, request=request)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    client.cookies.set(
        "storeName",
        "DE1503",
        domain="filiale.kaufland.de",
        path="/",
    )
    return client, calls


class KauflandK2EvidencePreflightTest(unittest.TestCase):
    def test_preflight_hashes_store_bound_families_without_retaining_raw_material(self):
        client, calls = _client_and_calls()
        with client:
            report = build_k2_preflight(
                client,
                collected_at=datetime(2026, 8, 19, 11, 15, tzinfo=BERLIN),
            )

        self.assertTrue(report.store_binding_proven)
        self.assertEqual(report.store_id, "1503")
        self.assertEqual(report.family_count, 4)
        self.assertEqual(report.distinct_validity_family_count, 4)
        self.assertEqual(
            {item.relation for item in report.families},
            {"current_short", "current_main", "preview_main", "preview_overlap"},
        )
        self.assertTrue(all(item.store_bound for item in report.families))
        self.assertTrue(all(len(item.sha256) == 64 for item in report.families))
        self.assertTrue(all(len(item.identity_sha256) == 64 for item in report.families))
        self.assertTrue(
            all(item.freeze_key.startswith("kaufland/1503/") for item in report.families)
        )
        self.assertEqual(len(report.skipped_leaflets), 1)
        self.assertEqual(
            report.skipped_leaflets[0].reason,
            "not_exact_store_1503_bound",
        )
        self.assertFalse(
            any("/DE_de_Magazine2_0_sdgdv/ar/0" in url for url in calls),
            "unbound thematic leaflet must remain metadata-only and must not be fetched",
        )

    def test_preview_family_is_not_marked_active_before_valid_from(self):
        client, _ = _client_and_calls()
        with client:
            report = build_k2_preflight(
                client,
                collected_at=datetime(2026, 8, 19, 23, 59, tzinfo=BERLIN),
            )

        preview_main = next(
            item for item in report.families if item.relation == "preview_main"
        )
        self.assertEqual(preview_main.valid_from, "2026-08-20")
        self.assertFalse(preview_main.active_at_collection)

    def test_manifest_identity_is_stable_across_collection_timestamps(self):
        client1, _ = _client_and_calls()
        with client1:
            first = build_k2_preflight(
                client1,
                collected_at=datetime(2026, 8, 19, 10, 0, tzinfo=BERLIN),
            )
        client2, _ = _client_and_calls()
        with client2:
            second = build_k2_preflight(
                client2,
                collected_at=datetime(2026, 8, 19, 12, 0, tzinfo=BERLIN),
            )

        self.assertNotEqual(first.collection_timestamp, second.collection_timestamp)
        self.assertEqual(first.preflight_manifest_sha256, second.preflight_manifest_sha256)
        self.assertEqual(
            [item.identity_sha256 for item in first.families],
            [item.identity_sha256 for item in second.families],
        )

    def test_freeze_occupancy_reuses_identical_identity_and_fails_on_collision(self):
        identity = "a" * 64
        self.assertEqual(validate_freeze_occupancy(None, identity), "CREATE")
        self.assertEqual(validate_freeze_occupancy(identity, identity), "NO_OP")
        with self.assertRaises(KauflandSourceDiscoveryError) as caught:
            validate_freeze_occupancy("b" * 64, identity)
        self.assertEqual(caught.exception.code, "EVIDENCE_COLLISION")


if __name__ == "__main__":
    unittest.main()
