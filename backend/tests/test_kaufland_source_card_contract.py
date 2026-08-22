from dataclasses import fields, replace
from decimal import Decimal

import pytest

from app.kaufland_source_card_contract import (
    CONTRACT_VERSION,
    EXPLICIT_FAMILY_BINDING,
    EXPLICIT_ROLE_BASIS,
    FAMILY_ASSOCIATION_BOUND,
    FAMILY_ASSOCIATION_UNBOUND,
    K2_PARSER_INPUT_CONTRACT_VERSION,
    SOURCE_ARTIFACT_ROLE,
    UNBOUND_FAMILY_REASONS,
    KauflandSourceCardContractError,
    PriceEvidence,
    build_bound_family_association,
    build_source_card_semantic_receipt,
    build_unbound_family_association,
    verify_family_association,
    verify_source_card_semantic_receipt,
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
    card_locator: str = "rawpath:/html/body/main/offers/card[17]",
    card_sha: str = SHA_C,
) -> PriceEvidence:
    return PriceEvidence(
        role=role,
        amount=amount,
        role_locator=role_locator,
        value_locator=value_locator,
        role_evidence_sha256=role_sha,
        value_evidence_sha256=value_sha,
        owner_card_locator=card_locator,
        owner_card_fragment_sha256=card_sha,
        owner_match_count=1,
        role_assignment_basis=EXPLICIT_ROLE_BASIS,
    )


def _prices() -> tuple[PriceEvidence, ...]:
    return (
        _price(
            "promo",
            "1.99",
            role_locator="rawpath:card[17]/price[promo]/label",
            value_locator="rawpath:card[17]/price[promo]/value",
            role_sha=SHA_D,
            value_sha=SHA_E,
        ),
        _price(
            "reference",
            "2.79",
            role_locator="rawpath:card[17]/price[reference]/label",
            value_locator="rawpath:card[17]/price[reference]/value",
            role_sha=SHA_F,
            value_sha=SHA_1,
        ),
        _price(
            "xtra",
            "1.49",
            role_locator="rawpath:card[17]/price[xtra]/label",
            value_locator="rawpath:card[17]/price[xtra]/value",
            role_sha=SHA_2,
            value_sha=SHA_3,
        ),
    )


def _semantic(**overrides):
    values = {
        "k2_bundle_identity_sha256": SHA_A,
        "k2_git_revision": "c451fb9027e87b62685557ad3c2c66701e912d57",
        "k2_parser_input_contract_version": K2_PARSER_INPUT_CONTRACT_VERSION,
        "store_id": "1503",
        "source_artifact_role": SOURCE_ARTIFACT_ROLE,
        "source_artifact_sha256": SHA_5,
        "source_artifact_byte_count": 4_440_080,
        "source_artifact_content_type": "text/html; charset=UTF-8",
        "card_locator": "rawpath:/html/body/main/offers/card[17]",
        "card_fragment_sha256": SHA_C,
        "card_owner_match_count": 1,
        "price_evidence": _prices(),
    }
    values.update(overrides)
    return build_source_card_semantic_receipt(**values)


def _bound(semantic=None, **overrides):
    semantic = semantic or _semantic()
    values = {
        "semantic_receipt": semantic,
        "family_relation": "current_main",
        "family_source_identifier": "DE_de_KDZ1_1503_D33",
        "family_identity_sha256": "a9baae4b5f702f59cbc3d9eba98eb12bdd31d91aaac5e49e2ac83ecb7fbb1db1",
        "family_binding_locator": "rawpath:card[17]/campaign",
        "family_binding_evidence_sha256": SHA_4,
        "family_binding_owner_card_locator": semantic.card_locator,
        "family_binding_owner_card_fragment_sha256": semantic.card_fragment_sha256,
        "family_binding_owner_match_count": 1,
        "family_binding_method": EXPLICIT_FAMILY_BINDING,
    }
    values.update(overrides)
    return build_bound_family_association(**values)


