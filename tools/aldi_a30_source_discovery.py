from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import html
import json
from pathlib import Path
import re
import time
from typing import Any, Iterable
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit, urlunsplit


MODE = "ALDI_A30_SOURCE_DISCOVERY_V04"
OFFICIAL_OVERVIEW_URL = "https://www.aldi-nord.de/prospekte.html"
OFFICIAL_HOSTS = {"www.aldi-nord.de", "aldi-nord.de"}
MAGAZINE_HOST = "magazine.aldi-nord.de"
IPAPER_HOST = "ipaper.ipapercms.dk"
SOURCE_HOSTS = {MAGAZINE_HOST, IPAPER_HOST}
DETAILS = {
    "current": {
        "path": "/prospekte/aldi-aktuell.html",
        "heading": r"aldi\s+aktuell",
        "date_tokens": ("03.08.2026", "3.8.2026", "03.08", "3.8"),
        "path_tokens": ("03-08", "03_08", "2026cw32"),
    },
    "preview": {
        "path": "/prospekte/aldi-vorschau.html",
        "heading": r"aldi\s+vorschau",
        "date_tokens": ("10.08.2026", "10.8.2026", "10.08", "10.8"),
        "path_tokens": ("10-08", "10_08", "2026cw33"),
    },
}
SENSITIVE_QUERY_KEYS = {
    "token",
    "signature",
    "sig",
    "policy",
    "key-pair-id",
    "x-amz-signature",
    "x-amz-credential",
    "x-amz-security-token",
}
SAFE_HEADERS = {
    "cache-control",
    "content-length",
    "content-type",
    "etag",
    "last-modified",
    "server",
    "x-ip-server",
    "x-ip-partnerversion",
    "x-ip-buildversion",
    "x-ip-assemblyversion",
}


class DiscoveryError(RuntimeError):
    pass


def redact_url(url: str) -> str:
    try:
        parts = urlsplit(url)
    except ValueError:
        return "<invalid-url>"
    query = []
    for key, value in parse_qsl(parts.query, keep_blank_values=True):
        if key.lower() in SENSITIVE_QUERY_KEYS:
            value = "<redacted>"
        query.append((key, value))
    return urlunsplit((parts.scheme, parts.netloc, parts.path, urlencode(query), parts.fragment))


def safe_absolute_url(base_url: str, value: object) -> str | None:
    if not isinstance(value, str):
        return None
    candidate = html.unescape(value).strip().replace("\\/", "/")
    if not candidate or candidate.startswith(("#", "javascript:", "data:", "mailto:", "tel:")):
        return None
    try:
        absolute = urljoin(base_url, candidate)
        parts = urlsplit(absolute)
    except (TypeError, ValueError):
        return None
    if parts.scheme not in {"http", "https"} or not parts.netloc:
        return None
    return absolute


def extract_urls(text: str, base_url: str) -> tuple[set[str], list[str]]:
    if not text:
        return set(), []
    variants = {
        text,
        html.unescape(text),
        text.replace("\\/", "/"),
        text.replace("\\u002F", "/").replace("\\u002f", "/"),
        text.replace("\\u003A", ":").replace("\\u003a", ":"),
    }
    values: set[str] = set()
    rejected: list[str] = []
    patterns = (
        re.compile(r"https?://[^\s\"'<>\\]+", re.I),
        re.compile(r"(?<!:)//(?:magazine\.aldi-nord\.de|ipaper\.ipapercms\.dk)/[^\s\"'<>\\]+", re.I),
        re.compile(r"(?:magazine\.aldi-nord\.de|ipaper\.ipapercms\.dk)/[^\s\"'<>\\]+", re.I),
        re.compile(r'''(?:"|')((?:/|\.{1,2}/)[^"'<>\\\s]{2,500})(?:"|')'''),
    )
    for variant in variants:
        for pattern in patterns:
            for raw in pattern.findall(variant):
                if isinstance(raw, tuple):
                    raw = raw[0]
                normalized = raw.rstrip("),;")
                if normalized.startswith("//"):
                    normalized = "https:" + normalized
                elif normalized.lower().startswith((MAGAZINE_HOST + "/", IPAPER_HOST + "/")):
                    normalized = "https://" + normalized
                absolute = safe_absolute_url(base_url, normalized)
                if absolute is None:
                    rejected.append(str(raw)[:500])
                else:
                    values.add(absolute)
        for path in re.findall(r"(?<![A-Za-z0-9])(/aldi-nord/[^\s\"'<>\\]{8,500})", variant, re.I):
            clean = path.rstrip("),;")
            for host in (MAGAZINE_HOST, IPAPER_HOST):
                absolute = safe_absolute_url(base_url, f"https://{host}{clean}")
                if absolute:
                    values.add(absolute)
    return values, sorted(set(rejected))


