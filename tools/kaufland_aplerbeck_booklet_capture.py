"""Owner-LIVE-gated one-shot Kaufland Aplerbeck original-image capture.

Fetch only first-party publisher-declared 70 signed image URLs. No guessed
URLs, offer identity, collector, publication or automatic activation.
"""
import argparse
import base64
import binascii
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import unescape
import json
import os
from pathlib import Path
import re
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

STORE = "1503"
FLYER_ID = "01a1831f-2f9c-7e3d-96ff-72c3cf783f80"
START, END = "2026-11-01", "2026-11-07"
PAGES = 69
SOURCE = "https://filiale.kaufland.de/service/filiale/dortmund-aplerbeck-1503.html"
VIEWER = "https://leaflets.kaufland.com/de-DE/DE_de_KDZ1_1503_D45/ar/1503"
API = "https://endpoints.leaflets.schwarz/v4/flyer?flyer_identifier=DE_de_KDZ1_1503_D45&region_id=1503&region_code=1503"
PROMOTION_ID = "01a17c12-30f4-7598-8e9f-60efaead0abe"
PROMOTION_ORIGINAL = "s3://leaflets/flyer_promotions/01a17c12-30f4-7598-8e9f-60efaead0abe/image_1457x2400_10-29-2026_10-43-26.jpg"
CDN = "https://imgproxy.leaflets.schwarz/"
QUALITIES = ("normal", "large")
MAX_HTML = 5 * 1024 * 1024
MAX_JSON = 3 * 1024 * 1024
MAX_IMAGE = 6 * 1024 * 1024
MAX_TOTAL = 100 * 1024 * 1024
MAX_MANIFEST = 256 * 1024
HEADER = {"User-Agent": "HermesDeals-Kaufland-first-party-capture/1",
          "Accept-Language": "de-DE,de;q=0.9"}
IMAGE_LINK = re.compile(r"https://imgproxy\.leaflets\.schwarz/[A-Za-z0-9_:/.-]+?\.jpg")


def _read(url, limit, mime, *, open_url=urlopen):
    request = Request(url, headers=HEADER)
    with open_url(request, timeout=30) as reply:
        expected, actual = urlsplit(url), urlsplit(reply.url)
        if (reply.status != 200
                or (actual.scheme, actual.netloc, actual.path, actual.query)
                   != (expected.scheme, expected.netloc, expected.path, expected.query)
                or actual.fragment):
            raise ValueError("Unexpected first-party redirect or response")
        media = reply.headers.get("Content-Type", "").split(";", 1)[0].lower().strip()
        if media != mime:
            raise ValueError("Wrong original source Content-Type")
        advertised = reply.headers.get("Content-Length")
        if advertised is not None and (not advertised.isdecimal() or int(advertised) > limit):
            raise ValueError("Unbounded original source")
        raw = reply.read(limit + 1)
    if not raw or len(raw) > limit:
        raise ValueError("Missing or oversized source")
    if mime == "image/jpeg" and (len(raw) <= 256 or not raw.startswith(b"\xff\xd8\xff")
                                or not raw.endswith(b"\xff\xd9")):
        raise ValueError("Invalid original JPEG")
    return raw


def _image_source(url, number, quality):
    """Validate signed CDN address and decoded first-party original identity."""
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
                or not re.fullmatch(r"[A-Za-z0-9_-]+\.jpg", parts[3])):
            return False
        token = parts[3][:-4]
        original = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("ascii")
        if 1 <= number <= 68:
            size = "rs:fit:1200:1200:1" if quality == "normal" else "rs:fit:2400:2400:1"
            if parts[1] != size:
                return False
            return bool(re.fullmatch(
                rf"s3://leaflets/images/{re.escape(FLYER_ID)}/page-{number:02d}_[0-9a-f]{{32}}\.png",
                original,
            ))
        if number == 69:
            size = "rs:fill:729:1200:1" if quality == "normal" else "rs:fill:1458:2400:1"
            return parts[1] == size and original == PROMOTION_ORIGINAL
        return False
    except (ValueError, UnicodeError, binascii.Error, TypeError):
        return False