def _unbound(reason="FAMILY_BINDING_MISSING", semantic=None):
    semantic = semantic or _semantic()
    return build_unbound_family_association(
        semantic_receipt=semantic,
        blocker_reason=reason,
    )


def _assert_code(code: str, func) -> None:
    with pytest.raises(KauflandSourceCardContractError) as exc_info:
        func()
    assert exc_info.value.code == code


def test_contract_is_versioned_successor():
    assert CONTRACT_VERSION == "kaufland-k3-source-card-v2"


def test_semantic_receipt_has_no_family_or_validity_fields():
    names = {item.name for item in fields(type(_semantic()))}
    assert not {
        "family_relation",
        "family_source_identifier",
        "family_identity_sha256",
        "family_binding_locator",
        "valid_from",
        "valid_to",
        "active",
        "preview",
        "current",
    } & names


def test_semantically_identical_price_order_has_same_identity():
    first = _semantic()
    second = _semantic(price_evidence=tuple(reversed(_prices())))

    assert first == second
    assert [item.role for item in first.price_evidence] == ["promo", "reference", "xtra"]
    verify_source_card_semantic_receipt(first)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("k2_bundle_identity_sha256", SHA_6),
        ("k2_git_revision", "0" * 40),
        ("source_artifact_sha256", SHA_6),
        ("source_artifact_byte_count", 4_440_081),
    ],
)
def test_semantic_identity_changes_when_source_binding_changes(field, value):
    baseline = _semantic()
    changed = _semantic(**{field: value})
    assert changed.receipt_identity_sha256 != baseline.receipt_identity_sha256


def test_semantic_identity_changes_when_card_anchor_changes():
    baseline = _semantic()
    card_locator = "rawpath:/html/body/main/offers/card[18]"
    prices = tuple(
        replace(
            item,
            owner_card_locator=card_locator,
            owner_card_fragment_sha256=SHA_6,
        )
        for item in _prices()
    )
    changed = _semantic(
        card_locator=card_locator,
        card_fragment_sha256=SHA_6,
        price_evidence=prices,
    )
    assert changed.receipt_identity_sha256 != baseline.receipt_identity_sha256


def test_semantic_identity_changes_when_price_evidence_changes():
    prices = list(_prices())
    prices[0] = replace(prices[0], value_evidence_sha256=SHA_6)
    assert _semantic(price_evidence=prices).receipt_identity_sha256 != _semantic().receipt_identity_sha256


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
    ],
)
def test_semantic_exact_source_and_ownership_gates(field, value, code):
    _assert_code(code, lambda: _semantic(**{field: value}))


def test_price_evidence_must_belong_to_exact_same_card():
    prices = list(_prices())
    prices[0] = replace(
        prices[0],
        owner_card_locator="rawpath:/html/body/main/offers/card[18]",
    )
    _assert_code("PRICE_EVIDENCE_OUTSIDE_CARD", lambda: _semantic(price_evidence=prices))


def test_price_evidence_owner_must_be_unique():
    prices = list(_prices())
    prices[0] = replace(prices[0], owner_match_count=1099)
    _assert_code("AMBIGUOUS_PRICE_OWNERSHIP", lambda: _semantic(price_evidence=prices))


def test_duplicate_price_role_fails_closed():
    prices = _prices() + (
        _price(
            "promo",
            "1.89",
            role_locator="rawpath:card[17]/price[promo2]/label",
            value_locator="rawpath:card[17]/price[promo2]/value",
            role_sha=SHA_5,
            value_sha=SHA_6,
        ),
    )
    _assert_code("DUPLICATE_PRICE_ROLE", lambda: _semantic(price_evidence=prices))


def test_one_locator_cannot_satisfy_promo_and_xtra():
    prices = list(_prices())
    prices[2] = replace(prices[2], role_locator=prices[0].role_locator)
    _assert_code("PRICE_EVIDENCE_CROSS_BOUND", lambda: _semantic(price_evidence=prices))


def test_one_fragment_cannot_satisfy_reference_and_xtra():
    prices = list(_prices())
    prices[2] = replace(prices[2], value_evidence_sha256=prices[1].value_evidence_sha256)
    _assert_code("PRICE_EVIDENCE_CROSS_BOUND", lambda: _semantic(price_evidence=prices))


