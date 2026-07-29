from __future__ import annotations

import hashlib
import json
import re
import unicodedata
from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
from typing import Any, Iterable, Mapping, Sequence
from uuid import NAMESPACE_URL, UUID, uuid5

import pymupdf

from app.lidl.models import (
    CardSemanticOffer,
    DiscoveredFlyer,
    DisplayPriceObservation,
    LidlParseResult,
    PhysicalCard,
    ProductBinding,
    TextSpan,
    UnresolvedObservation,
)
from app.schemas import OfferCandidate, SourceChain

PARSER_VERSION = "lidl-pdf-v08c-r6"

# Lidl's display-price font is the source contract. Inline decimals in product
# copy, unit prices, UVPs, dates, and footers are deliberately not anchors.
_DISPLAY_PRICE_RE = re.compile(
    r"^\s*(\d{1,4})(?:[.,]\s?(\d{2})|[.,]\s*(-))?\s*\*\s*$"
)
_PLAIN_DISPLAY_PRICE_RE = re.compile(
    r"^\s*(\d{1,4})(?:[.,]\s?(\d{2})|[.,]\s*(-))?\s*$"
)
_INLINE_PRICE_RE = re.compile(r"(?<!\d)(\d{1,4})[,.](\d{2})(?!\d)")
_APP_RE = re.compile(r"\blidl\s*plus\b|\bplus[-\s]?preis\b", re.I)
_NORMAL_PRICE_RE = re.compile(
    r"\bnormalpreis\s*:?\s*(\d{1,4})[,.](\d{2})\b",
    re.I,
)
_VARIANT_RE = re.compile(
    r"\b(?:standard(?:größe)?|komfort(?:größe)?|comfort|king|queen)\b"
    r"|\b\d{2,3}\s*[x×]\s*\d{2,3}\s*cm\b",
    re.I,
)
_PACKAGE_UNIT = (
    r"(?:kg|mg|g|ml|cl|l|stück|stk\.?|paar|set|topf|packung|rolle|"
    r"dosen?|flaschen?|bund|strauß|strauss|tray|beutel|glas|tafel|"
    r"schale|karton)"
)
_PACKAGE_ATOM = (
    r"(?:(?:\d+\s*[x×]\s*)?\d+(?:[,.]\d+)?"
    r"(?:\s*[-–]\s*\d+(?:[,.]\d+)?)?)"
)
_PACKAGE_VALUE = rf"{_PACKAGE_ATOM}(?:\s*/\s*{_PACKAGE_ATOM})*\s*{_PACKAGE_UNIT}"
_PACKAGE_RE = re.compile(rf"\b({_PACKAGE_VALUE})\b", re.I)
_JE_PACKAGE_RE = re.compile(
    rf"\bje\s+(?:ca\.\s*)?({_PACKAGE_VALUE})\b",
    re.I,
)
_JE_BARE_UNIT_RE = re.compile(
    r"\bje\s+(stück|stk\.?|paar|set|topf|bund|strauß|strauss|"
    r"packung|rolle|beutel|glas|tafel|schale|karton)\b",
    re.I,
)
_CA_PACKAGE_RE = re.compile(rf"\bca\.\s*({_PACKAGE_VALUE})\b", re.I)
_PACKAGE_REJECT_RE = re.compile(
    r"%|€|\*|\b(?:uvp|lidl|normalpreis|aktion|gültig|wimpfen|gmbh|www|http)\b",
    re.I,
)
_SUSPICIOUS_TITLE_RE = re.compile(
    r"\b(?:preis\s+pro|normalpreis|tiefpreis|gultig|lidl\s*plus|uvp|aktion|"
    r"erhaltlich\s+ab|fur\s+(?:drinnen|draußen)|\d+\s*stuck)\b"
    r"|^garantie(?:\b|[\s–-])"
    r"|^\d+\s+fur\s+\d+$"
    r"|^\d+\s*\+\s*\d+\s+gratis$"
    r"|^\d+\s+eis\s+gratis\b"
    r"|^\d[\d.]*\s*[- ]?\s*teilig$"
    r"|^\d+er[- ]?(?:pack|netz|beutel)$"
    r"|^entspricht\b"
    r"|^\d+(?:[,.]\d+)?\s*(?:liter|kg|g|ml|cl)$"
    r"|mit\s+bio-baumwolle|^[a-z]$|%",
    re.I,
)


def _fold(value: str) -> str:
    normalized = unicodedata.normalize("NFKD", value.casefold()).replace("\u00ad", "")
    folded = "".join(char for char in normalized if not unicodedata.combining(char))
    return " ".join(folded.replace("®", "").replace("™", "").split())


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", _fold(value))


def _clean_text(value: str) -> str:
    return " ".join(value.split())


def _rounded_bbox(bbox: Iterable[float]) -> list[float]:
    return [round(float(value), 2) for value in bbox]


@dataclass(frozen=True)
class _StructuredProductPrice:
    product_id: str
    title: str
    price_eur: str


def _structured_product_prices(raw_fetch: bytes) -> tuple[_StructuredProductPrice, ...]:
    """Extract only the Schwarz product fields consumed by price rescue.

    The full mutable JSON response is deliberately not parser input. Only the
    product id, title, and structured price used as corroborating evidence are
    retained and fingerprinted.
    """

    try:
        payload = json.loads(raw_fetch)
    except (TypeError, ValueError, UnicodeDecodeError):
        return ()
    if not isinstance(payload, Mapping):
        return ()
    flyer_payload = payload.get("flyer")
    if not isinstance(flyer_payload, Mapping):
        flyer_payload = payload
    products = flyer_payload.get("products")
    if isinstance(products, Mapping):
        rows = products.values()
    elif isinstance(products, list):
        rows = products
    else:
        return ()

    dedup: dict[tuple[str, str, str], _StructuredProductPrice] = {}
    for row in rows:
        if not isinstance(row, Mapping):
            continue
        product_id = _clean_text(str(row.get("productId") or row.get("id") or ""))
        title = _clean_text(str(row.get("title") or row.get("name") or ""))
        raw_price = row.get("price")
        if not product_id or not title or raw_price is None or isinstance(raw_price, bool):
            continue
        try:
            price = Decimal(str(raw_price).replace(",", "."))
        except (InvalidOperation, ValueError):
            continue
        if price < 0:
            continue
        price_eur = f"{price.quantize(Decimal('0.01')):.2f}"
        item = _StructuredProductPrice(
            product_id=product_id,
            title=title,
            price_eur=price_eur,
        )
        dedup[(product_id, title, price_eur)] = item
    return tuple(
        sorted(
            dedup.values(),
            key=lambda item: (item.product_id, item.title, item.price_eur),
        )
    )


def _structured_price_row(
    item: _StructuredProductPrice | Mapping[str, Any],
) -> dict[str, str]:
    if isinstance(item, _StructuredProductPrice):
        product_id = item.product_id
        title = item.title
        price_eur = item.price_eur
    else:
        product_id = str(item["product_id"])
        title = str(item["title"])
        price_eur = str(item["price_eur"])
    return {
        "product_id": _clean_text(product_id),
        "title": _clean_text(title),
        "price_eur": _clean_text(price_eur),
    }


def _binding_row(binding: ProductBinding | Mapping[str, Any]) -> dict[str, Any]:
    if isinstance(binding, ProductBinding):
        page = binding.page
        product_id = binding.product_id
        title = binding.title
        bbox = binding.bbox
    else:
        page = int(binding["page"])
        product_id = str(binding["product_id"])
        title = str(binding["title"])
        bbox = tuple(binding["bbox"])
    return {
        "page": int(page),
        "product_id": _clean_text(product_id),
        "title": _clean_text(title),
        "bbox": _rounded_bbox(bbox),
    }


def parser_input_fingerprint_v1(
    pages: Iterable[Iterable[TextSpan | Mapping[str, Any]]],
    *,
    document_sha256: str | None = None,
    product_bindings: Iterable[ProductBinding | Mapping[str, Any]] = (),
    structured_product_prices: Iterable[
        _StructuredProductPrice | Mapping[str, Any]
    ] = (),
) -> str:
    """Fingerprint deterministic parser inputs.

    It includes every span field consumed by the parser plus the immutable PDF
    identity and sorted official product-binding observations. Mutable Schwarz
    response fields that the parser does not consume stay outside this hash.
    """

    canonical: list[dict[str, Any]] = []
    for page_index, spans in enumerate(pages):
        page_rows: list[dict[str, Any]] = []
        for span in spans:
            if isinstance(span, TextSpan):
                page = span.page
                bbox = span.bbox
                text_value = span.text
                font = span.font
                size = span.size
                flags = span.flags
            else:
                page = int(span.get("page", page_index))
                bbox = tuple(span["bbox"])
                text_value = str(span["text"])
                font = str(span.get("font") or "")
                size = float(span.get("size") or 0.0)
                flags = int(span.get("flags") or 0)
            text_value = _clean_text(text_value)
            if text_value:
                page_rows.append(
                    {
                        "page": page,
                        "bbox": _rounded_bbox(bbox),
                        "text": text_value,
                        "font": font,
                        "size": round(float(size), 4),
                        "flags": flags,
                    }
                )
        canonical.extend(
            sorted(
                page_rows,
                key=lambda item: (
                    item["page"],
                    item["bbox"],
                    item["text"],
                    item["font"],
                    item["size"],
                    item["flags"],
                ),
            )
        )

    bindings = sorted(
        (_binding_row(binding) for binding in product_bindings),
        key=lambda item: (
            item["page"],
            item["product_id"],
            item["title"],
            item["bbox"],
        ),
    )
    structured_prices = sorted(
        (_structured_price_row(item) for item in structured_product_prices),
        key=lambda item: (item["product_id"], item["title"], item["price_eur"]),
    )
    payload: Any
    if document_sha256 is None and not bindings and not structured_prices:
        payload = canonical
    else:
        payload = {
            "document_sha256": (
                document_sha256.strip().casefold() if document_sha256 is not None else None
            ),
            "product_bindings": bindings,
            "spans": canonical,
        }
        if structured_prices:
            payload["structured_product_prices"] = structured_prices
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode()
    return hashlib.sha256(b"lidl-parser-input-v1\0" + encoded).hexdigest()


