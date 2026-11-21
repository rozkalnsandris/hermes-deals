"""Regression tests for independent, non-selecting Lidl campaign review #906."""

from __future__ import annotations

from copy import deepcopy
from datetime import date
import unittest

from app.lidl_family_source_discovery import (
    FlyerCandidate,
    LidlFamilyAmbiguityError,
    select_current_and_next,
)
from app.lidl_independent_campaign_review import plan_independent_campaign_reviews
from app.lidl_multi_campaign_review import MultiCampaignReviewError


FIRST = "aktionsprospekt-23-11-2026-28-11-2026-36518f"
SECOND = "aktionsprospekt-23-11-2026-28-11-2026-cde58d"


def candidate(slug: str, region: str, start: date, end: date) -> FlyerCandidate:
    return FlyerCandidate(
        slug=slug,
        route_region=region,
        valid_from=start,
        valid_until=end,
        viewer_url=f"https://www.lidl.de/l/prospekte/{slug}/ar/{region}",
    )


def November_candidates() -> list[FlyerCandidate]:
    return [
        candidate(SECOND, "21", date(2026, 11, 23), date(2026, 11, 28)),
        candidate(FIRST, "10", date(2026, 11, 23), date(2026, 11, 28)),
    ]


def ambiguous(rows: list[FlyerCandidate] | None = None, *, today: date | None = None) -> dict:
    try:
        select_current_and_next(
            November_candidates() if rows is None else rows,
            today=date(2026, 11, 21) if today is None else today,
        )
    except LidlFamilyAmbiguityError as exc:
        return exc.review
    raise AssertionError("fixture must raise ambiguous selected-store candidates")


def planned(source: dict | None = None, *, observations: list[dict] | None = None) -> dict:
    return plan_independent_campaign_reviews(
        ambiguous() if source is None else source,
        store_external_id="DE06664",
        berlin_as_of="2026-11-21",
        observations=observations,
    )


def observation(plan: dict, index: int, program: str, basis: str) -> dict:
    lane = plan["campaigns"][index]
    return {
        "flyer_identifier": lane["flyer_identifier"],
        "route_region": lane["route_region"],
        "proposed_program": program,
        "basis": basis,
    }


