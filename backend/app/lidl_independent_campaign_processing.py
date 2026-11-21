"""Pure offline verification of independently captured concurrent Lidl flyer sources.

Each input snapshot is inspected independently and bound to an existing
BLOCKED selected-store ambiguity. This module does not fetch, select, parse
offers, mutate storage, or grant Gate A/B and production authority.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import date
from hashlib import sha256
import json
import re
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

from app.lidl_family_source_discovery import (
    FlyerCandidate,
    FlyerEvidence,
    LidlFamilyDiscoveryError,
    _validate_flyer_payload,
    official_lidl_url,
)
from app.lidl_independent_campaign_review import plan_independent_campaign_reviews


_SHA = re.compile(r"[0-9a-f]{64}\Z")
_MAX_RAW_BYTES = 16 * 1024 * 1024
_MAX_PDF_BYTES = 256 * 1024 * 1024


class IndependentCampaignSourceError(ValueError):
    """Fail-closed untrusted input or a campaign-specific verification failure."""


def _require(condition: bool, code: str) -> None:
    if not condition:
        raise IndependentCampaignSourceError(code)


def _unique_json_pairs(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        if key in result:
            raise IndependentCampaignSourceError("INVALID_RAW_PAYLOAD")
        result[key] = value
    return result


def _safe_url(url: object, *, lidl: bool = False) -> bool:
    if not isinstance(url, str) or not url or len(url) > 4096:
        return False
    if any(ord(char) < 32 or ord(char) == 127 for char in url):
        return False
    try:
        parsed = urlsplit(url)
        host = parsed.hostname
        port = parsed.port
    except ValueError:
        return False
    return (
        parsed.scheme == "https"
        and bool(host and parsed.path)
        and parsed.username is None
        and parsed.password is None
        and port in (None, 443)
        and not parsed.fragment
        and (not lidl or official_lidl_url(url))
    )


def _verify_source(
    source: FlyerEvidence, *, lane: Mapping[str, Any], target: str, store: str
) -> dict[str, Any]:
    _require(isinstance(source, FlyerEvidence), "INVALID_SNAPSHOT_TYPE")
    identity = ("flyer_identifier", "route_region", "valid_from", "valid_until")
    _require(
        all(getattr(source, key) == lane[key] for key in identity)
        and source.target == target,
        "IDENTITY_MISMATCH",
    )
    _require(
        isinstance(source.source_json, bytes)
        and isinstance(source.source_pdf, bytes)
        and 0 < len(source.source_json) <= _MAX_RAW_BYTES
        and 0 < len(source.source_pdf) <= _MAX_PDF_BYTES
        and source.source_pdf.startswith(b"%PDF"),
        "INVALID_SOURCE_BYTES",
    )
    _require(
        type(source.raw_bytes) is int
        and type(source.pdf_bytes) is int
        and source.raw_bytes == len(source.source_json)
        and source.pdf_bytes == len(source.source_pdf)
        and isinstance(source.raw_sha256, str)
        and isinstance(source.pdf_sha256, str)
        and _SHA.fullmatch(source.raw_sha256) is not None
        and _SHA.fullmatch(source.pdf_sha256) is not None
        and sha256(source.source_json).hexdigest() == source.raw_sha256
        and sha256(source.source_pdf).hexdigest() == source.pdf_sha256,
        "SOURCE_HASH_MISMATCH",
    )
    _require(
        _safe_url(source.viewer_url, lidl=True)
        and _safe_url(source.viewer_final_url, lidl=True)
        and _safe_url(source.document_url)
        and urlsplit(source.viewer_url).path
        == f"/l/prospekte/{source.flyer_identifier}/ar/{source.route_region}",
        "UNTRUSTED_SOURCE_URL",
    )
    try:
        payload = json.loads(
            source.source_json.decode("utf-8"),
            object_pairs_hook=_unique_json_pairs,
        )
    except (ValueError, UnicodeError, TypeError) as exc:
        raise IndependentCampaignSourceError("INVALID_RAW_PAYLOAD") from exc
    _require(isinstance(payload, dict), "INVALID_RAW_PAYLOAD")
    candidate = FlyerCandidate(
        slug=lane["flyer_identifier"],
        route_region=lane["route_region"],
        valid_from=date.fromisoformat(lane["valid_from"]),
        valid_until=date.fromisoformat(lane["valid_until"]),
        viewer_url=source.viewer_url,
    )
    try:
        flyer, regions, pdf_url = _validate_flyer_payload(
            payload, candidate=candidate
        )
    except LidlFamilyDiscoveryError as exc:
        raise IndependentCampaignSourceError("SOURCE_API_MISMATCH") from exc
    _require(
        isinstance(source.advertised_regions, tuple)
        and bool(regions)
        and len(regions) == len(set(regions))
        and regions == source.advertised_regions
        and pdf_url == source.document_url,
        "SOURCE_API_MISMATCH",
    )
    _require(
        isinstance(source.official_flyer_id, str)
        and isinstance(flyer.get("id"), str)
        and flyer["id"] == source.official_flyer_id,
        "OFFICIAL_FLYER_ID_MISMATCH",
    )
    try:
        official_uuid = UUID(source.official_flyer_id)
    except (ValueError, AttributeError) as exc:
        raise IndependentCampaignSourceError("OFFICIAL_FLYER_ID_MISMATCH") from exc
    _require(
        str(official_uuid) == source.official_flyer_id,
        "OFFICIAL_FLYER_ID_MISMATCH",
    )
    pages = flyer.get("pages")
    _require(
        isinstance(pages, list)
        and type(source.page_count) is int
        and 0 < len(pages) == source.page_count,
        "PAGE_COUNT_MISMATCH",
    )
    provenance = {
        "store_external_id": store,
        "target": target,
        **{key: lane[key] for key in identity},
        "official_flyer_id": source.official_flyer_id,
        "advertised_regions": list(regions),
        "raw_sha256": source.raw_sha256,
        "pdf_sha256": source.pdf_sha256,
        "raw_bytes": source.raw_bytes,
        "pdf_bytes": source.pdf_bytes,
        "page_count": source.page_count,
        "viewer_url_sha256": sha256(source.viewer_url.encode("utf-8")).hexdigest(),
        "viewer_final_url_sha256": sha256(
            source.viewer_final_url.encode("utf-8")
        ).hexdigest(),
        "document_url_sha256": sha256(
            source.document_url.encode("utf-8")
        ).hexdigest(),
    }
    material = json.dumps(
        provenance, sort_keys=True, separators=(",", ":"), ensure_ascii=False
    ).encode("utf-8")
    return {
        **provenance,
        "provenance_sha256": sha256(material).hexdigest(),
        "origin_attested": False,
    }


def inspect_independent_campaign_sources(
    ambiguity: Mapping[str, Any],
    *,
    store_external_id: str,
    berlin_as_of: str,
    source_evidence: Mapping[tuple[str, str], FlyerEvidence],
    observations: list[Mapping[str, Any]] | None = None,
) -> dict[str, Any]:
    """Inspect *all* candidate snapshots in memory without promoting any lane.

    Source bytes must already have been captured by an independently
    authorized mechanism. Hash validation does not attest their origin.
    Invalid/missing sources stay in their own lanes, and the parent
    Gate A outcome remains BLOCKED even when every source is verified.
    """
    plan = plan_independent_campaign_reviews(
        ambiguity,
        store_external_id=store_external_id,
        berlin_as_of=berlin_as_of,
        observations=observations,
    )
    _require(isinstance(source_evidence, Mapping), "INVALID_SOURCE_SET")
    allowed = {
        (row["flyer_identifier"], row["route_region"])
        for row in plan["campaigns"]
    }
    _require(
        all(
            isinstance(key, tuple)
            and len(key) == 2
            and all(isinstance(part, str) for part in key)
            and key in allowed
            for key in source_evidence
        ),
        "UNEXPECTED_SOURCE_IDENTITY",
    )

    lanes: list[dict[str, Any]] = []
    for lane in plan["campaigns"]:
        key = (lane["flyer_identifier"], lane["route_region"])
        result = dict(lane)
        result["source_provenance"] = None
        if key not in source_evidence:
            result["source_state"] = "MISSING_SOURCE_SNAPSHOT"
        else:
            try:
                result["source_provenance"] = _verify_source(
                    source_evidence[key],
                    lane=lane,
                    target=plan["target"],
                    store=plan["store_external_id"],
                )
                result["source_state"] = "VERIFIED_INPUT_SNAPSHOT"
            except IndependentCampaignSourceError as exc:
                result["source_state"] = "REJECTED_INPUT_SNAPSHOT"
                result["source_rejection_code"] = str(exc)
        lanes.append(result)

    return {
        "schema_version": 1,
        "kind": "lidl_parallel_source_inspection",
        "store_external_id": plan["store_external_id"],
        "berlin_as_of": plan["berlin_as_of"],
        "target": plan["target"],
        "campaign_count": plan["campaign_count"],
        "campaigns": lanes,
        "source_inputs_complete": all(
            row["source_state"] == "VERIFIED_INPUT_SNAPSHOT" for row in lanes
        ),
        "planning_scope": "SOURCE_ONLY_OFFLINE",
        "gate_a_result": "BLOCKED",
        "decision": "UNRESOLVED",
        "review_required": True,
        "selection_authorized": False,
        "collection_authorized": False,
        "gate_b_authorized": False,
        "corpus_write_authorized": False,
        "db_write_authorized": False,
        "publication_authorized": False,
        "runtime_registration_authorized": False,
        "write_performed": False,
    }
