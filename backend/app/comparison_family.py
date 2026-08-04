from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal
from enum import StrEnum
from typing import Any, Iterable
from uuid import UUID, uuid5

from app.pricing_normalizer import PricingMode


COMPARISON_FAMILY_VERSION = "comparison-family-v1"
COMPARISON_FAMILY_NAMESPACE = UUID(
    "6a235f72-7f40-5e14-8ae4-216f75832765"
)


class ComparisonDimension(StrEnum):
    MASS = "mass"
    VOLUME = "volume"
    COUNT = "count"


@dataclass(frozen=True)
class ComparisonFamilyDefinition:
    id: UUID
    family_key: str
    display_name: str
    normalized_name: str
    variant_key: str | None
    comparison_dimension: ComparisonDimension
    basis_quantity_value: Decimal
    basis_quantity_unit: str
    display_unit: str
    status: str
    identity_equivalent: bool = False

    def __post_init__(self) -> None:
        if self.identity_equivalent:
            raise ValueError(
                "comparison family must not imply identity equivalence"
            )
        if not self.family_key.strip():
            raise ValueError("family_key must not be empty")
        if self.basis_quantity_value <= 0:
            raise ValueError("basis quantity must be positive")


@dataclass(frozen=True)
class ComparableOffer:
    offer_candidate_id: UUID
    canonical_product_id: UUID | None
    source_chain: str
    source_store_external_id: str | None
    source_offer_id: str
    brand_display: str | None
    package_price_eur: Decimal | None
    normalized_unit_price_eur: Decimal | None
    normalized_display_unit: str | None
    pricing_mode: PricingMode
    package_signature: tuple[str | None, str | None, int | None]
    family_membership_accepted: bool
    pricing_ready: bool
    blocked_reason: str | None = None


@dataclass(frozen=True)
class FamilyComparisonResult:
    family_id: UUID
    family_key: str
    identity_equivalent: bool
    comparison_available: bool
    comparable_offer_count: int
    blocked_offer_count: int
    lowest_normalized_unit_price_eur: Decimal | None
    normalized_unit_price_spread_eur: Decimal | None
    lowest_offer_candidate_ids: tuple[UUID, ...]
    package_price_comparison_available: bool
    offers: tuple[ComparableOffer, ...]

    def as_jsonable(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["family_id"] = str(self.family_id)
        payload["lowest_offer_candidate_ids"] = [
            str(value) for value in self.lowest_offer_candidate_ids
        ]
        for key in (
            "lowest_normalized_unit_price_eur",
            "normalized_unit_price_spread_eur",
        ):
            value = payload[key]
            if isinstance(value, Decimal):
                payload[key] = format(value, "f")
        for offer in payload["offers"]:
            offer["offer_candidate_id"] = str(
                offer["offer_candidate_id"]
            )
            if offer["canonical_product_id"] is not None:
                offer["canonical_product_id"] = str(
                    offer["canonical_product_id"]
                )
            for key in (
                "package_price_eur",
                "normalized_unit_price_eur",
            ):
                value = offer[key]
                if isinstance(value, Decimal):
                    offer[key] = format(value, "f")
            mode = offer["pricing_mode"]
            if isinstance(mode, PricingMode):
                offer["pricing_mode"] = mode.value
        return payload


def stable_family_id(family_key: str) -> UUID:
    key = family_key.strip().casefold()
    if not key:
        raise ValueError("family_key must not be empty")
    return uuid5(
        COMPARISON_FAMILY_NAMESPACE,
        f"hermes-deals:comparison-family:v1:{key}",
    )


def compare_family_offers(
    family: ComparisonFamilyDefinition,
    offers: Iterable[ComparableOffer],
) -> FamilyComparisonResult:
    all_offers = tuple(offers)
    compatible = tuple(
        offer
        for offer in all_offers
        if (
            offer.pricing_ready
            and offer.family_membership_accepted
            and offer.canonical_product_id is not None
            and offer.normalized_unit_price_eur is not None
            and offer.normalized_display_unit == family.display_unit
        )
    )
    blocked_count = len(all_offers) - len(compatible)
    comparison_available = len(compatible) >= 2

    lowest: Decimal | None = None
    spread: Decimal | None = None
    lowest_ids: tuple[UUID, ...] = ()
    if compatible:
        prices = [
            offer.normalized_unit_price_eur
            for offer in compatible
            if offer.normalized_unit_price_eur is not None
        ]
        lowest = min(prices)
        highest = max(prices)
        spread = (highest - lowest).quantize(Decimal("0.01"))
        lowest_ids = tuple(
            offer.offer_candidate_id
            for offer in compatible
            if offer.normalized_unit_price_eur == lowest
        )

    unknown_signature = (None, None, None)
    all_signatures_known = all(
        offer.package_signature != unknown_signature
        for offer in compatible
    )
    signatures = {
        offer.package_signature
        for offer in compatible
    }
    package_price_comparison_available = (
        comparison_available
        and all_signatures_known
        and len(signatures) == 1
        and all(
            offer.package_price_eur is not None
            for offer in compatible
        )
    )

    return FamilyComparisonResult(
        family_id=family.id,
        family_key=family.family_key,
        identity_equivalent=False,
        comparison_available=comparison_available,
        comparable_offer_count=len(compatible),
        blocked_offer_count=blocked_count,
        lowest_normalized_unit_price_eur=lowest,
        normalized_unit_price_spread_eur=spread,
        lowest_offer_candidate_ids=lowest_ids,
        package_price_comparison_available=(
            package_price_comparison_available
        ),
        offers=all_offers,
    )


WALNUT_KERNELS_NATURAL = ComparisonFamilyDefinition(
    id=stable_family_id("walnut-kernels-natural"),
    family_key="walnut-kernels-natural",
    display_name="Walnusskerne naturbelassen",
    normalized_name="walnusskerne",
    variant_key="natural",
    comparison_dimension=ComparisonDimension.MASS,
    basis_quantity_value=Decimal("1000"),
    basis_quantity_unit="g",
    display_unit="kg",
    status="proposed",
)

PISTACHIOS_ROASTED_SALTED = ComparisonFamilyDefinition(
    id=stable_family_id("pistachios-roasted-salted"),
    family_key="pistachios-roasted-salted",
    display_name="Pistazien geröstet und gesalzen",
    normalized_name="pistazien",
    variant_key="roasted_salted",
    comparison_dimension=ComparisonDimension.MASS,
    basis_quantity_value=Decimal("1000"),
    basis_quantity_unit="g",
    display_unit="kg",
    status="proposed",
)

MINI_WATERMELON_VARIABLE_WEIGHT = ComparisonFamilyDefinition(
    id=stable_family_id("mini-watermelon-fresh-variable-weight"),
    family_key="mini-watermelon-fresh-variable-weight",
    display_name="Mini-Wassermelone lose Ware",
    normalized_name="mini wassermelone",
    variant_key="fresh_variable_weight",
    comparison_dimension=ComparisonDimension.MASS,
    basis_quantity_value=Decimal("1000"),
    basis_quantity_unit="g",
    display_unit="kg",
    status="blocked_until_pricing_normalization",
)
