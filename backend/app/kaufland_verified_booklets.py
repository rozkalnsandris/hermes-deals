"""Fail-closed local image reader for separately registered Kaufland Dortmund-Aplerbeck capture.

Source-only: no collector, HTTP fetch, file mutation, or implicit activation.
The upstream page URLs rotate; serve only locally SHA256-checked bytes.
"""
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from pathlib import Path
from urllib.parse import urlencode, urlsplit
import base64
import binascii
import json
import os
import re
import stat

from app.settings import get_settings

SCHEMA = "kaufland_aplerbeck_immutable_page_capture_v1"
SOURCE = "https://filiale.kaufland.de/service/filiale/dortmund-aplerbeck-1503.html"
VIEWER = "https://leaflets.kaufland.com/de-DE/DE_de_KDZ1_1503_D45/ar/1503"
IMAGE_BASE = "https://imgproxy.leaflets.schwarz/"
FLYER_ID = "01a1831f-2f9c-7e3d-96ff-72c3cf783f80"
START, END = date(2026, 11, 1), date(2026, 11, 7)
COUNT = 70
QUALITIES = ("normal", "large")
SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_MANIFEST = 256 * 1024
MAX_IMAGE = 6 * 1024 * 1024
MAX_TOTAL = 100 * 1024 * 1024
UNAVAILABLE = {"state": "unavailable", "offers": [],
               "message": "Reģistrētās Kaufland Dortmund-Aplerbeck bukleta lapas pašlaik nevar pārbaudīt."}


