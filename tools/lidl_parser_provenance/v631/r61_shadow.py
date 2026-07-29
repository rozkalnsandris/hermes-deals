from __future__ import annotations

from dataclasses import dataclass, replace as dataclass_replace
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from difflib import SequenceMatcher
import hashlib
import json
import math
import re
from typing import Any, Iterable
from urllib.parse import parse_qs, urlparse

import fitz

from app.lidl import r61_base


PARSER_VERSION = "lidl-pdf-v08c-r61-shadow-v631"

_DATE_RANGE_RE = re.compile(
    r"\b(?:Ab|Gültig(?:\s+vom)?)\s+"
    r"(?P<from_dow>Mo|Di|Mi|Do|Fr|Sa|So)\.?\s*"
    r"(?P<from_day>\d{1,2})\.(?P<from_month>\d{1,2})\."
    r"(?:\s*bis\s*(?P<until_dow>Mo|Di|Mi|Do|Fr|Sa|So)\.?\s*"
    r"(?P<until_day>\d{1,2})\.(?P<until_month>\d{1,2})\.)?",
    re.IGNORECASE,
)
_GUELTIG_AM_RE = re.compile(
    r"\bGültig\s+am\s+(?P<day>\d{1,2})\.(?P<month>\d{1,2})\.",
    re.IGNORECASE,
)
_MONEY_RE = re.compile(r"(?<!\d)(\d{1,3}[.,]\d{2})(?!\d)")
_PRODUCT_ID_RE = re.compile(r"/p/.+/p(?P<id>\d+)(?:[/?#]|$)", re.IGNORECASE)
_DECORATIVE_TITLE_RE = re.compile(r"^(?:im\s+aufsteller|jetzt)$", re.IGNORECASE)
_VALID_PRODUCT_VARIANT_RE = re.compile(r"\bmaxi\s+king\b", re.IGNORECASE)
_OWNERSHIP_SENTINEL = "HERMESVALIDPRODUCTTITLE"


def _decorative_title(value: Any) -> bool:
    return _DECORATIVE_TITLE_RE.fullmatch(_clean(value)) is not None


def _ownership_span_text(value: Any) -> str | None:
    """Prepare a PDF span only for frozen R6 Stage-2 title ownership.

    Promotional labels are removed. A proven product phrase that otherwise
    trips R6 short KING/QUEEN size-label heuristic receives a temporary
    fourth token. The marker is removed before semantic extraction.
    """
    text = _clean(value)
    if _decorative_title(text):
        return None
    if _VALID_PRODUCT_VARIANT_RE.search(text):
        return f"{text} {_OWNERSHIP_SENTINEL}"
    return text


def _restore_ownership_card_title(card: Any) -> Any:
    title = _clean(getattr(card, "title", ""))
    if not title or _OWNERSHIP_SENTINEL not in title:
        return card
    restored = _clean(title.replace(_OWNERSHIP_SENTINEL, ""))
    return dataclass_replace(card, title=restored)

# Current Hermes Deals scope: physical-store food, drinks and household essentials.
_EXCLUDE_SCOPE = re.compile(
    r"\b("
    r"pflanze|blumen|strauß|rosen|hortensie|lavendel|orchidee|phaleanopsis|"
    r"matratze|kissen|decke|staubsauger|mopp|roboter|nähmaschine|"
    r"pfanne|topf|tellerset|kontaktgrill|mikrowelle|standmixer|"
    r"schuhe|shirt|hose|jacke|kleid|wäsche|socken|"
    r"werkzeug|bohrer|akku|rasenmäher|grillgerät|pool|sup|paddel|"
    r"reise|hotel|flug|fotobuch|fotos|connect|job|karriere"
    r")\b",
    re.IGNORECASE,
)
_INCLUDE_HOUSEHOLD = re.compile(
    r"\b("
    r"waschmittel|weichspüler|spülmittel|reiniger|toilettenpapier|windel|pampers|"
    r"taschentücher|küchenrolle|sonnenblumenöl|shampoo|duschgel|"
    r"katzenstreu"
    r")\b",
    re.IGNORECASE,
)
_FOOD_DRINK_HINT = re.compile(
    r"\b("
    r"milch|joghurt|käse|schnittkäse|butter|sahne|quark|zucker|fleisch|hähnchen|rind|schwein|"
    r"wurst|schinken|salami|pizza|flammkuchen|chips|pasta|pesto|brot|frischkäse|pils|bierfass|"
    r"croissant|tomate|apfel|mango|pfirsich|kiwi|beeren|gemüse|obst|"
    r"öl|honig|kaffee|tee|cola|fanta|sprite|wasser|saft|bier|wein|"
    r"whisky|vodka|likör|eis|garnelen|lachs|fisch|nudel|müsli|riegel|refresh|"
    r"nutella|schokolade|kaugummi|pommes"
    r")\b",
    re.IGNORECASE,
)

# Scope is deliberately title / official-category first. Page metadata is only
# an advisory fallback for a card whose own title has no durable/non-target
# signal. Never classify from broad neighbouring card text.
_EDIBLE_HERB_RE = re.compile(
    r"\b(?:basilikum|petersilie|schnittlauch|koriander|dill|minze|kräuter?)\b",
    re.IGNORECASE,
)
_HARD_NON_TARGET_TITLE_RE = re.compile(
    r"\b(?:"
    r"kombiservice|partygeschirr|geschirr|besteck|porzellan|"
    r"pfanne|topfset|kochtopf|kochplatte|toaster|waffeleisen|sandwichmaker|"
    r"wassersprudler(?:flaschen)?|trinkflasche|multizerkleinerer|backofen|"
    r"reiskocher|bratenform|frischhaltedosen|staubsauger|bügeleisen|"
    r"schubladenmatte|nähmaschine|matratze|kissen|decke|"
    r"schuhe|shirt|hose|jacke|kleid|socken|"
    r"werkzeug|bohrer|akku|rasenmäher|grillgerät|"
    r"allround[-\s]?sup|stand[-\s]?up|paddel|pool|"
    r"reise|hotel|flug|fotobuch|fotoservice|karriere|job"
    r")\b",
    re.IGNORECASE,
)
_ORNAMENTAL_PLANT_RE = re.compile(
    r"\b(?:blühpflanze|gartenhortensie|hortensie|lavendel|grünpflanze|"
    r"orchidee|phalaenopsis|zierpflanze|blumenstrauß|blumenstrauss)\b",
    re.IGNORECASE,
)
_STRUCTURED_TARGET_CATEGORY_RE = re.compile(
    r"(?:lebensmittel|getränk|drogerie|körperpflege|waschen|reinigen|"
    r"haushaltsreiniger|baby|tierbedarf|tierfutter|lebensmittelvorrat)",
    re.IGNORECASE,
)
_STRUCTURED_NON_TARGET_CATEGORY_RE = re.compile(
    r"(?:geschirr|besteck|porzellan|küchengerät|elektro|werkzeug|"
    r"bekleidung|mode|textil|möbel|sportgerät|freizeitgerät|reise|foto)",
    re.IGNORECASE,
)
_PAGE_TARGET_HINT_RE = re.compile(
    r"\b(?:lebensmittel|essen|trinken|getränk|fleisch|wurst|fisch|käse|"
    r"milch|joghurt|obst|gemüse|backwaren|brot|snack|süß|kaffee|tee|"
    r"bier|wein|spirituosen|drogerie|waschmittel|reinigung|hygiene|"
    r"shampoo|baby|windel|tierfutter|katzenstreu|haushaltsreiniger)\b",
    re.IGNORECASE,
)
_TITLE_TARGET_RE = re.compile(
    r"\b(?:"
    r"garnelen|lachs|fisch|pistaz|cashew|erdnüss|walnuss|mandel|nuts|"
    r"kohl|tomat|mais|apfel|pfirsich|heidelbeer|beeren|gemüse|obst|"
    r"rinder|fleisch|hähnchen|kaninchen|lammlachse|roastbeef|wurst|"
    r"schinken|salami|leberkäse|frikadellen|aufschnitt|würstchen|"
    r"brot|brötchen|apfeltasche|crusti|streusel|croissant|hefegebäck|"
    r"milch|joghurt|quark|käse|mozzarella|butter|crème|camembert|obazda|"
    r"pizza|flammkuchen|pasta|pesto|nudel|mehl|zucker|öl|ajvar|fond|"
    r"chips|snack|riegel|schoko|schokolade|candy|tiramisu|cantuccini|"
    r"kaffee|coffee|tee|eistee|cola|fanta|sprite|mezzo|energy|refresh|"
    r"wasser|volvic|saft|drink|bier|pils|wein|sekt|whisky|whiskey|"
    r"wodka|vodka|ouzo|bourbon|liqueur|likör|"
    r"waschmittel|weichspüler|hygienespüler|spülmittel|reiniger|"
    r"allzwecktücher|toilettenpapier|taschentücher|küchenrolle|"
    r"shampoo|duschgel|mundspül|windel|pampers|katzenstreu|tierfutter|purina"
    r")\b",
    re.IGNORECASE,
)


