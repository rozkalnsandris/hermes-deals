"""Regression tests for #906 review-only multi-campaign contract."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
import unittest

from app.lidl_multi_campaign_review import (
    MultiCampaignReviewError,
    annotate_human_observations,
    prepare_multi_campaign_review,
)
from app.lidl_family_source_discovery import (
    FlyerCandidate,
    LidlFamilyAmbiguityError,
    select_current_and_next,
)


PERIOD = (date(2026, 11, 23), date(2026, 11, 28))


def fixture_rows() -> list[FlyerCandidate]:
    return [
        FlyerCandidate(
            slug=f"aktionsprospekt-23-11-2026-28-11-2026-{tail}",
            route_region=region,
            valid_from=PERIOD[0],
            valid_until=PERIOD[1],
            viewer_url=f"https://www.lidl.de/l/prospekte/{tail}/ar/{region}",
        )
        for tail, region in (("cde58d", "21"), ("36518f", "10"))
    ]


def blocked_review(rows: list[FlyerCandidate] | None = None) -> dict:
    with unittest.TestCase().assertRaises(LidlFamilyAmbiguityError) as context:
        select_current_and_next(rows or fixture_rows(), today=date(2026, 11, 21))
    return context.exception.review


def prepared() -> dict:
    return prepare_multi_campaign_review(
        blocked_review(), store_external_id="DE06664", berlin_as_of="2026-11-21"
    )


class LidlMultiCampaignReviewTests(unittest.TestCase):
    def test_exact_two_candidate_case_stays_blocked_in_canonical_order(self) -> None:
        output = prepared()
        self.assertEqual(output["gate_a_result"], "BLOCKED")
        self.assertEqual(output["decision"], "UNRESOLVED")
        self.assertTrue(output["review_required"])
        self.assertIs(output["selection_authorized"], False)
        self.assertEqual(output["classification_status"], "AUTHORITATIVE_RULE_NOT_ESTABLISHED")
        self.assertEqual(output["candidate_count"], 2)
        self.assertEqual([row["flyer_identifier"][-6:] for row in output["candidates"]],
                         ["36518f", "cde58d"])
        self.assertEqual([row["route_region"] for row in output["candidates"]], ["10", "21"])
        self.assertEqual({row["valid_from"] for row in output["candidates"]}, {"2026-11-23"})
        self.assertTrue(all(set(row) == {
            "flyer_identifier", "route_region", "valid_from", "valid_until",
        } for row in output["candidates"]))
        self.assertNotIn("selected_flyer", output)
        self.assertEqual(output, prepare_multi_campaign_review(
            blocked_review(list(reversed(fixture_rows()))),
            store_external_id="DE06664", berlin_as_of="2026-11-21",
        ))

    def test_review_annotations_remain_advisory_regardless_of_proposed_type(self) -> None:
        draft = prepared()
        rows = [
            {
                "flyer_identifier": row["flyer_identifier"],
                "route_region": row["route_region"],
                "proposed_program": proposal,
                "basis": "CONTENT_HINT_ONLY",
            }
            for row, proposal in zip(draft["candidates"],
                                     ("OTHER_CAMPAIGN_LIKE", "GROCERY_LIKE"))
        ]
        annotated = annotate_human_observations(draft, list(reversed(rows)))
        self.assertEqual(annotated["gate_a_result"], "BLOCKED")
        self.assertEqual(annotated["decision"], "UNRESOLVED")
        self.assertFalse(annotated["selection_authorized"])
        self.assertEqual(annotated["human_review_state"], "ADVISORY_ONLY_NOT_APPROVED")
        self.assertEqual(annotated["human_observations"], rows)
        self.assertEqual(draft, prepared())
        self.assertNotIn("selected_flyer", annotated)

    def test_incomplete_or_absent_review_remains_blocked(self) -> None:
        draft = prepared()
        for obs in ([], [{
            "flyer_identifier": draft["candidates"][1]["flyer_identifier"],
            "route_region": "21",
            "proposed_program": "UNDETERMINED",
            "basis": "NONE",
        }]):
            annotated = annotate_human_observations(draft, obs)
            self.assertEqual(annotated["gate_a_result"], "BLOCKED")
            self.assertFalse(annotated["selection_authorized"])

    def test_reject_trust_boundary_or_candidate_injection(self) -> None:
        base = blocked_review()
        variants = []
        for key, value in (("selection_authorized", True), ("decision", "APPROVED"),
                           ("review_required", False), ("truncated", True),
                           ("candidate_count", 3)):
            row = deepcopy(base)
            row[key] = value
            variants.append(row)
        extra = deepcopy(base)
        extra["selected_flyer"] = extra["candidates"][0]["flyer_identifier"]
        variants.append(extra)
        duplicate = deepcopy(base)
        duplicate["candidates"][1] = duplicate["candidates"][0]
        variants.append(duplicate)
        mismatched = deepcopy(base)
        mismatched["candidates"][0]["valid_until"] = "2026-11-29"
        variants.append(mismatched)
        for variant in variants:
            with self.subTest(variant=variant):
                with self.assertRaises(MultiCampaignReviewError):
                    prepare_multi_campaign_review(
                        variant, store_external_id="DE06664", berlin_as_of="2026-11-21"
                    )
        with self.assertRaises(MultiCampaignReviewError):
            prepare_multi_campaign_review(base, store_external_id="DE00000",
                                          berlin_as_of="2026-11-21")

    def test_reject_untrusted_or_duplicate_human_observations(self) -> None:
        draft = prepared()
        candidate = draft["candidates"][0]
        valid = {
            "flyer_identifier": candidate["flyer_identifier"],
            "route_region": candidate["route_region"],
            "proposed_program": "GROCERY_LIKE",
            "basis": "CONTENT_HINT_ONLY",
        }
        examples = []
        for k, v in (("proposed_program", "APPROVED"),
                     ("basis", "AUTHORITATIVE"), ("route_region", "7")):
            invalid = dict(valid)
            invalid[k] = v
            examples.append([invalid])
        examples.extend([[valid, valid], [{**valid, "selection_authorized": True}],
                         [{**valid, "basis": "NONE"}]])
        for observations in examples:
            with self.subTest(observations=observations):
                with self.assertRaises(MultiCampaignReviewError):
                    annotate_human_observations(draft, observations)
        poisoned = dict(draft, selection_authorized=True)
        with self.assertRaises(MultiCampaignReviewError):
            annotate_human_observations(poisoned, [valid])
        poisoned = dict(draft)
        poisoned["selection_authorized"] = True
        with self.assertRaises(MultiCampaignReviewError):
            annotate_human_observations(poisoned, [valid])

    def test_current_ambiguity_reuses_contract_without_selecting(self) -> None:
        current = [
            FlyerCandidate(
                slug=f"aktionsprospekt-16-11-2026-21-11-2026-{tail}",
                route_region=region,
                valid_from=date(2026, 11, 16),
                valid_until=date(2026, 11, 21),
                viewer_url=f"https://www.lidl.de/l/prospekte/{tail}/ar/{region}",
            ) for tail, region in (("a23456", "7"), ("b23456", "21"))
        ]
        with self.assertRaises(LidlFamilyAmbiguityError) as context:
            select_current_and_next(current, today=date(2026, 11, 21))
        review = prepare_multi_campaign_review(
            context.exception.review, store_external_id="DE06664", berlin_as_of="2026-11-21"
        )
        self.assertEqual(review["target"], "current")
        self.assertEqual(review["gate_a_result"], "BLOCKED")
        self.assertFalse(review["selection_authorized"])


if __name__ == "__main__":
    unittest.main()
