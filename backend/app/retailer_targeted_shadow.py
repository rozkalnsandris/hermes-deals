from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
from io import BytesIO
import html
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Iterable
from urllib.parse import urljoin

import httpx

from app.settings import get_settings
from app.structured_source_shadow import (
    LIDL_OVERVIEW_URL,
    LIDL_STORE_URL,
    NETTO_STORE_ID,
    NETTO_STORE_URL,
    extract_lidl_flyers,
    extract_lidl_store_id,
    extract_netto_direct_viewers,
    extract_netto_group_slug,
    find_lidl_payload_url,
)

USER_AGENT = "HermesDeals/phase5g-block-b3-v02"
PUBLITAS_API = "https://api.publitas.com/v1"
PUBLITAS_ASSET_BASE = "https://view.publitas.com"


def save_bytes(root: Path, stamp: str, label: str, content: bytes, ext: str) -> dict[str, Any]:
    digest = sha256(content).hexdigest()
    path = root / f"{stamp}-{label}-{digest[:12]}.{ext.lstrip('.')}"
    path.write_bytes(content)
    return {"path": str(path), "sha256": digest, "bytes": len(content)}


def save_text(root: Path, stamp: str, label: str, text: str) -> dict[str, Any]:
    return save_bytes(root, stamp, label, text.encode("utf-8"), "txt")


def publitas_product_ids(payload: dict[str, Any]) -> list[int]:
    ids: set[int] = set()
    for spread in payload.get("spreads") or []:
        if not isinstance(spread, dict):
            continue
        for hotspot in spread.get("hotspots") or []:
            if not isinstance(hotspot, dict) or hotspot.get("type") != "product":
                continue
            for product in hotspot.get("products") or []:
                if isinstance(product, dict) and isinstance(product.get("id"), int):
                    ids.add(product["id"])
    return sorted(ids)


def publitas_product_url(group: str, publication: str, product_id: int) -> str:
    return (
        f"{PUBLITAS_API}/groups/{group}/publications/"
        f"{publication}/products/{product_id}.json"
    )


def publitas_page_image_url(page_path: str, size: str = "at1600") -> str:
    if not page_path.startswith("/"):
        raise ValueError("Publitas page path must start with /")
    return f"{PUBLITAS_ASSET_BASE}{page_path}-{size}.jpg"


def publitas_asset_url(relative_or_absolute: str) -> str:
    if relative_or_absolute.startswith("http://") or relative_or_absolute.startswith("https://"):
        return relative_or_absolute
    return urljoin(PUBLITAS_ASSET_BASE + "/", relative_or_absolute.lstrip("/"))


def publication_page_paths(payload: dict[str, Any]) -> list[str]:
    result: list[str] = []
    for spread in payload.get("spreads") or []:
        if not isinstance(spread, dict):
            continue
        for page in spread.get("pages") or []:
            if isinstance(page, str):
                result.append(page)
    return result


def extract_german_date_ranges(text: str, default_year: int) -> list[tuple[date, date]]:
    normalized = (
        html.unescape(text)
        .replace("–", "-")
        .replace("—", "-")
        .replace(" bis ", " - ")
    )
    result: set[tuple[date, date]] = set()

    short_long = re.compile(
        r"\b(\d{1,2})\.(\d{1,2})\.\s*-\s*"
        r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b"
    )
    both_full = re.compile(
        r"\b(\d{1,2})\.(\d{1,2})\.(\d{2,4})\s*-\s*"
        r"(\d{1,2})\.(\d{1,2})\.(\d{2,4})\b"
    )
    short_short = re.compile(
        r"\b(\d{1,2})\.(\d{1,2})\.\s*-\s*"
        r"(\d{1,2})\.(\d{1,2})\.\b"
    )

    for m in short_long.finditer(normalized):
        d1, m1, d2, m2, y2 = map(int, m.groups())
        end_year = 2000 + y2 if y2 < 100 else y2
        start_year = end_year - 1 if m1 > m2 else end_year
        result.add((date(start_year, m1, d1), date(end_year, m2, d2)))

    for m in both_full.finditer(normalized):
        d1, m1, y1, d2, m2, y2 = map(int, m.groups())
        y1 = 2000 + y1 if y1 < 100 else y1
        y2 = 2000 + y2 if y2 < 100 else y2
        result.add((date(y1, m1, d1), date(y2, m2, d2)))

    for m in short_short.finditer(normalized):
        d1, m1, d2, m2 = map(int, m.groups())
        start_year = default_year
        end_year = default_year + 1 if m1 > m2 else default_year
        result.add((date(start_year, m1, d1), date(end_year, m2, d2)))

    return sorted(result)


