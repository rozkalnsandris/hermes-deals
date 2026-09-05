from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Literal
from uuid import NAMESPACE_URL, UUID, uuid5

from sqlalchemy import delete, func, or_, select, text
from sqlalchemy.orm import Session

from app.db import SessionLocal
from app.edeka_normalization_audit import (
    EXPECTED_INTERNAL_MARKET_ID,
    EXPECTED_PUBLIC_MARKET_ID,
    EXPECTED_SCOPE,
    EXPECTED_SOURCE_URL,
    EXPECTED_STORE_NAME,
    build_edeka_normalization_report,
)
from app.models import (
    CanonicalProduct,
    OfferCandidateRecord,
    OfferNormalization,
    OfferProductLink,
    OfferReviewItem,
    OfferReviewRevision,
    ProductMatchCandidate,
    SourceSnapshot,
)
from app.offer_store import save_offer_candidates
from app.parsers.edeka import EdekaParserContext, PARSER_VERSION, parse_edeka_html
from app.product_normalizer import NORMALIZER_VERSION, normalize_offer_fields
from app.schemas import OfferCandidate

PLAN_SCHEMA_VERSION = 1
AUTH_SCHEMA_VERSION = 1
AUTHORIZATION_TYPE = "edeka_production_canary_v01"
CANARY_STRATEGY = "edeka_production_canary_v01"
CANARY_CONTENT_TYPE = "application/vnd.hermes-deals.edeka-production-canary+json"
Mode = Literal["verify", "apply", "rollback"]

_MONITORED_MODELS = {
    "source_snapshots": SourceSnapshot,
    "offer_candidates": OfferCandidateRecord,
    "offer_normalizations": OfferNormalization,
    "product_match_candidates": ProductMatchCandidate,
    "offer_product_links": OfferProductLink,
    "canonical_products": CanonicalProduct,
    "offer_review_items": OfferReviewItem,
    "offer_review_revisions": OfferReviewRevision,
}


@dataclass(frozen=True)
class CanaryPlan:
    payload: dict[str, Any]
    sha256: str

    @property
    def plan_id(self) -> str:
        return str(self.payload["plan_id"])

    @property
    def source(self) -> dict[str, Any]:
        return self.payload["authoritative_source"]

    @property
    def market(self) -> dict[str, Any]:
        return self.payload["market"]

    @property
    def rows(self) -> list[dict[str, Any]]:
        return self.payload["canary_rows"]

    @property
    def expected_first_delta(self) -> dict[str, int]:
        return self.payload["expected_first_apply_delta"]

    @property
    def expected_replay_delta(self) -> dict[str, int]:
        return self.payload["expected_exact_replay_delta"]


@dataclass(frozen=True)
class CanaryEvidence:
    manifest_path: Path
    raw_html_path: Path
    manifest: dict[str, Any]
    raw_html: bytes
    offers: list[OfferCandidate]
    selected_offers: list[OfferCandidate]
    normalization_report: dict[str, Any]


def _json_object(path: Path, *, label: str) -> tuple[dict[str, Any], bytes]:
    data = path.read_bytes()
    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError(f"{label} must be a JSON object")
    return payload, data


def _require_exact_keys(
    actual: dict[str, Any],
    expected: set[str],
    *,
    label: str,
) -> None:
    if set(actual) != expected:
        raise ValueError(
            f"{label} keys mismatch: expected={sorted(expected)} "
            f"actual={sorted(actual)}"
        )


