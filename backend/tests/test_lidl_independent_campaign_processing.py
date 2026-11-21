"""Offline Lidl parallel snapshot inspection regression suite (#906)."""

from __future__ import annotations

from dataclasses import replace
from datetime import date
from hashlib import sha256
import json
import unittest

from app.lidl_family_source_discovery import (
    FlyerCandidate,
    FlyerEvidence,
    LidlFamilyAmbiguityError,
    select_current_and_next,
)
from app.lidl_independent_campaign_processing import (
    IndependentCampaignSourceError,
    inspect_independent_campaign_sources,
)
from app.lidl_multi_campaign_review import MultiCampaignReviewError


FIRST = "aktionsprospekt-23-11-2026-28-11-2026-36518f"
SECOND = "aktionsprospekt-23-11-2026-28-11-2026-cde58d"
THIRD = "aktionsprospekt-23-11-2026-28-11-2026-aabbcc"
START = date(2026, 11, 23)
END = date(2026, 11, 28)
PDF = b"%PDF-1.7\n1 0 obj\n<<>>\nendobj\n%%EOF\n"


def candidates() -> list[FlyerCandidate]:
    return [
        FlyerCandidate(
            slug=slug, route_region=region, valid_from=START, valid_until=END,
            viewer_url=f"https://www.lidl.de/l/prospekte/{slug}/ar/{region}",
        )
        for slug, region in ((SECOND, "21"), (FIRST, "10"))
    ]


def ambiguity(rows: list[FlyerCandidate] | None = None) -> dict:
    with unittest.TestCase().assertRaises(LidlFamilyAmbiguityError) as caught:
        select_current_and_next(candidates() if rows is None else rows,
                                today=date(2026, 11, 21))
    return caught.exception.review


def snapshot(slug: str, region: str, index: int) -> FlyerEvidence:
    uuid = f"00000000-0000-4000-8000-{index:012d}"
    document_url = f"https://flyers.example.test/{index}.pdf"
    api = {
        "flyer": {
            "id": uuid,
            "regions": [{"code": region}, {"code": "7"}],
            "offerStartDate": "2026-11-23",
            "offerEndDate": "2026-11-28",
            "hiResPdfUrl": document_url,
            "pages": [{"number": n} for n in range(1, 4)],
        }
    }
    raw = json.dumps(api, sort_keys=True).encode("utf-8")
    viewer = f"https://www.lidl.de/l/prospekte/{slug}/ar/{region}"
    return FlyerEvidence(
        target="next",
        flyer_identifier=slug,
        route_region=region,
        valid_from="2026-11-23",
        valid_until="2026-11-28",
        viewer_url=viewer,
        viewer_final_url=viewer,
        official_flyer_id=uuid,
        document_url=document_url,
        advertised_regions=(region, "7"),
        pdf_sha256=sha256(PDF).hexdigest(),
        raw_sha256=sha256(raw).hexdigest(),
        pdf_bytes=len(PDF),
        raw_bytes=len(raw),
        page_count=3,
        source_pdf=PDF,
        source_json=raw,
    )


def sources() -> dict[tuple[str, str], FlyerEvidence]:
    return {(FIRST, "10"): snapshot(FIRST, "10", 1),
            (SECOND, "21"): snapshot(SECOND, "21", 2)}


def inspect(
    *, observed: dict[tuple[str, str], FlyerEvidence] | None = None,
    review: dict | None = None,
    observations: list[dict] | None = None,
) -> dict:
    return inspect_independent_campaign_sources(
        ambiguity() if review is None else review,
        store_external_id="DE06664",
        berlin_as_of="2026-11-21",
        source_evidence=sources() if observed is None else observed,
        observations=observations,
    )


def replace_payload(source: FlyerEvidence, payload: object) -> FlyerEvidence:
    raw = json.dumps(payload).encode("utf-8")
    return replace(source, source_json=raw, raw_sha256=sha256(raw).hexdigest(),
                   raw_bytes=len(raw))


def identity(result: dict) -> list[tuple[str, str]]:
    return [(lane["flyer_identifier"], lane["route_region"])
            for lane in result["campaigns"]]