def netto_publication_start_context(store_html: str, slug: str) -> list[str]:
    text = html.unescape(store_html)
    result: set[str] = set()
    for match in re.finditer(re.escape(slug), text):
        block = text[max(0, match.start() - 2200) : match.start()]
        hits = re.findall(
            r"(?i)ab\s+(?:Montag|Dienstag|Mittwoch|Donnerstag|Freitag|Samstag|Sonntag),?\s*"
            r"(\d{2}\.\d{2}\.\d{2,4})",
            block,
        )
        if hits:
            result.add(hits[-1])
    return sorted(result)


def _tesseract_text(image_path: Path, psm: int) -> str:
    proc = subprocess.run(
        [
            "tesseract",
            str(image_path),
            "stdout",
            "-l",
            "deu+eng",
            "--psm",
            str(psm),
        ],
        check=True,
        text=True,
        capture_output=True,
        timeout=150,
    )
    return proc.stdout


def _first_page_ocr(
    client: httpx.Client,
    root: Path,
    stamp: str,
    slug: str,
    page_path: str,
) -> dict[str, Any]:
    url = publitas_page_image_url(page_path, "at1600")
    response = client.get(url)
    response.raise_for_status()
    raw = save_bytes(root, stamp, f"netto-{slug}-first-page", response.content, "jpg")
    local_path = Path(raw["path"])
    texts: list[str] = []
    modes: dict[str, int] = {}
    for psm in (6, 11):
        text = _tesseract_text(local_path, psm)
        texts.append(text)
        modes[str(psm)] = len(text)
    merged = "\n".join(texts)
    text_raw = save_text(root, stamp, f"netto-{slug}-first-page-ocr", merged)
    return {
        "url": url,
        "raw": raw,
        "text_raw": text_raw,
        "text_chars_by_psm": modes,
        "date_ranges": [
            [a.isoformat(), b.isoformat()]
            for a, b in extract_german_date_ranges(merged, datetime.now().year)
        ],
        "text_preview": merged[:1200],
    }


def _pdf_text_fallback(
    client: httpx.Client,
    root: Path,
    stamp: str,
    slug: str,
    download_pdf_url: str | None,
) -> dict[str, Any]:
    if not download_pdf_url:
        return {"attempted": False, "reason": "publication_has_no_download_pdf_url"}
    try:
        from pypdf import PdfReader
    except Exception as exc:
        return {
            "attempted": False,
            "reason": f"pypdf_unavailable:{type(exc).__name__}",
        }

    url = publitas_asset_url(download_pdf_url)
    try:
        response = client.get(url, timeout=120.0)
        response.raise_for_status()
        raw = save_bytes(root, stamp, f"netto-{slug}-publication", response.content, "pdf")
        reader = PdfReader(BytesIO(response.content))
        texts: list[str] = []
        for page in reader.pages[:3]:
            try:
                texts.append(page.extract_text() or "")
            except Exception:
                texts.append("")
        merged = "\n".join(texts)
        text_raw = save_text(root, stamp, f"netto-{slug}-pdf-text", merged)
        return {
            "attempted": True,
            "url": url,
            "raw": raw,
            "text_raw": text_raw,
            "pages_total": len(reader.pages),
            "pages_examined": min(3, len(reader.pages)),
            "text_chars": len(merged),
            "date_ranges": [
                [a.isoformat(), b.isoformat()]
                for a, b in extract_german_date_ranges(merged, datetime.now().year)
            ],
            "text_preview": merged[:1200],
        }
    except Exception as exc:
        return {
            "attempted": True,
            "url": url,
            "error": f"{type(exc).__name__}: {exc}"[:1000],
            "date_ranges": [],
        }


