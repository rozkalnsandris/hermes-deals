"""Read-only concurrent Lidl source acquisition regression tests (#906)."""

from __future__ import annotations

from datetime import date
import unittest

import httpx

from app.lidl_family_source_discovery import (
    FLYER_API_URL,
    HUB_URL,
    FlyerCandidate,
    LidlFamilyAmbiguityError,
    StoreBinding,
    select_current_and_next,
)
from app.lidl_independent_campaign_capture import (
    IndependentCampaignCaptureError,
    capture_parallel_campaign_sources,
)
from app.lidl_multi_campaign_review import MultiCampaignReviewError


FIRST = "aktionsprospekt-23-11-2026-28-11-2026-36518f"
SECOND = "aktionsprospekt-23-11-2026-28-11-2026-cde58d"
THIRD = "aktionsprospekt-23-11-2026-28-11-2026-aabbcc"
PAIR = ((SECOND, "21"), (FIRST, "10"))
AS_OF = "2026-11-21"
ALLOWED = frozenset({"assets.lidl.de"})
PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


def candidate(slug: str, region: str) -> FlyerCandidate:
    return FlyerCandidate(
        slug=slug, route_region=region,
        valid_from=date(2026, 11, 23), valid_until=date(2026, 11, 28),
        viewer_url=f"https://www.lidl.de/l/prospekte/{slug}/ar/{region}",
    )


def source_ambiguity(rows: tuple[tuple[str, str], ...] = PAIR) -> dict:
    with unittest.TestCase().assertRaises(LidlFamilyAmbiguityError) as caught:
        select_current_and_next(
            [candidate(slug, region) for slug, region in rows],
            today=date.fromisoformat(AS_OF),
        )
    return caught.exception.review


def capture(
    handler, *,
    ambiguity: dict | None = None,
    allowlist: frozenset[str] = ALLOWED,
    client_options: dict | None = None,
):
    with httpx.Client(
        transport=httpx.MockTransport(handler),
        follow_redirects=True, **(client_options or {})
    ) as client:
        return capture_parallel_campaign_sources(
            client, ambiguity=source_ambiguity() if ambiguity is None else ambiguity,
            binding=StoreBinding(), berlin_as_of=AS_OF,
            allowed_pdf_hosts=allowlist,
        )


class FakeOfficialTransport:
    def __init__(self, rows=PAIR):
        self.rows = rows
        self.requests: list[httpx.Request] = []
        self.hub_status = 200
        self.hub_body: str | None = None
        self.api_override: dict[str, dict] = {}
        self.raw_override: dict[str, bytes] = {}
        self.pdf_status: dict[str, int] = {}
        self.pdf_host: dict[str, str] = {}
        self.viewer_status: dict[str, int] = {}
        self.viewer_redirect: dict[str, str] = {}
        self.shared_uuid = False
        self.block_external = True

    def __call__(self, request: httpx.Request) -> httpx.Response:
        self.requests.append(request)
        url = str(request.url)
        if url == HUB_URL:
            html = self.hub_body
            if html is None:
                html = "\n".join(
                    f'<a href="/l/prospekte/{slug}/ar/{region}">Flyer</a>'
                    for slug, region in self.rows
                )
            return httpx.Response(
                self.hub_status, text=html,
                headers={"Set-Cookie": "untrusted_cookie=do-not-forward; Path=/"},
                request=request,
            )
        if request.url.host == "www.lidl.de" and request.url.path.startswith("/l/prospekte/"):
            slug = request.url.path.split("/")[3]
            region = request.url.path.split("/")[-1]
            if slug in self.viewer_redirect:
                return httpx.Response(
                    302, headers={"Location": self.viewer_redirect[slug]},
                    request=request,
                )
            return httpx.Response(
                self.viewer_status.get(slug, 200),
                text=f"<html>official-{slug}-{region}</html>", request=request,
            )
        if request.url.host == "endpoints.leaflets.schwarz":
            self_test = request.url
            assert self_test.path == "/v4/flyer"
            slug = self_test.params["flyer_identifier"]
            region = self_test.params["region_id"]
            assert self_test.params["version"] == "4"
            assert self_test.params["client"] == "lidl"
            if slug in self.raw_override:
                return httpx.Response(200, content=self.raw_override[slug],
                                      request=request)
            i = {"36518f": 1, "cde58d": 2, "aabbcc": 3}[slug.rsplit("-", 1)[-1]]
            uuid = (
                "00000000-0000-4000-8000-000000000001"
                if self.shared_uuid else
                f"00000000-0000-4000-8000-{i:012d}"
            )
            payload = {
                "flyer": {
                    "id": uuid,
                    "regions": [{"code": region}, {"code": "7"}]
                    if region != "7" else [{"code": "7"}],
                    "offerStartDate": "2026-11-23",
                    "offerEndDate": "2026-11-28",
                    "hiResPdfUrl": f"https://{self.pdf_host.get(slug, 'assets.lidl.de')}/{i}.pdf",
                    "pages": [{"number": 1}, {"number": 2}],
                }
            }
            if slug in self.api_override:
                payload["flyer"].update(self.api_override[slug])
            return httpx.Response(200, json=payload, request=request)
        if request.url.host == "assets.lidl.de":
            name = request.url.path.rsplit("/", 1)[-1]
            return httpx.Response(
                self.pdf_status.get(name, 200),
                content=PDF + name.encode("ascii"),
                request=request,
            )
        if self.block_external:
            raise AssertionError(f"unexpected network destination: {request.url}")
        return httpx.Response(404, request=request)


