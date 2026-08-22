from __future__ import annotations

import hashlib
import json
import re
from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from typing import Iterable

SCHEMA_VERSION = 2
CONTRACT_VERSION = "kaufland-k3-source-card-v2"
K2_PARSER_INPUT_CONTRACT_VERSION = "kaufland-k2-v1"
STORE_ID = "1503"
SOURCE_ARTIFACT_ROLE = "offer-overview"
EXPLICIT_ROLE_BASIS = "explicit_source_role_evidence"
EXPLICIT_FAMILY_BINDING = "explicit_card_local_source_evidence"

PRICE_ROLES = ("promo", "reference", "xtra")
FAMILY_RELATIONS = (
    "current_main",
    "current_short",
    "preview_main",
    "preview_overlap",
)
ACCEPTED_FAMILIES = {
    "current_main": (
        "DE_de_KDZ1_1503_D33",
        "a9baae4b5f702f59cbc3d9eba98eb12bdd31d91aaac5e49e2ac83ecb7fbb1db1",
    ),
    "current_short": (
        "DE_de_KDZ2_1503_D34-MoMi",
        "f8da4ff71615141aaf97ade1b91c3b63259a41b2436e09f65c5b4e4db6898e69",
    ),
    "preview_main": (
        "DE_de_KDZ1_1503_D34",
        "20f1b8f998e361399b9e1fec74f700712e1a62d7048fb92e40b5e9bbe8241c9a",
    ),
    "preview_overlap": (
        "DE_de_leaflet2_1503_D34-EL-Schule",
        "ab338f5fd1aca216380a1cbd0a0a7fea6f86a70a9bf656b1ed99d29dbcc4a6e3",
    ),
}
FAMILY_ASSOCIATION_BOUND = "BOUND"
FAMILY_ASSOCIATION_UNBOUND = "UNBOUND"
UNBOUND_FAMILY_REASONS = (
    "FAMILY_BINDING_MISSING",
    "FAMILY_BINDING_AMBIGUOUS",
    "FAMILY_BINDING_NOT_CARD_LOCAL",
)

_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
_GIT_SHA_RE = re.compile(r"^[0-9a-f]{40}$")
_IDENTIFIER_RE = re.compile(r"^[A-Za-z0-9._-]+$")
_CANONICAL_AMOUNT_RE = re.compile(r"^(?:0|[1-9][0-9]{0,5})\.[0-9]{2}$")
_MAX_LOCATOR_LENGTH = 512


class KauflandSourceCardContractError(ValueError):
    """Fail-closed K3 source-card contract error with a stable reason code."""

    def __init__(self, code: str, message: str) -> None:
        self.code = code
        super().__init__(f"{code}: {message}")


@dataclass(frozen=True)
class PriceEvidence:
    role: str
    amount: str
    role_locator: str
    value_locator: str
    role_evidence_sha256: str
    value_evidence_sha256: str
    owner_card_locator: str
    owner_card_fragment_sha256: str
    owner_match_count: int = 1
    role_assignment_basis: str = EXPLICIT_ROLE_BASIS


@dataclass(frozen=True)
class SourceCardSemanticReceipt:
    schema_version: int
    contract_version: str
    receipt_type: str
    k2_bundle_identity_sha256: str
    k2_git_revision: str
    k2_parser_input_contract_version: str
    store_id: str
    source_artifact_role: str
    source_artifact_sha256: str
    source_artifact_byte_count: int
    source_artifact_content_type: str
    card_locator: str
    card_fragment_sha256: str
    card_owner_match_count: int
    price_evidence: tuple[PriceEvidence, ...]
    receipt_identity_sha256: str

    def as_public_dict(self) -> dict[str, object]:
        return asdict(self)