def source_path(url: str) -> str | None:
    try:
        parts = urlsplit(url)
    except ValueError:
        return None
    if parts.netloc.lower() not in SOURCE_HOSTS:
        return None
    path = parts.path
    lowered = path.lower()
    if "/image.ashx" in lowered:
        path = path[: lowered.index("/image.ashx") + 1]
    elif any(
        lowered.endswith(suffix)
        for suffix in (
            ".js", ".css", ".png", ".jpg", ".jpeg", ".webp", ".svg",
            ".woff", ".woff2", ".ico", ".json", ".xml", ".map",
        )
    ):
        return None
    elif not path.endswith("/"):
        path += "/"
    if not path.lower().startswith("/aldi-nord/"):
        return None
    return "/" + path.strip("/") + "/"


def descriptor_from_path(path: str) -> dict[str, str]:
    normalized = "/" + path.strip("/") + "/"
    return {
        "source_path": normalized,
        "magazine_root": f"https://{MAGAZINE_HOST}{normalized}",
        "ipaper_root": f"https://{IPAPER_HOST}{normalized}",
    }


def add_urls(
    values: set[str],
    channels: dict[str, set[str]],
    urls: Iterable[object],
    channel: str,
    base_url: str,
    rejected: list[dict[str, str]],
) -> None:
    for value in urls:
        absolute = safe_absolute_url(base_url, value)
        if absolute is None:
            rejected.append({"channel": channel, "value": str(value)[:500], "reason": "invalid_url"})
            continue
        values.add(absolute)
        path = source_path(absolute)
        if path:
            channels[path].add(channel)


def safe_headers(headers: dict[str, str]) -> dict[str, str]:
    return {
        str(key).lower(): str(value)
        for key, value in headers.items()
        if str(key).lower() in SAFE_HEADERS
    }


def image_format(data: bytes) -> str | None:
    if data.startswith(b"\xff\xd8"):
        return "jpeg"
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "png"
    if data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "webp"
    return None


def image_template(old_first_image: str, old_ipaper_root: str, new_ipaper_root: str) -> str:
    old = urlsplit(old_first_image)
    old_root = urlsplit(old_ipaper_root)
    suffix = old.path
    if suffix.startswith(old_root.path):
        suffix = suffix[len(old_root.path):]
    suffix = suffix.lstrip("/") or "Image.ashx"
    query = []
    page_seen = False
    for key, value in parse_qsl(old.query, keep_blank_values=True):
        if key.lower() == "pagenumber":
            value = "{page}"
            page_seen = True
        query.append((key, value))
    if not page_seen:
        query.append(("PageNumber", "{page}"))
    return urljoin(new_ipaper_root, suffix) + "?" + urlencode(query)


def render_page_url(template: str, page_number: int) -> str:
    return template.replace("{page}", str(page_number)).replace("%7Bpage%7D", str(page_number))