def _publication_products(
    client: httpx.Client,
    root: Path,
    stamp: str,
    group: str,
    slug: str,
    payload: dict[str, Any],
) -> list[dict[str, Any]]:
    result: list[dict[str, Any]] = []
    for product_id in publitas_product_ids(payload):
        url = publitas_product_url(group, slug, product_id)
        try:
            response = client.get(url, headers={"Accept": "application/json"})
            response.raise_for_status()
            raw = save_bytes(
                root,
                stamp,
                f"netto-{slug}-product-{product_id}",
                response.content,
                "json",
            )
            product = response.json()
            result.append(
                {
                    "resolved": True,
                    "id": product.get("id"),
                    "hotspot_id": product.get("hotspotId"),
                    "title": product.get("title"),
                    "description": product.get("description"),
                    "price": product.get("price"),
                    "discounted_price": product.get("discountedPrice"),
                    "webshop_identifier": product.get("webshopIdentifier"),
                    "webshop_url": product.get("webshopUrl"),
                    "photo_count": len(product.get("photos") or []),
                    "raw": raw,
                }
            )
        except Exception as exc:
            result.append(
                {
                    "resolved": False,
                    "id": product_id,
                    "url": url,
                    "error": f"{type(exc).__name__}: {exc}"[:1000],
                }
            )
    return result


def run_netto(client: httpx.Client, root: Path, stamp: str) -> dict[str, Any]:
    store = client.get(NETTO_STORE_URL)
    store.raise_for_status()
    store_raw = save_bytes(root, stamp, "netto-store-5659", store.content, "html")

    viewers = extract_netto_direct_viewers(store.text, NETTO_STORE_ID)
    publications: list[dict[str, Any]] = []
    today = datetime.now(timezone.utc).date()

    for slug, viewer_url in sorted(viewers.items()):
        viewer = client.get(viewer_url)
        viewer.raise_for_status()
        viewer_raw = save_bytes(root, stamp, f"netto-viewer-{slug}", viewer.content, "html")
        group = extract_netto_group_slug(viewer.text)
        if not group:
            raise RuntimeError(f"Publitas group slug missing for {slug}")

        api_url = f"{PUBLITAS_API}/groups/{group}/publications/{slug}.json"
        response = client.get(api_url, headers={"Accept": "application/json"})
        response.raise_for_status()
        api_raw = save_bytes(root, stamp, f"netto-publication-{slug}", response.content, "json")
        payload = response.json()
        config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
        pages = publication_page_paths(payload)

        products = _publication_products(client, root, stamp, group, slug, payload)

        first_page = None
        ocr_ranges: list[list[str]] = []
        if pages:
            try:
                first_page = _first_page_ocr(client, root, stamp, slug, pages[0])
                ocr_ranges = list(first_page["date_ranges"])
            except Exception as exc:
                first_page = {
                    "error": f"{type(exc).__name__}: {exc}"[:1000],
                    "date_ranges": [],
                }

        pdf = {"attempted": False, "reason": "not_needed_first_page_ocr_has_date_range"}
        pdf_ranges: list[list[str]] = []
        if not ocr_ranges:
            pdf = _pdf_text_fallback(
                client,
                root,
                stamp,
                slug,
                config.get("downloadPdfUrl"),
            )
            pdf_ranges = list(pdf.get("date_ranges") or [])

        combined_ranges = sorted({tuple(x) for x in ocr_ranges + pdf_ranges})
        current_by_explicit_range = any(
            date.fromisoformat(start) <= today <= date.fromisoformat(end)
            for start, end in combined_ranges
        )

        publications.append(
            {
                "slug": slug,
                "group_slug": group,
                "viewer_url": str(viewer.url),
                "viewer_raw": viewer_raw,
                "public_api_url": api_url,
                "public_api_raw": api_raw,
                "publication_id": config.get("publicationId"),
                "title": config.get("publicationTitle"),
                "download_pdf_url": config.get("downloadPdfUrl"),
                "page_count": len(pages),
                "product_hotspot_ids": publitas_product_ids(payload),
                "structured_product_count": sum(bool(x.get("resolved")) for x in products),
                "structured_product_failures": sum(not bool(x.get("resolved")) for x in products),
                "structured_products": products,
                "store_start_signals": netto_publication_start_context(store.text, slug),
                "first_page_ocr": first_page,
                "pdf_text_fallback": pdf,
                "explicit_validity_ranges": [list(x) for x in combined_ranges],
                "current_by_explicit_range": current_by_explicit_range,
            }
        )

    return {
        "store_id": NETTO_STORE_ID,
        "store_url": str(store.url),
        "store_raw": store_raw,
        "viewer_count": len(viewers),
        "publications": publications,
        "structured_product_total": sum(x["structured_product_count"] for x in publications),
        "current_publications_by_explicit_range": [
            x["slug"] for x in publications if x["current_by_explicit_range"]
        ],
    }


