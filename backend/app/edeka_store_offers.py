from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
import time
from urllib.parse import urlparse
from uuid import UUID, uuid4

import httpx
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import SourceSnapshot
from app.parsers.edeka import EdekaParserContext, parse_edeka_html
from app.schemas import OfferCandidate
from app.settings import get_settings
from app.source_config import SourceConfig


MANIFEST_SCHEMA_VERSION = 1
MANIFEST_STRATEGY = "edeka_patzer_store_offers_v1"
MANIFEST_CONTENT_TYPE = (
    "application/vnd.hermes-deals.edeka-store-offers+json"
)
OFFER_SEMANTIC_FINGERPRINT_VERSION = 1
_EXPECTED_PUBLIC_MARKET_ID = "071897"
_EXPECTED_INTERNAL_MARKET_ID = "587881"
_EXPECTED_STORE_NAME = "EDEKA Patzer"
_EXPECTED_SOURCE_URL = "https://www.edeka.de/maerkte/071897/angebote/"
_EXPECTED_SCOPE = "family_primary_edeka"


@dataclass(frozen=True)
class EdekaFetchedPage:
    final_url: str
    content: bytes
    content_type: str | None
    http_status: int
    elapsed_ms: int


@dataclass(frozen=True)
class EdekaCollectionResult:
    snapshot: SourceSnapshot
    unchanged: bool


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _validate_source(source: SourceConfig) -> None:
    if source.chain != "edeka":
        raise ValueError("EDEKA collector requires source chain edeka")
    if source.url != _EXPECTED_SOURCE_URL:
        raise ValueError("EDEKA collector source URL is not Patzer 071897")
    if source.scope != _EXPECTED_SCOPE:
        raise ValueError("EDEKA collector scope is not family_primary_edeka")
    if source.store_external_id != _EXPECTED_PUBLIC_MARKET_ID:
        raise ValueError("EDEKA collector public market ID mismatch")
    if source.store_internal_id != _EXPECTED_INTERNAL_MARKET_ID:
        raise ValueError("EDEKA collector internal market ID mismatch")
    if source.store_name != _EXPECTED_STORE_NAME:
        raise ValueError("EDEKA collector store name mismatch")


def fetch_edeka_store_offers(source: SourceConfig) -> EdekaFetchedPage:
    _validate_source(source)
    settings = get_settings()
    headers = {
        "User-Agent": settings.http_user_agent,
        "Accept": (
            "text/html,application/xhtml+xml,application/json;q=0.9,*/*;q=0.8"
        ),
        "Accept-Language": "de-DE,de;q=0.9,en;q=0.5",
        "Cache-Control": "no-cache",
    }
    started = time.monotonic()
    with httpx.Client(
        follow_redirects=True,
        timeout=httpx.Timeout(30.0, connect=10.0),
        headers=headers,
    ) as client:
        response = client.get(source.url)
    elapsed_ms = round((time.monotonic() - started) * 1000)
    response.raise_for_status()

    content = response.content
    if len(content) < 1000:
        raise ValueError("EDEKA source response is unexpectedly small")

    final_url = str(response.url)
    if final_url != source.url:
        raise ValueError(
            "EDEKA source redirected away from the canonical Patzer page: "
            f"{final_url}"
        )

    return EdekaFetchedPage(
        final_url=final_url,
        content=content,
        content_type=response.headers.get("content-type"),
        http_status=response.status_code,
        elapsed_ms=elapsed_ms,
    )


def _write_immutable(path: Path, value: bytes) -> None:
    try:
        with path.open("xb") as handle:
            handle.write(value)
    except FileExistsError:
        if path.read_bytes() != value:
            raise ValueError(
                f"Refusing to replace immutable EDEKA evidence: {path}"
            )


def _single_offer_window(
    offers: list[OfferCandidate],
) -> tuple[date, date]:
    windows = {(offer.valid_from, offer.valid_until) for offer in offers}
    if len(windows) != 1:
        raise ValueError(
            "EDEKA manifest requires one exact offer validity window"
        )
    valid_from, valid_until = next(iter(windows))
    if valid_from is None or valid_until is None:
        raise ValueError("EDEKA manifest validity window is incomplete")
    return valid_from, valid_until