def test_reference_cannot_be_inferred_from_numeric_order():
    prices = list(_prices())
    prices[1] = replace(prices[1], role_assignment_basis="larger_number_is_reference")
    _assert_code("PRICE_ROLE_NOT_EXPLICIT", lambda: _semantic(price_evidence=prices))


@pytest.mark.parametrize("amount", [1.99, 199, True, "1,99", "01.99", "0.00", "-1.00", "1.999"])
def test_price_amount_requires_positive_canonical_decimal(amount):
    prices = list(_prices())
    prices[0] = replace(prices[0], amount=amount)
    _assert_code("INVALID_PRICE_AMOUNT", lambda: _semantic(price_evidence=prices))


def test_decimal_amount_canonicalizes_without_float():
    prices = list(_prices())
    prices[0] = replace(prices[0], amount=Decimal("1.90"))
    assert _semantic(price_evidence=prices).price_evidence[0].amount == "1.90"


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 1),
        ("contract_version", "kaufland-k3-source-card-v1"),
        ("receipt_type", "family_association"),
    ],
)
def test_semantic_verifier_rejects_header_tampering(field, value):
    receipt = _semantic()
    _assert_code(
        "RECEIPT_CONTRACT_MISMATCH",
        lambda: verify_source_card_semantic_receipt(replace(receipt, **{field: value})),
    )


def test_semantic_verifier_rejects_identity_tampering():
    receipt = _semantic()
    _assert_code(
        "RECEIPT_IDENTITY_MISMATCH",
        lambda: verify_source_card_semantic_receipt(
            replace(receipt, receipt_identity_sha256=SHA_6)
        ),
    )


def test_semantic_receipt_is_valid_without_family_association():
    receipt = _semantic()
    verify_source_card_semantic_receipt(receipt)
    assert receipt.price_evidence
    assert receipt.receipt_type == "source_card_semantics"


def test_bound_family_association_binds_same_semantic_card():
    semantic = _semantic()
    association = _bound(semantic)
    verify_family_association(association, semantic_receipt=semantic)

    assert association.status == FAMILY_ASSOCIATION_BOUND
    assert association.is_bound is True
    assert association.blocker_reason is None
    assert association.family_relation == "current_main"


@pytest.mark.parametrize(
    ("field", "value", "code"),
    [
        ("family_relation", "weekly_default", "UNSUPPORTED_FAMILY_RELATION"),
        ("family_binding_owner_match_count", 0, "AMBIGUOUS_FAMILY_OWNERSHIP"),
        ("family_binding_owner_match_count", 2, "AMBIGUOUS_FAMILY_OWNERSHIP"),
        ("family_binding_method", "page_context_inference", "FAMILY_BINDING_NOT_EXPLICIT"),
    ],
)
def test_bound_family_association_is_explicit_and_unique(field, value, code):
    _assert_code(code, lambda: _bound(**{field: value}))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("family_source_identifier", "DE_de_KDZ1_1503_D34"),
        ("family_identity_sha256", SHA_B),
    ],
)
def test_bound_family_requires_exact_accepted_relation_identity_tuple(field, value):
    _assert_code("FAMILY_IDENTITY_MISMATCH", lambda: _bound(**{field: value}))


def test_bound_family_evidence_must_belong_to_same_card():
    _assert_code(
        "FAMILY_EVIDENCE_OUTSIDE_CARD",
        lambda: _bound(
            family_binding_owner_card_locator="rawpath:/html/body/main/offers/card[18]",
        ),
    )


def test_bound_family_identity_changes_with_family_evidence():
    semantic = _semantic()
    baseline = _bound(semantic)
    changed = _bound(semantic, family_binding_evidence_sha256=SHA_6)
    assert baseline.association_identity_sha256 != changed.association_identity_sha256


