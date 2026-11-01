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
PAGES = 70
SOURCE = "https://filiale.kaufland.de/service/filiale/dortmund-aplerbeck-1503.html"
VIEWER = "https://leaflets.kaufland.com/de-DE/DE_de_KDZ1_1503_D45/ar/1503"
VIEWER_PAGE = "https://leaflets.kaufland.com/de-DE/DE_de_KDZ1_1503_D45/view/flyer/page/"
CDN = "https://imgproxy.leaflets.schwarz/"
QUALITIES = ("normal", "large")
MAX_HTML = 5 * 1024 * 1024
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


def _original(url):
    """Return (page number, original asset path, rendered width)."""
    if not isinstance(url, str) or len(url) > 700:
        return None
    try:
        p = urlsplit(url)
        if (p.scheme != "https" or p.netloc != "imgproxy.leaflets.schwarz"
                or p.query or p.fragment or p.username or p.password):
            return None
        parts = p.path.lstrip("/").split("/")
        if len(parts) != 4 or parts[2] != "g:no":
            return None
        if not re.fullmatch(r"[A-Za-z0-9_-]{40,64}", parts[0]):
            return None
        size = re.fullmatch(r"rs:fit:(800|1200|1600|2400):\1:1", parts[1])
        if not size or not re.fullmatch(r"[A-Za-z0-9_-]+\.jpg", parts[3]):
            return None
        token = parts[3][:-4]
        original = base64.urlsafe_b64decode(token + "=" * (-len(token) % 4)).decode("ascii")
        match = re.fullmatch(
            rf"s3://leaflets/images/{re.escape(FLYER_ID)}/page-(\d{{2}})_[0-9a-f]{{32}}\.png",
            original,
        )
        if match:
            page = int(match.group(1))
            if 1 <= page <= PAGES:
                return page, original, int(size.group(1))
    except (ValueError, TypeError, UnicodeError, binascii.Error):
        pass
    return None


def _image_links(raw):
    text = unescape(raw.decode("utf-8", "strict")).replace("\\u002F", "/").replace("\\/", "/")
    return sorted(set(IMAGE_LINK.findall(text)))


def _verify_store(raw):
    text = unescape(raw.decode("utf-8", "strict"))
    if ("Kaufland Dortmund-Aplerbeck" not in text or "Aplerbecker Marktplatz" not in text
            or "DE_de_KDZ1_1503_D45" not in text or STORE not in text):
        raise ValueError("Wrong or unproven Kaufland store/flyer binding")
    return sha256(raw).hexdigest()


def _verify_viewer(raw):
    text = unescape(raw.decode("utf-8", "strict"))
    if not (re.search(r"01\.11\.2026\s*-\s*07\.11\.2026", text)
            and re.search(r"(?:1\s*/\s*70|pageCount[\\\"]*\s*[:=]\s*70)", text)):
        raise ValueError("Unverified first-party edition dates/page count")


def _choose_urls(htmls):
    groups = {n: {} for n in range(1, PAGES + 1)}
    for html in htmls:
        for url in _image_links(html):
            found = _original(url)
            if not found:
                continue
            number, original, pixels = found
            options = groups[number]
            if options and options["original"] != original:
                raise ValueError("Conflicting original page identities")
            options.setdefault("original", original)
            if pixels not in options or url < options[pixels]:
                options[pixels] = url
    selected = {}
    for number, options in groups.items():
        sizes = sorted(x for x in options if type(x) is int)
        if not sizes:
            raise ValueError(f"Missing verified first-party page {number}")
        normal = 1200 if 1200 in sizes else sizes[0]
        selected[number] = {"normal": options[normal], "large": options[max(sizes)]}
    return selected


def capture(*, open_url=urlopen, now=None):
    clock = now or datetime.now(timezone.utc)
    if clock.tzinfo is None or clock.utcoffset() is None:
        raise ValueError("UTC-aware clock required")
    clock = clock.astimezone(timezone.utc)
    if not datetime(2026, 11, 1, tzinfo=timezone.utc) <= clock < datetime(2026, 11, 8, tzinfo=timezone.utc):
        raise ValueError("Pinned Kaufland capture window ended")
    landing = _read(SOURCE, MAX_HTML, "text/html", open_url=open_url)
    source_sha = _verify_store(landing)
    first = _read(VIEWER_PAGE + "1", MAX_HTML, "text/html", open_url=open_url)
    _verify_viewer(first)
    # Official viewer uses page 1 then even-numbered spread URLs 2-3,
    # 4-5 ... 68-69 and the final single page 70.
    htmls = [first]
    for n in range(2, PAGES + 1, 2):
        htmls.append(_read(VIEWER_PAGE + str(n), MAX_HTML, "text/html", open_url=open_url))
    chosen = _choose_urls(htmls)
    files, pages, total = {}, [], 0
    for number in range(1, PAGES + 1):
        row, downloaded = {"number": number}, {}
        for quality in QUALITIES:
            url = chosen[number][quality]
            if url not in downloaded:
                downloaded[url] = _read(url, MAX_IMAGE, "image/jpeg", open_url=open_url)
            raw = downloaded[url]
            total += len(raw)
            if total > MAX_TOTAL:
                raise ValueError("Unbounded Kaufland page capture")
            path = f"pages/{quality}/bk_{number:02d}.jpg"
            files[path] = raw
            row[quality] = {"source_url": url, "path": path,
                            "bytes": len(raw), "sha256": sha256(raw).hexdigest()}
        pages.append(row)
    if _verify_store(_read(SOURCE, MAX_HTML, "text/html", open_url=open_url)) != source_sha:
        raise ValueError("Kaufland source rotated mid-capture")
    again = _read(VIEWER_PAGE + "1", MAX_HTML, "text/html", open_url=open_url)
    _verify_viewer(again)
    for url in _image_links(again):
        item = _original(url)
        if item and item[0] == 1 and item[1] != _original(chosen[1]["normal"])[1]:
            raise ValueError("Page one edition rotated")
    for number in (1, PAGES):
        for url in set(chosen[number].values()):
            actual = _read(url, MAX_IMAGE, "image/jpeg", open_url=open_url)
            quality = "normal" if url == chosen[number]["normal"] else "large"
            if sha256(actual).hexdigest() != pages[number - 1][quality]["sha256"]:
                raise ValueError("Publisher page changed mid-capture")
    return {
        "schema": "kaufland_aplerbeck_immutable_page_capture_v1",
        "retailer": "kaufland", "store_id": STORE, "source_flyer_id": FLYER_ID,
        "scope": "family_primary_kaufland", "source_page": SOURCE,
        "source_html_sha256": source_sha, "viewer_url": VIEWER,
        "valid_from": START, "valid_until": END, "page_count": PAGES,
        "pages": pages, "observed_at": clock.isoformat(),
        "expires_at": (clock + timedelta(days=30)).isoformat(),
        "state": "candidate_only_unregistered",
        "publisher_urls_may_rotate": True,
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
    print("KAUFLAND_PAGES_CAPTURED=70 IMAGE_FILES=140")
    print("ACTIVATION=NOT_PERFORMED DB=UNCHANGED DEPLOY=UNCHANGED")


def main():
    ap = argparse.ArgumentParser(description="KAUFLAND Patzer candidate-only 70-page first-party capture")
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