def _offer_semantic_sha256(offers: list[OfferCandidate]) -> str:
    rows: list[dict[str, object]] = []
    source_offer_ids: list[str] = []
    for offer in offers:
        row = offer.model_dump(mode="json")
        row.pop("snapshot_id", None)
        row.pop("collected_at", None)
        source_offer_id = row.get("source_offer_id")
        if not isinstance(source_offer_id, str) or not source_offer_id:
            raise ValueError(
                "EDEKA semantic fingerprint requires source_offer_id"
            )
        source_offer_ids.append(source_offer_id)
        rows.append(row)
    if len(source_offer_ids) != len(set(source_offer_ids)):
        raise ValueError(
            "EDEKA semantic fingerprint contains duplicate source_offer_id"
        )
    rows.sort(key=lambda row: str(row["source_offer_id"]))
    payload = {
        "schema_version": OFFER_SEMANTIC_FINGERPRINT_VERSION,
        "offers": rows,
    }
    data = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(data).hexdigest()


def _write_manifest(
    *,
    source: SourceConfig,
    snapshot_id: object,
    collected_at: datetime,
    fetched: EdekaFetchedPage,
    offers: list[OfferCandidate],
) -> tuple[Path, str]:
    valid_from, valid_until = _single_offer_window(offers)
    settings = get_settings()
    root = settings.raw_snapshot_dir / "edeka"
    root.mkdir(parents=True, exist_ok=True)

    raw_sha = sha256(fetched.content).hexdigest()
    raw_path = root / (
        f"{_EXPECTED_PUBLIC_MARKET_ID}-offers-{raw_sha}.html"
    )
    _write_immutable(raw_path, fetched.content)

    manifest = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "strategy": MANIFEST_STRATEGY,
        "snapshot_id": str(snapshot_id),
        "source_chain": source.chain,
        "scope": source.scope,
        "public_market_id": source.store_external_id,
        "internal_market_id": source.store_internal_id,
        "store_name": source.store_name,
        "source_url": source.url,
        "final_url": fetched.final_url,
        "collected_at": collected_at.isoformat(),
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat(),
        "offer_count": len(offers),
        "offer_semantic_fingerprint_version": (
            OFFER_SEMANTIC_FINGERPRINT_VERSION
        ),
        "offer_semantic_sha256": _offer_semantic_sha256(offers),
        "raw_html_path": str(raw_path),
        "raw_html_sha256": raw_sha,
        "raw_content_type": fetched.content_type,
        "raw_content_bytes": len(fetched.content),
    }
    data = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    digest = sha256(data).hexdigest()
    stamp = collected_at.strftime("%Y%m%dT%H%M%SZ")
    manifest_path = root / (
        f"{stamp}-{_EXPECTED_PUBLIC_MARKET_ID}-offers-manifest-"
        f"{digest[:12]}.json"
    )
    _write_immutable(manifest_path, data)
    return manifest_path, digest


def _read_manifest_bytes(path: Path, expected_sha256: str) -> dict[str, object]:
    data = path.read_bytes()
    actual_sha = sha256(data).hexdigest()
    if actual_sha != expected_sha256:
        raise ValueError("EDEKA manifest SHA mismatch")
    manifest = json.loads(data)
    if not isinstance(manifest, dict):
        raise ValueError("EDEKA manifest must be a JSON object")
    return manifest


def _validate_manifest_source(
    manifest: dict[str, object],
    source: SourceConfig,
) -> None:
    expected = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "strategy": MANIFEST_STRATEGY,
        "source_chain": source.chain,
        "scope": source.scope,
        "public_market_id": source.store_external_id,
        "internal_market_id": source.store_internal_id,
        "store_name": source.store_name,
        "source_url": source.url,
        "final_url": source.url,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"EDEKA manifest {key} mismatch")


def _read_raw_html(manifest: dict[str, object]) -> bytes:
    raw_path_value = manifest.get("raw_html_path")
    raw_sha = manifest.get("raw_html_sha256")
    if not isinstance(raw_path_value, str) or not isinstance(raw_sha, str):
        raise ValueError("EDEKA manifest raw HTML binding is missing")
    raw = Path(raw_path_value).read_bytes()
    if sha256(raw).hexdigest() != raw_sha:
        raise ValueError("EDEKA raw HTML SHA mismatch")
    return raw


