
from __future__ import annotations

from datetime import date, datetime, timezone
import json
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

import httpx

from app.lidl_family_source_discovery import (
    FLYER_API_URL,
    HUB_URL,
    FlyerCandidate,
    LidlFamilyDiscoveryError,
    StoreBinding,
    _validate_flyer_payload,
    berlin_today,
    discover_selected_store_flyers,
    official_lidl_url,
    parse_hub_candidates,
    select_current_and_next,
    selected_store_cookies,
    write_discovery_evidence,
)


CURRENT_SLUG = "aktionsprospekt-27-07-2026-01-08-2026-c338f8"
NEXT_SLUG = "aktionsprospekt-03-08-2026-08-08-2026-5ec593"
CURRENT_VIEWER = f"https://www.lidl.de/l/prospekte/{CURRENT_SLUG}/ar/7"
NEXT_VIEWER = f"https://www.lidl.de/l/prospekte/{NEXT_SLUG}/ar/21"


def candidate(
    slug: str,
    region: str,
    start: date,
    end: date,
) -> FlyerCandidate:
    return FlyerCandidate(
        slug=slug,
        route_region=region,
        valid_from=start,
        valid_until=end,
        viewer_url=(
            f"https://www.lidl.de/l/prospekte/{slug}/ar/{region}"
        ),
    )


