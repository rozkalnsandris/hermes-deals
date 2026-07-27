from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable
from urllib.parse import urlparse

import httpx

API_BASE = "https://endpoints.leaflets.schwarz/v4"
OVERVIEW_LOCALE = "lidl/de-DE"
_PRICE_LIKE_RE = re.compile(r"(?<!\d)(?:\d{1,3}[.,]\d{2}|\d{1,3}[.,]-|\d{1,3}\s*€)(?!\d)", re.IGNORECASE)


def _safe_json(response: httpx.Response) -> tuple[Any | None, str | None]:
    try:
        return response.json(), None
    except Exception as exc:  # keep discovery useful on non-JSON responses
        return None, f"{type(exc).__name__}: {exc}"[:500]


def _flyer_object(payload: Any) -> dict[str, Any] | None:
    if isinstance(payload, dict):
        flyer = payload.get("flyer")
        if isinstance(flyer, dict):
            return flyer
        # Be tolerant if a market returns the flyer object directly.
        if isinstance(payload.get("pages"), list):
            return payload
    return None


def _dict_items(value: Any) -> list[tuple[str | None, dict[str, Any]]]:
    """Normalize list- or object-shaped API collections without guessing their semantics."""
    if isinstance(value, list):
        return [(None, item) for item in value if isinstance(item, dict)]
    if isinstance(value, dict):
        return [(str(key), item) for key, item in value.items() if isinstance(item, dict)]
    return []


def _product_sample(product: dict[str, Any], *, collection_key: str | None = None) -> dict[str, Any]:
    result: dict[str, Any] = {
        "collection_key": collection_key,
        "keys": sorted(product.keys())[:100],
        "id": product.get("id") or product.get("productId"),
        "name": product.get("name") or product.get("title"),
        "brand": product.get("brand"),
        "price": product.get("price"),
        "currencyText": product.get("currencyText"),
        "currencySymbol": product.get("currencySymbol"),
        "image": product.get("image"),
        "url": product.get("url") or product.get("canonicalUrl"),
    }
    return {key: value for key, value in result.items() if value is not None}


def _iter_page_links(page: dict[str, Any]) -> Iterable[dict[str, Any]]:
    links = page.get("links")
    if isinstance(links, list):
        yield from (item for item in links if isinstance(item, dict))
    elif isinstance(links, dict):
        yield from (item for item in links.values() if isinstance(item, dict))


