"""Read saved Netto publication metadata for the booklet UI; no PDF or network I/O."""
from collections import OrderedDict
from datetime import date, datetime, time, timedelta
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import parse_qsl, urlencode, urlsplit
from zoneinfo import ZoneInfo

from sqlalchemy import select

from app.models import OfferCandidateRecord, SourceSnapshot
from app.retailer_targeted_shadow import publication_page_paths, publitas_page_image_url
from app.settings import get_settings
from app.netto_store_prospect import extract_prospect_validity
from app.netto_html_publications import validated_pages
from app.structured_source_shadow import extract_netto_group_slug

STRATEGIES = (
    "netto_store_page_plus_current_prospect_v1",
    "netto_store_page_plus_current_prospect_pdf_v2",
    "netto_store_page_plus_current_prospect_pdf_v3",
)
STORE = "5659"
MAX_JSON = 2 * 1024 * 1024
_TEASER_STARTS_CACHE_LIMIT = 8
# Cache only the derived result, never unverified source bytes or household data.
_TEASER_STARTS_CACHE: OrderedDict[str, tuple[tuple[str, date], ...]] = OrderedDict()


def _verified_json(path_value, digest, root):
    if not isinstance(path_value, str) or not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Missing metadata binding")
    path = Path(path_value).resolve(strict=True)
    if not path.is_relative_to(root) or path.suffix != ".json":
        raise ValueError("Metadata outside raw root")
    with path.open("rb") as handle:
        content = handle.read(MAX_JSON + 1)
    if len(content) > MAX_JSON or sha256(content).hexdigest() != digest:
        raise ValueError("Metadata integrity failure")
    data = json.loads(content)
    if not isinstance(data, dict):
        raise ValueError("Metadata must be an object")
    return data


def _verified_teaser_starts(raw: bytes, digest: str) -> dict[str, date]:
    """Memoize costly HTML parsing *after* verifying these exact source bytes.

    Callers still run _verified_html on each request. A changed or missing raw
    file must fail closed rather than being hidden by the derived-value cache.
    Cached values are immutable; return a fresh mapping to prevent mutation.
    """
    if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise ValueError("Invalid Netto HTML SHA")
    if sha256(raw).hexdigest() != digest:
        raise ValueError("Netto teaser source integrity failure")

    cached = _TEASER_STARTS_CACHE.get(digest)
    if cached is not None:
        _TEASER_STARTS_CACHE.move_to_end(digest)
        return dict(cached)

    from app.netto_booklet_teasers import extract_netto_booklet_teaser_starts
    parsed = extract_netto_booklet_teaser_starts(raw.decode("utf-8", errors="replace"), STORE)
    cached = tuple(sorted(parsed.items()))
    _TEASER_STARTS_CACHE[digest] = cached
    _TEASER_STARTS_CACHE.move_to_end(digest)
    while len(_TEASER_STARTS_CACHE) > _TEASER_STARTS_CACHE_LIMIT:
        _TEASER_STARTS_CACHE.popitem(last=False)
    return dict(cached)


def _store_url_key(value):
    """Compare the request/final URL without losing selected-branch evidence."""
    url = urlsplit(value)
    if (url.scheme != "https" or url.netloc not in {"www.netto-online.de", "netto-online.de"}
            or url.username or url.fragment
            or not url.path.startswith("/filialen/") or not url.path.endswith("/" + STORE)):
        raise ValueError("Invalid store URL")
    query = parse_qsl(url.query, keep_blank_values=True, max_num_fields=20)
    selected = [value for key, value in query if key == "stores_id"]
    if selected and selected != [STORE]:
        raise ValueError("Conflicting selected store")
    return url.netloc, url.path, sorted((key, value) for key, value in query if key != "stores_id")


def booklet_href(day, page):
    return "/ui/home/?" + urlencode({"view": "booklets", "date": day.isoformat(), "page": page})


def _verified_html(path_value, digest, root):
    if not isinstance(path_value, str) or not isinstance(digest, str):
        raise ValueError("Missing Netto HTML source binding")
    if re.fullmatch(r"[0-9a-f]{64}", digest) is None:
        raise ValueError("Invalid Netto HTML SHA")
    path = Path(path_value)
    if path.is_symlink():
        raise ValueError("Symlinked Netto HTML evidence")
    resolved = path.resolve(strict=True)
    if not resolved.is_relative_to(root / "netto-html") or resolved.suffix != ".html":
        raise ValueError("Netto HTML evidence outside permitted root")
    with resolved.open("rb") as handle:
        content = handle.read(8 * 1024 * 1024 + 1)
    if len(content) > 8 * 1024 * 1024 or sha256(content).hexdigest() != digest:
        raise ValueError("Netto HTML source integrity failure")
    return content