@dataclass(frozen=True)
class FamilyAssociationReceipt:
    schema_version: int
    contract_version: str
    receipt_type: str
    source_card_receipt_identity_sha256: str
    card_locator: str
    card_fragment_sha256: str
    status: str
    blocker_reason: str | None
    family_relation: str | None
    family_source_identifier: str | None
    family_identity_sha256: str | None
    family_binding_locator: str | None
    family_binding_evidence_sha256: str | None
    family_binding_owner_card_locator: str | None
    family_binding_owner_card_fragment_sha256: str | None
    family_binding_owner_match_count: int | None
    family_binding_method: str | None
    association_identity_sha256: str

    @property
    def is_bound(self) -> bool:
        return self.status == FAMILY_ASSOCIATION_BOUND

    def as_public_dict(self) -> dict[str, object]:
        return asdict(self)


def _stable_sha(payload: object) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _fail(code: str, message: str) -> None:
    raise KauflandSourceCardContractError(code, message)


def _require_sha256(value: str, *, label: str) -> str:
    if not isinstance(value, str) or not _SHA256_RE.fullmatch(value):
        _fail("INVALID_SHA256", f"{label} must be a lowercase SHA-256")
    return value


def _require_git_sha(value: str) -> str:
    if not isinstance(value, str) or not _GIT_SHA_RE.fullmatch(value):
        _fail("INVALID_GIT_REVISION", "k2_git_revision must be a lowercase 40-character Git SHA")
    return value


def _require_identifier(value: str, *, label: str) -> str:
    if (
        not isinstance(value, str)
        or value in {"", ".", ".."}
        or not _IDENTIFIER_RE.fullmatch(value)
    ):
        _fail("INVALID_IDENTIFIER", f"{label} is not a safe exact identifier")
    return value


def _require_locator(value: str, *, label: str) -> str:
    if not isinstance(value, str):
        _fail("INVALID_LOCATOR", f"{label} must be a string")
    if value != value.strip() or not value or len(value) > _MAX_LOCATOR_LENGTH:
        _fail(
            "INVALID_LOCATOR",
            f"{label} must be non-empty, trimmed and <= {_MAX_LOCATOR_LENGTH} characters",
        )
    if any(character in value for character in ("\n", "\r", "\t")):
        _fail("INVALID_LOCATOR", f"{label} must be a single-line sanitized locator")
    return value


def _canonical_amount(value: object) -> str:
    if isinstance(value, bool) or isinstance(value, (int, float)):
        _fail("INVALID_PRICE_AMOUNT", "price amount must be a canonical decimal string or Decimal")
    if isinstance(value, Decimal):
        amount = value
    elif isinstance(value, str) and _CANONICAL_AMOUNT_RE.fullmatch(value):
        try:
            amount = Decimal(value)
        except InvalidOperation as exc:
            _fail("INVALID_PRICE_AMOUNT", "price amount is not a valid Decimal")
            raise AssertionError from exc
    else:
        _fail(
            "INVALID_PRICE_AMOUNT",
            "price amount must use canonical decimal form with exactly two fractional digits",
        )
    if not amount.is_finite() or amount <= 0:
        _fail("INVALID_PRICE_AMOUNT", "price amount must be finite and positive")
    quantized = amount.quantize(Decimal("0.01"))
    if quantized != amount:
        _fail("INVALID_PRICE_AMOUNT", "price amount must have cent precision")
    return format(quantized, ".2f")


