from __future__ import annotations

from datetime import date
import re
from typing import Any, Mapping
from urllib.parse import urlparse

from edeka_market_binding import (
    EXPECTED_PUBLIC_MARKET_CODE,
    EXPECTED_SCOPE,
    EXPECTED_SOURCE_MARKET_ID,
)

EXPECTED_STRATEGY = "edeka_regional_source_manifest_v1"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PARSER_IDENTITY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{2,127}$")


class EdekaRegionalSourceManifestError(ValueError):
    pass


def _iso_date(value: Any, label: str) -> date:
    if not isinstance(value, str):
        raise EdekaRegionalSourceManifestError(f"{label} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise EdekaRegionalSourceManifestError(f"{label} must be an ISO date") from exc


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str) or not SHA256_RE.fullmatch(value):
        raise EdekaRegionalSourceManifestError(
            f"{label} must be 64 lowercase hexadecimal characters"
        )
    return value


def _official_https_url(value: Any) -> str:
    if not isinstance(value, str):
        raise EdekaRegionalSourceManifestError("source_url must be a string")
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.hostname:
        raise EdekaRegionalSourceManifestError("source_url must use HTTPS")
    hostname = parsed.hostname.casefold()
    if hostname != "edeka.de" and not hostname.endswith(".edeka.de"):
        raise EdekaRegionalSourceManifestError(
            "source_url must be hosted on an official edeka.de domain"
        )
    if parsed.username or parsed.password or parsed.fragment:
        raise EdekaRegionalSourceManifestError("source_url contains forbidden components")
    return value


def validate_regional_source_manifest(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != 1:
        raise EdekaRegionalSourceManifestError("unsupported schema_version")
    if payload.get("strategy") != EXPECTED_STRATEGY:
        raise EdekaRegionalSourceManifestError("unexpected strategy")
    if payload.get("retailer") != "edeka":
        raise EdekaRegionalSourceManifestError("retailer must be edeka")
    if payload.get("public_market_code") != EXPECTED_PUBLIC_MARKET_CODE:
        raise EdekaRegionalSourceManifestError("public market code mismatch")
    if payload.get("source_market_id") != EXPECTED_SOURCE_MARKET_ID:
        raise EdekaRegionalSourceManifestError("source market id mismatch")
    if payload.get("scope") != EXPECTED_SCOPE:
        raise EdekaRegionalSourceManifestError("scope mismatch")

    campaign_id = payload.get("campaign_id")
    if not isinstance(campaign_id, str) or not campaign_id.strip():
        raise EdekaRegionalSourceManifestError("campaign_id is required")
    valid_from = _iso_date(payload.get("valid_from"), "valid_from")
    valid_to = _iso_date(payload.get("valid_to"), "valid_to")
    if valid_to < valid_from:
        raise EdekaRegionalSourceManifestError("campaign window is inverted")
    if (valid_to - valid_from).days > 31:
        raise EdekaRegionalSourceManifestError("campaign window is unexpectedly broad")

    _official_https_url(payload.get("source_url"))
    _sha256(payload.get("source_sha256"), "source_sha256")
    _sha256(payload.get("manifest_sha256"), "manifest_sha256")

    parser_identity = payload.get("parser_identity")
    if not isinstance(parser_identity, str) or not PARSER_IDENTITY_RE.fullmatch(
        parser_identity
    ):
        raise EdekaRegionalSourceManifestError("invalid parser_identity")

    source_state = payload.get("source_state")
    allowed_states = {
        "available",
        "not_published_yet",
        "source_unavailable",
        "evidence_mismatch",
        "parser_failed",
        "review_pending",
    }
    if source_state not in allowed_states:
        raise EdekaRegionalSourceManifestError("unsupported source_state")

    if payload.get("fallback_allowed") is not False:
        raise EdekaRegionalSourceManifestError("fallback must remain forbidden")
    if payload.get("ambiguous_rows_route") != "review_required":
        raise EdekaRegionalSourceManifestError("ambiguous rows must route to Review")
    for key in (
        "database_write_authorized",
        "review_write_authorized",
        "automatic_approval_enabled",
        "automatic_publish_enabled",
        "production_apply_authorized",
    ):
        if payload.get(key) is not False:
            raise EdekaRegionalSourceManifestError(f"{key} must be false")

    result = dict(payload)
    result["campaign_window_days"] = (valid_to - valid_from).days + 1
    result["shadow_ready"] = source_state in {"available", "review_pending"}
    return result