def extract_pdf_spans(document: bytes) -> tuple[tuple[TextSpan, ...], ...]:
    """Extract immutable text observations, including font evidence."""

    pages: list[tuple[TextSpan, ...]] = []
    with pymupdf.open(stream=document, filetype="pdf") as pdf:
        for page_number, page in enumerate(pdf):
            spans: list[TextSpan] = []
            payload = page.get_text("dict", sort=True)
            for block in payload.get("blocks", []):
                if block.get("type") != 0:
                    continue
                for line in block.get("lines", []):
                    for raw_span in line.get("spans", []):
                        text_value = _clean_text(str(raw_span.get("text", "")))
                        bbox = raw_span.get("bbox")
                        if not (
                            text_value
                            and isinstance(bbox, (list, tuple))
                            and len(bbox) == 4
                        ):
                            continue
                        spans.append(
                            TextSpan(
                                page=page_number,
                                bbox=tuple(float(value) for value in bbox),
                                text=text_value,
                                font=str(raw_span.get("font") or ""),
                                size=float(raw_span.get("size") or 0.0),
                                flags=int(raw_span.get("flags") or 0),
                            )
                        )
            pages.append(
                tuple(
                    sorted(
                        spans,
                        key=lambda span: (
                            span.bbox[1],
                            span.bbox[0],
                            span.bbox,
                            span.text,
                            span.font,
                        ),
                    )
                )
            )
    return tuple(pages)


def _page_dimensions(
    document: bytes,
    pages: Sequence[Sequence[TextSpan]],
) -> tuple[tuple[float, float], ...]:
    try:
        with pymupdf.open(stream=document, filetype="pdf") as pdf:
            return tuple((float(page.rect.width), float(page.rect.height)) for page in pdf)
    except Exception:
        # This fallback keeps isolated stage tests useful; production PDFs take
        # the authoritative MediaBox dimensions above.
        return tuple(
            (
                max((span.bbox[2] for span in spans), default=1.0),
                max((span.bbox[3] for span in spans), default=1.0),
            )
            for spans in pages
        )


def fallback_source_offer_id(
    *,
    product_name: str,
    brand: str | None,
    package_text: str | None,
    variant_key: str = "",
) -> str:
    """Stable identity from intrinsic product text only.

    Price, validity, page, geometry, and snapshot identifiers remain absent.
    The optional semantic variant is intrinsic and preserves the old identity
    byte-for-byte when it is empty.
    """

    parts = (_fold(product_name), _fold(brand or ""), _fold(package_text or ""))
    identity = "|".join(parts)
    if variant_key:
        identity = f"{identity}|{_fold(variant_key)}"
    return f"lidl:fallback:{uuid5(NAMESPACE_URL, 'hermes-deals:lidl:' + identity)}"


def _display_price(span: TextSpan) -> str | None:
    if "lidlfontprice-pt" not in span.font.casefold() and (
        "lidlfontprice-wopt" not in span.font.casefold()
    ):
        return None
    if span.size < 20.0:
        return None
    match = _DISPLAY_PRICE_RE.fullmatch(span.text)
    if match is None:
        return None
    euros = int(match.group(1))
    cents = 0 if match.group(3) else int(match.group(2) or "00")
    return f"{euros}.{cents:02d}"


def _unstarred_display_price(span: TextSpan) -> str | None:
    """Return an unstarred PDF display price only for narrow rescue use.

    Unlike Stage 1, this deliberately excludes LidlFontPrice-WoPt and never
    creates a standalone offer. It can only corroborate an already bound
    product whose Schwarz structured price contradicts a starred assignment.
    """

    if "lidlfontprice-pt" not in span.font.casefold():
        return None
    if span.size < 20.0:
        return None
    match = _PLAIN_DISPLAY_PRICE_RE.fullmatch(span.text)
    if match is None:
        return None
    euros = int(match.group(1))
    cents = 0 if match.group(3) else int(match.group(2) or "00")
    return f"{euros}.{cents:02d}"


def _is_structured_rescue_price(price: DisplayPriceObservation) -> bool:
    return (
        "lidlfontprice-pt" in price.font.casefold()
        and _PLAIN_DISPLAY_PRICE_RE.fullmatch(price.text) is not None
        and _DISPLAY_PRICE_RE.fullmatch(price.text) is None
    )


def _intersection_area(
    first: Sequence[float],
    second: Sequence[float],
) -> float:
    width = max(0.0, min(first[2], second[2]) - max(first[0], second[0]))
    height = max(0.0, min(first[3], second[3]) - max(first[1], second[1]))
    return width * height


def _iou(first: Sequence[float], second: Sequence[float]) -> float:
    intersection = _intersection_area(first, second)
    first_area = max(0.0, first[2] - first[0]) * max(0.0, first[3] - first[1])
    second_area = max(0.0, second[2] - second[0]) * max(0.0, second[3] - second[1])
    union = first_area + second_area - intersection
    return intersection / union if union else 0.0


def extract_display_price_observations(
    pages: Iterable[Iterable[TextSpan]],
) -> tuple[DisplayPriceObservation, ...]:
    """Stage 1: find only starred, font-backed Lidl display-price anchors."""

    observations: list[DisplayPriceObservation] = []
    for spans in pages:
        for span in spans:
            value = _display_price(span)
            if value is None:
                continue
            observation = DisplayPriceObservation(
                page=span.page,
                bbox=span.bbox,
                text=span.text,
                price_eur=value,
                font=span.font,
                size=span.size,
            )
            if any(
                prior.page == observation.page
                and prior.price_eur == observation.price_eur
                and _iou(prior.bbox, observation.bbox) >= 0.80
                for prior in observations
            ):
                continue
            observations.append(observation)
    return tuple(
        sorted(
            observations,
            key=lambda item: (item.page, item.bbox[1], item.bbox[0], item.bbox, item.text),
        )
    )


# Short alias for callers that name the stage by its output.
extract_display_prices = extract_display_price_observations


def _bbox_union(boxes: Iterable[Sequence[float]]) -> tuple[float, float, float, float]:
    materialized = list(boxes)
    return (
        min(box[0] for box in materialized),
        min(box[1] for box in materialized),
        max(box[2] for box in materialized),
        max(box[3] for box in materialized),
    )


def _bbox_gap(first: Sequence[float], second: Sequence[float]) -> tuple[float, float]:
    horizontal = max(0.0, first[0] - second[2], second[0] - first[2])
    vertical = max(0.0, first[1] - second[3], second[1] - first[3])
    return horizontal, vertical


def _center(box: Sequence[float]) -> tuple[float, float]:
    return ((box[0] + box[2]) / 2.0, (box[1] + box[3]) / 2.0)


def _is_strict_title_span(span: TextSpan) -> bool:
    return (
        "lidlfontcondpro-bold" in span.font.casefold()
        and 8.5 <= span.size <= 11.5
    )


def _is_title_span(span: TextSpan) -> bool:
    if _is_strict_title_span(span):
        return True
    font = span.font.casefold()
    return (
        7.0 <= span.size <= 18.0
        and "lidlfontprice" not in font
        and (
            "bold" in font
            or "medium" in font
            or font.endswith("bdcn")
            or font.endswith("-bd")
        )
    )


@dataclass(frozen=True)
class _TitleLine:
    spans: tuple[TextSpan, ...]
    bbox: tuple[float, float, float, float]
    text: str


@dataclass(frozen=True)
class _TitleGroup:
    group_id: int
    page: int
    spans: tuple[TextSpan, ...]
    bbox: tuple[float, float, float, float]
    text: str
    strict: bool


def _title_lines(spans: Sequence[TextSpan]) -> list[_TitleLine]:
    rows: list[list[TextSpan]] = []
    for span in sorted(spans, key=lambda item: (_center(item.bbox)[1], item.bbox[0])):
        center_y = _center(span.bbox)[1]
        if rows:
            last = rows[-1]
            last_center = sum(_center(item.bbox)[1] for item in last) / len(last)
            x_gap = _bbox_gap(
                _bbox_union(item.bbox for item in last),
                span.bbox,
            )[0]
            if abs(center_y - last_center) <= 2.6 and x_gap <= 8.0:
                last.append(span)
                continue
        rows.append([span])
    result: list[_TitleLine] = []
    for row in rows:
        ordered = tuple(sorted(row, key=lambda item: (item.bbox[0], item.bbox[1], item.text)))
        result.append(
            _TitleLine(
                spans=ordered,
                bbox=_bbox_union(item.bbox for item in ordered),
                text=_clean_text(" ".join(item.text for item in ordered)),
            )
        )
    return result


def _join_title_lines(lines: Sequence[_TitleLine]) -> str:
    value = ""
    for line in lines:
        if value.endswith("-"):
            value = f"{value[:-1]}{line.text}"
        else:
            value = f"{value} {line.text}".strip()
    return _clean_text(value)


