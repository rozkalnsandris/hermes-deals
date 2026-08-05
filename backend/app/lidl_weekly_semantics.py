from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import hashlib
import json
from pathlib import PurePosixPath
from typing import Any, Iterable, Mapping, Sequence

from app.lidl_weekly_completeness_contract import (
    classify_target_scope,
    normalize_text,
    promo_or_non_product_title,
)


SEMANTIC_GATE_VERSION = "lidl-weekly-semantics-v1"
_ALLOWED_REFERENCE_SOURCES = frozenset(
    {"normalpreis", "uvp", "uvp_inline", "strikethrough"}
)


@dataclass(frozen=True)
class PriceObservation:
    role: str
    price_eur: str
    bbox: tuple[float, float, float, float]
    label: str | None = None


@dataclass(frozen=True)
class WeeklyEligibilityDecision:
    state: str
    production_ready: bool
    comparison_eligible: bool
    reasons: tuple[str, ...]
    row: dict[str, Any]


def _decimal(value: Any) -> Decimal | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError):
        return None
    return result if result > 0 else None


def _truth(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y"}


def _page(value: Any) -> int | None:
    try:
        page = int(value)
    except (TypeError, ValueError):
        return None
    return page if page > 0 else None


def _bbox(value: Sequence[float]) -> tuple[float, float, float, float]:
    if len(value) != 4:
        raise ValueError("bbox must contain four coordinates")
    x0, y0, x1, y1 = (float(entry) for entry in value)
    if not (x1 > x0 and y1 > y0):
        raise ValueError("bbox must have positive area")
    return x0, y0, x1, y1


def _center(value: Sequence[float]) -> tuple[float, float]:
    x0, y0, x1, y1 = _bbox(value)
    return (x0 + x1) / 2.0, (y0 + y1) / 2.0


def _center_inside(
    card_bbox: Sequence[float],
    observation_bbox: Sequence[float],
    *,
    margin: float = 0.0,
) -> bool:
    x0, y0, x1, y1 = _bbox(card_bbox)
    cx, cy = _center(observation_bbox)
    return (
        x0 - margin <= cx <= x1 + margin
        and y0 - margin <= cy <= y1 + margin
    )


def bind_card_prices(
    *,
    card_bbox: Sequence[float],
    observations: Iterable[PriceObservation],
    margin: float = 2.0,
) -> dict[str, str | None]:
    """Bind store, regular and app prices to one card without neighbour leakage.

    A price belongs to a card only when its own centre is inside that card.
    Explicit labels are required for regular and Lidl Plus prices. Multiple
    distinct values for one role are ambiguous and fail closed.
    """

    grouped: dict[str, list[PriceObservation]] = {
        "store": [],
        "regular": [],
        "app": [],
    }
    for observation in observations:
        if observation.role not in grouped:
            continue
        if not _center_inside(card_bbox, observation.bbox, margin=margin):
            continue
        label = normalize_text(observation.label or "")
        if observation.role == "regular" and label not in _ALLOWED_REFERENCE_SOURCES:
            continue
        if observation.role == "app" and label not in {"lidl plus", "lidl_plus"}:
            continue
        if _decimal(observation.price_eur) is None:
            continue
        grouped[observation.role].append(observation)

    result: dict[str, str | None] = {
        "price_eur": None,
        "regular_price_eur": None,
        "app_price_eur": None,
    }
    key_by_role = {
        "store": "price_eur",
        "regular": "regular_price_eur",
        "app": "app_price_eur",
    }
    for role, rows in grouped.items():
        values = sorted(
            {
                f"{_decimal(row.price_eur).quantize(Decimal('0.01')):.2f}"
                for row in rows
                if _decimal(row.price_eur) is not None
            }
        )
        if len(values) > 1:
            raise ValueError(f"ambiguous {role} price ownership")
        if values:
            result[key_by_role[role]] = values[0]
    return result


def variable_weight_fields(row: Mapping[str, Any]) -> dict[str, Any]:
    """Return lossless API-compatible unit-basis fields for a variable-weight row."""

    if str(row.get("price_basis") or "") != "variable_weight_example":
        return {
            "pricing_mode": "fixed_package",
            "unit_price_eur": None,
            "unit_label": None,
            "basis_quantity": None,
            "basis_unit": None,
            "example_price_eur": None,
            "example_weight_g": None,
            "variable_weight_complete": True,
            "variable_weight_reason": None,
        }

    raw_candidates = row.get("unit_price_candidates_eur_per_kg") or []
    if not isinstance(raw_candidates, list):
        raw_candidates = []
    candidates = sorted(
        {
            value.quantize(Decimal("0.0001"))
            for raw in raw_candidates
            if (value := _decimal(raw)) is not None
        }
    )
    example_price = _decimal(row.get("price_eur"))
    complete = len(candidates) == 1 and example_price is not None
    unit_price = candidates[0] if len(candidates) == 1 else None
    example_weight = None
    if complete and unit_price is not None and unit_price > 0:
        example_weight = (
            example_price / unit_price * Decimal("1000")
        ).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)

    reason = None
    if not complete:
        if not candidates:
            reason = "variable_weight_unit_price_missing"
        elif len(candidates) > 1:
            reason = "variable_weight_unit_price_ambiguous"
        else:
            reason = "variable_weight_example_price_missing"

    return {
        "pricing_mode": "example_total_plus_unit" if complete else None,
        "unit_price_eur": (
            f"{unit_price:.4f}" if unit_price is not None else None
        ),
        "unit_label": "kg" if unit_price is not None else None,
        "basis_quantity": "1.0000" if unit_price is not None else None,
        "basis_unit": "kg" if unit_price is not None else None,
        "example_price_eur": (
            f"{example_price.quantize(Decimal('0.01')):.2f}"
            if example_price is not None
            else None
        ),
        "example_weight_g": (
            f"{example_weight:.2f}" if example_weight is not None else None
        ),
        "variable_weight_complete": complete,
        "variable_weight_reason": reason,
    }