def load_old_preview(plan_path: Path) -> dict[str, Any]:
    document = json.loads(plan_path.read_text(encoding="utf-8"))
    source = document.get("sources", {}).get("preview") if isinstance(document, dict) else None
    if not isinstance(source, dict):
        source = document.get("old_preview_source") if isinstance(document, dict) else None
    if not isinstance(source, dict):
        raise DiscoveryError("old preview source descriptor is missing")
    image_urls = source.get("image_urls")
    if source.get("page_count") != 41 or not isinstance(image_urls, list) or len(image_urls) != 41:
        raise DiscoveryError("old preview source descriptor does not contain exact 41 pages")
    for required in ("magazine_url", "ipaper_base_url"):
        if not isinstance(source.get(required), str):
            raise DiscoveryError(f"old preview source descriptor lacks {required}")
    return source


def request_snapshot(api: Any, url: str) -> tuple[dict[str, Any], str]:
    try:
        response = api.get(url, timeout=120_000, fail_on_status_code=False)
        body = response.body()
        content_type = str(response.headers.get("content-type") or "")
        textual = any(token in content_type.lower() for token in ("text/", "json", "javascript", "xml", "html"))
        text = body.decode("utf-8", errors="replace") if textual else ""
        return (
            {
                "requested_url": redact_url(url),
                "final_url": redact_url(response.url),
                "status": response.status,
                "content_type": content_type,
                "bytes": len(body),
                "sha256": sha256(body).hexdigest(),
                "headers": safe_headers(response.headers),
                "textual": textual,
            },
            text,
        )
    except Exception as exc:
        return ({"requested_url": redact_url(url), "error": f"{type(exc).__name__}: {exc}", "textual": False}, "")


def dismiss_consent(page: Any) -> None:
    for pattern in (
        re.compile(r"alle akzeptieren", re.I),
        re.compile(r"akzeptieren", re.I),
        re.compile(r"zustimmen", re.I),
        re.compile(r"einverstanden", re.I),
    ):
        try:
            locator = page.get_by_role("button", name=pattern)
            if locator.count():
                locator.first.click(timeout=2500)
                time.sleep(0.5)
                return
        except Exception:
            continue


def route_light(route: Any, request: Any) -> None:
    if request.resource_type in {"image", "media", "font"}:
        route.abort()
    else:
        route.continue_()


def overview_inventory(page: Any) -> dict[str, Any]:
    try:
        raw = page.evaluate(
            """
            () => ({
              title: document.title,
              body: (document.body?.innerText || '').replace(/\\s+/g, ' ').slice(0, 50000),
              controls: Array.from(document.querySelectorAll('a,button')).map(el => ({
                tag: el.tagName.toLowerCase(),
                text: (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 1000),
                href: el.closest('a[href]')?.href || el.href || '',
                aria: el.getAttribute('aria-label') || '',
                title: el.getAttribute('title') || '',
              })).filter(row => /prospekt|durchblättern|aktuell|vorschau|03\\.08|10\\.08/i.test(
                [row.text, row.href, row.aria, row.title].join(' ')
              )),
            })
            """
        )
    except Exception as exc:
        return {"error": f"{type(exc).__name__}: {exc}", "controls": []}
    controls = []
    for row in raw.get("controls") or []:
        href = safe_absolute_url(page.url, row.get("href"))
        controls.append({**row, "href": redact_url(href) if href else ""})
    return {
        "title": str(raw.get("title") or ""),
        "body_text_excerpt": str(raw.get("body") or ""),
        "controls": controls,
    }


