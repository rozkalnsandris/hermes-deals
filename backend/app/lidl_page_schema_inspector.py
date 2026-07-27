from __future__ import annotations

import json
import re
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

import httpx

_PRICE_PATTERNS = (
    re.compile(r"(?<!\d)\d{1,3}[.,]\d{2}\s*€?", re.IGNORECASE),
    re.compile(r"(?<!\d)\d{1,3}[.,]-\s*€?", re.IGNORECASE),
    re.compile(r"(?<!\d)[.,]\d{2}\s*€?", re.IGNORECASE),
    re.compile(r"(?<!\d)\d{1,3}\s*€(?!\w)", re.IGNORECASE),
    re.compile(r"(?<!\d)\d{1,3}\s*(?:ct|cent)(?!\w)", re.IGNORECASE),
)
_GROCERY_TERMS = (
    "milch", "käse", "joghurt", "quark", "butter", "brot", "brötchen", "fleisch",
    "hähnchen", "wurst", "lachs", "garnelen", "fisch", "paprika", "tomate", "gurke",
    "apfel", "äpfel", "banane", "melone", "trauben", "heidelbeeren", "gemüse", "obst",
    "wasser", "saft", "cola", "kaffee", "schokolade", "nudeln", "reis", "kartoffeln",
    "pistazien", "möhren", "kiwi", "haferdrink", "pizza", "eis", "wein", "bier",
)
_INTERESTING_KEY_RE = re.compile(
    r"price|preis|amount|currency|discount|rabatt|offer|aktion|product|produkt|article|artikel|"
    r"hotspot|link|keyword|text|ocr|content|label|title|description",
    re.IGNORECASE,
)


def price_like_tokens(text: str) -> list[str]:
    value = text or ""
    candidates: list[tuple[int, int, str]] = []
    for pattern in _PRICE_PATTERNS:
        for match in pattern.finditer(value):
            token = match.group(0).strip()
            candidates.append((match.start(), match.end(), token))

    # Prefer the longest match at a given position and reject overlapping
    # sub-matches such as ``29 €`` inside ``1,29 €``.
    candidates.sort(key=lambda item: (item[0], -(item[1] - item[0])))
    selected: list[tuple[int, int, str]] = []
    for start, end, token in candidates:
        if any(start < chosen_end and end > chosen_start for chosen_start, chosen_end, _ in selected):
            continue
        selected.append((start, end, token))
    selected.sort(key=lambda item: item[0])
    return [token for _, _, token in selected]


def grocery_hits(text: str) -> list[str]:
    """Return grocery terms as real OCR words, not arbitrary substrings.

    The Phase 2B7 deep scan exposed false positives such as ``reis`` inside
    ``Preis`` and ``eis`` inside unrelated words. Token-aware matching keeps
    genuine flyer terms while avoiding those substring collisions.
    """
    tokens = set(re.findall(r"[a-zäöüß]+", (text or "").lower()))
    return sorted({term for term in _GROCERY_TERMS if term in tokens})


