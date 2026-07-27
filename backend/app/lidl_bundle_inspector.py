from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urljoin, urlparse

import httpx

_ABSOLUTE_URL_RE = re.compile(r"https?://[^\"'<>\\\s)]+", re.IGNORECASE)
_RELATIVE_URL_RE = re.compile(r"[\"'`](/[^\"'`<>\\\s]{3,})[\"'`]")
_SOURCE_MAP_RE = re.compile(r"[#@]\s*sourceMappingURL\s*=\s*([^\s*]+)", re.IGNORECASE)
_INTERESTING_RE = re.compile(
    r"(?:api|graphql|leaflet|flyer|prospekt|catalog|brochure|publication|product|page|content|manifest|config|asset)",
    re.IGNORECASE,
)
_NETWORK_MARKERS = (
    "fetch(",
    "XMLHttpRequest",
    "axios",
    "graphql",
    "baseURL",
    "baseUrl",
    "apiUrl",
    "apiURL",
    "endpoint",
    "leaflet",
    "publication",
)


def _normalize_js_text(text: str) -> str:
    return (
        text.replace("\\/", "/")
        .replace("\\u002F", "/")
        .replace("\\u002f", "/")
        .replace("\\u003A", ":")
        .replace("\\u003a", ":")
        .replace("\\u0026", "&")
    )


def _unique(values: list[str], limit: int) -> list[str]:
    seen: set[str] = set()
    result: list[str] = []
    for value in values:
        if value in seen:
            continue
        seen.add(value)
        result.append(value)
        if len(result) >= limit:
            break
    return result


def extract_endpoint_candidates(js: bytes | str, base_url: str, limit: int = 200) -> list[str]:
    text = js.decode("utf-8", errors="replace") if isinstance(js, bytes) else js
    text = _normalize_js_text(text)
    values: list[str] = []

    for token in _ABSOLUTE_URL_RE.findall(text):
        token = token.rstrip(".,;]")
        if _INTERESTING_RE.search(token):
            values.append(token)

    for match in _RELATIVE_URL_RE.findall(text):
        token = match.rstrip(".,;]")
        if _INTERESTING_RE.search(token):
            values.append(urljoin(base_url, token))

    return _unique(sorted(values), limit)


def extract_network_snippets(js: bytes | str, limit: int = 40, radius: int = 180) -> list[str]:
    text = js.decode("utf-8", errors="replace") if isinstance(js, bytes) else js
    text = _normalize_js_text(text)
    lowered = text.lower()
    snippets: list[str] = []

    for marker in _NETWORK_MARKERS:
        marker_lower = marker.lower()
        start = 0
        while True:
            idx = lowered.find(marker_lower, start)
            if idx < 0:
                break
            left = max(0, idx - radius)
            right = min(len(text), idx + len(marker) + radius)
            snippet = " ".join(text[left:right].split())
            snippets.append(snippet)
            if len(_unique(snippets, limit)) >= limit:
                return _unique(snippets, limit)
            start = idx + len(marker)

    return _unique(snippets, limit)


def extract_source_map_url(js: bytes | str, bundle_url: str) -> str | None:
    text = js.decode("utf-8", errors="replace") if isinstance(js, bytes) else js
    matches = _SOURCE_MAP_RE.findall(text[-10000:])
    if not matches:
        return None
    candidate = matches[-1].strip().strip('"\'')
    if candidate.startswith("data:"):
        return None
    return urljoin(bundle_url, candidate)


def _select_bundle_url(discovery: dict[str, object]) -> str:
    candidates: list[str] = []
    for page in discovery.get("page_probes", []):
        if isinstance(page, dict):
            for url in page.get("script_srcs", []):
                if isinstance(url, str):
                    candidates.append(url)
    for url in discovery.get("landing_script_srcs", []):
        if isinstance(url, str):
            candidates.append(url)

    preferred = [
        url
        for url in candidates
        if urlparse(url).hostname == "lidl.leaflets.schwarz" and "/assets/" in url and url.endswith(".js")
    ]
    if preferred:
        return sorted(set(preferred))[0]

    fallback = [url for url in candidates if url.endswith(".js") and "leaflet" in url.lower()]
    if fallback:
        return sorted(set(fallback))[0]
    raise ValueError("No Lidl leaflet JavaScript bundle URL found in discovery report")


def inspect_lidl_bundle(
    *,
    discovery_report_path: Path,
    output_dir: Path,
    user_agent: str,
) -> dict[str, object]:
    discovery = json.loads(discovery_report_path.read_text(encoding="utf-8"))
    bundle_url = _select_bundle_url(discovery)
    headers = {
        "User-Agent": user_agent,
        "Accept": "text/javascript,application/javascript,*/*;q=0.8",
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
        "Cache-Control": "no-cache",
        "Referer": str(discovery.get("landing_url") or "https://www.lidl.de/"),
    }

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")

    with httpx.Client(follow_redirects=True, timeout=httpx.Timeout(45.0, connect=10.0), headers=headers) as client:
        response = client.get(bundle_url)
        response.raise_for_status()
        content = response.content
        final_url = str(response.url)
        sha256 = hashlib.sha256(content).hexdigest()
        bundle_path = output_dir / f"{stamp}-lidl-leaflet-bundle-{sha256[:12]}.js"
        bundle_path.write_bytes(content)

        candidates = extract_endpoint_candidates(content, final_url)
        snippets = extract_network_snippets(content)
        source_map_url = extract_source_map_url(content, final_url)
        source_map: dict[str, object] | None = None

        if source_map_url:
            try:
                map_response = client.get(source_map_url)
                map_content = map_response.content
                map_sha = hashlib.sha256(map_content).hexdigest()
                map_path = output_dir / f"{stamp}-lidl-leaflet-bundle-{map_sha[:12]}.map"
                if map_response.is_success:
                    map_path.write_bytes(map_content)
                source_map = {
                    "url": str(map_response.url),
                    "status": map_response.status_code,
                    "content_type": map_response.headers.get("content-type"),
                    "content_bytes": len(map_content),
                    "saved_path": str(map_path) if map_response.is_success else None,
                    "sha256": map_sha if map_response.is_success else None,
                }
            except Exception as exc:  # discovery must remain useful even without a source map
                source_map = {"url": source_map_url, "error": f"{type(exc).__name__}: {exc}"[:1000]}

    hostnames = sorted({urlparse(url).hostname for url in candidates if urlparse(url).hostname})
    report: dict[str, object] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": "http_bundle_static_analysis",
        "playwright_used": False,
        "discovery_report": str(discovery_report_path),
        "bundle_url": bundle_url,
        "bundle_final_url": final_url,
        "bundle_status": response.status_code,
        "bundle_content_type": response.headers.get("content-type"),
        "bundle_bytes": len(content),
        "bundle_sha256": sha256,
        "bundle_snapshot": str(bundle_path),
        "candidate_count": len(candidates),
        "candidate_hostnames": hostnames,
        "endpoint_candidates": candidates,
        "network_snippet_count": len(snippets),
        "network_snippets": snippets,
        "source_map": source_map,
        "gate": {
            "bundle_reachable": response.is_success,
            "bundle_saved": bundle_path.is_file() and bundle_path.stat().st_size == len(content),
        },
    }

    report_path = output_dir / f"{stamp}-lidl-bundle-analysis.json"
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    report["report_path"] = str(report_path)
    return report
