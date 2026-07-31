from __future__ import annotations

import argparse
import csv
import hashlib
import json
import shutil
from dataclasses import dataclass
from datetime import UTC, date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urljoin
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.models import OfferCandidateRecord, OfferReviewItem, SourceSnapshot
from app.offer_store import save_offer_candidates
from app.review_queue import seed_review_item
from app.schemas import OfferCandidate, SourceChain
from app.lidl_completeness_rescue import (
    RESCUE_VERSION,
    load_rescue_artifact,
    rescue_reason_codes,
    rescue_row_key,
)
from app.lidl_corpus_reconciliation import (
    load_reconciliation_plan,
    validate_import_approval,
)
from app.lidl_review_seed_reconciliation import (
    REVIEW_SEED_DECISION,
    REVIEW_SEED_WORKFLOW_VERSION,
    canonical_row_material as review_canonical_row_material,
    load_review_seed_plan,
)

SOURCE_STRATEGY = "lidl_public_flyer_json_canonical"
CORPUS_IMPORT_VERSION = "lidl-corpus-import-v1"
RECONCILED_CORPUS_IMPORT_VERSION = "lidl-corpus-import-v2-reconciled"
EXPECTED_PARSER_VERSION = "lidl-pdf-v08c-r61-shadow-v631"
FAMILY_STORE_EXTERNAL_ID = "DE06664"
FAMILY_STORE_NAME = "Lidl Husener Straße 44, Dortmund"


@dataclass(frozen=True)
class FlyerContext:
    flyer_key: str
    scan_name: str
    parser_version: str
    parser_sha256: str
    raw_sha256: str
    pdf_sha256: str
    collected_at: datetime
    valid_from: date
    valid_until: date
    region: str
    official_flyer_id: str
    api_url: str
    viewer_url: str
    document_url: str
    pages: dict[int, dict[str, Any]]


def _sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            h.update(chunk)
    return h.hexdigest()


