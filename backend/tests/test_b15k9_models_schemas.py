from decimal import Decimal
from uuid import uuid4

import pytest
from pydantic import ValidationError

from app.comparison_models import (
    ComparisonFamily,
    ComparisonFamilyMember,
    OfferPricingNormalization,
)
from app.comparison_schemas import (
    ComparisonBasisOut,
    ComparisonFamilyCurrentOffersOut,
    ComparisonFamilyDetailOut,
    ComparisonFamilyMemberOut,
    ComparisonFamilySummaryOut,
    ComparisonOfferOut,
)
from app.models import Base
from app.pricing_normalizer import PricingMode


def test_shadow_tables_register_on_existing_base():
    assert OfferPricingNormalization.__table__.metadata is Base.metadata
    assert ComparisonFamily.__table__.metadata is Base.metadata
    assert ComparisonFamilyMember.__table__.metadata is Base.metadata
    assert {
        "offer_pricing_normalizations",
        "comparison_families",
        "comparison_family_members",
    }.issubset(Base.metadata.tables)


def test_family_member_targets_canonical_product_not_offer():
    table = ComparisonFamilyMember.__table__
    assert "canonical_product_id" in table.c
    assert "offer_candidate_id" not in table.c
    targets = {
        foreign_key.target_fullname
        for foreign_key in table.foreign_keys
    }
    assert "canonical_products.id" in targets
    assert "comparison_families.id" in targets
    assert "offer_candidates.id" not in targets


def test_pricing_normalization_targets_offer_candidate():
    targets = {
        foreign_key.target_fullname
        for foreign_key in OfferPricingNormalization.__table__.foreign_keys
    }
    assert targets == {"offer_candidates.id"}


def test_comparison_schema_requires_false_identity_equivalence():
    family = ComparisonFamilySummaryOut(
        id=uuid4(),
        family_key="walnut-kernels-natural",
        display_name="Walnusskerne naturbelassen",
        normalized_name="walnusskerne",
        variant_key="natural",
        basis=ComparisonBasisOut(
            quantity_value=Decimal("1000"),
            quantity_unit="g",
            display_unit="kg",
        ),
        identity_equivalent=False,
    )
    assert family.identity_equivalent is False
    with pytest.raises(ValidationError):
        ComparisonFamilySummaryOut(
            id=uuid4(),
            family_key="invalid",
            display_name="Invalid",
            normalized_name="invalid",
            variant_key=None,
            basis=ComparisonBasisOut(
                quantity_value=Decimal("1000"),
                quantity_unit="g",
                display_unit="kg",
            ),
            identity_equivalent=True,
        )


def test_ready_offer_requires_normalized_price():
    with pytest.raises(ValidationError):
        ComparisonOfferOut(
            offer_candidate_id=uuid4(),
            canonical_product_id=None,
            source_chain="netto",
            source_store_external_id="5659",
            source_offer_id="fixture",
            package_price_eur=None,
            normalized_unit_price_eur=None,
            normalized_display_unit=None,
            pricing_mode=PricingMode.UNKNOWN,
            family_membership_accepted=False,
            pricing_ready=True,
        )


def test_current_offer_response_contract():
    family = ComparisonFamilySummaryOut(
        id=uuid4(),
        family_key="mini-watermelon-fresh-variable-weight",
        display_name="Mini-Wassermelone lose Ware",
        normalized_name="mini wassermelone",
        variant_key="fresh_variable_weight",
        basis=ComparisonBasisOut(
            quantity_value=Decimal("1000"),
            quantity_unit="g",
            display_unit="kg",
        ),
    )
    payload = ComparisonFamilyCurrentOffersOut(
        family=family,
        comparison_mode="normalized_unit_basis",
        identity_equivalent=False,
        comparison_available=True,
        comparable_offer_count=2,
        blocked_offer_count=0,
        lowest_normalized_unit_price_eur=Decimal("0.99"),
        normalized_unit_price_spread_eur=Decimal("0.20"),
        package_price_comparison_available=False,
        offers=[
            ComparisonOfferOut(
                offer_candidate_id=uuid4(),
                canonical_product_id=uuid4(),
                source_chain="aldi_nord",
                source_store_external_id=None,
                source_offer_id="1038886",
                package_price_eur=None,
                normalized_unit_price_eur=Decimal("0.99"),
                normalized_display_unit="kg",
                pricing_mode=PricingMode.VARIABLE_WEIGHT,
                family_membership_accepted=True,
                pricing_ready=True,
            )
        ],
    )
    assert payload.identity_equivalent is False
    assert payload.comparison_mode == "normalized_unit_basis"



def constraint_names(model):
    return {
        constraint.name
        for constraint in model.__table__.constraints
        if constraint.name is not None
    }


def test_pricing_model_has_fail_closed_constraints():
    names = constraint_names(OfferPricingNormalization)
    assert {
        "ck_offer_pricing_normalizations_advertised_price",
        "ck_offer_pricing_normalizations_basis_positive",
        "ck_offer_pricing_normalizations_basis_unit",
        "ck_offer_pricing_normalizations_fixed_quantity",
        "ck_offer_pricing_normalizations_review",
        "ck_offer_pricing_normalizations_accepted_ready",
    }.issubset(names)


def test_family_model_has_basis_compatibility_constraint():
    assert (
        "ck_comparison_families_basis_compatible"
        in constraint_names(ComparisonFamily)
    )


def test_member_model_has_method_and_exact_decision_constraints():
    names = constraint_names(ComparisonFamilyMember)
    assert "ck_comparison_family_members_method" in names
    assert "ck_comparison_family_members_decision" in names


def test_family_detail_schema_exposes_only_accepted_members():
    family = ComparisonFamilySummaryOut(
        id=uuid4(),
        family_key="walnut-kernels-natural",
        display_name="Walnusskerne naturbelassen",
        normalized_name="walnusskerne",
        variant_key="natural",
        basis=ComparisonBasisOut(
            quantity_value=Decimal("1000"),
            quantity_unit="g",
            display_unit="kg",
        ),
    )
    payload = ComparisonFamilyDetailOut(
        family=family,
        members=[
            ComparisonFamilyMemberOut(
                canonical_product_id=uuid4(),
                display_name="Walnusskerne XXL",
                brand_display="ALesto",
                relation_type="direct_peer",
                membership_review_status="accepted",
            )
        ],
    )
    assert payload.identity_equivalent is False
    assert payload.members[0].membership_review_status == "accepted"