def _clean(text: Any) -> str:
    return " ".join(str(text or "").replace("\u00ad", "").replace("\u2002", " ").split())


def _fold(text: Any) -> str:
    return (
        _clean(text)
        .casefold()
        .replace("ß", "ss")
        .replace("ä", "a")
        .replace("ö", "o")
        .replace("ü", "u")
    )


def _decimal(text: Any) -> Decimal | None:
    value = _clean(text).replace("*", "").replace(",", ".")
    try:
        return Decimal(value)
    except (InvalidOperation, ValueError):
        return None


def _intersects(a: Iterable[float], b: Iterable[float]) -> bool:
    ax0, ay0, ax1, ay1 = map(float, a)
    bx0, by0, bx1, by1 = map(float, b)
    return max(ax0, bx0) <= min(ax1, bx1) and max(ay0, by0) <= min(ay1, by1)


def _expand(bbox: Iterable[float], x: float = 8.0, y: float = 8.0) -> tuple[float, float, float, float]:
    x0, y0, x1, y1 = map(float, bbox)
    return (x0 - x, y0 - y, x1 + x, y1 + y)


def _bbox_center(bbox: Iterable[float]) -> tuple[float, float]:
    x0, y0, x1, y1 = map(float, bbox)
    return ((x0 + x1) / 2.0, (y0 + y1) / 2.0)


def _distance(a: Iterable[float], b: Iterable[float]) -> float:
    ax, ay = _bbox_center(a)
    bx, by = _bbox_center(b)
    return math.hypot(ax - bx, ay - by)


def _year_date(year: int, day: str, month: str) -> date:
    return date(year, int(month), int(day))


@dataclass(frozen=True)
class TextLine:
    text: str
    bbox: tuple[float, float, float, float]
    spans: tuple[dict[str, Any], ...]


@dataclass(frozen=True)
class PdfLink:
    uri: str
    bbox: tuple[float, float, float, float]
    product_id: str | None
    recipe_query: str | None


@dataclass(frozen=True)
class SchwarzLink:
    display_type: str
    uri: str
    title: str
    bbox: tuple[float, float, float, float]
    product_id: str | None
    structured_price: Decimal | None
    category_text: str
    online_column_signal: bool


@dataclass(frozen=True)
class PageMeta:
    page: int
    keywords: str
    alt_text: str
    target_hint: bool


@dataclass(frozen=True)
class PageEvidence:
    page: int
    width: float
    height: float
    lines: tuple[TextLine, ...]
    links: tuple[PdfLink, ...]
    page_valid_from: date | None
    page_valid_until: date | None
    page_validity_source: str | None


def _line_from_spans(spans: list[dict[str, Any]]) -> TextLine:
    x0 = min(float(s["bbox"][0]) for s in spans)
    y0 = min(float(s["bbox"][1]) for s in spans)
    x1 = max(float(s["bbox"][2]) for s in spans)
    y1 = max(float(s["bbox"][3]) for s in spans)
    return TextLine(
        text=_clean(" ".join(str(s.get("text") or "") for s in spans)),
        bbox=(x0, y0, x1, y1),
        spans=tuple(spans),
    )


def _parse_validity(text: str, year: int, default_until: date) -> tuple[date | None, date | None, str | None]:
    m = _GUELTIG_AM_RE.search(text)
    if m:
        d = _year_date(year, m.group("day"), m.group("month"))
        return d, d, "gueltig_am"

    m = _DATE_RANGE_RE.search(text)
    if not m:
        return None, None, None
    start = _year_date(year, m.group("from_day"), m.group("from_month"))
    if m.group("until_day") and m.group("until_month"):
        end = _year_date(year, m.group("until_day"), m.group("until_month"))
        return start, end, "explicit_range"
    return start, default_until, "explicit_start"


def _page_validity(
    lines: tuple[TextLine, ...],
    *,
    page_height: float,
    year: int,
    default_until: date,
) -> tuple[date | None, date | None, str | None]:
    """Resolve only an actual page/section banner, never a random card date.

    Lidl's banners such as "Ab Do. 30.7. bis Sa. 1.8." live at the top of the
    page. A card-local date elsewhere on the page must not silently become the
    default for neighbouring products.
    """
    candidates: list[tuple[float, date, date, str]] = []
    top_limit = page_height * 0.18
    for line in lines:
        if line.bbox[1] > top_limit:
            continue
        vf, vu, source = _parse_validity(line.text, year, default_until)
        if vf is None or vu is None or source is None:
            continue
        max_size = max((float(span.get("size") or 0) for span in line.spans), default=0.0)
        # Prefer an explicit range and a visibly prominent banner.
        score = line.bbox[1] - (250.0 if source == "explicit_range" else 0.0) - min(max_size, 40.0)
        candidates.append((score, vf, vu, source))
    if not candidates:
        return None, None, None
    _, vf, vu, source = min(candidates, key=lambda item: item[0])
    return vf, vu, "page_" + source


def extract_pdf_evidence(document: bytes, flyer_valid_until: date) -> tuple[PageEvidence, ...]:
    doc = fitz.open(stream=document, filetype="pdf")
    year = flyer_valid_until.year
    result: list[PageEvidence] = []

    for pno in range(doc.page_count):
        page = doc[pno]
        raw = page.get_text("dict", sort=True)
        lines: list[TextLine] = []

        for block in raw.get("blocks", []):
            for line in block.get("lines", []):
                spans = [dict(span) for span in line.get("spans", []) if _clean(span.get("text"))]
                if spans:
                    lines.append(_line_from_spans(spans))

        links: list[PdfLink] = []
        for link in page.get_links():
            uri = str(link.get("uri") or "")
            rect = link.get("from")
            if not uri or rect is None:
                continue
            product_id = None
            m = _PRODUCT_ID_RE.search(uri)
            if m:
                product_id = m.group("id")
            recipe_query = None
            parsed = urlparse(uri)
            if parsed.netloc == "rezepte.lidl.de":
                q = parse_qs(parsed.query)
                recipe_query = _clean((q.get("q") or [None])[0])
            links.append(
                PdfLink(
                    uri=uri,
                    bbox=(float(rect.x0), float(rect.y0), float(rect.x1), float(rect.y1)),
                    product_id=product_id,
                    recipe_query=recipe_query,
                )
            )

        p_from, p_until, p_source = _page_validity(
            tuple(lines),
            page_height=float(page.rect.height),
            year=year,
            default_until=flyer_valid_until,
        )
        result.append(
            PageEvidence(
                page=pno + 1,
                width=float(page.rect.width),
                height=float(page.rect.height),
                lines=tuple(lines),
                links=tuple(links),
                page_valid_from=p_from,
                page_valid_until=p_until,
                page_validity_source=p_source,
            )
        )
    doc.close()
    return tuple(result)



def _bbox_union(boxes: Iterable[Iterable[float]]) -> tuple[float, float, float, float]:
    rows = [tuple(map(float, box)) for box in boxes]
    if not rows:
        raise ValueError("bbox union requires at least one box")
    return (
        min(box[0] for box in rows),
        min(box[1] for box in rows),
        max(box[2] for box in rows),
        max(box[3] for box in rows),
    )


def _contained(inner: Iterable[float], outer: Iterable[float], tolerance: float = 0.8) -> bool:
    ix0, iy0, ix1, iy1 = map(float, inner)
    ox0, oy0, ox1, oy1 = map(float, outer)
    return (
        ix0 >= ox0 - tolerance
        and iy0 >= oy0 - tolerance
        and ix1 <= ox1 + tolerance
        and iy1 <= oy1 + tolerance
    )