def _load_json(path: Path) -> dict[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise ValueError(f"JSON root must be an object: {path}")
    return payload


def _read_tsv(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _truth(value: Any) -> bool:
    return str(value or "").strip().casefold() in {"1", "true", "yes", "y"}


def _none(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def _decimal(value: Any) -> Decimal | None:
    text = _none(value)
    return Decimal(text.replace(",", ".")) if text is not None else None


def _date(value: Any) -> date | None:
    text = _none(value)
    return date.fromisoformat(text) if text is not None else None


def _json_list(value: Any) -> list[Any]:
    text = _none(value)
    if text is None:
        return []
    parsed = json.loads(text)
    if not isinstance(parsed, list):
        raise ValueError(f"Expected JSON list, got {type(parsed).__name__}")
    return parsed


def _canonical_row_material(row: dict[str, str]) -> str:
    return json.dumps(
        {key: row.get(key, "") for key in sorted(row)},
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def _row_digest(row: dict[str, str]) -> str:
    return hashlib.sha256(_canonical_row_material(row).encode("utf-8")).hexdigest()


def source_row_key(scan_name: str, ordinal: int, row: dict[str, str]) -> str:
    return f"{scan_name}:row{ordinal:03d}:{_row_digest(row)[:12]}"


def source_offer_id(
    flyer_key: str,
    scan_name: str,
    ordinal: int,
    row: dict[str, str],
) -> str:
    return (
        f"lidl:corpus:{flyer_key}:{scan_name}:"
        f"r{ordinal:03d}:{_row_digest(row)[:12]}"
    )


def _api_url(source_payload: dict[str, Any]) -> str:
    raw = str(source_payload.get("self") or "").strip()
    if not raw:
        raise ValueError("source.json has no Schwarz self endpoint")
    return urljoin("https://endpoints.leaflets.schwarz/", raw)


def load_context(
    *,
    flyer_dir: Path,
    scan_name: str,
    expected_raw_sha256: str,
    expected_pdf_sha256: str,
) -> FlyerContext:
    source_path = flyer_dir / "source.json"
    pdf_path = flyer_dir / "source.pdf"
    scan_dir = flyer_dir / "scans" / scan_name
    summary_path = scan_dir / "summary.json"

    for path in (source_path, pdf_path, summary_path):
        if not path.exists():
            raise FileNotFoundError(path)

    raw_sha = _sha256_file(source_path)
    pdf_sha = _sha256_file(pdf_path)
    if raw_sha != expected_raw_sha256:
        raise ValueError(
            f"Raw source SHA mismatch: expected {expected_raw_sha256}, got {raw_sha}"
        )
    if pdf_sha != expected_pdf_sha256:
        raise ValueError(
            f"PDF SHA mismatch: expected {expected_pdf_sha256}, got {pdf_sha}"
        )

    source = _load_json(source_path)
    summary = _load_json(summary_path)
    flyer = source.get("flyer")
    if not isinstance(flyer, dict):
        raise ValueError("source.json has no flyer object")

    flyer_key = flyer_dir.name
    if str(summary.get("flyer_key") or "") != flyer_key:
        raise ValueError("Scan summary flyer_key does not match corpus directory")
    if str(summary.get("scan") or "") != scan_name:
        raise ValueError("Scan summary scan does not match requested scan")

    parser_version = str(summary.get("parser_version") or "")
    if parser_version != EXPECTED_PARSER_VERSION:
        raise ValueError(
            f"Unexpected parser version: {parser_version!r}; "
            f"expected {EXPECTED_PARSER_VERSION!r}"
        )
    parser_sha = str(summary.get("parser_sha256") or "").strip()
    if len(parser_sha) != 64:
        raise ValueError("Scan summary parser_sha256 is missing or invalid")

    collected_raw = str(source.get("dateTime") or "").strip()
    if not collected_raw:
        raise ValueError("source.json has no dateTime")
    collected_at = datetime.fromisoformat(collected_raw.replace("Z", "+00:00"))

    valid_from = date.fromisoformat(str(flyer["offerStartDate"]))
    valid_until = date.fromisoformat(str(flyer["offerEndDate"]))
    official_flyer_id = str(flyer.get("id") or "").strip()
    viewer_url = str(flyer.get("flyerUrlAbsolute") or "").strip()
    document_url = str(flyer.get("hiResPdfUrl") or "").strip()
    if not official_flyer_id or not viewer_url or not document_url:
        raise ValueError("Flyer identity/viewer/document metadata is incomplete")

    pages: dict[int, dict[str, Any]] = {}
    for raw_page in flyer.get("pages") or []:
        if not isinstance(raw_page, dict):
            continue
        number = raw_page.get("number")
        if isinstance(number, int) and number > 0:
            pages[number] = raw_page

    region = ""
    marker = "/ar/"
    if marker in viewer_url:
        region = viewer_url.split(marker, 1)[1].split("?", 1)[0].strip("/")
    if not region:
        raise ValueError("Could not derive flyer region from viewer URL")

    return FlyerContext(
        flyer_key=flyer_key,
        scan_name=scan_name,
        parser_version=parser_version,
        parser_sha256=parser_sha,
        raw_sha256=raw_sha,
        pdf_sha256=pdf_sha,
        collected_at=collected_at,
        valid_from=valid_from,
        valid_until=valid_until,
        region=region,
        official_flyer_id=official_flyer_id,
        api_url=_api_url(source),
        viewer_url=viewer_url,
        document_url=document_url,
        pages=pages,
    )


def _page_visual(context: FlyerContext, page_number: int) -> str | None:
    page = context.pages.get(page_number) or {}
    for key in ("zoom", "image", "thumbnail"):
        value = str(page.get(key) or "").strip()
        if value:
            return value
    return None


def safe_rows(scan_dir: Path) -> list[dict[str, str]]:
    accepted = scan_dir / "accepted-physical.tsv"
    source = accepted if accepted.exists() else scan_dir / "target-rows.tsv"
    rows = _read_tsv(source)
    result = [
        row
        for row in rows
        if row.get("scope") == "in_scope"
        and row.get("channel") == "physical_store"
        and _truth(row.get("production_ready_shadow"))
        and row.get("price_basis") != "variable_weight_example"
    ]
    return result


def review_rows(scan_dir: Path) -> list[dict[str, str]]:
    return _read_tsv(scan_dir / "review-required.tsv")


def validate_scan_contract(
    *,
    flyer_dir: Path,
    scan_name: str,
    expected_safe_count: int,
    expected_review_count: int,
    expected_raw_sha256: str,
    expected_pdf_sha256: str,
) -> dict[str, Any]:
    context = load_context(
        flyer_dir=flyer_dir,
        scan_name=scan_name,
        expected_raw_sha256=expected_raw_sha256,
        expected_pdf_sha256=expected_pdf_sha256,
    )
    scan_dir = flyer_dir / "scans" / scan_name
    safe = safe_rows(scan_dir)
    review = review_rows(scan_dir)

    if len(safe) != expected_safe_count:
        raise ValueError(
            f"Safe row count mismatch: expected {expected_safe_count}, got {len(safe)}"
        )
    if len(review) != expected_review_count:
        raise ValueError(
            f"Review row count mismatch: expected {expected_review_count}, got {len(review)}"
        )

    safe_ids = {
        source_offer_id(context.flyer_key, scan_name, ordinal, row)
        for ordinal, row in enumerate(safe, start=1)
    }
    if len(safe_ids) != len(safe):
        raise ValueError("Safe corpus source_offer_id collision")

    review_keys = {
        source_row_key(scan_name, ordinal, row)
        for ordinal, row in enumerate(review, start=1)
    }
    if len(review_keys) != len(review):
        raise ValueError("Review corpus source_row_key collision")

    return {
        "flyer_key": context.flyer_key,
        "scan_name": scan_name,
        "parser_version": context.parser_version,
        "parser_sha256": context.parser_sha256,
        "raw_sha256": context.raw_sha256,
        "pdf_sha256": context.pdf_sha256,
        "region": context.region,
        "valid_from": context.valid_from.isoformat(),
        "valid_until": context.valid_until.isoformat(),
        "safe_count": len(safe),
        "review_count": len(review),
    }


def _snapshot_identity(raw_sha256: str) -> UUID:
    return uuid5(NAMESPACE_URL, f"hermes-deals:lidl:corpus-source:{raw_sha256}")


def _snapshot_scope(context: FlyerContext) -> str:
    return (
        f"physical_store_flyer:r{context.region}:"
        f"{context.valid_from.isoformat()}:{context.valid_until.isoformat()}"
    )


def _utc_datetime(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=UTC)
    return value.astimezone(UTC)


def _assert_snapshot_same(
    snapshot: SourceSnapshot,
    *,
    context: FlyerContext,
    snapshot_path: str,
    content_bytes: int,
) -> None:
    expected = {
        "source_chain": "lidl",
        "source_url": context.api_url,
        "final_url": context.api_url,
        "scope": _snapshot_scope(context),
        "collected_at": context.collected_at,
        "http_status": 200,
        "content_type": "application/json",
        "content_bytes": content_bytes,
        "sha256": context.raw_sha256,
        "snapshot_path": snapshot_path,
        "strategy_hint": SOURCE_STRATEGY,
        "success": True,
        "error": None,
    }
    for key, value in expected.items():
        actual = getattr(snapshot, key)
        if key == "collected_at":
            if not isinstance(actual, datetime) or not isinstance(value, datetime):
                raise ValueError("Existing SourceSnapshot has invalid collected_at")
            if _utc_datetime(actual) != _utc_datetime(value):
                raise ValueError(
                    "Existing SourceSnapshot conflicts on collected_at"
                )
            continue
        if actual != value:
            raise ValueError(f"Existing SourceSnapshot conflicts on {key}")


def register_source_snapshot(
    db: Session,
    *,
    flyer_dir: Path,
    scan_name: str,
    raw_root: Path,
    db_raw_prefix: str,
    expected_raw_sha256: str,
    expected_pdf_sha256: str,
    commit: bool = True,
) -> SourceSnapshot:
    context = load_context(
        flyer_dir=flyer_dir,
        scan_name=scan_name,
        expected_raw_sha256=expected_raw_sha256,
        expected_pdf_sha256=expected_pdf_sha256,
    )
    raw_source = flyer_dir / "source.json"
    canonical_dir = raw_root / "lidl"
    canonical_dir.mkdir(parents=True, exist_ok=True)
    canonical = canonical_dir / f"flyer-{context.raw_sha256}.json"

    if canonical.exists():
        if _sha256_file(canonical) != context.raw_sha256:
            raise ValueError("Existing canonical Lidl raw snapshot hash mismatch")
    else:
        temp = canonical.with_suffix(".json.tmp")
        shutil.copyfile(raw_source, temp)
        if _sha256_file(temp) != context.raw_sha256:
            temp.unlink(missing_ok=True)
            raise ValueError("Temporary canonical Lidl raw snapshot hash mismatch")
        temp.replace(canonical)

    prefix = db_raw_prefix.rstrip("/")
    snapshot_path = f"{prefix}/lidl/{canonical.name}"
    content_bytes = raw_source.stat().st_size
    deterministic_id = _snapshot_identity(context.raw_sha256)

    existing = db.get(SourceSnapshot, deterministic_id)
    if existing is None:
        same_sha = list(
            db.scalars(
                select(SourceSnapshot).where(
                    SourceSnapshot.source_chain == "lidl",
                    SourceSnapshot.sha256 == context.raw_sha256,
                    SourceSnapshot.strategy_hint == SOURCE_STRATEGY,
                )
            ).all()
        )
        if len(same_sha) > 1:
            raise ValueError("Multiple canonical Lidl SourceSnapshots share raw SHA")
        if same_sha:
            existing = same_sha[0]

    if existing is not None:
        _assert_snapshot_same(
            existing,
            context=context,
            snapshot_path=snapshot_path,
            content_bytes=content_bytes,
        )
        return existing

    snapshot = SourceSnapshot(
        id=deterministic_id,
        source_chain="lidl",
        source_url=context.api_url,
        final_url=context.api_url,
        scope=_snapshot_scope(context),
        collected_at=context.collected_at,
        http_status=200,
        elapsed_ms=None,
        content_type="application/json",
        content_bytes=content_bytes,
        sha256=context.raw_sha256,
        snapshot_path=snapshot_path,
        keyword_hits={},
        json_ld_blocks=0,
        strategy_hint=SOURCE_STRATEGY,
        success=True,
        error=None,
    )
    db.add(snapshot)
    if commit:
        db.commit()
    else:
        db.flush()
    db.refresh(snapshot)
    return snapshot


def build_offer(
    *,
    row: dict[str, str],
    ordinal: int,
    context: FlyerContext,
    snapshot: SourceSnapshot,
    source_offer_id_override: str | None = None,
    identity_origin: str | None = None,
    identity_plan_sha256: str | None = None,
    semantic_digest_sha256: str | None = None,
) -> OfferCandidate:
    if row.get("scope") != "in_scope":
        raise ValueError("Only in_scope corpus rows may become automatic offers")
    if row.get("channel") != "physical_store":
        raise ValueError("Only physical_store corpus rows may become automatic offers")
    if not _truth(row.get("production_ready_shadow")):
        raise ValueError("Corpus row is not production_ready_shadow")
    if row.get("price_basis") == "variable_weight_example":
        raise ValueError("Variable-weight example cannot be auto-promoted")

    page = int(row.get("page") or 0)
    product = _none(row.get("product_name"))
    price = _decimal(row.get("price_eur"))
    if page <= 0 or not product or price is None:
        raise ValueError("Corpus safe row lacks page/product/price")

    valid_from = _date(row.get("valid_from"))
    valid_until = _date(row.get("valid_until"))
    if valid_from is None or valid_until is None:
        raise ValueError("Corpus safe row lacks validity")

    app_price = _decimal(row.get("app_price_eur"))
    image_url = _page_visual(context, page)

    reconciled = source_offer_id_override is not None
    if reconciled and not all(
        (identity_origin, identity_plan_sha256, semantic_digest_sha256)
    ):
        raise ValueError("Reconciled offer identity metadata is incomplete")

    raw_payload = {
        "corpus_import_version": (
            RECONCILED_CORPUS_IMPORT_VERSION
            if reconciled
            else CORPUS_IMPORT_VERSION
        ),
        "flyer_key": context.flyer_key,
        "scan": context.scan_name,
        "source_row_key": source_row_key(context.scan_name, ordinal, row),
        "source_row_ordinal": ordinal,
        "page": page,
        "official_flyer_id": context.official_flyer_id,
        "region": context.region,
        "source_snapshot_id": str(snapshot.id),
        "source_snapshot_sha256": context.raw_sha256,
        "source_pdf_sha256": context.pdf_sha256,
        "page_image_url": image_url,
        "parser_version": context.parser_version,
        "parser_sha256": context.parser_sha256,
        "scope": row.get("scope"),
        "scope_source": row.get("scope_source"),
        "channel": row.get("channel"),
        "channel_source": row.get("channel_source"),
        "price_basis": row.get("price_basis"),
        "validity_source": row.get("validity_source"),
        "regular_price_source": row.get("regular_price_source"),
        "r6_classification": row.get("r6_classification"),
        "recovery_source": row.get("recovery_source"),
        "warnings": _json_list(row.get("warnings")),
        "manual_reviewed": _truth(row.get("manual_reviewed")),
        "manual_corrections": _json_list(row.get("manual_corrections")),
        "production_ready_shadow": True,
        "db_write_eligible": True,
    }
    if reconciled:
        raw_payload.update(
            {
                "source_id_reconciliation_version": (
                    "lidl-corpus-source-id-reconciliation-v1"
                ),
                "source_id_reconciliation_plan_sha256": identity_plan_sha256,
                "source_id_identity_origin": identity_origin,
                "source_id_semantic_digest_sha256": semantic_digest_sha256,
            }
        )

    return OfferCandidate(
        source_chain=SourceChain.LIDL,
        source_store_external_id=FAMILY_STORE_EXTERNAL_ID,
        source_store_name=FAMILY_STORE_NAME,
        source_offer_id=(
            source_offer_id_override
            if source_offer_id_override is not None
            else source_offer_id(
                context.flyer_key,
                context.scan_name,
                ordinal,
                row,
            )
        ),
        product_name_raw=product,
        brand_raw=None,
        description_raw=None,
        package_text_raw=_none(row.get("package_text")),
        price_eur=price,
        regular_price_eur=_decimal(row.get("regular_price_eur")),
        unit_price_eur=None,
        unit_label=None,
        discount_percent=None,
        app_price_eur=app_price,
        requires_app=app_price is not None,
        coupon_required=False,
        valid_from=valid_from,
        valid_until=valid_until,
        app_valid_from=valid_from if app_price is not None else None,
        app_valid_until=valid_until if app_price is not None else None,
        source_url=context.viewer_url,
        source_image_url=None,
        snapshot_id=snapshot.id,
        collected_at=context.collected_at,
        parser_version=context.parser_version,
        raw_payload=raw_payload,
    )


def build_safe_offers(
    *,
    flyer_dir: Path,
    scan_name: str,
    snapshot: SourceSnapshot,
    expected_raw_sha256: str,
    expected_pdf_sha256: str,
    expected_count: int,
) -> list[OfferCandidate]:
    context = load_context(
        flyer_dir=flyer_dir,
        scan_name=scan_name,
        expected_raw_sha256=expected_raw_sha256,
        expected_pdf_sha256=expected_pdf_sha256,
    )
    rows = safe_rows(flyer_dir / "scans" / scan_name)
    if len(rows) != expected_count:
        raise ValueError(
            f"Safe row count mismatch: expected {expected_count}, got {len(rows)}"
        )
    offers = [
        build_offer(
            row=row,
            ordinal=ordinal,
            context=context,
            snapshot=snapshot,
        )
        for ordinal, row in enumerate(rows, start=1)
    ]
    if len({str(offer.source_offer_id) for offer in offers}) != len(offers):
        raise ValueError("Safe offer identities are not unique")
    return offers


def build_reconciled_safe_offers(
    *,
    flyer_dir: Path,
    scan_name: str,
    snapshot: SourceSnapshot,
    expected_raw_sha256: str,
    expected_pdf_sha256: str,
    expected_count: int,
    identity_plan_path: Path,
    expected_identity_plan_sha256: str,
) -> list[OfferCandidate]:
    context = load_context(
        flyer_dir=flyer_dir,
        scan_name=scan_name,
        expected_raw_sha256=expected_raw_sha256,
        expected_pdf_sha256=expected_pdf_sha256,
    )
    rows = safe_rows(flyer_dir / "scans" / scan_name)
    if len(rows) != expected_count:
        raise ValueError(
            f"Safe row count mismatch: expected {expected_count}, got {len(rows)}"
        )
    plan = load_reconciliation_plan(
        path=identity_plan_path,
        expected_sha256=expected_identity_plan_sha256,
        flyer_key=context.flyer_key,
        scan_name=scan_name,
        parser_version=context.parser_version,
        parser_sha256=context.parser_sha256,
        raw_sha256=context.raw_sha256,
        pdf_sha256=context.pdf_sha256,
        safe_rows=rows,
    )
    offers = [
        build_offer(
            row=row,
            ordinal=ordinal,
            context=context,
            snapshot=snapshot,
            source_offer_id_override=str(entry["source_offer_id"]),
            identity_origin=str(entry["identity_origin"]),
            identity_plan_sha256=plan.sha256,
            semantic_digest_sha256=str(entry["semantic_digest_sha256"]),
        )
        for ordinal, (row, entry) in enumerate(
            zip(rows, plan.entries),
            start=1,
        )
    ]
    if len({str(offer.source_offer_id) for offer in offers}) != len(offers):
        raise ValueError("Reconciled safe offer identities are not unique")
    return offers


def review_reason_codes(row: dict[str, str]) -> list[str]:
    reasons: list[str] = []
    if row.get("scope") == "review":
        reasons.append("scope_requires_review")
    if row.get("price_basis") == "variable_weight_example":
        reasons.append("variable_weight_requires_review")
    for warning in _json_list(row.get("warnings")):
        text = str(warning).strip()
        if text:
            reasons.append(text)
    if not reasons:
        reasons.append("parser_requires_review")
    return sorted(set(reasons))


def _review_original_payload(
    *,
    row: dict[str, str],
    context: FlyerContext,
    page: int,
) -> dict[str, Any]:
    image_url = _page_visual(context, page)
    return {
        "product_name": _none(row.get("product_name")),
        "product_name_raw": _none(row.get("product_name")),
        "brand": None,
        "brand_raw": None,
        "package_text": _none(row.get("package_text")),
        "package_text_raw": _none(row.get("package_text")),
        "price_eur": _none(row.get("price_eur")),
        "regular_price_eur": _none(row.get("regular_price_eur")),
        "app_price_eur": _none(row.get("app_price_eur")),
        "valid_from": _none(row.get("valid_from")),
        "valid_until": _none(row.get("valid_until")),
        "scope": row.get("scope"),
        "channel": row.get("channel"),
        "source_url": context.viewer_url,
        "source_image_url": image_url,
        "source_store_external_id": FAMILY_STORE_EXTERNAL_ID,
        "source_store_name": FAMILY_STORE_NAME,
        "price_basis": row.get("price_basis"),
        "scope_source": row.get("scope_source"),
        "channel_source": row.get("channel_source"),
        "validity_source": row.get("validity_source"),
        "warnings": _json_list(row.get("warnings")),
        "corpus_row": dict(row),
    }


def seed_review_rows(
    db: Session,
    *,
    flyer_dir: Path,
    scan_name: str,
    snapshot: SourceSnapshot,
    expected_raw_sha256: str,
    expected_pdf_sha256: str,
    expected_count: int,
) -> list[OfferReviewItem]:
    context = load_context(
        flyer_dir=flyer_dir,
        scan_name=scan_name,
        expected_raw_sha256=expected_raw_sha256,
        expected_pdf_sha256=expected_pdf_sha256,
    )
    rows = review_rows(flyer_dir / "scans" / scan_name)
    if len(rows) != expected_count:
        raise ValueError(
            f"Review row count mismatch: expected {expected_count}, got {len(rows)}"
        )

    items: list[OfferReviewItem] = []
    for ordinal, row in enumerate(rows, start=1):
        page = int(row.get("page") or 0)
        if page <= 0:
            raise ValueError("Review row has invalid page")
        image_url = _page_visual(context, page)
        key = source_row_key(scan_name, ordinal, row)
        provenance = {
            "corpus_import_version": CORPUS_IMPORT_VERSION,
            "flyer_key": context.flyer_key,
            "scan": scan_name,
            "source_row_key": key,
            "source_row_ordinal": ordinal,
            "page": page,
            "source_snapshot_id": str(snapshot.id),
            "source_snapshot_sha256": context.raw_sha256,
            "source_pdf_sha256": context.pdf_sha256,
            "official_flyer_id": context.official_flyer_id,
            "region": context.region,
            "source_url": context.viewer_url,
            "document_url": context.document_url,
            "page_image_url": image_url,
            "crop_url": image_url,
            "crop_kind": "full_page_fallback",
            "parser_version": context.parser_version,
            "parser_sha256": context.parser_sha256,
        }
        item = seed_review_item(
            db,
            source_chain="lidl",
            source_flyer_key=context.flyer_key,
            source_row_key=key,
            parser_version=context.parser_version,
            original_payload=_review_original_payload(
                row=row,
                context=context,
                page=page,
            ),
            provenance_json=provenance,
            reason_codes=review_reason_codes(row),
            source_snapshot_id=snapshot.id,
            page_number=page,
        )
        items.append(item)

    return items


def seed_reconciled_review_rows(
    db: Session,
    *,
    flyer_dir: Path,
    scan_name: str,
    snapshot: SourceSnapshot,
    expected_raw_sha256: str,
    expected_pdf_sha256: str,
    review_plan_path: Path,
    expected_review_plan_sha256: str,
    expected_count: int,
) -> dict[str, Any]:
    context = load_context(
        flyer_dir=flyer_dir,
        scan_name=scan_name,
        expected_raw_sha256=expected_raw_sha256,
        expected_pdf_sha256=expected_pdf_sha256,
    )
    if snapshot.source_chain != "lidl" or snapshot.sha256 != context.raw_sha256:
        raise ValueError("Filtered review seed snapshot does not match flyer source")

    rows = review_rows(flyer_dir / "scans" / scan_name)
    plan = load_review_seed_plan(
        path=review_plan_path,
        expected_sha256=expected_review_plan_sha256,
        flyer_key=context.flyer_key,
        scan_name=scan_name,
        raw_sha256=context.raw_sha256,
        pdf_sha256=context.pdf_sha256,
        snapshot_id=str(snapshot.id),
        review_rows=rows,
    )
    if len(plan.entries) != expected_count:
        raise ValueError(
            f"Filtered review seed count mismatch: "
            f"expected {expected_count}, got {len(plan.entries)}"
        )

    plan_ordinals = {
        int(entry["review_row_ordinal"])
        for entry in plan.entries
    }
    plan_keys = {
        str(entry["source_row_key"])
        for entry in plan.entries
    }
    existing_plan_items = list(
        db.scalars(
            select(OfferReviewItem)
            .where(
                OfferReviewItem.source_chain == "lidl",
                OfferReviewItem.source_flyer_key == context.flyer_key,
                OfferReviewItem.source_row_key.in_(plan_keys),
            )
            .order_by(OfferReviewItem.source_row_key.asc())
        ).all()
    )
    if len(existing_plan_items) not in {0, expected_count}:
        raise ValueError(
            "Filtered review seed is in a partial existing state: "
            f"{len(existing_plan_items)} of {expected_count}"
        )
    if existing_plan_items and {
        item.source_row_key for item in existing_plan_items
    } != plan_keys:
        raise ValueError("Filtered review seed existing identity set mismatch")

    eligible_rows = [
        (ordinal, row)
        for ordinal, row in enumerate(rows, start=1)
        if row.get("scope") in {"review", "in_scope"}
    ]
    omitted_rows = [
        (ordinal, row)
        for ordinal, row in eligible_rows
        if ordinal not in plan_ordinals
    ]
    if len(omitted_rows) != 47:
        raise ValueError("Filtered review seed suppressed-row count mismatch")

    existing_items = list(
        db.scalars(
            select(OfferReviewItem)
            .where(
                OfferReviewItem.source_chain == "lidl",
                OfferReviewItem.source_flyer_key == context.flyer_key,
            )
            .order_by(OfferReviewItem.id.asc())
        ).all()
    )
    existing_by_material: dict[str, list[OfferReviewItem]] = {}
    for item in existing_items:
        original = item.original_payload or {}
        corpus_row = original.get("corpus_row")
        if not isinstance(corpus_row, dict):
            continue
        material = review_canonical_row_material(corpus_row)
        existing_by_material.setdefault(material, []).append(item)

    suppressed_ids: list[str] = []
    published_ids: list[UUID] = []
    for _, row in omitted_rows:
        material = review_canonical_row_material(row)
        matches = existing_by_material.get(material, [])
        if len(matches) != 1:
            raise ValueError(
                "Filtered review seed suppressed row does not have "
                "one exact existing Review match"
            )
        item = matches[0]
        if item.status != "approved":
            raise ValueError("Filtered review seed suppressed row is not approved")
        if item.published_offer_candidate_id is None:
            raise ValueError(
                "Filtered review seed suppressed row lacks published offer"
            )
        published = db.get(
            OfferCandidateRecord,
            item.published_offer_candidate_id,
        )
        if published is None:
            raise ValueError(
                "Filtered review seed suppressed publication is missing"
            )
        suppressed_ids.append(str(item.id))
        published_ids.append(item.published_offer_candidate_id)

    if len(set(suppressed_ids)) != 47:
        raise ValueError("Filtered review seed suppressed Review identities drift")
    if len(set(published_ids)) != 47:
        raise ValueError("Filtered review seed suppressed publication identities drift")

    items: list[OfferReviewItem] = []
    for entry in plan.entries:
        ordinal = int(entry["review_row_ordinal"])
        row = rows[ordinal - 1]
        page = int(entry["page"])
        image_url = _page_visual(context, page)
        key = str(entry["source_row_key"])
        provenance = {
            "corpus_import_version": CORPUS_IMPORT_VERSION,
            "review_seed_workflow_version": REVIEW_SEED_WORKFLOW_VERSION,
            "review_seed_decision": REVIEW_SEED_DECISION,
            "review_seed_plan_sha256": plan.sha256,
            "flyer_key": context.flyer_key,
            "scan": scan_name,
            "source_row_key": key,
            "source_row_ordinal": ordinal,
            "row_digest_sha256": entry["row_digest_sha256"],
            "page": page,
            "source_snapshot_id": str(snapshot.id),
            "source_snapshot_sha256": context.raw_sha256,
            "source_pdf_sha256": context.pdf_sha256,
            "official_flyer_id": context.official_flyer_id,
            "region": context.region,
            "source_url": context.viewer_url,
            "document_url": context.document_url,
            "page_image_url": image_url,
            "crop_url": image_url,
            "crop_kind": "full_page_fallback",
            "parser_version": context.parser_version,
            "parser_sha256": context.parser_sha256,
        }
        item = seed_review_item(
            db,
            source_chain="lidl",
            source_flyer_key=context.flyer_key,
            source_row_key=key,
            parser_version=context.parser_version,
            original_payload=_review_original_payload(
                row=row,
                context=context,
                page=page,
            ),
            provenance_json=provenance,
            reason_codes=list(entry["reason_codes"]),
            source_snapshot_id=snapshot.id,
            page_number=page,
        )
        items.append(item)

    final_plan_items = list(
        db.scalars(
            select(OfferReviewItem)
            .where(
                OfferReviewItem.source_chain == "lidl",
                OfferReviewItem.source_flyer_key == context.flyer_key,
                OfferReviewItem.source_row_key.in_(plan_keys),
            )
            .order_by(OfferReviewItem.source_row_key.asc())
        ).all()
    )
    if len(final_plan_items) != expected_count:
        raise ValueError("Filtered review seed final identity count mismatch")
    for item in final_plan_items:
        if item.status != "pending":
            raise ValueError("Filtered review seed created non-pending item")
        if item.published_offer_candidate_id is not None:
            raise ValueError("Filtered review seed unexpectedly published an offer")
        if item.provenance_json.get("review_seed_plan_sha256") != plan.sha256:
            raise ValueError("Filtered review seed provenance plan SHA mismatch")

    created = expected_count if not existing_plan_items else 0
    return {
        "result": "RECONCILED_REVIEW_SEED_COMPLETE",
        "review_seed_plan_sha256": plan.sha256,
        "seeded_or_reused": expected_count,
        "created": created,
        "reused": expected_count - created,
        "suppressed_existing_approved_rows": 47,
        "scope_excluded_rows": 44,
        "review_seed": True,
        "offer_candidate_write": False,
        "auto_approve": False,
        "auto_publish": False,
        "delete_existing_rows": False,
        "update_existing_rows": False,
        "systemd_change": False,
        "timer_install": False,
    }


def _rescue_original_payload(
    *,
    record: dict[str, Any],
    context: FlyerContext,
) -> dict[str, Any]:
    page = int(record["page"])
    image_url = _page_visual(context, page)
    return {
        "product_name": record["product_name"],
        "product_name_raw": record["product_name"],
        "brand": None,
        "brand_raw": None,
        "package_text": record.get("package_text"),
        "package_text_raw": record.get("package_text"),
        "price_eur": record.get("price_eur"),
        "regular_price_eur": record.get("regular_price_eur"),
        "app_price_eur": record.get("app_price_eur"),
        "requires_app": bool(record.get("requires_app", False)),
        "valid_from": context.valid_from.isoformat(),
        "valid_until": context.valid_until.isoformat(),
        "scope": record["scope"],
        "channel": record["channel"],
        "source_url": context.viewer_url,
        "source_image_url": image_url,
        "source_store_external_id": FAMILY_STORE_EXTERNAL_ID,
        "source_store_name": FAMILY_STORE_NAME,
        "price_basis": "completeness_rescue_review",
        "scope_source": "completeness_rescue_evidence",
        "channel_source": "physical_flyer_binding",
        "validity_source": "flyer_validity",
        "warnings": rescue_reason_codes(record),
        "completeness_rescue": dict(record),
    }


def seed_completeness_rescue_rows(
    db: Session,
    *,
    flyer_dir: Path,
    scan_name: str,
    snapshot: SourceSnapshot,
    artifact_path: Path,
    expected_raw_sha256: str,
    expected_pdf_sha256: str,
    expected_count: int,
) -> list[OfferReviewItem]:
    context = load_context(
        flyer_dir=flyer_dir,
        scan_name=scan_name,
        expected_raw_sha256=expected_raw_sha256,
        expected_pdf_sha256=expected_pdf_sha256,
    )
    if snapshot.source_chain != "lidl" or snapshot.sha256 != context.raw_sha256:
        raise ValueError("Completeness rescue snapshot does not match flyer source")
    records = load_rescue_artifact(
        artifact_path,
        flyer_key=context.flyer_key,
        scan_name=scan_name,
        parser_version=context.parser_version,
        parser_sha256=context.parser_sha256,
        raw_sha256=context.raw_sha256,
        pdf_sha256=context.pdf_sha256,
        valid_pages=set(context.pages),
        expected_count=expected_count,
    )

    items: list[OfferReviewItem] = []
    for record in records:
        page = int(record["page"])
        image_url = _page_visual(context, page)
        key = rescue_row_key(scan_name, record)
        provenance = {
            "completeness_rescue_version": RESCUE_VERSION,
            "flyer_key": context.flyer_key,
            "scan": scan_name,
            "candidate_key": record["candidate_key"],
            "record_digest": record["record_digest"],
            "page": page,
            "bbox": list(record["bbox"]),
            "evidence_kind": record["evidence_kind"],
            "evidence_text": record["evidence_text"],
            "confidence": record.get("confidence"),
            "source_snapshot_id": str(snapshot.id),
            "source_snapshot_sha256": context.raw_sha256,
            "source_pdf_sha256": context.pdf_sha256,
            "official_flyer_id": context.official_flyer_id,
            "region": context.region,
            "source_url": context.viewer_url,
            "document_url": context.document_url,
            "page_image_url": image_url,
            "crop_url": image_url,
            "crop_kind": "bbox_evidence",
            "base_parser_version": context.parser_version,
            "base_parser_sha256": context.parser_sha256,
        }
        item = seed_review_item(
            db,
            source_chain="lidl",
            source_flyer_key=context.flyer_key,
            source_row_key=key,
            parser_version=RESCUE_VERSION,
            original_payload=_rescue_original_payload(record=record, context=context),
            provenance_json=provenance,
            reason_codes=rescue_reason_codes(record),
            source_snapshot_id=snapshot.id,
            page_number=page,
        )
        items.append(item)
    return items


def persist_safe_offers(
    db: Session,
    *,
    flyer_dir: Path,
    scan_name: str,
    snapshot: SourceSnapshot,
    expected_raw_sha256: str,
    expected_pdf_sha256: str,
    expected_count: int,
    commit: bool = True,
) -> tuple[int, list[OfferCandidate]]:
    offers = build_safe_offers(
        flyer_dir=flyer_dir,
        scan_name=scan_name,
        snapshot=snapshot,
        expected_raw_sha256=expected_raw_sha256,
        expected_pdf_sha256=expected_pdf_sha256,
        expected_count=expected_count,
    )
    written = save_offer_candidates(db, offers, commit=commit)
    return written, offers


def persist_reconciled_safe_offers(
    db: Session,
    *,
    flyer_dir: Path,
    scan_name: str,
    snapshot: SourceSnapshot,
    expected_raw_sha256: str,
    expected_pdf_sha256: str,
    expected_count: int,
    identity_plan_path: Path,
    expected_identity_plan_sha256: str,
    commit: bool = True,
) -> tuple[int, list[OfferCandidate]]:
    offers = build_reconciled_safe_offers(
        flyer_dir=flyer_dir,
        scan_name=scan_name,
        snapshot=snapshot,
        expected_raw_sha256=expected_raw_sha256,
        expected_pdf_sha256=expected_pdf_sha256,
        expected_count=expected_count,
        identity_plan_path=identity_plan_path,
        expected_identity_plan_sha256=expected_identity_plan_sha256,
    )
    written = save_offer_candidates(db, offers, commit=commit)
    return written, offers


def import_reconciled_safe(
    db: Session,
    *,
    flyer_dir: Path,
    scan_name: str,
    raw_root: Path,
    db_raw_prefix: str,
    expected_raw_sha256: str,
    expected_pdf_sha256: str,
    expected_count: int,
    identity_plan_path: Path,
    expected_identity_plan_sha256: str,
    approval_path: Path,
    expected_approval_sha256: str,
) -> dict[str, Any]:
    context = load_context(
        flyer_dir=flyer_dir,
        scan_name=scan_name,
        expected_raw_sha256=expected_raw_sha256,
        expected_pdf_sha256=expected_pdf_sha256,
    )
    rows = safe_rows(flyer_dir / "scans" / scan_name)
    plan = load_reconciliation_plan(
        path=identity_plan_path,
        expected_sha256=expected_identity_plan_sha256,
        flyer_key=context.flyer_key,
        scan_name=scan_name,
        parser_version=context.parser_version,
        parser_sha256=context.parser_sha256,
        raw_sha256=context.raw_sha256,
        pdf_sha256=context.pdf_sha256,
        safe_rows=rows,
    )
    validate_import_approval(
        path=approval_path,
        expected_sha256=expected_approval_sha256,
        flyer_key=context.flyer_key,
        scan_name=scan_name,
        raw_sha256=context.raw_sha256,
        pdf_sha256=context.pdf_sha256,
        identity_plan_sha256=plan.sha256,
    )
    if len(rows) != expected_count:
        raise ValueError(
            f"Safe row count mismatch: expected {expected_count}, got {len(rows)}"
        )
    if db.in_transaction():
        raise ValueError("Reconciled import requires a fresh database transaction")

    deterministic_id = _snapshot_identity(context.raw_sha256)
    snapshot_created = False
    with db.begin():
        snapshot_created = db.get(SourceSnapshot, deterministic_id) is None
        snapshot = register_source_snapshot(
            db,
            flyer_dir=flyer_dir,
            scan_name=scan_name,
            raw_root=raw_root,
            db_raw_prefix=db_raw_prefix,
            expected_raw_sha256=expected_raw_sha256,
            expected_pdf_sha256=expected_pdf_sha256,
            commit=False,
        )
        written, offers = persist_reconciled_safe_offers(
            db,
            flyer_dir=flyer_dir,
            scan_name=scan_name,
            snapshot=snapshot,
            expected_raw_sha256=expected_raw_sha256,
            expected_pdf_sha256=expected_pdf_sha256,
            expected_count=expected_count,
            identity_plan_path=identity_plan_path,
            expected_identity_plan_sha256=expected_identity_plan_sha256,
            commit=False,
        )
        persisted = int(
            db.scalar(
                select(func.count())
                .select_from(OfferCandidateRecord)
                .where(OfferCandidateRecord.snapshot_id == snapshot.id)
            )
            or 0
        )
        if persisted != expected_count:
            raise ValueError(
                f"Reconciled snapshot persisted {persisted}; expected {expected_count}"
            )
        snapshot_id = str(snapshot.id)
        expected_offers = len(offers)

    return {
        "result": "RECONCILED_SAFE_IMPORT_COMPLETE",
        "snapshot_id": snapshot_id,
        "snapshot_created": snapshot_created,
        "written": written,
        "expected": expected_offers,
        "snapshot_persisted": persisted,
        "identity_plan_sha256": plan.sha256,
        "approval_sha256": expected_approval_sha256,
        "review_seed": False,
        "auto_approve": False,
        "auto_publish": False,
        "systemd_change": False,
        "timer_install": False,
    }


def _session():
    from app.db import SessionLocal

    return SessionLocal()


def _command_validate(args: argparse.Namespace) -> int:
    report = validate_scan_contract(
        flyer_dir=Path(args.flyer_dir),
        scan_name=args.scan,
        expected_safe_count=args.safe_count,
        expected_review_count=args.review_count,
        expected_raw_sha256=args.raw_sha,
        expected_pdf_sha256=args.pdf_sha,
    )
    print(json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


def _command_register(args: argparse.Namespace) -> int:
    with _session() as db:
        snapshot = register_source_snapshot(
            db,
            flyer_dir=Path(args.flyer_dir),
            scan_name=args.scan,
            raw_root=Path(args.raw_root),
            db_raw_prefix=args.db_raw_prefix,
            expected_raw_sha256=args.raw_sha,
            expected_pdf_sha256=args.pdf_sha,
        )
        print(
            json.dumps(
                {
                    "snapshot_id": str(snapshot.id),
                    "sha256": snapshot.sha256,
                    "scope": snapshot.scope,
                    "snapshot_path": snapshot.snapshot_path,
                },
                sort_keys=True,
            )
        )
    return 0


def _command_seed_review(args: argparse.Namespace) -> int:
    with _session() as db:
        snapshot = db.get(SourceSnapshot, UUID(args.snapshot_id))
        if snapshot is None:
            raise ValueError("SourceSnapshot not found")
        items = seed_review_rows(
            db,
            flyer_dir=Path(args.flyer_dir),
            scan_name=args.scan,
            snapshot=snapshot,
            expected_raw_sha256=args.raw_sha,
            expected_pdf_sha256=args.pdf_sha,
            expected_count=args.review_count,
        )
        total = int(
            db.scalar(
                select(func.count())
                .select_from(OfferReviewItem)
                .where(
                    OfferReviewItem.source_chain == "lidl",
                    OfferReviewItem.source_flyer_key == Path(args.flyer_dir).name,
                )
            )
            or 0
        )
        print(json.dumps({"seeded_or_reused": len(items), "flyer_total": total}))
    return 0


def _command_seed_reconciled_review(args: argparse.Namespace) -> int:
    with _session() as db:
        snapshot = db.get(SourceSnapshot, UUID(args.snapshot_id))
        if snapshot is None:
            raise ValueError("SourceSnapshot not found")
        result = seed_reconciled_review_rows(
            db,
            flyer_dir=Path(args.flyer_dir),
            scan_name=args.scan,
            snapshot=snapshot,
            expected_raw_sha256=args.raw_sha,
            expected_pdf_sha256=args.pdf_sha,
            review_plan_path=Path(args.review_plan),
            expected_review_plan_sha256=args.review_plan_sha,
            expected_count=args.review_count,
        )
        print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


def _command_validate_rescue(args: argparse.Namespace) -> int:
    context = load_context(
        flyer_dir=Path(args.flyer_dir),
        scan_name=args.scan,
        expected_raw_sha256=args.raw_sha,
        expected_pdf_sha256=args.pdf_sha,
    )
    records = load_rescue_artifact(
        Path(args.artifact),
        flyer_key=context.flyer_key,
        scan_name=args.scan,
        parser_version=context.parser_version,
        parser_sha256=context.parser_sha256,
        raw_sha256=context.raw_sha256,
        pdf_sha256=context.pdf_sha256,
        valid_pages=set(context.pages),
        expected_count=args.rescue_count,
    )
    print(
        json.dumps(
            {
                "rescue_version": RESCUE_VERSION,
                "count": len(records),
                "candidate_keys": [r["candidate_key"] for r in records],
                "review_only": True,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


def _command_seed_rescue(args: argparse.Namespace) -> int:
    with _session() as db:
        snapshot = db.get(SourceSnapshot, UUID(args.snapshot_id))
        if snapshot is None:
            raise ValueError("SourceSnapshot not found")
        items = seed_completeness_rescue_rows(
            db,
            flyer_dir=Path(args.flyer_dir),
            scan_name=args.scan,
            snapshot=snapshot,
            artifact_path=Path(args.artifact),
            expected_raw_sha256=args.raw_sha,
            expected_pdf_sha256=args.pdf_sha,
            expected_count=args.rescue_count,
        )
        print(
            json.dumps(
                {
                    "seeded_or_reused": len(items),
                    "review_only": True,
                    "review_ids": [str(item.id) for item in items],
                },
                sort_keys=True,
            )
        )
    return 0


def _command_promote_safe(args: argparse.Namespace) -> int:
    with _session() as db:
        snapshot = db.get(SourceSnapshot, UUID(args.snapshot_id))
        if snapshot is None:
            raise ValueError("SourceSnapshot not found")
        written, offers = persist_safe_offers(
            db,
            flyer_dir=Path(args.flyer_dir),
            scan_name=args.scan,
            snapshot=snapshot,
            expected_raw_sha256=args.raw_sha,
            expected_pdf_sha256=args.pdf_sha,
            expected_count=args.safe_count,
        )
        persisted = int(
            db.scalar(
                select(func.count())
                .select_from(OfferCandidateRecord)
                .where(OfferCandidateRecord.snapshot_id == snapshot.id)
            )
            or 0
        )
        print(
            json.dumps(
                {
                    "written": written,
                    "expected": len(offers),
                    "snapshot_persisted": persisted,
                },
                sort_keys=True,
            )
        )
    return 0


def _command_import_reconciled_safe(args: argparse.Namespace) -> int:
    with _session() as db:
        report = import_reconciled_safe(
            db,
            flyer_dir=Path(args.flyer_dir),
            scan_name=args.scan,
            raw_root=Path(args.raw_root),
            db_raw_prefix=args.db_raw_prefix,
            expected_raw_sha256=args.raw_sha,
            expected_pdf_sha256=args.pdf_sha,
            expected_count=args.safe_count,
            identity_plan_path=Path(args.identity_plan),
            expected_identity_plan_sha256=args.identity_plan_sha,
            approval_path=Path(args.approval),
            expected_approval_sha256=args.approval_sha,
        )
        print(json.dumps(report, sort_keys=True))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="lidl-corpus-import")
    sub = parser.add_subparsers(dest="command", required=True)

    def common(p: argparse.ArgumentParser) -> None:
        p.add_argument("--flyer-dir", required=True)
        p.add_argument("--scan", required=True)
        p.add_argument("--raw-sha", required=True)
        p.add_argument("--pdf-sha", required=True)

    p = sub.add_parser("validate")
    common(p)
    p.add_argument("--safe-count", required=True, type=int)
    p.add_argument("--review-count", required=True, type=int)
    p.set_defaults(func=_command_validate)

    p = sub.add_parser("register-source")
    common(p)
    p.add_argument("--raw-root", required=True)
    p.add_argument("--db-raw-prefix", default="/data/raw")
    p.set_defaults(func=_command_register)

    p = sub.add_parser("seed-review")
    common(p)
    p.add_argument("--snapshot-id", required=True)
    p.add_argument("--review-count", required=True, type=int)
    p.set_defaults(func=_command_seed_review)

    p = sub.add_parser("seed-reconciled-review")
    common(p)
    p.add_argument("--snapshot-id", required=True)
    p.add_argument("--review-count", required=True, type=int)
    p.add_argument("--review-plan", required=True)
    p.add_argument("--review-plan-sha", required=True)
    p.set_defaults(func=_command_seed_reconciled_review)

    p = sub.add_parser("validate-rescue")
    common(p)
    p.add_argument("--artifact", required=True)
    p.add_argument("--rescue-count", required=True, type=int)
    p.set_defaults(func=_command_validate_rescue)

    p = sub.add_parser("seed-rescue")
    common(p)
    p.add_argument("--snapshot-id", required=True)
    p.add_argument("--artifact", required=True)
    p.add_argument("--rescue-count", required=True, type=int)
    p.set_defaults(func=_command_seed_rescue)

    p = sub.add_parser("promote-safe")
    common(p)
    p.add_argument("--snapshot-id", required=True)
    p.add_argument("--safe-count", required=True, type=int)
    p.set_defaults(func=_command_promote_safe)

    p = sub.add_parser("import-reconciled-safe")
    common(p)
    p.add_argument("--raw-root", required=True)
    p.add_argument("--db-raw-prefix", default="/data/raw")
    p.add_argument("--safe-count", required=True, type=int)
    p.add_argument("--identity-plan", required=True)
    p.add_argument("--identity-plan-sha", required=True)
    p.add_argument("--approval", required=True)
    p.add_argument("--approval-sha", required=True)
    p.set_defaults(func=_command_import_reconciled_safe)

    return parser


def main() -> int:
    args = build_parser().parse_args()
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