def _validate_source_identity(
    *,
    k2_bundle_identity_sha256: str,
    k2_git_revision: str,
    k2_parser_input_contract_version: str,
    store_id: str,
    source_artifact_role: str,
    source_artifact_sha256: str,
    source_artifact_byte_count: int,
    source_artifact_content_type: str,
) -> tuple[str, str, str]:
    bundle_sha = _require_sha256(
        k2_bundle_identity_sha256,
        label="k2_bundle_identity_sha256",
    )
    git_revision = _require_git_sha(k2_git_revision)
    if k2_parser_input_contract_version != K2_PARSER_INPUT_CONTRACT_VERSION:
        _fail(
            "UPSTREAM_CONTRACT_MISMATCH",
            f"K3 source-card contract requires {K2_PARSER_INPUT_CONTRACT_VERSION!r}",
        )
    if store_id != STORE_ID:
        _fail("STORE_BINDING_MISMATCH", f"K3 source-card contract requires exact Kaufland store {STORE_ID}")
    if source_artifact_role != SOURCE_ARTIFACT_ROLE:
        _fail(
            "WRONG_SOURCE_ARTIFACT_ROLE",
            f"structured card evidence must come from {SOURCE_ARTIFACT_ROLE!r}",
        )
    artifact_sha = _require_sha256(
        source_artifact_sha256,
        label="source_artifact_sha256",
    )
    if isinstance(source_artifact_byte_count, bool) or not isinstance(source_artifact_byte_count, int):
        _fail("INVALID_ARTIFACT_BYTE_COUNT", "source_artifact_byte_count must be an integer")
    if source_artifact_byte_count <= 0:
        _fail("INVALID_ARTIFACT_BYTE_COUNT", "source_artifact_byte_count must be positive")
    if (
        not isinstance(source_artifact_content_type, str)
        or not source_artifact_content_type.casefold().startswith("text/html")
    ):
        _fail(
            "WRONG_SOURCE_CONTENT_TYPE",
            "structured card evidence must be bound to retained HTML",
        )
    return bundle_sha, git_revision, artifact_sha


def _validate_card_identity(
    *,
    card_locator: str,
    card_fragment_sha256: str,
    card_owner_match_count: int,
) -> tuple[str, str]:
    exact_card_locator = _require_locator(card_locator, label="card_locator")
    card_sha = _require_sha256(
        card_fragment_sha256,
        label="card_fragment_sha256",
    )
    if card_owner_match_count != 1:
        _fail(
            "AMBIGUOUS_CARD_OWNERSHIP",
            "source-card anchor must resolve to exactly one card in the bound artifact",
        )
    return exact_card_locator, card_sha


def _validate_price_evidence(
    item: PriceEvidence,
    *,
    card_locator: str,
    card_fragment_sha256: str,
) -> PriceEvidence:
    if item.role not in PRICE_ROLES:
        _fail("UNSUPPORTED_PRICE_ROLE", f"unsupported Kaufland K3 price role: {item.role!r}")
    amount = _canonical_amount(item.amount)
    role_locator = _require_locator(item.role_locator, label=f"{item.role}.role_locator")
    value_locator = _require_locator(item.value_locator, label=f"{item.role}.value_locator")
    role_sha = _require_sha256(
        item.role_evidence_sha256,
        label=f"{item.role}.role_evidence_sha256",
    )
    value_sha = _require_sha256(
        item.value_evidence_sha256,
        label=f"{item.role}.value_evidence_sha256",
    )
    owner_locator = _require_locator(
        item.owner_card_locator,
        label=f"{item.role}.owner_card_locator",
    )
    owner_fragment_sha = _require_sha256(
        item.owner_card_fragment_sha256,
        label=f"{item.role}.owner_card_fragment_sha256",
    )
    if item.owner_match_count != 1:
        _fail(
            "AMBIGUOUS_PRICE_OWNERSHIP",
            f"{item.role} evidence must have exactly one source-card owner",
        )
    if owner_locator != card_locator or owner_fragment_sha != card_fragment_sha256:
        _fail(
            "PRICE_EVIDENCE_OUTSIDE_CARD",
            f"{item.role} evidence is not bound to the receipt source card",
        )
    if item.role_assignment_basis != EXPLICIT_ROLE_BASIS:
        _fail(
            "PRICE_ROLE_NOT_EXPLICIT",
            f"{item.role} role must come from explicit source role evidence; numeric inference is forbidden",
        )
    return PriceEvidence(
        role=item.role,
        amount=amount,
        role_locator=role_locator,
        value_locator=value_locator,
        role_evidence_sha256=role_sha,
        value_evidence_sha256=value_sha,
        owner_card_locator=owner_locator,
        owner_card_fragment_sha256=owner_fragment_sha,
        owner_match_count=1,
        role_assignment_basis=EXPLICIT_ROLE_BASIS,
    )