def _title_groups(spans: Sequence[TextSpan]) -> list[_TitleGroup]:
    candidates = [span for span in spans if _is_title_span(span)]
    lines = _title_lines(candidates)
    grouped: list[list[_TitleLine]] = []
    for line in lines:
        chosen: list[_TitleLine] | None = None
        best_score = float("inf")
        for group in reversed(grouped):
            prior = group[-1]
            vertical = line.bbox[1] - prior.bbox[3]
            if vertical < -2.0 or vertical > 7.5:
                continue
            overlap = max(
                0.0,
                min(line.bbox[2], prior.bbox[2]) - max(line.bbox[0], prior.bbox[0]),
            )
            left_delta = abs(line.bbox[0] - prior.bbox[0])
            center_delta = abs(_center(line.bbox)[0] - _center(prior.bbox)[0])
            width = max(line.bbox[2] - line.bbox[0], prior.bbox[2] - prior.bbox[0])
            if overlap <= 0.0 and left_delta > 12.0 and center_delta > width * 0.50:
                continue
            score = max(vertical, 0.0) + 0.05 * center_delta
            if score < best_score:
                chosen = group
                best_score = score
        if chosen is None:
            grouped.append([line])
        else:
            chosen.append(line)

    result: list[_TitleGroup] = []
    for group_id, group in enumerate(grouped):
        flat = tuple(span for line in group for span in line.spans)
        strict_spans = tuple(span for span in flat if _is_strict_title_span(span))
        if strict_spans:
            evidence_spans = strict_spans
            strict_lines = _title_lines(strict_spans)
            text_value = _join_title_lines(strict_lines)
            evidence_bbox = _bbox_union(span.bbox for span in strict_spans)
        else:
            evidence_spans = flat
            text_value = _join_title_lines(group)
            evidence_bbox = _bbox_union(line.bbox for line in group)
        if not text_value:
            continue
        result.append(
            _TitleGroup(
                group_id=group_id,
                page=flat[0].page,
                spans=evidence_spans,
                bbox=evidence_bbox,
                text=text_value,
                strict=bool(strict_spans),
            )
        )
    return result


def _title_cost(price: DisplayPriceObservation, title: _TitleGroup) -> float:
    horizontal, vertical = _bbox_gap(price.bbox, title.bbox)
    price_center = _center(price.bbox)
    title_center = _center(title.bbox)
    cost = (
        horizontal
        + 0.70 * vertical
        + 0.04 * abs(price_center[0] - title_center[0])
        + 0.02 * abs(price_center[1] - title_center[1])
    )
    if title.bbox[1] > price.bbox[3]:
        cost += 60.0
    if not title.strict:
        cost += 18.0
    if _is_suspicious_title(title.text):
        cost += 500.0
    return cost


def _minimum_assignment(costs: Sequence[Sequence[float]]) -> list[int]:
    """Rectangular Hungarian assignment; columns must be at least rows."""

    if not costs:
        return []
    row_count = len(costs)
    column_count = len(costs[0])
    if column_count < row_count:
        raise ValueError("assignment requires at least as many columns as rows")
    u = [0.0] * (row_count + 1)
    v = [0.0] * (column_count + 1)
    p = [0] * (column_count + 1)
    way = [0] * (column_count + 1)
    for row in range(1, row_count + 1):
        p[0] = row
        minimum = [float("inf")] * (column_count + 1)
        used = [False] * (column_count + 1)
        column0 = 0
        while True:
            used[column0] = True
            row0 = p[column0]
            delta = float("inf")
            column1 = 0
            for column in range(1, column_count + 1):
                if used[column]:
                    continue
                current = costs[row0 - 1][column - 1] - u[row0] - v[column]
                if current < minimum[column]:
                    minimum[column] = current
                    way[column] = column0
                if minimum[column] < delta:
                    delta = minimum[column]
                    column1 = column
            for column in range(column_count + 1):
                if used[column]:
                    u[p[column]] += delta
                    v[column] -= delta
                else:
                    minimum[column] -= delta
            column0 = column1
            if p[column0] == 0:
                break
        while True:
            column1 = way[column0]
            p[column0] = p[column1]
            column0 = column1
            if column0 == 0:
                break
    assignment = [-1] * row_count
    for column in range(1, column_count + 1):
        if p[column]:
            assignment[p[column] - 1] = column - 1
    return assignment


def _is_suspicious_title(value: str) -> bool:
    folded = _fold(value)
    return (
        len(re.sub(r"[^a-z]", "", folded)) < 3
        or _SUSPICIOUS_TITLE_RE.search(folded) is not None
        or (
            _VARIANT_RE.search(value) is not None
            and len(value.split()) <= 3
        )
    )


def _contains_or_near(box: Sequence[float], span_box: Sequence[float]) -> bool:
    if _intersection_area(box, span_box) > 0:
        return True
    horizontal, vertical = _bbox_gap(box, span_box)
    return horizontal <= 3.0 and vertical <= 2.0