def _price_semantic_reasons(row: Mapping[str, Any]) -> list[str]:
    reasons: list[str] = []
    price = _decimal(row.get("price_eur"))
    regular = _decimal(row.get("regular_price_eur"))
    app_price = _decimal(row.get("app_price_eur"))
    regular_source = normalize_text(row.get("regular_price_source") or "")

    if price is None:
        reasons.append("store_price_missing")
    if regular is not None:
        if regular_source not in _ALLOWED_REFERENCE_SOURCES:
            reasons.append("reference_price_not_explicitly_owned")
        if price is not None and regular < price:
            reasons.append("reference_price_below_store_price")
    if app_price is not None:
        if price is not None and app_price >= price:
            reasons.append("app_price_not_lower_than_store_price")
        app_from = row.get("app_valid_from")
        app_until = row.get("app_valid_until")
        if bool(app_from) != bool(app_until):
            reasons.append("app_price_validity_incomplete")
    return reasons


def classify_known_false_negative(
    *,
    title: str,
    structured_category_text: str = "",
) -> dict[str, Any]:
    """Classify a historically missed title without flyer-specific promotion."""

    scope = classify_target_scope(
        title=title,
        structured_category_text=structured_category_text,
    )
    if scope == "in_scope":
        reason = "generic_scope_evidence_in_scope"
    elif scope == "excluded":
        reason = "generic_scope_evidence_excluded"
    else:
        reason = "insufficient_generic_scope_evidence_requires_review"
    return {
        "title": title,
        "scope": scope,
        "reason": reason,
        "production_ready": False,
        "review_required": True,
    }


