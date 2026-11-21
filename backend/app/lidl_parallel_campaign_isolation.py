"""Pure source-only Lidl campaign isolation and conflict quarantine (#906).

This does not parse offers, infer product identity, select a flyer, deduplicate,
write files, call the network, or modify Gate A/B / production.
"""

from __future__ import annotations

from datetime import date
from hashlib import sha256
import json
from typing import Any, Mapping

from app.lidl_family_source_discovery import FlyerEvidence
from app.lidl_independent_campaign_processing import (
    inspect_independent_campaign_sources,
)


class ParallelCampaignIsolationError(ValueError):
    """Reject an impossible or colliding provenance namespace."""


def _digest(material: Mapping[str, Any]) -> str:
    serialized = json.dumps(
        material, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return sha256(serialized).hexdigest()


def plan_parallel_campaign_isolation(
    ambiguity: Mapping[str, Any],
    *,
    store_external_id: str,
    berlin_as_of: str,
    source_evidence: Mapping[tuple[str, str], FlyerEvidence],
) -> dict[str, Any]:
    """Build isolated, non-publishable source lanes and review-only conflicts.

    Raw source evidence is independently validated using the existing inspector.
    A namespace binds to the exact source revision; it is a digest, not a
    filesystem or DB namespace. Shared advertised regions and overlapping
    dates are *review hints*, not store or product identity proof.
    """
    inspected = inspect_independent_campaign_sources(
        ambiguity,
        store_external_id=store_external_id,
        berlin_as_of=berlin_as_of,
        source_evidence=source_evidence,
    )

    campaigns: list[dict[str, Any]] = []
    seen_namespaces: set[str] = set()
    for row in inspected["campaigns"]:
        proof = row["source_provenance"]
        namespace: str | None = None
        reasons: list[str] = []
        if proof is None:
            reasons.append("SOURCE_NOT_VERIFIED")
        else:
            namespace = _digest({
                "schema_version": 1,
                "store_external_id": inspected["store_external_id"],
                "target": inspected["target"],
                "flyer_identifier": row["flyer_identifier"],
                "route_region": row["route_region"],
                "valid_from": row["valid_from"],
                "valid_until": row["valid_until"],
                "official_flyer_id": proof["official_flyer_id"],
                "source_provenance_sha256": proof["provenance_sha256"],
            })
            if namespace in seen_namespaces:
                raise ParallelCampaignIsolationError("NAMESPACE_COLLISION")
            seen_namespaces.add(namespace)

        campaigns.append({
            "flyer_identifier": row["flyer_identifier"],
            "route_region": row["route_region"],
            "valid_from": row["valid_from"],
            "valid_until": row["valid_until"],
            "source_state": row["source_state"],
            "source_rejection_code": row.get("source_rejection_code"),
            "campaign_namespace_sha256": namespace,
            "source_provenance_sha256": (
                proof["provenance_sha256"] if proof is not None else None
            ),
            "official_flyer_id": (
                proof["official_flyer_id"] if proof is not None else None
            ),
            "advertised_regions": (
                list(proof["advertised_regions"]) if proof is not None else []
            ),
            "raw_sha256": proof["raw_sha256"] if proof is not None else None,
            "pdf_sha256": proof["pdf_sha256"] if proof is not None else None,
            "quarantine_reasons": reasons,
            "classification_authorized": False,
            "collection_authorized": False,
        })

    conflicts: list[dict[str, Any]] = []
    for index, left in enumerate(campaigns):
        if left["campaign_namespace_sha256"] is None:
            continue
        for right in campaigns[index + 1:]:
            if right["campaign_namespace_sha256"] is None:
                continue
            overlap_start = max(left["valid_from"], right["valid_from"])
            overlap_end = min(left["valid_until"], right["valid_until"])
            shared_regions = sorted(
                set(left["advertised_regions"]) & set(right["advertised_regions"])
            )
            reasons = []
            if overlap_start <= overlap_end and shared_regions:
                reasons.append("SHARED_ADVERTISED_REGION_AND_PERIOD")
            if left["official_flyer_id"] == right["official_flyer_id"]:
                reasons.append("OFFICIAL_FLYER_UUID_COLLISION")
            if left["pdf_sha256"] == right["pdf_sha256"]:
                reasons.append("PDF_CONTENT_SHA256_REUSE")
            if not reasons:
                continue
            for campaign in (left, right):
                campaign["quarantine_reasons"].extend(reasons)
            conflicts.append({
                "left_campaign_namespace_sha256": left["campaign_namespace_sha256"],
                "right_campaign_namespace_sha256": right["campaign_namespace_sha256"],
                "reason_codes": reasons,
                "shared_advertised_regions": (
                    shared_regions if overlap_start <= overlap_end else []
                ),
                "overlap_valid_from": (
                    overlap_start if overlap_start <= overlap_end else None
                ),
                "overlap_valid_until": (
                    overlap_end if overlap_start <= overlap_end else None
                ),
                "product_identity_inferred": False,
                "deduplication_authorized": False,
            })

    for lane in campaigns:
        lane["quarantine_reasons"] = sorted(set(lane["quarantine_reasons"]))
        lane["review_state"] = (
            "QUARANTINED" if lane["quarantine_reasons"]
            else "AWAITING_PROGRAM_APPLICABILITY"
        )

    return {
        "schema_version": 1,
        "kind": "lidl_independent_campaign_isolation",
        "planning_scope": "SOURCE_ONLY_NO_PERSISTENCE",
        "store_external_id": inspected["store_external_id"],
        "berlin_as_of": inspected["berlin_as_of"],
        "target": inspected["target"],
        "campaign_count": inspected["campaign_count"],
        "source_inputs_complete": inspected["source_inputs_complete"],
        "campaigns": campaigns,
        "conflict_quarantine": conflicts,
        "quarantined_campaign_count": sum(
            row["review_state"] == "QUARANTINED" for row in campaigns
        ),
        "conflict_pair_count": len(conflicts),
        "product_identity_inferred": False,
        "deduplication_authorized": False,
        "origin_attested": False,
        "gate_a_result": "BLOCKED",
        "decision": "UNRESOLVED",
        "review_required": True,
        "selection_authorized": False,
        "classification_authorized": False,
        "collection_authorized": False,
        "gate_b_authorized": False,
        "corpus_write_authorized": False,
        "db_write_authorized": False,
        "publication_authorized": False,
        "runtime_registration_authorized": False,
        "write_performed": False,
        "local_write_performed": False,
    }
