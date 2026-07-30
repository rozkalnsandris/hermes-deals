from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import html
import json
from pathlib import Path
import re
from typing import Any
from urllib.parse import unquote, urljoin, urlparse
from uuid import uuid4

import httpx

from app.parsers.aldi_nord import AldiNordParserContext, parse_aldi_nord_html
from app.settings import get_settings


USER_AGENT = "HermesDeals/phase5g-structured-shadow"
ALDI_URLS = {
    "current": "https://www.aldi-nord.de/angebote.html",
    "preview": "https://www.aldi-nord.de/angebote-vorschau.html",
}
LIDL_STORE_URL = "https://www.lidl.de/s/de-DE/filialen/dortmund/husener-strasse-44/"
LIDL_OVERVIEW_URL = "https://endpoints.leaflets.schwarz/v4/overview"
NETTO_STORE_URL = "https://www.netto-online.de/filialen/dortmund/rauschenbuschstr-1/5659"
NETTO_STORE_ID = "5659"


def save_raw(output_dir: Path, stamp: str, label: str, content: bytes, suffix: str) -> dict[str, Any]:
    digest = sha256(content).hexdigest()
    path = output_dir / f"{stamp}-{label}-{digest[:12]}.{suffix}"
    path.write_bytes(content)
    return {"path": str(path), "sha256": digest, "bytes": len(content)}


def extract_netto_direct_viewers(text: str, store_id: str = NETTO_STORE_ID) -> dict[str, str]:
    decoded = html.unescape(unquote(text))
    urls = set(
        re.findall(
            r"https?://wochenprospekt\.netto-online\.de/[A-Za-z0-9_-]+/[^\s\"'<>]*",
            decoded,
            flags=re.I,
        )
    )
    for href in re.findall(r'href=["\']([^"\']+)["\']', text, flags=re.I):
        value = html.unescape(unquote(href))
        urls.update(
            re.findall(
                r"https?://wochenprospekt\.netto-online\.de/[A-Za-z0-9_-]+/[^\s\"'<>]*",
                value,
                flags=re.I,
            )
        )

    result: dict[str, str] = {}
    for raw_url in urls:
        parsed = urlparse(raw_url)
        parts = [x for x in parsed.path.split("/") if x]
        if not parts:
            continue
        slug = parts[0]
        result[slug] = f"https://wochenprospekt.netto-online.de/{slug}/?storeid={store_id}"
    return dict(sorted(result.items()))


def extract_netto_group_slug(viewer_html: str) -> str | None:
    match = re.search(r'(?i)"groupSlug"\s*:\s*"([^"]+)"', viewer_html)
    return match.group(1) if match else None


def nearby_date_signals(store_html: str, slug: str) -> list[str]:
    positions = [m.start() for m in re.finditer(re.escape(slug), store_html)]
    dates: set[str] = set()
    for pos in positions:
        block = html.unescape(store_html[max(0, pos - 2500): pos + 2500])
        dates.update(re.findall(r"\b\d{2}\.\d{2}\.\d{2,4}\b", block))
    return sorted(dates)


def summarize_publitas(payload: dict[str, Any]) -> dict[str, Any]:
    config = payload.get("config") if isinstance(payload.get("config"), dict) else {}
    spreads = payload.get("spreads") if isinstance(payload.get("spreads"), list) else []
    pages = []
    hotspot_types: dict[str, int] = {}
    for spread in spreads:
        if not isinstance(spread, dict):
            continue
        for page in spread.get("pages") or []:
            if isinstance(page, str):
                pages.append(page)
        for hotspot in spread.get("hotspots") or []:
            if isinstance(hotspot, dict):
                kind = str(hotspot.get("type") or "unknown")
                hotspot_types[kind] = hotspot_types.get(kind, 0) + 1
    return {
        "publication_id": config.get("publicationId"),
        "slug": config.get("slug"),
        "title": config.get("publicationTitle"),
        "download_pdf_url": config.get("downloadPdfUrl"),
        "spread_count": len(spreads),
        "page_count": len(pages),
        "hotspot_types": dict(sorted(hotspot_types.items())),
        "page_paths": pages,
    }