def _latest_manifest_snapshot(
    db: Session,
    source: SourceConfig,
) -> SourceSnapshot | None:
    return db.scalar(
        select(SourceSnapshot)
        .where(
            SourceSnapshot.source_chain == source.chain,
            SourceSnapshot.scope == source.scope,
            SourceSnapshot.content_type == MANIFEST_CONTENT_TYPE,
            SourceSnapshot.success.is_(True),
        )
        .order_by(SourceSnapshot.collected_at.desc())
        .limit(1)
    )


def _manifest_offer_semantic_sha256(
    manifest_path: Path,
    expected_sha256: str,
    source: SourceConfig,
) -> str:
    manifest = _read_manifest_bytes(manifest_path, expected_sha256)
    _validate_manifest_source(manifest, source)
    raw = _read_raw_html(manifest)

    snapshot_id_value = manifest.get("snapshot_id")
    collected_at_value = manifest.get("collected_at")
    if not isinstance(snapshot_id_value, str):
        raise ValueError("EDEKA manifest snapshot_id is missing")
    if not isinstance(collected_at_value, str):
        raise ValueError("EDEKA manifest collected_at is missing")
    context = EdekaParserContext(
        snapshot_id=UUID(snapshot_id_value),
        source_url=source.url,
        collected_at=datetime.fromisoformat(collected_at_value),
        public_market_id=source.store_external_id or "",
        internal_market_id=source.store_internal_id or "",
        store_name=source.store_name or "",
    )
    offers = parse_edeka_html(raw, context)
    semantic_sha = _offer_semantic_sha256(offers)

    manifest_semantic_sha = manifest.get("offer_semantic_sha256")
    manifest_semantic_version = manifest.get(
        "offer_semantic_fingerprint_version"
    )
    if manifest_semantic_sha is not None:
        if manifest_semantic_version != OFFER_SEMANTIC_FINGERPRINT_VERSION:
            raise ValueError(
                "EDEKA manifest semantic fingerprint version mismatch"
            )
        if manifest_semantic_sha != semantic_sha:
            raise ValueError(
                "EDEKA manifest semantic fingerprint mismatch"
            )
    return semantic_sha


def _matching_previous_snapshot(
    db: Session,
    source: SourceConfig,
    *,
    offer_semantic_sha256: str,
    valid_from: date,
    valid_until: date,
    offer_count: int,
) -> SourceSnapshot | None:
    snapshot = _latest_manifest_snapshot(db, source)
    if snapshot is None:
        return None
    if not snapshot.snapshot_path or not snapshot.sha256:
        raise ValueError("EDEKA manifest snapshot binding is incomplete")

    manifest_path = Path(snapshot.snapshot_path)
    manifest = _read_manifest_bytes(
        manifest_path,
        snapshot.sha256,
    )
    _validate_manifest_source(manifest, source)
    previous_semantic_sha = _manifest_offer_semantic_sha256(
        manifest_path,
        snapshot.sha256,
        source,
    )

    if (
        previous_semantic_sha == offer_semantic_sha256
        and manifest.get("valid_from") == valid_from.isoformat()
        and manifest.get("valid_until") == valid_until.isoformat()
        and manifest.get("offer_count") == offer_count
    ):
        return snapshot
    return None


