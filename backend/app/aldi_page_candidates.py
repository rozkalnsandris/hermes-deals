"""Read-only, unverified ALDI Nord first-party iPaper page candidates.

No candidate is evidence of issue dates, region or publication readiness.
Do not route these candidates into the public booklet reader directly.
"""

from dataclasses import dataclass
from hashlib import sha256
from html.parser import HTMLParser
import json
from urllib.parse import parse_qsl, urlsplit

LANDINGS = frozenset({
    "https://www.aldi-nord.de/prospekte/aldi-aktuell.html",
    "https://www.aldi-nord.de/prospekte/aldi-vorschau.html",
})
SOURCE_HOSTS = frozenset({"magazine.aldi-nord.de", "ipaper.ipapercms.dk"})
SENSITIVE_KEYS = frozenset({
    "token", "signature", "sig", "policy", "key-pair-id",
    "x-amz-signature", "x-amz-credential", "x-amz-security-token",
})
MAX_HTML_BYTES = 10_000_000
MAX_PAGES = 200


class InvalidAldiPageCandidates(ValueError):
    """Fail closed without publishing or guessing an edition."""


@dataclass(frozen=True)
class AldiPageCandidates:
    landing_url: str
    source_html_sha256: str
    viewer_url: str
    page_images: tuple[tuple[int, str], ...]
    status: str = "unverified"


class _NextDataScript(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.active = False
        self.closed = False
        self.seen = 0
        self.chunks: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "script" and dict(attrs).get("id") == "__NEXT_DATA__":
            self.seen += 1
            self.active = True

    def handle_data(self, data: str) -> None:
        if self.active:
            self.chunks.append(data)

    def handle_endtag(self, tag: str) -> None:
        if tag == "script" and self.active:
            self.active = False
            self.closed = True


def _official_source_url(value: object) -> tuple[str, str]:
    if not isinstance(value, str):
        raise InvalidAldiPageCandidates("missing official source URL")
    try:
        url = urlsplit(value)
        if (url.scheme != "https" or url.hostname not in SOURCE_HOSTS
                or url.port is not None or url.username or url.password
                or url.fragment or not url.path.startswith("/aldi-nord/")):
            raise InvalidAldiPageCandidates("untrusted ALDI source URL")
        segments = url.path.strip("/").split("/")
        if len(segments) < 2 or any(part in {"", ".", ".."} for part in segments):
            raise InvalidAldiPageCandidates("missing or unsafe ALDI issue path")
        if any(k.lower() in SENSITIVE_KEYS for k, _ in parse_qsl(url.query)):
            raise InvalidAldiPageCandidates("signed or sensitive ALDI URL")
    except ValueError as exc:
        raise InvalidAldiPageCandidates("invalid ALDI source URL") from exc
    return value, url.path.rstrip("/") + "/"


def parse_aldi_page_candidates(html: str, *, landing_url: str) -> AldiPageCandidates:
    """Decode page numbers/images from ALDI Next.js HTML; never verify a week.

    The caller must separately acquire an immutable, first-party source with
    source-bound issue identity, dates, region, full pages and retention.
    This pure parser performs no HTTP requests, file writes or UI publication.
    """
    if landing_url not in LANDINGS:
        raise InvalidAldiPageCandidates("unexpected first-party landing")
    if not isinstance(html, str):
        raise InvalidAldiPageCandidates("expected HTML text")
    raw = html.encode("utf-8")
    if not raw or len(raw) > MAX_HTML_BYTES:
        raise InvalidAldiPageCandidates("HTML source size out of bounds")
    parser = _NextDataScript()
    parser.feed(html)
    if parser.seen != 1 or not parser.closed:
        raise InvalidAldiPageCandidates("unique complete Next.js payload missing")
    try:
        payload = json.loads("".join(parser.chunks))
        props = payload["props"]["pageProps"]
        viewer_url, root = _official_source_url(props["page"]["link"])
        api_data = props["apiData"]
        if isinstance(api_data, str):
            api_data = json.loads(api_data)
        pages = api_data[0][1]["res"]
    except (KeyError, IndexError, TypeError, ValueError) as exc:
        raise InvalidAldiPageCandidates("invalid ALDI first-party page payload") from exc
    if not isinstance(pages, list) or not (1 <= len(pages) <= MAX_PAGES):
        raise InvalidAldiPageCandidates("missing or unreasonable page list")
    images: dict[int, str] = {}
    for row in pages:
        if not isinstance(row, dict):
            raise InvalidAldiPageCandidates("invalid page row")
        number = row.get("pageNumber")
        if isinstance(number, bool) or not (
            isinstance(number, int) or (isinstance(number, str) and number.isdecimal())
        ):
            raise InvalidAldiPageCandidates("invalid page number")
        number = int(number)
        image, image_root = _official_source_url(row.get("url"))
        if number in images or number < 1 or image_root != root and not image.startswith(
            ("https://ipaper.ipapercms.dk" + root, "https://magazine.aldi-nord.de" + root)
        ):
            raise InvalidAldiPageCandidates("duplicate or cross-publication page")
        query = dict(parse_qsl(urlsplit(image).query))
        if "PageNumber" in query and query["PageNumber"] != str(number):
            raise InvalidAldiPageCandidates("page number does not match URL")
        images[number] = image
    if sorted(images) != list(range(1, len(pages) + 1)):
        raise InvalidAldiPageCandidates("incomplete page sequence")
    return AldiPageCandidates(
        landing_url=landing_url,
        source_html_sha256=sha256(raw).hexdigest(),
        viewer_url=viewer_url,
        page_images=tuple(sorted(images.items())),
    )
