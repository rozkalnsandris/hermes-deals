"""Read saved Lidl booklet pages; never collect, render PDFs, or infer products."""
from datetime import date, datetime, time, timedelta, timezone
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urljoin, urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import exists, select

from app.lidl_corpus_import import FAMILY_STORE_EXTERNAL_ID, FAMILY_STORE_NAME, SOURCE_STRATEGY
from app.models import OfferCandidateRecord, SourceSnapshot
from app.settings import get_settings

SHA = re.compile(r"[0-9a-f]{64}\Z")
LIMIT = 16 * 1024 * 1024


def _official(value, hosts, path_re=None):
    if not isinstance(value, str) or not 1 <= len(value) <= 4096:
        raise ValueError("Invalid official Lidl URL")
    if any(ord(c) < 32 or ord(c) == 127 for c in value):
        raise ValueError("Invalid URL character")
    url = urlsplit(value)
    if (url.scheme != "https" or url.netloc not in hosts or url.username or
            url.password or url.fragment or not url.path or
            (path_re is not None and not re.fullmatch(path_re, url.path))):
        raise ValueError("Untrusted official Lidl URL")
    return url


def _source(snapshot, root):
    digest = snapshot.sha256
    if not isinstance(digest, str) or not SHA.fullmatch(digest):
        raise ValueError("Invalid source SHA")
    path = Path(snapshot.snapshot_path or "")
    if path.is_symlink():
        raise ValueError("Symlinked source")
    path = path.resolve(strict=True)
    if path.parent != root / "lidl" or path.name != f"flyer-{digest}.json":
        raise ValueError("Noncanonical Lidl raw file")
    if not isinstance(snapshot.content_bytes, int) or not 0 < snapshot.content_bytes <= LIMIT:
        raise ValueError("Unbounded source bytes")
    with path.open("rb") as handle:
        content = handle.read(LIMIT + 1)
    if len(content) != snapshot.content_bytes or sha256(content).hexdigest() != digest:
        raise ValueError("Lidl source integrity mismatch")
    parsed = json.loads(content)
    if not isinstance(parsed, dict):
        raise ValueError("Lidl source is not an object")
    return parsed


def _publication(snapshot, source):
    flyer = source["flyer"]
    if not isinstance(flyer, dict):
        raise ValueError("Invalid flyer object")
    start, end = date.fromisoformat(flyer["offerStartDate"]), date.fromisoformat(flyer["offerEndDate"])
    if start > end or (end - start).days > 30:
        raise ValueError("Invalid date window")
    observed = datetime.fromisoformat(source["dateTime"].replace("Z", "+00:00"))
    stored = snapshot.collected_at
    if observed.tzinfo is None or stored is None:
        raise ValueError("No source observation timestamp")
    stored = stored.replace(tzinfo=stored.tzinfo or timezone.utc)
    if observed.astimezone(timezone.utc) != stored.astimezone(timezone.utc):
        raise ValueError("Source timestamp mismatch")
    self_path = source["self"]
    if not isinstance(self_path, str) or not self_path.startswith("v4/flyer?"):
        raise ValueError("Invalid source self URL")
    endpoint = urljoin("https://endpoints.leaflets.schwarz/", self_path)
    api = _official(endpoint, {"endpoints.leaflets.schwarz"}, r"/v4/flyer")
    region_args = [v for k, v in parse_qsl(api.query, keep_blank_values=True, max_num_fields=20) if k == "region_id"]
    viewer = flyer["flyerUrlAbsolute"]
    view = _official(viewer, {"www.lidl.de", "lidl.de"}, r"/l/prospekte/[^?#]+/ar/[0-9]+/?")
    region = view.path.rstrip("/").rsplit("/", 1)[-1]
    if region_args != [region] or snapshot.scope != f"physical_store_flyer:r{region}:{start}:{end}":
        raise ValueError("Region/scope mismatch")
    if snapshot.source_url != endpoint or snapshot.final_url != endpoint:
        raise ValueError("Canonical source endpoint mismatch")
    if not str(flyer.get("id") or "").strip():
        raise ValueError("Missing flyer ID")
    if "regions" in flyer:
        regions = flyer["regions"]
        if not isinstance(regions, list) or region not in [
            str(v.get("code")) for v in regions if isinstance(v, dict)
        ]:
            raise ValueError("Region not advertised")
    original = flyer.get("pages")
    if not isinstance(original, list) or not 1 <= len(original) <= 200:
        raise ValueError("Incomplete page inventory")
    pages = {}
    for item in original:
        if not isinstance(item, dict) or type(item.get("number")) is not int:
            raise ValueError("Invalid page")
        number = item["number"]
        if not 1 <= number <= len(original) or number in pages:
            raise ValueError("Invalid page order")
        urls = {}
        for key in ("image", "zoom", "thumbnail"):
            url = item.get(key)
            if url:
                _official(url, {"imgproxy.leaflets.schwarz"})
                urls[key] = url
        image = urls.get("image") or urls.get("zoom")
        if not image:
            raise ValueError("Missing page image")
        pages[number] = {
            "image_url": image,
            "zoom_image_url": urls.get("zoom") if urls.get("zoom") != image else None,
            "source_urls": set(urls.values()),
        }
    if set(pages) != set(range(1, len(original) + 1)):
        raise ValueError("Noncontiguous pages")
    return start, end, region, str(flyer["id"]), viewer, [pages[i] for i in range(1, len(original) + 1)]


