"""Read-only, in-memory capture of *all* official concurrent Lidl campaign sources.

No command-line entrypoint or runtime dispatch wiring. A valid capture never
selects a weekly grocery flyer or authorizes persistence, Gate A/B, or publish.
"""

from __future__ import annotations

from datetime import date
from hashlib import sha256
from ipaddress import ip_address
import json
import re
from typing import Any, Mapping
from urllib.parse import urlsplit, urlencode
from uuid import UUID

import httpx

from app.lidl_family_source_discovery import (
    FLYER_API_URL,
    HUB_URL,
    FlyerCandidate,
    FlyerEvidence,
    LidlFamilyAmbiguityError,
    LidlFamilyDiscoveryError,
    StoreBinding,
    _validate_flyer_payload,
    parse_hub_candidates,
    selected_store_cookies,
    select_current_and_next,
)
from app.lidl_independent_campaign_processing import (
    inspect_independent_campaign_sources,
)
from app.lidl_independent_campaign_review import plan_independent_campaign_reviews

_HUB_LIMIT = 2 * 1024 * 1024
_VIEWER_LIMIT = 2 * 1024 * 1024
_RAW_LIMIT = 16 * 1024 * 1024
_PDF_LIMIT = 256 * 1024 * 1024
_HOST_PATTERN = re.compile(r"[a-z0-9-]+(?:\.[a-z0-9-]+)+\Z")


class IndependentCampaignCaptureError(ValueError):
    """Reject an untrusted capture boundary or selected-store hub."""


def _require(ok: bool, reason: str) -> None:
    if not ok:
        raise IndependentCampaignCaptureError(reason)


def _trusted_https_url(url: str, allowed_hosts: frozenset[str]) -> bool:
    if not isinstance(url, str) or not 1 <= len(url) <= 4096:
        return False
    if any(ord(c) < 32 or ord(c) == 127 for c in url):
        return False
    try:
        parsed = urlsplit(url)
        return (
            parsed.scheme == "https"
            and parsed.hostname in allowed_hosts
            and parsed.username is None
            and parsed.password is None
            and parsed.port in (None, 443)
            and not parsed.fragment
            and bool(parsed.path and parsed.path.startswith("/"))
            and not parsed.path.startswith("//")
        )
    except ValueError:
        return False


def _validate_pdf_hosts(hosts: frozenset[str]) -> None:
    _require(type(hosts) is frozenset and bool(hosts), "PDF_HOST_ALLOWLIST_REQUIRED")
    for host in hosts:
        _require(
            isinstance(host, str)
            and host == host.lower()
            and _HOST_PATTERN.fullmatch(host) is not None
            and all(not label.startswith("-") and not label.endswith("-")
                    for label in host.split(".")),
            "INVALID_PDF_HOST_ALLOWLIST",
        )
        try:
            ip_address(host)
        except ValueError:
            pass
        else:
            raise IndependentCampaignCaptureError("INVALID_PDF_HOST_ALLOWLIST")


