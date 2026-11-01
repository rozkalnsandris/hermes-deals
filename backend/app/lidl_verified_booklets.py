"""Registered original Lidl physical-store flyer, isolated from offer publication.

This module only reads local, owner-registered immutable evidence. No source
network requests, collector, product matching, PDF or implicit activation.
"""
import base64
import binascii
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
import stat
from urllib.parse import parse_qs, urlencode, urlsplit

from app.settings import get_settings

SCHEMA = "lidl_family_original_image_capture_v1"
HUB = "https://www.lidl.de/c/online-prospekte/s10005610/"
STORE = "DE06664"
ENTITY = "6664"
CONTROL_REGION = "7"  # Selected-store cookie control; never a flyer route identity.
REGION = "21"  # Week 45 observed in selected-store HTML; checked against first-party API.
FLYER_ID = "01a1770f-71cb-7322-ba85-b04b8c4bc460"
SLUG_ID = "aktionsprospekt-02-11-2026-07-11-2026-84eded"
START, END = date(2026, 11, 2), date(2026, 11, 7)
QUALITIES = ("normal", "large")
SHA = re.compile(r"[0-9a-f]{64}\Z")
UUID = re.compile(r"[0-9a-f]{8}(?:-[0-9a-f]{4}){3}-[0-9a-f]{12}\Z")
SLUG = re.compile(r"aktionsprospekt-02-11-2026-07-11-2026-[a-z0-9]+\Z")
MAX_MANIFEST = 256 * 1024
MAX_API = 5 * 1024 * 1024
MAX_HUB = 6 * 1024 * 1024
MAX_IMAGE = 6 * 1024 * 1024
MAX_TOTAL = 250 * 1024 * 1024
MAX_PAGES = 120
UNAVAILABLE = {
    "state": "unavailable", "offers": [],
    "message": "Reģistrētās Lidl ģimenes veikala bukleta lapas nevar pārbaudīt.",
}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate source metadata key")
        result[key] = value
    return result


class _Links(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []

    def handle_starttag(self, tag, attrs):
        if tag.lower() == "a":
            for key, value in attrs:
                if key.lower() == "href" and isinstance(value, str):
                    self.links.append(value)


def _read(root, components, limit):
    """Bounded no-follow reads of exact relative paths, including root itself."""
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("Untrusted Lidl booklet root")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    fd = os.open(root, flags | os.O_DIRECTORY)
    try:
        for component in components[:-1]:
            if component in (".", "..") or not re.fullmatch(r"[a-zA-Z0-9_.-]+", component):
                raise ValueError("Invalid directory name")
            new_fd = os.open(component, flags | os.O_DIRECTORY, dir_fd=fd)
            os.close(fd)
            fd = new_fd
        name = components[-1]
        if name in (".", "..") or not re.fullmatch(r"[a-zA-Z0-9_.-]+", name):
            raise ValueError("Invalid file name")
        file_fd = os.open(name, flags, dir_fd=fd)
        with os.fdopen(file_fd, "rb") as stream:
            st = os.fstat(stream.fileno())
            if not stat.S_ISREG(st.st_mode) or not 0 < st.st_size <= limit:
                raise ValueError("Unbounded or non-regular source")
            data = stream.read(limit + 1)
            if len(data) != st.st_size:
                raise ValueError("File size changed")
            return data
    finally:
        os.close(fd)


def _viewer(value):
    if not isinstance(value, str):
        raise ValueError("Missing first-party Lidl viewer")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.netloc != "www.lidl.de"
            or parsed.username or parsed.password or parsed.fragment
            or not re.fullmatch(r"/l/prospekte/aktionsprospekt-02-11-2026-07-11-2026-[a-z0-9]+/ar/21/?", parsed.path)):
        raise ValueError("Wrong Lidl edition or regional viewer")
    return parsed


def _api_url(value, slug):
    if not isinstance(value, str):
        raise ValueError("Missing source API URL")
    parsed = urlsplit(value)
    try:
        query = parse_qs(parsed.query, strict_parsing=True, max_num_fields=8)
    except ValueError as exc:
        raise ValueError("Invalid source API query") from exc
    if (parsed.scheme != "https" or parsed.netloc != "endpoints.leaflets.schwarz"
            or parsed.path != "/v4/flyer" or parsed.fragment
            or parsed.username or parsed.password
            or query.get("flyer_identifier") != [slug]
            or query.get("region_id") != [REGION]
            or query.get("client") != ["lidl"] or query.get("version") != ["4"]
            or set(query) != {"flyer_identifier", "region_id", "client", "version"}):
        raise ValueError("Unbound publisher API")
    return parsed


