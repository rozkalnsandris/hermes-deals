"""Read only explicitly registered ALDI Nord page metadata for the shared reader.

An on-disk manifest does not constitute trust: publication is disabled unless
the owner separately registers its exact SHA256 in an environment variable.
Source acquisition, image/PDF retention and activation are distinct LIVE gates.
"""
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urlsplit

from app.settings import get_settings

MANIFEST_NAME = "verified-manifest.json"
SHA = re.compile(r"[0-9a-f]{64}\Z")
MAX_BYTES = 256 * 1024
MAX_PAGES = 200
PDF_LIMIT = 190 * 1024 * 1024
IMAGE_HOSTS = {"magazine.aldi-nord.de", "ipaper.ipapercms.dk"}


def _no_duplicate_fields(pairs):
    obj = {}
    for key, value in pairs:
        if key in obj:
            raise ValueError("Duplicate manifest field")
        obj[key] = value
    return obj


def _https(value, host):
    if not isinstance(value, str) or not 1 <= len(value) <= 2048:
        raise ValueError("Missing or oversized official URL")
    if any(ord(char) < 32 or ord(char) == 127 for char in value):
        raise ValueError("Invalid URL characters")
    parsed = urlsplit(value)
    if (parsed.scheme != "https" or parsed.hostname != host
            or parsed.port is not None or parsed.username or parsed.password
            or parsed.fragment):
        raise ValueError("Untrusted official URL")
    return parsed


def _viewer(value):
    parsed = _https(value, "magazine.aldi-nord.de")
    path = parsed.path
    if (parsed.query or not re.fullmatch(
        r"/aldi-nord/aldi-aktuell/[0-9]{4}/[A-Za-z0-9_-]{8,160}/", path
    )):
        raise ValueError("Invalid immutable ALDI edition URL")
    return value


def _image(url, viewer, number, kind):
    parsed = urlsplit(url) if isinstance(url, str) else None
    if parsed is None or parsed.hostname not in IMAGE_HOSTS:
        raise ValueError("Untrusted page host")
    parsed = _https(url, parsed.hostname)
    # Explicit per-page URLs only; none are synthesized from an image template.
    if parsed.path != urlsplit(viewer).path + "Image.ashx":
        raise ValueError("Page image is from a different edition")
    try:
        query = parse_qsl(parsed.query, keep_blank_values=True, max_num_fields=4)
    except ValueError as exc:
        raise ValueError("Invalid image query") from exc
    if sorted(query) != sorted([("PageNumber", str(number)), ("ImageType", kind)]):
        raise ValueError("Image page and resolution do not match evidence")
    return url


def _publication(record):
    if not isinstance(record, dict) or record.get("scope") != "national_unbound":
        raise ValueError("Unverified ALDI region or scope")
    start, end = date.fromisoformat(record["valid_from"]), date.fromisoformat(record["valid_until"])
    if start > end or (end - start).days > 14:
        raise ValueError("Invalid publisher validity")
    viewer = _viewer(record["viewer_url"])
    pdf_url = record["pdf_url"]
    _https(pdf_url, "magazine.aldi-nord.de")
    if pdf_url not in (viewer + "GetPDF.ashx", viewer + "/GetPDF.ashx"):
        raise ValueError("PDF does not belong to the viewer")
    if not isinstance(record.get("pdf_sha256"), str) or not SHA.fullmatch(record["pdf_sha256"]):
        raise ValueError("Missing verified PDF SHA256")
    size = record.get("pdf_bytes")
    if type(size) is not int or not 1024 <= size <= PDF_LIMIT:
        raise ValueError("Invalid original PDF size")
    pages = record.get("pages")
    if not isinstance(pages, list) or not 1 <= len(pages) <= MAX_PAGES:
        raise ValueError("Incomplete ALDI page list")
    verified = []
    for index, entry in enumerate(pages, 1):
        if not isinstance(entry, dict) or type(entry.get("number")) is not int or entry["number"] != index:
            raise ValueError("Noncontiguous ALDI page numbers")
        verified.append({
            "number": index,
            "image_url": _image(entry.get("image_url"), viewer, index, "Normal"),
            "zoom_image_url": _image(entry.get("zoom_image_url"), viewer, index, "Zoom"),
        })
    if record.get("page_count") != len(verified) or type(record.get("page_count")) is not int:
        raise ValueError("Publisher page count mismatch")
    return start, end, viewer, verified