def _canonical_price_evidence(
    evidence: Iterable[PriceEvidence],
    *,
    card_locator: str,
    card_fragment_sha256: str,
) -> tuple[PriceEvidence, ...]:
    validated = [
        _validate_price_evidence(
            item,
            card_locator=card_locator,
            card_fragment_sha256=card_fragment_sha256,
        )
        for item in evidence
    ]
    if not validated:
        _fail(
            "PRICE_EVIDENCE_MISSING",
            "source-card semantic receipt must contain explicit price-role evidence",
        )

    by_role: dict[str, PriceEvidence] = {}
    locator_owners: dict[str, str] = {}
    hash_owners: dict[str, str] = {}
    for item in validated:
        if item.role in by_role:
            _fail(
                "DUPLICATE_PRICE_ROLE",
                f"source card has multiple observations for price role {item.role!r}",
            )
        by_role[item.role] = item

        for locator in {item.role_locator, item.value_locator}:
            prior = locator_owners.get(locator)
            if prior is not None and prior != item.role:
                _fail(
                    "PRICE_EVIDENCE_CROSS_BOUND",
                    f"one evidence locator is assigned to both {prior!r} and {item.role!r}",
                )
            locator_owners[locator] = item.role

        for evidence_sha in {item.role_evidence_sha256, item.value_evidence_sha256}:
            prior = hash_owners.get(evidence_sha)
            if prior is not None and prior != item.role:
                _fail(
                    "PRICE_EVIDENCE_CROSS_BOUND",
                    f"one evidence fragment is assigned to both {prior!r} and {item.role!r}",
                )
            hash_owners[evidence_sha] = item.role

    return tuple(by_role[role] for role in PRICE_ROLES if role in by_role)


def _semantic_identity_payload(
    *,
    k2_bundle_identity_sha256: str,
    k2_git_revision: str,
    store_id: str,
    source_artifact_sha256: str,
    source_artifact_byte_count: int,
    source_artifact_content_type: str,
    card_locator: str,
    card_fragment_sha256: str,
    price_evidence: tuple[PriceEvidence, ...],
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_version": CONTRACT_VERSION,
        "receipt_type": "source_card_semantics",
        "k2_bundle_identity_sha256": k2_bundle_identity_sha256,
        "k2_git_revision": k2_git_revision,
        "k2_parser_input_contract_version": K2_PARSER_INPUT_CONTRACT_VERSION,
        "store_id": store_id,
        "source_artifact_role": SOURCE_ARTIFACT_ROLE,
        "source_artifact_sha256": source_artifact_sha256,
        "source_artifact_byte_count": source_artifact_byte_count,
        "source_artifact_content_type": source_artifact_content_type,
        "card_locator": card_locator,
        "card_fragment_sha256": card_fragment_sha256,
        "card_owner_match_count": 1,
        "price_evidence": [asdict(item) for item in price_evidence],
    }


def build_source_card_semantic_receipt(
    *,
    k2_bundle_identity_sha256: str,
    k2_git_revision: str,
    k2_parser_input_contract_version: str,
    store_id: str,
    source_artifact_role: str,
    source_artifact_sha256: str,
    source_artifact_byte_count: int,
    source_artifact_content_type: str,
    card_locator: str,
    card_fragment_sha256: str,
    card_owner_match_count: int,
    price_evidence: Iterable[PriceEvidence],
) -> SourceCardSemanticReceipt:
    bundle_sha, git_revision, artifact_sha = _validate_source_identity(
        k2_bundle_identity_sha256=k2_bundle_identity_sha256,
        k2_git_revision=k2_git_revision,
        k2_parser_input_contract_version=k2_parser_input_contract_version,
        store_id=store_id,
        source_artifact_role=source_artifact_role,
        source_artifact_sha256=source_artifact_sha256,
        source_artifact_byte_count=source_artifact_byte_count,
        source_artifact_content_type=source_artifact_content_type,
    )
    exact_card_locator, card_sha = _validate_card_identity(
        card_locator=card_locator,
        card_fragment_sha256=card_fragment_sha256,
        card_owner_match_count=card_owner_match_count,
    )
    canonical_prices = _canonical_price_evidence(
        price_evidence,
        card_locator=exact_card_locator,
        card_fragment_sha256=card_sha,
    )
    payload = _semantic_identity_payload(
        k2_bundle_identity_sha256=bundle_sha,
        k2_git_revision=git_revision,
        store_id=store_id,
        source_artifact_sha256=artifact_sha,
        source_artifact_byte_count=source_artifact_byte_count,
        source_artifact_content_type=source_artifact_content_type,
        card_locator=exact_card_locator,
        card_fragment_sha256=card_sha,
        price_evidence=canonical_prices,
    )
    identity = _stable_sha(payload)
    return SourceCardSemanticReceipt(
        schema_version=SCHEMA_VERSION,
        contract_version=CONTRACT_VERSION,
        receipt_type="source_card_semantics",
        k2_bundle_identity_sha256=bundle_sha,
        k2_git_revision=git_revision,
        k2_parser_input_contract_version=K2_PARSER_INPUT_CONTRACT_VERSION,
        store_id=store_id,
        source_artifact_role=SOURCE_ARTIFACT_ROLE,
        source_artifact_sha256=artifact_sha,
        source_artifact_byte_count=source_artifact_byte_count,
        source_artifact_content_type=source_artifact_content_type,
        card_locator=exact_card_locator,
        card_fragment_sha256=card_sha,
        card_owner_match_count=1,
        price_evidence=canonical_prices,
        receipt_identity_sha256=identity,
    )


