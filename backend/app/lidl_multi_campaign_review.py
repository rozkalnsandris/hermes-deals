"""Review-only Lidl multi-campaign classification contract.

This module never selects a flyer or grants Gate A/B or production authority.
It does not participate in the live discovery or dispatch path.
"""

from __future__ import annotations

from datetime import date
import re
from typing import Any, Mapping


class MultiCampaignReviewError(ValueError):
    """Reject incomplete or authority-expanding review input."""


_AMBIGUITY_KEYS = frozenset({
    "schema_version", "target", "decision", "review_required",
    "selection_authorized", "candidate_count", "truncated", "candidates",
})
_CANDIDATE_KEYS = frozenset({
    "flyer_identifier", "route_region", "valid_from", "valid_until",
})
_REVIEW_KEYS = frozenset({
    "schema_version", "kind", "store_external_id", "berlin_as_of", "target",
    "candidate_count", "candidates", "gate_a_result", "decision",
    "review_required", "selection_authorized", "classification_status",
})
_OBSERVATION_KEYS = frozenset({
    "flyer_identifier", "route_region", "proposed_program", "basis",
})
_SLUG = re.compile(
    r"aktionsprospekt-(\d{2})-(\d{2})-(\d{4})-(\d{2})-(\d{2})-(\d{4})-[a-z0-9]+\Z"
)
_REGION = re.compile(r"[0-9]+\Z")
_ALLOWED_PROGRAMS = frozenset({
    "UNDETERMINED", "GROCERY_LIKE", "OTHER_CAMPAIGN_LIKE",
})
_ALLOWED_BASES = frozenset({"NONE", "CONTENT_HINT_ONLY", "UNVERIFIED_API_FIELD"})


def _require(condition: bool, reason: str) -> None:
    if not condition:
        raise MultiCampaignReviewError(reason)


def _canonical_date(value: Any) -> date:
    _require(isinstance(value, str), "date must be a string")
    try:
        parsed = date.fromisoformat(value)
    except ValueError as exc:
        raise MultiCampaignReviewError("invalid date") from exc
    _require(parsed.isoformat() == value, "date must be canonical ISO-8601")
    return parsed


def prepare_multi_campaign_review(
    ambiguity: Mapping[str, Any], *, store_external_id: str, berlin_as_of: str
) -> dict[str, Any]:
    """Convert an existing BLOCKED ambiguity into a bounded human-review draft.

    The draft contains no decision interface or source-selection authority.
    """
    _require(store_external_id == "DE06664", "unsupported selected-store identity")
    as_of = _canonical_date(berlin_as_of)
    _require(isinstance(ambiguity, Mapping), "ambiguity must be a mapping")
    _require(set(ambiguity) == _AMBIGUITY_KEYS, "unexpected ambiguity fields")
    _require(type(ambiguity["schema_version"]) is int and ambiguity["schema_version"] == 1,
             "unsupported ambiguity schema")
    target = ambiguity["target"]
    _require(target in ("current", "next"), "invalid target")
    _require(ambiguity["decision"] == "UNRESOLVED", "source is not unresolved")
    _require(ambiguity["review_required"] is True, "review must remain required")
    _require(ambiguity["selection_authorized"] is False, "selection must remain forbidden")
    _require(ambiguity["truncated"] is False, "truncated candidates cannot be reviewed")
    source_rows = ambiguity["candidates"]
    _require(isinstance(source_rows, list), "candidate list is required")
    count = ambiguity["candidate_count"]
    _require(type(count) is int and 2 <= count <= 12 and len(source_rows) == count,
             "incomplete or invalid candidate count")

    rows: list[dict[str, str]] = []
    identities: set[tuple[str, str]] = set()
    for entry in source_rows:
        _require(isinstance(entry, Mapping) and set(entry) == _CANDIDATE_KEYS,
                 "invalid candidate fields")
        slug, region = entry["flyer_identifier"], entry["route_region"]
        _require(isinstance(slug, str) and isinstance(region, str),
                 "invalid candidate identity")
        matched = _SLUG.fullmatch(slug)
        _require(matched is not None and _REGION.fullmatch(region) is not None,
                 "invalid official flyer identity")
        start, end = _canonical_date(entry["valid_from"]), _canonical_date(entry["valid_until"])
        _require(start <= end, "invalid validity range")
        try:
            from_slug = date(int(matched[3]), int(matched[2]), int(matched[1]))
            until_slug = date(int(matched[6]), int(matched[5]), int(matched[4]))
        except ValueError as exc:
            raise MultiCampaignReviewError("invalid flyer slug dates") from exc
        _require((start, end) == (from_slug, until_slug), "flyer/validity mismatch")
        if target == "current":
            _require(start <= as_of <= end, "non-current candidate")
        else:
            _require(start > as_of, "non-future candidate")
        identity = (slug, region)
        _require(identity not in identities, "duplicate candidate")
        identities.add(identity)
        rows.append({key: entry[key] for key in (
            "flyer_identifier", "route_region", "valid_from", "valid_until"
        )})
    if target == "next":
        _require(len({row["valid_from"] for row in rows}) == 1,
                 "next candidates do not share the nearest start")

    rows.sort(key=lambda row: (
        row["valid_from"], row["valid_until"],
        row["flyer_identifier"], row["route_region"],
    ))
    return {
        "schema_version": 1,
        "kind": "lidl_multi_campaign_classification_review",
        "store_external_id": store_external_id,
        "berlin_as_of": as_of.isoformat(),
        "target": target,
        "candidate_count": count,
        "candidates": rows,
        "gate_a_result": "BLOCKED",
        "decision": "UNRESOLVED",
        "review_required": True,
        "selection_authorized": False,
        "classification_status": "AUTHORITATIVE_RULE_NOT_ESTABLISHED",
    }


