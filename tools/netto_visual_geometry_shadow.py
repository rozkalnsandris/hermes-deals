from __future__ import annotations

from dataclasses import asdict, dataclass
from decimal import Decimal, InvalidOperation
import math
from pathlib import Path
import re
from statistics import median
from typing import Any, Iterable, Mapping, Sequence


PARSER_IDENTITY = "netto-visual-geometry-shadow-v3-unrotated-page-space"
PRICE_RE = re.compile(r"(?<!\d)(\d{1,3})[,.](\d{2})(?!\d)")
MAJOR_PRICE_RE = re.compile(r"^\s*(\d{1,3})[.,]\s*$")
CENTS_PRICE_RE = re.compile(r"^\s*(\d{2})\s*$")
MEMBER_LABEL_RE = re.compile(r"(?:\bnetto\s*\+|\bnetto\s+plus\b|\bapp[- ]?preis\b)", re.I)
REGULAR_LABEL_RE = re.compile(r"\b(?:uvp|statt|bisher)\b", re.I)
UNIT_LABEL_RE = re.compile(
    r"(?:\b(?:100\s*g|100\s*ml|1\s*kg|1\s*l|kg|liter|stück|st\.)\b|grundpreis|einzelpreis|pfand)",
    re.I,
)
PROMO_EXACT = {
    "bis",
    "du entscheidest",
    "kracher",
    "marke",
    "marke oder netto marke",
    "netto marke",
    "video anleitung",
    "versch",
    "verschiedene",
}
PROMO_PREFIXES = (
    "abgabe nur in haushaltsüblichen mengen",
    "angebot gilt nur in ausgewählten filialen",
    "aus unserer eigenen fleisch und wurst fachabteilung",
    "für die artikel auf der seite",
)


@dataclass(frozen=True)
class Box:
    x0: float
    y0: float
    x1: float
    y1: float

    @property
    def width(self) -> float:
        return max(0.0, self.x1 - self.x0)

    @property
    def height(self) -> float:
        return max(0.0, self.y1 - self.y0)

    @property
    def area(self) -> float:
        return self.width * self.height

    @property
    def cx(self) -> float:
        return (self.x0 + self.x1) / 2.0

    @property
    def cy(self) -> float:
        return (self.y0 + self.y1) / 2.0

    def expanded(self, amount: float) -> "Box":
        return Box(self.x0 - amount, self.y0 - amount, self.x1 + amount, self.y1 + amount)

    def contains_point(self, x: float, y: float, tolerance: float = 0.0) -> bool:
        return (
            self.x0 - tolerance <= x <= self.x1 + tolerance
            and self.y0 - tolerance <= y <= self.y1 + tolerance
        )


@dataclass(frozen=True)
class TextSpan:
    index: int
    text: str
    bbox: Box
    size: float
    font: str
    color: int
    flags: int


@dataclass(frozen=True)
class Separator:
    orientation: str
    x1: float
    y1: float
    x2: float
    y2: float
    length: float


@dataclass(frozen=True)
class PriceAnchor:
    anchor_id: str
    span_index: int
    component_span_indexes: tuple[int, ...]
    source_kind: str
    value: str
    bbox: Box
    font_size: float
    member_labeled: bool
    regular_labeled: bool
    unit_labeled: bool


@dataclass(frozen=True)
class PriceGroup:
    group_id: str
    anchor_ids: tuple[str, ...]
    bbox: Box


