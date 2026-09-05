from __future__ import annotations

import hashlib
import re
from dataclasses import asdict, dataclass
from datetime import date
from urllib.parse import parse_qs, unquote, urljoin, urlsplit

import httpx
from bs4 import BeautifulSoup, Tag

STORE_ID = "1503"
STORE_NAME = "Kaufland Dortmund-Aplerbeck"
STORE_ADDRESS = "Aplerbecker Marktplatz 7-10"
STORE_POSTCODE_CITY = "44287 Dortmund"
STORE_PAGE_URL = (
    "https://filiale.kaufland.de/service/filiale/"
    "dortmund-aplerbeck-1503.html"
)

HTML_HOSTS = frozenset({"filiale.kaufland.de"})
LEAFLET_HOSTS = frozenset({"leaflets.kaufland.com"})
MAX_REDIRECTS = 5
MAX_HTML_BYTES = 8 * 1024 * 1024
MAX_ARTICLE_ID_SAMPLE = 32

_REDIRECT_STATUS = frozenset({301, 302, 303, 307, 308})
_MAIN_VALIDITY_RE = re.compile(
    r"Gültig\s+vom\s+(?P<from>\d{2}\.\d{2}\.\d{4})\s+bis\s+"
    r"(?P<to>\d{2}\.\d{2}\.\d{4})",
    re.IGNORECASE,
)
_SHORT_VALIDITY_RE = re.compile(
    r"Gültig\s+vom\s+(?P<from>\d{2}\.\d{2}\.)\s+bis\s+"
    r"(?P<to>\d{2}\.\d{2}\.)",
    re.IGNORECASE,
)
_STORE_ID_TOKEN_RE = re.compile(r"(?<!\d)(?:DE)?1503(?!\d)", re.IGNORECASE)
_EXACT_STORE_COOKIE_VALUES = frozenset({STORE_ID.casefold(), f"DE{STORE_ID}".casefold()})


class KauflandSourceDiscoveryError(RuntimeError):
    def __init__(self, code: str, message: str):
        super().__init__(message)
        self.code = code


@dataclass(frozen=True)
class RedirectHop:
    status: int
    source_url: str
    target_url: str


@dataclass(frozen=True)
class FetchedHtml:
    requested_url: str
    final_url: str
    status: int
    content_type: str
    body: bytes
    sha256: str
    redirects: tuple[RedirectHop, ...]
    request_cookie_header: str


@dataclass(frozen=True)
class LeafletRef:
    url: str
    validity_label: str | None
    preview: bool


@dataclass(frozen=True)
class StorePageEvidence:
    store_name: str
    store_id: str
    address: str
    postcode_city: str
    main_valid_from: str
    main_valid_to: str
    offer_overview_url: str
    article_id_count: int
    article_id_sample: tuple[str, ...]
    leaflets: tuple[LeafletRef, ...]


@dataclass(frozen=True)
class KauflandDiscoveryReport:
    schema_version: int
    source_state: str
    store_binding_proven: bool
    binding_method: str
    store: StorePageEvidence
    store_page_url: str
    store_page_final_url: str
    store_page_sha256: str
    store_page_bytes: int
    store_page_redirects: tuple[RedirectHop, ...]
    offer_overview_url: str
    offer_overview_final_url: str
    offer_overview_sha256: str
    offer_overview_bytes: int
    offer_overview_redirects: tuple[RedirectHop, ...]
    session_cookie_names: tuple[str, ...]
    session_cookie_has_store_id: bool
    overview_request_cookie_has_store_id: bool
    overview_body_has_store_name: bool
    overview_body_has_store_id: bool

    def as_public_dict(self) -> dict[str, object]:
        # Cookie values and response bodies are intentionally never serialized.
        return asdict(self)


def _norm(value: str) -> str:
    return " ".join(value.replace("\xa0", " ").split()).strip()


def _parse_date_de(value: str) -> date:
    day, month, year = value.split(".")
    return date(int(year), int(month), int(day))


