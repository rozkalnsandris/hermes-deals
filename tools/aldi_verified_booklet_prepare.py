"""Prepare an unactivated ALDI original-page manifest from two verified PDFs.

This is an explicit, manually authorized acquisition tool, NOT a collector.
It checks all Normal and Zoom page URLs against live first-party iPaper
redirects before it writes one new output file. Never automatically registers
a manifest, changes backend settings, deploys or deletes retained PDFs.
"""
import argparse
from datetime import datetime, timedelta, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import subprocess
from urllib.parse import urlsplit
from urllib.request import Request, urlopen

ROOT = "https://magazine.aldi-nord.de/aldi-nord/aldi-aktuell/2026/"
EXPECTED = (
    {
        "name": "aldi-nord-2026-11-02_2026-11-07.pdf",
        "start": "2026-11-02", "end": "2026-11-07", "pages": 43,
        "sha": "37b4e379b8c8c570049bd0a6de29aa22582980a4ccf7de7ca79464b2c08484f6",
        "bytes": 114790351,
        "slug": "2026cw45mopromotionaldi-angebote-ab-montag-02-11-1",
    },
    {
        "name": "aldi-nord-2026-11-09_2026-11-14.pdf",
        "start": "2026-11-09", "end": "2026-11-14", "pages": 47,
        "sha": "7ac0ff94b3063f45f468c919ae969e75112860f642f7728f9fb0ff32ff3ac1ee",
        "bytes": 139086067,
        "slug": "2026cw46mopromotionaldi-angebote-ab-montag-09-11",
    },
)
UUID = r"[a-f0-9]{8}-(?:[a-f0-9]{4}-){3}[a-f0-9]{12}"
IMAGE_PATH = re.compile(rf"/iPaper/Papers/({UUID})/Pages/(\d+)/(Normal|Zoom)\.jpg\Z")
PDF_MAGIC = b"%PDF-"


def source_url(spec):
    return ROOT + spec["slug"] + "/"


def candidate_image_url(viewer, page, kind):
    """URL is only a candidate until the live redirected image is verified."""
    if type(page) is not int or not 1 <= page <= 200 or kind not in ("Normal", "Zoom"):
        raise ValueError("Invalid page candidate")
    return f"{viewer}Image.ashx?PageNumber={page}&ImageType={kind}"


def validate_image_response(response, page, kind):
    """Validate CDN paper UUID, exact page/quality, range response and magic."""
    if response.status not in (200, 206):
        raise ValueError("Unverified page response status")
    if not response.headers.get("Content-Type", "").lower().startswith("image/jpeg"):
        raise ValueError("Unverified page response media")
    redirected = urlsplit(response.url)
    if (redirected.scheme != "https" or redirected.hostname != "cdn.ipaper.io"
            or redirected.port is not None or redirected.username
            or redirected.password or redirected.fragment):
        raise ValueError("Untrusted page redirect")
    match = IMAGE_PATH.fullmatch(redirected.path)
    if match is None or int(match.group(2)) != page or match.group(3) != kind:
        raise ValueError("Wrong edition page or image quality")
    if response.read(3) != b"\xff\xd8\xff":
        raise ValueError("Invalid JPEG body")
    return match.group(1)


def verified_asset(viewer, number, kind, *, open_url=urlopen):
    candidate = candidate_image_url(viewer, number, kind)
    request = Request(candidate, headers={
        "Range": "bytes=0-7", "User-Agent": "Mozilla/5.0",
        "Referer": "https://www.aldi-nord.de/prospekte.html",
    })
    with open_url(request, timeout=25) as response:
        paper_id = validate_image_response(response, number, kind)
    return candidate, paper_id


def verify_pdf(pdf, spec):
    if pdf.is_symlink() or not pdf.is_file() or pdf.stat().st_size != spec["bytes"]:
        raise ValueError("Missing, symlinked or size-mismatched ALDI PDF")
    digest = sha256()
    with pdf.open("rb") as stream:
        if stream.read(5) != PDF_MAGIC:
            raise ValueError("PDF magic mismatch")
        stream.seek(0)
        for block in iter(lambda: stream.read(1024 * 1024), b""):
            digest.update(block)
    if digest.hexdigest() != spec["sha"]:
        raise ValueError("ALDI source PDF SHA256 mismatch")
    info = subprocess.run(["pdfinfo", str(pdf)], check=True, capture_output=True, text=True, timeout=60)
    match = re.search(r"^Pages:\s*(\d+)\s*$", info.stdout, re.M)
    if not match or int(match.group(1)) != spec["pages"]:
        raise ValueError("ALDI PDF page count mismatch")