def build_physical_cards(
    pages: Sequence[Sequence[TextSpan]],
    display_prices: Sequence[DisplayPriceObservation],
    *,
    product_bindings: Sequence[ProductBinding] = (),
    page_dimensions: Sequence[tuple[float, float]] = (),
) -> tuple[PhysicalCard, ...]:
    """Stage 2: globally assign title ownership, then form physical cards."""

    del product_bindings  # Bindings enrich semantic identity, not PDF title truth.
    by_page_prices: dict[int, list[DisplayPriceObservation]] = defaultdict(list)
    for price in display_prices:
        by_page_prices[price.page].append(price)

    card_rows: list[tuple[int, _TitleGroup | None, list[DisplayPriceObservation]]] = []
    for page_number, page_spans in enumerate(pages):
        prices = sorted(
            by_page_prices.get(page_number, []),
            key=lambda item: (item.bbox[1], item.bbox[0], item.bbox, item.price_eur),
        )
        if not prices:
            continue
        titles = _title_groups(tuple(page_spans))
        columns: list[tuple[_TitleGroup | None, int]] = [
            (title, 0)
            for title in titles
        ]
        columns.extend((None, index) for index in range(len(prices)))
        costs = [
            [
                450.0 + copy * 0.001
                if title is None
                else _title_cost(price, title)
                for title, copy in columns
            ]
            for price in prices
        ]
        assigned_columns = _minimum_assignment(costs)
        assignments: list[_TitleGroup | None] = []
        for row, column in enumerate(assigned_columns):
            title, _copy = columns[column]
            if title is None or _title_cost(prices[row], title) > 420.0:
                assignments.append(None)
            else:
                assignments.append(title)

        # A strict, globally unowned title may repair a generic/broken assigned
        # label, but never steals ownership from an already valid card.
        owned = {
            title.group_id
            for title in assignments
            if title is not None and not _is_suspicious_title(title.text)
        }
        for index, assigned in enumerate(assignments):
            if assigned is not None and not _is_suspicious_title(assigned.text):
                continue
            candidates = sorted(
                (
                    (_title_cost(prices[index], title), title)
                    for title in titles
                    if title.strict and title.group_id not in owned
                ),
                key=lambda item: (item[0], item[1].group_id),
            )
            if not candidates or candidates[0][0] > 420.0:
                continue
            margin = (
                candidates[1][0] - candidates[0][0]
                if len(candidates) > 1
                else 999.0
            )
            if margin < 8.0:
                continue
            assignments[index] = candidates[0][1]
            owned.add(candidates[0][1].group_id)

        # Shared parent headings such as "ESMARA MEN Slips/Boxer" own two
        # nearby rendered variants. The small regular label beside each price
        # provides the intrinsic child name without duplicating parent title
        # ownership.
        for index, price in enumerate(prices):
            parent_candidates = [
                title
                for title in titles
                if "/" in title.text and _title_cost(price, title) <= 210.0
            ]
            repairs: list[tuple[float, _TitleGroup]] = []
            for parent in parent_candidates:
                match = re.search(r"(\S+)\s*/\s*(\S+)\s*$", parent.text)
                if match is None:
                    continue
                alternatives = (match.group(1), match.group(2))
                expanded_alternatives = list(alternatives)
                first_hyphen = re.match(r"(.+?)[-–](\S+)$", alternatives[0])
                if first_hyphen is not None:
                    shared_variant_prefix = first_hyphen.group(1).rstrip("-– ")
                    inherited = f"{shared_variant_prefix}-{alternatives[1]}"
                    if _compact(inherited) not in {
                        _compact(value) for value in expanded_alternatives
                    }:
                        expanded_alternatives.append(inherited)
                raw_prefix = parent.text[: match.start()].strip()
                brand_tokens: list[str] = []
                prefix_tokens = raw_prefix.split()
                for token in prefix_tokens:
                    letters = re.sub(r"[^A-Za-zÄÖÜäöüß]", "", token)
                    if letters and letters == letters.upper():
                        brand_tokens.append(token)
                    else:
                        break
                prefix = " ".join(brand_tokens) or raw_prefix
                shared_tail = " ".join(prefix_tokens[len(brand_tokens) :]).strip()
                for span in page_spans:
                    if not 6.0 <= span.size <= 9.0:
                        continue
                    span_compact = _compact(span.text)
                    label = next(
                        (
                            alternative
                            for alternative in expanded_alternatives
                            if span_compact == _compact(alternative)
                            or (
                                shared_tail
                                and span_compact
                                == _compact(f"{shared_tail}{alternative}")
                            )
                        ),
                        None,
                    )
                    if label is None:
                        continue
                    horizontal, vertical = _bbox_gap(span.bbox, price.bbox)
                    if horizontal > 100.0 or vertical > 85.0:
                        continue
                    repairs.append(
                        (
                            horizontal
                            + 0.7 * vertical
                            + 0.05
                            * abs(_center(span.bbox)[0] - _center(price.bbox)[0]),
                            _TitleGroup(
                                group_id=-(page_number * 1000 + index + 1),
                                page=page_number,
                                spans=(*parent.spans, span),
                                bbox=_bbox_union((parent.bbox, span.bbox)),
                                text=_clean_text(f"{prefix} {span.text}"),
                                strict=True,
                            ),
                        )
                    )
            if repairs:
                repair_score, repair = min(repairs, key=lambda item: (item[0], item[1].text))
                assigned = assignments[index]
                if (
                    assigned is None
                    or _is_suspicious_title(assigned.text)
                    or repair_score <= 120.0
                    or _title_cost(price, repair) + repair_score * 0.05
                    < _title_cost(price, assigned)
                ):
                    assignments[index] = repair

        # Start from one physical owner per anchor. Merge only evidence-proven
        # pairs: a scoped Plus anchor with one nearby higher base anchor, or
        # two anchors carrying distinct local size labels.
        pairs: list[tuple[int, int]] = []
        consumed: set[int] = set()
        markers = [span for span in page_spans if _APP_RE.search(span.text)]
        plus_indexes = {
            index
            for index, price in enumerate(prices)
            if any(_marker_belongs_to_price(marker.bbox, price.bbox) for marker in markers)
        }

        def has_explicit_normal_price(app_index: int) -> bool:
            app = prices[app_index]
            title = assignments[app_index]
            evidence_boxes = [app.bbox]
            if title is not None:
                evidence_boxes.append(title.bbox)
            evidence_bbox = _bbox_union(evidence_boxes)
            scope = (
                evidence_bbox[0] - 20.0,
                evidence_bbox[1] - 50.0,
                evidence_bbox[2] + 20.0,
                evidence_bbox[3] + 50.0,
            )
            local_spans = tuple(
                span for span in page_spans if _contains_or_near(scope, span.bbox)
            )
            local_card = PhysicalCard(
                page=page_number,
                card_index=-1,
                bbox=scope,
                spans=local_spans,
                prices=(app,),
                title=title.text if title is not None else None,
                title_bbox=title.bbox if title is not None else None,
            )
            return bool(_explicit_normal_prices(local_card, app))

        for app_index in sorted(plus_indexes):
            # An explicit local Normalpreis is stronger base-price evidence than
            # a merely nearby higher starred anchor. Keep such Plus anchors as
            # singleton cards; Stage 3 will use the explicit Normalpreis.
            if has_explicit_normal_price(app_index):
                continue
            app = prices[app_index]
            app_center = _center(app.bbox)
            candidates: list[tuple[float, int]] = []
            for base_index, base in enumerate(prices):
                if base_index == app_index or _decimal(base.price_eur) <= _decimal(app.price_eur):
                    continue
                base_center = _center(base.bbox)
                x_delta = abs(base_center[0] - app_center[0])
                y_delta = abs(base_center[1] - app_center[1])
                if x_delta > 95.0 or y_delta > 110.0:
                    continue
                app_title = assignments[app_index]
                base_title = assignments[base_index]
                similarity = (
                    _title_similarity(app_title.text, base_title.text)
                    if app_title is not None and base_title is not None
                    else 1.0
                )
                candidates.append((x_delta + 0.45 * y_delta - 15.0 * similarity, base_index))
            if candidates:
                _score, base_index = min(candidates)
                if app_index not in consumed and base_index not in consumed:
                    pairs.append((base_index, app_index))
                    consumed.update((base_index, app_index))

        def local_variant(index: int) -> str | None:
            price = prices[index]
            candidates: list[tuple[float, str]] = []
            for span in page_spans:
                match = _VARIANT_RE.search(span.text)
                if match is None or span.size > 11.5:
                    continue
                horizontal, vertical = _bbox_gap(span.bbox, price.bbox)
                if horizontal <= 110.0 and vertical <= 70.0:
                    candidates.append(
                        (
                            horizontal
                            + 0.7 * vertical
                            + 0.05
                            * abs(_center(span.bbox)[0] - _center(price.bbox)[0]),
                            _clean_text(match.group(0)),
                        )
                    )
            return min(candidates)[1] if candidates else None

        labels = {index: local_variant(index) for index in range(len(prices))}
        for first in range(len(prices)):
            if first in consumed or not labels[first]:
                continue
            for second in range(first + 1, len(prices)):
                if second in consumed or not labels[second]:
                    continue
                first_center = _center(prices[first].bbox)
                second_center = _center(prices[second].bbox)
                if (
                    abs(first_center[1] - second_center[1]) <= 35.0
                    and abs(first_center[0] - second_center[0]) <= 210.0
                    and _fold(labels[first] or "") != _fold(labels[second] or "")
                ):
                    pairs.append((first, second))
                    consumed.update((first, second))
                    break

        groups = [list(pair) for pair in pairs]
        groups.extend([index] for index in range(len(prices)) if index not in consumed)
        for group in sorted(
            groups,
            key=lambda indexes: (
                min(prices[index].bbox[1] for index in indexes),
                min(prices[index].bbox[0] for index in indexes),
            ),
        ):
            group_titles = [
                assignments[index]
                for index in group
                if assignments[index] is not None
                and not _is_suspicious_title(assignments[index].text)
            ]
            title: _TitleGroup | None = None

            # For a proven Lidl Plus pair the Plus anchor's own strict local
            # title is stronger evidence than a nearby higher base anchor's
            # title. This prevents dense layouts from turning Sneaker into the
            # neighboring Feinstrick product.
            app_group = [index for index in group if index in plus_indexes]
            app_title_candidates = sorted(
                (
                    (_title_cost(prices[index], assignments[index]), assignments[index])
                    for index in app_group
                    if assignments[index] is not None
                    and assignments[index].strict
                    and not _is_suspicious_title(assignments[index].text)
                ),
                key=lambda item: (item[0], item[1].group_id),
            )
            if app_title_candidates and app_title_candidates[0][0] <= 160.0:
                title = app_title_candidates[0][1]

            # Size-variant pairs share one product heading. Rank strict titles
            # against the whole pair, not just whichever anchor happens to be
            # first after global assignment. This rejects page headings such
            # as "Wohnen & Einrichtung" when a strong Steppbett title explains
            # both 135x200 and 155x220 prices.
            if title is None and len(group) > 1 and all(labels.get(index) for index in group):
                shared_candidates = sorted(
                    (
                        (
                            sum(_title_cost(prices[index], candidate) for index in group),
                            candidate,
                        )
                        for candidate in titles
                        if candidate.strict
                        and not _is_suspicious_title(candidate.text)
                        and min(_title_cost(prices[index], candidate) for index in group) <= 210.0
                    ),
                    key=lambda item: (item[0], item[1].group_id),
                )
                if shared_candidates:
                    title = shared_candidates[0][1]

            if title is None:
                first_title = assignments[group[0]]
                if first_title is not None and not _is_suspicious_title(first_title.text):
                    title = first_title
                else:
                    title = max(
                        group_titles,
                        key=lambda item: (len(item.text), -item.group_id),
                        default=next(
                            (
                                assignments[index]
                                for index in group
                                if assignments[index] is not None
                            ),
                            None,
                        ),
                    )
            card_rows.append((page_number, title, [prices[index] for index in group]))

    cards: list[PhysicalCard] = []
    for card_index, (page_number, title, prices) in enumerate(card_rows):
        evidence_boxes = [price.bbox for price in prices]
        if title is not None:
            evidence_boxes.append(title.bbox)
        evidence_bbox = _bbox_union(evidence_boxes)
        width, height = (
            page_dimensions[page_number]
            if page_number < len(page_dimensions)
            else (
                max((span.bbox[2] for span in pages[page_number]), default=evidence_bbox[2]),
                max((span.bbox[3] for span in pages[page_number]), default=evidence_bbox[3]),
            )
        )
        card_bbox = (
            max(0.0, evidence_bbox[0] - 28.0),
            max(0.0, evidence_bbox[1] - 65.0),
            min(width, evidence_bbox[2] + 28.0),
            min(height, evidence_bbox[3] + 65.0),
        )
        local_spans = tuple(
            sorted(
                (
                    span
                    for span in pages[page_number]
                    if _contains_or_near(card_bbox, span.bbox)
                ),
                key=lambda span: (span.bbox[1], span.bbox[0], span.bbox, span.text),
            )
        )
        cards.append(
            PhysicalCard(
                page=page_number,
                card_index=card_index,
                bbox=card_bbox,
                spans=local_spans,
                prices=tuple(
                    sorted(
                        prices,
                        key=lambda price: (
                            price.bbox[1],
                            price.bbox[0],
                            price.bbox,
                            price.price_eur,
                        ),
                    )
                ),
                title=title.text if title is not None else None,
                title_bbox=title.bbox if title is not None else None,
            )
        )
    return tuple(cards)


def _decimal(value: str) -> Decimal:
    return Decimal(value).quantize(Decimal("0.01"))


def _price_from_inline(text_value: str) -> Decimal | None:
    match = _INLINE_PRICE_RE.search(text_value)
    if match is None:
        return None
    try:
        return Decimal(f"{match.group(1)}.{match.group(2)}")
    except InvalidOperation:
        return None


def _marker_belongs_to_price(
    marker_bbox: Sequence[float],
    price_bbox: Sequence[float],
) -> bool:
    vertical = price_bbox[1] - marker_bbox[3]
    overlap = max(
        0.0,
        min(marker_bbox[2], price_bbox[2]) - max(marker_bbox[0], price_bbox[0]),
    )
    minimum_width = max(
        1.0,
        min(marker_bbox[2] - marker_bbox[0], price_bbox[2] - price_bbox[0]),
    )
    center_delta = abs(_center(marker_bbox)[0] - _center(price_bbox)[0])
    return -8.0 <= vertical <= 55.0 and (
        overlap / minimum_width >= 0.20 or center_delta <= 45.0
    )


def _app_anchor_indexes(card: PhysicalCard) -> set[int]:
    markers = [span for span in card.spans if _APP_RE.search(span.text)]
    result: set[int] = set()
    for marker in markers:
        candidates = [
            (
                abs(card.prices[index].bbox[1] - marker.bbox[3])
                + 0.20
                * abs(_center(card.prices[index].bbox)[0] - _center(marker.bbox)[0]),
                index,
            )
            for index in range(len(card.prices))
            if _marker_belongs_to_price(marker.bbox, card.prices[index].bbox)
        ]
        if candidates:
            result.add(min(candidates)[1])
    return result