def normalize_text(value: object) -> str:
    text = str(value or "").casefold()
    text = text.replace("ß", "ss")
    text = re.sub(r"[-_/]+", " ", text)
    text = re.sub(r"[^\wäöü]+", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def title_tokens(value: object) -> tuple[str, ...]:
    ignored = {
        "und", "oder", "der", "die", "das", "mit", "von", "aus", "im", "in",
        "versch", "verschiedene", "sorten", "sorte",
    }
    return tuple(
        token
        for token in normalize_text(value).split()
        if len(token) >= 3 and token not in ignored
    )


def canonical_price(value: object) -> str | None:
    try:
        parsed = Decimal(str(value).replace(",", ".")).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None
    if parsed <= 0:
        return None
    return f"{parsed:.2f}"


def _box(value: Sequence[object]) -> Box:
    return Box(*(float(value[index]) for index in range(4)))


def _distance(a: Box, b: Box) -> float:
    return math.hypot(a.cx - b.cx, a.cy - b.cy)


def _union(boxes: Sequence[Box]) -> Box:
    return Box(
        min(box.x0 for box in boxes),
        min(box.y0 for box in boxes),
        max(box.x1 for box in boxes),
        max(box.y1 for box in boxes),
    )


def _segment_crosses_vertical(a: Box, b: Box, separator: Separator, tolerance: float = 2.5) -> bool:
    if separator.orientation != "vertical":
        return False
    x = (separator.x1 + separator.x2) / 2.0
    if not (min(a.cx, b.cx) + tolerance < x < max(a.cx, b.cx) - tolerance):
        return False
    y = (a.cy + b.cy) / 2.0
    low = min(separator.y1, separator.y2) - 6.0
    high = max(separator.y1, separator.y2) + 6.0
    return low <= y <= high


def _segment_crosses_horizontal(a: Box, b: Box, separator: Separator, tolerance: float = 2.5) -> bool:
    if separator.orientation != "horizontal":
        return False
    y = (separator.y1 + separator.y2) / 2.0
    if not (min(a.cy, b.cy) + tolerance < y < max(a.cy, b.cy) - tolerance):
        return False
    x = (a.cx + b.cx) / 2.0
    low = min(separator.x1, separator.x2) - 6.0
    high = max(separator.x1, separator.x2) + 6.0
    return low <= x <= high


def separated(a: Box, b: Box, separators: Sequence[Separator]) -> bool:
    return any(
        _segment_crosses_vertical(a, b, sep)
        or _segment_crosses_horizontal(a, b, sep)
        for sep in separators
    )


def spans_from_layout(layout: Mapping[str, Any]) -> list[TextSpan]:
    rows = layout.get("spans")
    if not isinstance(rows, list):
        raise ValueError("layout spans are missing")
    result: list[TextSpan] = []
    for index, raw in enumerate(rows):
        if not isinstance(raw, Mapping):
            raise ValueError("span row must be an object")
        text = re.sub(r"\s+", " ", str(raw.get("text") or "")).strip()
        if not text:
            continue
        result.append(
            TextSpan(
                index=index,
                text=text,
                bbox=_box(raw["bbox"]),
                size=float(raw.get("size") or 0.0),
                font=str(raw.get("font") or ""),
                color=int(raw.get("color") or 0),
                flags=int(raw.get("flags") or 0),
            )
        )
    return result


def separators_from_layout(layout: Mapping[str, Any]) -> list[Separator]:
    page = layout.get("page") or {}
    width = float(page.get("width_points") or 0.0)
    height = float(page.get("height_points") or 0.0)
    if width <= 0 or height <= 0:
        raise ValueError("page dimensions are invalid")
    vectors = layout.get("vectors") or {}
    result: list[Separator] = []
    for orientation, key, min_fraction in (
        ("horizontal", "horizontal_lines", 0.11),
        ("vertical", "vertical_lines", 0.10),
    ):
        rows = vectors.get(key) or []
        for raw in rows:
            length = float(raw.get("length") or 0.0)
            minimum = width * min_fraction if orientation == "horizontal" else height * min_fraction
            if length < minimum:
                continue
            result.append(
                Separator(
                    orientation=orientation,
                    x1=float(raw["x1"]),
                    y1=float(raw["y1"]),
                    x2=float(raw["x2"]),
                    y2=float(raw["y2"]),
                    length=length,
                )
            )
    for raw in vectors.get("rectangles") or []:
        box = Box(float(raw["x0"]), float(raw["y0"]), float(raw["x1"]), float(raw["y1"]))
        if box.width >= width * 0.10 and box.height >= height * 0.06:
            result.extend(
                (
                    Separator("horizontal", box.x0, box.y0, box.x1, box.y0, box.width),
                    Separator("horizontal", box.x0, box.y1, box.x1, box.y1, box.width),
                    Separator("vertical", box.x0, box.y0, box.x0, box.y1, box.height),
                    Separator("vertical", box.x1, box.y0, box.x1, box.y1, box.height),
                )
            )
    return result


def _nearby_label_box(
    anchor_box: Box,
    excluded_span_indexes: Sequence[int],
    spans: Sequence[TextSpan],
    separators: Sequence[Separator],
    pattern: re.Pattern[str],
    radius: float,
) -> bool:
    excluded = set(excluded_span_indexes)
    for span in spans:
        if span.index in excluded or not pattern.search(span.text):
            continue
        if _distance(anchor_box, span.bbox) > radius:
            continue
        if separated(anchor_box, span.bbox, separators):
            continue
        return True
    return False


def _price_label_flags(
    bbox: Box,
    component_span_indexes: Sequence[int],
    component_text: str,
    spans: Sequence[TextSpan],
    separators: Sequence[Separator],
) -> tuple[bool, bool, bool]:
    member = bool(MEMBER_LABEL_RE.search(component_text)) or _nearby_label_box(
        bbox, component_span_indexes, spans, separators, MEMBER_LABEL_RE, 45.0
    )
    regular = bool(REGULAR_LABEL_RE.search(component_text)) or _nearby_label_box(
        bbox, component_span_indexes, spans, separators, REGULAR_LABEL_RE, 52.0
    )
    unit = bool(UNIT_LABEL_RE.search(component_text)) or _nearby_label_box(
        bbox, component_span_indexes, spans, separators, UNIT_LABEL_RE, 42.0
    )
    return member, regular, unit


def _split_price_pair_score(major: TextSpan, cents: TextSpan) -> float | None:
    if cents.bbox.cx <= major.bbox.cx:
        return None
    dx = cents.bbox.x0 - major.bbox.x1
    dy = cents.bbox.cy - major.bbox.cy
    if not (-18.0 <= dx <= 45.0 and -35.0 <= dy <= 24.0):
        return None
    if major.size <= 0:
        return None
    ratio = cents.size / major.size
    if not (0.30 <= ratio <= 1.02):
        return None
    return abs(dx + 2.0) + abs(dy + 7.0) * 0.8 + abs(ratio - 0.60) * 18.0


def price_anchors(
    spans: Sequence[TextSpan],
    separators: Sequence[Separator],
) -> list[PriceAnchor]:
    result: list[PriceAnchor] = []
    # Use ordinary non-price text as the typography baseline. If numeric spans
    # participate in the baseline, pages/tests dominated by large price glyphs
    # can raise the threshold high enough to hide the prices themselves.
    baseline_sizes = [
        span.size
        for span in spans
        if span.size > 0
        and not PRICE_RE.search(span.text)
        and not MAJOR_PRICE_RE.fullmatch(span.text)
        and not CENTS_PRICE_RE.fullmatch(span.text)
        and not re.search(r"\d", span.text)
    ]
    if not baseline_sizes:
        baseline_sizes = [
            span.size
            for span in spans
            if span.size > 0
            and not MAJOR_PRICE_RE.fullmatch(span.text)
            and not CENTS_PRICE_RE.fullmatch(span.text)
        ]
    page_font_median = median(baseline_sizes) if baseline_sizes else 8.0
    full_decimal_min_font = max(8.5, page_font_median * 1.10)
    major_min_font = max(14.0, page_font_median * 1.60)
    cents_min_font = max(10.0, page_font_median * 1.25)
    whole_euro_min_font = max(26.0, page_font_median * 3.00)

    for span in spans:
        for ordinal, match in enumerate(PRICE_RE.finditer(span.text), start=1):
            value = canonical_price(f"{match.group(1)}.{match.group(2)}")
            if value is None:
                continue
            direct_typed = bool(
                MEMBER_LABEL_RE.search(span.text)
                or REGULAR_LABEL_RE.search(span.text)
                or UNIT_LABEL_RE.search(span.text)
            )
            if span.size < full_decimal_min_font and not direct_typed:
                continue
            member, regular, unit = _price_label_flags(
                span.bbox, (span.index,), span.text, spans, separators
            )
            result.append(
                PriceAnchor(
                    anchor_id=f"p{span.index:04d}-{ordinal}",
                    span_index=span.index,
                    component_span_indexes=(span.index,),
                    source_kind="full_decimal_span",
                    value=value,
                    bbox=span.bbox,
                    font_size=span.size,
                    member_labeled=member,
                    regular_labeled=regular,
                    unit_labeled=unit,
                )
            )

    majors: list[tuple[TextSpan, re.Match[str]]] = []
    cents_rows: list[tuple[TextSpan, re.Match[str]]] = []
    for span in spans:
        major_match = MAJOR_PRICE_RE.fullmatch(span.text)
        if major_match and span.size >= major_min_font:
            majors.append((span, major_match))
        cents_match = CENTS_PRICE_RE.fullmatch(span.text)
        if cents_match and span.size >= cents_min_font:
            cents_rows.append((span, cents_match))

    pairs: list[tuple[float, int, int, TextSpan, re.Match[str], TextSpan, re.Match[str]]] = []
    for major, major_match in majors:
        for cents, cents_match in cents_rows:
            if major.index == cents.index or separated(major.bbox, cents.bbox, separators):
                continue
            score = _split_price_pair_score(major, cents)
            if score is None:
                continue
            pairs.append(
                (score, major.index, cents.index, major, major_match, cents, cents_match)
            )
    pairs.sort(key=lambda row: (row[0], row[1], row[2]))

    used_majors: set[int] = set()
    used_cents: set[int] = set()
    for _, _, _, major, major_match, cents, cents_match in pairs:
        if major.index in used_majors or cents.index in used_cents:
            continue
        value = canonical_price(f"{major_match.group(1)}.{cents_match.group(1)}")
        if value is None:
            continue
        bbox = _union([major.bbox, cents.bbox])
        component_indexes = (major.index, cents.index)
        member, regular, unit = _price_label_flags(
            bbox, component_indexes, f"{major.text} {cents.text}", spans, separators
        )
        result.append(
            PriceAnchor(
                anchor_id=f"s{major.index:04d}-{cents.index:04d}",
                span_index=major.index,
                component_span_indexes=component_indexes,
                source_kind="split_major_cents",
                value=value,
                bbox=bbox,
                font_size=max(major.size, cents.size),
                member_labeled=member,
                regular_labeled=regular,
                unit_labeled=unit,
            )
        )
        used_majors.add(major.index)
        used_cents.add(cents.index)

    for major, major_match in majors:
        if major.index in used_majors or major.size < whole_euro_min_font:
            continue
        value = canonical_price(f"{major_match.group(1)}.00")
        if value is None:
            continue
        member, regular, unit = _price_label_flags(
            major.bbox, (major.index,), major.text, spans, separators
        )
        result.append(
            PriceAnchor(
                anchor_id=f"w{major.index:04d}",
                span_index=major.index,
                component_span_indexes=(major.index,),
                source_kind="whole_euro_major",
                value=value,
                bbox=major.bbox,
                font_size=major.size,
                member_labeled=member,
                regular_labeled=regular,
                unit_labeled=unit,
            )
        )

    dedup: dict[tuple[str, tuple[int, ...], str], PriceAnchor] = {}
    for anchor in result:
        dedup.setdefault(
            (anchor.value, anchor.component_span_indexes, anchor.source_kind),
            anchor,
        )
    return sorted(
        dedup.values(),
        key=lambda row: (row.bbox.cy, row.bbox.cx, row.value, row.anchor_id),
    )


def _price_group_link(a: PriceAnchor, b: PriceAnchor, separators: Sequence[Separator]) -> bool:
    if separated(a.bbox, b.bbox, separators):
        return False
    dx = abs(a.bbox.cx - b.bbox.cx)
    dy = abs(a.bbox.cy - b.bbox.cy)
    if dx <= 48.0 and dy <= 58.0:
        return True
    x_overlap = min(a.bbox.x1, b.bbox.x1) - max(a.bbox.x0, b.bbox.x0)
    if x_overlap >= -16.0 and dy <= 68.0:
        return True
    return False


def build_price_groups(
    anchors: Sequence[PriceAnchor],
    separators: Sequence[Separator],
) -> list[PriceGroup]:
    parent = list(range(len(anchors)))

    def find(index: int) -> int:
        while parent[index] != index:
            parent[index] = parent[parent[index]]
            index = parent[index]
        return index

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for i, left in enumerate(anchors):
        for j in range(i + 1, len(anchors)):
            if _price_group_link(left, anchors[j], separators):
                union(i, j)

    buckets: dict[int, list[PriceAnchor]] = {}
    for index, anchor in enumerate(anchors):
        buckets.setdefault(find(index), []).append(anchor)

    groups: list[PriceGroup] = []
    for ordinal, rows in enumerate(
        sorted(
            buckets.values(),
            key=lambda values: (
                min(row.bbox.cy for row in values),
                min(row.bbox.cx for row in values),
            ),
        ),
        start=1,
    ):
        groups.append(
            PriceGroup(
                group_id=f"g{ordinal:03d}",
                anchor_ids=tuple(sorted(row.anchor_id for row in rows)),
                bbox=_union([row.bbox for row in rows]),
            )
        )
    return groups


def _is_title_noise(text: str) -> bool:
    normalized = normalize_text(text)
    if not normalized:
        return True
    if normalized in PROMO_EXACT:
        return True
    if any(normalized.startswith(prefix) for prefix in PROMO_PREFIXES):
        return True
    if PRICE_RE.search(text) or MEMBER_LABEL_RE.search(text):
        return True
    if REGULAR_LABEL_RE.search(text) or UNIT_LABEL_RE.search(text):
        return True
    if len(normalized) <= 2:
        return True
    return False


def _assignment_cost(span: TextSpan, group: PriceGroup) -> float:
    dx = abs(span.bbox.cx - group.bbox.cx)
    dy = abs(span.bbox.cy - group.bbox.cy)
    cost = dx * 0.75 + dy
    if span.bbox.cy > group.bbox.cy + 26.0:
        cost += 42.0
    if span.bbox.x1 < group.bbox.x0 - 95.0 or span.bbox.x0 > group.bbox.x1 + 95.0:
        cost += 60.0
    return cost


def assign_text(
    spans: Sequence[TextSpan],
    groups: Sequence[PriceGroup],
    separators: Sequence[Separator],
    anchors: Sequence[PriceAnchor],
) -> tuple[dict[int, str], set[int], dict[int, list[tuple[str, float]]]]:
    assignments: dict[int, str] = {}
    ambiguous: set[int] = set()
    scored: dict[int, list[tuple[str, float]]] = {}
    price_component_indexes = {
        index
        for anchor in anchors
        for index in anchor.component_span_indexes
    }
    for span in spans:
        if span.index in price_component_indexes or PRICE_RE.search(span.text):
            continue
        candidates: list[tuple[str, float]] = []
        for group in groups:
            if separated(span.bbox, group.bbox, separators):
                continue
            cost = _assignment_cost(span, group)
            if cost <= 220.0:
                candidates.append((group.group_id, round(cost, 4)))
        candidates.sort(key=lambda row: (row[1], row[0]))
        scored[span.index] = candidates[:3]
        if not candidates:
            continue
        if len(candidates) > 1 and candidates[1][1] - candidates[0][1] < 18.0:
            ambiguous.add(span.index)
            continue
        assignments[span.index] = candidates[0][0]
    return assignments, ambiguous, scored


def analyze_layout(layout: Mapping[str, Any]) -> dict[str, Any]:
    spans = spans_from_layout(layout)
    separators = separators_from_layout(layout)
    anchors = price_anchors(spans, separators)
    groups = build_price_groups(anchors, separators)
    assignments, ambiguous_spans, scored = assign_text(spans, groups, separators, anchors)
    by_anchor = {row.anchor_id: row for row in anchors}
    price_component_indexes = {
        index
        for anchor in anchors
        for index in anchor.component_span_indexes
    }
    body_sizes = [
        span.size
        for span in spans
        if span.size > 0
        and span.index not in price_component_indexes
        and not re.search(r"\d", span.text)
    ]
    page_font_median = median(body_sizes) if body_sizes else (
        median([span.size for span in spans if span.size > 0]) if spans else 0.0
    )

    group_rows: list[dict[str, Any]] = []
    for group in groups:
        group_anchors = [by_anchor[value] for value in group.anchor_ids]
        assigned_spans = [
            span for span in spans if assignments.get(span.index) == group.group_id
        ]
        title_candidates = [
            span
            for span in assigned_spans
            if not _is_title_noise(span.text)
            and span.size >= max(5.0, page_font_median * 0.72)
            and span.bbox.cy <= group.bbox.cy + 30.0
        ]
        title_candidates.sort(
            key=lambda span: (
                _assignment_cost(span, group),
                -span.size,
                span.bbox.y0,
                span.bbox.x0,
            )
        )
        normal = [
            row for row in group_anchors
            if not row.member_labeled and not row.regular_labeled and not row.unit_labeled
        ]
        member = [row for row in group_anchors if row.member_labeled]
        regular = [row for row in group_anchors if row.regular_labeled]
        unit = [row for row in group_anchors if row.unit_labeled and not row.member_labeled]
        nearby_ambiguous = [
            span.index
            for span in spans
            if span.index in ambiguous_spans
            and _assignment_cost(span, group) <= 180.0
        ]
        reasons: list[str] = []
        if len(normal) != 1:
            reasons.append("normal_price_ambiguous_or_missing")
        if not title_candidates:
            reasons.append("title_missing")
        if nearby_ambiguous:
            reasons.append("text_ownership_ambiguous")
        if any(
            separated(title.bbox, group.bbox, separators)
            for title in title_candidates[:3]
        ):
            reasons.append("separator_conflict")
        route = "automatic_candidate" if not reasons else "review_required"
        selected_title = None
        if title_candidates:
            chosen = title_candidates[:3]
            chosen.sort(key=lambda span: (span.bbox.y0, span.bbox.x0))
            selected_title = " ".join(span.text for span in chosen)
        group_rows.append(
            {
                "group_id": group.group_id,
                "bbox": asdict(group.bbox),
                "anchor_ids": list(group.anchor_ids),
                "normal_price_candidates": sorted({row.value for row in normal}),
                "member_price_candidates": sorted({row.value for row in member}),
                "regular_price_candidates": sorted({row.value for row in regular}),
                "unit_price_candidates": sorted({row.value for row in unit}),
                "selected_normal_price": normal[0].value if len(normal) == 1 else None,
                "selected_member_price": member[0].value if len(member) == 1 else None,
                "selected_title": selected_title,
                "title_span_indexes": [span.index for span in title_candidates[:8]],
                "ambiguous_span_indexes": nearby_ambiguous,
                "reasons": sorted(set(reasons)),
                "route": route,
                "shadow_only": True,
                "production_eligible": False,
                "promotion_ready": False,
            }
        )

    return {
        "schema_version": 1,
        "parser_identity": PARSER_IDENTITY,
        "page": dict(layout.get("page") or {}),
        "separator_count": len(separators),
        "price_anchor_count": len(anchors),
        "price_group_count": len(groups),
        "spans": [
            {
                "index": span.index,
                "text": span.text,
                "normalized": normalize_text(span.text),
                "bbox": asdict(span.bbox),
                "size": span.size,
                "assignment": assignments.get(span.index),
                "ambiguous": span.index in ambiguous_spans,
                "assignment_candidates": scored.get(span.index, []),
            }
            for span in spans
        ],
        "price_anchors": [
            {
                **asdict(anchor),
                "bbox": asdict(anchor.bbox),
            }
            for anchor in anchors
        ],
        "groups": group_rows,
        "shadow_only": True,
        "production_eligible": False,
        "promotion_ready": False,
    }


def extract_layout_from_pdf(pdf_path: Path, page_number: int) -> dict[str, Any]:
    try:
        import fitz
    except ImportError as exc:
        raise RuntimeError("PyMuPDF is required for PDF extraction") from exc

    document = fitz.open(pdf_path)
    try:
        if page_number < 1 or page_number > document.page_count:
            raise ValueError("page number outside PDF")
        page = document.load_page(page_number - 1)
        text = page.get_textpage().extractDICT()
        spans: list[dict[str, Any]] = []
        for block in text.get("blocks", []):
            if block.get("type") != 0:
                continue
            for line in block.get("lines", []):
                for span in line.get("spans", []):
                    value = re.sub(r"\s+", " ", str(span.get("text") or "")).strip()
                    if not value:
                        continue
                    spans.append(
                        {
                            "text": value,
                            "bbox": [round(float(v), 3) for v in span.get("bbox", (0, 0, 0, 0))],
                            "size": round(float(span.get("size") or 0.0), 3),
                            "font": str(span.get("font") or ""),
                            "color": int(span.get("color") or 0),
                            "flags": int(span.get("flags") or 0),
                        }
                    )

        horizontal: list[dict[str, float]] = []
        vertical: list[dict[str, float]] = []
        rectangles: list[dict[str, float]] = []
        for drawing in page.get_drawings():
            for item in drawing.get("items", []):
                kind = item[0]
                if kind == "l" and len(item) >= 3:
                    a, b = item[1], item[2]
                    x1, y1, x2, y2 = float(a.x), float(a.y), float(b.x), float(b.y)
                    length = math.hypot(x2 - x1, y2 - y1)
                    row = {
                        "x1": round(x1, 3), "y1": round(y1, 3),
                        "x2": round(x2, 3), "y2": round(y2, 3),
                        "length": round(length, 3),
                    }
                    if abs(y2 - y1) <= 1.5 and length >= 20.0:
                        horizontal.append(row)
                    elif abs(x2 - x1) <= 1.5 and length >= 20.0:
                        vertical.append(row)
                elif kind == "re" and len(item) >= 2:
                    rect = item[1]
                    rectangles.append(
                        {
                            "x0": round(float(rect.x0), 3),
                            "y0": round(float(rect.y0), 3),
                            "x1": round(float(rect.x1), 3),
                            "y1": round(float(rect.y1), 3),
                        }
                    )
        return {
            "schema_version": 1,
            "page": {
                "width_points": round(float(page.cropbox.width), 3),
                "height_points": round(float(page.cropbox.height), 3),
                "rotation": int(page.rotation),
                "page_number": page_number,
            },
            "spans": spans,
            "vectors": {
                "horizontal_lines": horizontal,
                "vertical_lines": vertical,
                "rectangles": rectangles,
            },
        }
    finally:
        document.close()