def summarize_flyer_payload(payload: Any) -> dict[str, Any]:
    flyer = _flyer_object(payload)
    if flyer is None:
        top_keys = sorted(payload.keys())[:80] if isinstance(payload, dict) else []
        return {
            "has_flyer": False,
            "top_level_keys": top_keys,
            "page_count": 0,
            "product_collection_type": None,
            "product_count": 0,
            "linked_product_detail_count": 0,
            "linked_product_detail_unique_count": 0,
            "related_flyer_count": 0,
            "flyer": {},
            "page_samples": [],
            "product_samples": [],
            "linked_product_samples": [],
        }

    pages = flyer.get("pages") if isinstance(flyer.get("pages"), list) else []
    products_raw = flyer.get("products")
    products = _dict_items(products_raw)
    related = _dict_items(flyer.get("relatedFlyers"))
    # Some markets expose related flyers as scalar/list values; preserve the old count behavior too.
    if not related and isinstance(flyer.get("relatedFlyers"), list):
        related_count = len(flyer["relatedFlyers"])
    elif not related and isinstance(flyer.get("relatedFlyers"), dict):
        related_count = len(flyer["relatedFlyers"])
    else:
        related_count = len(related)

    if isinstance(products_raw, dict):
        product_collection_type = "object"
    elif isinstance(products_raw, list):
        product_collection_type = "array"
    elif products_raw is None:
        product_collection_type = None
    else:
        product_collection_type = type(products_raw).__name__

    metadata_fields = (
        "id",
        "uuid",
        "name",
        "title",
        "locale",
        "countryCode",
        "category",
        "subcategory",
        "startDate",
        "endDate",
        "offerStartDate",
        "offerEndDate",
        "status",
        "isActive",
        "discoverable",
        "pdfUrl",
        "hiResPdfUrl",
        "fileSize",
    )
    metadata = {key: flyer.get(key) for key in metadata_fields if flyer.get(key) is not None}

    page_samples: list[dict[str, Any]] = []
    linked_product_samples: list[dict[str, Any]] = []
    linked_product_detail_count = 0
    linked_product_ids: set[str] = set()

    for page in pages:
        if not isinstance(page, dict):
            continue
        links = list(_iter_page_links(page))
        keywords = page.get("keyWords")
        alt_text = page.get("altText")

        for link in links:
            details = link.get("productDetails")
            if not isinstance(details, dict):
                continue
            linked_product_detail_count += 1
            product_id = details.get("productId") or details.get("id")
            if product_id is not None:
                linked_product_ids.add(str(product_id))
            if len(linked_product_samples) < 12:
                sample = _product_sample(details)
                sample.update(
                    {
                        "page_number": page.get("number"),
                        "link_icon": link.get("icon"),
                        "link_label": link.get("label") or link.get("title"),
                    }
                )
                linked_product_samples.append({key: value for key, value in sample.items() if value is not None})

        if len(page_samples) < 8:
            keyword_text = keywords if isinstance(keywords, str) else ""
            page_samples.append(
                {
                    "id": page.get("id"),
                    "number": page.get("number"),
                    "type": page.get("type"),
                    "pageType": page.get("pageType"),
                    "image": page.get("image"),
                    "zoom": page.get("zoom"),
                    "thumbnail": page.get("thumbnail"),
                    "keyWords_chars": len(keyword_text),
                    "keyWords_preview": keyword_text[:360] if keyword_text else None,
                    "price_like_tokens": _PRICE_LIKE_RE.findall(keyword_text)[:20],
                    "altText_chars": len(alt_text) if isinstance(alt_text, str) else 0,
                    "altText_preview": alt_text[:300] if isinstance(alt_text, str) else None,
                    "links_count": len(links),
                    "links_with_product_details": sum(
                        1 for link in links if isinstance(link.get("productDetails"), dict)
                    ),
                }
            )

    product_samples = [_product_sample(product, collection_key=key) for key, product in products[:12]]

    return {
        "has_flyer": True,
        "top_level_keys": sorted(payload.keys())[:80] if isinstance(payload, dict) else [],
        "page_count": len(pages),
        "product_collection_type": product_collection_type,
        "product_count": len(products),
        "linked_product_detail_count": linked_product_detail_count,
        "linked_product_detail_unique_count": len(linked_product_ids),
        "related_flyer_count": related_count,
        "flyer": metadata,
        "page_samples": page_samples,
        "product_samples": product_samples,
        "linked_product_samples": linked_product_samples,
    }


def _save_response(output_dir: Path, stamp: str, label: str, response: httpx.Response) -> dict[str, Any]:
    content = response.content
    sha256 = hashlib.sha256(content).hexdigest()
    content_type = response.headers.get("content-type", "")
    suffix = ".json" if "json" in content_type.lower() else ".bin"
    path = output_dir / f"{stamp}-lidl-api-{label}-{sha256[:12]}{suffix}"
    path.write_bytes(content)
    return {
        "path": str(path),
        "sha256": sha256,
        "bytes": len(content),
        "content_type": content_type,
    }


