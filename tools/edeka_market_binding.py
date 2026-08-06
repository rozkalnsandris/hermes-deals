from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

EXPECTED_PUBLIC_MARKET_CODE = "071897"
EXPECTED_SOURCE_MARKET_ID = "587881"
EXPECTED_SCOPE = "family_primary_edeka"
EXPECTED_STRATEGY = "edeka_family_market_binding_v1"


class EdekaMarketBindingError(ValueError):
    pass


def validate_market_binding(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("schema_version") != 1:
        raise EdekaMarketBindingError("unsupported schema_version")
    if payload.get("strategy") != EXPECTED_STRATEGY:
        raise EdekaMarketBindingError("unexpected strategy")
    if payload.get("retailer") != "edeka":
        raise EdekaMarketBindingError("retailer must be edeka")
    if payload.get("public_market_code") != EXPECTED_PUBLIC_MARKET_CODE:
        raise EdekaMarketBindingError("public market code mismatch")
    if payload.get("source_market_id") != EXPECTED_SOURCE_MARKET_ID:
        raise EdekaMarketBindingError("source market id mismatch")
    if payload.get("scope") != EXPECTED_SCOPE:
        raise EdekaMarketBindingError("scope mismatch")
    required_true = (
        "source_manifest_required",
        "campaign_window_required",
        "source_sha256_required",
        "parser_identity_required",
    )
    for key in required_true:
        if payload.get(key) is not True:
            raise EdekaMarketBindingError(f"{key} must be true")
    required_false = (
        "fallback_allowed",
        "automatic_approval_enabled",
        "automatic_publish_enabled",
        "database_write_authorized",
        "production_apply_authorized",
    )
    for key in required_false:
        if payload.get(key) is not False:
            raise EdekaMarketBindingError(f"{key} must be false")
    if payload.get("ambiguous_rows_route") != "review_required":
        raise EdekaMarketBindingError("ambiguous rows must route to Review")
    return dict(payload)


def load_market_binding(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise EdekaMarketBindingError("binding must be a regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EdekaMarketBindingError("invalid binding document") from exc
    if not isinstance(payload, dict):
        raise EdekaMarketBindingError("binding root must be an object")
    return validate_market_binding(payload)
