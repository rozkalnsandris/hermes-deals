from decimal import Decimal

import pytest

from app.pricing_normalizer import (
    PRICING_NORMALIZER_VERSION,
    PricingMode,
    normalize_netto_variable_weight,
)


NETTO_LINES = [
    "Mini Wassermelone",
    "1 kg",
    "Italien / Spanien, Kl. I",
    "-20 %",
    "UVP 1.49",
    "1.19*",
]


def test_netto_variable_weight_fixture_is_accepted():
    result = normalize_netto_variable_weight(
        NETTO_LINES,
        Decimal("1.19"),
    )
    assert result.accepted is True
    assert result.pricing_mode is PricingMode.VARIABLE_WEIGHT
    assert result.advertised_price_eur == Decimal("1.1900")
    assert result.normalized_unit_price_eur == Decimal("1.1900")
    assert result.basis_quantity_value == Decimal("1")
    assert result.basis_quantity_unit == "kg"
    assert result.fixed_item_quantity_value is None
    assert result.fixed_item_quantity_unit is None
    assert result.confidence == Decimal("0.9900")
    assert (
        result.evidence["normalizer_version"]
        == PRICING_NORMALIZER_VERSION
    )


@pytest.mark.parametrize(
    "lines",
    [
        ["Walnusskerne", "500 g Beutel", "4.99"],
        ["Kartoffeln", "1 kg Beutel", "1.49"],
        ["Joghurt", "2 x 500 g", "1.99"],
        ["Mango", "Stück", "1.19"],
        ["Waschmittel", "1 kg", "4.99"],
    ],
)
def test_non_variable_weight_fixtures_are_rejected(lines):
    result = normalize_netto_variable_weight(lines, "1.19")
    assert result.accepted is False
    assert result.pricing_mode is PricingMode.UNKNOWN
    assert result.normalized_unit_price_eur is None
    assert result.fixed_item_quantity_value is None


def test_price_must_be_positive():
    with pytest.raises(ValueError):
        normalize_netto_variable_weight(NETTO_LINES, "0")



def test_country_origin_without_fresh_produce_signal_is_rejected():
    result = normalize_netto_variable_weight(
        ["Olivenöl", "1 kg", "Italien", "4.99"],
        "4.99",
    )
    assert result.accepted is False
    assert result.evidence["has_origin_context"] is True
    assert result.evidence["has_produce_context"] is False