def verify_source_card_semantic_receipt(receipt: SourceCardSemanticReceipt) -> None:
    if (
        receipt.schema_version != SCHEMA_VERSION
        or receipt.contract_version != CONTRACT_VERSION
        or receipt.receipt_type != "source_card_semantics"
    ):
        _fail(
            "RECEIPT_CONTRACT_MISMATCH",
            "source-card semantic receipt schema/contract version does not match",
        )
    rebuilt = build_source_card_semantic_receipt(
        k2_bundle_identity_sha256=receipt.k2_bundle_identity_sha256,
        k2_git_revision=receipt.k2_git_revision,
        k2_parser_input_contract_version=receipt.k2_parser_input_contract_version,
        store_id=receipt.store_id,
        source_artifact_role=receipt.source_artifact_role,
        source_artifact_sha256=receipt.source_artifact_sha256,
        source_artifact_byte_count=receipt.source_artifact_byte_count,
        source_artifact_content_type=receipt.source_artifact_content_type,
        card_locator=receipt.card_locator,
        card_fragment_sha256=receipt.card_fragment_sha256,
        card_owner_match_count=receipt.card_owner_match_count,
        price_evidence=receipt.price_evidence,
    )
    if rebuilt.receipt_identity_sha256 != receipt.receipt_identity_sha256:
        _fail(
            "RECEIPT_IDENTITY_MISMATCH",
            "source-card semantic receipt identity does not match its canonical validated payload",
        )


def _association_payload(
    *,
    semantic_receipt: SourceCardSemanticReceipt,
    status: str,
    blocker_reason: str | None,
    family_relation: str | None,
    family_source_identifier: str | None,
    family_identity_sha256: str | None,
    family_binding_locator: str | None,
    family_binding_evidence_sha256: str | None,
    family_binding_owner_card_locator: str | None,
    family_binding_owner_card_fragment_sha256: str | None,
    family_binding_owner_match_count: int | None,
    family_binding_method: str | None,
) -> dict[str, object]:
    return {
        "schema_version": SCHEMA_VERSION,
        "contract_version": CONTRACT_VERSION,
        "receipt_type": "family_association",
        "source_card_receipt_identity_sha256": semantic_receipt.receipt_identity_sha256,
        "card_locator": semantic_receipt.card_locator,
        "card_fragment_sha256": semantic_receipt.card_fragment_sha256,
        "status": status,
        "blocker_reason": blocker_reason,
        "family_relation": family_relation,
        "family_source_identifier": family_source_identifier,
        "family_identity_sha256": family_identity_sha256,
        "family_binding_locator": family_binding_locator,
        "family_binding_evidence_sha256": family_binding_evidence_sha256,
        "family_binding_owner_card_locator": family_binding_owner_card_locator,
        "family_binding_owner_card_fragment_sha256": family_binding_owner_card_fragment_sha256,
        "family_binding_owner_match_count": family_binding_owner_match_count,
        "family_binding_method": family_binding_method,
    }