def _flyer_object(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        flyer = payload.get("flyer")
        if isinstance(flyer, dict):
            return flyer
        if isinstance(payload.get("pages"), list):
            return payload
    return None


def _iter_scalars(value: Any, path: str = "$", *, max_depth: int = 8) -> Iterable[tuple[str, str, Any]]:
    if max_depth < 0:
        return
    if isinstance(value, dict):
        for key, child in value.items():
            child_path = f"{path}.{key}"
            if isinstance(child, (dict, list)):
                yield from _iter_scalars(child, child_path, max_depth=max_depth - 1)
            else:
                yield child_path, str(key), child
    elif isinstance(value, list):
        for index, child in enumerate(value):
            child_path = f"{path}[{index}]"
            if isinstance(child, (dict, list)):
                yield from _iter_scalars(child, child_path, max_depth=max_depth - 1)
            else:
                yield child_path, str(index), child


def _safe_text(value: Any, limit: int = 300) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    return text[:limit]


def analyze_page(page: dict[str, Any]) -> dict[str, Any]:
    keywords = page.get("keyWords") if isinstance(page.get("keyWords"), str) else ""
    alt_text = page.get("altText") if isinstance(page.get("altText"), str) else ""
    links = page.get("links")
    if isinstance(links, list):
        link_items = [item for item in links if isinstance(item, dict)]
    elif isinstance(links, dict):
        link_items = [item for item in links.values() if isinstance(item, dict)]
    else:
        link_items = []

    nested_key_counts: Counter[str] = Counter()
    interesting_fields: list[dict[str, Any]] = []
    all_text: list[str] = []
    for path, key, value in _iter_scalars(page):
        nested_key_counts[key] += 1
        if isinstance(value, str):
            all_text.append(value)
        if _INTERESTING_KEY_RE.search(key):
            text = _safe_text(value)
            if text is not None and len(interesting_fields) < 60:
                interesting_fields.append({"path": path, "key": key, "value": text})

    scalar_text = "\n".join(all_text)
    image = page.get("image") if isinstance(page.get("image"), str) else None
    zoom = page.get("zoom") if isinstance(page.get("zoom"), str) else None
    thumbnail = page.get("thumbnail") if isinstance(page.get("thumbnail"), str) else None

    return {
        "id": page.get("id"),
        "number": page.get("number"),
        "root_keys": sorted(page.keys()),
        "image": image,
        "zoom": zoom,
        "thumbnail": thumbnail,
        "keywords_chars": len(keywords),
        "keywords_price_tokens": price_like_tokens(keywords)[:80],
        "keywords_grocery_hits": grocery_hits(keywords),
        "keywords_text": keywords or None,
        "keywords_preview": keywords[:700] if keywords else None,
        "alt_chars": len(alt_text),
        "alt_price_tokens": price_like_tokens(alt_text)[:40],
        "alt_grocery_hits": grocery_hits(alt_text),
        "alt_text": alt_text or None,
        "alt_preview": alt_text[:500] if alt_text else None,
        "all_scalar_price_tokens": price_like_tokens(scalar_text)[:120],
        "links_count": len(link_items),
        "links_with_product_details": sum(1 for item in link_items if isinstance(item.get("productDetails"), dict)),
        "nested_key_counts": dict(nested_key_counts),
        "interesting_fields": interesting_fields,
    }


def _current_payload_path(structure_report: dict[str, Any]) -> tuple[str, Path, dict[str, Any]]:
    probes = structure_report.get("flyer_probes")
    if not isinstance(probes, list):
        raise ValueError("Structure report has no flyer_probes")
    for probe in probes:
        if not isinstance(probe, dict) or not probe.get("success"):
            continue
        key = str(probe.get("leaflet_key") or "")
        if not key.startswith("latest-leaflet-"):
            continue
        attempts = probe.get("attempts")
        if not isinstance(attempts, list):
            continue
        for attempt in attempts:
            if not isinstance(attempt, dict) or int(attempt.get("status") or 0) != 200:
                continue
            saved = attempt.get("saved")
            if not isinstance(saved, dict) or not saved.get("path"):
                continue
            path = Path(str(saved["path"]))
            return key, path, probe
    raise ValueError("No saved current Lidl flyer JSON payload found")


def _probe_asset(url: str | None, user_agent: str) -> dict[str, Any]:
    if not url:
        return {"url": None, "status": None, "reachable": False, "error": "missing URL"}
    headers = {
        "User-Agent": user_agent,
        "Accept": "*/*",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
        "Referer": "https://www.lidl.de/",
        "Range": "bytes=0-4095",
    }
    try:
        with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, connect=10.0), headers=headers) as client:
            with client.stream("GET", url) as response:
                return {
                    "url": url,
                    "final_url": str(response.url),
                    "status": response.status_code,
                    "reachable": response.status_code in (200, 206),
                    "content_type": response.headers.get("content-type"),
                    "content_length": response.headers.get("content-length"),
                    "content_range": response.headers.get("content-range"),
                    "accept_ranges": response.headers.get("accept-ranges"),
                    "error": None,
                }
    except Exception as exc:
        return {
            "url": url,
            "status": None,
            "reachable": False,
            "error": f"{type(exc).__name__}: {exc}"[:1000],
        }