def load_plan(path: Path) -> CanaryPlan:
    payload, data = _json_object(path, label="EDEKA canary plan")
    if payload.get("schema_version") != PLAN_SCHEMA_VERSION:
        raise ValueError("EDEKA canary plan schema_version mismatch")
    if payload.get("state") != "preparation_only":
        raise ValueError("EDEKA canary v01 requires preparation_only plan state")
    if payload.get("production_apply_authorized") is not False:
        raise ValueError(
            "EDEKA canary plan must not itself authorize production apply"
        )

    market = payload.get("market")
    source = payload.get("authoritative_source")
    preflight = payload.get("preflight")
    rollback = payload.get("rollback")
    rows = payload.get("canary_rows")
    first_delta = payload.get("expected_first_apply_delta")
    replay_delta = payload.get("expected_exact_replay_delta")
    if not all(
        isinstance(value, dict)
        for value in (market, source, preflight, rollback)
    ):
        raise ValueError("EDEKA canary plan object sections are incomplete")
    if not isinstance(rows, list) or len(rows) != 3:
        raise ValueError("EDEKA canary plan requires exactly three canary rows")
    if not isinstance(first_delta, dict) or not isinstance(replay_delta, dict):
        raise ValueError("EDEKA canary plan delta sections are missing")

    expected_market = {
        "source_chain": "edeka",
        "scope": EXPECTED_SCOPE,
        "public_market_id": EXPECTED_PUBLIC_MARKET_ID,
        "internal_market_id": EXPECTED_INTERNAL_MARKET_ID,
        "store_name": EXPECTED_STORE_NAME,
        "source_url": EXPECTED_SOURCE_URL,
    }
    for key, expected in expected_market.items():
        if market.get(key) != expected:
            raise ValueError(f"EDEKA canary plan market {key} mismatch")

    if source.get("parser_version") != PARSER_VERSION:
        raise ValueError(
            "EDEKA canary plan parser version differs from current parser"
        )
    if source.get("normalizer_version") != NORMALIZER_VERSION:
        raise ValueError(
            "EDEKA canary plan normalizer version differs from current normalizer"
        )
    if source.get("full_offer_count") != 203:
        raise ValueError("EDEKA canary v01 authoritative offer count mismatch")

    expected_delta_keys = set(_MONITORED_MODELS)
    _require_exact_keys(
        first_delta,
        expected_delta_keys,
        label="first apply delta",
    )
    _require_exact_keys(
        replay_delta,
        expected_delta_keys,
        label="replay delta",
    )
    if first_delta != {
        "source_snapshots": 1,
        "offer_candidates": 3,
        "offer_normalizations": 3,
        "product_match_candidates": 0,
        "offer_product_links": 0,
        "canonical_products": 0,
        "offer_review_items": 0,
        "offer_review_revisions": 0,
    }:
        raise ValueError("EDEKA canary v01 first-apply delta contract mismatch")
    if any(int(value) != 0 for value in replay_delta.values()):
        raise ValueError("EDEKA canary v01 replay delta must be all zero")

    required_preflight = {
        "required_alembic_head": "0007_comparison_family_pricing",
        "require_exact_source_hashes": True,
        "require_exact_three_source_offer_ids": True,
        "require_no_existing_canary_snapshot_binding": True,
        "require_baseline_counts": True,
        "require_rollback_backup_before_write": True,
        "fail_on_any_review_route": True,
        "fail_on_any_source_or_market_mismatch": True,
        "fail_on_unexpected_dependency_rows": True,
    }
    for key, expected in required_preflight.items():
        if preflight.get(key) != expected:
            raise ValueError(f"EDEKA canary plan preflight {key} mismatch")

    if rollback.get("scope") != "captured_canary_ids_only":
        raise ValueError("EDEKA canary rollback scope mismatch")
    if rollback.get("delete_order") != [
        "offer_normalizations",
        "offer_candidates",
        "source_snapshots",
    ]:
        raise ValueError("EDEKA canary rollback delete order mismatch")
    if rollback.get("broad_delete_by_chain_forbidden") is not True:
        raise ValueError("EDEKA canary rollback must forbid broad chain deletes")

    source_offer_ids = [
        row.get("source_offer_id")
        for row in rows
        if isinstance(row, dict)
    ]
    if (
        len(source_offer_ids) != 3
        or any(
            not isinstance(value, str) or not value
            for value in source_offer_ids
        )
        or len(set(source_offer_ids)) != 3
    ):
        raise ValueError(
            "EDEKA canary rows require three unique source_offer_id values"
        )
    if any(row.get("review_required") is not False for row in rows):
        raise ValueError("EDEKA canary v01 rows must all be resolved")

    return CanaryPlan(payload=payload, sha256=sha256(data).hexdigest())


