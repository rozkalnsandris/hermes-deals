from __future__ import annotations

import json
import re
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse, urlsplit, urlunsplit

import httpx
from bs4 import BeautifulSoup

_LEAFLET_RE = re.compile(
    r"https?://(?:www\.)?lidl\.de/l/prospekte/[^\"'<>\s]+/view/flyer/page/\d+"
    r"|/l/prospekte/[^\"'<>\s]+/view/flyer/page/\d+",
    re.IGNORECASE,
)
_PAGE_RE = re.compile(r"/view/flyer/page/(\d+)", re.IGNORECASE)
_URL_TOKEN_RE = re.compile(r"https?://[^\"'<>\s\\]+|/[A-Za-z0-9_./?=&%:+-]{8,}")
_INTERESTING_TOKEN_RE = re.compile(r"(?:api|graphql|json|leaflet|prospekt|flyer|catalog|brochure)", re.IGNORECASE)


@dataclass(frozen=True)
class LeafletRef:
    url: str
    page: int | None
    leaflet_key: str


@dataclass(frozen=True)
class PageProbe:
    url: str
    status: int | None
    content_type: str | None
    content_bytes: int
    script_src_count: int
    script_srcs: list[str]
    candidate_tokens: list[str]
    error: str | None = None


def _leaflet_key(url: str) -> str:
    parsed = urlparse(url)
    parts = [part for part in parsed.path.split("/") if part]
    try:
        idx = parts.index("prospekte")
        return parts[idx + 1]
    except (ValueError, IndexError):
        return "unknown"


def extract_leaflet_refs(html: bytes | str, base_url: str) -> list[LeafletRef]:
    text = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    text = text.replace("\\/", "/")
    soup = BeautifulSoup(text, "html.parser")
    candidates: set[str] = set()

    def canonical_leaflet_url(value: str) -> str:
        absolute = urljoin(base_url, value)
        parsed = urlsplit(absolute)
        # Tracking/query parameters are irrelevant for identifying a flyer page and
        # otherwise create duplicate refs for the same immutable page path.
        return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, "", ""))

    for tag in soup.find_all("a", href=True):
        href = str(tag.get("href", "")).strip()
        if "/l/prospekte/" in href and "/view/flyer/page/" in href:
            candidates.add(canonical_leaflet_url(href))

    # Some Lidl links can also appear inside hydration/script payloads rather than anchors.
    for match in _LEAFLET_RE.findall(text):
        candidates.add(canonical_leaflet_url(match))

    refs: list[LeafletRef] = []
    for url in sorted(candidates):
        page_match = _PAGE_RE.search(url)
        page = int(page_match.group(1)) if page_match else None
        refs.append(LeafletRef(url=url, page=page, leaflet_key=_leaflet_key(url)))
    return refs


def extract_script_srcs(html: bytes | str, base_url: str, limit: int = 40) -> list[str]:
    text = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    soup = BeautifulSoup(text, "html.parser")
    values = sorted({urljoin(base_url, str(tag.get("src"))) for tag in soup.find_all("script", src=True)})
    return values[:limit]

def extract_candidate_tokens(html: bytes | str, base_url: str, limit: int = 80) -> list[str]:
    text = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    text = text.replace("\\/", "/")
    soup = BeautifulSoup(text, "html.parser")
    values: set[str] = set()

    for tag in soup.find_all("script", src=True):
        values.add(urljoin(base_url, str(tag.get("src"))))

    for token in _URL_TOKEN_RE.findall(text):
        if _INTERESTING_TOKEN_RE.search(token):
            values.add(urljoin(base_url, token) if token.startswith("/") else token)

    # Keep the report useful and deterministic rather than dumping the whole Lidl page.
    ordered = sorted(value for value in values if _INTERESTING_TOKEN_RE.search(value))
    return ordered[:limit]


def probe_leaflet_page(client: httpx.Client, url: str) -> PageProbe:
    try:
        response = client.get(url)
        content = response.content
        text = response.text
        soup = BeautifulSoup(text, "html.parser")
        return PageProbe(
            url=str(response.url),
            status=response.status_code,
            content_type=response.headers.get("content-type"),
            content_bytes=len(content),
            script_src_count=len(soup.find_all("script", src=True)),
            script_srcs=extract_script_srcs(text, str(response.url)),
            candidate_tokens=extract_candidate_tokens(text, str(response.url)),
        )
    except Exception as exc:
        return PageProbe(
            url=url,
            status=None,
            content_type=None,
            content_bytes=0,
            script_src_count=0,
            script_srcs=[],
            candidate_tokens=[],
            error=f"{type(exc).__name__}: {exc}"[:1000],
        )


def inspect_lidl_source(
    *,
    landing_html_path: Path,
    landing_url: str,
    output_dir: Path,
    user_agent: str,
    max_pages: int = 5,
) -> dict[str, object]:
    html = landing_html_path.read_bytes()
    refs = extract_leaflet_refs(html, landing_url)

    # Probe distinct flyer pages, preferring lower page numbers because they are cheap sanity checks.
    unique_urls: list[str] = []
    seen: set[str] = set()
    for ref in sorted(refs, key=lambda item: (item.page is None, item.page or 10**9, item.url)):
        if ref.url not in seen:
            unique_urls.append(ref.url)
            seen.add(ref.url)
        if len(unique_urls) >= max(max_pages, 1):
            break

    headers = {
        "User-Agent": user_agent,
        "Accept": "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
        "Cache-Control": "no-cache",
    }
    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(30.0, connect=10.0), headers=headers) as client:
        probes = [probe_leaflet_page(client, url) for url in unique_urls]

    landing_candidates = extract_candidate_tokens(html, landing_url)
    landing_script_srcs = extract_script_srcs(html, landing_url)
    leaflet_keys = sorted({ref.leaflet_key for ref in refs})
    pages = sorted({ref.page for ref in refs if ref.page is not None})
    successful_page_probes = sum(1 for probe in probes if probe.status is not None and 200 <= probe.status < 300)

    report: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "landing_url": landing_url,
        "landing_snapshot": str(landing_html_path),
        "strategy": "http_leaflet_discovery",
        "playwright_used": False,
        "leaflet_link_count": len(refs),
        "leaflet_keys": leaflet_keys,
        "linked_pages": pages,
        "landing_script_srcs": landing_script_srcs,
        "landing_candidate_tokens": landing_candidates,
        "page_probes": [asdict(probe) for probe in probes],
        "successful_page_probes": successful_page_probes,
        "gate": {
            "has_leaflet_links": len(refs) > 0,
            "has_reachable_leaflet_page": successful_page_probes > 0,
        },
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    output_path = output_dir / f"{stamp}-lidl-discovery.json"
    output_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(output_path)
    return report