def inspect_lidl_api(
    *,
    discovery_report_path: Path,
    output_dir: Path,
    user_agent: str,
) -> dict[str, Any]:
    discovery = json.loads(discovery_report_path.read_text(encoding="utf-8"))
    leaflet_keys = [str(value) for value in discovery.get("leaflet_keys", []) if isinstance(value, str)]
    if not leaflet_keys:
        raise ValueError("Discovery report contains no Lidl leaflet keys")

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    headers = {
        "User-Agent": user_agent,
        "Accept": "application/json,text/plain,*/*",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
        "Cache-Control": "no-cache",
        "Origin": "https://www.lidl.de",
        "Referer": "https://www.lidl.de/",
    }

    overview: dict[str, Any] = {}
    flyer_probes: list[dict[str, Any]] = []

    with httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(45.0, connect=10.0),
        headers=headers,
    ) as client:
        # Overview is useful for future weekly slug discovery, but it is not a hard gate yet.
        overview_url = f"{API_BASE}/overview"
        try:
            response = client.get(overview_url, params={"client_locale": OVERVIEW_LOCALE})
            saved = _save_response(output_dir, stamp, "overview-de-DE", response)
            payload, json_error = _safe_json(response)
            overview = {
                "url": str(response.url),
                "status": response.status_code,
                "saved": saved,
                "json_error": json_error,
                "top_level_keys": sorted(payload.keys())[:80] if isinstance(payload, dict) else [],
            }
            if isinstance(payload, dict):
                categories = payload.get("categories")
                overview["category_count"] = len(categories) if isinstance(categories, list) else None
        except Exception as exc:
            overview = {"url": overview_url, "error": f"{type(exc).__name__}: {exc}"[:1000]}

        for index, key in enumerate(leaflet_keys, start=1):
            url = f"{API_BASE}/flyer"
            attempts: list[dict[str, Any]] = []
            successful_payload: Any | None = None
            successful_response: httpx.Response | None = None

            # Start with the exact call shape observed in the viewer; only add public client/version
            # query params if the minimal form does not yield a flyer JSON object.
            param_sets = [
                {"flyer_identifier": key},
                {"flyer_identifier": key, "client": "lidl", "version": "4"},
            ]
            for attempt_no, params in enumerate(param_sets, start=1):
                try:
                    response = client.get(url, params=params)
                    label = f"flyer-{index}-attempt-{attempt_no}"
                    saved = _save_response(output_dir, stamp, label, response)
                    payload, json_error = _safe_json(response)
                    summary = summarize_flyer_payload(payload)
                    attempt = {
                        "url": str(response.url),
                        "status": response.status_code,
                        "saved": saved,
                        "json_error": json_error,
                        "summary": summary,
                    }
                    attempts.append(attempt)
                    if response.is_success and summary["has_flyer"]:
                        successful_payload = payload
                        successful_response = response
                        break
                except Exception as exc:
                    attempts.append(
                        {
                            "url": url,
                            "params": params,
                            "error": f"{type(exc).__name__}: {exc}"[:1000],
                        }
                    )

            final_summary = summarize_flyer_payload(successful_payload) if successful_payload is not None else {}
            flyer_probes.append(
                {
                    "leaflet_key": key,
                    "success": successful_response is not None,
                    "status": successful_response.status_code if successful_response is not None else None,
                    "final_url": str(successful_response.url) if successful_response is not None else None,
                    "summary": final_summary,
                    "attempts": attempts,
                }
            )

    successful = [probe for probe in flyer_probes if probe["success"]]
    page_rich = [probe for probe in successful if int(probe.get("summary", {}).get("page_count", 0)) > 0]
    root_product_rich = [probe for probe in successful if int(probe.get("summary", {}).get("product_count", 0)) > 0]
    linked_product_rich = [
        probe for probe in successful if int(probe.get("summary", {}).get("linked_product_detail_count", 0)) > 0
    ]

    report: dict[str, Any] = {
        "schema_version": 2,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": "direct_public_leaflet_api_structure_probe",
        "playwright_used": False,
        "api_base": API_BASE,
        "api_host": urlparse(API_BASE).hostname,
        "discovery_report": str(discovery_report_path),
        "leaflet_keys": leaflet_keys,
        "overview": overview,
        "flyer_probes": flyer_probes,
        "successful_flyer_probes": len(successful),
        "flyers_with_pages": len(page_rich),
        "flyers_with_root_products": len(root_product_rich),
        "flyers_with_linked_product_details": len(linked_product_rich),
        # Backwards-compatible field name from v0.2.5, now correctly handling object-shaped products.
        "flyers_with_products": len(root_product_rich),
        "gate": {
            "api_host_expected": urlparse(API_BASE).hostname == "endpoints.leaflets.schwarz",
            "has_successful_flyer_json": bool(successful),
            "has_page_data": bool(page_rich),
            "has_any_structured_product_data": bool(root_product_rich or linked_product_rich),
        },
    }
    report_path = output_dir / f"{stamp}-lidl-api-structure-analysis.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report
