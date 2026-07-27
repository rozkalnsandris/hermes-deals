from __future__ import annotations

import json
import re
import subprocess
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from statistics import mean, median
from typing import Any

import httpx

from app.lidl_page_schema_inspector import grocery_hits

_DECIMAL_PRICE_RE = re.compile(r"(?<!\d)(\d{1,3}[,.]\d{2})(?!\d)", re.IGNORECASE)
_SPLIT_CENTS_RE = re.compile(r"(?<!\d)(\d{1,3})\s+(\d{2})(?:\s*(?:€|EUR))?(?!\d)", re.IGNORECASE)
_WHOLE_EURO_RE = re.compile(r"(?<![\d,.])(\d{1,3})\s*(?:€|,-|\.\-)(?![\w\d])", re.IGNORECASE)
_UNIT_PRICE_RE = re.compile(
    r"(?:\b1\s*(?:kg|l|ltr\.?|liter)\b|\b100\s*(?:g|ml)\b|\bkg\s*=|\bl\s*=|\bgrundpreis\b)",
    re.IGNORECASE,
)
_REFERENCE_RE = re.compile(r"\b(?:normalpreis|uvp|statt|vorher|regulär)\b", re.IGNORECASE)
_SHIPPING_RE = re.compile(r"\b(?:versand(?:kosten(?:pauschale)?)?|porto)\b", re.IGNORECASE)
_INSTALLMENT_RE = re.compile(r"\b(?:ratenzahlung|pro\s+monat|monat|laufzeit|gesamtpreis)\b", re.IGNORECASE)
_DELIVERY_RE = re.compile(r"\b(?:lieferkosten|lieferung|zzgl\.?\s+liefer)\b", re.IGNORECASE)
_PACKAGE_SIZE_RE = re.compile(r"\b(?:je\s+)?\d{1,3}(?:[,.]\d{1,3})?\s*(?:kg|g|l|ml|cl)\b", re.IGNORECASE)
_PACKAGE_CAPTURE_RE = re.compile(r"\b(?:je\s+)?(\d{1,4}(?:[,.]\d{1,3})?)\s*(kg|g|l|ml|cl)\b", re.IGNORECASE)

_PACKAGE_AMOUNT_CAPTURE_RE = re.compile(
    r"(?<!\d)(\d{1,4}(?:[,.]\d{1,3})?)\s*(?:kg|g|l|ltr\.?|liter|ml|cl)\b",
    re.IGNORECASE,
)
_MULTIPACK_AMOUNT_CAPTURE_RE = re.compile(
    r"\b\d{1,3}\s*[x×]\s*(\d{1,4}(?:[,.]\d{1,3})?)\b",
    re.IGNORECASE,
)
_PACKAGING_PREFIX_AMOUNT_CAPTURE_RE = re.compile(
    r"\b(?:gebinde|standardpackung|packung)\s*:?\s*(\d{1,4}(?:[,.]\d{1,3})?)\b",
    re.IGNORECASE,
)
_DEPOSIT_AMOUNT_CAPTURE_RE = re.compile(
    r"(?:zzgl\.?|zuzüglich)?\s*(\d{1,4}(?:[,.]\d{1,2})?)\s*(?:€|eur)?\s*pfand\b",
    re.IGNORECASE,
)
_UNIT_KG_RE = re.compile(r"\b1\s*kg\b|\bkg\s*=", re.IGNORECASE)
_UNIT_L_RE = re.compile(r"\b1\s*(?:l|ltr\.?|liter)\b|\bl\s*=", re.IGNORECASE)
_EXPLICIT_CURRENCY_RE = re.compile(r"(?:€|\bEUR\b)", re.IGNORECASE)
_SALE_SIGNAL_RE = re.compile(r"\b(?:aktion|angebot|lidl\s+plus|nur|jetzt|preis)\b", re.IGNORECASE)
_BOILERPLATE_RE = re.compile(
    r"(?:versand|versandkosten|lieferkosten|ratenzahlung|pro\s+monat|laufzeit|gesamtpreis|"
    r"mwst|zzgl|bestellbar|lidl\.de|lidl\s+reisen|couponbedingungen|angebot\s+ausschließlich)",
    re.IGNORECASE,
)
_PAIRING_REJECT_RE = re.compile(
    r"(?:https?://|www\.|herkunft-|\b(?:inkl|zzgl|mwst|versand|lieferkosten|ratenzahlung)\b|"
    r"\bx\s*[bhl]\b|\b[blh]\s*\d+(?:[,.]\d+)?\s*(?:cm|mm|m)\b)",
    re.IGNORECASE,
)
_PAIRING_UNIT_ONLY_RE = re.compile(
    r"^\W*(?:je\s+)?\d+(?:[,.]\d+)?\s*(?:kg|g|ml|cl|l|cm|mm|m|stk|stück)\W*$",
    re.IGNORECASE,
)
_PAIRING_GENERIC_TERMS = {
    "gemuse", "obst", "frische", "angebot", "aktion", "preis", "stuck", "sorten",
    "lidl", "plus", "normalpreis", "uvp", "klasse", "ursprung", "gekühlt", "gekuhlt",
}
_PAIRING_STOPWORDS = {
    "der", "die", "das", "den", "dem", "des", "ein", "eine", "einer", "eines", "und", "oder",
    "mit", "ohne", "fur", "für", "von", "vom", "je", "pro", "ca", "versch", "verschiedene", "sorten",
}

_OCR_PSM_MODES = (11, 12)
_BASELINE_PSM = 11


@dataclass(frozen=True)
class OcrWord:
    level: int
    page_num: int
    block_num: int
    par_num: int
    line_num: int
    word_num: int
    left: int
    top: int
    width: int
    height: int
    confidence: float
    text: str

    @property
    def right(self) -> int:
        return self.left + self.width

    @property
    def bottom(self) -> int:
        return self.top + self.height

    @property
    def center_x(self) -> float:
        return self.left + self.width / 2

    @property
    def center_y(self) -> float:
        return self.top + self.height / 2


def _price_value(token: str) -> float | None:
    value = token.strip().replace("€", "").replace("EUR", "").replace(" ", "")
    value = value.replace(".", ",")
    if value.endswith(",-"):
        value = value[:-2]
    try:
        return float(value.replace(",", "."))
    except ValueError:
        return None


def _valid_price_token(token: str) -> bool:
    value = _price_value(token)
    return value is not None and value > 0


def price_candidates(text: str) -> list[str]:
    """Extract conservative textual price tokens.

    Bare integers followed by a hyphen are deliberately *not* treated as prices,
    because flyer OCR frequently contains strings such as ``9-teilig``.
    """
    normalized = " ".join(text.replace("\u00a0", " ").split())
    found: list[str] = []
    seen: set[str] = set()

    for match in _DECIMAL_PRICE_RE.finditer(normalized):
        token = match.group(1).replace(".", ",")
        if _valid_price_token(token) and token not in seen:
            seen.add(token)
            found.append(token)

    for match in _SPLIT_CENTS_RE.finditer(normalized):
        token = f"{match.group(1)},{match.group(2)}"
        if _valid_price_token(token) and token not in seen:
            seen.add(token)
            found.append(token)

    for match in _WHOLE_EURO_RE.finditer(normalized):
        token = match.group(1)
        if _valid_price_token(token) and token not in seen:
            seen.add(token)
            found.append(token)

    return found