def inspect_lidl_page_schema(
    *,
    structure_report_path: Path,
    output_dir: Path,
    user_agent: str,
) -> dict[str, Any]:
    structure = json.loads(structure_report_path.read_text(encoding="utf-8"))
    leaflet_key, payload_path, probe = _current_payload_path(structure)
    payload = json.loads(payload_path.read_text(encoding="utf-8"))
    flyer = _flyer_object(payload)
    if flyer is None:
        raise ValueError("Saved Lidl payload has no flyer object")
    pages_raw = flyer.get("pages")
    if not isinstance(pages_raw, list):
        raise ValueError("Current Lidl flyer has no pages list")
    pages = [page for page in pages_raw if isinstance(page, dict)]

    analyzed = [analyze_page(page) for page in pages]
    root_key_counts: Counter[str] = Counter()
    nested_key_counts: Counter[str] = Counter()
    for page in analyzed:
        root_key_counts.update(page["root_keys"])
        nested_key_counts.update(page["nested_key_counts"])

    pages_with_keywords = sum(1 for page in analyzed if page["keywords_chars"] > 0)
    pages_with_images = sum(1 for page in analyzed if page.get("image"))
    pages_with_grocery_terms = sum(1 for page in analyzed if page["keywords_grocery_hits"] or page["alt_grocery_hits"])
    pages_with_keyword_prices = sum(1 for page in analyzed if page["keywords_price_tokens"])
    pages_with_any_scalar_prices = sum(1 for page in analyzed if page["all_scalar_price_tokens"])
    pages_with_product_details = sum(1 for page in analyzed if page["links_with_product_details"] > 0)

    interesting_key_counts = {
        key: count for key, count in sorted(nested_key_counts.items()) if _INTERESTING_KEY_RE.search(key)
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dump_path = output_dir / f"{stamp}-lidl-page-metadata-dump.txt"
    dump_parts: list[str] = []
    for page in analyzed:
        dump_parts.append(f"===== PAGE {page.get('number')} =====\n")
        dump_parts.append("KEYWORDS:\n{}\n\n".format(page.get("keywords_preview") or ""))
        dump_parts.append("ALT:\n{}\n\n".format(page.get("alt_preview") or ""))
        dump_parts.append("PRICE TOKENS: {}\n".format(page.get("all_scalar_price_tokens") or []))
        dump_parts.append("GROCERY: {}\n\n".format(page.get("keywords_grocery_hits") or page.get("alt_grocery_hits") or []))
    dump_path.write_text("".join(dump_parts), encoding="utf-8")

    meta = probe.get("summary", {}).get("flyer", {}) if isinstance(probe.get("summary"), dict) else {}
    pdf_url = meta.get("pdfUrl") or flyer.get("pdfUrl")
    hires_pdf_url = meta.get("hiResPdfUrl") or flyer.get("hiResPdfUrl")
    first_image = next((page.get("image") for page in analyzed if page.get("image")), None)
    first_zoom = next((page.get("zoom") for page in analyzed if page.get("zoom")), None)

    asset_probes = {
        "pdf": _probe_asset(str(pdf_url) if pdf_url else None, user_agent),
        "hires_pdf": _probe_asset(str(hires_pdf_url) if hires_pdf_url else None, user_agent),
        "first_page_image": _probe_asset(str(first_image) if first_image else None, user_agent),
        "first_page_zoom": _probe_asset(str(first_zoom) if first_zoom else None, user_agent),
    }

    if pages_with_keyword_prices >= 10:
        recommendation = "metadata_price_parser_candidate"
    elif pages_with_any_scalar_prices >= 10:
        recommendation = "nested_page_fields_parser_candidate"
    elif pages_with_images >= max(1, int(len(analyzed) * 0.80)):
        recommendation = "page_image_price_extraction_needed"
    else:
        recommendation = "source_strategy_unresolved"

    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": "lidl_page_schema_deep_scan",
        "playwright_used": False,
        "ocr_used": False,
        "pdf_required": False,
        "structure_report": str(structure_report_path),
        "payload_path": str(payload_path),
        "leaflet_key": leaflet_key,
        "flyer": {
            "title": meta.get("title") or flyer.get("title"),
            "offerStartDate": meta.get("offerStartDate") or flyer.get("offerStartDate"),
            "offerEndDate": meta.get("offerEndDate") or flyer.get("offerEndDate"),
            "pdfUrl": pdf_url,
            "hiResPdfUrl": hires_pdf_url,
        },
        "page_count": len(analyzed),
        "pages_with_keywords": pages_with_keywords,
        "pages_with_images": pages_with_images,
        "pages_with_grocery_terms": pages_with_grocery_terms,
        "pages_with_keyword_price_tokens": pages_with_keyword_prices,
        "pages_with_any_scalar_price_tokens": pages_with_any_scalar_prices,
        "pages_with_product_details": pages_with_product_details,
        "root_key_counts": dict(sorted(root_key_counts.items())),
        "interesting_nested_key_counts": interesting_key_counts,
        "asset_probes": asset_probes,
        "metadata_dump_path": str(dump_path),
        "recommendation": recommendation,
        "pages": analyzed,
        "gate": {
            "payload_loaded": True,
            "enough_pages": len(analyzed) >= 50,
            "page_images_available": pages_with_images >= max(1, int(len(analyzed) * 0.80)),
        },
    }
    report_path = output_dir / f"{stamp}-lidl-page-schema-analysis.json"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