def _collection_items(value: Any) -> list[tuple[str | None, dict[str, Any]]]:
    if isinstance(value, dict):
        return [(str(k), v) for k, v in value.items() if isinstance(v, dict)]
    if isinstance(value, list):
        return [(None, v) for v in value if isinstance(v, dict)]
    return []


def _price_value(value: Any) -> float | None:
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, (int, float)):
        return float(value)
    if isinstance(value, str):
        text = value.strip().replace(",", ".")
        try:
            return float(text)
        except ValueError:
            return None
    if isinstance(value, dict):
        for key in ("value", "amount", "current", "price"):
            if key in value:
                parsed = _price_value(value[key])
                if parsed is not None:
                    return parsed
    return None


def lidl_root_products(detail: dict[str, Any]) -> list[dict[str, Any]]:
    flyer = detail.get("flyer") if isinstance(detail.get("flyer"), dict) else detail
    products_raw = flyer.get("products") if isinstance(flyer, dict) else None
    rows: list[dict[str, Any]] = []
    for collection_key, product in _collection_items(products_raw):
        product_id = product.get("id") or product.get("productId") or collection_key
        title = product.get("name") or product.get("title")
        price = _price_value(product.get("price"))
        rows.append(
            {
                "collection_key": collection_key,
                "id": None if product_id is None else str(product_id),
                "title": None if title is None else str(title).strip(),
                "brand": product.get("brand"),
                "price": price,
                "currency_text": product.get("currencyText"),
                "currency_symbol": product.get("currencySymbol"),
                "image": product.get("image") or product.get("imageUrl"),
                "url": product.get("url") or product.get("canonicalUrl"),
                "keys": sorted(map(str, product.keys()))[:80],
            }
        )
    return rows


def _iter_links(page: dict[str, Any]) -> Iterable[dict[str, Any]]:
    links = page.get("links")
    if isinstance(links, list):
        yield from (x for x in links if isinstance(x, dict))
    elif isinstance(links, dict):
        yield from (x for x in links.values() if isinstance(x, dict))


def lidl_linked_product_ids(detail: dict[str, Any]) -> set[str]:
    flyer = detail.get("flyer") if isinstance(detail.get("flyer"), dict) else detail
    pages = flyer.get("pages") if isinstance(flyer, dict) and isinstance(flyer.get("pages"), list) else []
    result: set[str] = set()
    for page in pages:
        if not isinstance(page, dict):
            continue
        for link in _iter_links(page):
            product = link.get("productDetails")
            if not isinstance(product, dict):
                continue
            product_id = product.get("productId") or product.get("id")
            if product_id is not None:
                result.add(str(product_id))
    return result


def lidl_product_signature(products: list[dict[str, Any]]) -> str:
    stable = sorted(
        (
            str(row.get("id") or ""),
            str(row.get("title") or ""),
            "" if row.get("price") is None else f"{float(row['price']):.4f}",
        )
        for row in products
    )
    return sha256(
        json.dumps(stable, ensure_ascii=False, separators=(",", ":")).encode("utf-8")
    ).hexdigest()


