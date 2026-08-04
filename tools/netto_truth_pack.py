#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass, asdict
from datetime import date, datetime, timezone
from hashlib import sha256
from http.cookiejar import CookieJar
from html import unescape
from pathlib import Path
from urllib.error import HTTPError, URLError
from urllib.parse import parse_qsl, quote, unquote, urlencode, urljoin, urlparse, urlunparse
from urllib.request import HTTPCookieProcessor, HTTPRedirectHandler, Request, build_opener
import csv
import json
import os
import re
import shutil
import subprocess
import sys
import time


USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36 "
    "HermesDeals-Netto-TruthPack/3.0"
)
VIEWER_HOST = "wochenprospekt.netto-online.de"
VIEW_ASSET_BASE = "https://view.publitas.com"
DATE_RANGE_RE = re.compile(
    r"(?P<d1>\d{1,2})\.(?P<m1>\d{1,2})\.(?:(?P<y1>\d{2,4}))?"
    r"\s*(?:-|–|—|bis)\s*"
    r"(?P<d2>\d{1,2})\.(?P<m2>\d{1,2})\.(?P<y2>\d{2,4})",
    re.I,
)
FULL_DATE_RANGE_RE = re.compile(
    r"(?P<d1>\d{1,2})\.(?P<m1>\d{1,2})\.(?P<y1>\d{2,4})"
    r"\s*(?:-|–|—|bis)\s*"
    r"(?P<d2>\d{1,2})\.(?P<m2>\d{1,2})\.(?P<y2>\d{2,4})",
    re.I,
)
PRICE_RE = re.compile(r"(?<!\d)(\d{1,3})[,.](\d{2})(?!\d)")
PACKAGE_RE = re.compile(
    r"(?<!\w)(?:(\d+)\s*[x×]\s*)?"
    r"(\d+(?:[,.]\d+)?)\s*(kg|g|l|ml|cl|stück|stk\.?|rollen?|tabs?|beutel|dosen?)\b",
    re.I,
)
UNIT_PRICE_RE = re.compile(
    r"(?:1\s*(kg|l|100\s*g|100\s*ml)|Grundpreis)[^0-9]{0,20}"
    r"(\d{1,3}[,.]\d{2})",
    re.I,
)
DEPOSIT_RE = re.compile(
    r"(?:zzgl\.?|zuzüglich)\s*(\d{1,3}[,.]\d{2})\s*€?\s*Pfand",
    re.I,
)


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def digest(data: bytes) -> str:
    return sha256(data).hexdigest()