def _explicit_normal_prices(
    card: PhysicalCard,
    app_anchor: DisplayPriceObservation,
) -> list[Decimal]:
    """Return only the best geometry-bound explicit Normalpreis value(s).

    Dense Lidl layouts can expose a neighboring card's ``Normalpreis`` inside
    the expanded card bbox. Rank the label/value evidence against the actual
    Plus anchor instead of collecting every textual match. Split forms such as
    ``Normalpreis:`` followed by ``3.39; 1 kg = 11.30`` are valid: the leading
    product price is the evidence and the semicolon tail is only unit-price
    context.
    """

    app_value = _decimal(app_anchor.price_eur)
    ranked: list[tuple[float, Decimal]] = []
    ordered = sorted(card.spans, key=lambda span: (span.bbox[1], span.bbox[0]))

    def add_candidate(value: Decimal, evidence_bbox: Sequence[float], *, alignment: float = 0.0) -> None:
        if value <= app_value:
            return
        horizontal, vertical = _bbox_gap(evidence_bbox, app_anchor.bbox)
        if horizontal > 90.0 or vertical > 75.0:
            return
        center_delta = abs(_center(evidence_bbox)[0] - _center(app_anchor.bbox)[0])
        score = horizontal + 0.70 * vertical + 0.08 * center_delta + alignment
        ranked.append((score, value))

    for span in ordered:
        for match in _NORMAL_PRICE_RE.finditer(span.text):
            add_candidate(
                Decimal(f"{match.group(1)}.{match.group(2)}"),
                span.bbox,
            )

    leading_price_re = re.compile(r"^\s*(\d{1,4})[,.](\d{2})(?!\d)")
    for index, span in enumerate(ordered):
        if "normalpreis" not in _fold(span.text):
            continue
        if _INLINE_PRICE_RE.search(span.text):
            continue
        for following in ordered[index + 1 : index + 4]:
            horizontal, vertical = _bbox_gap(span.bbox, following.bbox)
            if horizontal > 45.0 or vertical > 14.0:
                continue
            match = leading_price_re.match(following.text)
            if match is None:
                continue
            value = Decimal(f"{match.group(1)}.{match.group(2)}")
            evidence_bbox = _bbox_union((span.bbox, following.bbox))
            left_alignment = 0.12 * abs(span.bbox[0] - following.bbox[0])
            add_candidate(value, evidence_bbox, alignment=left_alignment)

    if not ranked:
        return []
    ranked.sort(key=lambda item: (item[0], item[1]))
    best_score = ranked[0][0]
    return sorted(
        {
            value
            for score, value in ranked
            if score <= best_score + 2.0
        }
    )

def _small_reference_prices(
    card: PhysicalCard,
    app_anchor: DisplayPriceObservation,
) -> list[Decimal]:
    app_value = _decimal(app_anchor.price_eur)
    candidates: list[tuple[float, Decimal]] = []
    ordered = sorted(card.spans, key=lambda span: (span.bbox[1], span.bbox[0]))
    for index, span in enumerate(ordered):
        if "lidlfontprice" in span.font.casefold() or not 7.5 <= span.size <= 10.5:
            continue
        horizontal, vertical = _bbox_gap(span.bbox, app_anchor.bbox)
        if horizontal > 95.0 or vertical > 65.0:
            continue
        folded = _fold(span.text)
        nearby_prefix = " ".join(item.text for item in ordered[max(0, index - 2) : index])
        if (
            "=" in span.text
            or "%" in span.text
            or "uvp" in folded
            or "=" in nearby_prefix
        ):
            continue
        value = _price_from_inline(span.text)
        if value is not None and value > app_value:
            center_delta = abs(
                _center(span.bbox)[0] - _center(app_anchor.bbox)[0]
            )
            candidates.append((horizontal + 0.7 * vertical + 0.1 * center_delta, value))
    if not candidates:
        return []
    candidates.sort(key=lambda item: (item[0], item[1]))
    best_score = candidates[0][0]
    near_best = {
        value
        for score, value in candidates
        if score <= best_score + 2.0
    }
    # A split unit-price tail is normally the larger number. When geometry is
    # effectively tied, the lower local reference is the conservative base
    # price and avoids promoting a per-kilo value to the product price.
    return [min(near_best)]


def _variant_assignments(card: PhysicalCard) -> dict[int, str]:
    candidates: list[tuple[float, int, TextSpan, str]] = []
    for span in card.spans:
        match = _VARIANT_RE.search(span.text)
        if match is None or span.size > 11.5:
            continue
        label = _clean_text(match.group(0))
        for index, price in enumerate(card.prices):
            horizontal, vertical = _bbox_gap(span.bbox, price.bbox)
            if horizontal > 80.0 or vertical > 60.0:
                continue
            distance = horizontal + 0.7 * vertical + 0.05 * abs(
                _center(span.bbox)[0] - _center(price.bbox)[0]
            )
            candidates.append((distance, index, span, label))
    assignments: dict[int, str] = {}
    used_spans: set[tuple[float, float, float, float]] = set()
    for _distance, index, span, label in sorted(
        candidates,
        key=lambda row: (row[0], row[1], row[2].bbox, row[3]),
    ):
        if index in assignments or span.bbox in used_spans:
            continue
        assignments[index] = label
        used_spans.add(span.bbox)
    if len(set(_fold(value) for value in assignments.values())) != len(assignments):
        return {}
    return assignments


def _package_local_spans(card: PhysicalCard) -> tuple[TextSpan, ...]:
    """Return the narrow product/price evidence lane used for package parsing."""

    boxes: list[Sequence[float]] = [price.bbox for price in card.prices]
    if card.title_bbox is not None:
        boxes.append(card.title_bbox)
    if not boxes:
        return card.spans

    evidence = _bbox_union(boxes)
    local_box = (
        evidence[0] - 24.0,
        evidence[1] - 22.0,
        evidence[2] + 24.0,
        evidence[3] + 28.0,
    )

    result = []
    for span in card.spans:
        cx, cy = _center(span.bbox)
        if (
            local_box[0] <= cx <= local_box[2]
            and local_box[1] <= cy <= local_box[3]
        ):
            result.append(span)

    return tuple(
        sorted(
            result,
            key=lambda span: (span.bbox[1], span.bbox[0], span.bbox, span.text),
        )
    )


def _normalize_package(value: str) -> str:
    value = _clean_text(value).rstrip(".,;")
    value = re.sub(r"\s*/\s*", "/", value)
    value = re.sub(r"(\d)\s*[x×]\s*(?=\d)", r"\1x ", value, flags=re.I)
    return value


def _package_text(card: PhysicalCard) -> tuple[str | None, tuple[str, ...]]:
    local_spans = _package_local_spans(card)
    # Large display-price glyphs can sit geometrically between two consecutive
    # package-copy lines in PDF reading order (for example Corny
    # ``Je 6x 25/`` + ``6x 20/4x 30 g``). They are price evidence, never
    # package text, so exclude them before reconstructing the package phrase.
    package_text_spans = tuple(
        span
        for span in local_spans
        if "lidlfontprice" not in span.font.casefold()
    )
    ordered_text = " ".join(span.text for span in package_text_spans)
    folded_text = _fold(ordered_text)
    folded_title = _fold(card.title or "")

    if re.search(r"\bpreis\s+nach\s+gewicht\b|\bnach\s+gewicht\b", folded_text):
        return "nach Gewicht", ("nach Gewicht",)
    if (
        (" lose" in f" {folded_title}" or folded_title.endswith("lose"))
        and re.search(r"\bkg[-\s]?preis\b", folded_text)
    ):
        return "nach Gewicht", ("nach Gewicht",)
    if (
        _CA_PACKAGE_RE.search(ordered_text)
        and re.search(r"\bkg[-\s]?preis\b", folded_text)
        and _JE_PACKAGE_RE.search(ordered_text) is None
    ):
        return "nach Gewicht", ("nach Gewicht",)

    ranked: list[tuple[int, int, str]] = []

    for match in _JE_PACKAGE_RE.finditer(ordered_text):
        value = _normalize_package(match.group(1))
        if value and not _PACKAGE_REJECT_RE.search(value):
            ranked.append((0, match.start(), value))

    for match in _JE_BARE_UNIT_RE.finditer(ordered_text):
        value = _normalize_package(match.group(1))
        if value and not _PACKAGE_REJECT_RE.search(value):
            ranked.append((0, match.start(), value))

    if card.title:
        for match in _PACKAGE_RE.finditer(card.title):
            value = _normalize_package(match.group(1))
            if value and not _PACKAGE_REJECT_RE.search(value):
                ranked.append((1, match.start(), value))

    for index, span in enumerate(local_spans):
        if "=" in span.text or _PACKAGE_REJECT_RE.search(span.text):
            continue
        match = _PACKAGE_RE.fullmatch(span.text.strip(" ,.;"))
        if match is not None:
            value = _normalize_package(match.group(1))
            ranked.append((2, index, value))

    if not ranked:
        return None, ()

    best_rank = min(rank for rank, _position, _value in ranked)
    best = [row for row in ranked if row[0] == best_rank]
    chosen = min(
        best,
        key=lambda row: (row[1], _fold(row[2]), row[2]),
    )[2]
    return chosen, (chosen,)

def _date_for_mmdd(day: int, month: int, flyer: DiscoveredFlyer) -> date | None:
    reference = flyer.valid_from or flyer.valid_until
    if reference is None:
        return None
    possibilities: list[date] = []
    for year in (reference.year - 1, reference.year, reference.year + 1):
        try:
            possibilities.append(date(year, month, day))
        except ValueError:
            continue
    if not possibilities:
        return None
    return min(possibilities, key=lambda value: abs((value - reference).days))


