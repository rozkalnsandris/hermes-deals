"""One-shot, owner-LIVE-gated EDEKA Patzer page-image evidence acquisition.

This code does NOT run from the API, cron, workflows or a collector.
EDEKA's normal/large image URLs are unversioned and can rotate weekly:
NEVER publish those mutable URLs as a verified historical publication.
Capture the 34 explicitly pinned original pages, bind SHA256 and retain <=30 days.
The publisher's total page count is not independently proven by this capture.
"""
import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from html import unescape
from html.parser import HTMLParser
import json
import os
from pathlib import Path
import re
from urllib.parse import urljoin, urlsplit
from urllib.request import Request, urlopen

MARKET = "071897"
WEEK_FROM = "2026-11-02"
WEEK_UNTIL = "2026-11-07"
PAGES = 34
SOURCE = "https://www.edeka.de/maerkte/071897/prospekte/"
VIEWER = "https://blaetterkatalog.edeka.de/RHEINRUHR/1897/index.html"
ASSET_BASE = "https://blaetterkatalog.edeka.de/RHEINRUHR/1897/blaetterkatalog/"
QUALITIES = ("normal", "large")
MAX_HTML = 4 * 1024 * 1024
MAX_IMAGE = 6 * 1024 * 1024
MAX_TOTAL = 100 * 1024 * 1024
HEADER = {"User-Agent": "Hermes-Deals-EDEKA-first-party-evidence/1", "Accept-Language": "de-DE"}


def image_url(page, quality):
    if type(page) is not int or not 1 <= page <= PAGES or quality not in QUALITIES:
        raise ValueError("Untrusted EDEKA page request")
    return f"{ASSET_BASE}{quality}/bk_{page}.jpg"


class _IframeFinder(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.sources = []

    def handle_starttag(self, tag, attrs):
        if tag == "iframe":
            values = dict(attrs)
            for key in ("src", "data-src"):
                if values.get(key):
                    self.sources.append(urljoin(SOURCE, values[key]))


def _read(url, limit, content_type, *, open_url=urlopen):
    req = Request(url, headers=HEADER)
    with open_url(req, timeout=30) as reply:
        actual = urlsplit(reply.url)
        expected = urlsplit(url)
        if (reply.status != 200 or actual.scheme != "https"
                or actual.netloc != expected.netloc
                or actual.path != expected.path
                or actual.query != expected.query
                or actual.fragment):
            raise ValueError("Unexpected redirect or EDEKA HTTP status")
        media = reply.headers.get("Content-Type", "").split(";", 1)[0].strip().lower()
        if media != content_type:
            raise ValueError("Unexpected EDEKA content type")
        advertised = reply.headers.get("Content-Length")
        if advertised and (not advertised.isdigit() or int(advertised) > limit):
            raise ValueError("Unbounded source body")
        raw = reply.read(limit + 1)
    if not raw or len(raw) > limit:
        raise ValueError("Empty or oversized source body")
    if content_type == "image/jpeg" and not (
        len(raw) > 256 and raw.startswith(b"\xff\xd8\xff") and raw.endswith(b"\xff\xd9")
    ):
        raise ValueError("Invalid or truncated EDEKA JPEG")
    return raw


def _verify_landing(raw):
    doc = unescape(raw.decode("utf-8", "strict"))
    parser = _IframeFinder()
    parser.feed(doc)
    # The source HTML can have a separate SUUPER catalogue. Match *only*
    # the exact weekly iframe for EDEKA Patzer, never a different market.
    if VIEWER not in parser.sources or parser.sources.count(VIEWER) != 1:
        raise ValueError("EDEKA Patzer weekly viewer not uniquely identified")
    if (not re.search(r"EDEKA\s+Patzer", doc, re.IGNORECASE)
            or "071897" not in doc
            or WEEK_FROM[-2:] != "02"):
        raise ValueError("Unbound EDEKA market")
    # All three values are required: a date pair and its weekly header.
    if not ("02.11.2026" in doc and "07.11.2026" in doc
            and re.search(r"Gültig\s+vom", re.sub(r"<[^>]+>", " ", doc), re.IGNORECASE)):
        raise ValueError("EDEKA week validity not proven")
    return sha256(raw).hexdigest()


def capture(*, open_url=urlopen, now=None):
    """Entire source acquisition happens before any output file is created."""
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("UTC-aware capture timestamp required")
    clock = clock.astimezone(timezone.utc)
    if not datetime(2026, 11, 1, tzinfo=timezone.utc) <= clock < datetime(2026, 11, 8, tzinfo=timezone.utc):
        raise ValueError("Pinned edition capture window has ended")
    landing = _read(SOURCE, MAX_HTML, "text/html", open_url=open_url)
    landing_sha = _verify_landing(landing)
    files = {}
    pages = []
    total = 0
    for number in range(1, PAGES + 1):
        item = {"number": number}
        for quality in QUALITIES:
            url = image_url(number, quality)
            raw = _read(url, MAX_IMAGE, "image/jpeg", open_url=open_url)
            total += len(raw)
            if total > MAX_TOTAL:
                raise ValueError("Unbounded EDEKA source capture")
            rel = f"pages/{quality}/bk_{number:02d}.jpg"
            files[rel] = raw
            item[quality] = {
                "source_url": url, "path": rel,
                "bytes": len(raw), "sha256": sha256(raw).hexdigest(),
            }
        pages.append(item)
    # The unversioned publisher path may change during the crawl.
    # Recheck both covers at the end; no mixed edition is released on drift.
    for number in (1, PAGES):
        for quality in QUALITIES:
            rel = f"pages/{quality}/bk_{number:02d}.jpg"
            if _read(image_url(number, quality), MAX_IMAGE, "image/jpeg", open_url=open_url) != files[rel]:
                raise ValueError("EDEKA source rotated during capture")
    meta = {
        "schema": "edeka_patzer_immutable_page_capture_v1",
        "retailer": "edeka", "public_market_code": MARKET,
        "source_market_id": "587881", "scope": "family_primary_edeka",
        "source_page": SOURCE, "source_html_sha256": landing_sha,
        "viewer_url": VIEWER, "valid_from": WEEK_FROM,
        "valid_until": WEEK_UNTIL, "page_count": PAGES, "pages": pages,
        "observed_at": clock.isoformat(),
        "expires_at": (clock + timedelta(days=30)).isoformat(),
        "state": "candidate_only_unregistered",
        "publisher_urls_may_rotate": True,
        "pdf_retained": False, "publication_authorized": False,
    }
    return meta, files


def save_new_output(directory, meta, files):
    """Single exclusive write phase. A failed partial capture must be inspected;
    no automatic retry, deletion, overwrite or rollback."""
    directory = Path(directory)
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
    print("EDeka_CAPTURE_DIR=" + str(directory))
    print("EDEKA_CAPTURE_MANIFEST_SHA256=" + sha256(manifest_raw).hexdigest())
    print("EDEKA_PAGES_CAPTURED=34 IMAGE_FILES=68")
    print("ACTIVATION=NOT_PERFORMED DB=UNCHANGED DEPLOY=UNCHANGED")


def main():
    ap = argparse.ArgumentParser(description="EDEKA Patzer candidate-only 34-page first-party capture")
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