def atomic_write(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + f".tmp-{os.getpid()}")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def atomic_json(path: Path, value: object) -> None:
    atomic_write(
        path,
        (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8"),
    )


def safe_name(value: str) -> str:
    value = re.sub(r"[^A-Za-z0-9._-]+", "-", value).strip("-")
    return value[:120] or "unknown"


def build_corpus_key(
    *,
    store_id: str,
    publication: str,
    source_sha: str,
    selected_range: dict[str, str] | None,
) -> str:
    normalized_store_id = str(store_id).strip()
    if not re.fullmatch(r"[0-9]{1,20}", normalized_store_id):
        raise ValueError(f"invalid Netto store ID for corpus key: {store_id!r}")
    if not re.fullmatch(r"[0-9a-f]{64}", source_sha):
        raise ValueError("source SHA256 must contain exactly 64 lowercase hex characters")
    if selected_range:
        valid_from = str(selected_range.get("valid_from") or "")
        valid_until = str(selected_range.get("valid_until") or "")
        if not (
            re.fullmatch(r"\d{4}-\d{2}-\d{2}", valid_from)
            and re.fullmatch(r"\d{4}-\d{2}-\d{2}", valid_until)
        ):
            raise ValueError("selected validity range must use YYYY-MM-DD dates")
        key_prefix = valid_from.replace("-", "") + "-" + valid_until.replace("-", "")
    else:
        key_prefix = "unknown-unknown"
    return (
        f"{key_prefix}-store{normalized_store_id}-"
        f"{safe_name(publication)}-{source_sha[:12]}"
    )


def decoded_variants(text: str) -> list[str]:
    variants: list[str] = []
    current = text
    for _ in range(5):
        for candidate in (
            current,
            unescape(current),
            current.replace("\\/", "/"),
            unquote(current),
        ):
            if candidate not in variants:
                variants.append(candidate)
        next_value = unquote(unescape(current.replace("\\/", "/")))
        if next_value == current:
            break
        current = next_value
    return variants


def canonical_viewer_url(url: str, store_id: str) -> str:
    parsed = urlparse(unescape(url).replace("\\/", "/"))
    if parsed.scheme not in {"http", "https"} or parsed.netloc.casefold() != VIEWER_HOST:
        raise ValueError(f"not a Netto viewer URL: {url}")
    parts = [part for part in re.sub(r"/+", "/", parsed.path).split("/") if part]
    if not parts:
        raise ValueError(f"viewer path has no publication slug: {url}")
    path = "/" + parts[0] + "/"
    return urlunparse(("https", VIEWER_HOST, path, "", urlencode({"storeid": store_id}), ""))


def extract_viewer_urls(text: str, store_id: str) -> list[str]:
    found: set[str] = set()
    pattern = re.compile(
        r"https?://wochenprospekt\.netto-online\.de/"
        r"[A-Za-z0-9._~%+-]+/?(?:\?[^\"'<>\s\\]*)?",
        re.I,
    )
    for variant in decoded_variants(text):
        for match in pattern.findall(variant):
            try:
                found.add(canonical_viewer_url(match.rstrip(".,);]"), store_id))
            except ValueError:
                continue
    return sorted(found)


def viewer_base_url(url: str) -> str:
    parsed = urlparse(url)
    path = parsed.path
    if not path.endswith("/"):
        path += "/"
    return urlunparse((parsed.scheme, parsed.netloc, path.rstrip("/"), "", "", ""))


def viewer_slug(url: str) -> str:
    parts = [part for part in urlparse(url).path.split("/") if part]
    return unquote(parts[0]) if parts else ""


def extract_reader_bootstrap(text: str) -> dict:
    anchors = [
        re.compile(r"\bvar\s+data\s*=\s*", re.I),
        re.compile(r"\blet\s+data\s*=\s*", re.I),
        re.compile(r"\bconst\s+data\s*=\s*", re.I),
    ]
    decoder = json.JSONDecoder()
    candidates: list[dict] = []
    for anchor in anchors:
        for match in anchor.finditer(text):
            pos = text.find("{", match.end())
            if pos < 0:
                continue
            try:
                payload, consumed = decoder.raw_decode(text[pos:])
            except json.JSONDecodeError:
                continue
            tail = text[pos + consumed : pos + consumed + 1000]
            if (
                isinstance(payload, dict)
                and "id" in payload
                and "slug" in payload
                and "cacheToken" in payload
                and "numPages" in payload
                and "Reader.Bootstrap.init" in tail
            ):
                candidates.append(payload)
    unique: dict[tuple, dict] = {}
    for item in candidates:
        key = (item.get("id"), item.get("slug"), item.get("cacheToken"))
        unique[key] = item
    if len(unique) != 1:
        raise ValueError(f"expected exactly one reader bootstrap object, found={len(unique)}")
    return next(iter(unique.values()))


def normalize_year(raw: str) -> int:
    year = int(raw)
    return year + 2000 if year < 100 else year


def extract_date_ranges(text: str) -> list[dict[str, str]]:
    ranges: set[tuple[str, str, str]] = set()
    for pattern in (FULL_DATE_RANGE_RE, DATE_RANGE_RE):
        for match in pattern.finditer(text):
            gd = match.groupdict()
            y2 = normalize_year(gd["y2"])
            y1 = normalize_year(gd["y1"]) if gd.get("y1") else y2
            try:
                start = date(y1, int(gd["m1"]), int(gd["d1"]))
                end = date(y2, int(gd["m2"]), int(gd["d2"]))
            except ValueError:
                continue
            if end < start:
                continue
            ranges.add((start.isoformat(), end.isoformat(), match.group(0)))
    return [
        {"valid_from": start, "valid_until": end, "matched_text": raw}
        for start, end, raw in sorted(ranges)
    ]


def plain_text_from_html(text: str) -> str:
    text = re.sub(r"(?is)<script\b.*?</script>", " ", text)
    text = re.sub(r"(?is)<style\b.*?</style>", " ", text)
    text = re.sub(r"(?s)<[^>]+>", "\n", text)
    text = unescape(text)
    lines = [re.sub(r"\s+", " ", line).strip() for line in text.splitlines()]
    return "\n".join(line for line in lines if line)


def source_signals(text: str) -> dict:
    return {
        "prices": sorted(set(".".join(x) for x in PRICE_RE.findall(text))),
        "packages": sorted(set(m.group(0) for m in PACKAGE_RE.finditer(text))),
        "unit_prices": sorted(set(m.group(0) for m in UNIT_PRICE_RE.finditer(text))),
        "deposits": sorted(set(m.group(0) for m in DEPOSIT_RE.finditer(text))),
        "date_ranges": extract_date_ranges(text),
        "app_markers": len(re.findall(r"\b(app|netto-app|coupon)\b", text, re.I)),
        "line_count": len(text.splitlines()),
    }


def with_query(url: str, params: dict[str, str] | None = None) -> str:
    if not params:
        return url
    parsed = urlparse(url)
    query = dict(parse_qsl(parsed.query, keep_blank_values=True))
    query.update({k: v for k, v in params.items() if v is not None})
    return urlunparse(
        (parsed.scheme, parsed.netloc, parsed.path, parsed.params, urlencode(query), parsed.fragment)
    )


def build_url(base: str, path: str, params: dict[str, str] | None = None) -> str:
    url = urljoin(base.rstrip("/") + "/", path.lstrip("/"))
    return with_query(url, params)


def resolve_asset_url(value: str, viewer_url: str) -> str:
    if value.startswith("http://") or value.startswith("https://"):
        return value
    if value.startswith("/screenshots"):
        parsed = urlparse(viewer_url)
        return urlunparse((parsed.scheme, parsed.netloc, value, "", "", ""))
    return urljoin(VIEW_ASSET_BASE + "/", value.lstrip("/"))


def header_value(headers: dict, name: str) -> str | None:
    wanted = name.casefold()
    for key, value in headers.items():
        if str(key).casefold() == wanted:
            return str(value)
    return None


@dataclass
class FetchRecord:
    label: str
    requested_url: str
    final_url: str | None
    status: int | None
    content_type: str | None
    bytes: int
    sha256: str | None
    path: str | None
    fetched_at: str
    error: str | None
    headers_path: str | None


class Fetcher:
    def __init__(self, root: Path, timeout: int = 60, retries: int = 3):
        self.root = root
        self.timeout = timeout
        self.retries = retries
        self.jar = CookieJar()
        self.opener = build_opener(HTTPCookieProcessor(self.jar), HTTPRedirectHandler())
        self.records: list[FetchRecord] = []

    def fetch(
        self,
        url: str,
        *,
        label: str,
        relative_path: Path,
        accept: str = "*/*",
        required: bool = True,
        max_bytes: int = 300_000_000,
    ) -> bytes | None:
        error: Exception | None = None
        for attempt in range(1, self.retries + 1):
            try:
                request = Request(
                    url,
                    headers={
                        "User-Agent": USER_AGENT,
                        "Accept": accept,
                        "Accept-Language": "de-DE,de;q=0.9,en;q=0.6",
                        "Cache-Control": "no-cache",
                    },
                )
                with self.opener.open(request, timeout=self.timeout) as response:
                    data = response.read(max_bytes + 1)
                    if len(data) > max_bytes:
                        raise ValueError(f"response exceeds max_bytes={max_bytes}")
                    final_url = response.geturl()
                    status = int(getattr(response, "status", 200))
                    content_type = response.headers.get_content_type()
                    target = self.root / relative_path
                    atomic_write(target, data)
                    headers = dict(response.headers.items())
                    headers_path = target.with_suffix(target.suffix + ".headers.json")
                    atomic_json(
                        headers_path,
                        {
                            "requested_url": url,
                            "final_url": final_url,
                            "status": status,
                            "headers": headers,
                            "fetched_at": utc_now(),
                        },
                    )
                    record = FetchRecord(
                        label=label,
                        requested_url=url,
                        final_url=final_url,
                        status=status,
                        content_type=content_type,
                        bytes=len(data),
                        sha256=digest(data),
                        path=str(relative_path),
                        fetched_at=utc_now(),
                        error=None,
                        headers_path=str(headers_path.relative_to(self.root)),
                    )
                    self.records.append(record)
                    print(
                        f"FETCH_OK|{label}|status={status}|bytes={len(data)}|"
                        f"sha256={record.sha256}|path={relative_path}",
                        flush=True,
                    )
                    return data
            except (HTTPError, URLError, TimeoutError, OSError, ValueError) as exc:
                error = exc
                if attempt < self.retries:
                    time.sleep(attempt * 2)
        self.records.append(
            FetchRecord(
                label=label,
                requested_url=url,
                final_url=None,
                status=getattr(error, "code", None),
                content_type=None,
                bytes=0,
                sha256=None,
                path=None,
                fetched_at=utc_now(),
                error=f"{type(error).__name__}: {error}",
                headers_path=None,
            )
        )
        print(
            f"FETCH_FAILED|{label}|required={str(required).lower()}|"
            f"error={type(error).__name__}: {error}",
            flush=True,
        )
        if required:
            raise RuntimeError(f"{label} fetch failed: {url}: {error}")
        return None

    def fetch_paginated_json(
        self,
        url: str,
        *,
        label: str,
        relative_dir: Path,
        max_pages: int = 100,
    ) -> list:
        combined: list = []
        next_page: str | None = "1"
        seen: set[str] = set()
        page_no = 0
        while next_page:
            if next_page in seen:
                raise RuntimeError(f"{label} pagination loop detected at page={next_page}")
            seen.add(next_page)
            page_no += 1
            if page_no > max_pages:
                raise RuntimeError(f"{label} exceeds max_pages={max_pages}")
            page_url = with_query(url, {"page": next_page})
            rel = relative_dir / f"page-{page_no:03d}.json"
            data = self.fetch(
                page_url,
                label=f"{label}:page:{page_no}",
                relative_path=rel,
                accept="application/json",
                required=True,
                max_bytes=40_000_000,
            )
            assert data is not None
            try:
                payload = json.loads(data.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise RuntimeError(f"{label} invalid JSON page={page_no}: {exc}") from exc
            if isinstance(payload, list):
                combined.extend(payload)
            elif isinstance(payload, dict):
                for key in ("results", "items", "spreads", "hotspots"):
                    if isinstance(payload.get(key), list):
                        combined.extend(payload[key])
                        break
                else:
                    raise RuntimeError(f"{label} unsupported JSON object keys={sorted(payload)}")
            else:
                raise RuntimeError(f"{label} unsupported JSON type={type(payload).__name__}")
            headers_doc = json.loads(
                (self.root / rel.with_suffix(rel.suffix + ".headers.json")).read_text(
                    encoding="utf-8"
                )
            )
            next_page = header_value(headers_doc.get("headers") or {}, "X-Next-Page")
            if next_page in {"", "null", "None"}:
                next_page = None
        atomic_json(self.root / relative_dir / "combined.json", combined)
        return combined


def run_pdftotext(pdf: Path, output: Path) -> dict:
    if not shutil.which("pdftotext"):
        return {"available": False, "success": False, "error": "pdftotext_missing"}
    proc = subprocess.run(
        ["pdftotext", "-layout", str(pdf), str(output)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=False,
    )
    return {
        "available": True,
        "success": proc.returncode == 0 and output.exists(),
        "returncode": proc.returncode,
        "stderr": proc.stderr[-4000:],
    }


def spread_page_numbers(spread: dict, fallback_start: int) -> tuple[list[int], int]:
    pages = [p for p in (spread.get("pages") or []) if isinstance(p, dict)]
    explicit: list[int] = []
    for page in pages:
        raw = page.get("number")
        try:
            explicit.append(int(raw))
        except (TypeError, ValueError):
            explicit = []
            break
    if explicit and len(explicit) == len(pages):
        return explicit, max(explicit) + 1
    original = spread.get("originalPageNumbers")
    if isinstance(original, list) and len(original) == len(pages):
        try:
            values = [int(x) for x in original]
            return values, max(values) + 1
        except (TypeError, ValueError):
            pass
    values = list(range(fallback_start, fallback_start + len(pages)))
    return values, fallback_start + len(pages)


def assign_hotspot_page(
    page_numbers: list[int],
    position: object,
) -> tuple[int | None, str]:
    if len(page_numbers) == 1:
        return page_numbers[0], "single_reader_page"
    if len(page_numbers) == 2 and isinstance(position, dict):
        try:
            left = float(position.get("left"))
        except (TypeError, ValueError):
            left = None
        if left is not None:
            return (
                page_numbers[0] if left < 0.5 else page_numbers[1],
                "two_page_spread_left_coordinate",
            )
    return None, "spread_level_hotspot_requires_coordinate_review"


def choose_page_image(page: dict) -> tuple[str | None, str | None]:
    images = page.get("images")
    if isinstance(images, dict):
        for size in ("at1600", "at2000", "at1200", "at1000", "at800"):
            value = images.get(size)
            if isinstance(value, str) and value:
                return value, f"images.{size}"
    screenshots = page.get("screenshots")
    if isinstance(screenshots, dict):
        for size in ("at1600", "at2000", "at1200", "at1000", "at800"):
            value = screenshots.get(size)
            if isinstance(value, str) and value:
                return value, f"screenshots.{size}"
    return None, None


def product_detail_url(base_url: str, product_id: int) -> str:
    return build_url(base_url, f"product/{product_id}.json")


def write_inventory_tsv(path: Path, rows: list[dict]) -> None:
    fields = [
        "publication_slug", "product_id", "hotspot_id", "page_number",
        "page_assignment_method", "title", "description", "brand", "price",
        "discounted_price", "webshop_identifier", "webshop_url",
        "availability", "detail_source", "detail_error",
    ]
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=fields, delimiter="\t", extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def capture_publication(
    fetcher: Fetcher,
    *,
    viewer_url: str,
    viewer_index: int,
    viewer_bytes: bytes,
    bootstrap: dict,
    store_id: str,
    root: Path,
) -> dict:
    publication = str(bootstrap["slug"])
    group = str(bootstrap.get("groupSlug") or "")
    pub_dir = root / "publications" / safe_name(publication)
    pub_dir.mkdir(parents=True, exist_ok=True)
    atomic_write(pub_dir / "viewer.html", viewer_bytes)
    bootstrap_bytes = (
        json.dumps(bootstrap, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    atomic_write(pub_dir / "reader-bootstrap.json", bootstrap_bytes)

    base_url = viewer_base_url(viewer_url)
    cache_token = str(bootstrap.get("cacheToken") or "")
    if not cache_token:
        raise RuntimeError(f"{publication}: reader cacheToken missing")

    spreads_url = build_url(base_url, "spreads.json", {"version": cache_token})
    spreads = fetcher.fetch_paginated_json(
        spreads_url,
        label=f"{publication}:spreads",
        relative_dir=Path("publications") / safe_name(publication) / "spreads-raw",
    )
    if not spreads:
        raise RuntimeError(f"{publication}: reader returned zero spreads")

    page_rows: list[dict] = []
    hotspot_rows: list[dict] = []
    inventory_by_product: dict[int, dict] = {}
    next_fallback_page = 1

    for spread_index, spread in enumerate(spreads, start=1):
        if not isinstance(spread, dict):
            raise RuntimeError(f"{publication}: spread {spread_index} is not an object")
        pages = [p for p in (spread.get("pages") or []) if isinstance(p, dict)]
        page_numbers, next_fallback_page = spread_page_numbers(spread, next_fallback_page)
        if len(page_numbers) != len(pages):
            raise RuntimeError(f"{publication}: page number mapping mismatch at spread={spread_index}")

        for offset, (page, page_number) in enumerate(zip(pages, page_numbers)):
            image_value, image_field = choose_page_image(page)
            if not image_value:
                raise RuntimeError(
                    f"{publication}: no usable page image at spread={spread_index}, page={page_number}"
                )
            image_url = resolve_asset_url(image_value, viewer_url)
            rel = (
                Path("publications") / safe_name(publication)
                / "pages" / f"{page_number:03d}.jpg"
            )
            image_bytes = fetcher.fetch(
                image_url,
                label=f"{publication}:page_image:{page_number}",
                relative_path=rel,
                accept="image/avif,image/webp,image/apng,image/*,*/*;q=0.8",
                required=True,
                max_bytes=30_000_000,
            )
            assert image_bytes is not None
            page_rows.append(
                {
                    "page_number": page_number,
                    "spread_index": spread_index,
                    "spread_page_offset": offset,
                    "page_id": page.get("id"),
                    "original_page_number": page.get("number"),
                    "image_field": image_field,
                    "image_url": image_url,
                    "image_path": str(rel),
                    "image_sha256": digest(image_bytes),
                    "text": page.get("text"),
                    "background_type": page.get("backgroundType"),
                }
            )

        page_key = "-".join(str(x) for x in page_numbers)
        hotspots_url = build_url(
            base_url,
            f"page/{page_key}/hotspots_data.json",
            {"version": cache_token},
        )
        hotspots = fetcher.fetch_paginated_json(
            hotspots_url,
            label=f"{publication}:hotspots:{page_key}",
            relative_dir=(
                Path("publications") / safe_name(publication)
                / "hotspots-raw" / f"pages-{page_key}"
            ),
        )

        for hotspot in hotspots:
            if not isinstance(hotspot, dict):
                continue
            hrow = dict(hotspot)
            hrow["_spread_index"] = spread_index
            hrow["_reader_pages"] = page_numbers
            hotspot_rows.append(hrow)
            if hotspot.get("type") not in {"product", "dynamicProduct", "generatedProduct"}:
                continue
            products = hotspot.get("products") or []
            for product in products:
                if not isinstance(product, dict):
                    continue
                try:
                    product_id = int(product.get("id"))
                except (TypeError, ValueError):
                    continue
                detail = dict(product)
                detail_source = "hotspot_inline"
                detail_error = None
                if product.get("stub") is True or str(product.get("stub")).casefold() == "true":
                    rel = (
                        Path("publications") / safe_name(publication)
                        / "products" / f"{product_id}.json"
                    )
                    raw = fetcher.fetch(
                        product_detail_url(base_url, product_id),
                        label=f"{publication}:product:{product_id}",
                        relative_path=rel,
                        accept="application/json",
                        required=False,
                        max_bytes=5_000_000,
                    )
                    if raw is not None:
                        try:
                            loaded = json.loads(raw.decode("utf-8"))
                            if isinstance(loaded, dict):
                                detail = loaded
                                detail_source = "reader_product_endpoint"
                            else:
                                detail_error = "product_endpoint_non_object"
                        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                            detail_error = f"{type(exc).__name__}: {exc}"
                    else:
                        detail_error = "product_endpoint_unavailable"

                assigned_page, assignment_method = assign_hotspot_page(
                    page_numbers,
                    hotspot.get("position"),
                )
                row = {
                    "publication_slug": publication,
                    "product_id": product_id,
                    "hotspot_id": hotspot.get("id"),
                    "page_number": assigned_page,
                    "page_assignment_method": assignment_method,
                    "title": detail.get("title"),
                    "description": detail.get("description"),
                    "brand": detail.get("brand"),
                    "price": detail.get("price"),
                    "discounted_price": detail.get("discountedPrice"),
                    "webshop_identifier": detail.get("webshopIdentifier"),
                    "webshop_url": detail.get("webshopUrl"),
                    "availability": detail.get("availability"),
                    "detail_source": detail_source,
                    "detail_error": detail_error,
                    "raw_detail": detail,
                    "position": hotspot.get("position"),
                    "reader_pages": page_numbers,
                }
                current = inventory_by_product.get(product_id)
                if current is None or (
                    current.get("detail_error") and not row.get("detail_error")
                ):
                    inventory_by_product[product_id] = row

    page_rows.sort(key=lambda row: row["page_number"])
    atomic_json(pub_dir / "pages.json", page_rows)
    atomic_json(pub_dir / "spreads.json", spreads)
    atomic_json(pub_dir / "hotspots.json", hotspot_rows)
    inventory = [inventory_by_product[k] for k in sorted(inventory_by_product)]
    atomic_json(pub_dir / "publication-inventory.json", inventory)
    write_inventory_tsv(pub_dir / "publication-inventory.tsv", inventory)

    expected_pages = int(bootstrap.get("numPages") or 0)
    actual_page_numbers = [row["page_number"] for row in page_rows]
    if len(page_rows) != expected_pages:
        raise RuntimeError(
            f"{publication}: page_count mismatch bootstrap={expected_pages} captured={len(page_rows)}"
        )
    if sorted(set(actual_page_numbers)) != list(range(1, expected_pages + 1)):
        raise RuntimeError(
            f"{publication}: page number sequence is not exact 1..{expected_pages}"
        )

    config = bootstrap.get("config") or {}
    pdf_rel = None
    pdf_sha = None
    pdf_text_rel = None
    pdf_text_result = {"available": False, "success": False, "error": "pdf_not_exposed"}
    download_pdf_url = config.get("downloadPdfUrl")
    if isinstance(download_pdf_url, str) and download_pdf_url.strip():
        pdf_url = resolve_asset_url(download_pdf_url, viewer_url)
        pdf_rel = Path("publications") / safe_name(publication) / "source.pdf"
        pdf_bytes = fetcher.fetch(
            pdf_url,
            label=f"{publication}:pdf",
            relative_path=pdf_rel,
            accept="application/pdf,*/*;q=0.8",
            required=True,
            max_bytes=500_000_000,
        )
        assert pdf_bytes is not None
        if not pdf_bytes.startswith(b"%PDF-"):
            raise RuntimeError(f"{publication}: PDF response lacks PDF signature")
        pdf_sha = digest(pdf_bytes)
        pdf_text_path = pub_dir / "source.txt"
        pdf_text_result = run_pdftotext(root / pdf_rel, pdf_text_path)
        if pdf_text_result.get("success"):
            pdf_text_rel = str(pdf_text_path.relative_to(root))

    signals: list[dict] = []
    for source_name, source_text in (
        ("viewer_html", viewer_bytes.decode("utf-8", errors="replace")),
        ("reader_bootstrap", bootstrap_bytes.decode("utf-8", errors="replace")),
    ):
        for item in extract_date_ranges(source_text):
            signals.append({"source": source_name, **item})
    if pdf_text_rel:
        pdf_text = (root / pdf_text_rel).read_text(encoding="utf-8", errors="replace")
        for item in extract_date_ranges(pdf_text):
            signals.append({"source": "pdf_native_text", **item})

    unique_ranges = sorted({(x["valid_from"], x["valid_until"]) for x in signals})
    validity_state = (
        "single_agreed_range" if len(unique_ranges) == 1
        else "no_range" if not unique_ranges
        else "conflicting_or_multiple_ranges"
    )
    selected_range = (
        {"valid_from": unique_ranges[0][0], "valid_until": unique_ranges[0][1]}
        if len(unique_ranges) == 1
        else None
    )
    source_sha = pdf_sha or digest(bootstrap_bytes)
    corpus_key = build_corpus_key(
        store_id=store_id,
        publication=publication,
        source_sha=source_sha,
        selected_range=selected_range,
    )

    summary = {
        "schema_version": 2,
        "strategy": "netto_n25_custom_domain_reader_bootstrap_v3",
        "viewer_index": viewer_index,
        "viewer_url": viewer_url,
        "reader_base_url": base_url,
        "group_slug": group,
        "group_id": bootstrap.get("groupId"),
        "publication_slug": publication,
        "publication_id": bootstrap.get("id"),
        "publication_title": config.get("publicationTitle"),
        "publication_original_title": config.get("publicationOriginalTitle"),
        "collection_title": bootstrap.get("collectionTitle"),
        "account_name": bootstrap.get("accountName"),
        "page_count": len(page_rows),
        "spread_count": len(spreads),
        "hotspot_count": len(hotspot_rows),
        "product_hotspot_ref_count": len(inventory),
        "product_detail_count": sum(1 for row in inventory if not row.get("detail_error")),
        "product_detail_missing_count": sum(1 for row in inventory if row.get("detail_error")),
        "pdf_exposed": bool(download_pdf_url),
        "pdf_path": str(pdf_rel) if pdf_rel else None,
        "pdf_sha256": pdf_sha,
        "pdf_text_path": pdf_text_rel,
        "pdf_text_result": pdf_text_result,
        "validity_signals": signals,
        "unique_validity_ranges": [
            {"valid_from": start, "valid_until": end} for start, end in unique_ranges
        ],
        "validity_state": validity_state,
        "selected_validity": selected_range,
        "publication_json_kind": "reader_bootstrap",
        "publication_json_sha256": digest(bootstrap_bytes),
        "reader_bootstrap_sha256": digest(bootstrap_bytes),
        "viewer_html_sha256": digest(viewer_bytes),
        "source_identity_sha256": source_sha,
        "corpus_key": corpus_key,
    }
    atomic_json(pub_dir / "summary.json", summary)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--store-url", required=True)
    parser.add_argument("--store-id", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    root = args.output.resolve()
    root.mkdir(parents=True, exist_ok=True)
    fetcher = Fetcher(root)
    selection_url = args.store_url + (
        "&stores_id=" + quote(args.store_id)
        if "?" in args.store_url
        else "?stores_id=" + quote(args.store_id)
    )
    store_bytes = fetcher.fetch(
        selection_url,
        label="store_page",
        relative_path=Path("store.html"),
        accept="text/html,application/xhtml+xml",
        required=True,
        max_bytes=20_000_000,
    )
    assert store_bytes is not None
    store_text = store_bytes.decode("utf-8", errors="replace")
    store_visible = plain_text_from_html(store_text)
    atomic_write(root / "store-visible.txt", (store_visible + "\n").encode("utf-8"))
    atomic_json(root / "store-signals.json", source_signals(store_visible))
    if args.store_id not in store_text and args.store_id not in store_visible:
        raise RuntimeError("captured store page does not prove selected store ID")

    viewers = extract_viewer_urls(store_text, args.store_id)
    atomic_json(root / "viewer-urls.json", viewers)
    if not viewers:
        raise RuntimeError("store page exposes no direct Netto weekly-prospect viewer URLs")

    publication_summaries: list[dict] = []
    unresolved_viewers: list[dict] = []
    seen_publications: set[tuple[int, str]] = set()

    for index, viewer_url in enumerate(viewers, start=1):
        slug = viewer_slug(viewer_url)
        viewer_rel = Path("viewers") / f"{index:02d}-{safe_name(slug)}.html"
        viewer_bytes = fetcher.fetch(
            viewer_url,
            label=f"viewer:{index}:{slug}",
            relative_path=viewer_rel,
            accept="text/html,application/xhtml+xml",
            required=True,
            max_bytes=25_000_000,
        )
        assert viewer_bytes is not None
        viewer_text = viewer_bytes.decode("utf-8", errors="replace")
        try:
            bootstrap = extract_reader_bootstrap(viewer_text)
        except ValueError as exc:
            unresolved_viewers.append(
                {"viewer_url": viewer_url, "reason": "reader_bootstrap_unresolved", "error": str(exc)}
            )
            continue

        reasons: list[str] = []
        if str(bootstrap.get("slug") or "").casefold() != slug.casefold():
            reasons.append("viewer_slug_mismatch")
        try:
            publication_id = int(bootstrap.get("id"))
        except (TypeError, ValueError):
            publication_id = 0
            reasons.append("publication_id_invalid")
        try:
            num_pages = int(bootstrap.get("numPages"))
        except (TypeError, ValueError):
            num_pages = 0
            reasons.append("num_pages_invalid")
        if num_pages <= 0:
            reasons.append("num_pages_not_positive")
        account_name = str(bootstrap.get("accountName") or "")
        if "netto" not in account_name.casefold():
            reasons.append("account_name_not_netto")
        if reasons:
            unresolved_viewers.append(
                {
                    "viewer_url": viewer_url,
                    "reason": "reader_bootstrap_identity_failed",
                    "identity_failures": reasons,
                    "bootstrap_identity": {
                        "id": bootstrap.get("id"),
                        "slug": bootstrap.get("slug"),
                        "groupSlug": bootstrap.get("groupSlug"),
                        "accountName": bootstrap.get("accountName"),
                        "numPages": bootstrap.get("numPages"),
                    },
                }
            )
            continue

        identity = (publication_id, str(bootstrap["slug"]))
        if identity in seen_publications:
            unresolved_viewers.append(
                {
                    "viewer_url": viewer_url,
                    "reason": "duplicate_publication_after_canonicalization",
                    "identity": list(identity),
                }
            )
            continue
        seen_publications.add(identity)
        publication_summaries.append(
            capture_publication(
                fetcher,
                viewer_url=viewer_url,
                viewer_index=index,
                viewer_bytes=viewer_bytes,
                bootstrap=bootstrap,
                store_id=args.store_id,
                root=root,
            )
        )

    atomic_json(root / "unresolved-viewers.json", unresolved_viewers)
    atomic_json(root / "publication-summaries.json", publication_summaries)
    atomic_json(root / "fetch-records.json", [asdict(x) for x in fetcher.records])
    atomic_json(
        root / "cookies.json",
        [
            {
                "name": cookie.name,
                "value_sha256": digest(cookie.value.encode("utf-8")),
                "domain": cookie.domain,
                "path": cookie.path,
                "secure": cookie.secure,
                "expires": cookie.expires,
            }
            for cookie in fetcher.jar
        ],
    )
    if not publication_summaries:
        raise RuntimeError("no Netto reader publication resolved")
    if unresolved_viewers:
        raise RuntimeError(
            f"{len(unresolved_viewers)} viewer(s) unresolved; see unresolved-viewers.json"
        )

    manifest = {
        "schema_version": 2,
        "strategy": "netto_n25_store_aware_reader_truth_pack_v3",
        "created_at": utc_now(),
        "store_id": args.store_id,
        "store_url": args.store_url,
        "selection_url": selection_url,
        "store_sha256": digest(store_bytes),
        "viewer_count": len(viewers),
        "resolved_publication_count": len(publication_summaries),
        "publications": publication_summaries,
        "fetch_record_count": len(fetcher.records),
        "production_write_performed": False,
        "db_write_performed": False,
        "review_write_performed": False,
        "ocr_performed": False,
    }
    atomic_json(root / "manifest.json", manifest)
    print(json.dumps(manifest, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