def build_bound_family_association(
    *,
    semantic_receipt: SourceCardSemanticReceipt,
    family_relation: str,
    family_source_identifier: str,
    family_identity_sha256: str,
    family_binding_locator: str,
    family_binding_evidence_sha256: str,
    family_binding_owner_card_locator: str,
    family_binding_owner_card_fragment_sha256: str,
    family_binding_owner_match_count: int,
    family_binding_method: str,
) -> FamilyAssociationReceipt:
    verify_source_card_semantic_receipt(semantic_receipt)
    if family_relation not in FAMILY_RELATIONS:
        _fail(
            "UNSUPPORTED_FAMILY_RELATION",
            f"family relation {family_relation!r} is outside the accepted K2 baseline",
        )
    family_identifier = _require_identifier(
        family_source_identifier,
        label="family_source_identifier",
    )
    family_sha = _require_sha256(
        family_identity_sha256,
        label="family_identity_sha256",
    )
    expected_identifier, expected_family_sha = ACCEPTED_FAMILIES[family_relation]
    if family_identifier != expected_identifier or family_sha != expected_family_sha:
        _fail(
            "FAMILY_IDENTITY_MISMATCH",
            "BOUND family relation/source identifier/identity must match one exact accepted K2 family",
        )
    family_locator = _require_locator(
        family_binding_locator,
        label="family_binding_locator",
    )
    family_evidence_sha = _require_sha256(
        family_binding_evidence_sha256,
        label="family_binding_evidence_sha256",
    )
    owner_locator = _require_locator(
        family_binding_owner_card_locator,
        label="family_binding_owner_card_locator",
    )
    owner_sha = _require_sha256(
        family_binding_owner_card_fragment_sha256,
        label="family_binding_owner_card_fragment_sha256",
    )
    if family_binding_owner_match_count != 1:
        _fail(
            "AMBIGUOUS_FAMILY_OWNERSHIP",
            "family-binding evidence must have exactly one source-card owner",
        )
    if owner_locator != semantic_receipt.card_locator or owner_sha != semantic_receipt.card_fragment_sha256:
        _fail(
            "FAMILY_EVIDENCE_OUTSIDE_CARD",
            "family-binding evidence is not bound to the exact semantic source card",
        )
    if family_binding_method != EXPLICIT_FAMILY_BINDING:
        _fail(
            "FAMILY_BINDING_NOT_EXPLICIT",
            "campaign family must be proven by explicit card-local source evidence",
        )

    payload = _association_payload(
        semantic_receipt=semantic_receipt,
        status=FAMILY_ASSOCIATION_BOUND,
        blocker_reason=None,
        family_relation=family_relation,
        family_source_identifier=family_identifier,
        family_identity_sha256=family_sha,
        family_binding_locator=family_locator,
        family_binding_evidence_sha256=family_evidence_sha,
        family_binding_owner_card_locator=owner_locator,
        family_binding_owner_card_fragment_sha256=owner_sha,
        family_binding_owner_match_count=1,
        family_binding_method=EXPLICIT_FAMILY_BINDING,
    )
    identity = _stable_sha(payload)
    return FamilyAssociationReceipt(
        **payload,
        association_identity_sha256=identity,
    )


def build_unbound_family_association(
    *,
    semantic_receipt: SourceCardSemanticReceipt,
    blocker_reason: str,
) -> FamilyAssociationReceipt:
    verify_source_card_semantic_receipt(semantic_receipt)
    if blocker_reason not in UNBOUND_FAMILY_REASONS:
        _fail(
            "INVALID_UNBOUND_FAMILY_REASON",
            "UNBOUND family association requires a stable supported blocker reason",
        )
    payload = _association_payload(
        semantic_receipt=semantic_receipt,
        status=FAMILY_ASSOCIATION_UNBOUND,
        blocker_reason=blocker_reason,
        family_relation=None,
        family_source_identifier=None,
        family_identity_sha256=None,
        family_binding_locator=None,
        family_binding_evidence_sha256=None,
        family_binding_owner_card_locator=None,
        family_binding_owner_card_fragment_sha256=None,
        family_binding_owner_match_count=None,
        family_binding_method=None,
    )
    identity = _stable_sha(payload)
    return FamilyAssociationReceipt(
        **payload,
        association_identity_sha256=identity,
    )