def _unique(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError("Duplicate metadata key")
        result[key] = value
    return result


def _read_file(root: Path, components: tuple[str, ...], limit: int) -> bytes:
    """Open only bounded, fixed-path regular files without following symlinks."""
    if not root.is_absolute() or root.is_symlink() or not root.is_dir():
        raise ValueError("Untrusted KAUFLAND evidence root")
    flags = os.O_RDONLY | os.O_NOFOLLOW
    directory = os.open(root, flags | os.O_DIRECTORY)
    try:
        for component in components[:-1]:
            if component in (".", "..") or not re.fullmatch(r"[a-zA-Z0-9_.-]+", component):
                raise ValueError("Invalid directory component")
            child = os.open(component, flags | os.O_DIRECTORY, dir_fd=directory)
            os.close(directory)
            directory = child
        name = components[-1]
        if name in (".", "..") or not re.fullmatch(r"[a-zA-Z0-9_.-]+", name):
            raise ValueError("Invalid file component")
        fd = os.open(name, flags, dir_fd=directory)
        with os.fdopen(fd, "rb") as stream:
            info = os.fstat(stream.fileno())
            if not stat.S_ISREG(info.st_mode) or not 0 < info.st_size <= limit:
                raise ValueError("Not a bounded regular source file")
            data = stream.read(limit + 1)
        if len(data) != info.st_size:
            raise ValueError("Source file changed during read")
        return data
    finally:
        os.close(directory)


def _valid_image_url(url, number):
    if not isinstance(url, str) or len(url) > 700:
        return False
    try:
        parsed = urlsplit(url)
        if (parsed.scheme != "https" or parsed.netloc != "imgproxy.leaflets.schwarz"
                or parsed.query or parsed.fragment or parsed.username or parsed.password):
            return False
        parts = parsed.path.lstrip("/").split("/")
        if len(parts) != 4 or parts[2] != "g:no":
            return False
        if (not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", parts[0])
                or not re.fullmatch(r"rs:fit:(800|1200|1600|2400):\1:1", parts[1])
                or not re.fullmatch(r"[A-Za-z0-9_-]+\.jpg", parts[3])):
            return False
        token = parts[3][:-4]
        raw = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("ascii")
        return bool(re.fullmatch(
            rf"s3://leaflets/images/{re.escape(FLYER_ID)}/page-{number:02d}_[0-9a-f]{{32}}\.png",
            raw,
        ))
    except (ValueError, UnicodeError, TypeError, binascii.Error):
        return False


def _asset(root, number, quality, entry):
    raw = _read_file(root, ("pages", quality, f"bk_{number:02d}.jpg"), MAX_IMAGE)
    if (len(raw) != entry["bytes"] or sha256(raw).hexdigest() != entry["sha256"]
            or not raw.startswith(b"\xff\xd8\xff") or not raw.endswith(b"\xff\xd9")):
        raise ValueError("Tampered or truncated KAUFLAND JPEG")
    return raw


def _manifest(root, digest, clock, *, verify_all):
    if not isinstance(digest, str) or not SHA.fullmatch(digest):
        raise ValueError("Missing exact SHA256 registration")
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("Invalid clock")
    raw = _read_file(root, ("capture.json",), MAX_MANIFEST)
    if sha256(raw).hexdigest() != digest:
        raise ValueError("Capture manifest digest mismatch")
    meta = json.loads(raw, object_pairs_hook=_unique)
    if not isinstance(meta, dict):
        raise ValueError("Invalid manifest")
    expected = {
        "schema": SCHEMA, "retailer": "kaufland", "store_id": "1503",
        "source_flyer_id": FLYER_ID, "scope": "family_primary_kaufland",
        "source_page": SOURCE, "viewer_url": VIEWER,
        "valid_from": START.isoformat(), "valid_until": END.isoformat(),
        "state": "candidate_only_unregistered",
        "publisher_urls_may_rotate": True, "pdf_retained": False,
        "publication_authorized": False, "page_count": COUNT,
    }
    if any(type(meta.get(k)) is not type(v) or meta.get(k) != v for k, v in expected.items()):
        raise ValueError("Wrong market, edition or source provenance")
    html_sha = meta.get("source_html_sha256")
    if not isinstance(html_sha, str) or not SHA.fullmatch(html_sha):
        raise ValueError("Missing source HTML digest")
    observed = datetime.fromisoformat(meta["observed_at"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(meta["expires_at"].replace("Z", "+00:00"))
    if (observed.tzinfo is None or expires.tzinfo is None or observed > clock
            or expires <= clock or expires != observed + timedelta(days=30)):
        raise ValueError("Invalid or expired image retention")
    pages = meta.get("pages")
    if not isinstance(pages, list) or len(pages) != COUNT:
        raise ValueError("Incomplete page coverage")
    total = 0
    for number, row in enumerate(pages, 1):
        if not isinstance(row, dict) or type(row.get("number")) is not int or row["number"] != number:
            raise ValueError("Noncontiguous pages")
        for quality in QUALITIES:
            item = row.get(quality)
            if (not isinstance(item, dict)
                    or item.get("path") != f"pages/{quality}/bk_{number:02d}.jpg"
                    or not _valid_image_url(item.get("source_url"), number)):
                raise ValueError("Wrong original image source or path")
            size, check = item.get("bytes"), item.get("sha256")
            if (type(size) is not int or not 256 < size <= MAX_IMAGE
                    or not isinstance(check, str) or not SHA.fullmatch(check)):
                raise ValueError("Invalid image integrity metadata")
            total += size
            if total > MAX_TOTAL:
                raise ValueError("Oversized original capture")
            if verify_all:
                _asset(root, number, quality, item)
    return pages


def _root(root):
    return Path(root) if root is not None else get_settings().raw_snapshot_dir / "kaufland-booklets"


def _digest(sha):
    return sha if sha is not None else os.environ.get("KAUFLAND_APLERBECK_CAPTURE_SHA256")


def _href(day, number):
    return "/ui/home/?" + urlencode({"view": "booklets", "date": day.isoformat(),
                                     "page": number, "retailer": "kaufland"})


def _url(number, quality):
    return f"/ui/home/booklet-assets/kaufland/{quality}/{number}"


def read_verified_kaufland_booklet(day: date, page: int = 1, *, root=None,
                                manifest_sha256=None, now=None):
    if type(day) is not date or type(page) is not int or not 1 <= page <= 200:
        raise ValueError("Invalid KAUFLAND selected page/date")
    digest = _digest(manifest_sha256)
    if not digest:
        return None
    try:
        pages = _manifest(_root(root), digest, now or datetime.now(timezone.utc),
                          verify_all=True)
        if not START <= day <= END:
            return None
        if page > COUNT:
            return {"state": "missing_page", "offers": [],
                    "message": "Šāda lapa bukletā nav pieejama."}
        return {
            "state": "ready", "offers": [], "page": page, "page_count": COUNT,
            "image_url": _url(page, "normal"), "source_url": VIEWER,
            "store_name": "Kaufland Dortmund-Aplerbeck · Aplerbecker Marktplatz 7–10, Dortmund",
            "valid_label": "01.11.2026–07.11.2026", "swipeable": True,
            "pages": [
                {"number": n, "href": _href(day, n), "image_url": _url(n, "normal"),
                 "zoom_image_url": _url(n, "large")} for n in range(1, len(pages) + 1)
            ],
            "previous_href": _href(day, page - 1) if page > 1 else None,
            "next_href": _href(day, page + 1) if page < COUNT else None,
        }
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return dict(UNAVAILABLE)


def read_verified_kaufland_image(number: int, quality: str, *, root=None,
                              manifest_sha256=None, now=None):
    if type(number) is not int or not 1 <= number <= COUNT or quality not in QUALITIES:
        raise ValueError("Invalid KAUFLAND image selection")
    digest = _digest(manifest_sha256)
    if not digest:
        raise ValueError("KAUFLAND booklet not registered")
    directory = _root(root)
    pages = _manifest(directory, digest, now or datetime.now(timezone.utc),
                      verify_all=False)
    return _asset(directory, number, quality, pages[number - 1][quality])
