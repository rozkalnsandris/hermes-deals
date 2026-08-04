from decimal import Decimal
from uuid import UUID

import pytest

from app.comparison_family import (
    ComparableOffer,
    ComparisonDimension,
    ComparisonFamilyDefinition,
    MINI_WATERMELON_VARIABLE_WEIGHT,
    PISTACHIOS_ROASTED_SALTED,
    WALNUT_KERNELS_NATURAL,
    compare_family_offers,
    stable_family_id,
)
from app.pricing_normalizer import PricingMode


def offer(
    offer_id: str,
    *,
    source: str,
    price: str | None,
    unit_price: str | None,
    ready: bool = True,
    signature: tuple[str | None, str | None, int | None] = (
        "500",
        "g",
        1,
    ),
    blocked_reason: str | None = None,
    linked: bool = True,
    accepted_member: bool = True,
) -> ComparableOffer:
    return ComparableOffer(
        offer_candidate_id=UUID(offer_id),
        canonical_product_id=(UUID(offer_id) if linked else None),
        source_chain=source,
        source_store_external_id=None,
        source_offer_id=f"{source}:{offer_id}",
        brand_display=None,
        package_price_eur=(
            Decimal(price) if price is not None else None
        ),
        normalized_unit_price_eur=(
            Decimal(unit_price)
            if unit_price is not None
            else None
        ),
        normalized_display_unit="kg" if ready else None,
        pricing_mode=(
            PricingMode.FIXED_PACKAGE
            if ready
            else PricingMode.UNKNOWN
        ),
        package_signature=signature,
        family_membership_accepted=accepted_member,
        pricing_ready=ready,
        blocked_reason=blocked_reason,
    )


def test_family_ids_are_deterministic():
    assert WALNUT_KERNELS_NATURAL.id == stable_family_id(
        "walnut-kernels-natural"
    )
    assert str(WALNUT_KERNELS_NATURAL.id) == (
        "dc8f2297-fbf4-548d-aa74-ed610ae61ea1"
    )
    assert str(PISTACHIOS_ROASTED_SALTED.id) == (
        "6bcad9da-24fe-576d-a0e0-de8d452b59e9"
    )
    assert str(MINI_WATERMELON_VARIABLE_WEIGHT.id) == (
        "a93721e4-9bf8-5f30-aa72-c4e7cb866a0d"
    )


def test_identity_equivalence_is_forbidden():
    with pytest.raises(ValueError):
        ComparisonFamilyDefinition(
            id=stable_family_id("invalid"),
            family_key="invalid",
            display_name="Invalid",
            normalized_name="invalid",
            variant_key=None,
            comparison_dimension=ComparisonDimension.MASS,
            basis_quantity_value=Decimal("1000"),
            basis_quantity_unit="g",
            display_unit="kg",
            status="proposed",
            identity_equivalent=True,
        )


def test_walnut_comparison_matches_b15k8_prototype():
    result = compare_family_offers(
        WALNUT_KERNELS_NATURAL,
        [
            offer(
                "044d2d7c-715e-4b6d-9df0-e396e5882711",
                source="aldi_nord",
                price="4.99",
                unit_price="9.98",
            ),
            offer(
                "a62917ef-c0cd-4a50-a5e6-5574f53cd215",
                source="lidl",
                price="5.99",
                unit_price="11.98",
            ),
        ],
    )
    assert result.identity_equivalent is False
    assert result.comparison_available is True
    assert result.lowest_normalized_unit_price_eur == Decimal("9.98")
    assert result.normalized_unit_price_spread_eur == Decimal("2.00")
    assert result.package_price_comparison_available is True


def test_pistachio_comparison_is_tie():
    result = compare_family_offers(
        PISTACHIOS_ROASTED_SALTED,
        [
            offer(
                "cce3e288-e99c-4a02-b4f0-f0c07fa9c3ea",
                source="aldi_nord",
                price="5.99",
                unit_price="11.98",
            ),
            offer(
                "928d9cd1-de9c-4c0c-8db7-bc38cba6f005",
                source="lidl",
                price="5.99",
                unit_price="11.98",
            ),
        ],
    )
    assert result.comparison_available is True
    assert result.normalized_unit_price_spread_eur == Decimal("0.00")
    assert len(result.lowest_offer_candidate_ids) == 2


def test_watermelon_is_blocked_until_netto_pricing_ready():
    result = compare_family_offers(
        MINI_WATERMELON_VARIABLE_WEIGHT,
        [
            offer(
                "bf557f7c-eb24-4dd0-a70e-c6b5d5c50307",
                source="aldi_nord",
                price=None,
                unit_price="0.99",
                signature=(None, None, None),
            ),
            offer(
                "20343288-0b6b-4d85-999e-87ddd5e66db1",
                source="netto",
                price=None,
                unit_price=None,
                ready=False,
                signature=(None, None, None),
                blocked_reason="missing_pricing_normalization",
            ),
        ],
    )
    assert result.comparison_available is False
    assert result.comparable_offer_count == 1
    assert result.blocked_offer_count == 1


def test_watermelon_after_normalization_matches_b15k8():
    result = compare_family_offers(
        MINI_WATERMELON_VARIABLE_WEIGHT,
        [
            offer(
                "bf557f7c-eb24-4dd0-a70e-c6b5d5c50307",
                source="aldi_nord",
                price=None,
                unit_price="0.99",
                signature=(None, None, None),
            ),
            offer(
                "20343288-0b6b-4d85-999e-87ddd5e66db1",
                source="netto",
                price=None,
                unit_price="1.19",
                signature=(None, None, None),
            ),
        ],
    )
    assert result.comparison_available is True
    assert result.lowest_normalized_unit_price_eur == Decimal("0.99")
    assert result.normalized_unit_price_spread_eur == Decimal("0.20")
    assert result.package_price_comparison_available is False



def test_unknown_package_signature_blocks_package_price_comparison():
    result = compare_family_offers(
        WALNUT_KERNELS_NATURAL,
        [
            offer(
                "044d2d7c-715e-4b6d-9df0-e396e5882711",
                source="aldi_nord",
                price="4.99",
                unit_price="9.98",
            ),
            offer(
                "a62917ef-c0cd-4a50-a5e6-5574f53cd215",
                source="lidl",
                price="5.99",
                unit_price="11.98",
                signature=(None, None, None),
            ),
        ],
    )
    assert result.comparison_available is True
    assert result.package_price_comparison_available is False


def test_unaccepted_family_member_is_blocked():
    result = compare_family_offers(
        WALNUT_KERNELS_NATURAL,
        [
            offer(
                "044d2d7c-715e-4b6d-9df0-e396e5882711",
                source="aldi_nord",
                price="4.99",
                unit_price="9.98",
            ),
            offer(
                "a62917ef-c0cd-4a50-a5e6-5574f53cd215",
                source="lidl",
                price="5.99",
                unit_price="11.98",
                accepted_member=False,
            ),
        ],
    )
    assert result.comparison_available is False
    assert result.comparable_offer_count == 1
    assert result.blocked_offer_count == 1


def test_unlinked_offer_is_blocked():
    result = compare_family_offers(
        WALNUT_KERNELS_NATURAL,
        [
            offer(
                "044d2d7c-715e-4b6d-9df0-e396e5882711",
                source="aldi_nord",
                price="4.99",
                unit_price="9.98",
            ),
            offer(
                "a62917ef-c0cd-4a50-a5e6-5574f53cd215",
                source="lidl",
                price="5.99",
                unit_price="11.98",
                linked=False,
            ),
        ],
    )
    assert result.comparison_available is False
    assert result.blocked_offer_count == 1