def probe_descriptor(playwright: Any, descriptor: dict[str, Any], old_source: dict[str, Any], detail_url: str) -> dict[str, Any]:
    template = image_template(old_source["image_urls"][0], old_source["ipaper_base_url"], descriptor["ipaper_root"])
    api = playwright.request.new_context(
        extra_http_headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 Chrome/149 Safari/537.36",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
            "Referer": detail_url,
        }
    )
    try:
        magazine_probe, _ = request_snapshot(api, descriptor["magazine_root"])
        probes = []
        verified = True
        for page_number in (1, 2):
            url = render_page_url(template, page_number)
            try:
                response = api.get(
                    url,
                    headers={"Referer": detail_url, "Accept": "image/avif,image/webp,image/apng,image/*,*/*;q=0.8"},
                    timeout=120_000,
                    fail_on_status_code=False,
                )
                body = response.body()
                fmt = image_format(body)
                live = 200 <= response.status < 400 and fmt is not None and len(body) >= 10_000
                row = {
                    "page_number": page_number,
                    "requested_url": redact_url(url),
                    "final_url": redact_url(response.url),
                    "status": response.status,
                    "content_type": response.headers.get("content-type", ""),
                    "bytes": len(body),
                    "sha256": sha256(body).hexdigest(),
                    "image_format": fmt or "",
                    "live": live,
                    "headers": safe_headers(response.headers),
                }
            except Exception as exc:
                live = False
                row = {"page_number": page_number, "requested_url": redact_url(url), "live": False, "error": f"{type(exc).__name__}: {exc}"}
            probes.append(row)
            verified = verified and live
        return {
            **descriptor,
            "magazine_probe": magazine_probe,
            "image_template": redact_url(template),
            "page_probes": probes,
            "verified": verified,
        }
    finally:
        api.dispose()


