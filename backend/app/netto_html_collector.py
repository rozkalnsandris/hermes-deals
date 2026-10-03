"""HTML-primary Netto import, with immutable evidence and atomic persistence."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from urllib.parse import urljoin, urlparse
from uuid import uuid4
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SourceSnapshot
from app.offer_store import save_offer_candidates
from app.parsers.netto import NettoParserContext
from app.parsers.netto_listing import (
    LISTING_URL, PARSER_VERSION, STORE_PATH, parse_listing, validate_store, validate_url,
)
from app.source_config import SourceConfig

STRATEGY = "netto_store_html_v1"


@dataclass(frozen=True)
class HtmlPage:
    url: str
    final_url: str
    content: bytes
    role: str = "listing"


@dataclass(frozen=True)
class HtmlImportResult:
    snapshot_id: str
    saved: int
    offers: int
    cards: int
    rejected: int


def validate_source(source: SourceConfig) -> None:
    validate_url(source.url)
    if source.chain != "netto" or source.store_external_id != "5659" or urlparse(source.url).path.rstrip("/") != STORE_PATH:
        raise ValueError("Netto HTML collector requires configured family store 5659")


def fetch_pages(source: SourceConfig) -> list[HtmlPage]:
    validate_source(source)
    pages = []
    with httpx.Client(follow_redirects=False, timeout=45, headers={
        "User-Agent": "Mozilla/5.0 HermesDeals", "Accept-Language": "de-DE,de;q=0.9",
    }) as client:
        def fetch(url: str, role: str = "listing") -> HtmlPage:
            validate_url(url)
            target = url
            for _ in range(5):
                validate_url(target)
                response = client.get(target)
                if not response.is_redirect:
                    break
                location = response.headers.get("location")
                if not location:
                    raise ValueError("Netto redirect without location")
                target = urljoin(str(response.url), location)
            else:
                raise ValueError("Netto redirect limit exceeded")
            response.raise_for_status()
            validate_url(str(response.url))
            if "text/html" not in response.headers.get("content-type", "") or len(response.content) > 8 * 1024 * 1024:
                raise ValueError("Netto unexpected HTML response")
            return HtmlPage(url, str(response.url), response.content, role)

        selection = source.url + ("&" if "?" in source.url else "?") + "stores_id=5659"
        store = fetch(selection, "store")
        if urlparse(store.final_url).path.rstrip("/") != STORE_PATH:
            raise ValueError("Netto store selection redirected away from 5659")
        if not any(
            c.name == "netto_user_stores_id"
            and c.value == source.store_external_id
            for c in client.cookies.jar
        ):
            raise ValueError("Netto selected-store cookie mismatch")
        pages.append(store)
        listing = fetch(LISTING_URL)
        validate_store(BeautifulSoup(listing.content, "html.parser"))
        pages.append(listing)
        # Follow only short-period catalogue links actually exposed by this store.
        soup = BeautifulSoup(store.content, "html.parser")
        specials = sorted({urljoin(source.url, a["href"]).rstrip("/") for a in soup.select("a[href]") if urlparse(urljoin(source.url, a["href"])).path.startswith("/filialangebote/2/")})
        if len(specials) > 4:
            raise ValueError("Netto unexpected number of short-period catalogues")
        for url in specials:
            page = fetch(url)
            validate_store(BeautifulSoup(page.content, "html.parser"))
            pages.append(page)
    return pages


def encode(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()


def immutable(path: Path, data: bytes) -> None:
    try:
        with path.open("xb") as f:
            f.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError("Netto immutable evidence collision")


def parse_pages(pages: list[HtmlPage], source: SourceConfig, snapshot_id, now: datetime):
    offers, rejected, cards = [], [], 0
    for page in pages:
        validate_url(page.url)
        validate_url(page.final_url)
        if page.role == "store":
            continue
        if page.role != "listing":
            raise ValueError("Netto unknown evidence page role")
        context = NettoParserContext(snapshot_id, page.url, now, "5659", source.store_name)
        result = parse_listing(page.content, context)
        offers.extend(result.offers)
        rejected.extend({**row, "source_url": page.url} for row in result.rejected)
        cards += result.card_count
    if not cards or len({o.source_offer_id for o in offers}) != len(offers):
        raise ValueError("Netto empty or overlapping catalogue identities")
    return offers, rejected, cards


def semantic(offers, rejected) -> str:
    values = [o.model_dump(mode="json", exclude={"snapshot_id", "collected_at"}) for o in offers]
    values.sort(key=lambda o: o["source_offer_id"])
    stable_rejected = [{k: v for k, v in row.items() if k != "card_index"} for row in rejected]
    stable_rejected.sort(key=lambda row: (row["source_url"], row["sku"], row["reason"]))
    return sha256(encode({"parser": PARSER_VERSION, "offers": values, "rejected": stable_rejected})).hexdigest()


def replay(snapshot: SourceSnapshot, source: SourceConfig):
    raw = Path(snapshot.snapshot_path).read_bytes()
    if sha256(raw).hexdigest() != snapshot.sha256:
        raise ValueError("Netto manifest SHA mismatch")
    manifest = json.loads(raw)
    if (manifest["strategy"], manifest["snapshot_id"], manifest["source_url"], manifest["store_external_id"], manifest["store_name"], manifest["scope"]) != (STRATEGY, str(snapshot.id), source.url, "5659", source.store_name, source.scope):
        raise ValueError("Netto manifest identity mismatch")
    pages = []
    for entry in manifest["pages"]:
        content = Path(entry["path"]).read_bytes()
        if sha256(content).hexdigest() != entry["sha256"]:
            raise ValueError("Netto HTML SHA mismatch")
        pages.append(HtmlPage(entry["url"], entry["final_url"], content, entry["role"]))
    offers, rejected, cards = parse_pages(pages, source, snapshot.id, datetime.fromisoformat(manifest["collected_at"]))
    if semantic(offers, rejected) != manifest["semantic_sha256"] or cards != manifest["cards"]:
        raise ValueError("Netto manifest replay mismatch")
    return offers, manifest["semantic_sha256"]


def collect_html(db: Session, source: SourceConfig, root: Path, min_offers: int, *, now: datetime | None = None) -> HtmlImportResult:
    validate_source(source)
    now = now or datetime.now(timezone.utc)
    snapshot = SourceSnapshot(
        id=uuid4(), source_chain="netto", source_url=source.url, scope=source.scope,
        collected_at=now, content_bytes=0, keyword_hits={}, json_ld_blocks=0,
        strategy_hint=STRATEGY, success=False,
    )
    root = root / "netto-html"
    root.mkdir(parents=True, exist_ok=True)
    try:
        pages = fetch_pages(source)
        entries = []
        for page in pages:
            digest = sha256(page.content).hexdigest()
            path = root / f"{digest}.html"
            immutable(path, page.content)
            entries.append({"url": page.url, "final_url": page.final_url, "role": page.role, "path": str(path), "sha256": digest})
        snapshot.content_bytes = sum(len(p.content) for p in pages)
        capture = encode({"strategy": STRATEGY, "snapshot_id": str(snapshot.id),
                          "source_url": source.url, "collected_at": now.isoformat(), "pages": entries})
        capture_path = root / f"{snapshot.id}-capture.json"
        immutable(capture_path, capture)
        snapshot.snapshot_path, snapshot.sha256 = str(capture_path), sha256(capture).hexdigest()
        offers, rejected, cards = parse_pages(pages, source, snapshot.id, now)
        fingerprint = semantic(offers, rejected)
        manifest = {
            "strategy": STRATEGY, "snapshot_id": str(snapshot.id), "source_url": source.url,
            "store_external_id": "5659", "store_name": source.store_name, "scope": source.scope,
            "collected_at": now.isoformat(), "pages": entries, "cards": cards,
            "rejected": rejected, "semantic_sha256": fingerprint,
            # Compatibility envelope for existing weekly snapshot selection;
            # each offer keeps its own card-local dates. No PDF is claimed.
            "valid_from": min((o.valid_from for o in offers), default=None).isoformat() if offers else None,
            "valid_until": max((o.valid_until for o in offers), default=None).isoformat() if offers else None,
        }
        raw = encode(manifest)
        path = root / f"{snapshot.id}.json"
        immutable(path, raw)
        snapshot.snapshot_path, snapshot.sha256 = str(path), sha256(raw).hexdigest()
        snapshot.final_url = LISTING_URL
        snapshot.http_status = 200
        snapshot.content_type = "application/vnd.hermes-deals.netto-html+json"
        snapshot.keyword_hits = {"cards": cards, "offers": len(offers), "rejected": len(rejected)}
        today = now.astimezone(ZoneInfo("Europe/Berlin")).date()
        if sum(o.valid_from <= today <= o.valid_until for o in offers) < max(min_offers, 1):
            raise ValueError("Netto current offer count below minimum; no offers written")
        previous = db.scalar(select(SourceSnapshot).where(
            SourceSnapshot.source_chain == "netto", SourceSnapshot.source_url == source.url,
            SourceSnapshot.scope == source.scope, SourceSnapshot.strategy_hint == STRATEGY,
            SourceSnapshot.success.is_(True),
        ).order_by(SourceSnapshot.collected_at.desc()).limit(1))
        if previous is not None:
            old_offers, old_fingerprint = replay(previous, source)
            if old_fingerprint == fingerprint:
                # Check the complete persisted set even when the source is unchanged.
                saved = save_offer_candidates(db, old_offers)
                return HtmlImportResult(str(previous.id), saved, len(offers), cards, len(rejected))
        snapshot.success = True
        db.add(snapshot)
        db.flush()
        saved = save_offer_candidates(db, offers, commit=False)
        db.commit()
        return HtmlImportResult(str(snapshot.id), saved, len(offers), cards, len(rejected))
    except Exception as exc:
        db.rollback()
        snapshot.success = False
        snapshot.error = f"{type(exc).__name__}: {exc}"[:2000]
        db.add(snapshot)
        db.commit()
        raise