def select_current_lidl_variants(
    flyers: list[dict[str, Any]],
    on_date: date,
) -> list[dict[str, Any]]:
    result = []
    for flyer in flyers:
        if flyer.get("name") != "Aktionsprospekt":
            continue
        try:
            start = date.fromisoformat(str(flyer.get("offerStartDate")))
            end = date.fromisoformat(str(flyer.get("offerEndDate")))
        except ValueError:
            continue
        if start <= on_date <= end and flyer.get("flyerJson"):
            result.append(flyer)
    return result


def resolve_nuxt_store_object(payload: Any, store_id: str) -> dict[str, Any] | None:
    if not isinstance(payload, list):
        return None
    store_indices = {i for i, value in enumerate(payload) if value == store_id}
    if not store_indices:
        return None
    for idx, value in enumerate(payload):
        if not isinstance(value, dict):
            continue
        ref = value.get("objectNumber")
        if isinstance(ref, int) and ref in store_indices:
            return {"payload_index": idx, "raw_ref_object": value}
    return None


def _resolve_nuxt_ref(payload: list[Any], value: Any, depth: int = 0, seen: set[int] | None = None) -> Any:
    if depth > 10:
        return "<max-depth>"
    if seen is None:
        seen = set()
    if isinstance(value, int) and not isinstance(value, bool) and 0 <= value < len(payload):
        if value in seen:
            return "<cycle>"
        return _resolve_nuxt_ref(payload, payload[value], depth + 1, seen | {value})
    if isinstance(value, dict):
        return {
            str(k): _resolve_nuxt_ref(payload, v, depth + 1, set(seen))
            for k, v in value.items()
        }
    if isinstance(value, list):
        return [
            _resolve_nuxt_ref(payload, v, depth + 1, set(seen))
            for v in value[:200]
        ]
    return value


def _keyword_signals(value: Any, path: str = "") -> list[dict[str, Any]]:
    keywords = ("region", "offer", "leaflet", "flyer", "prospekt", "marketing")
    result: list[dict[str, Any]] = []
    if isinstance(value, dict):
        for key, nested in value.items():
            child = f"{path}/{key}"
            if any(word in key.casefold() for word in keywords):
                if isinstance(nested, (str, int, float, bool)) or nested is None:
                    result.append({"path": child, "value": nested})
            result.extend(_keyword_signals(nested, child))
    elif isinstance(value, list):
        for i, nested in enumerate(value[:200]):
            result.extend(_keyword_signals(nested, f"{path}/{i}"))
    return result


def lidl_store_region_evidence(
    payload: Any,
    store_id: str,
    known_offer_regions: set[str],
) -> dict[str, Any]:
    found = resolve_nuxt_store_object(payload, store_id)
    if found is None or not isinstance(payload, list):
        return {
            "store_object_found": False,
            "candidate_offer_regions": [],
            "signals": [],
        }
    raw = found["raw_ref_object"]
    resolved = _resolve_nuxt_ref(payload, raw)
    signals = _keyword_signals(resolved)
    candidate_codes: set[str] = set()
    for signal in signals:
        value = str(signal.get("value") or "")
        for token in re.findall(r"\b\d{1,3}\b", value):
            if token in known_offer_regions:
                candidate_codes.add(token)
    return {
        "store_object_found": True,
        "payload_index": found["payload_index"],
        "resolved_store_preview": resolved,
        "signals": signals[:120],
        "candidate_offer_regions": sorted(candidate_codes),
    }