def extract_lidl_store_id(payload_text: str) -> str | None:
    matches = re.findall(r"\bDE\d{5}\b", payload_text)
    unique = list(dict.fromkeys(matches))
    return unique[0] if unique else None


def extract_lidl_flyers(payload: Any) -> list[dict[str, Any]]:
    found: list[dict[str, Any]] = []

    def walk(value: Any) -> None:
        if isinstance(value, dict):
            if value.get("flyerJson") and value.get("offerStartDate") and value.get("offerEndDate"):
                found.append(value)
            for nested in value.values():
                walk(nested)
        elif isinstance(value, list):
            for nested in value:
                walk(nested)

    walk(payload)
    unique: dict[str, dict[str, Any]] = {}
    for flyer in found:
        key = str(flyer.get("id") or flyer.get("flyerJson"))
        unique[key] = flyer
    return list(unique.values())


def select_lidl_period_variants(
    flyers: list[dict[str, Any]],
    on_date: date,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    """Select the active and immediately following Aktionsprospekt windows."""
    windows: dict[tuple[date, date], list[dict[str, Any]]] = {}
    for flyer in flyers:
        if flyer.get("name") != "Aktionsprospekt" or not flyer.get("flyerJson"):
            continue
        try:
            start = date.fromisoformat(str(flyer.get("offerStartDate")))
            end = date.fromisoformat(str(flyer.get("offerEndDate")))
        except ValueError:
            continue
        if start > end:
            continue
        windows.setdefault((start, end), []).append(flyer)

    active_windows = [
        window
        for window in windows
        if window[0] <= on_date <= window[1]
    ]
    if not active_windows:
        return [], []

    current_window = max(
        active_windows,
        key=lambda window: (window[0], window[1]),
    )
    next_windows = [
        window
        for window in windows
        if window[0] > current_window[1]
    ]
    next_window = (
        min(next_windows, key=lambda window: (window[0], window[1]))
        if next_windows
        else None
    )
    return (
        windows[current_window],
        [] if next_window is None else windows[next_window],
    )


def summarize_lidl_detail(payload: dict[str, Any]) -> dict[str, Any]:
    flyer = payload.get("flyer") if isinstance(payload.get("flyer"), dict) else {}
    pages = flyer.get("pages") if isinstance(flyer.get("pages"), list) else []
    product_details: list[dict[str, Any]] = []
    link_keys: set[str] = set()
    price_field_hits = 0
    geometry_field_hits = 0

    for page in pages:
        if not isinstance(page, dict):
            continue
        links = page.get("links") if isinstance(page.get("links"), list) else []
        for link in links:
            if not isinstance(link, dict):
                continue
            link_keys.update(map(str, link.keys()))
            if any(k in link for k in ("position", "left", "top", "width", "height", "x", "y")):
                geometry_field_hits += 1
            details = link.get("productDetails")
            if isinstance(details, dict):
                product_details.append(details)
                if any("price" in str(k).casefold() for k in details):
                    price_field_hits += 1

    unique_ids = {
        str(item.get("productId"))
        for item in product_details
        if item.get("productId") is not None
    }
    unique_titles = {
        str(item.get("title")).strip()
        for item in product_details
        if str(item.get("title") or "").strip()
    }
    return {
        "page_count": len(pages),
        "linked_product_detail_count": len(product_details),
        "unique_product_ids": len(unique_ids),
        "unique_titles": len(unique_titles),
        "product_detail_price_field_hits": price_field_hits,
        "link_geometry_hits": geometry_field_hits,
        "link_keys": sorted(link_keys),
    }


def find_lidl_payload_url(store_html: str) -> str | None:
    matches = re.findall(r'["\']([^"\']*_payload\.json\?[^"\']+)["\']', store_html)
    if matches:
        return urljoin(LIDL_STORE_URL, html.unescape(matches[0]))
    bid = re.search(r"\bbid_[0-9_]+\b", store_html)
    if bid:
        return urljoin(LIDL_STORE_URL, f"_payload.json?{bid.group(0)}")
    return None


def aldi_shadow(client: httpx.Client, output_dir: Path, stamp: str) -> dict[str, Any]:
    result: dict[str, Any] = {}
    sets: dict[str, set[str]] = {}

    for scope, url in ALDI_URLS.items():
        response = client.get(url)
        response.raise_for_status()
        saved = save_raw(output_dir, stamp, f"aldi-{scope}", response.content, "html")
        context = AldiNordParserContext(
            snapshot_id=uuid4(),
            source_url=str(response.url),
            collected_at=datetime.now(timezone.utc),
        )
        offers = parse_aldi_nord_html(response.content, context)
        ids = {offer.source_offer_id for offer in offers}
        sets[scope] = ids
        result[scope] = {
            "url": str(response.url),
            "raw": saved,
            "offer_count": len(offers),
            "distinct_source_offer_ids": len(ids),
            "image_count": sum(offer.source_image_url is not None for offer in offers),
            "package_count": sum(bool(offer.package_text_raw) for offer in offers),
            "validity_count": sum(
                offer.valid_from is not None and offer.valid_until is not None
                for offer in offers
            ),
            "validity_windows": sorted({
                (str(offer.valid_from), str(offer.valid_until))
                for offer in offers
            }),
        }

    current = sets["current"]
    preview = sets["preview"]
    result["overlap"] = {
        "overlap": len(current & preview),
        "current_only": len(current - preview),
        "preview_only": len(preview - current),
    }
    return result


def netto_shadow(client: httpx.Client, output_dir: Path, stamp: str) -> dict[str, Any]:
    store = client.get(NETTO_STORE_URL)
    store.raise_for_status()
    store_raw = save_raw(output_dir, stamp, "netto-store-5659", store.content, "html")
    viewers = extract_netto_direct_viewers(store.text)
    publications: list[dict[str, Any]] = []

    for slug, viewer_url in viewers.items():
        viewer = client.get(viewer_url)
        viewer.raise_for_status()
        viewer_raw = save_raw(output_dir, stamp, f"netto-viewer-{slug}", viewer.content, "html")
        group = extract_netto_group_slug(viewer.text)
        if not group:
            raise RuntimeError(f"Publitas groupSlug missing for {slug}")
        api_url = f"https://api.publitas.com/v1/groups/{group}/publications/{slug}.json"
        api_response = client.get(api_url, headers={"Accept": "application/json"})
        api_response.raise_for_status()
        api_raw = save_raw(output_dir, stamp, f"netto-publitas-{slug}", api_response.content, "json")
        summary = summarize_publitas(api_response.json())
        summary.update({
            "viewer_url": viewer_url,
            "viewer_raw": viewer_raw,
            "group_slug": group,
            "public_api_url": api_url,
            "public_api_raw": api_raw,
            "store_nearby_date_signals": nearby_date_signals(store.text, slug),
        })
        publications.append(summary)

    return {
        "store_id": NETTO_STORE_ID,
        "store_url": str(store.url),
        "store_raw": store_raw,
        "viewer_count": len(viewers),
        "publications": sorted(publications, key=lambda x: str(x.get("slug"))),
    }


def lidl_shadow(client: httpx.Client, output_dir: Path, stamp: str) -> dict[str, Any]:
    store = client.get(LIDL_STORE_URL)
    store.raise_for_status()
    store_raw = save_raw(output_dir, stamp, "lidl-store-husener-44", store.content, "html")

    payload_url = find_lidl_payload_url(store.text)
    payload_text = ""
    payload_raw = None
    if payload_url:
        response = client.get(payload_url)
        if response.status_code == 200:
            payload_text = response.text
            payload_raw = save_raw(output_dir, stamp, "lidl-store-payload", response.content, "json")

    overview = client.get(
        LIDL_OVERVIEW_URL,
        params={"client_locale": "lidl/de-DE"},
        headers={"Accept": "application/json"},
    )
    overview.raise_for_status()
    overview_raw = save_raw(output_dir, stamp, "lidl-overview", overview.content, "json")
    flyers = extract_lidl_flyers(overview.json())

    current, next_week = select_lidl_period_variants(
        flyers,
        datetime.now(timezone.utc).date(),
    )
    national = next(
        (
            flyer for flyer in current
            if any(
                isinstance(region, dict)
                and str(region.get("code")) == "0"
                and region.get("type") == "national"
                for region in flyer.get("regions") or []
            )
        ),
        None,
    )
    if national is None:
        raise RuntimeError("Active Lidl national Aktionsprospekt was not found")

    detail = client.get(national["flyerJson"], headers={"Accept": "application/json"})
    detail.raise_for_status()
    detail_raw = save_raw(output_dir, stamp, "lidl-current-national-detail", detail.content, "json")
    detail_summary = summarize_lidl_detail(detail.json())

    def variant(flyer: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": flyer.get("id"),
            "regions": [
                {"code": region.get("code"), "type": region.get("type")}
                for region in flyer.get("regions") or []
                if isinstance(region, dict)
            ],
            "flyer_json": flyer.get("flyerJson"),
            "pdf_url": flyer.get("pdfUrl"),
        }

    return {
        "store_url": str(store.url),
        "store_raw": store_raw,
        "store_payload_url": payload_url,
        "store_payload_raw": payload_raw,
        "store_object_number": extract_lidl_store_id(payload_text),
        "overview_raw": overview_raw,
        "flyer_count": len(flyers),
        "current_variant_count": len(current),
        "next_variant_count": len(next_week),
        "current_variants": [variant(x) for x in current],
        "national_current": variant(national),
        "national_detail_raw": detail_raw,
        "national_detail": detail_summary,
        "offer_region_binding": None,
        "offer_region_binding_status": "PENDING",
    }


def run_shadow() -> dict[str, Any]:
    settings = get_settings()
    output_dir = settings.raw_snapshot_dir / "structured-shadow"
    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    headers = {
        "User-Agent": USER_AGENT,
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
    }
    with httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(45.0, connect=10.0),
        headers=headers,
    ) as client:
        report = {
            "schema_version": 1,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "mode": "shadow_only_no_db_writes",
            "aldi_nord": aldi_shadow(client, output_dir, stamp),
            "netto": netto_shadow(client, output_dir, stamp),
            "lidl": lidl_shadow(client, output_dir, stamp),
        }

    report["gates"] = {
        "aldi_current_min_240": report["aldi_nord"]["current"]["offer_count"] >= 240,
        "aldi_preview_min_280": report["aldi_nord"]["preview"]["offer_count"] >= 280,
        "aldi_current_preview_disjoint": report["aldi_nord"]["overlap"]["overlap"] == 0,
        "netto_two_publications_resolved": report["netto"]["viewer_count"] >= 2,
        "netto_public_api_resolved": all(
            pub.get("publication_id") and pub.get("page_count", 0) > 0
            for pub in report["netto"]["publications"]
        ),
        "lidl_store_id_de06664": report["lidl"]["store_object_number"] == "DE06664",
        "lidl_current_variants_discovered": report["lidl"]["current_variant_count"] >= 18,
        "lidl_national_product_links_over_100": (
            report["lidl"]["national_detail"]["linked_product_detail_count"] >= 100
        ),
        "lidl_structured_price_gap_explicit": (
            report["lidl"]["national_detail"]["product_detail_price_field_hits"] == 0
        ),
    }
    report["all_gates_pass"] = all(report["gates"].values())
    report_path = output_dir / f"{stamp}-phase5g-structured-shadow.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report


def main() -> int:
    report = run_shadow()
    print(json.dumps(report, ensure_ascii=False, indent=2))
    print(f"REPORT_PATH={report['report_path']}")
    return 0 if report["all_gates_pass"] else 2


if __name__ == "__main__":
    raise SystemExit(main())