def _manifest_context(
    plan: CanaryPlan,
    manifest: dict[str, Any],
) -> EdekaParserContext:
    expected = {
        "source_chain": "edeka",
        "scope": EXPECTED_SCOPE,
        "public_market_id": EXPECTED_PUBLIC_MARKET_ID,
        "internal_market_id": EXPECTED_INTERNAL_MARKET_ID,
        "store_name": EXPECTED_STORE_NAME,
        "source_url": EXPECTED_SOURCE_URL,
        "final_url": EXPECTED_SOURCE_URL,
        "snapshot_id": plan.source["shadow_snapshot_id"],
        "valid_from": plan.source["campaign_valid_from"],
        "valid_until": plan.source["campaign_valid_until"],
        "offer_count": plan.source["full_offer_count"],
        "raw_html_sha256": plan.source["raw_html_sha256"],
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"EDEKA canary manifest {key} mismatch")

    try:
        snapshot_id = UUID(str(manifest["snapshot_id"]))
        collected_at = datetime.fromisoformat(str(manifest["collected_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError("EDEKA canary manifest identity is incomplete") from exc
    if collected_at.tzinfo is None or collected_at.utcoffset() is None:
        raise ValueError("EDEKA canary manifest collected_at must be timezone-aware")

    return EdekaParserContext(
        snapshot_id=snapshot_id,
        source_url=EXPECTED_SOURCE_URL,
        collected_at=collected_at,
        public_market_id=EXPECTED_PUBLIC_MARKET_ID,
        internal_market_id=EXPECTED_INTERNAL_MARKET_ID,
        store_name=EXPECTED_STORE_NAME,
    )


def _validate_selected_row(
    plan_row: dict[str, Any],
    offer: OfferCandidate,
    report_row: dict[str, Any],
) -> None:
    expected_offer = {
        "source_offer_id": plan_row["source_offer_id"],
        "product_name_raw": plan_row["product_name_raw"],
        "price_eur": Decimal(str(plan_row["price_eur"])),
        "valid_from": str(plan_row["valid_from"]),
        "valid_until": str(plan_row["valid_until"]),
        "dialog_id": plan_row["dialog_id"],
    }
    actual_offer = {
        "source_offer_id": offer.source_offer_id,
        "product_name_raw": offer.product_name_raw,
        "price_eur": offer.price_eur,
        "valid_from": (
            offer.valid_from.isoformat() if offer.valid_from else None
        ),
        "valid_until": (
            offer.valid_until.isoformat() if offer.valid_until else None
        ),
        "dialog_id": offer.raw_payload.get("dialog_id"),
    }
    if actual_offer != expected_offer:
        raise ValueError(
            "EDEKA canary selected offer differs from immutable plan: "
            f"{plan_row['source_offer_id']}"
        )

    expected_report = {
        "normalized_name": plan_row["normalized_name"],
        "normalized_brand": plan_row["normalized_brand"],
        "package_parse_method": plan_row["package_parse_method"],
        "package_evidence_source": plan_row["package_evidence_source"],
        "package_signature": plan_row["package_signature"],
        "status": "resolved",
    }
    actual_report = {
        key: report_row.get(key)
        for key in (
            "normalized_name",
            "normalized_brand",
            "package_parse_method",
            "package_evidence_source",
            "package_signature",
            "status",
        )
    }
    if actual_report != expected_report:
        raise ValueError(
            "EDEKA canary selected normalization differs from immutable plan: "
            f"{plan_row['source_offer_id']}"
        )


def load_evidence(
    plan: CanaryPlan,
    *,
    manifest_path: Path,
    raw_html_path: Path,
) -> CanaryEvidence:
    manifest, manifest_bytes = _json_object(
        manifest_path,
        label="EDEKA retained manifest",
    )
    if sha256(manifest_bytes).hexdigest() != plan.source["manifest_sha256"]:
        raise ValueError("EDEKA canary retained manifest SHA mismatch")

    raw_html = raw_html_path.read_bytes()
    if sha256(raw_html).hexdigest() != plan.source["raw_html_sha256"]:
        raise ValueError("EDEKA canary retained raw HTML SHA mismatch")

    context = _manifest_context(plan, manifest)
    offers = parse_edeka_html(raw_html, context)
    if len(offers) != plan.source["full_offer_count"]:
        raise ValueError("EDEKA canary parsed offer count mismatch")
    if {offer.parser_version for offer in offers} != {
        plan.source["parser_version"]
    }:
        raise ValueError("EDEKA canary parsed offer parser version mismatch")

    report = build_edeka_normalization_report(
        offers,
        manifest_sha256=plan.source["manifest_sha256"],
    )
    if report.get("normalizer_version") != plan.source["normalizer_version"]:
        raise ValueError("EDEKA canary normalization report version mismatch")
    summary = report.get("summary")
    if not isinstance(summary, dict):
        raise ValueError("EDEKA canary normalization report summary missing")
    if summary.get("rows_sha256") != plan.source["full_normalization_rows_sha256"]:
        raise ValueError("EDEKA canary full normalization rows SHA mismatch")

    offer_by_id = {str(offer.source_offer_id): offer for offer in offers}
    report_rows = report.get("rows")
    if not isinstance(report_rows, list):
        raise ValueError("EDEKA canary normalization report rows missing")
    report_by_id = {
        str(row["source_offer_id"]): row
        for row in report_rows
        if isinstance(row, dict) and "source_offer_id" in row
    }

    selected: list[OfferCandidate] = []
    for plan_row in plan.rows:
        source_offer_id = str(plan_row["source_offer_id"])
        offer = offer_by_id.get(source_offer_id)
        report_row = report_by_id.get(source_offer_id)
        if offer is None or report_row is None:
            raise ValueError(
                "EDEKA canary source_offer_id missing from retained evidence: "
                f"{source_offer_id}"
            )
        _validate_selected_row(plan_row, offer, report_row)
        selected.append(offer)

    return CanaryEvidence(
        manifest_path=manifest_path,
        raw_html_path=raw_html_path,
        manifest=manifest,
        raw_html=raw_html,
        offers=offers,
        selected_offers=selected,
        normalization_report=report,
    )


def _canary_snapshot_id(plan: CanaryPlan) -> UUID:
    return uuid5(
        NAMESPACE_URL,
        f"hermes-deals:{plan.plan_id}:{plan.source['manifest_sha256']}",
    )


def _table_counts(db: Session) -> dict[str, int]:
    return {
        name: int(db.scalar(select(func.count()).select_from(model)) or 0)
        for name, model in _MONITORED_MODELS.items()
    }


def _delta(after: dict[str, int], before: dict[str, int]) -> dict[str, int]:
    return {name: after[name] - before[name] for name in _MONITORED_MODELS}


def _required_alembic_head(db: Session, plan: CanaryPlan) -> str:
    value = db.execute(
        text("SELECT version_num FROM alembic_version")
    ).scalar_one()
    expected = str(plan.payload["preflight"]["required_alembic_head"])
    if value != expected:
        raise ValueError(
            "EDEKA canary Alembic head mismatch: "
            f"expected={expected} actual={value}"
        )
    return value


def _authorization(
    plan: CanaryPlan,
    *,
    mode: Literal["apply", "rollback"],
    authorization_path: Path | None,
) -> dict[str, Any]:
    if authorization_path is None:
        raise ValueError(f"EDEKA canary {mode} requires owner authorization JSON")
    payload, _ = _json_object(
        authorization_path,
        label="EDEKA canary owner authorization",
    )
    expected = {
        "schema_version": AUTH_SCHEMA_VERSION,
        "authorization_type": AUTHORIZATION_TYPE,
        "production_apply_authorized": True,
        "authorized_mode": mode,
        "plan_id": plan.plan_id,
        "plan_sha256": plan.sha256,
        "manifest_sha256": plan.source["manifest_sha256"],
        "rollback_backup_verified": True,
    }
    for key, value in expected.items():
        if payload.get(key) != value:
            raise ValueError(f"EDEKA canary authorization {key} mismatch")

    baseline = payload.get("baseline_counts")
    if not isinstance(baseline, dict):
        raise ValueError("EDEKA canary authorization baseline_counts missing")
    _require_exact_keys(
        baseline,
        set(_MONITORED_MODELS),
        label="authorization baseline_counts",
    )
    if any(
        not isinstance(value, int) or value < 0
        for value in baseline.values()
    ):
        raise ValueError(
            "EDEKA canary authorization baseline counts must be non-negative ints"
        )
    return payload


def _clone_selected_offers(
    plan: CanaryPlan,
    evidence: CanaryEvidence,
) -> list[OfferCandidate]:
    snapshot_id = _canary_snapshot_id(plan)
    return [
        offer.model_copy(update={"snapshot_id": snapshot_id})
        for offer in evidence.selected_offers
    ]


def _expected_normalization(
    plan: CanaryPlan,
    candidate: OfferCandidateRecord,
) -> dict[str, Any]:
    source_offer_id = str(candidate.source_offer_id)
    normalized = normalize_offer_fields(
        offer_candidate_id=str(candidate.id),
        source_chain=candidate.source_chain,
        source_store_external_id=candidate.source_store_external_id,
        source_offer_id=source_offer_id,
        product_name_raw=candidate.product_name_raw,
        brand_raw=candidate.brand_raw,
        package_text_raw=candidate.package_text_raw,
        raw_payload=candidate.raw_payload,
        source_image_url=candidate.source_image_url,
    )
    if normalized.package_parse_method is None:
        raise ValueError(
            f"EDEKA canary unexpectedly routes to review: {source_offer_id}"
        )
    plan_row = next(
        row for row in plan.rows if row["source_offer_id"] == source_offer_id
    )
    signature = {
        "item_quantity_value": normalized.package_signature()[0],
        "item_quantity_unit": normalized.package_signature()[1],
        "pack_count": normalized.package_signature()[2],
    }
    if (
        normalized.normalized_name != plan_row["normalized_name"]
        or normalized.normalized_brand != plan_row["normalized_brand"]
        or normalized.package_parse_method != plan_row["package_parse_method"]
        or normalized.package_evidence_source
        != plan_row["package_evidence_source"]
        or signature != plan_row["package_signature"]
    ):
        raise ValueError(
            f"EDEKA canary normalization drift for {source_offer_id}"
        )

    evidence_json = {
        "canary_plan_id": plan.plan_id,
        "source_offer_id": source_offer_id,
        "package_parse_method": normalized.package_parse_method,
        "package_evidence_source": normalized.package_evidence_source,
        "package_evidence_text": normalized.package_evidence_text,
        "gtin_evidence": normalized.gtin_evidence,
    }
    return {
        "offer_candidate_id": candidate.id,
        "normalizer_version": plan.source["normalizer_version"],
        "normalized_name": normalized.normalized_name,
        "normalized_brand": normalized.normalized_brand,
        "item_quantity_value": normalized.item_quantity_value,
        "item_quantity_unit": normalized.item_quantity_unit,
        "pack_count": normalized.pack_count,
        "gtin14": normalized.gtin14,
        "category_key": None,
        "evidence_json": evidence_json,
    }


def _normalization_matches(
    row: OfferNormalization,
    expected: dict[str, Any],
) -> bool:
    fields = (
        "offer_candidate_id",
        "normalizer_version",
        "normalized_name",
        "normalized_brand",
        "item_quantity_value",
        "item_quantity_unit",
        "pack_count",
        "gtin14",
        "category_key",
        "evidence_json",
    )
    for field in fields:
        actual = getattr(row, field)
        wanted = expected[field]
        if field == "item_quantity_value":
            if actual is None or wanted is None:
                if actual is not wanted:
                    return False
            elif Decimal(str(actual)) != Decimal(str(wanted)):
                return False
        elif actual != wanted:
            return False
    return True


def _candidate_rows(
    db: Session,
    snapshot_id: UUID,
) -> list[OfferCandidateRecord]:
    return list(
        db.scalars(
            select(OfferCandidateRecord)
            .where(OfferCandidateRecord.snapshot_id == snapshot_id)
            .order_by(OfferCandidateRecord.source_offer_id.asc())
        ).all()
    )


def _normalization_rows(
    db: Session,
    candidate_ids: list[UUID],
) -> list[OfferNormalization]:
    if not candidate_ids:
        return []
    return list(
        db.scalars(
            select(OfferNormalization)
            .where(OfferNormalization.offer_candidate_id.in_(candidate_ids))
            .order_by(OfferNormalization.offer_candidate_id.asc())
        ).all()
    )


def _assert_no_dependencies(
    db: Session,
    *,
    snapshot_id: UUID,
    candidate_ids: list[UUID],
) -> None:
    if not candidate_ids:
        return

    match_count = int(
        db.scalar(
            select(func.count())
            .select_from(ProductMatchCandidate)
            .where(ProductMatchCandidate.offer_candidate_id.in_(candidate_ids))
        )
        or 0
    )
    link_count = int(
        db.scalar(
            select(func.count())
            .select_from(OfferProductLink)
            .where(OfferProductLink.offer_candidate_id.in_(candidate_ids))
        )
        or 0
    )
    review_items = list(
        db.scalars(
            select(OfferReviewItem).where(
                or_(
                    OfferReviewItem.source_snapshot_id == snapshot_id,
                    OfferReviewItem.published_offer_candidate_id.in_(candidate_ids),
                )
            )
        ).all()
    )
    review_ids = [row.id for row in review_items]
    revision_count = 0
    if review_ids:
        revision_count = int(
            db.scalar(
                select(func.count())
                .select_from(OfferReviewRevision)
                .where(OfferReviewRevision.review_item_id.in_(review_ids))
            )
            or 0
        )

    if any((match_count, link_count, len(review_items), revision_count)):
        raise ValueError(
            "EDEKA canary has unexpected dependent matching/review rows"
        )


def _validate_complete_state(
    db: Session,
    plan: CanaryPlan,
    evidence: CanaryEvidence,
    snapshot: SourceSnapshot,
    candidates: list[OfferCandidateRecord],
    normalizations: list[OfferNormalization],
) -> None:
    expected_snapshot = {
        "id": _canary_snapshot_id(plan),
        "source_chain": "edeka",
        "source_url": EXPECTED_SOURCE_URL,
        "final_url": EXPECTED_SOURCE_URL,
        "scope": EXPECTED_SCOPE,
        "content_type": CANARY_CONTENT_TYPE,
        "content_bytes": len(evidence.raw_html),
        "sha256": plan.source["manifest_sha256"],
        "strategy_hint": CANARY_STRATEGY,
        "success": True,
        "error": None,
    }
    for field, expected in expected_snapshot.items():
        if getattr(snapshot, field) != expected:
            raise ValueError(f"EDEKA canary persisted snapshot {field} mismatch")

    if len(candidates) != 3 or len(normalizations) != 3:
        raise ValueError("EDEKA canary persisted state is partial")

    cloned = _clone_selected_offers(plan, evidence)
    if save_offer_candidates(db, cloned, commit=False) != 0:
        raise ValueError(
            "EDEKA canary replay unexpectedly inserted offer candidates"
        )

    expected_ids = {str(row["source_offer_id"]) for row in plan.rows}
    if {str(row.source_offer_id) for row in candidates} != expected_ids:
        raise ValueError("EDEKA canary persisted source_offer_id set mismatch")

    normalizations_by_candidate = {
        row.offer_candidate_id: row for row in normalizations
    }
    for candidate in candidates:
        expected = _expected_normalization(plan, candidate)
        row = normalizations_by_candidate.get(candidate.id)
        if row is None or not _normalization_matches(row, expected):
            raise ValueError(
                "EDEKA canary persisted normalization mismatch: "
                f"{candidate.source_offer_id}"
            )

    _assert_no_dependencies(
        db,
        snapshot_id=snapshot.id,
        candidate_ids=[row.id for row in candidates],
    )


def _state(
    db: Session,
    plan: CanaryPlan,
    evidence: CanaryEvidence,
) -> tuple[
    str,
    SourceSnapshot | None,
    list[OfferCandidateRecord],
    list[OfferNormalization],
]:
    snapshot_id = _canary_snapshot_id(plan)
    collisions = list(
        db.scalars(
            select(SourceSnapshot).where(
                SourceSnapshot.source_chain == "edeka",
                SourceSnapshot.scope == EXPECTED_SCOPE,
                SourceSnapshot.strategy_hint == CANARY_STRATEGY,
            )
        ).all()
    )
    if any(row.id != snapshot_id for row in collisions):
        raise ValueError("EDEKA canary has conflicting snapshot binding")

    snapshot = db.get(SourceSnapshot, snapshot_id)
    candidates = _candidate_rows(db, snapshot_id)
    normalizations = _normalization_rows(db, [row.id for row in candidates])

    if snapshot is None:
        if candidates or normalizations or collisions:
            raise ValueError("EDEKA canary has partial snapshot state")
        return "empty", None, [], []

    if len(candidates) != 3 or len(normalizations) != 3:
        raise ValueError("EDEKA canary has partial persisted state")

    _validate_complete_state(
        db,
        plan,
        evidence,
        snapshot,
        candidates,
        normalizations,
    )
    return "complete", snapshot, candidates, normalizations


def _build_snapshot(
    plan: CanaryPlan,
    evidence: CanaryEvidence,
) -> SourceSnapshot:
    context = _manifest_context(plan, evidence.manifest)
    return SourceSnapshot(
        id=_canary_snapshot_id(plan),
        source_chain="edeka",
        source_url=EXPECTED_SOURCE_URL,
        final_url=EXPECTED_SOURCE_URL,
        scope=EXPECTED_SCOPE,
        collected_at=context.collected_at,
        http_status=None,
        elapsed_ms=None,
        content_type=CANARY_CONTENT_TYPE,
        content_bytes=len(evidence.raw_html),
        sha256=plan.source["manifest_sha256"],
        snapshot_path=str(evidence.manifest_path),
        keyword_hits={
            "exact_market_binding": 1,
            "canary_offer_count": 3,
            "retained_evidence": 1,
        },
        json_ld_blocks=0,
        strategy_hint=CANARY_STRATEGY,
        success=True,
        error=None,
    )


def _insert_normalizations(
    db: Session,
    plan: CanaryPlan,
    candidates: list[OfferCandidateRecord],
) -> None:
    rows: list[OfferNormalization] = []
    for candidate in candidates:
        expected = _expected_normalization(plan, candidate)
        normalization_id = uuid5(
            NAMESPACE_URL,
            f"hermes-deals:{plan.plan_id}:normalization:{candidate.id}",
        )
        rows.append(OfferNormalization(id=normalization_id, **expected))
    db.add_all(rows)
    db.flush()


def _expected_post_apply_counts(
    baseline: dict[str, int],
    plan: CanaryPlan,
) -> dict[str, int]:
    return {
        name: baseline[name] + int(plan.expected_first_delta[name])
        for name in _MONITORED_MODELS
    }


def execute_prepared_canary(
    db: Session,
    plan: CanaryPlan,
    evidence: CanaryEvidence,
    *,
    mode: Mode,
    authorization_path: Path | None = None,
) -> dict[str, Any]:
    if mode not in {"verify", "apply", "rollback"}:
        raise ValueError(f"Unsupported EDEKA canary mode: {mode}")

    auth: dict[str, Any] | None = None
    if mode in {"apply", "rollback"}:
        auth = _authorization(
            plan,
            mode=mode,
            authorization_path=authorization_path,
        )

    try:
        with db.begin():
            alembic_head = _required_alembic_head(db, plan)
            before = _table_counts(db)
            state, snapshot, candidates, _ = _state(db, plan, evidence)

            if mode == "verify":
                expected_delta = (
                    plan.expected_first_delta
                    if state == "empty"
                    else plan.expected_replay_delta
                )
                return {
                    "result": "pass",
                    "mode": mode,
                    "state": state,
                    "plan_id": plan.plan_id,
                    "plan_sha256": plan.sha256,
                    "manifest_sha256": plan.source["manifest_sha256"],
                    "canary_snapshot_id": str(_canary_snapshot_id(plan)),
                    "alembic_head": alembic_head,
                    "database_counts": before,
                    "expected_next_delta": expected_delta,
                    "writes_performed": False,
                }

            assert auth is not None
            baseline = dict(auth["baseline_counts"])
            expected_post = _expected_post_apply_counts(baseline, plan)

            if mode == "apply":
                if state == "complete":
                    if before != expected_post:
                        raise ValueError(
                            "EDEKA canary replay counts differ from authorized "
                            "post-apply state"
                        )
                    return {
                        "result": "pass",
                        "mode": mode,
                        "state": "replay_noop",
                        "plan_id": plan.plan_id,
                        "plan_sha256": plan.sha256,
                        "manifest_sha256": plan.source["manifest_sha256"],
                        "canary_snapshot_id": str(_canary_snapshot_id(plan)),
                        "alembic_head": alembic_head,
                        "before_counts": before,
                        "after_counts": before,
                        "delta": dict(plan.expected_replay_delta),
                        "writes_performed": False,
                    }

                if before != baseline:
                    raise ValueError(
                        "EDEKA canary database counts differ from authorized baseline"
                    )

                db.add(_build_snapshot(plan, evidence))
                db.flush()
                cloned = _clone_selected_offers(plan, evidence)
                inserted = save_offer_candidates(db, cloned, commit=False)
                if inserted != 3:
                    raise ValueError(
                        f"EDEKA canary expected 3 offer inserts, got {inserted}"
                    )
                candidates = _candidate_rows(db, _canary_snapshot_id(plan))
                if len(candidates) != 3:
                    raise ValueError(
                        "EDEKA canary did not persist exactly three offers"
                    )
                _insert_normalizations(db, plan, candidates)

                after = _table_counts(db)
                actual_delta = _delta(after, before)
                if actual_delta != plan.expected_first_delta:
                    raise ValueError(
                        "EDEKA canary first-apply delta mismatch: "
                        f"expected={plan.expected_first_delta} "
                        f"actual={actual_delta}"
                    )
                state_after, _, _, _ = _state(db, plan, evidence)
                if state_after != "complete":
                    raise ValueError(
                        "EDEKA canary post-apply state is incomplete"
                    )
                return {
                    "result": "pass",
                    "mode": mode,
                    "state": "applied",
                    "plan_id": plan.plan_id,
                    "plan_sha256": plan.sha256,
                    "manifest_sha256": plan.source["manifest_sha256"],
                    "canary_snapshot_id": str(_canary_snapshot_id(plan)),
                    "alembic_head": alembic_head,
                    "before_counts": before,
                    "after_counts": after,
                    "delta": actual_delta,
                    "writes_performed": True,
                }

            if state == "empty":
                if before != baseline:
                    raise ValueError(
                        "EDEKA canary rollback baseline mismatch for already-empty state"
                    )
                return {
                    "result": "pass",
                    "mode": mode,
                    "state": "already_rolled_back",
                    "plan_id": plan.plan_id,
                    "plan_sha256": plan.sha256,
                    "manifest_sha256": plan.source["manifest_sha256"],
                    "canary_snapshot_id": str(_canary_snapshot_id(plan)),
                    "alembic_head": alembic_head,
                    "before_counts": before,
                    "after_counts": before,
                    "writes_performed": False,
                }

            if before != expected_post:
                raise ValueError(
                    "EDEKA canary rollback counts differ from authorized "
                    "post-apply state"
                )
            assert snapshot is not None
            candidate_ids = [row.id for row in candidates]
            _assert_no_dependencies(
                db,
                snapshot_id=snapshot.id,
                candidate_ids=candidate_ids,
            )
            db.execute(
                delete(OfferNormalization).where(
                    OfferNormalization.offer_candidate_id.in_(candidate_ids)
                )
            )
            db.execute(
                delete(OfferCandidateRecord).where(
                    OfferCandidateRecord.id.in_(candidate_ids)
                )
            )
            db.delete(snapshot)
            db.flush()

            after = _table_counts(db)
            if after != baseline:
                raise ValueError(
                    "EDEKA canary rollback did not restore authorized baseline"
                )
            return {
                "result": "pass",
                "mode": mode,
                "state": "rolled_back",
                "plan_id": plan.plan_id,
                "plan_sha256": plan.sha256,
                "manifest_sha256": plan.source["manifest_sha256"],
                "canary_snapshot_id": str(_canary_snapshot_id(plan)),
                "alembic_head": alembic_head,
                "before_counts": before,
                "after_counts": after,
                "delta": _delta(after, before),
                "writes_performed": True,
            }
    except Exception:
        db.rollback()
        raise


def execute_canary(
    db: Session,
    *,
    plan_path: Path,
    manifest_path: Path,
    raw_html_path: Path,
    mode: Mode = "verify",
    authorization_path: Path | None = None,
) -> dict[str, Any]:
    plan = load_plan(plan_path)
    evidence = load_evidence(
        plan,
        manifest_path=manifest_path,
        raw_html_path=raw_html_path,
    )
    return execute_prepared_canary(
        db,
        plan,
        evidence,
        mode=mode,
        authorization_path=authorization_path,
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Verify or execute the exact EDEKA Patzer production canary v01"
        )
    )
    parser.add_argument("--plan", type=Path, required=True)
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--raw-html", type=Path, required=True)
    parser.add_argument(
        "--mode",
        choices=("verify", "apply", "rollback"),
        default="verify",
    )
    parser.add_argument("--authorization", type=Path)
    args = parser.parse_args()

    db = SessionLocal()
    try:
        result = execute_canary(
            db,
            plan_path=args.plan,
            manifest_path=args.manifest,
            raw_html_path=args.raw_html,
            mode=args.mode,
            authorization_path=args.authorization,
        )
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    finally:
        db.close()

    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