def _validity_candidates(
    text_value: str,
    flyer: DiscoveredFlyer,
) -> list[tuple[int, int, date | None, date | None, str, bool]]:
    candidates: list[tuple[int, int, date | None, date | None, str, bool]] = []
    patterns: tuple[tuple[int, str, re.Pattern[str]], ...] = (
        (
            0,
            "gueltig_vom_bis",
            re.compile(
                r"gültig\s+vom\s+(?:[A-Za-zÄÖÜäöüß]+\.?,?\s*)?"
                r"(\d{1,2})\.(\d{1,2})\."
                r"\s*(?:bis|[-–])\s*(?:[A-Za-zÄÖÜäöüß]+\.?,?\s*)?"
                r"(\d{1,2})\.(\d{1,2})\.",
                re.I,
            ),
        ),
        (
            1,
            "gueltig_am",
            re.compile(
                r"gültig\s+am\s+(?:[A-Za-zÄÖÜäöüß]+\.?,?\s*)?"
                r"(\d{1,2})\.(\d{1,2})\.",
                re.I,
            ),
        ),
        (
            2,
            "ab_bis",
            re.compile(
                r"\bab\s+(?:[A-Za-zÄÖÜäöüß]+\.?,?\s*)?"
                r"(\d{1,2})\.(\d{1,2})\."
                r"(?:\s*bis\s*(?:[A-Za-zÄÖÜäöüß]+\.?,?\s*)?"
                r"(\d{1,2})\.(\d{1,2})\.)?",
                re.I,
            ),
        ),
    )
    for priority, source, pattern in patterns:
        for match in pattern.finditer(text_value):
            start = _date_for_mmdd(int(match.group(1)), int(match.group(2)), flyer)
            if source == "gueltig_am":
                end = start
            elif match.lastindex and match.lastindex >= 4 and match.group(3):
                end = _date_for_mmdd(int(match.group(3)), int(match.group(4)), flyer)
            else:
                end = flyer.valid_until
            prefix = text_value[max(0, match.start() - 140) : match.start()]
            candidates.append(
                (
                    priority,
                    match.start(),
                    start,
                    end,
                    source,
                    _APP_RE.search(prefix) is not None,
                )
            )
    return sorted(candidates, key=lambda row: (row[0], row[1], row[4]))


def _validity(
    card: PhysicalCard,
    flyer: DiscoveredFlyer,
    *,
    requires_app: bool,
    anchor_indexes: Sequence[int] = (),
) -> tuple[
    date | None,
    date | None,
    str,
    date | None,
    date | None,
    str | None,
]:
    ordered_spans = sorted(card.spans, key=lambda span: (span.bbox[1], span.bbox[0]))
    text_value = " ".join(span.text for span in ordered_spans)
    candidates = _validity_candidates(text_value, flyer)
    base = next((row for row in candidates if not row[5]), None)

    app = None
    if requires_app:
        # App validity must be bound to the actual Lidl Plus price geometry.
        # A card-level text window can contain neighboring Plus validity text
        # in dense layouts (e.g. adjacent luggage variants), so never promote
        # an app range from the whole expanded card alone.
        app_indexes = _app_anchor_indexes(card)
        scoped_indexes = [
            index for index in anchor_indexes if index in app_indexes
        ] or sorted(app_indexes)
        scoped_spans: list[TextSpan] = []
        for index in scoped_indexes:
            if index >= len(card.prices):
                continue
            price = card.prices[index]
            scope = (
                price.bbox[0] - 22.0,
                price.bbox[1] - 85.0,
                price.bbox[2] + 22.0,
                price.bbox[3] + 70.0,
            )
            scoped_spans.extend(
                span for span in ordered_spans if _contains_or_near(scope, span.bbox)
            )
        if scoped_spans:
            scoped_unique = sorted(
                {
                    (span.page, span.bbox, span.text, span.font, span.size, span.flags): span
                    for span in scoped_spans
                }.values(),
                key=lambda span: (span.bbox[1], span.bbox[0], span.bbox, span.text),
            )
            app_text = " ".join(span.text for span in scoped_unique)
            app_candidates = _validity_candidates(app_text, flyer)
            app = next((row for row in app_candidates if row[5]), None)
    if base is None:
        base_from, base_until, base_source = (
            flyer.valid_from,
            flyer.valid_until,
            "flyer_default",
        )
    else:
        base_from, base_until, base_source = base[2], base[3], base[4]
    if not requires_app:
        return base_from, base_until, base_source, None, None, None
    if app is not None:
        app_from, app_until, app_source = app[2], app[3], app[4]
    else:
        app_from, app_until, app_source = base_from, base_until, "inherits_base"
    if (app_from is None) != (app_until is None):
        app_from = app_until = None
        app_source = None
    return (
        base_from,
        base_until,
        base_source,
        app_from,
        app_until,
        app_source,
    )


def _binding_values(
    binding: ProductBinding | Mapping[str, Any],
) -> tuple[int, str, str, tuple[float, float, float, float]]:
    if isinstance(binding, ProductBinding):
        return binding.page, binding.product_id, binding.title, binding.bbox
    return (
        int(binding["page"]),
        str(binding["product_id"]),
        str(binding["title"]),
        tuple(float(value) for value in binding["bbox"]),
    )


def _title_similarity(first: str, second: str) -> float:
    first_compact = _compact(first)
    second_compact = _compact(second)
    if not first_compact or not second_compact:
        return 0.0
    # Schwarz titles often enrich the exact PDF product title with package,
    # model, volume, or audience suffixes. Containment is therefore stronger
    # identity evidence than raw edit similarity.
    if first_compact in second_compact or second_compact in first_compact:
        return 1.0
    return SequenceMatcher(None, first_compact, second_compact).ratio()


def _official_binding(
    card: PhysicalCard,
    *,
    product_name: str,
    product_bindings: Sequence[ProductBinding | Mapping[str, Any]],
    page_dimensions: Sequence[tuple[float, float]],
) -> tuple[str | None, str | None, dict[str, Any] | None]:
    if card.page >= len(page_dimensions):
        return None, None, None
    width, height = page_dimensions[card.page]
    scored: list[tuple[float, int, int, float, str, str, tuple[float, ...]]] = []
    for binding in product_bindings:
        page, product_id, title, normalized_bbox = _binding_values(binding)
        if page != card.page:
            continue
        absolute = (
            normalized_bbox[0] * width,
            normalized_bbox[1] * height,
            normalized_bbox[2] * width,
            normalized_bbox[3] * height,
        )
        expanded = (
            absolute[0] - 0.035 * width,
            absolute[1] - 0.055 * height,
            absolute[2] + 0.035 * width,
            absolute[3] + 0.055 * height,
        )
        inside = sum(
            absolute[0] <= _center(price.bbox)[0] <= absolute[2]
            and absolute[1] <= _center(price.bbox)[1] <= absolute[3]
            for price in card.prices
        )
        near = sum(
            expanded[0] <= _center(price.bbox)[0] <= expanded[2]
            and expanded[1] <= _center(price.bbox)[1] <= expanded[3]
            for price in card.prices
        ) - inside
        similarity = _title_similarity(product_name, title)
        score = inside * 8.0 + near * 3.0 + similarity * 5.0
        scored.append(
            (
                score,
                inside,
                near,
                similarity,
                product_id,
                title,
                absolute,
            )
        )
    if not scored:
        return None, None, None
    scored.sort(key=lambda row: (-row[0], row[4], row[5], row[6]))
    best = scored[0]
    margin = best[0] - scored[1][0] if len(scored) > 1 else 999.0
    if not (
        (best[1] > 0 and margin >= 0.75)
        or (best[3] >= 0.92 and margin >= 1.0)
    ):
        return None, None, None
    evidence = {
        "score": round(best[0], 4),
        "inside": best[1],
        "near": best[2],
        "title_similarity": round(best[3], 4),
        "runner_up_margin": round(margin, 4),
        "bbox": _rounded_bbox(best[6]),
    }
    return best[4], best[5], evidence


def _rescue_structured_card_prices(
    cards: Sequence[PhysicalCard],
    *,
    pages: Sequence[Sequence[TextSpan]],
    product_bindings: Sequence[ProductBinding | Mapping[str, Any]],
    structured_product_prices: Sequence[_StructuredProductPrice],
) -> tuple[PhysicalCard, ...]:
    """Replace only proven starred misassignments with corroborated prices.

    A rescue requires all of the following:
    * one already-formed single-price card with a non-suspicious title;
    * an official page binding whose title essentially matches the card title;
    * a Schwarz structured price that contradicts the currently assigned
      starred price; and
    * an unstarred LidlFontPrice-Pt span carrying that exact structured price
      within a very strong local title geometry (cost <= 30).

    Unstarred prices never create cards on their own. This keeps ordinary
    online/regular-price typography outside the production offer surface.
    """

    structured_by_id: dict[str, list[_StructuredProductPrice]] = defaultdict(list)
    for item in structured_product_prices:
        structured_by_id[item.product_id].append(item)

    bindings_by_page: dict[int, list[tuple[int, str, str, tuple[float, ...]]]] = defaultdict(list)
    for binding in product_bindings:
        page, product_id, title, bbox = _binding_values(binding)
        bindings_by_page[page].append((page, product_id, title, bbox))

    result: list[PhysicalCard] = []
    for card in cards:
        if (
            len(card.prices) != 1
            or not card.title
            or card.title_bbox is None
            or _is_suspicious_title(card.title)
            or _DISPLAY_PRICE_RE.fullmatch(card.prices[0].text) is None
        ):
            result.append(card)
            continue

        observed = card.prices[0]
        title_group = _TitleGroup(
            group_id=-1,
            page=card.page,
            spans=(),
            bbox=card.title_bbox,
            text=card.title,
            strict=True,
        )
        candidates: list[
            tuple[
                float,
                float,
                str,
                str,
                TextSpan,
                DisplayPriceObservation,
            ]
        ] = []

        for _page, product_id, binding_title, _binding_bbox in bindings_by_page.get(
            card.page, ()
        ):
            for structured in structured_by_id.get(product_id, ()):
                if structured.price_eur == observed.price_eur:
                    continue
                binding_similarity = _title_similarity(binding_title, structured.title)
                card_similarity = _title_similarity(card.title, structured.title)
                if binding_similarity < 0.98 or card_similarity < 0.98:
                    continue
                for span in pages[card.page]:
                    value = _unstarred_display_price(span)
                    if value != structured.price_eur:
                        continue
                    rescued = DisplayPriceObservation(
                        page=span.page,
                        bbox=span.bbox,
                        text=span.text,
                        price_eur=value,
                        font=span.font,
                        size=span.size,
                    )
                    cost = _title_cost(rescued, title_group)
                    if cost > 30.0:
                        continue
                    candidates.append(
                        (
                            cost,
                            -card_similarity,
                            product_id,
                            structured.title,
                            span,
                            rescued,
                        )
                    )

        if not candidates:
            result.append(card)
            continue

        candidates.sort(
            key=lambda item: (
                item[0],
                item[1],
                item[2],
                item[3],
                item[5].bbox,
            )
        )
        best = candidates[0]
        distinct = {
            (item[2], item[5].price_eur, item[5].bbox) for item in candidates
        }
        if len(distinct) > 1:
            runner_up = candidates[1]
            if runner_up[0] - best[0] < 8.0:
                result.append(card)
                continue

        span = best[4]
        rescued = best[5]
        spans = tuple(
            sorted(
                {(*item.bbox, item.text, item.font, item.size, item.flags): item for item in (*card.spans, span)}.values(),
                key=lambda item: (item.bbox[1], item.bbox[0], item.bbox, item.text, item.font),
            )
        )
        result.append(
            PhysicalCard(
                page=card.page,
                card_index=card.card_index,
                bbox=_bbox_union((card.bbox, rescued.bbox)),
                spans=spans,
                prices=(rescued,),
                title=card.title,
                title_bbox=card.title_bbox,
            )
        )

    return tuple(result)