def _parse_tsv_rows(tsv_text: str, *, min_confidence: float) -> tuple[list[OcrWord], int]:
    """Parse Tesseract TSV without CSV quote semantics.

    Tesseract's TSV is tab-separated but OCR text is not RFC CSV-quoted. Using
    ``csv.DictReader`` with its default quote handling can swallow many physical
    TSV rows when OCR sees a literal double quote. That was visible in Phase 2B6
    as a page with only 24 words but >22k text characters and hundreds of bogus
    prices derived from TSV coordinates/confidence values.
    """
    lines = tsv_text.splitlines()
    if not lines:
        return [], 0

    expected = [
        "level",
        "page_num",
        "block_num",
        "par_num",
        "line_num",
        "word_num",
        "left",
        "top",
        "width",
        "height",
        "conf",
        "text",
    ]
    header = lines[0].split("\t")
    if header[:12] != expected:
        raise ValueError(f"Unexpected Tesseract TSV header: {header[:12]}")

    words: list[OcrWord] = []
    malformed = 0
    for raw in lines[1:]:
        if not raw.strip():
            continue
        parts = raw.split("\t", 11)
        if len(parts) != 12:
            malformed += 1
            continue
        text = parts[11].strip()
        if not text:
            continue
        try:
            conf = float(parts[10])
            if conf < min_confidence:
                continue
            words.append(
                OcrWord(
                    level=int(parts[0]),
                    page_num=int(parts[1]),
                    block_num=int(parts[2]),
                    par_num=int(parts[3]),
                    line_num=int(parts[4]),
                    word_num=int(parts[5]),
                    left=int(parts[6]),
                    top=int(parts[7]),
                    width=int(parts[8]),
                    height=int(parts[9]),
                    confidence=conf,
                    text=text,
                )
            )
        except (TypeError, ValueError):
            malformed += 1
    return words, malformed


def _classify_price_context(text: str) -> str:
    if _SHIPPING_RE.search(text) or _DELIVERY_RE.search(text):
        return "shipping"
    if _INSTALLMENT_RE.search(text):
        return "installment"
    if _UNIT_PRICE_RE.search(text):
        return "unit_price"
    if _REFERENCE_RE.search(text):
        return "reference_price"
    return "sale_candidate"


def _zone_context(zone: dict[str, Any]) -> str:
    parts = [str(zone.get("line_text") or "")]
    parts.extend(str(item) for item in zone.get("nearby_text") or [])
    return " ".join(parts)


def _numeric_token_matches(token: str, captured: str) -> bool:
    token_value = _price_value(token)
    captured_value = _price_value(captured)
    if token_value is None or captured_value is None:
        return False
    return abs(token_value - captured_value) <= 0.0001


def _token_matches_capture_patterns(
    token: str,
    line: str,
    patterns: tuple[re.Pattern[str], ...],
) -> bool:
    for pattern in patterns:
        for match in pattern.finditer(line):
            if _numeric_token_matches(token, match.group(1)):
                return True
    return False


def _token_is_package_amount(line: str, token: str) -> bool:
    return _token_matches_capture_patterns(
        token,
        line,
        (
            _PACKAGE_AMOUNT_CAPTURE_RE,
            _MULTIPACK_AMOUNT_CAPTURE_RE,
            _PACKAGING_PREFIX_AMOUNT_CAPTURE_RE,
        ),
    )


def _token_is_deposit_amount(line: str, token: str) -> bool:
    return _token_matches_capture_patterns(
        token,
        line,
        (_DEPOSIT_AMOUNT_CAPTURE_RE,),
    )


def _refine_zone_classification(zone: dict[str, Any]) -> str:
    context = _zone_context(zone)
    classified = _classify_price_context(context)
    if classified != "sale_candidate":
        return classified

    # Refine the exact numeric token. This avoids throwing away a real sale
    # price merely because the same OCR line also contains package/deposit data.
    line = str(zone.get("line_text") or "")
    token = str(zone.get("token") or "")
    if _token_is_deposit_amount(line, token):
        return "deposit"
    if _token_is_package_amount(line, token) and not _EXPLICIT_CURRENCY_RE.search(line):
        return "package_amount"
    return "sale_candidate"


def _bbox_from_words(words: list[OcrWord]) -> dict[str, int]:
    return {
        "left": min(w.left for w in words),
        "top": min(w.top for w in words),
        "right": max(w.right for w in words),
        "bottom": max(w.bottom for w in words),
    }


def _nearest_text(lines: list[dict[str, Any]], target: dict[str, int], *, limit: int = 3) -> list[str]:
    tx = (target["left"] + target["right"]) / 2
    ty = (target["top"] + target["bottom"]) / 2
    ranked: list[tuple[float, str]] = []
    for line in lines:
        text = str(line.get("text") or "").strip()
        if not text or line.get("price_candidates"):
            continue
        bbox = line["bbox"]
        lx = (bbox["left"] + bbox["right"]) / 2
        ly = (bbox["top"] + bbox["bottom"]) / 2
        # Vertical proximity matters more than horizontal distance on flyer cards.
        distance = abs(ty - ly) * 1.6 + abs(tx - lx) * 0.35
        ranked.append((distance, text))
    ranked.sort(key=lambda item: item[0])
    return [text for _, text in ranked[:limit]]



def _horizontal_overlap(a: dict[str, int], b: dict[str, int]) -> float:
    overlap = max(0, min(a["right"], b["right"]) - max(a["left"], b["left"]))
    width = max(1, min(a["right"] - a["left"], b["right"] - b["left"]))
    return overlap / width


def _product_label_candidates(lines: list[dict[str, Any]], target: dict[str, int], *, limit: int = 3) -> list[dict[str, Any]]:
    """Rank nearby OCR text that could be the label for a price zone.

    This is an audit primitive, not a persistence decision. Product labels are
    normally above or close beside the large price. Boilerplate, price lines
    and tiny/noisy strings are excluded before geometric ranking.
    """
    tx = (target["left"] + target["right"]) / 2
    ty = (target["top"] + target["bottom"]) / 2
    ranked: list[tuple[float, dict[str, Any]]] = []
    for line in lines:
        text = str(line.get("text") or "").strip()
        if not text or line.get("price_candidates") or len(text) < 3 or len(text) > 140:
            continue
        if _BOILERPLATE_RE.search(text) or not re.search(r"[A-Za-zÄÖÜäöüß]", text):
            continue
        bbox = line["bbox"]
        lx = (bbox["left"] + bbox["right"]) / 2
        ly = (bbox["top"] + bbox["bottom"]) / 2
        # Prefer labels above the price; allow a small amount below because OCR
        # line boxes can be noisy on dense flyer cards.
        dy = ty - ly
        if dy < -140 or dy > 700:
            continue
        overlap = _horizontal_overlap(target, bbox)
        xdist = abs(tx - lx)
        if overlap <= 0 and xdist > 500:
            continue
        score = 5.0
        score -= min(abs(dy), 700) / 180.0
        score -= min(xdist, 700) / 500.0
        score += overlap * 2.0
        hits = grocery_hits(text)
        if hits:
            score += 0.8
        item = {
            "text": text,
            "bbox": bbox,
            "score": round(score, 2),
            "grocery_hits": hits,
            "vertical_delta": round(dy, 1),
            "horizontal_overlap": round(overlap, 3),
        }
        ranked.append((score, item))
    ranked.sort(key=lambda item: item[0], reverse=True)
    return [item for score, item in ranked[:limit] if score >= 1.0]