class LidlFamilySourceDiscoveryTest(unittest.TestCase):
    def test_official_lidl_url_requires_https_lidl_host(self) -> None:
        self.assertTrue(official_lidl_url("https://www.lidl.de/a"))
        self.assertTrue(official_lidl_url("https://assets.lidl.de/a"))
        self.assertFalse(official_lidl_url("http://www.lidl.de/a"))
        self.assertFalse(official_lidl_url("https://lidl.de.evil.invalid/a"))

    def test_berlin_today_uses_iana_zone_at_utc_date_boundary(self) -> None:
        self.assertEqual(
            berlin_today(datetime(2026, 7, 29, 22, 30, tzinfo=timezone.utc)),
            date(2026, 7, 30),
        )
        with self.assertRaises(LidlFamilyDiscoveryError):
            berlin_today(datetime(2026, 7, 30, 0, 30))

    def test_parse_hub_candidates_deduplicates_and_preserves_own_regions(self) -> None:
        html = f"""
        <a href="/l/prospekte/{CURRENT_SLUG}/ar/7">Current</a>
        <a href="/l/prospekte/{CURRENT_SLUG}/ar/7">Duplicate</a>
        <a href="/l/prospekte/{NEXT_SLUG}/ar/21">Next</a>
        """
        rows = parse_hub_candidates(html)
        self.assertEqual(len(rows), 2)
        self.assertEqual([row.route_region for row in rows], ["7", "21"])

    def test_parse_hub_candidates_rejects_offsite_viewer(self) -> None:
        html = (
            f'<a href="https://evil.invalid/l/prospekte/'
            f'{CURRENT_SLUG}/ar/7">Current</a>'
        )
        with self.assertRaises(LidlFamilyDiscoveryError):
            parse_hub_candidates(html)

    def test_select_current_and_next_keeps_per_flyer_route_region(self) -> None:
        rows = [
            candidate(
                CURRENT_SLUG,
                "7",
                date(2026, 7, 27),
                date(2026, 8, 1),
            ),
            candidate(
                NEXT_SLUG,
                "21",
                date(2026, 8, 3),
                date(2026, 8, 8),
            ),
        ]
        selected = select_current_and_next(rows, today=date(2026, 7, 30))
        self.assertEqual(selected["current"].route_region, "7")
        self.assertEqual(selected["next"].route_region, "21")

    def test_select_current_and_next_keeps_saturday_current_only(self) -> None:
        rows = [
            candidate(
                CURRENT_SLUG,
                "7",
                date(2026, 7, 27),
                date(2026, 8, 1),
            )
        ]
        selected = select_current_and_next(rows, today=date(2026, 8, 1))
        self.assertEqual(selected["current"].route_region, "7")
        self.assertIsNone(selected["next"])

    def test_select_current_and_next_allows_sunday_gap_with_unique_next(self) -> None:
        rows = [
            candidate(
                CURRENT_SLUG,
                "7",
                date(2026, 7, 27),
                date(2026, 8, 1),
            ),
            candidate(
                NEXT_SLUG,
                "21",
                date(2026, 8, 3),
                date(2026, 8, 8),
            ),
        ]
        selected = select_current_and_next(rows, today=date(2026, 8, 2))
        self.assertIsNone(selected["current"])
        self.assertEqual(selected["next"].route_region, "21")

    def test_select_current_and_next_allows_no_current_or_future(self) -> None:
        rows = [
            candidate(
                CURRENT_SLUG,
                "7",
                date(2026, 7, 27),
                date(2026, 8, 1),
            )
        ]
        selected = select_current_and_next(rows, today=date(2026, 8, 2))
        self.assertIsNone(selected["current"])
        self.assertIsNone(selected["next"])

    def test_select_current_and_next_fails_closed_on_current_ambiguity(self) -> None:
        rows = [
            candidate(
                CURRENT_SLUG,
                "7",
                date(2026, 7, 27),
                date(2026, 8, 1),
            ),
            candidate(
                CURRENT_SLUG,
                "21",
                date(2026, 7, 27),
                date(2026, 8, 1),
            ),
        ]
        with self.assertRaises(LidlFamilyDiscoveryError):
            select_current_and_next(rows, today=date(2026, 7, 30))

    def test_select_current_and_next_fails_closed_on_nearest_next_ambiguity(self) -> None:
        rows = [
            candidate(
                CURRENT_SLUG,
                "7",
                date(2026, 7, 27),
                date(2026, 8, 1),
            ),
            candidate(
                NEXT_SLUG,
                "21",
                date(2026, 8, 3),
                date(2026, 8, 8),
            ),
            candidate(
                NEXT_SLUG,
                "7",
                date(2026, 8, 3),
                date(2026, 8, 8),
            ),
        ]
        with self.assertRaises(LidlFamilyDiscoveryError):
            select_current_and_next(rows, today=date(2026, 8, 2))

    def test_validate_flyer_payload_requires_matching_region_and_period(self) -> None:
        row = candidate(
            NEXT_SLUG,
            "21",
            date(2026, 8, 3),
            date(2026, 8, 8),
        )
        flyer, regions, pdf = _validate_flyer_payload(
            {
                "flyer": {
                    "id": "x",
                    "offerStartDate": "2026-08-03",
                    "offerEndDate": "2026-08-08",
                    "hiResPdfUrl": "https://assets.example.invalid/source.pdf",
                    "regions": [{"code": "21"}],
                }
            },
            candidate=row,
        )
        self.assertEqual(flyer["id"], "x")
        self.assertEqual(regions, ("21",))
        self.assertEqual(pdf, "https://assets.example.invalid/source.pdf")

        with self.assertRaises(LidlFamilyDiscoveryError):
            _validate_flyer_payload(
                {
                    "flyer": {
                        "offerStartDate": "2026-08-03",
                        "offerEndDate": "2026-08-08",
                        "hiResPdfUrl": "https://assets.example.invalid/source.pdf",
                        "regions": [{"code": "7"}],
                    }
                },
                candidate=row,
            )

    def test_discovery_end_to_end_uses_each_route_region(self) -> None:
        hub = f"""
        <a href="/l/prospekte/{CURRENT_SLUG}/ar/7">Current</a>
        <a href="/l/prospekte/{NEXT_SLUG}/ar/21">Next</a>
        """
        api_regions: list[str] = []

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url.startswith(HUB_URL):
                return httpx.Response(
                    200,
                    text=hub,
                    request=request,
                )
            if url.startswith(CURRENT_VIEWER) or url.startswith(NEXT_VIEWER):
                return httpx.Response(200, text="<html/>", request=request)
            if url.startswith(FLYER_API_URL):
                region = request.url.params["region_id"]
                api_regions.append(region)
                if region == "7":
                    slug = CURRENT_SLUG
                    start, end = "2026-07-27", "2026-08-01"
                else:
                    slug = NEXT_SLUG
                    start, end = "2026-08-03", "2026-08-08"
                payload = {
                    "flyer": {
                        "id": slug,
                        "offerStartDate": start,
                        "offerEndDate": end,
                        "hiResPdfUrl": f"https://assets.example.invalid/{region}.pdf",
                        "regions": [{"code": region}],
                        "pages": [{}, {}],
                    }
                }
                return httpx.Response(
                    200,
                    json=payload,
                    request=request,
                )
            if url == "https://assets.example.invalid/7.pdf":
                return httpx.Response(200, content=b"%PDF-current", request=request)
            if url == "https://assets.example.invalid/21.pdf":
                return httpx.Response(200, content=b"%PDF-next", request=request)
            return httpx.Response(404, request=request)

        binding = StoreBinding()
        with httpx.Client(
            transport=httpx.MockTransport(handler),
            follow_redirects=True,
            cookies=selected_store_cookies(binding),
        ) as client:
            summary, evidence = discover_selected_store_flyers(
                client,
                binding=binding,
                today=date(2026, 7, 30),
            )

        self.assertEqual(api_regions, ["7", "21"])
        self.assertEqual(summary["targets"]["current"]["route_region"], "7")
        self.assertEqual(summary["targets"]["next"]["route_region"], "21")
        self.assertEqual(evidence["current"].source_pdf, b"%PDF-current")
        self.assertEqual(evidence["next"].source_pdf, b"%PDF-next")

    def test_evidence_writer_is_atomic_and_refuses_nonempty_output(self) -> None:
        binding = StoreBinding()
        row = candidate(
            CURRENT_SLUG,
            "7",
            date(2026, 7, 27),
            date(2026, 8, 1),
        )

        def handler(request: httpx.Request) -> httpx.Response:
            url = str(request.url)
            if url.startswith(HUB_URL):
                return httpx.Response(
                    200,
                    text=(
                        f'<a href="/l/prospekte/{CURRENT_SLUG}/ar/7">'
                        "Current</a>"
                    ),
                    request=request,
                )
            if url.startswith(CURRENT_VIEWER):
                return httpx.Response(200, text="<html/>", request=request)
            if url.startswith(FLYER_API_URL):
                return httpx.Response(
                    200,
                    json={
                        "flyer": {
                            "id": "current",
                            "offerStartDate": "2026-07-27",
                            "offerEndDate": "2026-08-01",
                            "hiResPdfUrl": "https://assets.example.invalid/current.pdf",
                            "regions": [{"code": "7"}],
                            "pages": [{}],
                        }
                    },
                    request=request,
                )
            if url == "https://assets.example.invalid/current.pdf":
                return httpx.Response(200, content=b"%PDF-current", request=request)
            return httpx.Response(404, request=request)

        with httpx.Client(
            transport=httpx.MockTransport(handler),
            follow_redirects=True,
        ) as client:
            summary, evidence = discover_selected_store_flyers(
                client,
                binding=binding,
                today=date(2026, 7, 30),
            )

        with TemporaryDirectory() as temp:
            output = Path(temp) / "evidence"
            write_discovery_evidence(
                output,
                summary=summary,
                evidence=evidence,
            )
            self.assertTrue((output / "discovery.json").is_file())
            self.assertTrue((output / "family-current/source.pdf").is_file())
            self.assertFalse((output / "family-next/source.pdf").exists())
            with self.assertRaises(LidlFamilyDiscoveryError):
                write_discovery_evidence(
                    output,
                    summary=summary,
                    evidence=evidence,
                )


if __name__ == "__main__":
    unittest.main()