def _anchor_key(price: DisplayPriceObservation) -> list[Any]:
    return [price.page + 1, price.price_eur, _rounded_bbox(price.bbox)]


def _semantic_offer(
    *,
    card: PhysicalCard,
    semantic_index: int,
    product_name: str,
    price_eur: str,
    app_price_eur: str | None,
    package_text: str | None,
    variant_key: str,
    classification: str,
    anchor_indexes: Sequence[int],
    flyer: DiscoveredFlyer,
    product_bindings: Sequence[ProductBinding | Mapping[str, Any]],
    page_dimensions: Sequence[tuple[float, float]],
    evidence: str,
) -> CardSemanticOffer:
    requires_app = app_price_eur is not None
    (
        valid_from,
        valid_until,
        validity_source,
        app_valid_from,
        app_valid_until,
        app_validity_source,
    ) = _validity(
        card,
        flyer,
        requires_app=requires_app,
        anchor_indexes=anchor_indexes,
    )
    official_id, official_title, binding_evidence = _official_binding(
        card,
        product_name=product_name,
        product_bindings=product_bindings,
        page_dimensions=page_dimensions,
    )
    occurrence = {
        "card_index": card.card_index,
        "page": card.page + 1,
        "anchor_keys": [_anchor_key(card.prices[index]) for index in anchor_indexes],
        "package_text": package_text,
        "base_valid_from": valid_from.isoformat() if valid_from else None,
        "base_valid_until": valid_until.isoformat() if valid_until else None,
        "base_validity_source": validity_source,
        "app_valid_from": app_valid_from.isoformat() if app_valid_from else None,
        "app_valid_until": app_valid_until.isoformat() if app_valid_until else None,
        "app_validity_source": app_validity_source,
        "classification_evidence": evidence,
        "app_evidence_geometry_scoped": requires_app,
        "card_bbox": _rounded_bbox(card.bbox),
    }
    rescued_anchor_indexes = [
        index
        for index in anchor_indexes
        if _is_structured_rescue_price(card.prices[index])
    ]
    if rescued_anchor_indexes:
        occurrence["price_evidence_source"] = (
            "schwarz_product_price_plus_unstarred_pdf_display"
        )
        occurrence["structured_price_rescue"] = True
        occurrence["structured_price_rescue_product_id"] = official_id
        occurrence["structured_price_rescue_pdf_text"] = [
            card.prices[index].text for index in rescued_anchor_indexes
        ]
    if official_title is not None:
        occurrence["official_product_title"] = official_title
        occurrence["official_binding_evidence"] = binding_evidence
    return CardSemanticOffer(
        page=card.page,
        card_index=card.card_index,
        semantic_index=semantic_index,
        product_name=product_name,
        price_eur=price_eur,
        app_price_eur=app_price_eur,
        requires_app=requires_app,
        package_text=package_text,
        variant_key=variant_key,
        classification=classification,
        valid_from=valid_from,
        valid_until=valid_until,
        app_valid_from=app_valid_from,
        app_valid_until=app_valid_until,
        occurrence=occurrence,
        official_product_id=official_id,
    )


def extract_card_semantics(
    cards: Sequence[PhysicalCard],
    *,
    flyer: DiscoveredFlyer,
    product_bindings: Sequence[ProductBinding | Mapping[str, Any]] = (),
    page_dimensions: Sequence[tuple[float, float]] = (),
) -> tuple[tuple[CardSemanticOffer, ...], tuple[UnresolvedObservation, ...]]:
    """Stage 3: classify each card without guessing ambiguous price meaning."""

    semantic: list[CardSemanticOffer] = []
    unresolved: list[UnresolvedObservation] = []
    for card in cards:
        card_text = " ".join(span.text for span in card.spans)
        if not card.title or _is_suspicious_title(card.title):
            unresolved.append(
                UnresolvedObservation(
                    reason="missing_or_unresolved_product_title",
                    page=card.page,
                    text=card_text,
                    bbox=card.bbox,
                    details={"card_index": card.card_index},
                )
            )
            continue
        package_text, package_candidates = _package_text(card)
        if len(package_candidates) > 1:
            unresolved.append(
                UnresolvedObservation(
                    reason="ambiguous_package_text",
                    page=card.page,
                    text=card_text,
                    bbox=card.bbox,
                    details={
                        "card_index": card.card_index,
                        "package_candidates": package_candidates,
                    },
                )
            )
        plus_indexes = _app_anchor_indexes(card)
        variants = _variant_assignments(card)
        prices = list(card.prices)
        rows: list[
            tuple[str, str | None, str, str, list[int], str]
        ] = []

        if len(prices) == 1:
            if not plus_indexes:
                rows.append(
                    (
                        prices[0].price_eur,
                        None,
                        "",
                        "normal_single",
                        [0],
                        "no_anchor_scoped_lidl_plus_marker",
                    )
                )
            else:
                explicit = _explicit_normal_prices(card, prices[0])
                if len(explicit) > 1:
                    unresolved.append(
                        UnresolvedObservation(
                            reason="multiple_explicit_normalpreis_values",
                            page=card.page,
                            text=card_text,
                            bbox=prices[0].bbox,
                            details={"values": [str(value) for value in explicit]},
                        )
                    )
                    continue
                if explicit:
                    base = explicit[0]
                    basis = "explicit_normalpreis"
                else:
                    reference = _small_reference_prices(card, prices[0])
                    if len(reference) > 1:
                        unresolved.append(
                            UnresolvedObservation(
                                reason="multiple_small_reference_price_candidates",
                                page=card.page,
                                text=card_text,
                                bbox=prices[0].bbox,
                                details={"values": [str(value) for value in reference]},
                            )
                        )
                        continue
                    if not reference:
                        unresolved.append(
                            UnresolvedObservation(
                                reason="app_price_without_proven_base_price",
                                page=card.page,
                                text=card_text,
                                bbox=prices[0].bbox,
                                details={"card_index": card.card_index},
                            )
                        )
                        continue
                    base = reference[0]
                    basis = "small_reference_price"
                rows.append(
                    (
                        f"{base:.2f}",
                        prices[0].price_eur,
                        "",
                        "lidl_plus_single_with_base",
                        [0],
                        basis,
                    )
                )
        elif len(prices) >= 2:
            if len(plus_indexes) == 1 and len(prices) == 2:
                app_index = next(iter(plus_indexes))
                base_index = 1 - app_index
                app_value = _decimal(prices[app_index].price_eur)
                base_value = _decimal(prices[base_index].price_eur)
                if app_value >= base_value:
                    unresolved.append(
                        UnresolvedObservation(
                            reason="lidl_plus_price_not_below_base_price",
                            page=card.page,
                            text=card_text,
                            bbox=card.bbox,
                            details={
                                "base": str(base_value),
                                "app": str(app_value),
                            },
                        )
                    )
                    continue
                rows.append(
                    (
                        prices[base_index].price_eur,
                        prices[app_index].price_eur,
                        "",
                        "lidl_plus_pair",
                        [base_index, app_index],
                        "one_anchor_scoped_lidl_plus_marker",
                    )
                )
            elif plus_indexes:
                unresolved.append(
                    UnresolvedObservation(
                        reason="multiple_prices_with_ambiguous_lidl_plus_semantics",
                        page=card.page,
                        text=card_text,
                        bbox=card.bbox,
                        details={
                            "prices": [price.price_eur for price in prices],
                            "plus_anchor_indexes": sorted(plus_indexes),
                        },
                    )
                )
                continue
            elif (
                len({_decimal(price.price_eur) for price in prices}) == 1
                and not variants
            ):
                rows.append(
                    (
                        prices[0].price_eur,
                        None,
                        "",
                        "duplicate_price_render",
                        list(range(len(prices))),
                        "same_price_repeated_within_owned_title",
                    )
                )
            elif len(variants) == len(prices):
                for index, price in enumerate(prices):
                    label = variants[index]
                    rows.append(
                        (
                            price.price_eur,
                            None,
                            _fold(label),
                            "size_variants",
                            [index],
                            f"local_variant_label:{label}",
                        )
                    )
            else:
                unresolved.append(
                    UnresolvedObservation(
                        reason="multiple_prices_without_proven_size_or_lidl_plus_semantics",
                        page=card.page,
                        text=card_text,
                        bbox=card.bbox,
                        details={
                            "prices": [price.price_eur for price in prices],
                            "variant_assignments": variants,
                        },
                    )
                )
                continue

        for semantic_index, (
            base_price,
            app_price,
            variant_key,
            classification,
            anchor_indexes,
            evidence,
        ) in enumerate(rows):
            # Keep the product title stable across size variants. The local
            # size/dimension belongs in variant_key and source identity, not in
            # product_name; this matches the validated V08c semantic model.
            product_name = card.title
            semantic.append(
                _semantic_offer(
                    card=card,
                    semantic_index=semantic_index,
                    product_name=product_name,
                    price_eur=base_price,
                    app_price_eur=app_price,
                    package_text=package_text,
                    variant_key=variant_key,
                    classification=classification,
                    anchor_indexes=anchor_indexes,
                    flyer=flyer,
                    product_bindings=product_bindings,
                    page_dimensions=page_dimensions,
                    evidence=evidence,
                )
            )
    return (
        tuple(
            sorted(
                semantic,
                key=lambda item: (
                    item.page,
                    item.card_index,
                    item.semantic_index,
                    item.product_name,
                ),
            )
        ),
        tuple(unresolved),
    )