def _split_price_zones(words: list[OcrWord], median_height: float) -> list[dict[str, Any]]:
    """Find large euro + smaller cent pairs from OCR word geometry.

    Lidl often renders the main price as separate large euro digits and smaller
    superscript cents, so line-level text regexes miss the actual offer price.
    This is intentionally conservative and only emits geometry candidates.
    """
    euros = [w for w in words if re.fullmatch(r"\d{1,3}", w.text) and w.height >= median_height * 1.20]
    cents = [w for w in words if re.fullmatch(r"\d{2}", w.text) and w.height >= median_height * 0.45]
    zones: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()

    for euro in euros:
        best: tuple[float, OcrWord] | None = None
        for cent in cents:
            if cent is euro:
                continue
            # Cents should be at or just to the right of the euro digits and
            # typically no lower than the euro baseline.
            horizontal_gap = cent.left - euro.right
            if horizontal_gap < -0.25 * euro.width or horizontal_gap > 1.8 * euro.height:
                continue
            if abs(cent.center_y - euro.center_y) > 1.1 * euro.height:
                continue
            if cent.height > euro.height * 1.25:
                continue
            score = abs(horizontal_gap) + abs(cent.center_y - euro.center_y) * 0.8
            if best is None or score < best[0]:
                best = (score, cent)
        if best is None:
            continue
        cent = best[1]
        token = f"{euro.text},{cent.text}"
        if not _valid_price_token(token):
            continue
        key = (token, euro.left, euro.top)
        if key in seen:
            continue
        seen.add(key)
        bbox = _bbox_from_words([euro, cent])
        zones.append(
            {
                "token": token,
                "source": "split_geometry",
                "classification": "sale_candidate",
                "bbox": bbox,
                "height_ratio": round(euro.height / median_height, 2) if median_height else None,
                "mean_confidence": round((euro.confidence + cent.confidence) / 2, 2),
            }
        )
    return zones


def parse_tsv(tsv_text: str, *, min_confidence: float = 15.0) -> dict[str, Any]:
    words, malformed_rows = _parse_tsv_rows(tsv_text, min_confidence=min_confidence)

    lines_map: dict[tuple[int, int, int, int], list[OcrWord]] = {}
    for word in words:
        key = (word.page_num, word.block_num, word.par_num, word.line_num)
        lines_map.setdefault(key, []).append(word)

    lines: list[dict[str, Any]] = []
    textual_prices: list[str] = []
    seen_prices: set[str] = set()
    for key, line_words in lines_map.items():
        line_words.sort(key=lambda w: (w.left, w.top))
        text = " ".join(w.text for w in line_words)
        prices = price_candidates(text)
        for token in prices:
            if token not in seen_prices:
                seen_prices.add(token)
                textual_prices.append(token)
        lines.append(
            {
                "key": list(key),
                "text": text,
                "price_candidates": prices,
                "price_classification": _classify_price_context(text) if prices else None,
                "mean_confidence": round(mean(w.confidence for w in line_words), 2),
                "bbox": _bbox_from_words(line_words),
            }
        )
    lines.sort(key=lambda item: (item["bbox"]["top"], item["bbox"]["left"]))

    word_heights = [w.height for w in words if w.height > 0]
    median_height = float(median(word_heights)) if word_heights else 0.0

    zones: list[dict[str, Any]] = []
    for line in lines:
        if not line["price_candidates"]:
            continue
        bbox = line["bbox"]
        line_height = max(1, bbox["bottom"] - bbox["top"])
        for token in line["price_candidates"]:
            zone = {
                "token": token,
                "source": "line_text",
                "classification": line["price_classification"],
                "bbox": bbox,
                "height_ratio": round(line_height / median_height, 2) if median_height else None,
                "mean_confidence": line["mean_confidence"],
                "line_text": line["text"],
            }
            zones.append(zone)

    zones.extend(_split_price_zones(words, median_height))

    # Deduplicate same token at nearly the same location; prefer geometry split
    # over generic line text because it carries stronger visual evidence.
    deduped: list[dict[str, Any]] = []
    for zone in sorted(zones, key=lambda z: 0 if z["source"] == "split_geometry" else 1):
        bbox = zone["bbox"]
        duplicate = False
        for existing in deduped:
            eb = existing["bbox"]
            if zone["token"] == existing["token"] and abs(bbox["left"] - eb["left"]) < 40 and abs(bbox["top"] - eb["top"]) < 40:
                duplicate = True
                break
        if not duplicate:
            deduped.append(zone)

    for zone in deduped:
        zone["nearby_text"] = _nearest_text(lines, zone["bbox"])
        zone["classification"] = _refine_zone_classification(zone)
        zone["pairing_candidates"] = _product_label_candidates(lines, zone["bbox"])
        zone["best_pairing"] = zone["pairing_candidates"][0] if zone["pairing_candidates"] else None

        score = 0.0
        if zone["classification"] == "sale_candidate":
            score += 2.0
        if zone["source"] == "split_geometry":
            score += 2.0
        height_ratio = float(zone.get("height_ratio") or 0)
        if height_ratio >= 1.8:
            score += 2.0
        elif height_ratio >= 1.3:
            score += 1.0
        confidence = float(zone.get("mean_confidence") or 0)
        if confidence >= 75:
            score += 1.0
        elif confidence < 40:
            score -= 1.0
        if zone.get("best_pairing"):
            score += 0.5
        zone["score"] = round(score, 2)

    def is_credible(zone: dict[str, Any]) -> bool:
        if zone["classification"] != "sale_candidate" or not _valid_price_token(str(zone.get("token") or "")):
            return False
        score = float(zone.get("score") or 0)
        height_ratio = float(zone.get("height_ratio") or 0)
        if zone.get("source") == "split_geometry":
            return score >= 4.0 and height_ratio >= 1.2
        line = str(zone.get("line_text") or "")
        # Plain line text is noisy. Require visual emphasis, or explicit currency
        # plus at least modest emphasis. This removes package amounts and small
        # footer/shipping numbers that Phase 2B7 still admitted.
        emphasized = height_ratio >= 1.3
        explicit_currency = bool(_EXPLICIT_CURRENCY_RE.search(line))
        return score >= 3.5 and (emphasized or (explicit_currency and height_ratio >= 1.1))

    credible_zones = [z for z in deduped if is_credible(z)]
    credible_zones.sort(key=lambda z: (-float(z.get("score") or 0), z["bbox"]["top"], z["bbox"]["left"]))

    plain_text = "\n".join(item["text"] for item in lines)
    return {
        "word_count": len(words),
        "line_count": len(lines),
        "malformed_tsv_rows": malformed_rows,
        "median_word_height": round(median_height, 2) if median_height else None,
        "mean_confidence": round(mean(w.confidence for w in words), 2) if words else None,
        "text_chars": len(plain_text),
        "price_candidates": textual_prices,
        "price_zones": deduped,
        "credible_price_zones": credible_zones,
        "lines": lines,
        "plain_text": plain_text,
    }



def _bbox_center_distance(a: dict[str, int], b: dict[str, int]) -> float:
    ax = (a["left"] + a["right"]) / 2
    ay = (a["top"] + a["bottom"]) / 2
    bx = (b["left"] + b["right"]) / 2
    by = (b["top"] + b["bottom"]) / 2
    return ((ax - bx) ** 2 + (ay - by) ** 2) ** 0.5


def merge_credible_price_zones(psm_parsed: dict[int, dict[str, Any]]) -> list[dict[str, Any]]:
    """Merge conservative price zones found by several Tesseract page modes.

    The same visual price is frequently segmented slightly differently by PSM 11
    and 12. We only deduplicate when both the normalized price token and the
    geometry agree. Conflicting OCR tokens remain separate audit candidates.
    """
    candidates: list[dict[str, Any]] = []
    for psm, parsed in psm_parsed.items():
        for zone in parsed.get("credible_price_zones") or []:
            item = dict(zone)
            item["psm_modes"] = [int(psm)]
            candidates.append(item)

    merged: list[dict[str, Any]] = []
    for zone in sorted(candidates, key=lambda z: (-float(z.get("score") or 0), z["bbox"]["top"], z["bbox"]["left"])):
        match = None
        for existing in merged:
            if str(existing.get("token")) != str(zone.get("token")):
                continue
            if _bbox_center_distance(existing["bbox"], zone["bbox"]) <= 110:
                match = existing
                break
        if match is None:
            merged.append(zone)
            continue
        match["psm_modes"] = sorted(set(match.get("psm_modes") or []) | set(zone.get("psm_modes") or []))
        # Keep the strongest geometry/text interpretation, but retain all PSMs
        # that independently saw the same price.
        if float(zone.get("score") or 0) > float(match.get("score") or 0):
            modes = match["psm_modes"]
            match.clear()
            match.update(zone)
            match["psm_modes"] = modes

    for zone in merged:
        support = len(zone.get("psm_modes") or [])
        zone["psm_support"] = support
        zone["ensemble_score"] = round(float(zone.get("score") or 0) + min(1.5, 0.5 * max(0, support - 1)), 2)
    merged.sort(key=lambda z: (-float(z.get("ensemble_score") or 0), z["bbox"]["top"], z["bbox"]["left"]))
    return merged