def _validate_https_url(url: str, allowed_hosts: frozenset[str]) -> None:
    parsed = urlsplit(url)
    if parsed.scheme != "https":
        raise KauflandSourceDiscoveryError(
            "UNSAFE_SOURCE_URL",
            f"Kaufland source URL must use https: {url}",
        )
    host = (parsed.hostname or "").casefold()
    if host not in allowed_hosts:
        raise KauflandSourceDiscoveryError(
            "UNSAFE_SOURCE_HOST",
            f"Kaufland source host is not allowlisted: {host or '<missing>'}",
        )
    if parsed.username or parsed.password:
        raise KauflandSourceDiscoveryError(
            "UNSAFE_SOURCE_URL",
            "Kaufland source URL must not contain userinfo",
        )


def _read_bounded_html(response: httpx.Response) -> bytes:
    content_type = response.headers.get("content-type", "")
    if "text/html" not in content_type.casefold():
        raise KauflandSourceDiscoveryError(
            "UNEXPECTED_CONTENT_TYPE",
            f"Expected text/html, got {content_type or '<missing>'}",
        )

    chunks: list[bytes] = []
    total = 0
    for chunk in response.iter_bytes():
        total += len(chunk)
        if total > MAX_HTML_BYTES:
            raise KauflandSourceDiscoveryError(
                "SOURCE_TOO_LARGE",
                f"Kaufland HTML exceeded {MAX_HTML_BYTES} bytes",
            )
        chunks.append(chunk)
    return b"".join(chunks)


def fetch_html_bounded(
    client: httpx.Client,
    url: str,
    *,
    allowed_hosts: frozenset[str] = HTML_HOSTS,
) -> FetchedHtml:
    requested_url = url
    current_url = url
    redirects: list[RedirectHop] = []

    for _ in range(MAX_REDIRECTS + 1):
        _validate_https_url(current_url, allowed_hosts)
        with client.stream("GET", current_url, follow_redirects=False) as response:
            status = response.status_code
            if status in _REDIRECT_STATUS:
                location = response.headers.get("location")
                if not location:
                    raise KauflandSourceDiscoveryError(
                        "INVALID_REDIRECT",
                        f"Redirect {status} did not provide Location",
                    )
                target = urljoin(str(response.url), location)
                _validate_https_url(target, allowed_hosts)
                redirects.append(
                    RedirectHop(
                        status=status,
                        source_url=str(response.url),
                        target_url=target,
                    )
                )
                current_url = target
                continue

            if status < 200 or status >= 300:
                raise KauflandSourceDiscoveryError(
                    "SOURCE_UNAVAILABLE",
                    f"Kaufland source returned HTTP {status}: {response.url}",
                )

            body = _read_bounded_html(response)
            return FetchedHtml(
                requested_url=requested_url,
                final_url=str(response.url),
                status=status,
                content_type=response.headers.get("content-type", ""),
                body=body,
                sha256=hashlib.sha256(body).hexdigest(),
                redirects=tuple(redirects),
                request_cookie_header=response.request.headers.get("cookie", ""),
            )

    raise KauflandSourceDiscoveryError(
        "TOO_MANY_REDIRECTS",
        f"Kaufland source exceeded {MAX_REDIRECTS} redirects",
    )


def _find_single_offer_overview_url(soup: BeautifulSoup, base_url: str) -> str:
    urls: set[str] = set()
    for tag in soup.find_all("a", href=True):
        if _norm(tag.get_text(" ", strip=True)).casefold() != "zeige alle angebote":
            continue
        absolute = urljoin(base_url, str(tag.get("href", "")).strip())
        parsed = urlsplit(absolute)
        if (
            (parsed.hostname or "").casefold() == "filiale.kaufland.de"
            and parsed.path == "/angebote/uebersicht.html"
        ):
            urls.add(absolute)
    if len(urls) != 1:
        raise KauflandSourceDiscoveryError(
            "OFFER_OVERVIEW_AMBIGUOUS",
            f"Expected one distinct Kaufland offer overview URL, found {len(urls)}",
        )
    return next(iter(urls))


