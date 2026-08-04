from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import re
import unicodedata
from typing import Any, Iterable


PRICING_NORMALIZER_VERSION = "pricing-normalizer-v1"


class PricingMode(StrEnum):
    FIXED_PACKAGE = "fixed_package"
    VARIABLE_WEIGHT = "variable_weight"
    PIECE = "piece"
    UNIT_PRICE_ONLY = "unit_price_only"
    UNKNOWN = "unknown"


@dataclass(frozen=True)
class PricingNormalizationDecision:
    accepted: bool
    pricing_mode: PricingMode
    advertised_price_eur: Decimal
    basis_quantity_value: Decimal | None
    basis_quantity_unit: str | None
    normalized_unit_price_eur: Decimal | None
    fixed_item_quantity_value: Decimal | None
    fixed_item_quantity_unit: str | None
    confidence: Decimal
    reason: str
    evidence: dict[str, Any]

    def as_jsonable(self) -> dict[str, Any]:
        payload = asdict(self)
        for key, value in list(payload.items()):
            if isinstance(value, Decimal):
                payload[key] = format(value, "f")
            elif isinstance(value, PricingMode):
                payload[key] = value.value
        return payload


_EXACT_ONE_KG_BASIS = re.compile(r"^\s*1\s*kg\s*$", re.IGNORECASE)
_ORIGIN_CONTEXT = re.compile(
    r"\b("
    r"italien|spanien|deutschland|frankreich|griechenland|"
    r"niederlande|türkei"
    r")\b",
    re.IGNORECASE,
)
_FRESH_PRODUCE_CONTEXT = re.compile(
    r"\b("
    r"klasse\s*(?:1|i)|kl\.\s*i|lose\s+ware|obst|gemüse"
    r")\b",
    re.IGNORECASE,
)
_FIXED_PACKAGE = re.compile(
    r"\b("
    r"beutel|packung|schale|netz|dose|flasche|glas|karton|"
    r"stück|stueck|stk\.?"
    r")\b",
    re.IGNORECASE,
)
_MULTIPACK = re.compile(
    r"\b\d+\s*[x×]\s*\d+(?:[.,]\d+)?\s*(?:kg|g|l|ml)\b",
    re.IGNORECASE,
)


def _clean_lines(raw_lines: Iterable[str]) -> list[str]:
    output: list[str] = []
    for value in raw_lines:
        normalized = unicodedata.normalize("NFKC", str(value))
        normalized = " ".join(normalized.split())
        if normalized:
            output.append(normalized)
    return output


def _price(value: Decimal | str | int | float) -> Decimal:
    try:
        price = Decimal(str(value)).quantize(Decimal("0.0001"))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError("advertised_price_eur must be decimal") from exc
    if price <= 0:
        raise ValueError("advertised_price_eur must be positive")
    return price


def normalize_netto_variable_weight(
    raw_lines: Iterable[str],
    advertised_price_eur: Decimal | str | int | float,
) -> PricingNormalizationDecision:
    """Interpret a Netto fresh-produce ``1 kg`` line as a price basis.

    The function is deliberately conservative. It accepts only a bare
    ``1 kg`` basis line together with fresh-produce context and rejects
    packaging, multipack and piece markers. It never infers fixed weight.
    """

    lines = _clean_lines(raw_lines)
    price = _price(advertised_price_eur)

    has_basis = any(_EXACT_ONE_KG_BASIS.fullmatch(line) for line in lines)
    has_origin_context = any(_ORIGIN_CONTEXT.search(line) for line in lines)
    has_produce_context = any(
        _FRESH_PRODUCE_CONTEXT.search(line) for line in lines
    )
    has_fixed_package = any(_FIXED_PACKAGE.search(line) for line in lines)
    has_multipack = any(_MULTIPACK.search(line) for line in lines)

    evidence = {
        "rule": "netto_produce_1kg_pricing_basis_v1",
        "normalizer_version": PRICING_NORMALIZER_VERSION,
        "raw_lines": lines,
        "has_exact_one_kg_basis": has_basis,
        "has_origin_context": has_origin_context,
        "has_produce_context": has_produce_context,
        "has_fixed_package_marker": has_fixed_package,
        "has_multipack_marker": has_multipack,
    }

    accepted = (
        has_basis
        and has_produce_context
        and not has_fixed_package
        and not has_multipack
    )
    if not accepted:
        return PricingNormalizationDecision(
            accepted=False,
            pricing_mode=PricingMode.UNKNOWN,
            advertised_price_eur=price,
            basis_quantity_value=None,
            basis_quantity_unit=None,
            normalized_unit_price_eur=None,
            fixed_item_quantity_value=None,
            fixed_item_quantity_unit=None,
            confidence=Decimal("0.0000"),
            reason="insufficient_or_fixed_package_evidence",
            evidence=evidence,
        )

    return PricingNormalizationDecision(
        accepted=True,
        pricing_mode=PricingMode.VARIABLE_WEIGHT,
        advertised_price_eur=price,
        basis_quantity_value=Decimal("1"),
        basis_quantity_unit="kg",
        normalized_unit_price_eur=price,
        fixed_item_quantity_value=None,
        fixed_item_quantity_unit=None,
        confidence=Decimal("0.9900"),
        reason="exact_1kg_basis_with_fresh_produce_context",
        evidence=evidence,
    )