def prepare(input_dir, *, now=None, fetch=verified_asset):
    """Read and validate everything without creating or replacing any files."""
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None or input_dir.is_symlink() or not input_dir.is_dir():
        raise ValueError("Unsafe ALDI source directory")
    raw = (input_dir / "manifest.json")
    if raw.is_symlink() or not raw.is_file() or raw.stat().st_size > 32768:
        raise ValueError("Missing or unbounded original acquisition receipt")
    original = json.loads(raw.read_bytes())
    observed = datetime.fromisoformat(original["first_acquired_utc"].replace("Z", "+00:00"))
    expires = datetime.fromisoformat(original["pdf_expiry_utc"].replace("Z", "+00:00"))
    if (observed.tzinfo is None or expires.tzinfo is None
            or observed > now or now >= expires
            or not timedelta(0) < expires - observed <= timedelta(days=30)):
        raise ValueError("Original acquisition expired or not recorded")
    rows = original.get("files")
    if not isinstance(rows, list) or len(rows) != len(EXPECTED):
        raise ValueError("Incomplete ALDI source PDFs")
    publications = []
    paper_ids = set()
    for spec in EXPECTED:
        matches = [row for row in rows if isinstance(row, dict) and row.get("filename") == spec["name"]]
        if len(matches) != 1:
            raise ValueError("Missing or duplicate ALDI edition")
        row = matches[0]
        viewer = source_url(spec)
        expected_pdf_url = viewer + "/GetPDF.ashx"
        if (row.get("official_pdf_url") != expected_pdf_url
                or row.get("sha256") != spec["sha"]
                or row.get("bytes") != spec["bytes"]
                or row.get("pages") != spec["pages"]
                or row.get("valid_from") != spec["start"]
                or row.get("valid_until") != spec["end"]):
            raise ValueError("Acquisition receipt does not match official edition")
        verify_pdf(input_dir / spec["name"], spec)
        pages = []
        edition_id = None
        for number in range(1, spec["pages"] + 1):
            normal, normal_id = fetch(viewer, number, "Normal")
            zoom, zoom_id = fetch(viewer, number, "Zoom")
            if normal_id != zoom_id:
                raise ValueError("Page versions come from different editions")
            if edition_id is None:
                edition_id = normal_id
            if edition_id != normal_id:
                raise ValueError("Mixed paper ID within one ALDI edition")
            pages.append({"number": number, "image_url": normal, "zoom_image_url": zoom})
        if edition_id in paper_ids:
            raise ValueError("Different editions share same iPaper paper ID")
        paper_ids.add(edition_id)
        publications.append({
            "scope": "national_unbound",
            "valid_from": spec["start"], "valid_until": spec["end"],
            "viewer_url": viewer, "pdf_url": expected_pdf_url,
            "pdf_sha256": spec["sha"], "pdf_bytes": spec["bytes"],
            "page_count": spec["pages"], "pages": pages,
        })
    return {
        "schema": "aldi_nord_verified_booklet_v1",
        "observed_at": original["first_acquired_utc"],
        "expires_at": original["pdf_expiry_utc"],
        "publications": publications,
    }


def main():
    parser = argparse.ArgumentParser(description="Verify ALDI PDFs and 180 live page image variants")
    parser.add_argument("--input-dir", type=Path, required=True)
    parser.add_argument("--output-file", type=Path, required=True)
    args = parser.parse_args()
    if args.output_file.name != "verified-manifest.json" or args.output_file.is_symlink():
        parser.error("Output must be new verified-manifest.json")
    if not args.output_file.parent.is_dir() or args.output_file.parent.is_symlink():
        parser.error("Pre-existing non-symlinked output directory required")
    if args.output_file.exists():
        parser.error("Never replace or silently rotate registered evidence")
    result = prepare(args.input_dir)
    raw = (json.dumps(result, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode()
    # Open exclusively only after all source and 180 page-asset checks passed.
    fd = os.open(args.output_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600)
    with os.fdopen(fd, "wb") as out:
        out.write(raw)
        out.flush()
        os.fsync(out.fileno())
    print("VERIFIED_MANIFEST_PATH=" + str(args.output_file))
    print("VERIFIED_MANIFEST_SHA256=" + sha256(raw).hexdigest())
    print("PAGE_CANDIDATES_VERIFIED=90 NORMAL_PLUS_ZOOM=180")
    print("BACKEND_REGISTRATION=NOT_PERFORMED DEPLOY=NOT_PERFORMED")


if __name__ == "__main__":
    main()
