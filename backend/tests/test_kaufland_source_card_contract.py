from dataclasses import replace
from decimal import Decimal

import pytest

from app.kaufland_source_card_contract import (
    EXPLICIT_FAMILY_BINDING,
    EXPLICIT_ROLE_BASIS,
    K2_PARSER_INPUT_CONTRACT_VERSION,
    SOURCE_ARTIFACT_ROLE,
    KauflandSourceCardContractError,
    PriceEvidence,
    build_source_card_receipt,
    verify_source_card_receipt,
)

SHA_A = "a" * 64
SHA_B = "b" * 64
SHA_C = "c" * 64
SHA_D = "d" * 64
SHA_E = "e" * 64
SHA_F = "f" * 64
SHA_1 = "1" * 64
SHA_2 = "2" * 64
SHA_3 = "3" * 64
SHA_4 = "4" * 64
SHA_5 = "5" * 64
SHA_6 = "6" * 64


def _price(
    role: str,
    amount: str,
    *,
    role_locator: str,
    value_locator: str,
    role_sha: str,
    value_sha: str,
) -> PriceEvidence:
    return PriceEvidence(
        role=role,
        amount=amount,
        role_locator=role_locator,
        value_locator=value_locator,
        role_evidence_sha256=role_sha,
        value_evidence_sha256=value_sha,
        owner_card_locator="dompath:offers/card[17]",
        owner_card_fragment_sha256=SHA_C,
        owner_match_count=1,
        role_assignment_basis=EXPLICIT_ROLE_BASIS,
    )


def _prices() -> tuple[PriceEvidence, ...]:
    return (
        _price(
            "promo",
            "1.99",
            role_locator="dompath:offers/card[17]/price[promo]/label",
            value_locator="dompath:offers/card[17]/price[promo]/value",
            role_sha=SHA_D,
            value_sha=SHA_E,
        ),
        _price(
            "reference",
            "2.79",
            role_locator="dompath:offers/card[17]/price[reference]/label",
            value_locator="dompath:offers/card[17]/price[reference]/value",
            role_sha=SHA_F,
            value_sha=SHA_1,
        ),
        _price(
            "xtra",
            "1.49",
            role_locator="dompath:offers/card[17]/price[xtra]/label",
            value_locator="dompath:offers/card[17]/price[xtra]/value",
            role_sha=SHA_2,
            value_sha=SHA_3,
        ),
    )


def _receipt(**overrides):
    values = {
        "k2_bundle_identity_sha256": SHA_A,
        "k2_git_revision": "c451fb9027e87b62685557ad3c2c66701e912d57",
        "k2_parser_input_contract_version": K2_PARSER_INPUT_CONTRACT_VERSION,
        "store_id": "1503",
        "family_relation": "current_main",
        "family_source_identifier": "DE_de_KDZ1_1503_D33",
        "family_identity_sha256": SHA_B,
        "family_binding_locator": "dompath:offers/card[17]/validity",
        "family_binding_evidence_sha256": SHA_4,
        "family_binding_owner_card_locator": "dompath:offers/card[17]",
        "family_binding_owner_card_fragment_sha256": SHA_C,
        "family_binding_owner_match_count": 1,
        "family_binding_method": EXPLICIT_FAMILY_BINDING,
        "source_artifact_role": SOURCE_ARTIFACT_ROLE,
        "source_artifact_sha256": SHA_5,
        "source_artifact_byte_count": 123456,
        "source_artifact_content_type": "text/html; charset=utf-8",
        "card_locator": "dompath:offers/card[17]",
        "card_fragment_sha256": SHA_C,
        "card_owner_match_count": 1,
        "price_evidence": _prices(),
    }
    values.update(overrides)
    return build_source_card_receipt(**values)


def _assert_code(code: str, func) -> None:
    with pytest.raises(KauflandSourceCardContractError) as exc_info:
        func()
    assert exc_info.value.code == code


def test_semantically_identical_evidence_order_has_same_identity():
    first = _receipt()
    second = _receipt(price_evidence=tuple(reversed(_prices())))

    assert first == second
    assert first.receipt_identity_sha256 == second.receipt_identity_sha256
    assert [item.role for item in first.price_evidence] == ["promo", "reference", "xtra"]
    verify_source_card_receipt(first)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("k2_bundle_identity_sha256", SHA_6),
        ("k2_git_revision", "0" * 40),
        ("family_identity_sha256", SHA_6),
        ("family_binding_evidence_sha256", SHA_6),
        ("source_artifact_sha256", SHA_6),
        ("source_artifact_byte_count", 123457),
    ],
)
def test_identity_changes_when_immutable_evidence_binding_changes(field, value):
    baseline = _receipt()
    changed = _receipt(**{field: value})

    assert changed.receipt_identity_sha256 != baseline.receipt_identity_sha256


def test_identity_changes_when_card_anchor_changes_with_consistent_ownership_binding():
    baseline = _receipt()
    changed_locator = "dompath:offers/card[18]"
    changed_fragment_sha = SHA_6
    prices = tuple(
        replace(
            item,
            owner_card_locator=changed_locator,
            owner_card_fragment_sha256=changed_fragment_sha,
        )
        for item in _prices()
    )

    changed = _receipt(
        card_locator=changed_locator,
        card_fragment_sha256=changed_fragment_sha,
        family_binding_owner_card_locator=changed_locator,
        family_binding_owner_card_fragment_sha256=changed_fragment_sha,
        price_evidence=prices,
    )

    assert changed.receipt_identity_sha256 != baseline.receipt_identity_sha256