def _normalize_pairing_token(token: str) -> str:
    value = token.lower().replace("ä", "a").replace("ö", "o").replace("ü", "u").replace("ß", "ss")
    value = re.sub(r"[^a-z0-9]+", "", value)
    return value


def _pairing_terms(text: str) -> list[str]:
    raw = re.findall(r"[A-Za-zÄÖÜäöüß]{2,}", text or "")
    terms: list[str] = []
    for token in raw:
        normalized = _normalize_pairing_token(token)
        if len(normalized) < 3 or normalized in {_normalize_pairing_token(x) for x in _PAIRING_STOPWORDS}:
            continue
        terms.append(normalized)
    return terms


def _pairing_context_tokens(page: dict[str, Any]) -> set[str]:
    text = " ".join(
        str(page.get(key) or "")
        for key in ("keywords_text", "keywords_preview", "alt_text", "alt_preview")
    )
    return set(_pairing_terms(text))


def _evaluate_pairing_candidate(candidate: dict[str, Any], page: dict[str, Any]) -> dict[str, Any]:
    text = str(candidate.get("text") or "").strip()
    result = dict(candidate)
    result["accepted"] = False
    result["semantic_score"] = 0.0
    result["semantic_reasons"] = []

    if not text:
        result["semantic_reasons"].append("empty")
        return result
    if _PAIRING_REJECT_RE.search(text):
        result["semantic_reasons"].append("boilerplate_or_dimension")
        return result
    if _PAIRING_UNIT_ONLY_RE.match(text):
        result["semantic_reasons"].append("package_or_unit_only")
        return result

    terms = _pairing_terms(text)
    if not terms:
        result["semantic_reasons"].append("no_product_terms")
        return result
    if all(term in _PAIRING_GENERIC_TERMS for term in terms):
        result["semantic_reasons"].append("generic_only")
        return result

    context = _pairing_context_tokens(page)
    overlap = sorted(set(terms) & context)
    grocery = grocery_hits(text)
    score = float(candidate.get("score") or 0)
    score += min(4.5, len(overlap) * 1.5)
    if overlap:
        score += 1.0
    if grocery:
        score += 1.0
    if len(terms) >= 2:
        score += 0.5
    if len(text) >= 8:
        score += 0.25

    result["normalized_terms"] = terms
    result["keyword_overlap"] = overlap
    result["semantic_score"] = round(score, 2)
    if overlap:
        result["semantic_reasons"].append("keyword_overlap")
    if grocery:
        result["semantic_reasons"].append("grocery_term")

    # We deliberately require evidence from the retailer metadata or a genuine
    # grocery term; pure geometric proximity alone produced labels such as
    # ``www.herkunft-`` and dimension strings in Phase 2B8/2B9.
    result["accepted"] = bool(score >= 5.5 and (overlap or grocery))
    if not result["accepted"]:
        result["semantic_reasons"].append("insufficient_semantic_evidence")
    return result


def attach_semantic_pairings(zones: list[dict[str, Any]], page: dict[str, Any]) -> list[dict[str, Any]]:
    page_has_grocery = bool(page.get("keywords_grocery_hits") or page.get("alt_grocery_hits"))
    for zone in zones:
        evaluated = [_evaluate_pairing_candidate(item, page) for item in (zone.get("pairing_candidates") or [])]
        evaluated.sort(key=lambda item: float(item.get("semantic_score") or 0), reverse=True)
        zone["semantic_pairing_candidates"] = evaluated
        accepted = [item for item in evaluated if item.get("accepted")]
        zone["best_semantic_pairing"] = accepted[0] if accepted else None

        support = int(zone.get("psm_support") or 0)
        ensemble_score = float(zone.get("ensemble_score") or 0)
        source = str(zone.get("source") or "")
        semantic_score = float((zone.get("best_semantic_pairing") or {}).get("semantic_score") or 0)
        strong_price = support >= 2 or (source == "split_geometry" and ensemble_score >= 7.0)
        strong_pair = semantic_score >= 5.5
        zone["automatic_candidate"] = bool(page_has_grocery and strong_price and strong_pair)
        if not page_has_grocery:
            zone["automatic_reason"] = "non_grocery_page"
        elif not strong_price:
            zone["automatic_reason"] = "price_support_too_weak"
        elif not strong_pair:
            zone["automatic_reason"] = "pairing_not_semantic"
        else:
            zone["automatic_reason"] = "price_and_pairing_supported"
    return zones



def _package_base_quantity(text: str, unit_kind: str) -> tuple[float, str] | None:
    """Return package quantity converted to kg or litre for unit-price math.

    Package text may be on the same OCR line as the unit price (for example
    ``Je 190 g; 1kg = 5.21``). The canonical unit basis itself (``1kg =`` or
    ``1 l =``) is explicitly ignored so it can never masquerade as the package.
    """
    source = text or ""
    for match in _PACKAGE_CAPTURE_RE.finditer(source):
        raw_value = match.group(1).replace(",", ".")
        raw_unit = match.group(2).lower()
        suffix = source[match.end():match.end() + 8]
        # Do not treat the unit-price basis itself as the product package.
        if raw_value in {"1", "1.0", "1.00"} and raw_unit in {"kg", "l"} and re.match(r"\s*=", suffix):
            continue
        try:
            value = float(raw_value)
        except ValueError:
            continue
        if value <= 0:
            continue
        if unit_kind == "kg":
            if raw_unit == "kg":
                base = value
            elif raw_unit == "g":
                base = value / 1000.0
            else:
                continue
        elif unit_kind == "l":
            if raw_unit in {"l"}:
                base = value
            elif raw_unit == "ml":
                base = value / 1000.0
            elif raw_unit == "cl":
                base = value / 100.0
            else:
                continue
        else:
            continue
        if 0 < base <= 20:
            return base, match.group(0)
    return None


def _unit_package_context(unit_zone: dict[str, Any]) -> str:
    """Combine same-line and nearby text for package-size extraction.

    Same-line package sizes were intentionally ignored in Phase 2B11, which
    missed valid structures such as ``Je 190 g; 1kg = 5.21``.
    """
    parts = [str(unit_zone.get("line_text") or "")]
    parts.extend(str(x) for x in unit_zone.get("nearby_text") or [])
    return " ".join(parts)


def _looks_like_single_digit_price_ocr_error(actual: float, expected: float) -> bool:
    """Conservative detector for conflicts like OCR 0.59 vs arithmetic 0.69.

    This only creates an audit correction proposal; it never mutates or persists
    a sale price. We require the same whole-euro part and exactly one differing
    digit in the two-decimal representation.
    """
    if actual <= 0 or expected <= 0 or abs(actual - expected) > 0.20:
        return False
    a = f"{actual:.2f}"
    e = f"{expected:.2f}"
    if a.split(".", 1)[0] != e.split(".", 1)[0]:
        return False
    return sum(x != y for x, y in zip(a, e)) == 1

