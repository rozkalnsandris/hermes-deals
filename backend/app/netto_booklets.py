"""Read saved Netto publication metadata for the booklet UI; no PDF or network I/O."""
from datetime import date, datetime, time, timedelta
from hashlib import sha256
import json
from pathlib import Path
import re
from urllib.parse import urlencode, urlsplit
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


def booklet_href(day, page):
    return "/ui/home/?" + urlencode({"view": "booklets", "date": day.isoformat(), "page": page})


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
        return empty
    root = get_settings().raw_snapshot_dir.resolve()
    for snapshot in snapshots:
        try:
            manifest = _verified_json(snapshot.snapshot_path, snapshot.sha256, root)
            if (manifest.get("strategy") != snapshot.strategy_hint
                    or str(manifest.get("store_external_id")) != STORE
                    or manifest.get("scope") != "family_primary_netto"
                    or manifest.get("store_url") != snapshot.source_url
                    or manifest.get("selected_store_cookie_present") is not True):
                raise ValueError("Source identity mismatch")
            start = date.fromisoformat(manifest["valid_from"])
            end = date.fromisoformat(manifest["valid_until"])
            if start > end:
                raise ValueError("Invalid date window")
            if not start <= day <= end:
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
                    "www.netto-online.de", "netto-online.de", "view.publitas.com"
            } or source.username):
                raise ValueError("Invalid official source URL")
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
            # A corrupt newest source must not silently fall back to older pages.
            return {**empty, "state": "unavailable",
                    "message": "Saglabātās bukleta lapas pašlaik nevar pārbaudīt. Mēģini vēlāk."}
    return empty