def _variant_summary(
    client: httpx.Client,
    root: Path,
    stamp: str,
    flyer: dict[str, Any],
    ordinal: int,
) -> dict[str, Any]:
    response = client.get(str(flyer["flyerJson"]), headers={"Accept": "application/json"})
    response.raise_for_status()
    raw = save_bytes(
        root,
        stamp,
        f"lidl-current-variant-{ordinal:02d}",
        response.content,
        "json",
    )
    detail = response.json()
    products = lidl_root_products(detail)
    linked_ids = lidl_linked_product_ids(detail)
    root_ids = {str(x["id"]) for x in products if x.get("id")}
    regions = [
        {"code": str(x.get("code")), "type": x.get("type")}
        for x in flyer.get("regions") or []
        if isinstance(x, dict)
    ]
    return {
        "id": flyer.get("id"),
        "offer_start_date": flyer.get("offerStartDate"),
        "offer_end_date": flyer.get("offerEndDate"),
        "regions": regions,
        "flyer_json": flyer.get("flyerJson"),
        "pdf_url": flyer.get("pdfUrl"),
        "raw": raw,
        "root_product_count": len(products),
        "root_products_with_price": sum(x.get("price") is not None for x in products),
        "root_products_with_title": sum(bool(x.get("title")) for x in products),
        "root_products_with_brand": sum(bool(x.get("brand")) for x in products),
        "linked_product_id_count": len(linked_ids),
        "root_link_id_overlap": len(root_ids & linked_ids),
        "signature": lidl_product_signature(products),
        "product_samples": products[:10],
    }


def run_lidl(client: httpx.Client, root: Path, stamp: str) -> dict[str, Any]:
    store = client.get(LIDL_STORE_URL)
    store.raise_for_status()
    store_raw = save_bytes(root, stamp, "lidl-store-husener-44", store.content, "html")

    payload_url = find_lidl_payload_url(store.text)
    payload = None
    payload_raw = None
    payload_text = ""
    if payload_url:
        response = client.get(payload_url, headers={"Accept": "application/json"})
        response.raise_for_status()
        payload_raw = save_bytes(root, stamp, "lidl-store-payload", response.content, "json")
        payload_text = response.text
        try:
            payload = response.json()
        except Exception:
            payload = None

    overview = client.get(
        LIDL_OVERVIEW_URL,
        params={"client_locale": "lidl/de-DE"},
        headers={"Accept": "application/json"},
    )
    overview.raise_for_status()
    overview_raw = save_bytes(root, stamp, "lidl-overview", overview.content, "json")
    flyers = extract_lidl_flyers(overview.json())
    today = datetime.now(timezone.utc).date()
    current = select_current_lidl_variants(flyers, today)

    variant_summaries: list[dict[str, Any]] = []
    for i, flyer in enumerate(current, 1):
        try:
            variant_summaries.append(_variant_summary(client, root, stamp, flyer, i))
        except Exception as exc:
            variant_summaries.append(
                {
                    "id": flyer.get("id"),
                    "offer_start_date": flyer.get("offerStartDate"),
                    "offer_end_date": flyer.get("offerEndDate"),
                    "regions": [
                        {"code": str(x.get("code")), "type": x.get("type")}
                        for x in flyer.get("regions") or []
                        if isinstance(x, dict)
                    ],
                    "flyer_json": flyer.get("flyerJson"),
                    "pdf_url": flyer.get("pdfUrl"),
                    "root_product_count": 0,
                    "root_products_with_price": 0,
                    "root_products_with_title": 0,
                    "root_products_with_brand": 0,
                    "linked_product_id_count": 0,
                    "root_link_id_overlap": 0,
                    "signature": "ERROR",
                    "product_samples": [],
                    "error": f"{type(exc).__name__}: {exc}"[:1000],
                }
            )
    known_offer_regions = {
        region["code"]
        for variant in variant_summaries
        for region in variant["regions"]
        if region.get("type") == "offer_region"
    }

    region_evidence = (
        lidl_store_region_evidence(payload, "DE06664", known_offer_regions)
        if payload is not None
        else {
            "store_object_found": False,
            "candidate_offer_regions": [],
            "signals": [],
        }
    )

    signature_counts: dict[str, int] = {}
    for variant in variant_summaries:
        signature = variant["signature"]
        if signature == "ERROR":
            continue
        signature_counts[signature] = signature_counts.get(signature, 0) + 1

    candidate_regions = region_evidence.get("candidate_offer_regions") or []
    if len(candidate_regions) == 1:
        binding_status = "SOURCE_CANDIDATE_FOUND_NOT_YET_PRODUCTION_BOUND"
    else:
        binding_status = "PENDING"

    return {
        "store_url": str(store.url),
        "store_raw": store_raw,
        "store_payload_url": payload_url,
        "store_payload_raw": payload_raw,
        "store_object_number": extract_lidl_store_id(payload_text),
        "overview_raw": overview_raw,
        "flyer_count": len(flyers),
        "current_variant_count": len(current),
        "current_variants": variant_summaries,
        "max_root_product_count": max((x["root_product_count"] for x in variant_summaries), default=0),
        "max_structured_price_count": max((x["root_products_with_price"] for x in variant_summaries), default=0),
        "max_root_link_overlap": max((x["root_link_id_overlap"] for x in variant_summaries), default=0),
        "unique_product_signatures": len(signature_counts),
        "signature_group_sizes": sorted(signature_counts.values(), reverse=True),
        "store_region_evidence": region_evidence,
        "offer_region_binding_status": binding_status,
        "pillow_required": False,
    }


