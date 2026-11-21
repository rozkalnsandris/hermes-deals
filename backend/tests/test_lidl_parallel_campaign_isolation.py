"""Regression tests for source-only Lidl parallel isolation (#906)."""

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
from app.lidl_independent_campaign_processing import IndependentCampaignSourceError
from app.lidl_multi_campaign_review import MultiCampaignReviewError
from app.lidl_parallel_campaign_isolation import plan_parallel_campaign_isolation


FIRST = "aktionsprospekt-23-11-2026-28-11-2026-36518f"
SECOND = "aktionsprospekt-23-11-2026-28-11-2026-cde58d"
THIRD = "aktionsprospekt-23-11-2026-28-11-2026-aabbcc"
START = date(2026, 11, 23)
END = date(2026, 11, 28)


def candidate(slug: str, route: str) -> FlyerCandidate:
    return FlyerCandidate(
        slug=slug,
        route_region=route,
        valid_from=START,
        valid_until=END,
        viewer_url=f"https://www.lidl.de/l/prospekte/{slug}/ar/{route}",
    )


def blocked(rows: list[FlyerCandidate] | None = None) -> dict:
    rows = rows if rows is not None else [
        candidate(SECOND, "21"), candidate(FIRST, "10")
    ]
    with unittest.TestCase().assertRaises(LidlFamilyAmbiguityError) as error:
        select_current_and_next(rows, today=date(2026, 11, 21))
    return error.exception.review


def snapshot(
    slug: str, route: str, number: int, *,
    regions: tuple[str, ...] | None = None,
) -> FlyerEvidence:
    uuid = f"00000000-0000-4000-8000-{number:012d}"
    advertised = (route, "7") if regions is None else regions
    document_url = f"https://assets.leaflets.schwarz/{number}.pdf"
    content = b"%PDF-1.7\n" + f"test-fixture-{number}\n".encode("ascii")
    payload = {
        "flyer": {
            "id": uuid,
            "regions": [{"code": item} for item in advertised],
            "offerStartDate": "2026-11-23",
            "offerEndDate": "2026-11-28",
            "hiResPdfUrl": document_url,
            "pages": [{"number": 1}, {"number": 2}],
        }
    }
    raw = json.dumps(payload, sort_keys=True).encode("utf-8")
    viewer = f"https://www.lidl.de/l/prospekte/{slug}/ar/{route}"
    return FlyerEvidence(
        target="next",
        flyer_identifier=slug,
        route_region=route,
        valid_from="2026-11-23",
        valid_until="2026-11-28",
        viewer_url=viewer,
        viewer_final_url=viewer,
        official_flyer_id=uuid,
        document_url=document_url,
        advertised_regions=advertised,
        pdf_sha256=sha256(content).hexdigest(),
        raw_sha256=sha256(raw).hexdigest(),
        pdf_bytes=len(content),
        raw_bytes=len(raw),
        page_count=2,
        source_pdf=content,
        source_json=raw,
    )


def sources() -> dict[tuple[str, str], FlyerEvidence]:
    return {
        (FIRST, "10"): snapshot(FIRST, "10", 1),
        (SECOND, "21"): snapshot(SECOND, "21", 2),
    }


def plan(*, review=None, evidence=None) -> dict:
    return plan_parallel_campaign_isolation(
        blocked() if review is None else review,
        store_external_id="DE06664",
        berlin_as_of="2026-11-21",
        source_evidence=sources() if evidence is None else evidence,
    )