def discover_label(
    playwright: Any,
    browser: Any,
    label: str,
    old_source: dict[str, Any],
    output_dir: Path,
    overview_url: str,
) -> dict[str, Any]:
    spec = DETAILS[label]
    detail_url = urljoin(overview_url, spec["path"])
    values: set[str] = set()
    channels: dict[str, set[str]] = defaultdict(set)
    rejected: list[dict[str, str]] = []
    render_requests: list[dict[str, Any]] = []
    render_responses: list[dict[str, Any]] = []
    render_errors: list[str] = []
    crashes: list[dict[str, str]] = []

    api = playwright.request.new_context(
        extra_http_headers={
            "User-Agent": "Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 Chrome/149 Safari/537.36",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.7",
        }
    )
    http_documents = []
    linked_assets = []
    try:
        detail_snapshot, detail_text = request_snapshot(api, detail_url)
        detail_snapshot["detail_path_verified"] = False
        try:
            detail_snapshot["detail_path_verified"] = (
                urlsplit(str(detail_snapshot.get("final_url") or detail_url)).path.rstrip("/") == spec["path"].rstrip("/")
            )
        except ValueError:
            pass
        title_match = re.search(r"<title[^>]*>(.*?)</title>", detail_text, re.I | re.S)
        static_title = html.unescape(title_match.group(1)).strip() if title_match else ""
        detail_snapshot["static_title"] = static_title
        detail_snapshot["identity_signal"] = bool(re.search(spec["heading"], f"{static_title} {detail_text}", re.I))
        http_documents.append(detail_snapshot)
        urls, invalid = extract_urls(detail_text, detail_url)
        rejected.extend({"channel": "detail_http_body", "value": item[:500], "reason": "invalid_url"} for item in invalid)
        add_urls(values, channels, urls, "detail_http_body", detail_url, rejected)

        assets = sorted(
            url for url in urls
            if (safe_absolute_url(detail_url, url) and urlsplit(url).netloc.lower() in OFFICIAL_HOSTS
                and urlsplit(url).path.lower().endswith((".js", ".json", ".xml")))
        )[:60]
        for asset_url in assets:
            row, body_text = request_snapshot(api, asset_url)
            linked_assets.append(row)
            if row.get("bytes", 0) <= 5_000_000:
                asset_urls, invalid = extract_urls(body_text, asset_url)
                rejected.extend({"channel": "linked_first_party_asset", "value": item[:500], "reason": "invalid_url"} for item in invalid)
                add_urls(values, channels, asset_urls, "linked_first_party_asset", asset_url, rejected)
    finally:
        api.dispose()

    context = browser.new_context(
        locale="de-DE",
        timezone_id="Europe/Berlin",
        viewport={"width": 1280, "height": 900},
        user_agent="Mozilla/5.0 (X11; Linux aarch64) AppleWebKit/537.36 Chrome/149 Safari/537.36",
    )
    context.route("**/*", route_light)

    def on_request(request: Any) -> None:
        render_requests.append({"method": request.method, "resource_type": request.resource_type, "url": redact_url(request.url)})
        add_urls(values, channels, [request.url], "render_request", detail_url, rejected)

    def on_response(response: Any) -> None:
        try:
            headers = response.all_headers()
        except Exception:
            headers = {}
        render_responses.append({"status": response.status, "url": redact_url(response.url), "headers": safe_headers(headers)})
        add_urls(values, channels, [response.url], "render_response", detail_url, rejected)

    context.on("request", on_request)
    context.on("response", on_response)
    page = context.new_page()
    page.on("crash", lambda: crashes.append({"event": "page_crash", "url": redact_url(page.url)}))
    screenshot_saved = False
    dom_rows: list[dict[str, Any]] = []
    try:
        try:
            page.goto(detail_url, wait_until="domcontentloaded", timeout=120_000)
        except Exception as exc:
            render_errors.append(f"goto: {type(exc).__name__}: {exc}")
        time.sleep(2.0)
        if not crashes:
            dismiss_consent(page)
            for fraction in (0.0, 0.5, 1.0, 0.25, 0.75):
                try:
                    page.evaluate("fraction => window.scrollTo(0, Math.max(0, (document.documentElement.scrollHeight-window.innerHeight)*fraction))", fraction)
                    time.sleep(0.35)
                except Exception as exc:
                    render_errors.append(f"scroll: {type(exc).__name__}: {exc}")
                    break
            for pattern in (
                re.compile(r"durchblättern", re.I),
                re.compile(r"prospekt öffnen", re.I),
                re.compile(r"jetzt öffnen", re.I),
                re.compile(r"magazin öffnen", re.I),
            ):
                try:
                    locator = page.locator("a,button").filter(has_text=pattern)
                    for index in range(min(locator.count(), 3)):
                        item = locator.nth(index)
                        if item.is_visible():
                            try:
                                item.click(timeout=2500)
                                time.sleep(0.75)
                            except Exception as exc:
                                render_errors.append(f"click:{pattern.pattern}:{index}: {type(exc).__name__}: {exc}")
                except Exception as exc:
                    render_errors.append(f"click_scan:{pattern.pattern}: {type(exc).__name__}: {exc}")
            try:
                raw = page.evaluate(
                    """
                    () => {
                      const rows = [], urls = [];
                      const walk = (root, scope) => {
                        for (const el of root.querySelectorAll('*')) {
                          const attrs = {};
                          for (const attr of el.attributes || []) {
                            attrs[attr.name] = attr.value;
                            if (/^(src|href|data-src|data-url|data-href)$/i.test(attr.name)) {
                              try { urls.push(new URL(attr.value, document.baseURI).href); } catch (_) {}
                            }
                          }
                          const tag = el.tagName ? el.tagName.toLowerCase() : '';
                          const text = (el.innerText || el.textContent || '').replace(/\\s+/g, ' ').trim();
                          if (tag.includes('-') || tag === 'iframe' || /ipaper|magazine|prospekt|flipbook/i.test([tag, text, JSON.stringify(attrs)].join(' '))) {
                            rows.push({scope, tag, attrs, text: text.slice(0, 1200)});
                          }
                          if (el.shadowRoot) walk(el.shadowRoot, scope + '::shadow(' + tag + ')');
                        }
                      };
                      walk(document, 'document');
                      for (const entry of performance.getEntriesByType('resource')) if (entry.name) urls.push(entry.name);
                      return {rows, urls, html: document.documentElement.outerHTML.slice(0, 500000)};
                    }
                    """
                )
                dom_rows = raw.get("rows") or []
                add_urls(values, channels, raw.get("urls") or [], "render_dom_or_performance", detail_url, rejected)
                html_urls, invalid = extract_urls(str(raw.get("html") or ""), detail_url)
                rejected.extend({"channel": "render_html", "value": item[:500], "reason": "invalid_url"} for item in invalid)
                add_urls(values, channels, html_urls, "render_html", detail_url, rejected)
            except Exception as exc:
                render_errors.append(f"dom_inventory: {type(exc).__name__}: {exc}")
            try:
                page.screenshot(path=str(output_dir / f"{label}-detail.png"), full_page=False)
                screenshot_saved = True
            except Exception as exc:
                render_errors.append(f"screenshot: {type(exc).__name__}: {exc}")
    finally:
        try:
            page.close()
        except Exception:
            pass
        context.close()

    candidates = []
    for path, source_channels in channels.items():
        descriptor = descriptor_from_path(path)
        score = len(source_channels) * 20
        lowered = path.lower()
        if any(token.lower() in lowered for token in spec["path_tokens"]):
            score += 40
        if path == urlsplit(old_source["ipaper_base_url"]).path:
            score += 25 if label == "current" else -10
        candidates.append({**descriptor, "channels": sorted(source_channels), "score": score})
    candidates.sort(key=lambda item: (item["score"], len(item["channels"]), item["source_path"]), reverse=True)

    probes = []
    selected = None
    for candidate in candidates[:20]:
        probe = probe_descriptor(playwright, candidate, old_source, detail_url)
        probes.append(probe)
        if probe["verified"] and selected is None:
            selected = probe
            break

    return {
        "label": label,
        "detail_url": redact_url(detail_url),
        "detail_path_verified": bool(http_documents and http_documents[0].get("detail_path_verified")),
        "detail_identity_signal": bool(http_documents and http_documents[0].get("identity_signal")),
        "detail_http_documents": http_documents,
        "linked_first_party_assets": linked_assets,
        "render_crashes": crashes,
        "render_errors": render_errors,
        "render_requests": render_requests,
        "render_responses": render_responses,
        "dom_inventory": dom_rows,
        "detail_screenshot_saved": screenshot_saved,
        "rejected_url_candidates": rejected,
        "candidate_sources": [{**item, "magazine_root": redact_url(item["magazine_root"]), "ipaper_root": redact_url(item["ipaper_root"])} for item in candidates],
        "candidate_probes": [{**item, "magazine_root": redact_url(item["magazine_root"]), "ipaper_root": redact_url(item["ipaper_root"])} for item in probes],
        "selected_source": ({**selected, "magazine_root": redact_url(selected["magazine_root"]), "ipaper_root": redact_url(selected["ipaper_root"])} if selected else None),
        "source_verified": selected is not None,
    }