def _page_href(day, number):
    return "/ui/home/?" + urlencode({
        "view": "booklets", "date": day.isoformat(), "page": number,
        "retailer": "aldi_nord",
    })


def _registered_manifest(root, digest):
    if not isinstance(digest, str) or not SHA.fullmatch(digest):
        raise ValueError("Unregistered or malformed ALDI manifest SHA")
    if root.is_symlink() or not root.is_dir():
        raise ValueError("Missing or symlinked manifest directory")
    path = root / MANIFEST_NAME
    if path.is_symlink() or not path.is_file():
        raise ValueError("Missing or symlinked ALDI manifest")
    with path.open("rb") as handle:
        raw = handle.read(MAX_BYTES + 1)
    if not 0 < len(raw) <= MAX_BYTES or sha256(raw).hexdigest() != digest:
        raise ValueError("Registered ALDI manifest integrity failure")
    doc = json.loads(raw, object_pairs_hook=_no_duplicate_fields)
    if not isinstance(doc, dict) or doc.get("schema") != "aldi_nord_verified_booklet_v1":
        raise ValueError("Unknown ALDI publication registry")
    return doc


def read_verified_aldi_booklet(day: date, page: int = 1, *, root=None,
                               manifest_sha256=None, now=None):
    """Return None ONLY if registration is absent, never for corrupt evidence."""
    if type(page) is not int or not 1 <= page <= MAX_PAGES:
        raise ValueError("Invalid ALDI page")
    digest = (manifest_sha256 if manifest_sha256 is not None
              else os.environ.get("ALDI_NORD_BOOKLET_MANIFEST_SHA256"))
    if not digest:
        return None  # Explicitly no publication: preserve official catalogue.
    directory = (Path(root) if root is not None else
                 get_settings().raw_snapshot_dir / "aldi-booklets")
    unavailable = {
        "state": "unavailable", "offers": [],
        "message": "Reģistrētā ALDI Nord bukleta avotu pašlaik nevar verificēt.",
    }
    try:
        manifest = _registered_manifest(directory, digest)
        observed = datetime.fromisoformat(manifest["observed_at"].replace("Z", "+00:00"))
        expires = datetime.fromisoformat(manifest["expires_at"].replace("Z", "+00:00"))
        clock = now or datetime.now(timezone.utc)
        if (observed.tzinfo is None or expires.tzinfo is None
                or clock.tzinfo is None or observed > clock
                or expires <= clock or not timedelta(0) < expires - observed <= timedelta(days=30)):
            raise ValueError("Unverified or expired raw publication evidence")
        entries = manifest["publications"]
        if not isinstance(entries, list) or not 1 <= len(entries) <= 4:
            raise ValueError("Invalid publication catalogue")
        selected = []
        windows = []
        for entry in entries:
            start, end, viewer, pages = _publication(entry)
            if any(not (end < earlier or start > later) for earlier, later in windows):
                raise ValueError("Overlapping ALDI validity")
            windows.append((start, end))
            if start <= day <= end:
                selected.append((start, end, viewer, pages))
        if not selected:
            return None
        start, end, viewer, pages = selected[0]
        if page > len(pages):
            return {"state": "missing_page", "offers": [], "message": "Šāda lapa bukletā nav pieejama."}
        return {
            "state": "ready", "offers": [], "page": page,
            "page_count": len(pages),
            "image_url": pages[page - 1]["image_url"],
            "source_url": viewer,
            "store_name": "ALDI Nord · valsts buklets (filiāle nav piesaistīta)",
            "valid_label": f"{start:%d.%m.%Y}–{end:%d.%m.%Y}",
            "swipeable": True,
            "pages": [{**entry, "href": _page_href(day, entry["number"])} for entry in pages],
            "previous_href": _page_href(day, page - 1) if page > 1 else None,
            "next_href": _page_href(day, page + 1) if page < len(pages) else None,
        }
    except (OSError, ValueError, TypeError, KeyError, IndexError, AttributeError):
        return unavailable