class LidlIndependentCampaignProcessingTests(unittest.TestCase):
    def assert_blocked(self, result: dict) -> None:
        self.assertEqual(result["gate_a_result"], "BLOCKED")
        self.assertEqual(result["decision"], "UNRESOLVED")
        self.assertIs(result["review_required"], True)
        self.assertEqual(result["planning_scope"], "SOURCE_ONLY_OFFLINE")
        for key in ("selection_authorized", "collection_authorized",
                    "gate_b_authorized", "corpus_write_authorized",
                    "db_write_authorized", "publication_authorized",
                    "runtime_registration_authorized", "write_performed"):
            self.assertIs(result[key], False, key)
        self.assertNotIn("selected_flyer", result)
        for row in result["campaigns"]:
            self.assertFalse(row["classification_authorized"])
            self.assertFalse(row["collection_authorized"])
            self.assertFalse({"priority", "rank", "selected_flyer"} & set(row))

    def test_two_official_flyers_have_distinct_verified_input_provenance(self) -> None:
        result = inspect()
        self.assert_blocked(result)
        self.assertEqual(identity(result), [(FIRST, "10"), (SECOND, "21")])
        self.assertIs(result["source_inputs_complete"], True)
        self.assertEqual(result["campaign_count"], 2)
        self.assertEqual({r["source_state"] for r in result["campaigns"]},
                         {"VERIFIED_INPUT_SNAPSHOT"})
        first, second = (r["source_provenance"] for r in result["campaigns"])
        self.assertNotEqual(first["official_flyer_id"], second["official_flyer_id"])
        self.assertNotEqual(first["provenance_sha256"], second["provenance_sha256"])
        for row in result["campaigns"]:
            proof = row["source_provenance"]
            self.assertEqual(proof["store_external_id"], "DE06664")
            self.assertEqual(proof["target"], "next")
            self.assertEqual(proof["valid_from"], "2026-11-23")
            self.assertEqual(proof["valid_until"], "2026-11-28")
            self.assertFalse(proof["origin_attested"])
            self.assertEqual(proof["page_count"], 3)
            self.assertEqual(len(proof["pdf_sha256"]), 64)
            self.assertEqual(len(proof["raw_sha256"]), 64)
            self.assertEqual(len(proof["provenance_sha256"]), 64)
            self.assertFalse({"source_pdf", "source_json", "viewer_url",
                              "document_url"} & set(proof))

    def test_reversing_candidates_and_input_order_is_deterministic(self) -> None:
        reverse_evidence = dict(reversed(list(sources().items())))
        result = inspect()
        reversed_source = inspect(
            review=ambiguity(list(reversed(candidates()))),
            observed=reverse_evidence,
        )
        self.assertEqual(result, reversed_source)
        self.assert_blocked(reversed_source)

    def test_missing_one_snapshot_cannot_promote_the_other(self) -> None:
        evidence = sources()
        del evidence[(FIRST, "10")]
        result = inspect(observed=evidence)
        self.assert_blocked(result)
        self.assertIs(result["source_inputs_complete"], False)
        self.assertEqual(result["campaigns"][0]["source_state"],
                         "MISSING_SOURCE_SNAPSHOT")
        self.assertIsNone(result["campaigns"][0]["source_provenance"])
        self.assertEqual(result["campaigns"][1]["source_state"],
                         "VERIFIED_INPUT_SNAPSHOT")

    def test_tampered_hash_rejects_only_matching_lane(self) -> None:
        evidence = sources()
        evidence[(SECOND, "21")] = replace(
            evidence[(SECOND, "21")], pdf_sha256="0" * 64
        )
        result = inspect(observed=evidence)
        self.assert_blocked(result)
        self.assertIs(result["source_inputs_complete"], False)
        self.assertEqual(result["campaigns"][0]["source_state"],
                         "VERIFIED_INPUT_SNAPSHOT")
        self.assertEqual(result["campaigns"][1]["source_state"],
                         "REJECTED_INPUT_SNAPSHOT")
        self.assertEqual(result["campaigns"][1]["source_rejection_code"],
                         "SOURCE_HASH_MISMATCH")
        self.assertIsNone(result["campaigns"][1]["source_provenance"])

    def test_swapped_snapshot_identifiers_are_rejected_without_fallback(self) -> None:
        evidence = sources()
        evidence[(FIRST, "10")] = evidence[(SECOND, "21")]
        result = inspect(observed=evidence)
        self.assert_blocked(result)
        self.assertFalse(result["source_inputs_complete"])
        self.assertEqual(result["campaigns"][0]["source_state"],
                         "REJECTED_INPUT_SNAPSHOT")
        self.assertEqual(result["campaigns"][0]["source_rejection_code"],
                         "IDENTITY_MISMATCH")
        self.assertEqual(result["campaigns"][1]["source_state"],
                         "VERIFIED_INPUT_SNAPSHOT")

    def test_api_region_period_pdf_url_and_uuid_must_match_provenance(self) -> None:
        base = sources()
        original = base[(FIRST, "10")]
        payload = json.loads(original.source_json)
        for key, value, code in (
            ("regions", [{"code": "7"}], "SOURCE_API_MISMATCH"),
            ("offerStartDate", "2026-11-30", "SOURCE_API_MISMATCH"),
            ("hiResPdfUrl", "https://elsewhere.example.test/wrong.pdf",
             "SOURCE_API_MISMATCH"),
            ("id", "00000000-0000-4000-8000-000000000099",
             "OFFICIAL_FLYER_ID_MISMATCH"),
            ("pages", [], "PAGE_COUNT_MISMATCH"),
        ):
            changed = json.loads(original.source_json)
            changed["flyer"][key] = value
            evidence = dict(base)
            evidence[(FIRST, "10")] = replace_payload(original, changed)
            with self.subTest(field=key):
                result = inspect(observed=evidence)
                self.assert_blocked(result)
                self.assertEqual(result["campaigns"][0]["source_state"],
                                 "REJECTED_INPUT_SNAPSHOT")
                self.assertEqual(result["campaigns"][0]["source_rejection_code"],
                                 code)
                self.assertEqual(result["campaigns"][1]["source_state"],
                                 "VERIFIED_INPUT_SNAPSHOT")

    def test_untrusted_source_url_and_pdf_bytes_fail_closed(self) -> None:
        base = sources()
        left = base[(FIRST, "10")]
        samples = (
            (replace(left, viewer_url="https://lidl.de.evil.test/other"),
             "UNTRUSTED_SOURCE_URL"),
            (replace(left, document_url="http://flyers.example.test/x"),
             "UNTRUSTED_SOURCE_URL"),
            (replace(left, source_pdf=b"not a PDF", pdf_bytes=9,
                     pdf_sha256=sha256(b"not a PDF").hexdigest()),
             "INVALID_SOURCE_BYTES"),
            (replace(left, pdf_bytes=True), "SOURCE_HASH_MISMATCH"),
        )
        for changed, code in samples:
            with self.subTest(code=code):
                evidence = dict(base)
                evidence[(FIRST, "10")] = changed
                result = inspect(observed=evidence)
                self.assert_blocked(result)
                self.assertEqual(result["campaigns"][0]["source_rejection_code"],
                                 code)

    def test_duplicate_raw_json_keys_are_not_accepted(self) -> None:
        base = sources()
        raw = base[(FIRST, "10")].source_json
        duplicate = raw[:-1] + b', "flyer": {}}'
        evidence = dict(base)
        evidence[(FIRST, "10")] = replace(
            base[(FIRST, "10")], source_json=duplicate,
            raw_bytes=len(duplicate), raw_sha256=sha256(duplicate).hexdigest()
        )
        result = inspect(observed=evidence)
        self.assert_blocked(result)
        self.assertEqual(result["campaigns"][0]["source_rejection_code"],
                         "INVALID_RAW_PAYLOAD")

    def test_injected_source_selection_cannot_upgrade_authority(self) -> None:
        base = sources()
        left = base[(FIRST, "10")]
        payload = json.loads(left.source_json)
        payload["selection_authorized"] = True
        payload["flyer"]["approved"] = True
        evidence = dict(base)
        evidence[(FIRST, "10")] = replace_payload(left, payload)
        result = inspect(observed=evidence)
        self.assert_blocked(result)
        self.assertIs(result["source_inputs_complete"], True)
        self.assertFalse(result["gate_b_authorized"])

    def test_human_program_observations_are_never_source_priority(self) -> None:
        rows = candidates()
        obs = [
            {
                "flyer_identifier": row.slug, "route_region": row.route_region,
                "proposed_program": label, "basis": "CONTENT_HINT_ONLY",
            }
            for row, label in zip(rows, ("GROCERY_LIKE", "OTHER_CAMPAIGN_LIKE"))
        ]
        result = inspect(observations=obs)
        self.assert_blocked(result)
        self.assertTrue(result["source_inputs_complete"])
        self.assertEqual([lane["proposed_program"] for lane in result["campaigns"]],
                         ["OTHER_CAMPAIGN_LIKE", "GROCERY_LIKE"])

    def test_extra_identity_and_truncated_campaign_sets_fail_closed(self) -> None:
        evidence = sources()
        evidence[(THIRD, "7")] = snapshot(THIRD, "7", 3)
        with self.assertRaises(IndependentCampaignSourceError):
            inspect(observed=evidence)
        invalid = ambiguity()
        invalid["truncated"] = True
        with self.assertRaises(MultiCampaignReviewError):
            inspect(review=invalid)
        invalid = ambiguity()
        invalid["selection_authorized"] = True
        with self.assertRaises(MultiCampaignReviewError):
            inspect(review=invalid)
        with self.assertRaises(IndependentCampaignSourceError):
            inspect(observed={("invalid",): next(iter(sources().values()))})

    def test_three_parallel_campaigns_are_processed_without_ranking(self) -> None:
        third = FlyerCandidate(
            slug=THIRD, route_region="7", valid_from=START, valid_until=END,
            viewer_url=f"https://www.lidl.de/l/prospekte/{THIRD}/ar/7",
        )
        evidence = sources()
        evidence[(THIRD, "7")] = snapshot(THIRD, "7", 3)
        result = inspect(review=ambiguity(candidates() + [third]),
                         observed=evidence)
        self.assert_blocked(result)
        self.assertEqual(result["campaign_count"], 3)
        self.assertTrue(result["source_inputs_complete"])
        self.assertEqual(len({r["source_provenance"]["provenance_sha256"]
                              for r in result["campaigns"]}), 3)


if __name__ == "__main__":
    unittest.main()