def _article_ids(soup: BeautifulSoup, base_url: str) -> tuple[str, ...]:
    values: set[str] = set()
    for tag in soup.find_all("a", href=True):
        absolute = urljoin(base_url, str(tag.get("href", "")))
        parsed = urlsplit(absolute)
        if (parsed.hostname or "").casefold() != "filiale.kaufland.de":
            continue
        for value in parse_qs(parsed.query).get("kloffer-articleID", []):
            value = value.strip()
            if value:
                values.add(value)
    return tuple(sorted(values))


def _leaflet_refs(soup: BeautifulSoup, base_url: str) -> tuple[LeafletRef, ...]:
    tags = list(soup.find_all(True))
    preview_index: int | None = None
    for index, tag in enumerate(tags):
        if _norm(tag.get_text(" ", strip=True)) == "Prospekt-Vorschau":
            preview_index = index
            break

    refs: list[LeafletRef] = []
    seen: set[str] = set()
    for index, tag in enumerate(tags):
        if tag.name != "a" or not tag.has_attr("href"):
            continue
        absolute = urljoin(base_url, str(tag.get("href", "")))
        parsed = urlsplit(absolute)
        if (parsed.hostname or "").casefold() not in LEAFLET_HOSTS:
            continue
        if absolute in seen:
            continue
        seen.add(absolute)

        validity_label: str | None = None
        text_candidates = [_norm(tag.get_text(" ", strip=True))]
        if isinstance(tag.parent, Tag):
            text_candidates.append(_norm(tag.parent.get_text(" ", strip=True)))
        for candidate in text_candidates:
            match = _SHORT_VALIDITY_RE.search(candidate)
            if match:
                validity_label = match.group(0)
                break

        refs.append(
            LeafletRef(
                url=absolute,
                validity_label=validity_label,
                preview=preview_index is not None and index > preview_index,
            )
        )
    return tuple(refs)


def parse_store_page(html: bytes | str, source_url: str) -> StorePageEvidence:
    _validate_https_url(source_url, HTML_HOSTS)
    parsed_source = urlsplit(source_url)
    expected_path = f"/service/filiale/dortmund-aplerbeck-{STORE_ID}.html"
    if parsed_source.path != expected_path:
        raise KauflandSourceDiscoveryError(
            "STORE_BINDING_NOT_PROVEN",
            f"Unexpected Kaufland store path: {parsed_source.path}",
        )

    text = html.decode("utf-8", errors="replace") if isinstance(html, bytes) else html
    soup = BeautifulSoup(text, "html.parser")
    normalized = _norm(soup.get_text(" ", strip=True))

    h1_values = {_norm(tag.get_text(" ", strip=True)) for tag in soup.find_all("h1")}
    if STORE_NAME not in h1_values:
        raise KauflandSourceDiscoveryError(
            "STORE_BINDING_NOT_PROVEN",
            f"Expected exact store heading {STORE_NAME!r}",
        )
    for marker in (STORE_ADDRESS, STORE_POSTCODE_CITY):
        if marker not in normalized:
            raise KauflandSourceDiscoveryError(
                "STORE_BINDING_NOT_PROVEN",
                f"Missing exact store marker {marker!r}",
            )

    validity_values = {
        (match.group("from"), match.group("to"))
        for match in _MAIN_VALIDITY_RE.finditer(normalized)
    }
    if len(validity_values) != 1:
        raise KauflandSourceDiscoveryError(
            "CAMPAIGN_WINDOW_AMBIGUOUS",
            f"Expected one main campaign window, found {len(validity_values)}",
        )
    valid_from_raw, valid_to_raw = next(iter(validity_values))
    valid_from = _parse_date_de(valid_from_raw)
    valid_to = _parse_date_de(valid_to_raw)
    if valid_to < valid_from or (valid_to - valid_from).days > 7:
        raise KauflandSourceDiscoveryError(
            "CAMPAIGN_WINDOW_AMBIGUOUS",
            f"Implausible main campaign window: {valid_from_raw}..{valid_to_raw}",
        )

    overview_url = _find_single_offer_overview_url(soup, source_url)
    _validate_https_url(overview_url, HTML_HOSTS)
    article_ids = _article_ids(soup, source_url)
    leaflets = _leaflet_refs(soup, source_url)
    if not leaflets:
        raise KauflandSourceDiscoveryError(
            "LEAFLET_DISCOVERY_EMPTY",
            "Exact Kaufland store page exposed no first-party leaflet links",
        )

    return StorePageEvidence(
        store_name=STORE_NAME,
        store_id=STORE_ID,
        address=STORE_ADDRESS,
        postcode_city=STORE_POSTCODE_CITY,
        main_valid_from=valid_from.isoformat(),
        main_valid_to=valid_to.isoformat(),
        offer_overview_url=overview_url,
        article_id_count=len(article_ids),
        article_id_sample=article_ids[:MAX_ARTICLE_ID_SAMPLE],
        leaflets=leaflets,
    )