def apply_reviewed_weekly_eligibility(
    row: Mapping[str, Any],
    *,
    target_pages: Iterable[int] | None,
    page_role_reviewed: bool,
    product_reviewed: bool = False,
) -> WeeklyEligibilityDecision:
    """Apply the final weekly physical-store gate to one frozen-parser row."""

    output = dict(row)
    parser_ready = _truth(row.get("production_ready_shadow"))
    output["parser_production_ready_shadow"] = parser_ready
    output.update(variable_weight_fields(row))

    reasons: list[str] = []
    page = _page(row.get("page"))
    target_set = {int(value) for value in (target_pages or ())}

    if not page_role_reviewed:
        reasons.append("weekly_page_role_profile_not_reviewed")
    if page is None:
        reasons.append("source_page_missing")
    elif page not in target_set:
        reasons.append("outside_reviewed_weekly_target_pages")

    channel = str(row.get("channel") or "")
    if channel != "physical_store":
        reasons.append("not_physical_store")
    if _truth(row.get("structured_online_column_signal")) or channel == "online_only":
        reasons.append("online_only")

    title = str(row.get("product_name") or "").strip()
    if not title or promo_or_non_product_title(title):
        reasons.append("product_title_missing_or_promotional")

    parser_scope = str(row.get("scope") or "")
    shared_scope = classify_target_scope(
        title=title,
        structured_category_text=row.get("structured_category_text") or "",
    )
    if parser_scope == "excluded" or shared_scope == "excluded":
        reasons.append("outside_hermes_deals_scope")
    elif parser_scope != "in_scope":
        reasons.append("parser_scope_requires_review")
    elif shared_scope == "review" and not product_reviewed:
        reasons.append("shared_scope_requires_product_review")

    if not parser_ready:
        reasons.append("frozen_parser_not_production_ready")

    reasons.extend(_price_semantic_reasons(row))

    variable = output["pricing_mode"] != "fixed_package"
    if variable and not output["variable_weight_complete"]:
        reasons.append(str(output["variable_weight_reason"]))
    if variable and not product_reviewed:
        reasons.append("variable_weight_requires_product_review")

    reasons = sorted(set(filter(None, reasons)))
    production_ready = not reasons
    comparison_eligible = production_ready and (
        output["pricing_mode"] == "fixed_package"
        or output["unit_price_eur"] is not None
    )

    output["semantic_gate_version"] = SEMANTIC_GATE_VERSION
    output["semantic_gate_reasons"] = reasons
    output["weekly_eligibility_state"] = (
        "production_ready" if production_ready else "review_required"
    )
    output["production_ready_shadow"] = production_ready
    output["comparison_eligible_shadow"] = comparison_eligible

    return WeeklyEligibilityDecision(
        state=output["weekly_eligibility_state"],
        production_ready=production_ready,
        comparison_eligible=comparison_eligible,
        reasons=tuple(reasons),
        row=output,
    )


def gate_parser_report(report: Mapping[str, Any]) -> dict[str, Any]:
    """Fail closed until an immutable reviewed weekly profile is supplied."""

    output = dict(report)
    rows = [
        apply_reviewed_weekly_eligibility(
            row,
            target_pages=(),
            page_role_reviewed=False,
            product_reviewed=False,
        ).row
        for row in (report.get("shadow_rows") or [])
        if isinstance(row, Mapping)
    ]
    output["shadow_rows"] = rows
    output["semantic_gate_version"] = SEMANTIC_GATE_VERSION
    output["semantic_gate"] = {
        "mode": "fail_closed_until_reviewed_weekly_profile",
        "parser_row_count": len(rows),
        "parser_ready_count": sum(
            _truth(row.get("parser_production_ready_shadow")) for row in rows
        ),
        "production_ready_count": 0,
        "comparison_eligible_count": 0,
        "review_profile_required": True,
        "product_review_required_for_variable_weight": True,
    }
    return output


def canonical_evidence_manifest(files: Mapping[str, bytes]) -> tuple[bytes, str]:
    """Build a deterministic, path-sorted evidence manifest."""

    normalized: dict[str, bytes] = {}
    casefolded: set[str] = set()
    for raw_path, content in files.items():
        path = PurePosixPath(str(raw_path))
        if path.is_absolute() or ".." in path.parts or str(path) in {"", "."}:
            raise ValueError(f"unsafe evidence path: {raw_path}")
        key = path.as_posix()
        folded = key.casefold()
        if key in normalized or folded in casefolded:
            raise ValueError(f"duplicate evidence path: {key}")
        if not isinstance(content, bytes):
            raise TypeError(f"evidence content must be bytes: {key}")
        normalized[key] = content
        casefolded.add(folded)

    entries = [
        {
            "path": path,
            "sha256": hashlib.sha256(normalized[path]).hexdigest(),
            "bytes": len(normalized[path]),
        }
        for path in sorted(normalized)
    ]
    payload = {
        "schema_version": 1,
        "semantic_gate_version": SEMANTIC_GATE_VERSION,
        "entries": entries,
    }
    raw = (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")
    return raw, hashlib.sha256(raw).hexdigest()