def _strict_card_roi(
    *,
    page: PageEvidence,
    title_bbox: Iterable[float] | None,
    anchor_rows: list[tuple[Decimal, tuple[float, float, float, float]]],
    all_page_prices: Iterable[Any],
) -> tuple[float, float, float, float]:
    """Build a small evidence cell around this title and its owned price anchors.

    The key protection is horizontal neighbour clipping by display-price
    midpoints. It keeps nearby UVP / Normalpreis text with its own product while
    stopping that text from leaking into the neighbouring card.
    """
    boxes = [bbox for _value, bbox in anchor_rows]
    if title_bbox is not None:
        boxes.append(tuple(map(float, title_bbox)))
    if not boxes:
        return (0.0, 0.0, page.width, page.height)

    core = _bbox_union(boxes)
    x0 = max(0.0, core[0] - 24.0)
    y0 = max(0.0, core[1] - 12.0)
    x1 = min(page.width, core[2] + 32.0)
    y1 = min(page.height, core[3] + 14.0)

    anchor_centers = [_bbox_center(bbox) for _value, bbox in anchor_rows]
    if not anchor_centers:
        return (x0, y0, x1, y1)

    cx = sum(point[0] for point in anchor_centers) / len(anchor_centers)
    cy = sum(point[1] for point in anchor_centers) / len(anchor_centers)
    owned_boxes = {tuple(round(v, 3) for v in bbox) for _value, bbox in anchor_rows}

    left_mid: float | None = None
    right_mid: float | None = None
    above_mid: float | None = None
    below_mid: float | None = None

    for price in all_page_prices:
        bbox = tuple(float(v) for v in price.bbox)
        if tuple(round(v, 3) for v in bbox) in owned_boxes:
            continue
        px, py = _bbox_center(bbox)

        # Same visual row: derive horizontal cell boundary.
        if abs(py - cy) <= 75.0:
            midpoint = (px + cx) / 2.0
            if px < cx and midpoint < core[0]:
                left_mid = midpoint if left_mid is None else max(left_mid, midpoint)
            elif px > cx and midpoint > core[2]:
                right_mid = midpoint if right_mid is None else min(right_mid, midpoint)

        # Same visual column: prevent spill into rows above / below.
        if abs(px - cx) <= 110.0:
            midpoint = (py + cy) / 2.0
            if py < cy and midpoint < core[1]:
                above_mid = midpoint if above_mid is None else max(above_mid, midpoint)
            elif py > cy and midpoint > core[3]:
                below_mid = midpoint if below_mid is None else min(below_mid, midpoint)

    if left_mid is not None:
        x0 = max(x0, left_mid)
    if right_mid is not None:
        x1 = min(x1, right_mid)
    if above_mid is not None:
        y0 = max(y0, above_mid)
    if below_mid is not None:
        y1 = min(y1, below_mid)

    # Never let neighbour clipping cut the actual title/owned anchors.
    x0 = min(x0, core[0] - 0.5)
    y0 = min(y0, core[1] - 0.5)
    x1 = max(x1, core[2] + 0.5)
    y1 = max(y1, core[3] + 0.5)
    return (
        max(0.0, x0),
        max(0.0, y0),
        min(page.width, x1),
        min(page.height, y1),
    )


def _strict_lines(page: PageEvidence, roi: Iterable[float]) -> list[TextLine]:
    # Containment, not broad intersection, mirrors PyMuPDF clip semantics and
    # is the central defence against neighbouring-card ownership leakage.
    return [line for line in page.lines if _contained(line.bbox, roi)]


def _strict_links(page: PageEvidence, roi: Iterable[float]) -> list[PdfLink]:
    rx0, ry0, rx1, ry1 = map(float, roi)
    result: list[PdfLink] = []
    for link in page.links:
        cx, cy = _bbox_center(link.bbox)
        if _contained(link.bbox, roi) or (rx0 <= cx <= rx1 and ry0 <= cy <= ry1):
            result.append(link)
    return result

def _flatten_json_text(value: Any) -> str:
    parts: list[str] = []
    if isinstance(value, str):
        parts.append(value)
    elif isinstance(value, dict):
        for item in value.values():
            parts.append(_flatten_json_text(item))
    elif isinstance(value, (list, tuple)):
        for item in value:
            parts.append(_flatten_json_text(item))
    return _clean(" ".join(part for part in parts if part))


def _parse_schwarz_page_meta(raw_fetch: bytes) -> dict[int, PageMeta]:
    try:
        flyer = json.loads(raw_fetch)["flyer"]
    except Exception:
        return {}
    result: dict[int, PageMeta] = {}
    for index, raw_page in enumerate(flyer.get("pages") or [], start=1):
        if not isinstance(raw_page, dict):
            continue
        keywords = _flatten_json_text(raw_page.get("keyWords"))
        alt_text = _flatten_json_text(raw_page.get("altText"))
        meta_text = _clean(f"{keywords} {alt_text}")
        result[index] = PageMeta(
            page=index,
            keywords=keywords,
            alt_text=alt_text,
            target_hint=bool(_PAGE_TARGET_HINT_RE.search(meta_text)),
        )
    return result


def _same_online_column(product: dict[str, Any], cta: dict[str, Any]) -> bool:
    """Return true when a product hotspot is contained in an official CTA column."""
    product_left = float(product["left_pct"])
    product_right = product_left + float(product["width_pct"])
    cta_left = float(cta["left_pct"])
    cta_right = cta_left + float(cta["width_pct"])
    return (
        abs(product_left - cta_left) <= 1.0
        and product_left >= cta_left - 1.0
        and product_right <= cta_right + 1.0
    )


def _parse_schwarz_page_links(
    raw_fetch: bytes,
    pages: tuple[PageEvidence, ...],
) -> dict[int, tuple[SchwarzLink, ...]]:
    """Convert official Schwarz percentage link geometry into PDF coordinates."""
    try:
        payload = json.loads(raw_fetch)
        flyer = payload["flyer"]
    except Exception:
        return {}

    products_raw = flyer.get("products") or {}
    by_pid: dict[str, dict[str, Any]] = {}
    if isinstance(products_raw, dict):
        iterable = products_raw.values()
    elif isinstance(products_raw, list):
        iterable = products_raw
    else:
        iterable = ()
    for product in iterable:
        if isinstance(product, dict) and product.get("productId") is not None:
            by_pid[str(product["productId"])] = product

    result: dict[int, tuple[SchwarzLink, ...]] = {}
    raw_pages = flyer.get("pages") or []
    for idx, page in enumerate(pages):
        if idx >= len(raw_pages) or not isinstance(raw_pages[idx], dict):
            continue
        raw_links = [
            item for item in (raw_pages[idx].get("links") or [])
            if isinstance(item, dict)
        ]
        converted: list[dict[str, Any]] = []
        for item in raw_links:
            try:
                left = float(item.get("left"))
                top = float(item.get("top"))
                width = float(item.get("width"))
                height = float(item.get("height"))
            except (TypeError, ValueError):
                continue
            x0 = left / 100.0 * page.width
            y0 = top / 100.0 * page.height
            x1 = (left + width) / 100.0 * page.width
            y1 = (top + height) / 100.0 * page.height
            pd = item.get("productDetails")
            pid = (
                str(pd.get("productId"))
                if isinstance(pd, dict) and pd.get("productId") is not None
                else None
            )
            product = by_pid.get(pid or "")
            structured_price = (
                _decimal(product.get("price"))
                if isinstance(product, dict)
                else None
            )
            category_text = ""
            if isinstance(product, dict):
                category_text = _flatten_json_text({
                    key: product.get(key)
                    for key in (
                        "categoryPrimary",
                        "wonCategoryPrimary",
                        "categorySecondary",
                        "wonCategorySecondary",
                        "category",
                        "categories",
                    )
                    if product.get(key) is not None
                })
            converted.append({
                "display_type": _clean(item.get("displayType")).casefold(),
                "uri": str(item.get("url") or ""),
                "title": _clean(
                    (pd or {}).get("title")
                    if isinstance(pd, dict)
                    else item.get("title")
                ),
                "bbox": (x0, y0, x1, y1),
                "product_id": pid,
                "structured_price": structured_price,
                "category_text": category_text,
                "left_pct": left,
                "width_pct": width,
            })

        category_ctas = []
        for row in converted:
            parsed = urlparse(row["uri"])
            if (
                row["display_type"] == "standard"
                and parsed.netloc in {"www.lidl.de", "lidl.de"}
                and parsed.path.startswith("/c/")
            ):
                category_ctas.append(row)

        links: list[SchwarzLink] = []
        for row in converted:
            online_column_signal = False
            if row["display_type"] == "product":
                for cta in category_ctas:
                    if _same_online_column(row, cta):
                        online_column_signal = True
                        break
            links.append(
                SchwarzLink(
                    display_type=row["display_type"],
                    uri=row["uri"],
                    title=row["title"],
                    bbox=row["bbox"],
                    product_id=row["product_id"],
                    structured_price=row["structured_price"],
                    category_text=row["category_text"],
                    online_column_signal=online_column_signal,
                )
            )
        result[page.page] = tuple(links)
    return result