class LidlIndependentCampaignCaptureTests(unittest.TestCase):
    def assert_blocked(self, result: dict) -> None:
        self.assertEqual(result["gate_a_result"], "BLOCKED")
        self.assertEqual(result["decision"], "UNRESOLVED")
        self.assertEqual(result["capture_scope"], "SOURCE_ONLY_IN_MEMORY")
        self.assertFalse(result["origin_attested"])
        self.assertFalse(result["local_write_performed"])
        for flag in (
            "selection_authorized", "collection_authorized",
            "gate_b_authorized", "corpus_write_authorized",
            "db_write_authorized", "publication_authorized",
            "runtime_registration_authorized", "write_performed",
        ):
            self.assertIs(result[flag], False, flag)
        self.assertNotIn("selected_flyer", result)
        for lane in result["campaigns"]:
            self.assertIs(lane["classification_authorized"], False)
            self.assertIs(lane["collection_authorized"], False)
            self.assertFalse({"rank", "priority", "selected_flyer"} & set(lane))

    def test_two_independent_gets_and_full_identity_bound_provenance(self) -> None:
        transport = FakeOfficialTransport()
        result, sources = capture(transport)
        self.assert_blocked(result)
        self.assertTrue(result["capture_complete"])
        self.assertTrue(result["source_inputs_complete"])
        self.assertEqual(result["campaign_count"], 2)
        self.assertEqual(len(transport.requests), 7)
        self.assertEqual(
            [(lane["flyer_identifier"], lane["route_region"])
             for lane in result["campaigns"]],
            [(FIRST, "10"), (SECOND, "21")],
        )
        self.assertEqual(set(sources), {(FIRST, "10"), (SECOND, "21")})
        self.assertNotEqual(sources[(FIRST, "10")].raw_sha256,
                            sources[(SECOND, "21")].raw_sha256)
        self.assertNotEqual(sources[(FIRST, "10")].pdf_sha256,
                            sources[(SECOND, "21")].pdf_sha256)
        for lane in result["campaigns"]:
            self.assertEqual(lane["capture_state"], "CAPTURED")
            self.assertEqual(lane["source_state"], "VERIFIED_INPUT_SNAPSHOT")
            self.assertEqual(lane["request_count"], 3)
            provenance = lane["source_provenance"]
            self.assertEqual(provenance["store_external_id"], "DE06664")
            self.assertEqual(provenance["valid_from"], "2026-11-23")
            self.assertEqual(provenance["valid_until"], "2026-11-28")
            self.assertFalse(provenance["origin_attested"])
            self.assertEqual(len(provenance["provenance_sha256"]), 64)
            self.assertFalse({"source_pdf", "source_json", "document_url",
                              "viewer_url"} & set(lane))
        self.assertEqual(len(result["hub_raw_sha256"]), 64)
        self.assertEqual(len(result["selected_store_context_sha256"]), 64)

    def test_selected_store_cookies_are_not_sent_to_api_or_pdf(self) -> None:
        transport = FakeOfficialTransport()
        capture(transport, client_options={"cookies": {"secret": "no-leak"}})
        for request in transport.requests:
            host = request.url.host
            if host == "www.lidl.de":
                self.assertIn("st=6664", request.headers.get("cookie", ""))
                self.assertIn("wh=7", request.headers.get("cookie", ""))
                self.assertNotIn("secret", request.headers.get("cookie", ""))
            else:
                self.assertEqual(request.headers.get("cookie", ""), "")
        self.assertEqual({req.method for req in transport.requests}, {"GET"})

    def test_hub_order_cannot_select_source_and_both_are_fetched(self) -> None:
        first = FakeOfficialTransport()
        second = FakeOfficialTransport(rows=tuple(reversed(PAIR)))
        result1, sources1 = capture(first)
        result2, sources2 = capture(second)
        self.assert_blocked(result1)
        self.assert_blocked(result2)
        self.assertEqual(
            [r["source_provenance"] for r in result1["campaigns"]],
            [r["source_provenance"] for r in result2["campaigns"]],
        )
        self.assertEqual(set(sources1), set(sources2))
        self.assertEqual(result1["capture_complete"], result2["capture_complete"])

    def test_first_pdf_failure_cannot_block_second_or_promote_it(self) -> None:
        transport = FakeOfficialTransport()
        transport.pdf_status["1.pdf"] = 503
        result, sources = capture(transport)
        self.assert_blocked(result)
        self.assertFalse(result["capture_complete"])
        self.assertEqual(set(sources), {(SECOND, "21")})
        first, second = result["campaigns"]
        self.assertEqual(first["capture_state"], "FAILED")
        self.assertEqual(first["capture_failure_code"], "SOURCE_HTTP_NOT_200")
        self.assertIsNone(first["source_provenance"])
        self.assertEqual(second["source_state"], "VERIFIED_INPUT_SNAPSHOT")
        self.assertEqual(second["capture_state"], "CAPTURED")

    def test_external_pdf_host_rejected_before_any_get_to_it(self) -> None:
        transport = FakeOfficialTransport()
        transport.pdf_host[FIRST] = "assets.lidl.de.evil.test"
        result, sources = capture(transport)
        self.assert_blocked(result)
        self.assertEqual(set(sources), {(SECOND, "21")})
        self.assertEqual(result["campaigns"][0]["capture_failure_code"],
                         "UNTRUSTED_PDF_HOST")
        self.assertFalse(any("evil" in str(r.url) for r in transport.requests))

    def test_untrusted_viewer_redirect_is_not_followed(self) -> None:
        transport = FakeOfficialTransport()
        transport.viewer_redirect[FIRST] = "https://external.test/redirect"
        result, sources = capture(transport)
        self.assert_blocked(result)
        self.assertEqual(set(sources), {(SECOND, "21")})
        self.assertEqual(result["campaigns"][0]["capture_failure_code"],
                         "SOURCE_HTTP_NOT_200")
        self.assertFalse(any("external.test" in str(r.url)
                             for r in transport.requests))

    def test_wrong_api_region_period_and_uuid_reject_only_one_lane(self) -> None:
        cases = (
            ({"regions": [{"code": "9"}]}, "API_IDENTITY_MISMATCH"),
            ({"offerEndDate": "2026-11-29"}, "API_IDENTITY_MISMATCH"),
            ({"id": "00000000-0000-4000-8000-00000000000b"},
             None),
            ({"id": "not-uuid"}, "INVALID_OFFICIAL_FLYER_ID"),
            ({"pages": []}, "INVALID_OFFICIAL_FLYER_METADATA"),
        )
        for patch, expected in cases:
            transport = FakeOfficialTransport()
            transport.api_override[FIRST] = patch
            result, sources = capture(transport)
            with self.subTest(patch=patch):
                self.assert_blocked(result)
                if expected is None:
                    # A canonical but changed UUID still identifies this
                    # independently verified source: no program selection.
                    self.assertTrue(result["campaigns"][0]["source_provenance"])
                    self.assertEqual(len(sources), 2)
                else:
                    self.assertEqual(result["campaigns"][0]["capture_failure_code"],
                                     expected)
                    self.assertEqual(set(sources), {(SECOND, "21")})

    def test_duplicate_json_key_and_injected_selection_remain_fail_closed(self) -> None:
        transport = FakeOfficialTransport()
        transport.raw_override[FIRST] = b'{"flyer": {}, "flyer": {}}'
        result, sources = capture(transport)
        self.assert_blocked(result)
        self.assertEqual(set(sources), {(SECOND, "21")})
        self.assertEqual(result["campaigns"][0]["capture_failure_code"],
                         "INVALID_API_JSON")
        injection = FakeOfficialTransport()
        injection.api_override[FIRST] = {"selection_authorized": True}
        result, sources = capture(injection)
        self.assert_blocked(result)
        self.assertEqual(len(sources), 2)
        self.assertFalse(result["selection_authorized"])

    def test_flyer_uuid_collision_quarantines_both_sources(self) -> None:
        transport = FakeOfficialTransport()
        transport.shared_uuid = True
        result, sources = capture(transport)
        self.assert_blocked(result)
        self.assertFalse(result["capture_complete"])
        self.assertEqual(sources, {})
        for lane in result["campaigns"]:
            self.assertEqual(lane["source_state"], "REJECTED_INPUT_SNAPSHOT")
            self.assertEqual(lane["source_rejection_code"],
                             "OFFICIAL_UUID_COLLISION")
            self.assertIsNone(lane["source_provenance"])

    def test_hub_missing_or_changed_candidate_fails_before_viewer_fetch(self) -> None:
        for hub_rows in (((FIRST, "10"),), ((FIRST, "10"), (THIRD, "7"))):
            with self.subTest(hub_rows=hub_rows):
                transport = FakeOfficialTransport(rows=hub_rows)
                with self.assertRaises(IndependentCampaignCaptureError):
                    capture(transport)
                self.assertEqual(len(transport.requests), 1)

    def test_malformed_ambiguity_and_wrong_store_fail_before_network(self) -> None:
        invalid = source_ambiguity()
        invalid["selection_authorized"] = True
        transport = FakeOfficialTransport()
        with self.assertRaises(MultiCampaignReviewError):
            capture(transport, ambiguity=invalid)
        self.assertEqual(transport.requests, [])
        with httpx.Client(transport=httpx.MockTransport(transport)) as client:
            with self.assertRaises(IndependentCampaignCaptureError):
                capture_parallel_campaign_sources(
                    client, ambiguity=source_ambiguity(),
                    binding=StoreBinding(entity_id="1234"),
                    berlin_as_of=AS_OF, allowed_pdf_hosts=ALLOWED,
                )
        self.assertEqual(transport.requests, [])

    def test_inherited_http_auth_is_rejected_before_network(self) -> None:
        for client_options in (
            {"auth": ("username", "password")},
            {"headers": {"Authorization": "Bearer secret"}},
            {"headers": {"Proxy-Authorization": "Basic secret"}},
        ):
            with self.subTest(client_options=client_options):
                transport = FakeOfficialTransport()
                with self.assertRaisesRegex(IndependentCampaignCaptureError,
                                            "AUTHENTICATED_CLIENT_NOT_ALLOWED"):
                    capture(transport, client_options=client_options)
                self.assertEqual(transport.requests, [])

    def test_empty_or_invalid_pdf_host_policy_fails_before_network(self) -> None:
        transport = FakeOfficialTransport()
        for hosts in (frozenset(), frozenset({"127.0.0.1"}),
                      frozenset({"assets.lidl.de.evil.test", "localhost"})):
            with self.subTest(hosts=hosts):
                with self.assertRaises(IndependentCampaignCaptureError):
                    capture(transport, allowlist=hosts)
        self.assertEqual(transport.requests, [])

    def test_extra_third_campaign_preserved_and_unranked(self) -> None:
        third = PAIR + ((THIRD, "7"),)
        transport = FakeOfficialTransport(rows=third)
        result, sources = capture(transport, ambiguity=source_ambiguity(third))
        self.assert_blocked(result)
        self.assertEqual(result["campaign_count"], 3)
        self.assertTrue(result["capture_complete"])
        self.assertEqual(len(sources), 3)
        self.assertEqual(len(transport.requests), 10)
        self.assertEqual(
            {lane["route_region"] for lane in result["campaigns"]},
            {"10", "21", "7"},
        )

    def test_hub_oversize_rejected_without_downstream_fetch(self) -> None:
        transport = FakeOfficialTransport()
        transport.hub_body = "x" * (2 * 1024 * 1024 + 1)
        with self.assertRaisesRegex(IndependentCampaignCaptureError,
                                    "SOURCE_TOO_LARGE"):
            capture(transport)
        self.assertEqual(len(transport.requests), 1)


if __name__ == "__main__":
    unittest.main()