def main() -> int:
    settings = get_settings()
    root = settings.raw_snapshot_dir / "targeted-shadow"
    root.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    with httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(60.0, connect=15.0),
        headers={
            "User-Agent": USER_AGENT,
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
            "Cache-Control": "no-cache",
        },
    ) as client:
        report = {
            "schema_version": 2,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "mode": "shadow_only_no_db_writes",
            "netto": run_netto(client, root, stamp),
            "lidl": run_lidl(client, root, stamp),
        }

    report["gates"] = {
        "netto_two_publications": report["netto"]["viewer_count"] == 2,
        "netto_structured_hotspot_products_found": report["netto"]["structured_product_total"] >= 5,
        "netto_explicit_current_validity_found": bool(
            report["netto"]["current_publications_by_explicit_range"]
        ),
        "lidl_store_de06664": report["lidl"]["store_object_number"] == "DE06664",
        "lidl_current_variants_at_least_18": report["lidl"]["current_variant_count"] >= 18,
        "lidl_root_products_over_120": report["lidl"]["max_root_product_count"] >= 120,
        "lidl_structured_prices_over_100": report["lidl"]["max_structured_price_count"] >= 100,
        "lidl_root_link_overlap_over_100": report["lidl"]["max_root_link_overlap"] >= 100,
        "pillow_not_required": report["lidl"]["pillow_required"] is False,
    }
    report["all_gates_pass"] = all(report["gates"].values())

    path = root / f"{stamp}-phase5g-targeted-structured-v02.json"
    path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    print("NETTO_SUMMARY="+json.dumps({
        "viewer_count": report["netto"]["viewer_count"],
        "structured_product_total": report["netto"]["structured_product_total"],
        "current_publications_by_explicit_range": report["netto"]["current_publications_by_explicit_range"],
        "publications": [
            {
                "slug": x["slug"],
                "pages": x["page_count"],
                "structured_products": x["structured_product_count"],
                "start_signals": x["store_start_signals"],
                "validity_ranges": x["explicit_validity_ranges"],
                "current": x["current_by_explicit_range"],
            }
            for x in report["netto"]["publications"]
        ],
    }, ensure_ascii=False, sort_keys=True))
    print("LIDL_SUMMARY="+json.dumps({
        "store": report["lidl"]["store_object_number"],
        "current_variants": report["lidl"]["current_variant_count"],
        "max_root_products": report["lidl"]["max_root_product_count"],
        "max_structured_prices": report["lidl"]["max_structured_price_count"],
        "max_root_link_overlap": report["lidl"]["max_root_link_overlap"],
        "unique_signatures": report["lidl"]["unique_product_signatures"],
        "signature_group_sizes": report["lidl"]["signature_group_sizes"],
        "region_candidates": report["lidl"]["store_region_evidence"].get("candidate_offer_regions"),
        "binding_status": report["lidl"]["offer_region_binding_status"],
    }, ensure_ascii=False, sort_keys=True))
    print("GATES="+json.dumps(report["gates"], sort_keys=True))
    print("ALL_GATES_PASS="+str(report["all_gates_pass"]).lower())
    print(f"REPORT_PATH={path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