def _compact_identity(text: Any) -> str:
    return re.sub(r"[^a-z0-9]+", "", _fold(text))


def _title_similarity(a: str, b: str) -> int:
    aa = _compact_identity(a)
    bb = _compact_identity(b)
    if not aa or not bb:
        return 0
    if aa in bb or bb in aa:
        return min(len(aa), len(bb))
    # Prefix agreement helps with PDF line wrapping while avoiding a broad
    # semantic matcher.
    n = 0
    for ca, cb in zip(aa, bb):
        if ca != cb:
            break
        n += 1
    return n


def _match_schwarz_product_link(
    *,
    links: tuple[SchwarzLink, ...],
    product_name: str,
    price: Decimal | None,
    app_price: Decimal | None,
    anchor_rows: list[tuple[Decimal, tuple[float, float, float, float]]],
    card_bbox: Iterable[float],
) -> SchwarzLink | None:
    candidates: list[tuple[float, SchwarzLink]] = []
    target_values = {value for value in (price, app_price) if value is not None}

    anchor_bbox = anchor_rows[0][1] if anchor_rows else tuple(card_bbox)
    for link in links:
        if link.display_type != "product" or not link.product_id:
            continue

        value_match = (
            link.structured_price is not None
            and link.structured_price in target_values
        )
        title_score = _title_similarity(product_name, link.title)

        # Require either exact structured price agreement or strong title
        # agreement. This prevents a large R6 card bbox from stealing a
        # neighbour's hotspot.
        if not value_match and title_score < 12:
            continue

        distance = _distance(anchor_bbox, link.bbox)
        score = distance
        if value_match:
            score -= 250.0
        score -= min(title_score, 60) * 2.0
        candidates.append((score, link))

    if not candidates:
        return None
    candidates.sort(key=lambda item: item[0])
    best_score, best = candidates[0]

    # Fail closed if even the best candidate is implausibly far away and has
    # no strong title agreement.
    if _distance(anchor_bbox, best.bbox) > 240.0 and _title_similarity(product_name, best.title) < 20:
        return None
    return best


def _trusted_recipe_hints(
    links: list[PdfLink],
    product_name: str,
) -> list[str]:
    result = []
    for link in links:
        hint = _clean(link.recipe_query)
        if not hint:
            continue
        if _title_similarity(product_name, hint) >= 6:
            result.append(hint)
    return sorted(set(result))


def _local_lines(page: PageEvidence, bbox: Iterable[float]) -> list[TextLine]:
    area = _expand(bbox, 12.0, 16.0)
    return [line for line in page.lines if _intersects(line.bbox, area)]


def _local_links(page: PageEvidence, bbox: Iterable[float]) -> list[PdfLink]:
    area = _expand(bbox, 8.0, 8.0)
    return [link for link in page.links if _intersects(link.bbox, area)]


def _strict_validity(
    *,
    page: PageEvidence,
    strict_lines: list[TextLine],
    roi: Iterable[float],
    flyer_valid_from: date,
    flyer_valid_until: date,
) -> tuple[date, date, str]:
    year = flyer_valid_until.year
    candidates: list[tuple[float, date, date, str]] = []
    for line in strict_lines:
        vf, vu, source = _parse_validity(line.text, year, flyer_valid_until)
        if vf is None or vu is None or source is None:
            continue
        candidates.append((_distance(line.bbox, roi), vf, vu, "card_" + source))

    if candidates:
        _, vf, vu, source = min(candidates, key=lambda item: item[0])
        return vf, vu, source

    if page.page_valid_from and page.page_valid_until:
        return (
            page.page_valid_from,
            page.page_valid_until,
            page.page_validity_source or "page",
        )
    return flyer_valid_from, flyer_valid_until, "flyer_default"

def _channel(local_text: str) -> tuple[str, str]:
    folded = _fold(local_text)
    if "nur online" in folded:
        return "online_only", "local_nur_online"
    if "auch online" in folded:
        return "physical_and_online", "local_auch_online"
    return "physical_store", "no_local_online_only_marker"


def _scope(
    *,
    title: str,
    structured_category_text: str,
    page_meta: PageMeta | None,
) -> tuple[str, str]:
    """Classify from owned evidence only.

    Official product category wins when available. Otherwise the product title
    is used. Page metadata is only a final advisory fallback and can never
    override an explicit durable/non-target title.
    """
    title_text = _clean(title)
    category_text = _clean(structured_category_text)

    if _EDIBLE_HERB_RE.search(title_text):
        return "in_scope", "title_edible_herb"

    if category_text:
        if _STRUCTURED_NON_TARGET_CATEGORY_RE.search(category_text):
            return "excluded", "schwarz_non_target_category"
        if _STRUCTURED_TARGET_CATEGORY_RE.search(category_text):
            return "in_scope", "schwarz_target_category"

    if _HARD_NON_TARGET_TITLE_RE.search(title_text) or _ORNAMENTAL_PLANT_RE.search(title_text):
        return "excluded", "title_non_target"

    if (
        _INCLUDE_HOUSEHOLD.search(title_text)
        or _FOOD_DRINK_HINT.search(title_text)
        or _TITLE_TARGET_RE.search(title_text)
    ):
        return "in_scope", "title_target_taxonomy"

    if page_meta is not None and page_meta.target_hint:
        return "in_scope", "official_page_target_hint_title_not_excluded"

    return "review", "no_owned_scope_evidence"


def _stacked_value_below(
    label_bbox: Iterable[float],
    value_bbox: Iterable[float],
    *,
    x_tolerance: float,
    max_gap: float,
) -> bool:
    """True when a numeric line is visually stacked below its label.

    MuPDF font-metric rectangles for adjacent lines can overlap slightly.
    Treat that overlap as zero vertical gap instead of requiring a positive
    gap between rectangles.
    """
    lx0, ly0, lx1, ly1 = map(float, label_bbox)
    vx0, vy0, vx1, vy1 = map(float, value_bbox)
    if abs(vx0 - lx0) > x_tolerance:
        return False
    if vy0 < ly0 - 1.5:
        return False
    if vy0 - ly1 > max_gap:
        return False
    if vy1 <= ly0:
        return False
    return True


def _explicit_reference_price(
    *,
    lines: list[TextLine],
    anchor_rows: list[tuple[Decimal, tuple[float, float, float, float]]],
) -> tuple[Decimal | None, str | None]:
    """Return only a reference price proven inside the strict owned ROI.

    Unit-basis values such as `Normalpreis: 7.97/kg` are deliberately rejected.
    """
    candidates: list[tuple[float, Decimal, str]] = []
    anchor_bbox = _bbox_union([bbox for _value, bbox in anchor_rows]) if anchor_rows else None

    def add(value_text: str, source: str, bbox: Iterable[float], bonus: float) -> None:
        value = _decimal(value_text)
        if value is None:
            return
        score = (_distance(bbox, anchor_bbox) if anchor_bbox is not None else 0.0) + bonus
        candidates.append((score, value, source))

    for line in lines:
        text = _clean(line.text)
        # Explicit package Normalpreis remains valid when a separate unit-price
        # conversion follows after a semicolon. Slash-unit references such as
        # `Normalpreis: 7.97/kg` remain rejected by the regex itself.
        m = re.search(
            r"\bNormalpreis\s*:\s*(\d{1,3}[.,]\d{2})(?!\s*/\s*kg)",
            text,
            re.I,
        )
        if m:
            add(m.group(1), "normalpreis", line.bbox, -120.0)

        m = re.search(
            r"\bUVP\s*:?\s*(\d{1,3}[.,]\d{2})(?!\s*/\s*kg)",
            text,
            re.I,
        )
        if m:
            add(m.group(1), "uvp_inline", line.bbox, -110.0)

    # Handle split native lines: `Normal-` + `preis: 16.99`.
    ordered = sorted(lines, key=lambda item: (item.bbox[1], item.bbox[0]))
    for index, line in enumerate(ordered):
        text = _clean(line.text)
        if re.fullmatch(r"Normal-?", text, re.I):
            for nxt in ordered[index + 1:index + 4]:
                if not _stacked_value_below(
                    line.bbox,
                    nxt.bbox,
                    x_tolerance=20.0,
                    max_gap=18.0,
                ):
                    continue
                m = re.search(
                    r"\bpreis\s*:\s*(\d{1,3}[.,]\d{2})(?!\s*/\s*kg)",
                    _clean(nxt.text),
                    re.I,
                )
                if m:
                    add(m.group(1), "normalpreis", _bbox_union((line.bbox, nxt.bbox)), -115.0)

    # Handle `Normalpreis:` on one native line and the value directly
    # below it. Lidl frequently uses this typography for Plus-only cards.
    for index, line in enumerate(ordered):
        if not re.fullmatch(r"Normalpreis\s*:?", _clean(line.text), re.I):
            continue
        for nxt in ordered[index + 1:index + 4]:
            if not _stacked_value_below(
                line.bbox,
                nxt.bbox,
                x_tolerance=20.0,
                max_gap=18.0,
            ):
                continue
            text = _clean(nxt.text)
            # A leading package price may share this line with a semicolon
            # separated `1 kg = ...` / `1 l = ...` conversion.
            m = re.match(
                r"^(\d{1,3}[.,]\d{2})(?!\s*/\s*kg)(?:\s*;|\s*$)",
                text,
                re.I,
            )
            if m:
                add(
                    m.group(1),
                    "normalpreis",
                    _bbox_union((line.bbox, nxt.bbox)),
                    -115.0,
                )
                break

    # Handle the common two-line `UVP` / value typography.
    uvp_lines = [
        line for line in ordered
        if re.fullmatch(r"UVP", _clean(line.text), re.I)
    ]
    for uvp in uvp_lines:
        for value_line in ordered:
            text = _clean(value_line.text)
            if re.search(r"(?:/\s*kg\b|\bkg-?preis\b|\b1\s*kg\s*=)", text, re.I):
                continue
            m = re.fullmatch(r"(\d{1,3}[.,]\d{2})", text)
            if not m:
                continue
            if _stacked_value_below(
                uvp.bbox,
                value_line.bbox,
                x_tolerance=12.0,
                max_gap=14.0,
            ):
                add(
                    m.group(1),
                    "uvp",
                    _bbox_union((uvp.bbox, value_line.bbox)),
                    -105.0,
                )

    if not candidates:
        return None, None

    candidates.sort(key=lambda row: (row[0], row[1], row[2]))
    best = candidates[0]
    # If two different values are almost equally plausible, fail closed.
    if len(candidates) > 1:
        runner = candidates[1]
        if runner[1] != best[1] and runner[0] - best[0] < 8.0:
            return None, None
    return best[1], best[2]