def collect_edeka_store_offers(
    db: Session,
    source: SourceConfig,
) -> EdekaCollectionResult:
    _validate_source(source)
    collected_at = _utc_now()
    snapshot = SourceSnapshot(
        id=uuid4(),
        source_chain=source.chain,
        source_url=source.url,
        scope=source.scope,
        collected_at=collected_at,
        content_bytes=0,
        keyword_hits={},
        json_ld_blocks=0,
        strategy_hint=f"{MANIFEST_STRATEGY}_pending",
        success=False,
    )
    fetched: EdekaFetchedPage | None = None

    try:
        fetched = fetch_edeka_store_offers(source)
        context = EdekaParserContext(
            snapshot_id=snapshot.id,
            source_url=fetched.final_url,
            collected_at=collected_at,
            public_market_id=source.store_external_id or "",
            internal_market_id=source.store_internal_id or "",
            store_name=source.store_name or "",
        )
        offers = parse_edeka_html(fetched.content, context)
        valid_from, valid_until = _single_offer_window(offers)
        offer_semantic_sha = _offer_semantic_sha256(offers)

        previous = _matching_previous_snapshot(
            db,
            source,
            offer_semantic_sha256=offer_semantic_sha,
            valid_from=valid_from,
            valid_until=valid_until,
            offer_count=len(offers),
        )
        if previous is not None:
            return EdekaCollectionResult(
                snapshot=previous,
                unchanged=True,
            )

        manifest_path, manifest_sha = _write_manifest(
            source=source,
            snapshot_id=snapshot.id,
            collected_at=collected_at,
            fetched=fetched,
            offers=offers,
        )
        snapshot.final_url = fetched.final_url
        snapshot.http_status = fetched.http_status
        snapshot.elapsed_ms = fetched.elapsed_ms
        snapshot.content_type = MANIFEST_CONTENT_TYPE
        snapshot.content_bytes = len(fetched.content)
        snapshot.sha256 = manifest_sha
        snapshot.snapshot_path = str(manifest_path)
        snapshot.keyword_hits = {
            "exact_market_binding": 1,
            "validity_window": 1,
            "offer_count": len(offers),
        }
        snapshot.strategy_hint = MANIFEST_STRATEGY
        snapshot.success = True
    except Exception as exc:
        if fetched is not None:
            snapshot.final_url = fetched.final_url
            snapshot.http_status = fetched.http_status
            snapshot.elapsed_ms = fetched.elapsed_ms
            snapshot.content_type = fetched.content_type
            snapshot.content_bytes = len(fetched.content)
        snapshot.strategy_hint = f"{MANIFEST_STRATEGY}_error"
        snapshot.error = f"{type(exc).__name__}: {exc}"[:2000]

    db.add(snapshot)
    db.commit()
    db.refresh(snapshot)
    return EdekaCollectionResult(snapshot=snapshot, unchanged=False)


def parse_edeka_store_offers_snapshot(
    manifest_path: Path,
    expected_sha256: str,
    context: EdekaParserContext,
) -> list[OfferCandidate]:
    manifest = _read_manifest_bytes(manifest_path, expected_sha256)
    expected_identity = {
        "schema_version": MANIFEST_SCHEMA_VERSION,
        "strategy": MANIFEST_STRATEGY,
        "snapshot_id": str(context.snapshot_id),
        "source_chain": "edeka",
        "scope": _EXPECTED_SCOPE,
        "public_market_id": context.public_market_id,
        "internal_market_id": context.internal_market_id,
        "store_name": context.store_name,
        "source_url": context.source_url,
        "final_url": context.source_url,
    }
    for key, value in expected_identity.items():
        if manifest.get(key) != value:
            raise ValueError(f"EDEKA manifest {key} mismatch")

    raw = _read_raw_html(manifest)
    offers = parse_edeka_html(raw, context)
    valid_from, valid_until = _single_offer_window(offers)
    if manifest.get("valid_from") != valid_from.isoformat():
        raise ValueError("EDEKA manifest valid_from mismatch")
    if manifest.get("valid_until") != valid_until.isoformat():
        raise ValueError("EDEKA manifest valid_until mismatch")
    if manifest.get("offer_count") != len(offers):
        raise ValueError("EDEKA manifest offer_count mismatch")
    manifest_semantic_sha = manifest.get("offer_semantic_sha256")
    if manifest_semantic_sha is not None:
        if manifest.get("offer_semantic_fingerprint_version") != (
            OFFER_SEMANTIC_FINGERPRINT_VERSION
        ):
            raise ValueError(
                "EDEKA manifest semantic fingerprint version mismatch"
            )
        if manifest_semantic_sha != _offer_semantic_sha256(offers):
            raise ValueError(
                "EDEKA manifest semantic fingerprint mismatch"
            )
    return offers
