from __future__ import annotations

from collections import Counter
from typing import Any, Mapping, Sequence

from edeka_regional_source_manifest import validate_regional_source_manifest

EXPECTED_STRATEGY = "edeka_candidate_provenance_v1"
ALLOWED_ROUTES = {"automatic_candidate", "review_required", "excluded"}


class EdekaCandidateProvenanceError(ValueError):
    pass


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise EdekaCandidateProvenanceError(f"{label} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise EdekaCandidateProvenanceError(
            f"{label} must be a positive integer"
        ) from exc
    if parsed < 1:
        raise EdekaCandidateProvenanceError(f"{label} must be a positive integer")
    return parsed


def validate_candidate_provenance(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != 1:
        raise EdekaCandidateProvenanceError("unsupported schema_version")
    if payload.get("strategy") != EXPECTED_STRATEGY:
        raise EdekaCandidateProvenanceError("unexpected strategy")

    manifest = payload.get("manifest")
    if not isinstance(manifest, Mapping):
        raise EdekaCandidateProvenanceError("manifest must be an object")
    validated_manifest = validate_regional_source_manifest(manifest)
    if not validated_manifest["shadow_ready"]:
        raise EdekaCandidateProvenanceError("manifest is not shadow-ready")

    rows = payload.get("candidates")
    if not isinstance(rows, Sequence) or isinstance(rows, (str, bytes)):
        raise EdekaCandidateProvenanceError("candidates must be a sequence")

    seen_ids: set[str] = set()
    route_counts: Counter[str] = Counter()
    normalized_rows: list[dict[str, Any]] = []
    for raw in rows:
        if not isinstance(raw, Mapping):
            raise EdekaCandidateProvenanceError("candidate must be an object")
        candidate_id = raw.get("candidate_id")
        if not isinstance(candidate_id, str) or not candidate_id.strip():
            raise EdekaCandidateProvenanceError("candidate_id is required")
        if candidate_id in seen_ids:
            raise EdekaCandidateProvenanceError("candidate_id must be unique")
        seen_ids.add(candidate_id)

        for field in (
            "campaign_id",
            "source_sha256",
            "manifest_sha256",
            "parser_identity",
        ):
            if raw.get(field) != validated_manifest[field]:
                raise EdekaCandidateProvenanceError(
                    f"candidate {candidate_id} {field} mismatch"
                )

        page_number = _positive_int(raw.get("page_number"), "page_number")
        card_id = raw.get("card_id")
        if not isinstance(card_id, str) or not card_id.strip():
            raise EdekaCandidateProvenanceError("card_id is required")

        route = raw.get("route")
        if route not in ALLOWED_ROUTES:
            raise EdekaCandidateProvenanceError("unsupported route")
        ambiguous = raw.get("ambiguous")
        if not isinstance(ambiguous, bool):
            raise EdekaCandidateProvenanceError("ambiguous must be a boolean")
        if ambiguous and route != "review_required":
            raise EdekaCandidateProvenanceError(
                "ambiguous candidates must route to Review"
            )
        if route == "automatic_candidate" and raw.get("provenance_complete") is not True:
            raise EdekaCandidateProvenanceError(
                "automatic candidate requires complete provenance"
            )

        normalized_rows.append(
            {
                "candidate_id": candidate_id,
                "page_number": page_number,
                "card_id": card_id,
                "route": route,
                "ambiguous": ambiguous,
                "provenance_complete": raw.get("provenance_complete") is True,
            }
        )
        route_counts[route] += 1

    for key in (
        "database_write_authorized",
        "review_write_authorized",
        "automatic_approval_enabled",
        "automatic_publish_enabled",
        "production_apply_authorized",
    ):
        if payload.get(key) is not False:
            raise EdekaCandidateProvenanceError(f"{key} must be false")

    return {
        "schema_version": 1,
        "strategy": EXPECTED_STRATEGY,
        "campaign_id": validated_manifest["campaign_id"],
        "source_sha256": validated_manifest["source_sha256"],
        "manifest_sha256": validated_manifest["manifest_sha256"],
        "parser_identity": validated_manifest["parser_identity"],
        "candidate_count": len(normalized_rows),
        "route_counts": {
            route: route_counts.get(route, 0) for route in sorted(ALLOWED_ROUTES)
        },
        "all_candidates_provenance_bound": True,
        "promotion_ready": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "production_apply_authorized": False,
        "candidates": normalized_rows,
    }