def _owned_anchor_values(occurrence: dict[str, Any]) -> list[Decimal]:
    values: list[Decimal] = []
    for key in occurrence.get("anchor_keys") or []:
        if not isinstance(key, (list, tuple)) or len(key) < 2:
            continue
        value = _decimal(key[1])
        if value is not None:
            values.append(value)
    return values


def _owned_anchor_bboxes(
    occurrence: dict[str, Any],
    *,
    one_based_page: int,
) -> list[tuple[Decimal, tuple[float, float, float, float]]]:
    rows: list[tuple[Decimal, tuple[float, float, float, float]]] = []
    for key in occurrence.get("anchor_keys") or []:
        if not isinstance(key, (list, tuple)) or len(key) < 3:
            continue
        try:
            page = int(key[0])
            bbox = tuple(float(v) for v in key[2])
        except (TypeError, ValueError):
            continue
        value = _decimal(key[1])
        if value is None or len(bbox) != 4 or page != one_based_page:
            continue
        rows.append((value, bbox))
    return rows


def _value_owned(value: Decimal | None, owned_values: list[Decimal]) -> bool:
    if value is None:
        return True
    return value in owned_values



def _same_identity(first: str, second: str) -> bool:
    a = _compact_identity(first)
    b = _compact_identity(second)
    if not a or not b:
        return False
    if len(a) >= 6 and (a in b or b in a):
        return True
    return SequenceMatcher(None, a, b).ratio() >= 0.90


def _plain_display_price_from_span(span: dict[str, Any]) -> Decimal | None:
    font = str(span.get("font") or "").casefold()
    size = float(span.get("size") or 0.0)
    text = _clean(span.get("text"))
    if "lidlfontprice-pt" not in font or size < 20.0:
        return None
    m = re.fullmatch(r"(\d{1,4})[.,](\d{2})\s*\*?", text)
    if not m:
        return None
    return Decimal(f"{int(m.group(1))}.{m.group(2)}")


def _variable_weight_evidence(package_text: str | None, strict_text: str) -> tuple[bool, list[str]]:
    folded = _fold(f"{package_text or ''} {strict_text}")
    variable = "nach gewicht" in folded or "preis nach gewicht" in folded
    candidates: list[str] = []
    if variable:
        for pattern in (
            r"\bkg-?preis\s*(?:=|:)?\s*(\d{1,3}[.,]\d{2})",
            r"\b1\s*kg\s*=\s*(\d{1,3}[.,]\d{2})",
            r"\bNormalpreis\s*:\s*(\d{1,3}[.,]\d{2})\s*/\s*kg",
        ):
            for match in re.finditer(pattern, strict_text, re.I):
                value = _decimal(match.group(1))
                if value is not None:
                    candidates.append(str(value))
    return variable, sorted(set(candidates))


def _recovered_starred_rows(
    *,
    document: bytes,
    base: Any,
    pages: tuple[PageEvidence, ...],
    page_meta: dict[int, PageMeta],
    existing_rows: list[dict[str, Any]],
    flyer: Any,
) -> list[dict[str, Any]]:
    """Recover only unowned starred anchors using an unowned strict PDF title."""
    consumed: set[tuple[int, str, tuple[float, ...]]] = set()
    used_titles: dict[int, list[str]] = {}
    for row in existing_rows:
        used_titles.setdefault(int(row["page"]), []).append(str(row["product_name"]))
        for item in row.get("owned_anchor_bboxes") or []:
            consumed.add((
                int(row["page"]),
                str(item["price"]),
                tuple(round(float(v), 3) for v in item["bbox"]),
            ))

    page_spans = r61_base.extract_pdf_spans(document)

    result: list[dict[str, Any]] = []
    for observation in base.display_prices:
        page_no = int(observation.page) + 1
        key = (
            page_no,
            str(_decimal(observation.price_eur)),
            tuple(round(float(v), 3) for v in observation.bbox),
        )
        if key in consumed:
            continue

        titles = r61_base._title_groups(page_spans[observation.page])
        candidates: list[tuple[float, Any]] = []
        for title in titles:
            if not title.strict or r61_base._is_suspicious_title(title.text):
                continue
            if any(_same_identity(title.text, used) for used in used_titles.get(page_no, [])):
                continue
            # Strong local geometry: title above the price, overlapping the
            # same column, and within one normal Lidl card height.
            horizontal_overlap = max(
                0.0,
                min(title.bbox[2], observation.bbox[2])
                - max(title.bbox[0], observation.bbox[0]),
            )
            min_width = max(1.0, min(
                title.bbox[2] - title.bbox[0],
                observation.bbox[2] - observation.bbox[0],
            ))
            overlap_ratio = horizontal_overlap / min_width
            vertical_gap = observation.bbox[1] - title.bbox[3]
            center_delta = abs(_bbox_center(title.bbox)[0] - _bbox_center(observation.bbox)[0])
            if vertical_gap < -8.0 or vertical_gap > 125.0:
                continue
            if overlap_ratio < 0.20 and center_delta > 28.0:
                continue
            score = max(vertical_gap, 0.0) + 0.25 * center_delta - 35.0 * overlap_ratio
            candidates.append((score, title))

        if not candidates:
            continue
        candidates.sort(key=lambda row: (row[0], row[1].group_id))
        best_score, title = candidates[0]
        if best_score > 95.0:
            continue
        if len(candidates) > 1 and candidates[1][0] - best_score < 12.0:
            continue

        page = pages[page_no - 1]
        anchor_rows = [(_decimal(observation.price_eur), tuple(map(float, observation.bbox)))]
        roi = _strict_card_roi(
            page=page,
            title_bbox=title.bbox,
            anchor_rows=[row for row in anchor_rows if row[0] is not None],
            all_page_prices=[
                p for p in base.display_prices if int(p.page) == int(observation.page)
            ],
        )
        lines = _strict_lines(page, roi)
        strict_text = _clean(" ".join(line.text for line in lines))
        package_text = None
        temp_card = r61_base.PhysicalCard(
            page=int(observation.page),
            card_index=-10000 - len(result),
            bbox=roi,
            spans=tuple(
                span
                for span in page_spans[observation.page]
                if _contained(span.bbox, roi)
            ),
            prices=(observation,),
            title=title.text,
            title_bbox=title.bbox,
        )
        try:
            package_text, _sources = r61_base._package_text(temp_card)
        except Exception:
            package_text = None

        valid_from, valid_until, validity_source = _strict_validity(
            page=page,
            strict_lines=lines,
            roi=roi,
            flyer_valid_from=flyer.valid_from,
            flyer_valid_until=flyer.valid_until,
        )
        scope, scope_source = _scope(
            title=title.text,
            structured_category_text="",
            page_meta=page_meta.get(page_no),
        )
        variable, unit_candidates = _variable_weight_evidence(package_text, strict_text)
        rejections: list[str] = []
        if scope == "excluded":
            rejections.append("outside_hermes_deals_scope")
        if variable:
            rejections.append("variable_weight_requires_unit_basis_model")

        result.append({
            "page": page_no,
            "product_name": _clean(title.text),
            "package_text": _clean(package_text) or None,
            "price_eur": str(_decimal(observation.price_eur)),
            "regular_price_eur": None,
            "regular_price_source": None,
            "app_price_eur": None,
            "valid_from": valid_from.isoformat(),
            "valid_until": valid_until.isoformat(),
            "validity_source": validity_source,
            "channel": "physical_store",
            "channel_source": "starred_pdf_anchor_default_physical",
            "scope": scope,
            "scope_source": scope_source,
            "product_link_ids": [],
            "schwarz_product_title": None,
            "schwarz_structured_price": None,
            "schwarz_online_column_signal": False,
            "recipe_identity_hints": [],
            "base_anchor_ok": True,
            "base_evidence_source": "recovered_unowned_starred_display_anchor",
            "app_anchor_ok": True,
            "local_lidl_plus_marker": False,
            "app_evidence_geometry_scoped": False,
            "owned_anchor_values": [str(_decimal(observation.price_eur))],
            "owned_anchor_bboxes": [{
                "price": str(_decimal(observation.price_eur)),
                "bbox": [float(v) for v in observation.bbox],
            }],
            "card_bbox": [float(v) for v in roi],
            "strict_roi": [float(v) for v in roi],
            "r6_classification": "r61_v6_unowned_starred_rescue",
            "r6_official_product_id": None,
            "rejection_reasons": rejections,
            "warnings": [] if scope != "review" else ["scope_requires_review"],
            "price_basis": "variable_weight_example" if variable else "fixed_or_explicit",
            "unit_price_candidates_eur_per_kg": unit_candidates,
            "comparison_eligible_shadow": not variable,
            "production_ready_shadow": not rejections and scope == "in_scope",
            "recovery_source": "unowned_starred_anchor_plus_unowned_strict_title",
        })
        used_titles.setdefault(page_no, []).append(title.text)
    return result