class LidlParallelCampaignIsolationTests(unittest.TestCase):
    def assert_blocked(self, result: dict) -> None:
        self.assertEqual(result["gate_a_result"], "BLOCKED")
        self.assertEqual(result["decision"], "UNRESOLVED")
        self.assertTrue(result["review_required"])
        self.assertFalse(result["origin_attested"])
        self.assertEqual(result["planning_scope"], "SOURCE_ONLY_NO_PERSISTENCE")
        for key in (
            "product_identity_inferred", "deduplication_authorized",
            "selection_authorized", "classification_authorized",
            "collection_authorized", "gate_b_authorized",
            "corpus_write_authorized", "db_write_authorized",
            "publication_authorized", "runtime_registration_authorized",
            "write_performed", "local_write_performed",
        ):
            self.assertIs(result[key], False, key)
        self.assertFalse({"priority", "selected_flyer", "winner", "products",
                          "offers", "prices"} & set(result))
        for row in result["campaigns"]:
            self.assertIs(row["collection_authorized"], False)
            self.assertIs(row["classification_authorized"], False)
            self.assertFalse({"products", "offers", "prices", "rank", "priority",
                              "selected_flyer", "source_pdf", "source_json"} & set(row))

    def test_two_campaigns_are_isolated_and_overlapping_regions_quarantined(self) -> None:
        result = plan()
        self.assert_blocked(result)
        self.assertTrue(result["source_inputs_complete"])
        self.assertEqual(result["campaign_count"], 2)
        self.assertEqual(result["quarantined_campaign_count"], 2)
        self.assertEqual(result["conflict_pair_count"], 1)
        first, second = result["campaigns"]
        self.assertEqual(
            [(lane["flyer_identifier"], lane["route_region"])
             for lane in result["campaigns"]],
            [(FIRST, "10"), (SECOND, "21")],
        )
        self.assertNotEqual(first["campaign_namespace_sha256"],
                            second["campaign_namespace_sha256"])
        self.assertEqual(len(first["campaign_namespace_sha256"]), 64)
        self.assertEqual(first["review_state"], "QUARANTINED")
        self.assertEqual(second["review_state"], "QUARANTINED")
        self.assertEqual(first["source_state"], "VERIFIED_INPUT_SNAPSHOT")
        self.assertEqual(second["source_state"], "VERIFIED_INPUT_SNAPSHOT")
        overlap = result["conflict_quarantine"][0]
        self.assertEqual(overlap["reason_codes"],
                         ["SHARED_ADVERTISED_REGION_AND_PERIOD"])
        self.assertEqual(overlap["shared_advertised_regions"], ["7"])
        self.assertEqual(overlap["overlap_valid_from"], "2026-11-23")
        self.assertEqual(overlap["overlap_valid_until"], "2026-11-28")
        self.assertFalse(overlap["product_identity_inferred"])
        self.assertFalse(overlap["deduplication_authorized"])

    def test_order_of_source_evidence_and_hub_links_is_not_priority(self) -> None:
        original = plan()
        reverse = plan(
            review=blocked([candidate(FIRST, "10"), candidate(SECOND, "21")]),
            evidence=dict(reversed(list(sources().items()))),
        )
        self.assert_blocked(reverse)
        self.assertEqual(original, reverse)

    def test_missing_source_is_quarantined_without_fallback(self) -> None:
        evidence = sources()
        del evidence[(FIRST, "10")]
        result = plan(evidence=evidence)
        self.assert_blocked(result)
        self.assertFalse(result["source_inputs_complete"])
        self.assertEqual(result["campaigns"][0]["source_state"],
                         "MISSING_SOURCE_SNAPSHOT")
        self.assertIsNone(result["campaigns"][0]["campaign_namespace_sha256"])
        self.assertEqual(result["campaigns"][0]["quarantine_reasons"],
                         ["SOURCE_NOT_VERIFIED"])
        self.assertEqual(result["campaigns"][1]["source_state"],
                         "VERIFIED_INPUT_SNAPSHOT")
        self.assertEqual(result["campaigns"][1]["review_state"],
                         "AWAITING_PROGRAM_APPLICABILITY")
        self.assertEqual(result["conflict_pair_count"], 0)

    def test_tampered_hash_does_not_create_a_namespace_or_fallback(self) -> None:
        evidence = sources()
        evidence[(SECOND, "21")] = replace(
            evidence[(SECOND, "21")], pdf_sha256="0" * 64
        )
        result = plan(evidence=evidence)
        self.assert_blocked(result)
        self.assertEqual(result["campaigns"][1]["source_state"],
                         "REJECTED_INPUT_SNAPSHOT")
        self.assertEqual(result["campaigns"][1]["source_rejection_code"],
                         "SOURCE_HASH_MISMATCH")
        self.assertIsNone(result["campaigns"][1]["campaign_namespace_sha256"])
        self.assertEqual(result["campaigns"][1]["review_state"], "QUARANTINED")

    def test_distinct_advertised_regions_do_not_prove_applicability(self) -> None:
        evidence = {
            (FIRST, "10"): snapshot(FIRST, "10", 1, regions=("10",)),
            (SECOND, "21"): snapshot(SECOND, "21", 2, regions=("21",)),
        }
        result = plan(evidence=evidence)
        self.assert_blocked(result)
        self.assertEqual(result["conflict_pair_count"], 0)
        self.assertEqual(result["quarantined_campaign_count"], 0)
        self.assertTrue(all(
            row["review_state"] == "AWAITING_PROGRAM_APPLICABILITY"
            for row in result["campaigns"]
        ))
        self.assertFalse(result["selection_authorized"])

    def test_same_official_uuid_quarantines_both_campaigns(self) -> None:
        evidence = sources()
        first, second = evidence[(FIRST, "10")], evidence[(SECOND, "21")]
        payload = json.loads(second.source_json)
        payload["flyer"]["id"] = first.official_flyer_id
        raw = json.dumps(payload, sort_keys=True).encode("utf-8")
        evidence[(SECOND, "21")] = replace(
            second, official_flyer_id=first.official_flyer_id,
            source_json=raw, raw_sha256=sha256(raw).hexdigest(), raw_bytes=len(raw),
        )
        result = plan(evidence=evidence)
        self.assert_blocked(result)
        self.assertEqual(result["conflict_pair_count"], 1)
        self.assertIn("OFFICIAL_FLYER_UUID_COLLISION",
                      result["conflict_quarantine"][0]["reason_codes"])
        self.assertEqual(result["quarantined_campaign_count"], 2)

    def test_same_pdf_hash_is_quarantined_without_deduplication(self) -> None:
        evidence = sources()
        first, second = evidence[(FIRST, "10")], evidence[(SECOND, "21")]
        evidence[(SECOND, "21")] = replace(
            second, source_pdf=first.source_pdf,
            pdf_sha256=first.pdf_sha256, pdf_bytes=first.pdf_bytes,
        )
        result = plan(evidence=evidence)
        self.assert_blocked(result)
        self.assertIn("PDF_CONTENT_SHA256_REUSE",
                      result["conflict_quarantine"][0]["reason_codes"])
        self.assertNotEqual(result["campaigns"][0]["campaign_namespace_sha256"],
                            result["campaigns"][1]["campaign_namespace_sha256"])
        self.assertFalse(result["deduplication_authorized"])

    def test_provenance_namespace_changes_with_pdf_revision(self) -> None:
        first = plan()
        evidence = sources()
        source = evidence[(FIRST, "10")]
        updated = source.source_pdf + b"\nrevision"
        evidence[(FIRST, "10")] = replace(
            source, source_pdf=updated, pdf_sha256=sha256(updated).hexdigest(),
            pdf_bytes=len(updated),
        )
        revised = plan(evidence=evidence)
        self.assert_blocked(revised)
        self.assertNotEqual(
            first["campaigns"][0]["campaign_namespace_sha256"],
            revised["campaigns"][0]["campaign_namespace_sha256"],
        )
        self.assertEqual(
            first["campaigns"][1]["campaign_namespace_sha256"],
            revised["campaigns"][1]["campaign_namespace_sha256"],
        )

    def test_three_parallel_lanes_create_pairwise_quarantine(self) -> None:
        evidence = sources()
        evidence[(THIRD, "7")] = snapshot(THIRD, "7", 3, regions=("7", "13"))
        review = blocked([
            candidate(FIRST, "10"), candidate(SECOND, "21"), candidate(THIRD, "7")
        ])
        result = plan(review=review, evidence=evidence)
        self.assert_blocked(result)
        self.assertEqual(result["campaign_count"], 3)
        self.assertEqual(result["conflict_pair_count"], 3)
        self.assertEqual(result["quarantined_campaign_count"], 3)
        self.assertEqual(len({
            row["campaign_namespace_sha256"] for row in result["campaigns"]
        }), 3)

    def test_unexpected_extra_source_and_invalid_review_rejected(self) -> None:
        evidence = sources()
        evidence[(THIRD, "7")] = snapshot(THIRD, "7", 3)
        with self.assertRaises(IndependentCampaignSourceError):
            plan(evidence=evidence)
        review = blocked()
        review["selection_authorized"] = True
        with self.assertRaises(MultiCampaignReviewError):
            plan(review=review)
        review = blocked()
        review["truncated"] = True
        with self.assertRaises(MultiCampaignReviewError):
            plan(review=review)

    def test_swapped_source_is_quarantined_not_promoted(self) -> None:
        evidence = sources()
        evidence[(FIRST, "10")] = evidence[(SECOND, "21")]
        result = plan(evidence=evidence)
        self.assert_blocked(result)
        self.assertEqual(result["campaigns"][0]["source_state"],
                         "REJECTED_INPUT_SNAPSHOT")
        self.assertEqual(result["campaigns"][0]["source_rejection_code"],
                         "IDENTITY_MISMATCH")
        self.assertIsNone(result["campaigns"][0]["campaign_namespace_sha256"])
        self.assertEqual(result["campaigns"][1]["source_state"],
                         "VERIFIED_INPUT_SNAPSHOT")


if __name__ == "__main__":
    unittest.main()
