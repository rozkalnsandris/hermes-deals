from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import re
from typing import Any, Mapping, Sequence


FAMILY_PRIMARY_STORE_ID = "5659"
FAMILY_PRIMARY_SCOPE = "family_primary_netto"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
PRICE_QUANTUM = Decimal("0.01")

_TITLE_NOISE_EXACT = {
    "bis",
    "du entscheidest",
    "kracher",
    "marke",
    "marke oder netto marke",
    "netto marke",
    "video anleitung",
}
_TITLE_NOISE_PREFIXES = (
    "abgabe nur in haushaltsüblichen mengen",
    "angebot gilt nur in ausgewählten filialen",
    "aus unserer eigenen fleisch und wurst fachabteilung",
    "für die artikel auf der seite",
)
_TITLE_FRAGMENT_EXACT = {
    "versch",
    "verschiedene",
}


class Route(StrEnum):
    AUTOMATIC_CANDIDATE = "automatic_candidate"
    REVIEW_REQUIRED = "review_required"
    EXCLUDED = "excluded"


@dataclass(frozen=True)
class VisualCellDecision:
    route: Route
    selected_title: str | None
    selected_normal_price: str | None
    selected_member_price: str | None
    field_routes: dict[str, str]
    reasons: tuple[str, ...]
    promotion_ready: bool = False
    automatic_approval_enabled: bool = False
    automatic_publish_enabled: bool = False
    production_write_performed: bool = False

    def to_mapping(self) -> dict[str, Any]:
        value = asdict(self)
        value["route"] = self.route.value
        return value