def _recovered_structured_unstarred_rows(
    *,
    base: Any,
    pages: tuple[PageEvidence, ...],
    page_meta: dict[int, PageMeta],
    schwarz_links_by_page: dict[int, tuple[SchwarzLink, ...]],
    existing_rows: list[dict[str, Any]],
    flyer: Any,
) -> list[dict[str, Any]]:
    """Recover an unmatched official product only with three agreeing signals:
    structured product id/title/price, native PDF title, and matching unstarred
    Lidl price typography. The official hotspot binds the page / product but is
    not assumed to cover the price glyph itself.
    """
    used_product_ids = {
        pid
        for row in existing_rows
        for pid in (row.get("product_link_ids") or [])
        if pid
    }
    consumed_price_bboxes = {
        (
            int(row["page"]),
            str(item.get("price")),
            tuple(round(float(v), 3) for v in item.get("bbox", ())),
        )
        for row in existing_rows
        for item in (row.get("owned_anchor_bboxes") or [])
        if item.get("price") is not None and len(item.get("bbox", ())) == 4
    }
    result: list[dict[str, Any]] = []

    for page_no, links in schwarz_links_by_page.items():
        page = pages[page_no - 1]
        for link in links:
            if (
                link.display_type != "product"
                or not link.product_id
                or link.product_id in used_product_ids
                or link.structured_price is None
                or not link.title
            ):
                continue

            # Do not create a second row for a product R6 already represents
            # merely because the structured product ID was not attached.
            represented = False
            for existing in existing_rows:
                if int(existing.get("page") or -1) != page_no:
                    continue
                existing_name = _clean(existing.get("product_name"))
                existing_price = _decimal(existing.get("price_eur"))
                if _same_identity(existing_name, link.title):
                    represented = True
                    break
                if (
                    existing_price == link.structured_price
                    and _title_similarity(existing_name, link.title) >= 12
                ):
                    represented = True
                    break
            if represented:
                used_product_ids.add(link.product_id)
                continue

            # Independent native-title agreement.
            title_candidates: list[tuple[float, TextLine]] = []
            for line in page.lines:
                score = _title_similarity(line.text, link.title)
                if score < 8:
                    continue
                title_candidates.append((
                    _distance(line.bbox, link.bbox) - score * 2.0,
                    line,
                ))
            if not title_candidates:
                continue
            title_candidates.sort(key=lambda row: (row[0], row[1].bbox))
            title_line = title_candidates[0][1]

            # Exact structured price in Lidl's large price font, geometrically
            # local to the matching native title.
            price_candidates: list[
                tuple[float, tuple[float, float, float, float]]
            ] = []
            for line in page.lines:
                for span in line.spans:
                    value = _plain_display_price_from_span(span)
                    if value != link.structured_price:
                        continue
                    bbox = tuple(float(v) for v in span["bbox"])
                    consumed_key = (
                        page_no,
                        str(link.structured_price),
                        tuple(round(float(v), 3) for v in bbox),
                    )
                    if consumed_key in consumed_price_bboxes:
                        continue
                    horizontal, vertical = (
                        max(
                            0.0,
                            title_line.bbox[0] - bbox[2],
                            bbox[0] - title_line.bbox[2],
                        ),
                        max(
                            0.0,
                            title_line.bbox[1] - bbox[3],
                            bbox[1] - title_line.bbox[3],
                        ),
                    )
                    if horizontal > 105.0 or vertical > 125.0:
                        continue
                    score = (
                        horizontal
                        + 0.65 * vertical
                        + 0.15
                        * abs(
                            _bbox_center(title_line.bbox)[0]
                            - _bbox_center(bbox)[0]
                        )
                        + 0.05 * _distance(bbox, link.bbox)
                    )
                    price_candidates.append((score, bbox))
            if not price_candidates:
                continue
            price_candidates.sort(key=lambda row: (row[0], row[1]))
            if (
                len(price_candidates) > 1
                and price_candidates[1][0] - price_candidates[0][0] < 10.0
            ):
                continue
            price_bbox = price_candidates[0][1]

            roi = _strict_card_roi(
                page=page,
                title_bbox=title_line.bbox,
                anchor_rows=[(link.structured_price, price_bbox)],
                all_page_prices=[
                    p for p in base.display_prices if int(p.page) + 1 == page_no
                ],
            )
            lines = _strict_lines(page, roi)
            valid_from, valid_until, validity_source = _strict_validity(
                page=page,
                strict_lines=lines,
                roi=roi,
                flyer_valid_from=flyer.valid_from,
                flyer_valid_until=flyer.valid_until,
            )
            scope, scope_source = _scope(
                title=link.title,
                structured_category_text=link.category_text,
                page_meta=page_meta.get(page_no),
            )
            channel = "online_only" if link.online_column_signal else "physical_store"
            rejections = ["online_only"] if channel == "online_only" else []
            if scope == "excluded":
                rejections.append("outside_hermes_deals_scope")

            result.append({
                "page": page_no,
                "product_name": _clean(link.title),
                "package_text": None,
                "price_eur": str(link.structured_price),
                "regular_price_eur": None,
                "regular_price_source": None,
                "app_price_eur": None,
                "valid_from": valid_from.isoformat(),
                "valid_until": valid_until.isoformat(),
                "validity_source": validity_source,
                "channel": channel,
                "channel_source": (
                    "schwarz_online_column" if link.online_column_signal
                    else "schwarz_structured_product"
                ),
                "scope": scope,
                "scope_source": scope_source,
                "product_link_ids": [link.product_id],
                "schwarz_product_title": link.title,
                "schwarz_structured_price": str(link.structured_price),
                "schwarz_category_text": link.category_text,
                "schwarz_online_column_signal": bool(link.online_column_signal),
                "recipe_identity_hints": [],
                "base_anchor_ok": True,
                "base_evidence_source": "structured_price_plus_unstarred_pdf_display",
                "app_anchor_ok": True,
                "local_lidl_plus_marker": False,
                "app_evidence_geometry_scoped": False,
                "owned_anchor_values": [str(link.structured_price)],
                "owned_anchor_bboxes": [{
                    "price": str(link.structured_price),
                    "bbox": [float(v) for v in price_bbox],
                }],
                "card_bbox": [float(v) for v in roi],
                "strict_roi": [float(v) for v in roi],
                "r6_classification": "r61_v6_structured_unstarred_rescue",
                "r6_official_product_id": link.product_id,
                "rejection_reasons": rejections,
                "warnings": [] if scope != "review" else ["scope_requires_review"],
                "price_basis": "fixed_or_explicit",
                "unit_price_candidates_eur_per_kg": [],
                "comparison_eligible_shadow": channel != "online_only",
                "production_ready_shadow": (
                    not rejections and scope == "in_scope" and channel != "online_only"
                ),
                "recovery_source": "schwarz_product_plus_native_title_plus_unstarred_pdf_display",
            })
            used_product_ids.add(link.product_id)
    return result