def _verify_store(raw):
    text = unescape(raw.decode("utf-8", "strict"))
    if ("Kaufland Dortmund-Aplerbeck" not in text or "Aplerbecker Marktplatz" not in text
            or "DE_de_KDZ1_1503_D45" not in text or STORE not in text):
        raise ValueError("Wrong or unproven Kaufland store/flyer binding")
    return sha256(raw).hexdigest()


def _unique(pairs):
    result = {}
    for key, val in pairs:
        if key in result:
            raise ValueError("Duplicate first-party API metadata key")
        result[key] = val
    return result


def _verify_api(raw):
    data = json.loads(raw, object_pairs_hook=_unique)
    if (not isinstance(data, dict) or data.get("success") is not True
            or data.get("version") != 4 or not isinstance(data.get("flyer"), dict)):
        raise ValueError("Unverified first-party flyer API response")
    flyer = data["flyer"]
    expected = {
        "id": FLYER_ID, "startDate": START, "endDate": END,
        "title": "01.11.2026 - 07.11.2026", "flyerUrlAbsolute": VIEWER,
        "status": "current", "isActive": True,
    }
    if any(type(flyer.get(k)) is not type(v) or flyer.get(k) != v for k, v in expected.items()):
        raise ValueError("Wrong Kaufland flyer edition or active state")
    regions = flyer.get("regions")
    if (not isinstance(regions, list)
            or not any(isinstance(r, dict) and r.get("code") == STORE for r in regions)):
        raise ValueError("Exact store region not published")
    pages = flyer.get("pages")
    if not isinstance(pages, list) or len(pages) != PAGES:
        raise ValueError("Unexpected original-image page count")
    for number, page in enumerate(pages, 1):
        if not isinstance(page, dict) or type(page.get("number")) is not int or page["number"] != number:
            raise ValueError("Noncontiguous first-party page list")
        if number <= 68:
            if page.get("type") != "STANDARD" or page.get("promotionId") is not None:
                raise ValueError("Unexpected original flyer page type")
        elif page.get("type") != "PROMOTION" or page.get("promotionId") != PROMOTION_ID:
            raise ValueError("Unexpected separate promotional page")
        for quality, field in (("normal", "image"), ("large", "zoom")):
            if not _image_source(page.get(field), number, quality):
                raise ValueError(f"Untrusted page {number} {quality} original URL")
    return pages


def capture(*, open_url=urlopen, now=None):
    """Read original publisher API and every JPEG before any output write."""
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("UTC-aware clock required")
    clock = clock.astimezone(timezone.utc)
    if not datetime(2026, 11, 1, tzinfo=timezone.utc) <= clock < datetime(2026, 11, 8, tzinfo=timezone.utc):
        raise ValueError("Pinned Kaufland capture window ended")
    landing = _read(SOURCE, MAX_HTML, "text/html", open_url=open_url)
    source_sha = _verify_store(landing)
    api_raw = _read(API, MAX_JSON, "application/json", open_url=open_url)
    published = _verify_api(api_raw)
    files, pages, total = {}, [], 0
    for number, page in enumerate(published, 1):
        row = {"number": number}
        for quality, field in (("normal", "image"), ("large", "zoom")):
            url = page[field]
            data = _read(url, MAX_IMAGE, "image/jpeg", open_url=open_url)
            total += len(data)
            if total > MAX_TOTAL:
                raise ValueError("Unbounded Kaufland source capture")
            rel = f"pages/{quality}/bk_{number:02d}.jpg"
            files[rel] = data
            row[quality] = {
                "source_url": url, "path": rel, "bytes": len(data),
                "sha256": sha256(data).hexdigest(),
            }
        pages.append(row)
    # The official publisher may rotate a shared alias. Fail closed on drift.
    if _verify_store(_read(SOURCE, MAX_HTML, "text/html", open_url=open_url)) != source_sha:
        raise ValueError("Kaufland market source rotated during capture")
    fresh_api = _read(API, MAX_JSON, "application/json", open_url=open_url)
    _verify_api(fresh_api)
    if fresh_api != api_raw:
        raise ValueError("Kaufland flyer API rotated during capture")
    for number in (1, PAGES):
        for quality, field in (("normal", "image"), ("large", "zoom")):
            rel = f"pages/{quality}/bk_{number:02d}.jpg"
            if _read(published[number - 1][field], MAX_IMAGE, "image/jpeg", open_url=open_url) != files[rel]:
                raise ValueError("Publisher original image rotated during capture")
    return {
        "schema": "kaufland_aplerbeck_immutable_page_capture_v1",
        "retailer": "kaufland", "store_id": STORE, "source_flyer_id": FLYER_ID,
        "scope": "family_primary_kaufland", "source_page": SOURCE,
        "source_html_sha256": source_sha, "api_json_sha256": sha256(api_raw).hexdigest(),
        "viewer_url": VIEWER, "valid_from": START, "valid_until": END,
        "page_count": PAGES, "pages": pages, "observed_at": clock.isoformat(),
        "expires_at": (clock + timedelta(days=30)).isoformat(),
        "state": "candidate_only_unregistered", "publisher_urls_may_rotate": True,
        "pdf_retained": False, "publication_authorized": False,
    }, files