def _explicit_validities(
    rows: Sequence[CardSemanticOffer],
    *,
    app: bool,
) -> set[tuple[date | None, date | None]]:
    result: set[tuple[date | None, date | None]] = set()
    for row in rows:
        source = row.occurrence.get(
            "app_validity_source" if app else "base_validity_source"
        )
        if source in (None, "flyer_default", "inherits_base"):
            continue
        result.add(
            (
                row.app_valid_from if app else row.valid_from,
                row.app_valid_until if app else row.valid_until,
            )
        )
    return result


def deduplicate_semantic_offers(
    semantic_offers: Sequence[CardSemanticOffer],
    *,
    flyer: DiscoveredFlyer,
    snapshot_id: UUID,
    collected_at: datetime,
) -> tuple[tuple[OfferCandidate, ...], tuple[UnresolvedObservation, ...]]:
    """Stage 4: exact logical dedup while preserving every occurrence."""

    grouped: dict[tuple[str, str, str, str], list[CardSemanticOffer]] = defaultdict(list)
    for row in semantic_offers:
        grouped[
            (
                _fold(row.product_name),
                _fold(row.variant_key),
                row.price_eur,
                row.app_price_eur or "",
            )
        ].append(row)

    unresolved: list[UnresolvedObservation] = []
    accepted: list[tuple[CardSemanticOffer, list[CardSemanticOffer]]] = []
    for key, rows in sorted(grouped.items()):
        packages = {_fold(row.package_text) for row in rows if row.package_text}
        official_ids = {
            _fold(row.official_product_id) for row in rows if row.official_product_id
        }
        base_explicit = _explicit_validities(rows, app=False)
        app_explicit = _explicit_validities(rows, app=True)
        conflict_reason: str | None = None
        details: dict[str, Any] = {"logical_key": key}
        if len(packages) > 1:
            conflict_reason = "repeated_render_package_conflict"
            details["packages"] = sorted(packages)
        elif len(official_ids) > 1:
            conflict_reason = "repeated_render_official_product_id_conflict"
            details["official_product_ids"] = sorted(official_ids)
        elif len(base_explicit) > 1 or len(app_explicit) > 1:
            conflict_reason = "repeated_render_validity_conflict"
            details["base_validities"] = sorted(
                (str(start), str(end)) for start, end in base_explicit
            )
            details["app_validities"] = sorted(
                (str(start), str(end)) for start, end in app_explicit
            )
        if conflict_reason is not None:
            unresolved.append(
                UnresolvedObservation(
                    reason=conflict_reason,
                    page=rows[0].page,
                    text=rows[0].product_name,
                    details=details,
                )
            )
            continue

        representative = max(
            rows,
            key=lambda row: (
                row.official_product_id is not None,
                row.package_text is not None,
                row.occurrence.get("base_validity_source") != "flyer_default",
                row.occurrence.get("app_validity_source")
                not in (None, "inherits_base"),
                -row.page,
                -row.card_index,
            ),
        )
        # One explicit observation enriches default-validity repeats.
        if base_explicit:
            start, end = next(iter(base_explicit))
            representative = next(
                row for row in rows if (row.valid_from, row.valid_until) == (start, end)
            )
        if app_explicit:
            start, end = next(iter(app_explicit))
            representative = next(
                row
                for row in rows
                if (row.app_valid_from, row.app_valid_until) == (start, end)
            )
        accepted.append((representative, rows))

    official_group_counts: dict[str, int] = defaultdict(int)
    for representative, _rows in accepted:
        if representative.official_product_id:
            official_group_counts[_fold(representative.official_product_id)] += 1

    offers: list[OfferCandidate] = []
    identities: set[str] = set()
    for representative, rows in accepted:
        occurrences = sorted(
            (dict(row.occurrence) for row in rows),
            key=lambda item: (
                item.get("page") or 0,
                item.get("card_index") or 0,
                json.dumps(item.get("anchor_keys"), sort_keys=True),
            ),
        )
        package_text = next(
            (row.package_text for row in rows if row.package_text),
            representative.package_text,
        )
        official_id = next(
            (
                row.official_product_id
                for row in rows
                if row.official_product_id is not None
            ),
            representative.official_product_id,
        )
        if official_id:
            folded_id = _fold(official_id)
            source_offer_id = f"lidl:product:{folded_id}"
            source_offer_id_basis = "official_product_id"
            if official_group_counts[folded_id] > 1:
                variant_identity = "|".join(
                    (
                        _fold(package_text or ""),
                        _fold(representative.variant_key),
                        _fold(representative.product_name),
                    )
                )
                suffix = hashlib.sha256(variant_identity.encode()).hexdigest()[:12]
                source_offer_id = f"{source_offer_id}:{suffix}"
                source_offer_id_basis = "official_product_id_plus_logical_variant"
        else:
            source_offer_id = fallback_source_offer_id(
                product_name=representative.product_name,
                brand=None,
                package_text=package_text,
                variant_key=representative.variant_key,
            )
            source_offer_id_basis = "fallback_name_package_variant"
        if source_offer_id in identities:
            unresolved.append(
                UnresolvedObservation(
                    reason="source_offer_id_collision",
                    page=representative.page,
                    text=representative.product_name,
                    details={"source_offer_id": source_offer_id},
                )
            )
            continue
        identities.add(source_offer_id)

        app_from = representative.app_valid_from
        app_until = representative.app_valid_until
        if representative.app_price_eur is None or (app_from is None) != (app_until is None):
            app_from = app_until = None
        raw_payload = {
            "official_flyer_id": flyer.official_flyer_id,
            "flyer_identifier": flyer.flyer_identifier,
            "route_region": flyer.route_region,
            "page": representative.page + 1,
            "card_index": representative.card_index,
            "classification": representative.classification,
            "variant_key": representative.variant_key,
            "official_product_id": official_id,
            "source_offer_id_basis": source_offer_id_basis,
            "card_bbox": representative.occurrence.get("card_bbox"),
            "anchor_keys": representative.occurrence.get("anchor_keys", []),
            "occurrences": occurrences,
            "app_evidence_geometry_scoped": (
                representative.app_price_eur is not None
                and all(
                    bool(row.occurrence.get("app_evidence_geometry_scoped"))
                    for row in rows
                )
            ),
        }
        offers.append(
            OfferCandidate(
                source_chain=SourceChain.LIDL,
                source_store_external_id=None,
                source_store_name="Lidl public/default flyer",
                source_offer_id=source_offer_id,
                product_name_raw=representative.product_name,
                package_text_raw=package_text,
                price_eur=_decimal(representative.price_eur),
                app_price_eur=(
                    _decimal(representative.app_price_eur)
                    if representative.app_price_eur
                    else None
                ),
                requires_app=representative.app_price_eur is not None,
                valid_from=representative.valid_from,
                valid_until=representative.valid_until,
                app_valid_from=app_from,
                app_valid_until=app_until,
                source_url=flyer.document_url,
                snapshot_id=snapshot_id,
                collected_at=collected_at,
                parser_version=PARSER_VERSION,
                raw_payload=raw_payload,
            )
        )
    return (
        tuple(
            sorted(
                offers,
                key=lambda offer: (
                    str(offer.source_offer_id),
                    offer.product_name_raw,
                ),
            )
        ),
        tuple(unresolved),
    )


def parse_lidl_pdf(
    *,
    document: bytes,
    flyer: DiscoveredFlyer,
    snapshot_id: UUID,
    collected_at: datetime,
) -> LidlParseResult:
    pages = extract_pdf_spans(document)
    dimensions = _page_dimensions(document, pages)
    document_sha256 = hashlib.sha256(document).hexdigest()
    structured_prices = _structured_product_prices(flyer.raw_fetch)
    fingerprint = parser_input_fingerprint_v1(
        pages,
        document_sha256=document_sha256,
        product_bindings=flyer.product_bindings,
        structured_product_prices=structured_prices,
    )
    display_prices = extract_display_price_observations(pages)
    cards = build_physical_cards(
        pages,
        display_prices,
        product_bindings=flyer.product_bindings,
        page_dimensions=dimensions,
    )
    cards = _rescue_structured_card_prices(
        cards,
        pages=pages,
        product_bindings=flyer.product_bindings,
        structured_product_prices=structured_prices,
    )
    semantic, semantic_unresolved = extract_card_semantics(
        cards,
        flyer=flyer,
        product_bindings=flyer.product_bindings,
        page_dimensions=dimensions,
    )
    offers, dedup_unresolved = deduplicate_semantic_offers(
        semantic,
        flyer=flyer,
        snapshot_id=snapshot_id,
        collected_at=collected_at,
    )
    return LidlParseResult(
        offers=offers,
        unresolved=tuple((*semantic_unresolved, *dedup_unresolved)),
        parser_input_fingerprint_v1=fingerprint,
        display_prices=display_prices,
        physical_cards=cards,
        semantic_occurrences=semantic,
    )