def _card_local_validity_override(
    *,
    page: PageEvidence,
    strict_roi: Iterable[float],
    card_bbox: Iterable[float],
    flyer_valid_until: date,
) -> tuple[date, date, str] | None:
    """Probe only this card's horizontal cell, up to 18 pt above its bbox."""
    rx0, _ry0, rx1, _ry1 = map(float, strict_roi)
    _cx0, cy0, _cx1, cy1 = map(float, card_bbox)
    probe = (
        max(0.0, rx0),
        max(0.0, cy0 - 18.0),
        min(page.width, rx1),
        min(page.height, cy1 + 2.0),
    )
    candidates: list[tuple[float, date, date, str]] = []
    year = flyer_valid_until.year
    for line in _strict_lines(page, probe):
        vf, vu, source = _parse_validity(line.text, year, flyer_valid_until)
        if vf is None or vu is None or source is None:
            continue
        candidates.append(
            (_distance(line.bbox, card_bbox), vf, vu, "card_extended_" + source)
        )
    if not candidates:
        return None
    _score, vf, vu, source = min(candidates, key=lambda item: item[0])
    return vf, vu, source


def _promote_page_consensus_scope(rows: list[dict[str, Any]]) -> int:
    """Conservatively resolve residual review rows on clearly target-heavy pages."""
    by_page: dict[int, list[dict[str, Any]]] = {}
    for row in rows:
        if row.get("channel") == "online_only":
            continue
        by_page.setdefault(int(row["page"]), []).append(row)

    promoted = 0
    for page_rows in by_page.values():
        in_count = sum(row.get("scope") == "in_scope" for row in page_rows)
        excluded_count = sum(row.get("scope") == "excluded" for row in page_rows)
        review_rows = [row for row in page_rows if row.get("scope") == "review"]
        if not review_rows or in_count < 2 or in_count < excluded_count:
            continue
        for row in review_rows:
            row["scope"] = "in_scope"
            row["scope_source"] = "page_consensus_target_after_owned_evidence"
            row["warnings"] = [
                warning for warning in (row.get("warnings") or [])
                if warning != "scope_requires_review"
            ]
            row["production_ready_shadow"] = not (row.get("rejection_reasons") or [])
            promoted += 1
    return promoted


def _parse_r6_v631(
    *,
    document: bytes,
    flyer: Any,
    snapshot_id: Any,
    collected_at: datetime,
) -> Any:
    """Run frozen R6 with a narrow Stage-2 ownership view.

    The immutable R6 base stays byte-for-byte untouched. Original PDF spans
    still drive the fingerprint, display-price extraction and semantics. Only
    title ownership removes exact promotional labels and disambiguates the
    proven `Maxi King` product phrase from R6 short size-label heuristic.
    """
    pages = r61_base.extract_pdf_spans(document)
    ownership_pages = []
    for page in pages:
        ownership_spans = []
        for span in page:
            adjusted = _ownership_span_text(getattr(span, "text", ""))
            if adjusted is None:
                continue
            if adjusted != getattr(span, "text", ""):
                span = dataclass_replace(span, text=adjusted)
            ownership_spans.append(span)
        ownership_pages.append(tuple(ownership_spans))
    ownership_pages = tuple(ownership_pages)

    dimensions = r61_base._page_dimensions(document, pages)
    document_sha256 = hashlib.sha256(document).hexdigest()
    structured_prices = r61_base._structured_product_prices(flyer.raw_fetch)
    fingerprint = r61_base.parser_input_fingerprint_v1(
        pages,
        document_sha256=document_sha256,
        product_bindings=flyer.product_bindings,
        structured_product_prices=structured_prices,
    )
    display_prices = r61_base.extract_display_price_observations(pages)
    cards = r61_base.build_physical_cards(
        ownership_pages,
        display_prices,
        product_bindings=flyer.product_bindings,
        page_dimensions=dimensions,
    )
    cards = tuple(_restore_ownership_card_title(card) for card in cards)
    cards = r61_base._rescue_structured_card_prices(
        cards,
        pages=pages,
        product_bindings=flyer.product_bindings,
        structured_product_prices=structured_prices,
    )
    semantic, semantic_unresolved = r61_base.extract_card_semantics(
        cards,
        flyer=flyer,
        product_bindings=flyer.product_bindings,
        page_dimensions=dimensions,
    )
    offers, dedup_unresolved = r61_base.deduplicate_semantic_offers(
        semantic,
        flyer=flyer,
        snapshot_id=snapshot_id,
        collected_at=collected_at,
    )
    return r61_base.LidlParseResult(
        offers=offers,
        unresolved=tuple((*semantic_unresolved, *dedup_unresolved)),
        parser_input_fingerprint_v1=fingerprint,
        display_prices=display_prices,
        physical_cards=cards,
        semantic_occurrences=semantic,
    )