def _html_teaser_link(db, day, cutoff, page):
    """Official link on its verified start day only; no inferred validity or pages.

    Successful HTML snapshots have already passed the selected-store cookie gate
    in the collector. Replay the raw store bytes and verify manifest bindings here.
    Historical pre-teaser-field manifests remain compatible.
    """
    snapshot = db.scalar(select(SourceSnapshot).where(
        SourceSnapshot.source_chain == "netto",
        SourceSnapshot.scope == "family_primary_netto",
        SourceSnapshot.success.is_(True),
        SourceSnapshot.strategy_hint == "netto_store_html_v1",
        SourceSnapshot.collected_at < cutoff,
    ).order_by(SourceSnapshot.collected_at.desc(), SourceSnapshot.id.desc()).limit(1))
    if snapshot is None:
        return None
    unavailable = {
        "state": "unavailable", "offers": [],
        "message": "Jaunākā Netto bukleta avota pārbaude neizdevās.",
    }
    try:
        root = get_settings().raw_snapshot_dir.resolve()
        manifest = _verified_json(snapshot.snapshot_path, snapshot.sha256, root)
        if (manifest.get("strategy") != "netto_store_html_v1"
                or manifest.get("snapshot_id") != str(snapshot.id)
                or manifest.get("source_url") != snapshot.source_url
                or manifest.get("scope") != snapshot.scope
                or str(manifest.get("store_external_id")) != STORE
                or _store_url_key(snapshot.source_url) != _store_url_key(
                    "https://www.netto-online.de/filialen/dortmund/rauschenbuschstr-1/5659"
                )):
            raise ValueError("Netto HTML snapshot identity mismatch")
        entries = manifest.get("pages")
        if not isinstance(entries, list):
            raise ValueError("Missing HTML evidence pages")
        stores = [entry for entry in entries if isinstance(entry, dict) and entry.get("role") == "store"]
        if len(stores) != 1:
            raise ValueError("Ambiguous HTML store evidence")
        entry = stores[0]
        for key in ("url", "final_url"):
            if _store_url_key(entry[key]) != _store_url_key(snapshot.source_url):
                raise ValueError("HTML store URL mismatch")
        raw = _verified_html(entry["path"], entry["sha256"], root)
        starts = _verified_teaser_starts(raw, entry["sha256"])
        derived = {"state": "observed", "starts": {
            slug: start.isoformat() for slug, start in starts.items()
        }}
        if ("booklet_teaser_evidence" in manifest
                and manifest["booklet_teaser_evidence"] != derived):
            raise ValueError("HTML teaser metadata does not match source")
        # The active HTML collector can save only metadata with an explicit
        # viewer HTML validity range AND a verified official publication JSON.
        # Unrelated unverified source data must not become pages/offer identity.
        records = manifest.get("booklet_publications", [])
        if not isinstance(records, list) or len(records) > 4:
            raise ValueError("Invalid Netto HTML publication metadata")
        selected = []
        seen = set()
        for record in records:
            if not isinstance(record, dict):
                raise ValueError("Invalid Netto HTML publication entry")
            slug = record["slug"]
            if not isinstance(slug, str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", slug):
                raise ValueError("Invalid publication slug")
            if slug in seen or slug not in starts:
                raise ValueError("Unbound or duplicated Netto publication")
            seen.add(slug)
            viewer_url = f"https://wochenprospekt.netto-online.de/{slug}/?storeid={STORE}"
            if record["prospect_url"] != viewer_url:
                raise ValueError("Netto viewer URL mismatch")
            viewer = _verified_html(record["prospect_path"], record["prospect_sha256"], root)
            start, end, text = extract_prospect_validity(viewer)
            if (start != starts[slug] or end < start or (end - start).days > 14
                    or record["valid_from"] != start.isoformat()
                    or record["valid_until"] != end.isoformat()
                    or record["validity_text"] != text):
                raise ValueError("Netto publication validity mismatch")
            group = extract_netto_group_slug(viewer.decode("utf-8", errors="replace"))
            if (not isinstance(group, str)
                    or not re.fullmatch(r"[A-Za-z0-9_-]{1,128}", group)
                    or record["publication_api_url"] !=
                    f"https://api.publitas.com/v1/groups/{group}/publications/{slug}.json"):
                raise ValueError("Netto publication API identity mismatch")
            publication_path = Path(record["publication_path"]).resolve(strict=True)
            if not publication_path.is_relative_to(root / "netto-html"):
                raise ValueError("Netto publication JSON outside evidence root")
            publication = _verified_json(
                record["publication_path"], record["publication_sha256"], root
            )
            paths = validated_pages(publication)
            # Trust the SHA-verified publication's declared image sizes only.
            # An absent or malformed high-resolution size is not an asset URL.
            sizes = publication.get("sizes")
            high_size = None
            if isinstance(sizes, dict):
                for candidate in ("at2400", "at2000"):
                    dimensions = sizes.get(candidate)
                    if (isinstance(dimensions, dict)
                            and all(type(dimensions.get(axis)) in (int, float)
                                    and 1 <= dimensions[axis] <= 10000
                                    for axis in ("width", "height"))):
                        high_size = candidate
                        break
            if start <= day <= end:
                selected.append((record, paths, start, end, high_size))
        if len(selected) > 1:
            raise ValueError("Multiple Netto publications cover one day")
        if selected:
            record, paths, start, end, high_size = selected[0]
            if page > len(paths):
                return {"state": "missing_page", "offers": [],
                        "message": "Šāda lapa bukletā nav pieejama."}
            return {
                "state": "ready", "offers": [], "page": page,
                "page_count": len(paths),
                "image_url": publitas_page_image_url(paths[page - 1], "at1600"),
                "source_url": record["prospect_url"],
                "store_name": manifest.get("store_name") or "Netto · filiāle 5659",
                "valid_label": f"{start:%d.%m.%Y}–{end:%d.%m.%Y}",
                "snapshot_id": str(snapshot.id),
                "swipeable": True,
                "pages": [{"number": index, "href": booklet_href(day, index),
                           "image_url": publitas_page_image_url(asset, "at1600"),
                           "zoom_image_url": publitas_page_image_url(asset, high_size)
                           if high_size else None}
                          for index, asset in enumerate(paths, 1)],
                "previous_href": booklet_href(day, page - 1) if page > 1 else None,
                "next_href": booklet_href(day, page + 1) if page < len(paths) else None,
            }

        matching = [slug for slug, start in starts.items() if start == day]
        if not matching:
            return None
        if len(matching) != 1 or not re.fullmatch(r"[A-Za-z0-9_-]+", matching[0]):
            raise ValueError("Ambiguous dated Netto viewer")
        return {
            "state": "external_link", "offers": [],
            "source_url": f"https://wochenprospekt.netto-online.de/{matching[0]}/?storeid={STORE}",
            "start_label": day.strftime("%d.%m.%Y"),
            "store_name": "Netto · filiāle 5659",
            "message": (
                "Apstiprināta oriģinālā bukleta saite un sākuma datums. "
                "Pilns derīguma periods un bukleta lapas vēl nav pārbaudītas."
            ),
        }
    except (OSError, ValueError, TypeError, KeyError, UnicodeError):
        # Never select an older HTML teaser after corruption of the newest one.
        return unavailable


def build_netto_booklet(db, day: date, page: int = 1):
    if type(page) is not int or not 1 <= page <= 200:
        raise ValueError("Invalid booklet page")
    empty = {"state": "empty", "offers": [], "message": "Šai dienai vēl nav saglabātu Netto bukleta lapu."}
    cutoff = datetime.combine(day + timedelta(days=1), time.min, ZoneInfo("Europe/Berlin"))
    snapshots = db.scalars(select(SourceSnapshot).where(
        SourceSnapshot.source_chain == "netto",
        SourceSnapshot.scope == "family_primary_netto",
        SourceSnapshot.success.is_(True),
        SourceSnapshot.strategy_hint.in_(STRATEGIES),
        SourceSnapshot.collected_at < cutoff,
    ).order_by(SourceSnapshot.collected_at.desc(), SourceSnapshot.id.desc()).limit(50)).all()
    if not snapshots:
        return _html_teaser_link(db, day, cutoff, page) or empty
    root = get_settings().raw_snapshot_dir.resolve()
    latest_available = None
    for snapshot in snapshots:
        in_window = None
        try:
            manifest = _verified_json(snapshot.snapshot_path, snapshot.sha256, root)
            if (manifest.get("strategy") != snapshot.strategy_hint
                    or str(manifest.get("store_external_id")) != STORE
                    or manifest.get("scope") != "family_primary_netto"
                    or _store_url_key(manifest.get("store_url", "")) != _store_url_key(snapshot.source_url)
                    or manifest.get("selected_store_cookie_present") is not True):
                raise ValueError("Source identity mismatch")
            start = date.fromisoformat(manifest["valid_from"])
            end = date.fromisoformat(manifest["valid_until"])
            if start > end:
                raise ValueError("Invalid date window")
            in_window = start <= day <= end
            if not in_window:
                if latest_available is not None or start > day:
                    continue
                observed = snapshot.collected_at
                if observed.tzinfo is None:
                    observed = observed.replace(tzinfo=ZoneInfo("UTC"))
                archive_day = max(start, observed.astimezone(ZoneInfo("Europe/Berlin")).date())
                if archive_day > end:
                    continue
            publication = _verified_json(manifest.get("publication_path"), manifest.get("publication_sha256"), root)
            paths = publication_page_paths(publication)
            if not paths or len(paths) > 200 or len(set(paths)) != len(paths):
                raise ValueError("Invalid publication pages")
            # The browser may fetch only official Publitas page assets. Never
            # reflect arbitrary absolute URLs or untrusted query/fragment syntax.
            if any(not re.fullmatch(r"/[A-Za-z0-9_./-]+", value)
                   or value.startswith("//") or ".." in value.split("/") for value in paths):
                raise ValueError("Invalid page asset path")
            source = urlsplit(manifest.get("prospect_url", ""))
            if (source.scheme != "https" or source.netloc not in {
                    "www.netto-online.de", "netto-online.de", "view.publitas.com",
                    "wochenprospekt.netto-online.de"
            } or source.username or source.fragment):
                raise ValueError("Invalid official source URL")
            viewer_query = parse_qsl(source.query, keep_blank_values=True, max_num_fields=20)
            for key in ("storeid", "stores_id"):
                selected = [value for name, value in viewer_query if name == key]
                if selected and selected != [STORE]:
                    raise ValueError("Conflicting viewer store")
            if not in_window:
                # An archive link is a separate dated view, never today's offers.
                latest_available = {
                    **empty,
                    "latest_label": f"{start:%d.%m.%Y}–{end:%d.%m.%Y}",
                    "latest_href": booklet_href(archive_day, 1),
                }
                continue
            if page > len(paths):
                return {**empty, "state": "missing_page", "message": "Šāda lapa bukletā nav pieejama."}
            pdf_sha = manifest.get("prospect_pdf_sha256")
            rows = db.scalars(select(OfferCandidateRecord).where(
                OfferCandidateRecord.snapshot_id == snapshot.id,
                OfferCandidateRecord.source_chain == "netto",
                OfferCandidateRecord.source_store_external_id == STORE,
                OfferCandidateRecord.collected_at < cutoff,
                OfferCandidateRecord.valid_from <= day,
                OfferCandidateRecord.valid_until >= day,
            ).order_by(OfferCandidateRecord.product_name_raw, OfferCandidateRecord.id).limit(1000)).all()
            linked = []
            for row in rows:
                raw = row.raw_payload if isinstance(row.raw_payload, dict) else {}
                if (isinstance(pdf_sha, str) and re.fullmatch(r"[0-9a-f]{64}", pdf_sha)
                        and raw.get("source_pdf_sha256") == pdf_sha
                        and type(raw.get("special_source_page")) is int
                        and raw["special_source_page"] == page
                        and raw.get("shadow_only") is not True
                        and raw.get("db_write_eligible") is not False):
                    linked.append(row)
            return {
                "state": "ready", "offers": linked, "page": page, "page_count": len(paths),
                "image_url": publitas_page_image_url(paths[page - 1], "at1600"),
                "source_url": manifest["prospect_url"],
                "store_name": manifest.get("store_name") or "Netto · filiāle 5659",
                "valid_label": f"{start:%d.%m.%Y}–{end:%d.%m.%Y}",
                "snapshot_id": str(snapshot.id),
                "pages": [{"number": index, "href": booklet_href(day, index)}
                          for index in range(1, len(paths) + 1)],
                "previous_href": booklet_href(day, page - 1) if page > 1 else None,
                "next_href": booklet_href(day, page + 1) if page < len(paths) else None,
            }
        except (OSError, ValueError, TypeError, KeyError):
            if in_window is False:
                # Non-selected publication metadata is optional archive evidence.
                continue
            # A corrupt newest source must not silently fall back to older pages.
            return {**empty, "state": "unavailable",
                    "message": "Saglabātās bukleta lapas pašlaik nevar pārbaudīt. Mēģini vēlāk."}
    fallback = _html_teaser_link(db, day, cutoff, page)
    return {**(latest_available or empty), **fallback} if fallback else latest_available or empty
