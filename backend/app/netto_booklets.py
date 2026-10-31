"""Read saved Netto publication metadata for the booklet UI; no PDF or network I/O."""
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

STRATEGIES = (
    "netto_store_page_plus_current_prospect_v1",
    "netto_store_page_plus_current_prospect_pdf_v2",
    "netto_store_page_plus_current_prospect_pdf_v3",
)
STORE = "5659"
MAX_JSON = 2 * 1024 * 1024


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


def _html_teaser_link(db, day, cutoff):
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
        path = Path(entry["path"])
        if path.is_symlink():
            raise ValueError("Symlinked HTML evidence")
        resolved = path.resolve(strict=True)
        if not resolved.is_relative_to(root / "netto-html") or resolved.suffix != ".html":
            raise ValueError("HTML source outside permitted root")
        digest = entry["sha256"]
        if not isinstance(digest, str) or re.fullmatch(r"[0-9a-f]{64}", digest) is None:
            raise ValueError("Invalid HTML SHA")
        with resolved.open("rb") as handle:
            raw = handle.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024 or sha256(raw).hexdigest() != digest:
            raise ValueError("HTML source integrity failure")
        from app.netto_booklet_teasers import extract_netto_booklet_teaser_starts
        starts = extract_netto_booklet_teaser_starts(raw.decode("utf-8", errors="replace"), STORE)
        derived = {"state": "observed", "starts": {
            slug: start.isoformat() for slug, start in starts.items()
        }}
        if ("booklet_teaser_evidence" in manifest
                and manifest["booklet_teaser_evidence"] != derived):
            raise ValueError("HTML teaser metadata does not match source")
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
        return _html_teaser_link(db, day, cutoff) or empty
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
    fallback = _html_teaser_link(db, day, cutoff)
    return {**(latest_available or empty), **fallback} if fallback else latest_available or empty