def verify_family_association(
    association: FamilyAssociationReceipt,
    *,
    semantic_receipt: SourceCardSemanticReceipt,
) -> None:
    verify_source_card_semantic_receipt(semantic_receipt)
    if (
        association.schema_version != SCHEMA_VERSION
        or association.contract_version != CONTRACT_VERSION
        or association.receipt_type != "family_association"
    ):
        _fail(
            "FAMILY_ASSOCIATION_CONTRACT_MISMATCH",
            "family-association schema/contract version does not match",
        )
    if association.source_card_receipt_identity_sha256 != semantic_receipt.receipt_identity_sha256:
        _fail(
            "FAMILY_ASSOCIATION_SOURCE_CARD_MISMATCH",
            "family association is not bound to the supplied semantic receipt identity",
        )
    if (
        association.card_locator != semantic_receipt.card_locator
        or association.card_fragment_sha256 != semantic_receipt.card_fragment_sha256
    ):
        _fail(
            "FAMILY_ASSOCIATION_SOURCE_CARD_MISMATCH",
            "family association is not bound to the supplied semantic source card",
        )

    if association.status == FAMILY_ASSOCIATION_BOUND:
        if association.blocker_reason is not None:
            _fail(
                "BOUND_FAMILY_HAS_BLOCKER",
                "BOUND family association cannot carry an UNBOUND blocker reason",
            )
        rebuilt = build_bound_family_association(
            semantic_receipt=semantic_receipt,
            family_relation=association.family_relation,  # type: ignore[arg-type]
            family_source_identifier=association.family_source_identifier,  # type: ignore[arg-type]
            family_identity_sha256=association.family_identity_sha256,  # type: ignore[arg-type]
            family_binding_locator=association.family_binding_locator,  # type: ignore[arg-type]
            family_binding_evidence_sha256=association.family_binding_evidence_sha256,  # type: ignore[arg-type]
            family_binding_owner_card_locator=association.family_binding_owner_card_locator,  # type: ignore[arg-type]
            family_binding_owner_card_fragment_sha256=association.family_binding_owner_card_fragment_sha256,  # type: ignore[arg-type]
            family_binding_owner_match_count=association.family_binding_owner_match_count,  # type: ignore[arg-type]
            family_binding_method=association.family_binding_method,  # type: ignore[arg-type]
        )
    elif association.status == FAMILY_ASSOCIATION_UNBOUND:
        forbidden_values = (
            association.family_relation,
            association.family_source_identifier,
            association.family_identity_sha256,
            association.family_binding_locator,
            association.family_binding_evidence_sha256,
            association.family_binding_owner_card_locator,
            association.family_binding_owner_card_fragment_sha256,
            association.family_binding_owner_match_count,
            association.family_binding_method,
        )
        if any(value is not None for value in forbidden_values):
            _fail(
                "UNBOUND_FAMILY_CARRIES_SEMANTICS",
                "UNBOUND family association must not carry family identity, evidence, ownership, validity or state semantics",
            )
        rebuilt = build_unbound_family_association(
            semantic_receipt=semantic_receipt,
            blocker_reason=association.blocker_reason,  # type: ignore[arg-type]
        )
    else:
        _fail(
            "INVALID_FAMILY_ASSOCIATION_STATUS",
            "family association status must be exactly BOUND or UNBOUND",
        )

    if rebuilt.association_identity_sha256 != association.association_identity_sha256:
        _fail(
            "FAMILY_ASSOCIATION_IDENTITY_MISMATCH",
            "family-association identity does not match its canonical validated payload",
        )