@pytest.mark.parametrize("reason", UNBOUND_FAMILY_REASONS)
def test_unbound_family_is_first_class_and_has_stable_reason(reason):
    semantic = _semantic()
    association = _unbound(reason, semantic)

    verify_family_association(association, semantic_receipt=semantic)
    assert association.status == FAMILY_ASSOCIATION_UNBOUND
    assert association.is_bound is False
    assert association.blocker_reason == reason


def test_unbound_family_contains_no_family_or_validity_semantics():
    association = _unbound()

    assert association.family_relation is None
    assert association.family_source_identifier is None
    assert association.family_identity_sha256 is None
    assert association.family_binding_locator is None
    assert association.family_binding_evidence_sha256 is None
    assert association.family_binding_owner_card_locator is None
    assert association.family_binding_owner_card_fragment_sha256 is None
    assert association.family_binding_owner_match_count is None
    assert association.family_binding_method is None

    names = {item.name for item in fields(type(association))}
    assert not {"valid_from", "valid_to", "active", "preview", "current"} & names


def test_unbound_family_rejects_unknown_reason():
    _assert_code(
        "INVALID_UNBOUND_FAMILY_REASON",
        lambda: _unbound("DEFAULT_TO_CURRENT_MAIN"),
    )


def test_unbound_identity_changes_with_blocker_reason():
    semantic = _semantic()
    missing = _unbound("FAMILY_BINDING_MISSING", semantic)
    ambiguous = _unbound("FAMILY_BINDING_AMBIGUOUS", semantic)
    assert missing.association_identity_sha256 != ambiguous.association_identity_sha256


def test_family_association_rejects_different_semantic_receipt():
    semantic = _semantic()
    association = _unbound(semantic=semantic)
    other_prices = list(_prices())
    other_prices[0] = replace(other_prices[0], value_evidence_sha256=SHA_6)
    other = _semantic(price_evidence=other_prices)

    _assert_code(
        "FAMILY_ASSOCIATION_SOURCE_CARD_MISMATCH",
        lambda: verify_family_association(association, semantic_receipt=other),
    )


def test_unbound_verifier_rejects_family_semantics_injected_after_build():
    semantic = _semantic()
    association = _unbound(semantic=semantic)
    tampered = replace(
        association,
        family_relation="current_main",
    )
    _assert_code(
        "UNBOUND_FAMILY_CARRIES_SEMANTICS",
        lambda: verify_family_association(tampered, semantic_receipt=semantic),
    )


def test_bound_verifier_rejects_blocker_injected_after_build():
    semantic = _semantic()
    association = _bound(semantic)
    tampered = replace(association, blocker_reason="FAMILY_BINDING_MISSING")
    _assert_code(
        "BOUND_FAMILY_HAS_BLOCKER",
        lambda: verify_family_association(tampered, semantic_receipt=semantic),
    )


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("schema_version", 1),
        ("contract_version", "kaufland-k3-source-card-v1"),
        ("receipt_type", "source_card_semantics"),
    ],
)
def test_family_verifier_rejects_header_tampering(field, value):
    semantic = _semantic()
    association = _unbound(semantic=semantic)
    _assert_code(
        "FAMILY_ASSOCIATION_CONTRACT_MISMATCH",
        lambda: verify_family_association(
            replace(association, **{field: value}),
            semantic_receipt=semantic,
        ),
    )


def test_family_verifier_rejects_identity_tampering():
    semantic = _semantic()
    association = _unbound(semantic=semantic)
    _assert_code(
        "FAMILY_ASSOCIATION_IDENTITY_MISMATCH",
        lambda: verify_family_association(
            replace(association, association_identity_sha256=SHA_6),
            semantic_receipt=semantic,
        ),
    )


def test_synthetic_fixture_proves_contract_mechanics_not_retailer_semantics():
    semantic = _semantic()
    unbound = _unbound(semantic=semantic)

    assert {item.role for item in semantic.price_evidence} == {"promo", "reference", "xtra"}
    assert unbound.status == "UNBOUND"
    # Synthetic locators/amounts do not prove retained Kaufland HTML semantics.
    # A later separately authorized offline derivation must produce real receipts.