def _no_duplicate_json_keys(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for key, value in pairs:
        _require(key not in result, "API_DUPLICATE_JSON_KEY")
        result[key] = value
    return result


def _read_only_get(
    client: httpx.Client, url: str, *,
    allowed_hosts: frozenset[str],
    headers: Mapping[str, str],
    limit: int,
    params: Mapping[str, str] | None = None,
) -> bytes:
    """Exactly one bounded HTTP GET; never follow redirects or retry."""
    _require(_trusted_https_url(url, allowed_hosts), "UNTRUSTED_REQUEST_URL")
    try:
        with client.stream(
            "GET", url, params=params, headers=dict(headers),
            auth=None, follow_redirects=False,
        ) as response:
            _require(response.status_code == 200, "SOURCE_HTTP_NOT_200")
            size = 0
            parts: list[bytes] = []
            for chunk in response.iter_bytes():
                size += len(chunk)
                _require(size <= limit, "SOURCE_TOO_LARGE")
                parts.append(chunk)
            _require(size > 0, "SOURCE_EMPTY")
            return b"".join(parts)
    except httpx.HTTPError as exc:
        raise IndependentCampaignCaptureError("SOURCE_HTTP_TRANSPORT_ERROR") from exc


def _fetch_candidate(
    client: httpx.Client,
    candidate: FlyerCandidate,
    *,
    target: str,
    cookies: str,
    pdf_hosts: frozenset[str],
) -> tuple[FlyerEvidence, dict[str, Any]]:
    # The selected-store hub may decorate the same route with a query or
    # trailing slash. Bind the exact first-party path and request only its
    # canonical form; never forward hub-provided query parameters.
    canonical_viewer_url = (
        f"https://www.lidl.de/l/prospekte/{candidate.slug}/ar/{candidate.route_region}"
    )
    expected_path = urlsplit(canonical_viewer_url).path
    _require(
        _trusted_https_url(candidate.viewer_url, frozenset({"www.lidl.de"}))
        and urlsplit(candidate.viewer_url).path in (
            expected_path, expected_path + "/"
        ),
        "INVALID_VIEWER_ROUTE",
    )
    viewer_html = _read_only_get(
        client, canonical_viewer_url,
        allowed_hosts=frozenset({"www.lidl.de"}),
        headers={"Cookie": cookies, "Accept": "text/html"},
        limit=_VIEWER_LIMIT,
    )
    api_params = {
        "version": "4",
        "flyer_identifier": candidate.slug,
        "client": "lidl",
        "region_id": candidate.route_region,
    }
    raw = _read_only_get(
        client, FLYER_API_URL,
        allowed_hosts=frozenset({"endpoints.leaflets.schwarz"}),
        headers={
            "Cookie": "",
            "Accept": "application/json",
            "Origin": "https://www.lidl.de",
            "Referer": "https://www.lidl.de/",
        },
        params=api_params,
        limit=_RAW_LIMIT,
    )
    try:
        payload = json.loads(raw.decode("utf-8"),
                             object_pairs_hook=_no_duplicate_json_keys)
    except (UnicodeError, ValueError, TypeError) as exc:
        raise IndependentCampaignCaptureError("INVALID_API_JSON") from exc
    _require(isinstance(payload, dict), "INVALID_API_JSON")
    try:
        flyer, advertised, pdf_url = _validate_flyer_payload(
            payload, candidate=candidate
        )
    except (LidlFamilyDiscoveryError, ValueError, TypeError) as exc:
        raise IndependentCampaignCaptureError("API_IDENTITY_MISMATCH") from exc
    official_id = flyer.get("id")
    try:
        _require(
            isinstance(official_id, str)
            and str(UUID(official_id)) == official_id,
            "INVALID_OFFICIAL_FLYER_ID",
        )
    except (ValueError, TypeError) as exc:
        raise IndependentCampaignCaptureError("INVALID_OFFICIAL_FLYER_ID") from exc
    _require(
        isinstance(flyer.get("pages"), list) and bool(flyer["pages"])
        and bool(advertised) and len(set(advertised)) == len(advertised),
        "INVALID_OFFICIAL_FLYER_METADATA",
    )
    _require(_trusted_https_url(pdf_url, pdf_hosts), "UNTRUSTED_PDF_HOST")
    document = _read_only_get(
        client, pdf_url, allowed_hosts=pdf_hosts,
        headers={"Cookie": "", "Accept": "application/pdf"},
        limit=_PDF_LIMIT,
    )
    _require(document.startswith(b"%PDF"), "INVALID_OFFICIAL_PDF")
    evidence = FlyerEvidence(
        target=target,
        flyer_identifier=candidate.slug,
        route_region=candidate.route_region,
        valid_from=candidate.valid_from.isoformat(),
        valid_until=candidate.valid_until.isoformat(),
        viewer_url=canonical_viewer_url,
        viewer_final_url=canonical_viewer_url,
        official_flyer_id=official_id,
        document_url=pdf_url,
        advertised_regions=advertised,
        pdf_sha256=sha256(document).hexdigest(),
        raw_sha256=sha256(raw).hexdigest(),
        pdf_bytes=len(document),
        raw_bytes=len(raw),
        page_count=len(flyer["pages"]),
        source_pdf=document,
        source_json=raw,
    )
    capture = {
        "viewer_sha256": sha256(viewer_html).hexdigest(),
        "hub_viewer_url_sha256": sha256(
            candidate.viewer_url.encode("utf-8")
        ).hexdigest(),
        "viewer_request_url_sha256": sha256(
            canonical_viewer_url.encode("utf-8")
        ).hexdigest(),
        "viewer_url_normalized": candidate.viewer_url != canonical_viewer_url,
        "api_request_url_sha256": sha256(
            f"{FLYER_API_URL}?{urlencode(api_params)}".encode("utf-8")
        ).hexdigest(),
        "request_count": 3,
    }
    return evidence, capture


def capture_parallel_campaign_sources(
    client: httpx.Client,
    *,
    ambiguity: Mapping[str, Any],
    binding: StoreBinding,
    berlin_as_of: str,
    allowed_pdf_hosts: frozenset[str],
) -> tuple[dict[str, Any], dict[tuple[str, str], FlyerEvidence]]:
    """Fetch each official selected-store candidate independently, without writing.

    The caller provides a preexisting BLOCKED ambiguity and a fresh, isolated
    httpx Client. This source-only function is not connected to production
    dispatch, collection, corpus, DB, or a publisher. The PDF CDN host list
    must come from an independently reviewed trust configuration, never the
    untrusted Lidl API payload. Returned byte snapshots exist in memory only.
    """
    _require(isinstance(client, httpx.Client), "CLIENT_REQUIRED")
    _require(
        client.auth is None
        and "authorization" not in client.headers
        and "proxy-authorization" not in client.headers,
        "AUTHENTICATED_CLIENT_NOT_ALLOWED",
    )
    _require(
        isinstance(binding, StoreBinding) and binding == StoreBinding(),
        "UNSUPPORTED_SELECTED_STORE",
    )
    _validate_pdf_hosts(allowed_pdf_hosts)
    plan = plan_independent_campaign_reviews(
        ambiguity,
        store_external_id=binding.external_id,
        berlin_as_of=berlin_as_of,
    )
    cookie_header = "; ".join(
        f"{key}={value}" for key, value in
        selected_store_cookies(binding).items()
    )

    hub_html = _read_only_get(
        client, HUB_URL, allowed_hosts=frozenset({"www.lidl.de"}),
        headers={"Cookie": cookie_header, "Accept": "text/html"},
        limit=_HUB_LIMIT,
    )
    try:
        candidates = parse_hub_candidates(hub_html.decode("utf-8"))
        select_current_and_next(
            candidates, today=date.fromisoformat(plan["berlin_as_of"])
        )
    except LidlFamilyAmbiguityError as exc:
        fresh_ambiguity = exc.review
    except (UnicodeError, LidlFamilyDiscoveryError, ValueError) as exc:
        raise IndependentCampaignCaptureError("HUB_CANDIDATES_UNVERIFIED") from exc
    else:
        raise IndependentCampaignCaptureError("HUB_NOT_AMBIGUOUS")
    hub_plan = plan_independent_campaign_reviews(
        fresh_ambiguity,
        store_external_id=binding.external_id,
        berlin_as_of=berlin_as_of,
    )
    _require(plan == hub_plan, "HUB_AMBIGUITY_CHANGED")
    keyed_candidates = {(row.slug, row.route_region): row for row in candidates}

    captured: dict[tuple[str, str], FlyerEvidence] = {}
    attempts: dict[tuple[str, str], dict[str, Any]] = {}
    for lane in plan["campaigns"]:
        key = (lane["flyer_identifier"], lane["route_region"])
        candidate = keyed_candidates[key]
        try:
            evidence, details = _fetch_candidate(
                client, candidate, target=plan["target"],
                cookies=cookie_header, pdf_hosts=allowed_pdf_hosts,
            )
        except IndependentCampaignCaptureError as exc:
            attempts[key] = {
                "capture_state": "FAILED",
                "capture_failure_code": str(exc),
            }
        else:
            captured[key] = evidence
            attempts[key] = {"capture_state": "CAPTURED", **details}

    inspected = inspect_independent_campaign_sources(
        ambiguity, store_external_id=binding.external_id,
        berlin_as_of=berlin_as_of, source_evidence=captured,
    )
    for lane in inspected["campaigns"]:
        key = (lane["flyer_identifier"], lane["route_region"])
        lane.update(attempts[key])
        if lane["source_state"] == "REJECTED_INPUT_SNAPSHOT":
            captured.pop(key, None)
            lane["capture_state"] = "FAILED"
            lane["capture_failure_code"] = "INSPECTOR_REJECTED_SOURCE"
            lane.pop("request_count", None)

    # Official flyer UUIDs are not valid campaign discriminators if shared
    # by two different identities. Quarantine both; never pick a winner.
    identities_by_uuid: dict[str, list[tuple[str, str]]] = {}
    for key, source in captured.items():
        identities_by_uuid.setdefault(source.official_flyer_id, []).append(key)
    collisions = {
        identity for group in identities_by_uuid.values() if len(group) > 1
        for identity in group
    }
    for lane in inspected["campaigns"]:
        key = (lane["flyer_identifier"], lane["route_region"])
        if key in collisions:
            captured.pop(key, None)
            lane["source_state"] = "REJECTED_INPUT_SNAPSHOT"
            lane["source_provenance"] = None
            lane["source_rejection_code"] = "OFFICIAL_UUID_COLLISION"
            lane["capture_state"] = "FAILED"
            lane["capture_failure_code"] = "OFFICIAL_UUID_COLLISION"

    inspected.update({
        "capture_schema_version": 1,
        "capture_kind": "lidl_parallel_campaign_readonly_capture",
        "capture_scope": "SOURCE_ONLY_IN_MEMORY",
        "hub_raw_sha256": sha256(hub_html).hexdigest(),
        "hub_bytes": len(hub_html),
        "selected_store_context_sha256": sha256(
            cookie_header.encode("utf-8")
        ).hexdigest(),
        "source_inputs_complete": len(captured) == len(plan["campaigns"]),
        "capture_complete": len(captured) == len(plan["campaigns"]),
        "origin_attested": False,
        "local_write_performed": False,
    })
    return inspected, captured