def _image_source(value, number, quality, flyer_id):
    if not isinstance(value, str) or not 1 <= len(value) <= 700:
        return False
    try:
        parsed = urlsplit(value)
        if (parsed.scheme != "https" or parsed.netloc != "imgproxy.leaflets.schwarz"
                or parsed.fragment or parsed.query or parsed.username or parsed.password):
            return False
        parts = parsed.path.lstrip("/").split("/")
        if (len(parts) != 4 or parts[2] != "g:no"
                or not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", parts[0])
                or parts[1] != ("rs:fit:1200:1200:1" if quality == "normal" else "rs:fit:2400:2400:1")
                or not re.fullmatch(r"[A-Za-z0-9_-]+\.jpg", parts[3])):
            return False
        token = parts[3][:-4]
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("ascii")
        return bool(re.fullmatch(
            rf"s3://leaflets/images/{re.escape(flyer_id)}/page-{number:02d}_[0-9a-f]{{32}}\.png",
            raw,
        ))
    except (ValueError, UnicodeError, TypeError, binascii.Error):
        return False


def _source(root, meta):
    hub = _read(root, ("hub.html",), MAX_HUB)
    api = _read(root, ("api.json",), MAX_API)
    if sha256(hub).hexdigest() != meta.get("hub_html_sha256"):
        raise ValueError("Hub source digest drift")
    if sha256(api).hexdigest() != meta.get("api_json_sha256"):
        raise ValueError("API source digest drift")
    viewer = _viewer(meta.get("viewer_url"))
    slug = viewer.path.split("/")[3]
    if slug != SLUG_ID:
        raise ValueError("Different Lidl selected-store weekly edition")
    _api_url(meta.get("api_url"), slug)
    parser = _Links()
    parser.feed(hub.decode("utf-8", "strict"))
    # An explicit selected-store hub link and regional publisher response are
    # independently needed. Store-control cookies alone are never enough.
    candidates = [urlsplit(link) for link in parser.links]
    if not any(v.path == viewer.path and (not v.netloc or v.netloc == "www.lidl.de")
               and (not v.scheme or v.scheme == "https") for v in candidates):
        raise ValueError("Missing selected-store region-21 hub publication link")
    payload = json.loads(api, object_pairs_hook=_unique)
    if not isinstance(payload, dict) or payload.get("success") is not True or payload.get("version") != 4:
        raise ValueError("Publisher API not successful")
    flyer = payload.get("flyer")
    if not isinstance(flyer, dict):
        raise ValueError("Publisher flyer missing")
    if (flyer.get("id") != FLYER_ID or flyer.get("id") != meta.get("source_flyer_id")
            or not isinstance(flyer.get("regions"), list)
            or not {REGION, CONTROL_REGION}.issubset({str(x.get("code")) for x in flyer["regions"] if isinstance(x, dict)})
            or flyer.get("offerStartDate") != START.isoformat()
            or flyer.get("offerEndDate") != END.isoformat()
            or _viewer(flyer.get("flyerUrlAbsolute")).path != viewer.path):
        raise ValueError("No independent Lidl family-region flyer proof")
    pages = flyer.get("pages")
    if not isinstance(pages, list) or len(pages) != meta["page_count"]:
        raise ValueError("Source page count drift")
    return pages


def _asset(root, number, quality, item):
    data = _read(root, ("pages", quality, f"bk_{number:02d}.jpg"), MAX_IMAGE)
    if (len(data) != item["bytes"] or sha256(data).hexdigest() != item["sha256"]
            or not data.startswith(b"\xff\xd8\xff") or not data.endswith(b"\xff\xd9")):
        raise ValueError("Tampered Lidl JPEG")
    return data


