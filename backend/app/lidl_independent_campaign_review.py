"""Pure, source-only independent review lanes for concurrent Lidl campaigns.

This planner does not fetch, collect, select, ingest, publish or authorize
individual flyers. Each lane is independently reviewable; the whole set
remains BLOCKED until a separately approved source authority exists.
"""

from __future__ import annotations

from typing import Any, Mapping

from app.lidl_multi_campaign_review import (
    annotate_human_observations,
    prepare_multi_campaign_review,
)


def plan_independent_campaign_reviews(
    ambiguity: Mapping[str, Any],
    *,
    store_external_id: str,
    berlin_as_of: str,
    observations: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Make an isolated human-review lane for *every* ambiguous official flyer.

    A lane contains an identity-bound advisory observation, never a priority,
    approved program, source-processing instruction or selected target.
    Inputs are validated by the existing #1200 fail-closed review contract.
    """
    draft = prepare_multi_campaign_review(
        ambiguity, store_external_id=store_external_id, berlin_as_of=berlin_as_of
    )
    annotated = annotate_human_observations(
        draft, [] if observations is None else observations
    )
    by_identity = {
        (row["flyer_identifier"], row["route_region"]): row
        for row in annotated["human_observations"]
    }

    campaigns: list[dict[str, Any]] = []
    for candidate in draft["candidates"]:
        identity = (candidate["flyer_identifier"], candidate["route_region"])
        observation = by_identity.get(identity)
        campaigns.append(
            {
                "flyer_identifier": candidate["flyer_identifier"],
                "route_region": candidate["route_region"],
                "valid_from": candidate["valid_from"],
                "valid_until": candidate["valid_until"],
                "review_state": (
                    "ADVISORY_OBSERVATION_RECORDED"
                    if observation is not None
                    else "AWAITING_HUMAN_REVIEW"
                ),
                "proposed_program": (
                    observation["proposed_program"]
                    if observation is not None
                    else "UNDETERMINED"
                ),
                "observation_basis": (
                    observation["basis"] if observation is not None else "NONE"
                ),
                "classification_authorized": False,
                "collection_authorized": False,
            }
        )

    return {
        "schema_version": 1,
        "kind": "lidl_independent_campaign_review_plan",
        "store_external_id": draft["store_external_id"],
        "berlin_as_of": draft["berlin_as_of"],
        "target": draft["target"],
        "campaign_count": len(campaigns),
        "campaigns": campaigns,
        "planning_scope": "SOURCE_ONLY_ADVISORY",
        "gate_a_result": "BLOCKED",
        "decision": "UNRESOLVED",
        "review_required": True,
        "selection_authorized": False,
        "collection_authorized": False,
        "gate_b_authorized": False,
        "corpus_write_authorized": False,
        "production_publish_authorized": False,
    }