def run_discovery(
    *,
    old_source_plan: Path,
    output: Path,
    browser_executable: Path,
    overview_url: str,
    commit_sha: str,
) -> dict[str, Any]:
    from playwright.sync_api import sync_playwright

    old_source = load_old_preview(old_source_plan)
    output = output.resolve()
    output.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as playwright:
        browser = playwright.chromium.launch(
            executable_path=str(browser_executable.resolve()),
            headless=True,
            args=[
                "--disable-dev-shm-usage",
                "--disable-gpu",
                "--disable-background-networking",
                "--disable-background-timer-throttling",
                "--disable-renderer-backgrounding",
                "--disable-features=BackForwardCache,CalculateNativeWinOcclusion,MediaRouter",
                "--no-first-run",
                "--no-default-browser-check",
            ],
        )
        try:
            overview_context = browser.new_context(locale="de-DE", timezone_id="Europe/Berlin", viewport={"width": 1280, "height": 900})
            overview_context.route("**/*", route_light)
            overview_page = overview_context.new_page()
            overview = {"url": redact_url(overview_url), "errors": [], "inventory": None, "screenshot_saved": False}
            try:
                try:
                    overview_page.goto(overview_url, wait_until="domcontentloaded", timeout=120_000)
                except Exception as exc:
                    overview["errors"].append(f"goto: {type(exc).__name__}: {exc}")
                deadline = time.time() + 30.0
                inventory = {}
                while time.time() < deadline:
                    time.sleep(1.0)
                    inventory = overview_inventory(overview_page)
                    body = str(inventory.get("body_text_excerpt") or "")
                    if re.search(DETAILS["current"]["heading"], body, re.I) and re.search(DETAILS["preview"]["heading"], body, re.I):
                        break
                    try:
                        overview_page.evaluate("window.scrollTo(0, document.documentElement.scrollHeight)")
                    except Exception:
                        pass
                overview["inventory"] = inventory
                try:
                    overview_page.screenshot(path=str(output / "overview.png"), full_page=False)
                    overview["screenshot_saved"] = True
                except Exception as exc:
                    overview["errors"].append(f"screenshot: {type(exc).__name__}: {exc}")
            finally:
                try:
                    overview_page.close()
                except Exception:
                    pass
                overview_context.close()

            current = discover_label(playwright, browser, "current", old_source, output, overview_url)
            preview = discover_label(playwright, browser, "preview", old_source, output, overview_url)
        finally:
            browser.close()

    current_ok = current["source_verified"] is True
    preview_ok = preview["source_verified"] is True
    current_path = current.get("selected_source", {}).get("source_path") if current_ok else None
    preview_path = preview.get("selected_source", {}).get("source_path") if preview_ok else None
    roots_distinct = bool(current_path and preview_path and current_path != preview_path)
    if current_ok and preview_ok and roots_distinct:
        state = "current_and_preview_sources_verified"
        result = "pass"
    elif current_ok and preview_ok:
        state = "verified_sources_not_distinct"
        result = "blocked"
    else:
        state = "source_discovery_incomplete"
        result = "blocked"

    report = {
        "schema_version": 4,
        "mode": MODE,
        "commit_sha": commit_sha,
        "official_overview_url": redact_url(overview_url),
        "old_preview_source": {
            "magazine_url": redact_url(old_source["magazine_url"]),
            "ipaper_base_url": redact_url(old_source["ipaper_base_url"]),
            "page_count": old_source["page_count"],
        },
        "overview": overview,
        "current": current,
        "preview": preview,
        "current_source_verified": current_ok,
        "preview_source_verified": preview_ok,
        "source_roots_distinct": roots_distinct,
        "state": state,
        "result": result,
        "scope": "source_discovery_only",
        "page_acquisition_performed": False,
        "rollover_comparison_performed": False,
        "third_party_catalog_sources_used": False,
        "shadow_only": True,
        "production_apply_authorized": False,
        "database_write_performed": False,
        "deployment_performed": False,
        "collector_executed": False,
    }
    (output / "source-discovery-v04.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    return report


def main() -> int:
    parser = argparse.ArgumentParser(description="ALDI official current/preview source discovery")
    parser.add_argument("--old-source-plan", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--browser-executable", type=Path, required=True)
    parser.add_argument("--overview-url", default=OFFICIAL_OVERVIEW_URL)
    parser.add_argument("--commit-sha", required=True)
    args = parser.parse_args()
    try:
        report = run_discovery(
            old_source_plan=args.old_source_plan,
            output=args.output,
            browser_executable=args.browser_executable,
            overview_url=args.overview_url,
            commit_sha=args.commit_sha,
        )
    except (DiscoveryError, OSError, ValueError) as exc:
        print(f"ERROR|{type(exc).__name__}|{exc}")
        return 2
    print(json.dumps({
        "result": report["result"],
        "state": report["state"],
        "current_source_verified": report["current_source_verified"],
        "preview_source_verified": report["preview_source_verified"],
        "source_roots_distinct": report["source_roots_distinct"],
    }, sort_keys=True))
    return 0 if report["result"] == "pass" else 3


if __name__ == "__main__":
    raise SystemExit(main())
