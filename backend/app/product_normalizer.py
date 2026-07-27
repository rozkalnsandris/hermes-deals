from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
import hashlib
from pathlib import PurePosixPath
import re
import unicodedata
from typing import Any, Iterable
from urllib.parse import unquote, urlparse


NORMALIZER_VERSION = "normalizer-v1.1"
MATCHER_VERSION = "matcher-v1.1"

_EXPLICIT_BARCODE_KEYS = {
    "gtin",
    "gtin8",
    "gtin12",
    "gtin13",
    "gtin14",
    "ean",
    "ean8",
    "ean13",
    "upc",
    "upca",
    "barcode",
    "barcodenumber",
    "globaltradeitemnumber",
}

_METRIC_UNITS = r"kg|g|mg|l|ml|cl"
_TEXT_NUMBER = r"\d+(?:[.,]\d+)?"
_TEXT_SEP = r"\s*[-–—]?\s*"

_MULTIPACK_RE = re.compile(
    rf"(?P<count>\d{{1,3}})\s*[x×]\s*"
    rf"(?P<quantity>{_TEXT_NUMBER}){_TEXT_SEP}"
    rf"(?P<unit>{_METRIC_UNITS})\b",
    re.IGNORECASE,
)
_SINGLE_METRIC_RE = re.compile(
    rf"(?P<quantity>{_TEXT_NUMBER}){_TEXT_SEP}"
    rf"(?P<unit>{_METRIC_UNITS})\b",
    re.IGNORECASE,
)
_COUNT_PACK_RE = re.compile(
    r"(?P<count>\d{1,3})\s*er\s*[-–—]?\s*(?:packung|rolle)\b",
    re.IGNORECASE,
)
_PIECE_RE = re.compile(
    r"(?P<count>\d{1,3})\s*(?:stück|stueck|stk\.?)\b",
    re.IGNORECASE,
)
_VARIABLE_KG_PRICE_RE = re.compile(
    r"^kg\s*[-–—]?\s*preis$",
    re.IGNORECASE,
)