def save_new_output(directory, meta, files):
    """Single exclusive write phase. A failed partial capture must be inspected;
    no automatic retry, deletion, overwrite or rollback."""
    directory = Path(directory)
    if not directory.is_absolute():
        raise ValueError("Absolute output directory required")
    parent = directory.parent
    if (not parent.is_dir() or parent.is_symlink()
            or directory.exists() or directory.is_symlink()):
        raise ValueError("Unsafe or existing capture destination")
    if set(files) != {
        f"pages/{quality}/bk_{page:02d}.jpg"
        for page in range(1, PAGES + 1) for quality in QUALITIES
    }:
        raise ValueError("Incomplete or unexpected captured file set")
    for info in meta["pages"]:
        for quality in QUALITIES:
            item = info[quality]
            raw = files[item["path"]]
            if sha256(raw).hexdigest() != item["sha256"] or len(raw) != item["bytes"]:
                raise ValueError("Manifest does not match source bytes")
    manifest_raw = (json.dumps(meta, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    if len(manifest_raw) > MAX_MANIFEST:
        raise ValueError("Oversized candidate manifest")
    os.mkdir(directory, 0o700)
    for quality in QUALITIES:
        (directory / "pages" / quality).mkdir(parents=True, mode=0o700)
    for relative, raw in sorted(files.items()):
        target = directory / relative
        fd = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
        with os.fdopen(fd, "wb") as file:
            file.write(raw)
            file.flush()
            os.fsync(file.fileno())
    final = directory / "capture.json"
    fd = os.open(final, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o400)
    with os.fdopen(fd, "wb") as file:
        file.write(manifest_raw)
        file.flush()
        os.fsync(file.fileno())
    print("KAUFLAND_CAPTURE_DIR=" + str(directory))
    print("KAUFLAND_CAPTURE_MANIFEST_SHA256=" + sha256(manifest_raw).hexdigest())
    print("KAUFLAND_PAGES_CAPTURED=69 IMAGE_FILES=138")
    print("ACTIVATION=NOT_PERFORMED DB=UNCHANGED DEPLOY=UNCHANGED")


def main():
    ap = argparse.ArgumentParser(description="Kaufland Aplerbeck candidate-only 69-image-page first-party capture")
    ap.add_argument("--output-dir", type=Path, required=True,
                    help="Absolute, new, exclusive owner-authorized capture directory")
    args = ap.parse_args()
    if not args.output_dir.is_absolute():
        ap.error("Absolute output directory required")
    if args.output_dir.exists() or args.output_dir.is_symlink():
        ap.error("Output already exists: no retries or overwrite")
    metadata, assets = capture()
    save_new_output(args.output_dir, metadata, assets)


if __name__ == "__main__":
    main()