def _is_exact_store_cookie_value(value: str) -> bool:
    normalized = unquote(value).strip().strip('"').casefold()
    return normalized in _EXACT_STORE_COOKIE_VALUES


def _cookie_names(client: httpx.Client) -> tuple[str, ...]:
    return tuple(sorted({cookie.name for cookie in client.cookies.jar}))


def _cookie_store_id_match(client: httpx.Client) -> bool:
    return any(_is_exact_store_cookie_value(cookie.value or "") for cookie in client.cookies.jar)


def _request_cookie_store_id_match(cookie_header: str) -> bool:
    for token in cookie_header.split(";"):
        if "=" not in token:
            continue
        _, value = token.split("=", 1)
        if _is_exact_store_cookie_value(value):
            return True
    return False


def discover_kaufland_source(client: httpx.Client) -> KauflandDiscoveryReport:
    store_doc = fetch_html_bounded(client, STORE_PAGE_URL)
    store = parse_store_page(store_doc.body, store_doc.final_url)

    cookie_names = _cookie_names(client)
    cookie_has_store_id = _cookie_store_id_match(client)

    overview_doc = fetch_html_bounded(client, store.offer_overview_url)
    overview_text = _norm(
        BeautifulSoup(
            overview_doc.body.decode("utf-8", errors="replace"),
            "html.parser",
        ).get_text(" ", strip=True)
    )

    request_cookie_has_store_id = _request_cookie_store_id_match(
        overview_doc.request_cookie_header
    )
    overview_body_has_store_name = STORE_NAME in overview_text
    overview_body_has_store_id = bool(_STORE_ID_TOKEN_RE.search(overview_text))

    if overview_body_has_store_name:
        binding_method = "overview_body_exact_store_name"
    elif request_cookie_has_store_id:
        binding_method = "same_session_exact_store_cookie"
    else:
        raise KauflandSourceDiscoveryError(
            "STORE_BINDING_NOT_PROVEN",
            "Offer overview did not expose exact Aplerbeck identity and the "
            "same-session overview request did not carry an exact 1503/DE1503 cookie",
        )

    return KauflandDiscoveryReport(
        schema_version=1,
        source_state="available",
        store_binding_proven=True,
        binding_method=binding_method,
        store=store,
        store_page_url=store_doc.requested_url,
        store_page_final_url=store_doc.final_url,
        store_page_sha256=store_doc.sha256,
        store_page_bytes=len(store_doc.body),
        store_page_redirects=store_doc.redirects,
        offer_overview_url=overview_doc.requested_url,
        offer_overview_final_url=overview_doc.final_url,
        offer_overview_sha256=overview_doc.sha256,
        offer_overview_bytes=len(overview_doc.body),
        offer_overview_redirects=overview_doc.redirects,
        session_cookie_names=cookie_names,
        session_cookie_has_store_id=cookie_has_store_id,
        overview_request_cookie_has_store_id=request_cookie_has_store_id,
        overview_body_has_store_name=overview_body_has_store_name,
        overview_body_has_store_id=overview_body_has_store_id,
    )