class IndependentLidlCampaignReviewTest(unittest.TestCase):
    def test_official_parallel_campaigns_have_two_distinct_unranked_lanes(self) -> None:
        plan = planned()
        self.assertEqual(plan["kind"], "lidl_independent_campaign_review_plan")
        self.assertEqual(plan["store_external_id"], "DE06664")
        self.assertEqual(plan["target"], "next")
        self.assertEqual(plan["campaign_count"], 2)
        self.assertEqual(
            [(lane["flyer_identifier"], lane["route_region"]) for lane in plan["campaigns"]],
            [(FIRST, "10"), (SECOND, "21")],
        )
        for lane in plan["campaigns"]:
            self.assertEqual(lane["valid_from"], "2026-11-23")
            self.assertEqual(lane["valid_until"], "2026-11-28")
            self.assertEqual(lane["review_state"], "AWAITING_HUMAN_REVIEW")
            self.assertEqual(lane["proposed_program"], "UNDETERMINED")
            self.assertEqual(lane["observation_basis"], "NONE")
            self.assertIs(lane["classification_authorized"], False)
            self.assertIs(lane["collection_authorized"], False)
            self.assertFalse({"priority", "rank", "selected", "viewer_url", "pdf_url"} & set(lane))
        self.assertEqual(plan["gate_a_result"], "BLOCKED")
        self.assertEqual(plan["decision"], "UNRESOLVED")
        self.assertIs(plan["selection_authorized"], False)
        self.assertTrue(plan["review_required"])
        for key in ("collection_authorized", "gate_b_authorized", "corpus_write_authorized",
                    "production_publish_authorized"):
            self.assertIs(plan[key], False)
        self.assertNotIn("selected_flyer", plan)

    def test_hub_link_order_never_creates_priority(self) -> None:
        original = planned()
        reverse = planned(ambiguous(list(reversed(November_candidates()))))
        self.assertEqual(original, reverse)
        self.assertEqual(original["campaigns"][0]["flyer_identifier"], FIRST)

    def test_partial_manual_review_is_isolated_and_does_not_select(self) -> None:
        source = ambiguous()
        untouched = deepcopy(source)
        baseline = planned(source)
        annotation = observation(baseline, 1, "GROCERY_LIKE", "CONTENT_HINT_ONLY")
        notes = [annotation]
        result = planned(source, observations=notes)
        self.assertEqual(source, untouched)
        self.assertEqual(notes, [annotation])
        self.assertEqual(result["campaigns"][0], baseline["campaigns"][0])
        self.assertEqual(result["campaigns"][1]["review_state"],
                         "ADVISORY_OBSERVATION_RECORDED")
        self.assertEqual(result["campaigns"][1]["proposed_program"], "GROCERY_LIKE")
        self.assertEqual(result["campaigns"][1]["observation_basis"], "CONTENT_HINT_ONLY")
        self.assertEqual(result["gate_a_result"], "BLOCKED")
        self.assertFalse(result["selection_authorized"])

    def test_both_independent_observations_cannot_authorize_selection(self) -> None:
        base = planned()
        left = observation(base, 0, "OTHER_CAMPAIGN_LIKE", "CONTENT_HINT_ONLY")
        right = observation(base, 1, "GROCERY_LIKE", "CONTENT_HINT_ONLY")
        a = planned(observations=[left, right])
        b = planned(observations=[right, left])
        self.assertEqual(a, b)
        self.assertEqual([x["review_state"] for x in a["campaigns"]],
                         ["ADVISORY_OBSERVATION_RECORDED"] * 2)
        self.assertEqual(a["decision"], "UNRESOLVED")
        self.assertEqual(a["gate_a_result"], "BLOCKED")
        self.assertFalse(a["selection_authorized"])
        self.assertFalse(a["gate_b_authorized"])
        self.assertFalse(a["production_publish_authorized"])

    def test_three_parallel_official_candidates_all_remain_separate(self) -> None:
        rows = November_candidates() + [
            candidate("aktionsprospekt-23-11-2026-28-11-2026-abc123",
                      "7", date(2026, 11, 23), date(2026, 11, 28))
        ]
        result = planned(ambiguous(rows))
        self.assertEqual(result["campaign_count"], 3)
        self.assertEqual(len(result["campaigns"]), 3)
        self.assertEqual(result["gate_a_result"], "BLOCKED")
        self.assertFalse(result["selection_authorized"])

    def test_truncated_mismatched_and_authority_injections_fail_closed(self) -> None:
        source = ambiguous()
        for field, value in (("truncated", True),
                             ("candidate_count", 1),
                             ("decision", "APPROVED"),
                             ("selection_authorized", True)):
            row = deepcopy(source)
            row[field] = value
            with self.subTest(field=field):
                with self.assertRaises(MultiCampaignReviewError):
                    planned(row)
        invalid = deepcopy(source)
        invalid["candidates"][0]["priority"] = 1
        with self.assertRaises(MultiCampaignReviewError):
            planned(invalid)
        duplicate = deepcopy(source)
        duplicate["candidates"][1] = duplicate["candidates"][0]
        with self.assertRaises(MultiCampaignReviewError):
            planned(duplicate)
        with self.assertRaises(MultiCampaignReviewError):
            plan_independent_campaign_reviews(
                source, store_external_id="DE00000", berlin_as_of="2026-11-21"
            )

    def test_untrusted_observations_cannot_promote_a_lane(self) -> None:
        base = planned()
        valid = observation(base, 0, "UNDETERMINED", "NONE")
        cases = [
            [{**valid, "proposed_program": "APPROVED"}],
            [{**valid, "basis": "AUTHORITATIVE"}],
            [{**valid, "selection_authorized": True}],
            [{**valid, "route_region": "7"}],
            [valid, valid],
            [{**valid, "proposed_program": "GROCERY_LIKE"}],
        ]
        for rows in cases:
            with self.subTest(rows=rows):
                with self.assertRaises(MultiCampaignReviewError):
                    planned(observations=rows)
        self.assertEqual(planned(observations=[valid])["gate_a_result"], "BLOCKED")

    def test_current_period_ambiguity_stays_blocked(self) -> None:
        rows = [
            candidate(f"aktionsprospekt-16-11-2026-21-11-2026-{tail}", region,
                      date(2026, 11, 16), date(2026, 11, 21))
            for tail, region in (("aaaaaa", "7"), ("bbbbbb", "21"))
        ]
        plan = plan_independent_campaign_reviews(
            ambiguous(rows, today=date(2026, 11, 21)),
            store_external_id="DE06664",
            berlin_as_of="2026-11-21",
        )
        self.assertEqual(plan["target"], "current")
        self.assertEqual(plan["campaign_count"], 2)
        self.assertEqual(plan["gate_a_result"], "BLOCKED")
        self.assertFalse(plan["selection_authorized"])


if __name__ == "__main__":
    unittest.main()