def test_identity_changes_when_explicit_price_role_evidence_changes():
    baseline = _receipt()
    prices = list(_prices())
    prices[0] = replace(prices[0], value_evidence_sha256=SHA_6)

    changed = _receipt(price_evidence=prices)

    assert changed.receipt_identity_sha256 != baseline.receipt_identity_sha256


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("store_id", "9999", "STORE_BINDING_MISMATCH"),
        ("k2_parser_input_contract_version", "kaufland-k2-v2", "UPSTREAM_CONTRACT_MISMATCH"),
        ("source_artifact_role", "store-page", "WRONG_SOURCE_ARTIFACT_ROLE"),
        ("source_artifact_content_type", "application/pdf", "WRONG_SOURCE_CONTENT_TYPE"),
        ("source_artifact_byte_count", 0, "INVALID_ARTIFACT_BYTE_COUNT"),
        ("card_owner_match_count", 0, "AMBIGUOUS_CARD_OWNERSHIP"),
        ("card_owner_match_count", 2, "AMBIGUOUS_CARD_OWNERSHIP"),
        ("family_binding_owner_match_count", 2, "AMBIGUOUS_FAMILY_OWNERSHIP"),
        ("family_binding_method", "page_context_inference", "FAMILY_BINDING_NOT_EXPLICIT"),
    ],
)
def test_exact_upstream_and_single_card_ownership_gates(field, value, code):
    _assert_code(code, lambda: _receipt(**{field: value}))


def test_family_binding_evidence_must_belong_to_exact_same_card():
    _assert_code(
        "FAMILY_EVIDENCE_OUTSIDE_CARD",
        lambda: _receipt(
            family_binding_owner_card_locator="dompath:offers/card[18]",
        ),
    )


def test_price_evidence_must_belong_to_exact_same_card():
    prices = list(_prices())
    prices[0] = replace(prices[0], owner_card_locator="dompath:offers/card[18]")

    _assert_code("PRICE_EVIDENCE_OUTSIDE_CARD", lambda: _receipt(price_evidence=prices))


def test_price_evidence_owner_must_be_unique():
    prices = list(_prices())
    prices[0] = replace(prices[0], owner_match_count=2)

    _assert_code("AMBIGUOUS_PRICE_OWNERSHIP", lambda: _receipt(price_evidence=prices))


def test_duplicate_price_role_fails_closed_even_if_values_differ():
    prices = _prices() + (
        _price(
            "promo",
            "1.89",
            role_locator="dompath:offers/card[17]/price[promo2]/label",
            value_locator="dompath:offers/card[17]/price[promo2]/value",
            role_sha=SHA_5,
            value_sha=SHA_6,
        ),
    )

    _assert_code("DUPLICATE_PRICE_ROLE", lambda: _receipt(price_evidence=prices))


def test_one_evidence_locator_cannot_satisfy_promo_and_xtra_roles():
    prices = list(_prices())
    prices[2] = replace(prices[2], role_locator=prices[0].role_locator)

    _assert_code("PRICE_EVIDENCE_CROSS_BOUND", lambda: _receipt(price_evidence=prices))


def test_one_evidence_fragment_cannot_satisfy_reference_and_xtra_roles():
    prices = list(_prices())
    prices[2] = replace(prices[2], value_evidence_sha256=prices[1].value_evidence_sha256)

    _assert_code("PRICE_EVIDENCE_CROSS_BOUND", lambda: _receipt(price_evidence=prices))


def test_reference_role_cannot_be_inferred_from_numeric_order():
    prices = list(_prices())
    prices[1] = replace(prices[1], role_assignment_basis="larger_number_is_reference")

    _assert_code("PRICE_ROLE_NOT_EXPLICIT", lambda: _receipt(price_evidence=prices))


@pytest.mark.parametrize("amount", [1.99, 199, True, "1,99", "01.99", "0.00", "-1.00", "1.999"])
def test_price_amount_requires_positive_canonical_decimal_evidence(amount):
    prices = list(_prices())
    prices[0] = replace(prices[0], amount=amount)

    _assert_code("INVALID_PRICE_AMOUNT", lambda: _receipt(price_evidence=prices))


def test_decimal_input_canonicalizes_without_float_semantics():
    prices = list(_prices())
    prices[0] = replace(prices[0], amount=Decimal("1.90"))

    receipt = _receipt(price_evidence=prices)

    assert receipt.price_evidence[0].amount == "1.90"


def test_receipt_identity_verification_detects_tampering():
    receipt = _receipt()
    tampered = replace(receipt, receipt_identity_sha256=SHA_6)

    _assert_code("RECEIPT_IDENTITY_MISMATCH", lambda: verify_source_card_receipt(tampered))


def test_synthetic_fixture_proves_contract_mechanics_not_kaufland_semantics():
    # This fixture is deliberately synthetic. A passing contract test cannot
    # establish that real retained Kaufland HTML has these locators, roles or
    # card ownership. That proof belongs to the separate offline K2 receipt gate.
    receipt = _receipt()

    assert receipt.source_artifact_role == "offer-overview"
    assert {item.role for item in receipt.price_evidence} == {"promo", "reference", "xtra"}