def _unit_price_kind(line_text: str) -> str | None:
    if _UNIT_KG_RE.search(line_text or ""):
        return "kg"
    if _UNIT_L_RE.search(line_text or ""):
        return "l"
    return None


def _context_overlap(label_text: str, unit_zone: dict[str, Any]) -> list[str]:
    label_terms = set(_pairing_terms(label_text))
    unit_context = " ".join([str(unit_zone.get("line_text") or "")] + [str(x) for x in unit_zone.get("nearby_text") or []])
    return sorted(label_terms & set(_pairing_terms(unit_context)))


def attach_unit_price_consistency(
    zones: list[dict[str, Any]],
    psm_parsed: dict[int, dict[str, Any]],
) -> list[dict[str, Any]]:
    """Cross-check sale prices against nearby package size × unit-price math.

    This does not create or persist offers. It adds independent deterministic
    evidence to already-semantic OCR candidates.
    """
    unit_zones: list[dict[str, Any]] = []
    seen: set[tuple[str, int, int]] = set()
    for parsed in psm_parsed.values():
        for raw in parsed.get("price_zones") or []:
            if raw.get("classification") != "unit_price":
                continue
            key = (str(raw.get("token")), int(raw.get("bbox", {}).get("left", 0) // 40), int(raw.get("bbox", {}).get("top", 0) // 40))
            if key in seen:
                continue
            seen.add(key)
            unit_zones.append(raw)

    for zone in zones:
        zone["unit_price_crosschecks"] = []
        zone["unit_price_math_verified"] = False
        zone["unit_price_math_conflict"] = False
        zone["unit_price_math_correction_candidate"] = False
        zone["unit_price_math_correction_expected_price"] = None
        zone["unit_price_math_correction_reason"] = None
        zone["unit_price_math_correction_distance"] = None
        zone["unit_price_math_correction_dual_psm"] = False
        best_label = str((zone.get("best_semantic_pairing") or {}).get("text") or "")
        sale_value = _price_value(str(zone.get("token") or ""))
        if not zone.get("automatic_candidate") or sale_value is None:
            continue

        ranked: list[tuple[float, dict[str, Any]]] = []
        for unit_zone in unit_zones:
            unit_value = _price_value(str(unit_zone.get("token") or ""))
            unit_kind = _unit_price_kind(str(unit_zone.get("line_text") or ""))
            if unit_value is None or unit_kind is None:
                continue
            package_context = _unit_package_context(unit_zone)
            package = _package_base_quantity(package_context, unit_kind)
            if package is None:
                continue
            quantity, package_text = package
            distance = _bbox_center_distance(zone["bbox"], unit_zone["bbox"])
            overlap = _context_overlap(best_label, unit_zone)
            # Same-card unit prices are normally close. Semantic overlap allows
            # a slightly wider geometry window on dense multi-column pages.
            max_distance = 850 if overlap else 500
            if distance > max_distance:
                continue
            expected = round(unit_value * quantity, 4)
            delta = round(abs(expected - sale_value), 4)
            tolerance = max(0.03, sale_value * 0.015)
            verified = delta <= tolerance
            item = {
                "unit_price": unit_value,
                "unit_kind": unit_kind,
                "package_quantity_base": round(quantity, 4),
                "package_text": package_text,
                "expected_sale_price": round(expected, 2),
                "actual_sale_price": round(sale_value, 2),
                "delta": delta,
                "tolerance": round(tolerance, 4),
                "verified": verified,
                "distance": round(distance, 1),
                "label_overlap": overlap,
                "unit_line": str(unit_zone.get("line_text") or ""),
                "unit_nearby": list(unit_zone.get("nearby_text") or []),
            }
            rank_score = (4.0 if verified else 0.0) + len(overlap) * 2.0 - distance / 500.0
            ranked.append((rank_score, item))

        ranked.sort(key=lambda x: x[0], reverse=True)
        checks = [item for _, item in ranked[:4]]
        zone["unit_price_crosschecks"] = checks
        verified_checks = [item for item in checks if item.get("verified")]
        zone["unit_price_math_verified"] = bool(verified_checks)
        # A conflict is meaningful only when a very close/semantic unit-price
        # relation exists but its arithmetic disagrees with the OCR sale price.
        strong_nonmatch = []
        for item in checks:
            raw_distance = item.get("distance")
            distance_value = float("inf") if raw_distance is None else float(raw_distance)
            if not item.get("verified") and (item.get("label_overlap") or distance_value <= 260):
                strong_nonmatch.append(item)
        zone["unit_price_math_conflict"] = bool(strong_nonmatch and not verified_checks)
        if zone["unit_price_math_conflict"]:
            best_conflict = strong_nonmatch[0]
            expected = float(best_conflict.get("expected_sale_price") or 0)
            actual = float(best_conflict.get("actual_sale_price") or 0)
            raw_distance = best_conflict.get("distance")
            distance = float("inf") if raw_distance is None else float(raw_distance)
            close = distance <= 260
            semantic = bool(best_conflict.get("label_overlap"))
            dual_psm = int(zone.get("psm_support") or 0) >= 2
            # Lidl cards can place package/unit-price text farther away from the
            # large sale-price glyph.  Phase 2B12 required <=260 px even when
            # both PSM 11/12 agreed on the sale price and the unit-price context
            # shared a product term.  That was too strict for real dense cards
            # such as Penne Rigate.  Keep the audit conservative: a wider
            # geometry window is accepted only with dual-PSM price consensus +
            # semantic overlap + a one-digit arithmetic discrepancy.
            correction_geometry_ok = close or (dual_psm and semantic and distance <= 650)
            if correction_geometry_ok and semantic and _looks_like_single_digit_price_ocr_error(actual, expected):
                zone["unit_price_math_correction_candidate"] = True
                zone["unit_price_math_correction_expected_price"] = round(expected, 2)
                zone["unit_price_math_correction_reason"] = "single_digit_ocr_error_supported_by_unit_math"
                zone["unit_price_math_correction_distance"] = round(distance, 1)
                zone["unit_price_math_correction_dual_psm"] = dual_psm
    return zones

def select_grocery_pages(page_report: dict[str, Any]) -> list[dict[str, Any]]:
    """Select every flyer page that has retailer-metadata grocery evidence.

    This is deliberately based on Lidl page metadata rather than OCR output, so
    the full-grocery dry run does not cherry-pick pages that already produced a
    price. The function remains read-only and only returns pages with an image.
    """
    pages = [
        p for p in page_report.get("pages", [])
        if isinstance(p, dict)
        and (p.get("zoom") or p.get("image"))
        and (p.get("keywords_grocery_hits") or p.get("alt_grocery_hits"))
    ]
    pages.sort(key=lambda p: int(p.get("number") or 0))
    seen: set[int] = set()
    out: list[dict[str, Any]] = []
    for page in pages:
        number = int(page.get("number") or 0)
        if number <= 0 or number in seen:
            continue
        seen.add(number)
        out.append(page)
    return out



def _normalized_ocr_line(value: str) -> str:
    return " ".join(str(value or "").casefold().split())


def _resolved_ocr_artifact_path(value: str) -> Path:
    path = Path(str(value or ""))
    if path.exists():
        return path

    raw = str(path)
    marker = "/data/"
    if marker in raw:
        fallback = Path("/data") / raw.split(marker, 1)[1]
        if fallback.exists():
            return fallback

    return path


def _tsv_exact_line_support_modes(
    psm_results: dict[str, Any],
    candidate_name: str,
) -> list[int]:
    wanted = _normalized_ocr_line(candidate_name)
    if not wanted:
        return []

    support: list[int] = []

    for raw_mode, meta in (psm_results or {}).items():
        if not isinstance(meta, dict):
            continue

        raw_path = str(meta.get("tsv_path") or "")
        if not raw_path:
            continue

        path = _resolved_ocr_artifact_path(raw_path)
        if not path.exists():
            continue

        lines = path.read_text(encoding="utf-8", errors="replace").splitlines()
        if not lines:
            continue

        header = lines[0].split("\t")
        index = {name: idx for idx, name in enumerate(header)}
        required = {"block_num", "par_num", "line_num", "left", "text"}
        if not required <= set(index):
            continue

        grouped: dict[tuple[int, int, int], list[tuple[int, str]]] = {}

        for raw_row in lines[1:]:
            parts = raw_row.split("\t")
            if len(parts) < len(header):
                parts += [""] * (len(header) - len(parts))

            try:
                word = str(parts[index["text"]] or "").strip()
                if not word:
                    continue
                key = (
                    int(parts[index["block_num"]] or 0),
                    int(parts[index["par_num"]] or 0),
                    int(parts[index["line_num"]] or 0),
                )
                left = int(parts[index["left"]] or 0)
            except (ValueError, IndexError):
                continue

            grouped.setdefault(key, []).append((left, word))

        exact = False
        for entries in grouped.values():
            entries.sort(key=lambda item: item[0])
            line = " ".join(word for _, word in entries)
            if _normalized_ocr_line(line) == wanted:
                exact = True
                break

        if exact:
            try:
                support.append(int(raw_mode))
            except (TypeError, ValueError):
                continue

    return sorted(set(support))


def _recovery_name_words(value: str) -> set[str]:
    return {
        token
        for token in re.findall(r"[a-zäöüß]{3,}", str(value or "").casefold())
    }


def _recover_math_correction_product_name(
    zone: dict[str, Any],
    page_result: dict[str, Any],
) -> dict[str, Any] | None:
    if zone.get("unit_price_math_correction_candidate") is not True:
        return None
    if int(zone.get("psm_support") or 0) < 2:
        return None

    semantic = zone.get("best_semantic_pairing") or {}
    original_name = str(semantic.get("text") or "").strip()
    if not original_name:
        return None

    overlap = {
        _normalized_ocr_line(str(value))
        for value in (semantic.get("keyword_overlap") or [])
        if str(value).strip()
    }
    for crosscheck in zone.get("unit_price_crosschecks") or []:
        if not isinstance(crosscheck, dict):
            continue
        overlap.update(
            _normalized_ocr_line(str(value))
            for value in (crosscheck.get("label_overlap") or [])
            if str(value).strip()
        )

    if not overlap:
        return None

    zone_modes = {
        int(mode)
        for mode in (zone.get("psm_modes") or [])
        if str(mode).isdigit()
    }

    recovered: dict[str, dict[str, Any]] = {}

    for crosscheck in zone.get("unit_price_crosschecks") or []:
        if not isinstance(crosscheck, dict):
            continue

        cross_overlap = {
            _normalized_ocr_line(str(value))
            for value in (crosscheck.get("label_overlap") or [])
            if str(value).strip()
        }
        if not (cross_overlap & overlap):
            continue

        for raw_name in crosscheck.get("unit_nearby") or []:
            name = " ".join(str(raw_name).split())
            if not name:
                continue

            name_words = _recovery_name_words(name)
            if len(name_words) < 2:
                continue
            if not any(token in name_words for token in overlap):
                continue

            support_modes = _tsv_exact_line_support_modes(
                page_result.get("psm_results") or {},
                name,
            )
            shared_modes = sorted(zone_modes & set(support_modes))
            if len(shared_modes) < 2:
                continue

            folded = _normalized_ocr_line(name)
            recovered[folded] = {
                "original_semantic_product_name_raw": original_name,
                "recovered_product_name": name,
                "product_name_recovery_reason": "dual_psm_unit_math_label_overlap",
                "product_name_recovery_psm_modes": shared_modes,
            }

    if len(recovered) != 1:
        return None

    result = next(iter(recovered.values()))
    if _normalized_ocr_line(result["recovered_product_name"]) == _normalized_ocr_line(original_name):
        return None

    return result


def _dry_run_candidates(results: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Flatten automatic OCR zones into auditable, non-persisted candidates."""
    candidates: list[dict[str, Any]] = []
    for item in results:
        if not item.get("success"):
            continue
        page = int(item.get("page") or 0)
        for zone in item.get("ensemble_credible_price_zones") or []:
            if not zone.get("automatic_candidate"):
                continue
            pair = zone.get("best_semantic_pairing") or {}
            checks = zone.get("unit_price_crosschecks") or []
            check = checks[0] if checks else {}
            recovery = _recover_math_correction_product_name(zone, item)
            product_name_raw = (
                str(recovery.get("recovered_product_name") or "").strip()
                if recovery
                else str(pair.get("text") or "").strip()
            )
            if zone.get("unit_price_math_verified"):
                tier = "math_verified"
            elif zone.get("unit_price_math_correction_candidate"):
                tier = "math_correction_review"
            elif zone.get("unit_price_math_unresolved_conflict") or (zone.get("unit_price_math_conflict") and not zone.get("unit_price_math_correction_candidate")):
                tier = "unresolved_math_conflict"
            else:
                tier = "semantic_price_only"
            candidate = {
                "page": page,
                "product_name_raw": product_name_raw,
                "ocr_price_eur": _price_value(str(zone.get("token") or "")),
                "math_expected_price_eur": check.get("expected_sale_price"),
                "proposed_corrected_price_eur": zone.get("unit_price_math_correction_expected_price"),
                "evidence_tier": tier,
                "db_write_eligible": False,
                "psm_modes": zone.get("psm_modes") or [],
                "psm_support": int(zone.get("psm_support") or 0),
                "semantic_score": pair.get("semantic_score"),
                "keyword_overlap": pair.get("keyword_overlap") or [],
                "package_text": check.get("package_text"),
                "unit_price": check.get("unit_price"),
                "unit_kind": check.get("unit_kind"),
                "bbox": zone.get("bbox"),
            }
            if recovery:
                candidate.update(recovery)
            candidates.append(candidate)
    candidates.sort(key=lambda c: (c["page"], c.get("product_name_raw") or "", c.get("ocr_price_eur") or 0))
    return candidates


def select_sample_pages(page_report: dict[str, Any], max_pages: int = 8) -> list[dict[str, Any]]:
    pages = [p for p in page_report.get("pages", []) if isinstance(p, dict) and (p.get("zoom") or p.get("image"))]
    unstructured = [
        p
        for p in pages
        if (p.get("keywords_grocery_hits") or p.get("alt_grocery_hits"))
        and not p.get("all_scalar_price_tokens")
        and int(p.get("links_with_product_details") or 0) == 0
    ]
    metadata_price = [p for p in pages if p.get("all_scalar_price_tokens")]
    structured = [p for p in pages if int(p.get("links_with_product_details") or 0) > 0]

    def even(items: list[dict[str, Any]], count: int) -> list[dict[str, Any]]:
        if count <= 0 or not items:
            return []
        if len(items) <= count:
            return items[:]
        if count == 1:
            return [items[len(items) // 2]]
        indexes = [round(i * (len(items) - 1) / (count - 1)) for i in range(count)]
        out: list[dict[str, Any]] = []
        used: set[int] = set()
        for idx in indexes:
            if idx not in used:
                used.add(idx)
                out.append(items[idx])
        return out

    selected: list[dict[str, Any]] = []
    selected.extend(even(unstructured, min(6, max_pages)))
    if len(selected) < max_pages:
        selected.extend(even(metadata_price, min(1, max_pages - len(selected))))
    if len(selected) < max_pages:
        selected.extend(even(structured, min(1, max_pages - len(selected))))

    dedup: list[dict[str, Any]] = []
    seen: set[Any] = set()
    for page in selected:
        key = page.get("number") or page.get("id")
        if key in seen:
            continue
        seen.add(key)
        dedup.append(page)
    return dedup[:max_pages]


def _tesseract_version() -> str:
    proc = subprocess.run(["tesseract", "--version"], capture_output=True, text=True, check=True, timeout=15)
    return (proc.stdout or proc.stderr).splitlines()[0].strip()


def _tesseract_languages() -> list[str]:
    proc = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, check=True, timeout=15)
    return sorted(line.strip() for line in proc.stdout.splitlines()[1:] if line.strip())


def _download_image(url: str, target: Path, user_agent: str) -> dict[str, Any]:
    headers = {
        "User-Agent": user_agent,
        "Accept": "image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
        "Referer": "https://lidl.leaflets.schwarz/",
    }
    started = time.monotonic()
    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(45.0, connect=10.0), headers=headers) as client:
        response = client.get(url)
        response.raise_for_status()
    target.write_bytes(response.content)
    return {
        "url": url,
        "final_url": str(response.url),
        "status": response.status_code,
        "bytes": len(response.content),
        "content_type": response.headers.get("content-type"),
        "elapsed_ms": round((time.monotonic() - started) * 1000),
    }


def _run_tesseract(image_path: Path, *, language: str = "deu+eng", psm: int = 11) -> tuple[str, float]:
    started = time.monotonic()
    proc = subprocess.run(
        ["tesseract", str(image_path), "stdout", "-l", language, "--psm", str(psm), "tsv"],
        capture_output=True,
        text=True,
        check=True,
        timeout=180,
    )
    return proc.stdout, time.monotonic() - started


def inspect_lidl_ocr(
    *,
    page_report_path: Path,
    output_dir: Path,
    user_agent: str,
    max_pages: int = 8,
    selection_mode: str = "sample",
) -> dict[str, Any]:
    page_report = json.loads(page_report_path.read_text(encoding="utf-8"))
    if selection_mode == "all_grocery":
        selected = select_grocery_pages(page_report)
    elif selection_mode == "sample":
        selected = select_sample_pages(page_report, max_pages=max(1, max_pages))
    else:
        raise ValueError(f"Unknown Lidl OCR selection_mode: {selection_mode}")
    if not selected:
        raise ValueError("No Lidl pages with reachable image URLs were selected")

    version = _tesseract_version()
    languages = _tesseract_languages()
    if "deu" not in languages or "eng" not in languages:
        raise RuntimeError(f"Required Tesseract languages missing: {languages}")

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    run_suffix = "lidl-ocr-full-grocery" if selection_mode == "all_grocery" else "lidl-ocr-sample"
    run_dir = output_dir / f"{stamp}-{run_suffix}"
    run_dir.mkdir(parents=True, exist_ok=True)

    results: list[dict[str, Any]] = []
    for page in selected:
        number = int(page.get("number") or 0)
        image_url = str(page.get("zoom") or page.get("image"))
        image_path = run_dir / f"page-{number:02d}.jpg"
        tsv_path = run_dir / f"page-{number:02d}.tsv"
        txt_path = run_dir / f"page-{number:02d}.txt"
        try:
            download = _download_image(image_url, image_path, user_agent)
            psm_parsed: dict[int, dict[str, Any]] = {}
            psm_results: dict[str, Any] = {}
            ocr_seconds_total = 0.0
            for psm in _OCR_PSM_MODES:
                tsv_text, ocr_seconds = _run_tesseract(image_path, psm=psm)
                ocr_seconds_total += ocr_seconds
                psm_tsv_path = run_dir / f"page-{number:02d}-psm{psm}.tsv"
                psm_txt_path = run_dir / f"page-{number:02d}-psm{psm}.txt"
                psm_tsv_path.write_text(tsv_text, encoding="utf-8")
                parsed_mode = parse_tsv(tsv_text)
                psm_txt_path.write_text(parsed_mode["plain_text"], encoding="utf-8")
                psm_parsed[psm] = parsed_mode
                psm_results[str(psm)] = {
                    "ocr_seconds": round(ocr_seconds, 3),
                    "word_count": parsed_mode["word_count"],
                    "line_count": parsed_mode["line_count"],
                    "malformed_tsv_rows": parsed_mode["malformed_tsv_rows"],
                    "mean_confidence": parsed_mode["mean_confidence"],
                    "text_chars": parsed_mode["text_chars"],
                    "raw_price_zone_count": len(parsed_mode["price_zones"]),
                    "credible_price_zone_count": len(parsed_mode["credible_price_zones"]),
                    "credible_tokens": [z.get("token") for z in parsed_mode["credible_price_zones"][:30]],
                    "tsv_path": str(psm_tsv_path),
                    "text_path": str(psm_txt_path),
                }

            baseline = psm_parsed[_BASELINE_PSM]
            ensemble_zones = merge_credible_price_zones(psm_parsed)
            ensemble_zones = attach_semantic_pairings(ensemble_zones, page)
            ensemble_zones = attach_unit_price_consistency(ensemble_zones, psm_parsed)
            # Preserve the old filenames as the baseline PSM 11 artifacts for
            # compatibility with previous manual inspection commands.
            baseline_tsv = Path(psm_results[str(_BASELINE_PSM)]["tsv_path"]).read_text(encoding="utf-8")
            tsv_path.write_text(baseline_tsv, encoding="utf-8")
            txt_path.write_text(baseline["plain_text"], encoding="utf-8")
            results.append(
                {
                    "page": number,
                    "success": True,
                    "selection": {
                        "grocery_hits": page.get("keywords_grocery_hits") or page.get("alt_grocery_hits") or [],
                        "metadata_prices": page.get("all_scalar_price_tokens") or [],
                        "product_links": int(page.get("links_with_product_details") or 0),
                        "keywords_text": page.get("keywords_text") or page.get("keywords_preview") or "",
                        "alt_text": page.get("alt_text") or page.get("alt_preview") or "",
                    },
                    "download": download,
                    "image_path": str(image_path),
                    "tsv_path": str(tsv_path),
                    "text_path": str(txt_path),
                    "ocr_seconds": round(ocr_seconds_total, 3),
                    "word_count": baseline["word_count"],
                    "line_count": baseline["line_count"],
                    "malformed_tsv_rows": sum(int(v["malformed_tsv_rows"]) for v in psm_results.values()),
                    "median_word_height": baseline["median_word_height"],
                    "text_chars": baseline["text_chars"],
                    "mean_confidence": baseline["mean_confidence"],
                    "price_candidates": baseline["price_candidates"],
                    "price_zones": baseline["price_zones"][:80],
                    "credible_price_zones": baseline["credible_price_zones"][:40],
                    "ensemble_credible_price_zones": ensemble_zones[:80],
                    "psm_results": psm_results,
                    "price_lines": [line for line in baseline["lines"] if line["price_candidates"]][:20],
                    "text_preview": baseline["plain_text"][:1200],
                }
            )
        except Exception as exc:
            results.append(
                {
                    "page": number,
                    "success": False,
                    "selection": {
                        "grocery_hits": page.get("keywords_grocery_hits") or page.get("alt_grocery_hits") or [],
                        "metadata_prices": page.get("all_scalar_price_tokens") or [],
                        "product_links": int(page.get("links_with_product_details") or 0),
                        "keywords_text": page.get("keywords_text") or page.get("keywords_preview") or "",
                        "alt_text": page.get("alt_text") or page.get("alt_preview") or "",
                    },
                    "error": f"{type(exc).__name__}: {exc}"[:1200],
                }
            )

    successful = [item for item in results if item.get("success")]
    with_text = [item for item in successful if int(item.get("text_chars") or 0) >= 100]
    with_raw_prices = [item for item in successful if item.get("price_zones")]
    with_credible_prices = [item for item in successful if item.get("credible_price_zones")]
    with_ensemble_prices = [item for item in successful if item.get("ensemble_credible_price_zones")]
    paired_zones = [
        zone
        for item in successful
        for zone in (item.get("ensemble_credible_price_zones") or [])
        if zone.get("best_pairing")
    ]
    semantic_paired_zones = [
        zone
        for item in successful
        for zone in (item.get("ensemble_credible_price_zones") or [])
        if zone.get("best_semantic_pairing")
    ]
    automatic_zones = [
        zone
        for item in successful
        for zone in (item.get("ensemble_credible_price_zones") or [])
        if zone.get("automatic_candidate")
    ]
    math_verified_zones = [zone for zone in automatic_zones if zone.get("unit_price_math_verified")]
    math_conflict_zones = [zone for zone in automatic_zones if zone.get("unit_price_math_conflict")]
    math_correctable_zones = [zone for zone in math_conflict_zones if zone.get("unit_price_math_correction_candidate")]
    math_unresolved_conflict_zones = [zone for zone in math_conflict_zones if not zone.get("unit_price_math_correction_candidate")]
    math_crosscheck_zones = [zone for zone in automatic_zones if zone.get("unit_price_crosschecks")]
    pages_with_automatic = sum(
        1 for item in successful if any(z.get("automatic_candidate") for z in (item.get("ensemble_credible_price_zones") or []))
    )
    malformed_total = sum(int(item.get("malformed_tsv_rows") or 0) for item in successful)
    baseline_total = sum(len(item.get("credible_price_zones") or []) for item in successful)
    ensemble_total = sum(len(item.get("ensemble_credible_price_zones") or []) for item in successful)
    psm_totals = {str(psm): 0 for psm in _OCR_PSM_MODES}
    psm_pages = {str(psm): 0 for psm in _OCR_PSM_MODES}
    for item in successful:
        for psm in _OCR_PSM_MODES:
            count = int((item.get("psm_results") or {}).get(str(psm), {}).get("credible_price_zone_count") or 0)
            psm_totals[str(psm)] += count
            if count:
                psm_pages[str(psm)] += 1

    gain = ensemble_total - baseline_total
    auto_total = len(automatic_zones)
    verified_total = len(math_verified_zones)
    conflict_total = len(math_conflict_zones)
    correctable_total = len(math_correctable_zones)
    unresolved_conflict_total = len(math_unresolved_conflict_zones)
    dry_candidates = _dry_run_candidates(successful)
    tier_counts = {
        "math_verified": sum(c["evidence_tier"] == "math_verified" for c in dry_candidates),
        "math_correction_review": sum(c["evidence_tier"] == "math_correction_review" for c in dry_candidates),
        "semantic_price_only": sum(c["evidence_tier"] == "semantic_price_only" for c in dry_candidates),
        "unresolved_math_conflict": sum(c["evidence_tier"] == "unresolved_math_conflict" for c in dry_candidates),
    }
    success_ratio = round(len(successful) / len(selected), 3) if selected else 0.0
    if selection_mode == "all_grocery":
        if success_ratio >= 0.9 and tier_counts["unresolved_math_conflict"] == 0 and tier_counts["math_verified"] >= 10:
            recommendation = "candidate_contract_mapping_ready"
        elif success_ratio >= 0.85 and tier_counts["unresolved_math_conflict"] == 0 and (tier_counts["math_verified"] + tier_counts["math_correction_review"]) >= 5:
            recommendation = "full_grocery_dry_run_promising"
        elif tier_counts["unresolved_math_conflict"] > 0:
            recommendation = "full_grocery_conflict_review"
        else:
            recommendation = "full_grocery_coverage_tuning_needed"
    elif successful and auto_total >= 4 and verified_total >= 4 and unresolved_conflict_total == 0:
        recommendation = "full_grocery_dry_run_ready"
    elif successful and verified_total >= 3 and conflict_total > 0 and unresolved_conflict_total == 0:
        recommendation = "math_correction_candidate_review"
    elif successful and verified_total > 0 and conflict_total == 0:
        recommendation = "unit_math_promising_more_coverage_needed"
    elif successful and unresolved_conflict_total > 0:
        recommendation = "price_pairing_conflict_review"
    elif successful and auto_total > 0:
        recommendation = "semantic_candidates_without_math_evidence"
    else:
        recommendation = "ocr_strategy_unresolved"

    report: dict[str, Any] = {
        "schema_version": 9 if selection_mode == "all_grocery" else 8,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": "full_grocery_ocr_dry_run" if selection_mode == "all_grocery" else "targeted_page_ocr_unit_math_correction_gate_audit",
        "selection_mode": selection_mode,
        "db_write_performed": False,
        "grocery_pages_available": len(select_grocery_pages(page_report)),
        "playwright_used": False,
        "ocr_used": True,
        "ocr_engine": "tesseract",
        "ocr_version": version,
        "ocr_languages": languages,
        "ocr_language_request": "deu+eng",
        "ocr_psm_modes": list(_OCR_PSM_MODES),
        "ocr_baseline_psm": _BASELINE_PSM,
        "page_report": str(page_report_path),
        "leaflet_key": page_report.get("leaflet_key"),
        "offer_start": page_report.get("flyer", {}).get("offerStartDate"),
        "offer_end": page_report.get("flyer", {}).get("offerEndDate"),
        "sample_dir": str(run_dir),
        "pages_selected": len(selected),
        "pages_successful": len(successful),
        "page_success_ratio": success_ratio,
        "pages_with_text": len(with_text),
        "pages_with_raw_price_zones": len(with_raw_prices),
        "pages_with_credible_price_zones": len(with_credible_prices),
        "pages_with_ensemble_price_zones": len(with_ensemble_prices),
        "raw_price_zone_total": sum(len(item.get("price_zones") or []) for item in successful),
        "credible_price_zone_total": baseline_total,
        "ensemble_credible_price_zone_total": ensemble_total,
        "ensemble_gain_vs_psm11": gain,
        "credible_zones_with_pairing_total": len(paired_zones),
        "semantic_pairing_total": len(semantic_paired_zones),
        "automatic_candidate_total": len(automatic_zones),
        "pages_with_automatic_candidates": pages_with_automatic,
        "automatic_candidates_with_unit_crosscheck": len(math_crosscheck_zones),
        "automatic_candidates_math_verified": len(math_verified_zones),
        "automatic_candidates_math_conflicted": len(math_conflict_zones),
        "automatic_candidates_math_correctable": len(math_correctable_zones),
        "automatic_candidates_math_unresolved_conflict": len(math_unresolved_conflict_zones),
        "math_verified_or_correctable_total": len(math_verified_zones) + len(math_correctable_zones),
        "math_verified_ratio": round(len(math_verified_zones) / auto_total, 3) if auto_total else 0.0,
        "credible_price_zone_total_by_psm": psm_totals,
        "pages_with_credible_price_zones_by_psm": psm_pages,
        "malformed_tsv_rows_total": malformed_total,
        "ocr_seconds_total": round(sum(float(item.get("ocr_seconds") or 0) for item in successful), 3),
        "dry_run_candidate_total": len(dry_candidates),
        "dry_run_candidate_tiers": tier_counts,
        "dry_run_candidates": dry_candidates,
        "recommendation": recommendation,
        "pages": results,
        "gate": {
            "engine_available": True,
            "languages_available": True,
            "enough_pages_attempted": len(selected) >= min(4, max_pages),
            "enough_pages_succeeded": len(successful) >= min(4, len(selected)),
            "tsv_parser_sane": malformed_total <= max(20, len(successful) * 5),
        },
    }
    report_suffix = "lidl-ocr-full-grocery-dry-run.json" if selection_mode == "all_grocery" else "lidl-ocr-correction-gate-audit.json"
    report_path = output_dir / f"{stamp}-{report_suffix}"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