def analyze_lidl_pdf(
    *,
    document: bytes,
    flyer: Any,
    snapshot_id: Any,
    collected_at: datetime,
) -> dict[str, Any]:
    """Run exact R6, then reconcile only with stricter owned evidence.

    Shadow only: no DB write and no production parser replacement.
    """
    base = _parse_r6_v631(
        document=document,
        flyer=flyer,
        snapshot_id=snapshot_id,
        collected_at=collected_at,
    )

    pages = extract_pdf_evidence(document, flyer.valid_until)
    page_meta = _parse_schwarz_page_meta(flyer.raw_fetch)
    schwarz_links_by_page = _parse_schwarz_page_links(flyer.raw_fetch, pages)
    cards_by_index = {card.card_index: card for card in base.physical_cards}
    page_prices: dict[int, list[Any]] = {}
    for price in base.display_prices:
        page_prices.setdefault(int(price.page) + 1, []).append(price)

    output: list[dict[str, Any]] = []

    for occurrence in base.semantic_occurrences:
        occ = dict(getattr(occurrence, "occurrence", {}) or {})
        page_index = int(getattr(occurrence, "page"))
        page_no = page_index + 1
        if int(occ.get("page") or page_no) != page_no:
            raise RuntimeError(
                f"page-domain mismatch: semantic={page_index} occurrence={occ.get('page')}"
            )
        page = pages[page_index]
        card_index = int(occ.get("card_index"))
        card = cards_by_index.get(card_index)
        if card is None:
            raise RuntimeError(f"missing physical card for semantic card_index={card_index}")

        product_name = _clean(getattr(occurrence, "product_name", ""))
        package_text = _clean(getattr(occurrence, "package_text", "")) or None
        price = _decimal(getattr(occurrence, "price_eur", None))
        app_price = _decimal(getattr(occurrence, "app_price_eur", None))

        owned_values = _owned_anchor_values(occ)
        owned_anchor_rows = _owned_anchor_bboxes(occ, one_based_page=page_no)
        roi = _strict_card_roi(
            page=page,
            title_bbox=card.title_bbox,
            anchor_rows=owned_anchor_rows,
            all_page_prices=page_prices.get(page_no, ()),
        )
        strict_lines = _strict_lines(page, roi)
        strict_text = _clean(" ".join(line.text for line in strict_lines))
        strict_links = _strict_links(page, roi)

        valid_from, valid_until, validity_source = _strict_validity(
            page=page,
            strict_lines=strict_lines,
            roi=roi,
            flyer_valid_from=flyer.valid_from,
            flyer_valid_until=flyer.valid_until,
        )

        local_validity = _card_local_validity_override(
            page=page,
            strict_roi=roi,
            card_bbox=card.bbox,
            flyer_valid_until=flyer.valid_until,
        )
        if local_validity is not None:
            valid_from, valid_until, validity_source = local_validity

        regular_price, regular_source = _explicit_reference_price(
            lines=strict_lines,
            anchor_rows=owned_anchor_rows,
        )

        base_anchor_ok = _value_owned(price, owned_values)
        base_evidence_source = "owned_display_anchor" if base_anchor_ok else None
        app_anchor_ok = _value_owned(app_price, owned_values)

        # A Plus-only card can expose only the Plus price in LidlFontPrice while
        # the non-app price is an explicit Normalpreis or UVP in the same strict
        # ROI. Accept it only when that explicit reference equals R6 base price.
        if (
            not base_anchor_ok
            and app_price is not None
            and regular_price is not None
            and price is not None
            and regular_price == price
            and regular_source in {"normalpreis", "uvp", "uvp_inline"}
        ):
            base_anchor_ok = True
            base_evidence_source = "explicit_owned_reference_price"

        app_geometry_scoped = bool(occ.get("app_evidence_geometry_scoped"))
        app_marker_ok = app_price is None or app_geometry_scoped
        local_plus = "mit lidl plus" in _fold(strict_text)

        schwarz_links = schwarz_links_by_page.get(page_no, ())
        matched_schwarz = _match_schwarz_product_link(
            links=schwarz_links,
            product_name=product_name,
            price=price,
            app_price=app_price,
            anchor_rows=owned_anchor_rows,
            card_bbox=roi,
        )

        native_channel, native_channel_source = _channel(strict_text)
        if matched_schwarz is not None and matched_schwarz.online_column_signal:
            channel = "online_only"
            channel_source = "schwarz_online_column"
        else:
            channel = native_channel
            channel_source = native_channel_source

        scope, scope_source = _scope(
            title=product_name,
            structured_category_text=(
                matched_schwarz.category_text if matched_schwarz is not None else ""
            ),
            page_meta=page_meta.get(page_no),
        )

        product_ids = (
            [matched_schwarz.product_id]
            if matched_schwarz is not None and matched_schwarz.product_id
            else []
        )
        recipe_hints = _trusted_recipe_hints(strict_links, product_name)

        variable_weight, unit_candidates = _variable_weight_evidence(
            package_text,
            strict_text,
        )

        rejection_reasons: list[str] = []
        warnings: list[str] = []
        if not product_name:
            rejection_reasons.append("missing_product_title")
        if price is None or price <= 0:
            rejection_reasons.append("missing_or_invalid_store_price")
        if not base_anchor_ok:
            rejection_reasons.append("store_price_without_owned_evidence")
        if not app_anchor_ok:
            rejection_reasons.append("app_price_without_owned_display_anchor")
        if not app_marker_ok:
            rejection_reasons.append("app_price_without_r6_geometry_scope")
        if valid_until < valid_from:
            rejection_reasons.append("invalid_validity_interval")
        if channel == "online_only":
            rejection_reasons.append("online_only")
        if scope == "excluded":
            rejection_reasons.append("outside_hermes_deals_scope")
        if variable_weight:
            rejection_reasons.append("variable_weight_requires_unit_basis_model")
        if scope == "review":
            warnings.append("scope_requires_review")

        # A reference below the store price is not credible for this contract.
        if regular_price is not None and price is not None and regular_price < price:
            warnings.append("reference_price_below_store_price_dropped")
            regular_price = None
            regular_source = None

        output.append({
            "page": page_no,
            "product_name": product_name,
            "package_text": package_text,
            "price_eur": str(price) if price is not None else None,
            "regular_price_eur": str(regular_price) if regular_price is not None else None,
            "regular_price_source": regular_source,
            "app_price_eur": str(app_price) if app_price is not None else None,
            "valid_from": valid_from.isoformat(),
            "valid_until": valid_until.isoformat(),
            "validity_source": validity_source,
            "app_valid_from": occ.get("app_valid_from"),
            "app_valid_until": occ.get("app_valid_until"),
            "app_validity_source": occ.get("app_validity_source"),
            "channel": channel,
            "channel_source": channel_source,
            "scope": scope,
            "scope_source": scope_source,
            "product_link_ids": product_ids,
            "schwarz_product_title": (
                matched_schwarz.title if matched_schwarz is not None else None
            ),
            "schwarz_structured_price": (
                str(matched_schwarz.structured_price)
                if matched_schwarz is not None
                and matched_schwarz.structured_price is not None
                else None
            ),
            "schwarz_category_text": (
                matched_schwarz.category_text if matched_schwarz is not None else ""
            ),
            "schwarz_online_column_signal": (
                bool(matched_schwarz.online_column_signal)
                if matched_schwarz is not None else False
            ),
            "recipe_identity_hints": recipe_hints,
            "base_anchor_ok": base_anchor_ok,
            "base_evidence_source": base_evidence_source,
            "app_anchor_ok": app_anchor_ok,
            "local_lidl_plus_marker": local_plus,
            "app_evidence_geometry_scoped": app_geometry_scoped,
            "owned_anchor_values": [str(value) for value in owned_values],
            "owned_anchor_bboxes": [
                {"price": str(value), "bbox": list(bbox)}
                for value, bbox in owned_anchor_rows
            ],
            "card_bbox": [float(v) for v in card.bbox],
            "strict_roi": [float(v) for v in roi],
            "r6_classification": _clean(getattr(occurrence, "classification", "")) or None,
            "r6_official_product_id": (
                None
                if getattr(occurrence, "official_product_id", None) is None
                else str(getattr(occurrence, "official_product_id"))
            ),
            "rejection_reasons": rejection_reasons,
            "warnings": warnings,
            "price_basis": "variable_weight_example" if variable_weight else "fixed_or_explicit",
            "unit_price_candidates_eur_per_kg": unit_candidates,
            "comparison_eligible_shadow": not variable_weight and channel != "online_only",
            "production_ready_shadow": (
                not rejection_reasons and scope == "in_scope"
            ),
            "recovery_source": None,
        })

    # Post-R6 rescue never reassigns an existing title. It may only consume
    # previously unowned evidence.
    starred_rescue = _recovered_starred_rows(
        document=document,
        base=base,
        pages=pages,
        page_meta=page_meta,
        existing_rows=output,
        flyer=flyer,
    )
    output.extend(starred_rescue)

    structured_rescue = _recovered_structured_unstarred_rows(
        base=base,
        pages=pages,
        page_meta=page_meta,
        schwarz_links_by_page=schwarz_links_by_page,
        existing_rows=output,
        flyer=flyer,
    )
    output.extend(structured_rescue)

    inherited_app_validity_reconciled = 0
    for row in output:
        if (
            row.get("app_price_eur") is not None
            and row.get("app_validity_source") == "inherits_base"
        ):
            if (
                row.get("app_valid_from") != row.get("valid_from")
                or row.get("app_valid_until") != row.get("valid_until")
            ):
                inherited_app_validity_reconciled += 1
            row["app_valid_from"] = row.get("valid_from")
            row["app_valid_until"] = row.get("valid_until")

    page_consensus_promoted = _promote_page_consensus_scope(output)

    output.sort(key=lambda row: (
        int(row["page"]),
        float(row["owned_anchor_bboxes"][0]["bbox"][1])
        if row.get("owned_anchor_bboxes") else 0.0,
        float(row["owned_anchor_bboxes"][0]["bbox"][0])
        if row.get("owned_anchor_bboxes") else 0.0,
        row["product_name"],
    ))

    unresolved = []
    for row in getattr(base, "unresolved", ()):
        unresolved.append({
            "reason": _clean(getattr(row, "reason", "")),
            "page": (
                None if getattr(row, "page", None) is None
                else int(getattr(row, "page")) + 1
            ),
            "text": _clean(getattr(row, "text", "")),
        })

    return {
        "parser_version": PARSER_VERSION,
        "base_parser_version": getattr(r61_base, "PARSER_VERSION", None),
        "base_metrics": {
            "display_prices": len(base.display_prices),
            "physical_cards": len(base.physical_cards),
            "semantic_occurrences": len(base.semantic_occurrences),
            "offers": len(base.offers),
            "unresolved": len(base.unresolved),
        },
        "v6_metrics": {
            "rows": len(output),
            "starred_rescued": len(starred_rescue),
            "structured_unstarred_rescued": len(structured_rescue),
            "page_consensus_promoted": page_consensus_promoted,
            "inherited_app_validity_reconciled": inherited_app_validity_reconciled,
            "production_ready_shadow": sum(
                bool(row["production_ready_shadow"]) for row in output
            ),
            "comparison_eligible_shadow": sum(
                bool(row["comparison_eligible_shadow"]) for row in output
            ),
            "scope_in": sum(row["scope"] == "in_scope" for row in output),
            "scope_review": sum(row["scope"] == "review" for row in output),
            "scope_excluded": sum(row["scope"] == "excluded" for row in output),
            "online_only": sum(row["channel"] == "online_only" for row in output),
            "variable_weight": sum(
                row["price_basis"] == "variable_weight_example" for row in output
            ),
        },
        "shadow_rows": output,
        "base_unresolved": unresolved,
    }