# EDEKA's first-party image filenames encode product package evidence, e.g.
# "..._Almette_..._150g_....png", "..._4x100g_....png",
# "..._Astra_27x0_33l.png".  Decimal underscores are handled only when a
# metric unit is attached.  Numeric suffixes without metric units are ignored.
_IMAGE_MULTIPACK_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<count>\d{{1,3}})[xX×]"
    rf"(?P<quantity>\d+(?:[.,_]\d+)?)"
    rf"[-_]?(?P<unit>{_METRIC_UNITS})(?=[_.\-]|$)",
    re.IGNORECASE,
)
_IMAGE_SINGLE_METRIC_RE = re.compile(
    rf"(?<![A-Za-z0-9])(?P<quantity>\d+(?:[.,_]\d+)?)"
    rf"[-_]?(?P<unit>{_METRIC_UNITS})(?=[_.\-]|$)",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class PackageEvidence:
    item_quantity_value: Decimal | None
    item_quantity_unit: str | None
    pack_count: int | None
    source_text: str | None
    parse_method: str | None
    evidence_source: str | None

    def signature(self) -> tuple[str | None, str | None, int | None]:
        value = (
            format(self.item_quantity_value, "f")
            if self.item_quantity_value is not None
            else None
        )
        return value, self.item_quantity_unit, self.pack_count


@dataclass(frozen=True)
class NormalizedOffer:
    offer_candidate_id: str
    source_chain: str
    source_store_external_id: str | None
    source_offer_id: str | None
    product_name_raw: str
    brand_raw: str | None
    package_text_raw: str | None
    source_image_url: str | None
    normalized_name: str
    normalized_brand: str | None
    item_quantity_value: Decimal | None
    item_quantity_unit: str | None
    pack_count: int | None
    gtin14: str | None
    gtin_evidence: dict[str, Any] | None
    package_parse_method: str | None
    package_evidence_source: str | None
    package_evidence_text: str | None

    def package_signature(self) -> tuple[str | None, str | None, int | None]:
        value = (
            format(self.item_quantity_value, "f")
            if self.item_quantity_value is not None
            else None
        )
        return value, self.item_quantity_unit, self.pack_count

    def identity_node_key(self) -> tuple[Any, ...]:
        return (
            self.source_chain,
            self.normalized_name,
            self.normalized_brand,
            self.package_signature(),
            self.gtin14,
        )


def normalize_text(value: str | None) -> str:
    text = unicodedata.normalize("NFKC", value or "").casefold()
    text = text.replace("ß", "ss")

    normalized_chars: list[str] = []
    for char in text:
        if char.isalnum() or char == "%":
            normalized_chars.append(char)
        else:
            normalized_chars.append(" ")

    return " ".join("".join(normalized_chars).split())


def normalize_brand(value: str | None) -> str | None:
    normalized = normalize_text(value)
    return normalized or None


def _decimal(value: str) -> Decimal:
    return Decimal(value.replace("_", ".").replace(",", "."))


def _metric_to_base(
    quantity: Decimal,
    unit: str,
) -> tuple[Decimal, str]:
    unit = unit.casefold()
    if unit == "kg":
        return quantity * Decimal("1000"), "g"
    if unit == "mg":
        return quantity / Decimal("1000"), "g"
    if unit == "l":
        return quantity * Decimal("1000"), "ml"
    if unit == "cl":
        return quantity * Decimal("10"), "ml"
    return quantity, unit


def _metric_evidence(
    *,
    quantity_text: str,
    unit_text: str,
    count: int,
    source_text: str,
    parse_method: str,
    evidence_source: str,
) -> PackageEvidence:
    try:
        quantity = _decimal(quantity_text)
    except InvalidOperation:
        return PackageEvidence(
            None,
            None,
            None,
            source_text,
            None,
            evidence_source,
        )

    quantity, unit = _metric_to_base(quantity, unit_text)
    if quantity <= 0 or count <= 0:
        return PackageEvidence(
            None,
            None,
            None,
            source_text,
            None,
            evidence_source,
        )

    return PackageEvidence(
        quantity.normalize(),
        unit,
        count,
        source_text,
        parse_method,
        evidence_source,
    )


def parse_package_text(value: str | None) -> PackageEvidence:
    raw = (value or "").strip()
    if not raw:
        return PackageEvidence(None, None, None, value, None, None)

    multipack = _MULTIPACK_RE.search(raw)
    if multipack:
        return _metric_evidence(
            quantity_text=multipack.group("quantity"),
            unit_text=multipack.group("unit"),
            count=int(multipack.group("count")),
            source_text=raw,
            parse_method="metric_multipack",
            evidence_source="package_text_raw",
        )

    metric = _SINGLE_METRIC_RE.search(raw)
    if metric:
        return _metric_evidence(
            quantity_text=metric.group("quantity"),
            unit_text=metric.group("unit"),
            count=1,
            source_text=raw,
            parse_method="metric_single",
            evidence_source="package_text_raw",
        )

    count_pack = _COUNT_PACK_RE.search(raw)
    if count_pack:
        count = int(count_pack.group("count"))
        if count > 0:
            return PackageEvidence(
                None,
                "piece",
                count,
                raw,
                "count_pack",
                "package_text_raw",
            )

    pieces = _PIECE_RE.search(raw)
    if pieces:
        count = int(pieces.group("count"))
        if count > 0:
            return PackageEvidence(
                None,
                "piece",
                count,
                raw,
                "piece_count",
                "package_text_raw",
            )

    if raw.casefold() in {"stück", "stueck"}:
        return PackageEvidence(
            None,
            "piece",
            1,
            raw,
            "piece_single",
            "package_text_raw",
        )

    if _VARIABLE_KG_PRICE_RE.fullmatch(raw):
        return PackageEvidence(
            None,
            None,
            None,
            raw,
            "variable_weight_kg_price",
            "package_text_raw",
        )

    return PackageEvidence(None, None, None, value, None, None)


def _image_filename(source_image_url: str | None) -> str | None:
    if not source_image_url:
        return None
    try:
        path = unquote(urlparse(source_image_url).path)
        return PurePosixPath(path).name or None
    except Exception:
        return None


def parse_edeka_image_package(
    source_image_url: str | None,
) -> PackageEvidence:
    filename = _image_filename(source_image_url)
    if not filename:
        return PackageEvidence(None, None, None, None, None, None)

    stem = filename.rsplit(".", 1)[0]

    multipack = _IMAGE_MULTIPACK_RE.search(stem)
    if multipack:
        return _metric_evidence(
            quantity_text=multipack.group("quantity"),
            unit_text=multipack.group("unit"),
            count=int(multipack.group("count")),
            source_text=filename,
            parse_method="edeka_image_metric_multipack",
            evidence_source="source_image_filename",
        )

    metric_matches = list(_IMAGE_SINGLE_METRIC_RE.finditer(stem))
    if metric_matches:
        # Use the last explicit metric token. This avoids UUID/source prefixes
        # and follows observed EDEKA filenames where package evidence appears
        # near the trailing product metadata.
        metric = metric_matches[-1]
        return _metric_evidence(
            quantity_text=metric.group("quantity"),
            unit_text=metric.group("unit"),
            count=1,
            source_text=filename,
            parse_method="edeka_image_metric_single",
            evidence_source="source_image_filename",
        )

    return PackageEvidence(
        None,
        None,
        None,
        filename,
        None,
        "source_image_filename",
    )


def _key_norm(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _gtin_check(digits: str) -> bool:
    if len(digits) not in {8, 12, 13, 14} or not digits.isdigit():
        return False

    body = digits[:-1]
    total = 0
    for offset, digit in enumerate(reversed(body), start=1):
        total += int(digit) * (3 if offset % 2 == 1 else 1)
    check = (10 - (total % 10)) % 10
    return check == int(digits[-1])


def normalize_gtin(value: Any) -> str | None:
    if value is None or isinstance(value, bool):
        return None

    digits = re.sub(r"[\s\-]", "", str(value).strip())
    if not digits.isdigit() or not _gtin_check(digits):
        return None

    return digits.zfill(14)


def _walk(value: Any, path: str = "$") -> Iterable[tuple[str, str, Any]]:
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            yield str(key), child_path, child
            yield from _walk(child, child_path)
    elif isinstance(value, list):
        for index, child in enumerate(value):
            yield from _walk(child, f"{path}[{index}]")


def extract_explicit_gtin(
    raw_payload: dict[str, Any] | None,
) -> tuple[str | None, dict[str, Any] | None]:
    payload = raw_payload or {}

    for key, path, value in _walk(payload):
        if _key_norm(key) not in _EXPLICIT_BARCODE_KEYS:
            continue

        normalized = normalize_gtin(value)
        if normalized is not None:
            return normalized, {
                "source": "raw_payload_explicit_barcode_key",
                "key_path": path,
                "raw_value": str(value),
            }

    return None, None


def normalize_offer_fields(
    *,
    offer_candidate_id: str,
    source_chain: str,
    source_store_external_id: str | None,
    source_offer_id: str | None,
    product_name_raw: str,
    brand_raw: str | None,
    package_text_raw: str | None,
    raw_payload: dict[str, Any] | None,
    source_image_url: str | None = None,
) -> NormalizedOffer:
    normalized_name = normalize_text(product_name_raw)
    if not normalized_name:
        raise ValueError("product name normalizes to empty")

    package = parse_package_text(package_text_raw)

    # Phase 3Cb proved that EDEKA package_text_raw is absent but first-party
    # source image filenames carry explicit metric package tokens in 220/340
    # persisted observations. Use this only as a retailer-specific fallback.
    if package.parse_method is None and source_chain == "edeka":
        image_package = parse_edeka_image_package(source_image_url)
        if image_package.parse_method is not None:
            package = image_package

    gtin14, gtin_evidence = extract_explicit_gtin(raw_payload)

    return NormalizedOffer(
        offer_candidate_id=offer_candidate_id,
        source_chain=source_chain,
        source_store_external_id=source_store_external_id,
        source_offer_id=source_offer_id,
        product_name_raw=product_name_raw,
        brand_raw=brand_raw,
        package_text_raw=package_text_raw,
        source_image_url=source_image_url,
        normalized_name=normalized_name,
        normalized_brand=normalize_brand(brand_raw),
        item_quantity_value=package.item_quantity_value,
        item_quantity_unit=package.item_quantity_unit,
        pack_count=package.pack_count,
        gtin14=gtin14,
        gtin_evidence=gtin_evidence,
        package_parse_method=package.parse_method,
        package_evidence_source=package.evidence_source,
        package_evidence_text=package.source_text,
    )


def package_relation(
    left: NormalizedOffer,
    right: NormalizedOffer,
) -> str:
    left_sig = left.package_signature()
    right_sig = right.package_signature()

    left_known = (
        left_sig[0] is not None
        or left_sig[1] == "piece"
    )
    right_known = (
        right_sig[0] is not None
        or right_sig[1] == "piece"
    )

    if not left_known and not right_known:
        return "both_missing"
    if not left_known or not right_known:
        return "one_missing"
    if left_sig == right_sig:
        return "exact"
    return "conflict"


def token_set(value: str) -> set[str]:
    return {
        token
        for token in normalize_text(value).split()
        if len(token) >= 3
    }


def fuzzy_score(
    left_name: str,
    right_name: str,
) -> tuple[float, float, float]:
    left_tokens = token_set(left_name)
    right_tokens = token_set(right_name)
    if not left_tokens or not right_tokens:
        return 0.0, 0.0, 0.0

    union = left_tokens | right_tokens
    jaccard = len(left_tokens & right_tokens) / len(union)
    sequence = SequenceMatcher(
        None,
        normalize_text(left_name),
        normalize_text(right_name),
    ).ratio()
    score = (jaccard * 0.60) + (sequence * 0.40)

    return round(score, 4), round(jaccard, 4), round(sequence, 4)


def _strip_exact_brand_prefix(
    normalized_name: str,
    normalized_brand: str | None,
) -> str | None:
    if not normalized_brand:
        return None

    prefix = normalized_brand + " "
    if not normalized_name.startswith(prefix):
        return None

    remainder = normalized_name[len(prefix):].strip()
    return remainder or None


def brand_prefix_name_relation(
    left: NormalizedOffer,
    right: NormalizedOffer,
) -> dict[str, Any] | None:
    right_without_left_brand = _strip_exact_brand_prefix(
        right.normalized_name,
        left.normalized_brand,
    )
    if (
        right_without_left_brand is not None
        and right_without_left_brand == left.normalized_name
    ):
        return {
            "brand": left.normalized_brand,
            "brand_source_chain": left.source_chain,
            "name_with_brand_chain": right.source_chain,
        }

    left_without_right_brand = _strip_exact_brand_prefix(
        left.normalized_name,
        right.normalized_brand,
    )
    if (
        left_without_right_brand is not None
        and left_without_right_brand == right.normalized_name
    ):
        return {
            "brand": right.normalized_brand,
            "brand_source_chain": right.source_chain,
            "name_with_brand_chain": left.source_chain,
        }

    return None


def review_candidate_evidence(
    left: NormalizedOffer,
    right: NormalizedOffer,
) -> dict[str, Any] | None:
    if left.source_chain == right.source_chain:
        return None

    relation = package_relation(left, right)
    if relation == "conflict":
        return None

    if left.gtin14 and right.gtin14:
        if left.gtin14 != right.gtin14:
            return None
        return {
            "method": "gtin_exact_review",
            "score": 1.0,
            "package_relation": relation,
            "evidence": {"gtin14": left.gtin14},
        }

    brand_relation = brand_prefix_name_relation(left, right)
    if brand_relation is not None:
        return {
            "method": (
                "brand_prefix_name_exact_package_review"
                if relation == "exact"
                else "brand_prefix_name_exact_incomplete_package_review"
            ),
            "score": 0.99 if relation == "exact" else 0.93,
            "package_relation": relation,
            "evidence": brand_relation,
        }

    if left.normalized_name == right.normalized_name:
        return {
            "method": "exact_name_review",
            "score": 0.88,
            "package_relation": relation,
            "evidence": {
                "normalized_name": left.normalized_name,
                "left_brand": left.normalized_brand,
                "right_brand": right.normalized_brand,
            },
        }

    score, jaccard, sequence = fuzzy_score(
        left.normalized_name,
        right.normalized_name,
    )

    # Restore the Phase 3Aa evidence-backed dual threshold as review-only.
    # This is NOT a generic lowering of the weighted threshold.
    if jaccard >= 0.60 and sequence >= 0.78:
        return {
            "method": "legacy_dual_threshold_review",
            "score": score,
            "package_relation": relation,
            "evidence": {
                "token_jaccard": jaccard,
                "sequence_ratio": sequence,
            },
        }

    if score >= 0.82 and jaccard >= 0.50 and sequence >= 0.75:
        return {
            "method": "weighted_fuzzy_review",
            "score": score,
            "package_relation": relation,
            "evidence": {
                "token_jaccard": jaccard,
                "sequence_ratio": sequence,
            },
        }

    return None


def deterministic_node_id(key: tuple[Any, ...]) -> str:
    payload = repr(key).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()[:20]


def jsonable_normalized_offer(
    value: NormalizedOffer,
) -> dict[str, Any]:
    data = asdict(value)
    if value.item_quantity_value is not None:
        data["item_quantity_value"] = format(
            value.item_quantity_value,
            "f",
        )
    return data