def _normalize_words(value: str) -> str:
    text = value.casefold()
    text = text.replace("&", " und ")
    text = re.sub(r"[-_/]+", " ", text)
    text = re.sub(r"[^\wäöüß]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value)).strip()
    return text or None


def _require_sha(value: Any, label: str) -> str:
    text = str(value or "")
    if not SHA256_RE.fullmatch(text):
        raise ValueError(f"{label} must be 64 lowercase hexadecimal characters")
    return text


def _positive_int(value: Any, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if parsed < 1:
        raise ValueError(f"{label} must be positive")
    return parsed


def _non_negative_int(value: Any, label: str) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{label} must be an integer") from exc
    if parsed < 0:
        raise ValueError(f"{label} must not be negative")
    return parsed


def _boolean(value: Any, label: str) -> bool:
    if isinstance(value, bool):
        return value
    raise ValueError(f"{label} must be a boolean")


def _price(value: Any, label: str) -> Decimal:
    try:
        parsed = Decimal(str(value).replace(",", ".")).quantize(PRICE_QUANTUM)
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"{label} contains an invalid price: {value!r}") from exc
    if parsed <= 0:
        raise ValueError(f"{label} must be positive")
    return parsed


def _unique_prices(values: Any, label: str) -> tuple[Decimal, ...]:
    if values is None:
        return ()
    if isinstance(values, (str, int, float, Decimal)):
        raw_values: Sequence[Any] = (values,)
    elif isinstance(values, Sequence):
        raw_values = values
    else:
        raise ValueError(f"{label} must be a sequence")
    return tuple(sorted({_price(value, label) for value in raw_values}))


def _format_price(value: Decimal | None) -> str | None:
    return f"{value:.2f}" if value is not None else None


def _title_reasons(title: str | None, raw: Mapping[str, Any]) -> set[str]:
    reasons: set[str] = set()
    if title is None:
        reasons.add("title_missing")
        return reasons

    normalized = _normalize_words(title)
    if normalized in _TITLE_NOISE_EXACT:
        reasons.add("title_promotional_noise")
    if any(normalized.startswith(prefix) for prefix in _TITLE_NOISE_PREFIXES):
        reasons.add("title_promotional_or_footer_text")
    if normalized in _TITLE_FRAGMENT_EXACT:
        reasons.add("title_fragment")
    if re.search(r"(?:-|&|/)\s*$", title):
        reasons.add("title_truncated")
    if bool(raw.get("title_incomplete", False)):
        reasons.add("title_incomplete")
    if bool(raw.get("title_ownership_conflict", False)):
        reasons.add("title_ownership_conflict")
    return reasons


def evaluate_visual_cell(raw: Mapping[str, Any]) -> dict[str, Any]:
    """Evaluate one visual cell without inferring product-specific corrections.

    The policy only accepts explicit, independently typed evidence. It never
    manufactures a replacement title and never lets a member price replace a
    normal offer price. Mixed or ambiguous evidence fails closed to Review.
    """

    if str(raw.get("store_external_id") or "") != FAMILY_PRIMARY_STORE_ID:
        raise ValueError("visual cell is not bound to family-primary store 5659")
    if str(raw.get("scope") or "") != FAMILY_PRIMARY_SCOPE:
        raise ValueError("visual cell has the wrong scope")

    campaign_id = str(raw.get("campaign_id") or "").strip()
    card_id = str(raw.get("card_id") or "").strip()
    parser_identity = str(raw.get("parser_identity") or "").strip()
    if not campaign_id:
        raise ValueError("campaign_id is required")
    if not card_id:
        raise ValueError("card_id is required")
    if not parser_identity:
        raise ValueError("parser_identity is required")
    _positive_int(raw.get("page_number"), "page_number")
    _require_sha(raw.get("manifest_sha256"), "manifest_sha256")
    _require_sha(raw.get("pdf_sha256"), "pdf_sha256")

    product_scope = str(raw.get("product_scope") or "in_scope")
    if product_scope not in {"in_scope", "out_of_scope", "ambiguous"}:
        raise ValueError("product_scope must be in_scope, out_of_scope or ambiguous")

    boundary_conflict = _boolean(
        raw.get("boundary_conflict", False), "boundary_conflict"
    )
    ownership_conflict = _boolean(
        raw.get("ownership_conflict", False), "ownership_conflict"
    )
    title_ownership_conflict = _boolean(
        raw.get("title_ownership_conflict", False),
        "title_ownership_conflict",
    )
    title_incomplete = _boolean(
        raw.get("title_incomplete", False), "title_incomplete"
    )
    offer_marker_count = _non_negative_int(
        raw.get("offer_marker_count", 1), "offer_marker_count"
    )

    candidate_title = _optional_text(raw.get("candidate_title"))
    title_reasons = _title_reasons(
        candidate_title,
        {
            "title_incomplete": title_incomplete,
            "title_ownership_conflict": title_ownership_conflict,
        },
    )

    reasons: set[str] = set(title_reasons)
    if boundary_conflict:
        reasons.add("mixed_card_boundary")
    if ownership_conflict:
        reasons.add("card_ownership_conflict")
    if offer_marker_count > 1:
        reasons.add("multiple_offer_markers")
    if product_scope == "ambiguous":
        reasons.add("product_scope_ambiguous")

    normal_prices = _unique_prices(
        raw.get("normal_price_candidates"), "normal_price_candidates"
    )
    member_prices = _unique_prices(
        raw.get("member_price_candidates"), "member_price_candidates"
    )

    selected_normal: Decimal | None = None
    if len(normal_prices) == 1:
        selected_normal = normal_prices[0]
    elif len(normal_prices) > 1:
        reasons.add("ambiguous_normal_price")
    else:
        reasons.add("normal_price_missing")

    selected_member: Decimal | None = None
    if len(member_prices) == 1:
        selected_member = member_prices[0]
    elif len(member_prices) > 1:
        reasons.add("ambiguous_member_price")

    if selected_normal is None and selected_member is not None:
        reasons.add("member_price_cannot_replace_normal_price")

    card_conflict = (
        boundary_conflict
        or ownership_conflict
        or offer_marker_count > 1
    )

    title_blocked = bool(title_reasons) or card_conflict
    price_blocked = (
        selected_normal is None
        or card_conflict
        or "ambiguous_normal_price" in reasons
    )
    ownership_blocked = card_conflict

    if product_scope == "out_of_scope":
        route = Route.EXCLUDED
        selected_title = None
        selected_normal = None
        selected_member = None
        reasons.add("product_out_of_scope")
    else:
        selected_title = None if title_blocked else candidate_title
        if price_blocked:
            selected_normal = None
        route = (
            Route.REVIEW_REQUIRED
            if (
                product_scope == "ambiguous"
                or title_blocked
                or price_blocked
                or ownership_blocked
            )
            else Route.AUTOMATIC_CANDIDATE
        )

    field_routes = {
        "title": (
            Route.REVIEW_REQUIRED.value
            if title_blocked or product_scope != "in_scope"
            else Route.AUTOMATIC_CANDIDATE.value
        ),
        "price": (
            Route.REVIEW_REQUIRED.value
            if price_blocked or product_scope != "in_scope"
            else Route.AUTOMATIC_CANDIDATE.value
        ),
        "card_ownership": (
            Route.REVIEW_REQUIRED.value
            if ownership_blocked or product_scope != "in_scope"
            else Route.AUTOMATIC_CANDIDATE.value
        ),
        "brand": Route.REVIEW_REQUIRED.value,
        "package": Route.REVIEW_REQUIRED.value,
        "validity": Route.REVIEW_REQUIRED.value,
    }
    reasons.update(
        {
            "brand_independent_evidence_required",
            "package_independent_evidence_required",
            "validity_bound_campaign_review_required",
        }
    )

    decision = VisualCellDecision(
        route=route,
        selected_title=selected_title,
        selected_normal_price=_format_price(selected_normal),
        selected_member_price=_format_price(selected_member),
        field_routes=field_routes,
        reasons=tuple(sorted(reasons)),
    )
    return decision.to_mapping()