def annotate_human_observations(
    draft: Mapping[str, Any], observations: list[Mapping[str, Any]]
) -> dict[str, Any]:
    """Attach non-authoritative reviewer impressions without resolving the gate."""
    _require(isinstance(draft, Mapping) and set(draft) == _REVIEW_KEYS,
             "unexpected draft fields")
    _require(isinstance(draft["candidates"], list), "draft candidates missing")
    try:
        original = {
            "schema_version": 1,
            "target": draft["target"],
            "decision": "UNRESOLVED",
            "review_required": True,
            "selection_authorized": False,
            "candidate_count": draft["candidate_count"],
            "truncated": False,
            "candidates": [
                {key: row[key] for key in _CANDIDATE_KEYS}
                for row in draft["candidates"]
            ],
        }
        canonical = prepare_multi_campaign_review(
            original,
            store_external_id=draft["store_external_id"],
            berlin_as_of=draft["berlin_as_of"],
        )
    except (KeyError, TypeError) as exc:
        raise MultiCampaignReviewError("invalid draft candidates") from exc
    _require(dict(draft) == canonical, "draft is not an exact unmodified BLOCKED review")
    _require(isinstance(observations, list) and len(observations) <= canonical["candidate_count"],
             "invalid human observation list")
    allowed = {(row["flyer_identifier"], row["route_region"])
               for row in canonical["candidates"]}
    seen: set[tuple[str, str]] = set()
    approved: list[dict[str, str]] = []
    for row in observations:
        _require(isinstance(row, Mapping) and set(row) == _OBSERVATION_KEYS,
                 "invalid observation fields")
        _require(all(isinstance(row[key], str) for key in _OBSERVATION_KEYS),
                 "invalid observation values")
        identity = (row["flyer_identifier"], row["route_region"])
        _require(identity in allowed and identity not in seen,
                 "unmatched or duplicate observation")
        _require(row["proposed_program"] in _ALLOWED_PROGRAMS,
                 "unsupported proposed program")
        _require(row["basis"] in _ALLOWED_BASES,
                 "unsupported observation basis")
        _require(row["proposed_program"] == "UNDETERMINED" or row["basis"] != "NONE",
                 "proposed type requires an observation basis")
        seen.add(identity)
        approved.append({key: row[key] for key in (
            "flyer_identifier", "route_region", "proposed_program", "basis"
        )})
    approved.sort(key=lambda row: (row["flyer_identifier"], row["route_region"]))
    return {
        **canonical,
        "human_observations": approved,
        "human_review_state": "ADVISORY_ONLY_NOT_APPROVED",
    }