def _manifest(root, digest, clock, *, verify_all):
    if not isinstance(digest, str) or not SHA.fullmatch(digest):
        raise ValueError("Missing SHA registration")
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("Timezone-aware clock required")
    data = _read(root, ("capture.json",), MAX_MANIFEST)
    if sha256(data).hexdigest() != digest:
        raise ValueError("Registered source digest drift")
    meta = json.loads(data, object_pairs_hook=_unique)
    if not isinstance(meta, dict):
        raise ValueError("Invalid capture metadata")
    expected = {
        "schema": SCHEMA, "retailer": "lidl", "store_external_id": STORE,
        "store_entity_id": ENTITY, "scope": "physical_store_family_original",
        "region": REGION, "control_region": CONTROL_REGION,
        "source_page": HUB, "valid_from": START.isoformat(),
        "valid_until": END.isoformat(), "state": "candidate_only_unregistered",
        "publication_authorized": False, "pdf_retained": False,
    }
    if any(type(meta.get(k)) is not type(v) or meta.get(k) != v for k,v in expected.items()):
        raise ValueError("Invalid store or source identity")
    fid = meta.get("source_flyer_id")
    if not isinstance(fid, str) or not UUID.fullmatch(fid) or fid != FLYER_ID:
        raise ValueError("Unbound flyer identity")
    for name in ("hub_html_sha256", "api_json_sha256"):
        v = meta.get(name)
        if not isinstance(v, str) or not SHA.fullmatch(v):
            raise ValueError("Missing source SHA")
    observed = datetime.fromisoformat(meta["observed_at"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(meta["expires_at"].replace("Z", "+00:00"))
    if (observed.tzinfo is None or expires.tzinfo is None or observed > clock
            or expires <= clock or expires != observed + timedelta(days=30)):
        raise ValueError("Expired or invalid source retention")
    count = meta.get("page_count")
    if type(count) is not int or not 1 <= count <= MAX_PAGES:
        raise ValueError("Invalid verified page count")
    published = _source(root, meta)
    rows = meta.get("pages")
    if not isinstance(rows, list) or len(rows) != count:
        raise ValueError("Incomplete captured pages")
    total = 0
    for number, (row, source) in enumerate(zip(rows, published), 1):
        if (not isinstance(row, dict) or not isinstance(source, dict)
                or type(row.get("number")) is not int or row["number"] != number
                or type(source.get("number")) is not int or source["number"] != number
                or source.get("type") != "STANDARD"):
            raise ValueError("Unproven original image ordering")
        for quality, field in (("normal", "image"), ("large", "zoom")):
            item = row.get(quality)
            if not isinstance(item, dict) or item.get("path") != f"pages/{quality}/bk_{number:02d}.jpg":
                raise ValueError("Wrong local source path")
            if (item.get("source_url") != source.get(field)
                    or not _image_source(item.get("source_url"), number, quality, fid)):
                raise ValueError("Unverified first-party original image URL")
            size, check = item.get("bytes"), item.get("sha256")
            if (type(size) is not int or not 256 < size <= MAX_IMAGE
                    or not isinstance(check, str) or not SHA.fullmatch(check)):
                raise ValueError("Invalid page integrity metadata")
            total += size
            if total > MAX_TOTAL:
                raise ValueError("Oversized Lidl corpus")
            if verify_all:
                _asset(root, number, quality, item)
    return rows, meta


def _root(root):
    return Path(root) if root is not None else get_settings().raw_snapshot_dir / "lidl-booklets"


def _digest(value):
    return value if value is not None else os.getenv("LIDL_FAMILY_BOOKLET_CAPTURE_SHA256")


def _href(day, n):
    return "/ui/home/?" + urlencode({
        "view": "booklets", "date": day.isoformat(), "page": n, "retailer": "lidl",
    })


def _url(n, quality):
    return f"/ui/home/booklet-assets/lidl/{quality}/{n}"


def read_verified_lidl_booklet(day: date, page: int = 1, *, root=None,
                               manifest_sha256=None, now=None):
    if type(day) is not date or type(page) is not int or not 1 <= page <= 200:
        raise ValueError("Invalid Lidl selected page/date")
    digest = _digest(manifest_sha256)
    if not digest:
        return None
    try:
        rows, meta = _manifest(_root(root), digest, now or datetime.now(timezone.utc), verify_all=True)
        if not START <= day <= END:
            return None
        if page > len(rows):
            return {"state": "missing_page", "offers": [],
                    "message": "Šāda lapa bukletā nav pieejama."}
        return {
            "state": "ready", "offers": [], "page": page, "page_count": len(rows),
            "image_url": _url(page, "normal"),
            "source_url": meta["viewer_url"],
            "store_name": "Lidl · Husener Straße 44, 44319 Dortmund",
            "valid_label": "02.11.2026–07.11.2026", "swipeable": True,
            "pages": [
                {"number": n, "href": _href(day, n), "image_url": _url(n, "normal"),
                 "zoom_image_url": _url(n, "large")} for n in range(1, len(rows)+1)
            ],
            "previous_href": _href(day, page-1) if page > 1 else None,
            "next_href": _href(day, page+1) if page < len(rows) else None,
        }
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError, UnicodeError):
        return dict(UNAVAILABLE)


def read_verified_lidl_image(number: int, quality: str, *, root=None,
                             manifest_sha256=None, now=None):
    if type(number) is not int or not 1 <= number <= MAX_PAGES or quality not in QUALITIES:
        raise ValueError("Invalid Lidl image selection")
    digest = _digest(manifest_sha256)
    if not digest:
        raise ValueError("Lidl booklet not registered")
    directory = _root(root)
    rows, _ = _manifest(directory, digest, now or datetime.now(timezone.utc), verify_all=False)
    if number > len(rows):
        raise ValueError("Nonexistent Lidl original page")
    return _asset(directory, number, quality, rows[number-1][quality])