def _published_store_binding(db, snapshot, cutoff, start, end, region, flyer_id, viewer, pages):
    rows = db.scalars(select(OfferCandidateRecord).where(
        OfferCandidateRecord.snapshot_id == snapshot.id,
        OfferCandidateRecord.source_chain == "lidl",
        OfferCandidateRecord.source_store_external_id == FAMILY_STORE_EXTERNAL_ID,
        OfferCandidateRecord.collected_at < cutoff,
    ).order_by(OfferCandidateRecord.id).limit(1001)).all()
    if not rows or len(rows) > 1000:
        raise ValueError("No bounded, published family source binding")
    pdf_shas = set()
    for row in rows:
        data = row.raw_payload if isinstance(row.raw_payload, dict) else {}
        page = data.get("page")
        pdf = data.get("source_pdf_sha256")
        if (data.get("source_snapshot_id") != str(snapshot.id) or
                data.get("source_snapshot_sha256") != snapshot.sha256 or
                data.get("official_flyer_id") != flyer_id or data.get("region") != region or
                data.get("channel") != "physical_store" or
                data.get("import_scope_decision") != "in_scope" or
                data.get("db_write_eligible") is not True or
                data.get("production_ready_shadow") is not True or
                data.get("shadow_only") is True or
                type(page) is not int or not 1 <= page <= len(pages) or
                data.get("page_image_url") not in pages[page - 1]["source_urls"] or
                not isinstance(pdf, str) or not SHA.fullmatch(pdf) or
                row.source_url != viewer or row.valid_from is None or row.valid_until is None or
                not start <= row.valid_from <= row.valid_until <= end):
            raise ValueError("Lidl published source/offer identity mismatch")
        pdf_shas.add(pdf)
    if len(pdf_shas) != 1:
        raise ValueError("Mixed PDF identities")
    # Image swipes cannot refresh page-specific offer details server-side.
    return []


def _href(day, page):
    return "/ui/home/?" + urlencode({
        "view": "booklets", "date": day.isoformat(), "page": page, "retailer": "lidl",
    })


def build_lidl_booklet(db, day: date, page: int = 1):
    if type(page) is not int or not 1 <= page <= 200:
        raise ValueError("Invalid booklet page")
    empty = {"state": "unavailable", "offers": [],
             "message": "Šai dienai nav saglabātu, publicētu un pārbaudītu Lidl bukleta lapu."}
    cutoff = datetime.combine(day + timedelta(days=1), time.min, ZoneInfo("Europe/Berlin"))
    bound = exists(select(OfferCandidateRecord.id).where(
        OfferCandidateRecord.snapshot_id == SourceSnapshot.id,
        OfferCandidateRecord.source_chain == "lidl",
        OfferCandidateRecord.source_store_external_id == FAMILY_STORE_EXTERNAL_ID,
    ))
    candidates = db.scalars(select(SourceSnapshot).where(
        SourceSnapshot.source_chain == "lidl",
        SourceSnapshot.strategy_hint == SOURCE_STRATEGY,
        SourceSnapshot.success.is_(True),
        SourceSnapshot.scope.like("physical_store_flyer:r%"),
        SourceSnapshot.collected_at < cutoff, bound,
    ).order_by(SourceSnapshot.collected_at.desc(), SourceSnapshot.id.desc()).limit(50)).all()
    root = get_settings().raw_snapshot_dir.resolve()
    for snapshot in candidates:
        outside = None
        try:
            source = _source(snapshot, root)
            start, end, region, flyer_id, viewer, images = _publication(snapshot, source)
            outside = not start <= day <= end
            if outside:
                continue
            offers = _published_store_binding(db, snapshot, cutoff, start, end, region, flyer_id, viewer, images)
            if page > len(images):
                return {**empty, "state": "missing_page", "message": "Šāda lapa bukletā nav pieejama."}
            return {
                "state": "ready", "offers": offers, "page": page, "page_count": len(images),
                "image_url": images[page - 1]["image_url"], "source_url": viewer,
                "store_name": FAMILY_STORE_NAME,
                "valid_label": f"{start:%d.%m.%Y}–{end:%d.%m.%Y}",
                "snapshot_id": str(snapshot.id), "swipeable": True,
                "pages": [
                    {"number": n, "href": _href(day, n), "image_url": item["image_url"],
                     "zoom_image_url": item["zoom_image_url"]}
                    for n, item in enumerate(images, 1)
                ],
                "previous_href": _href(day, page - 1) if page > 1 else None,
                "next_href": _href(day, page + 1) if page < len(images) else None,
            }
        except (OSError, ValueError, KeyError, TypeError, OverflowError):
            if outside is True:
                continue
            return {**empty, "message": "Saglabātā Lidl bukleta izcelsmi vai lapas nevar pārbaudīt."}
    return empty
