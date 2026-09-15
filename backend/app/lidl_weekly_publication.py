from __future__ import annotations

import csv
from datetime import UTC, date, datetime
from decimal import Decimal
import hashlib
import json
from pathlib import Path
from typing import Any, Mapping, Sequence
from uuid import UUID

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.lidl_corpus_import import (
    SOURCE_STRATEGY,
    _snapshot_identity,
    _snapshot_scope,
    build_offer,
    load_context,
    register_source_snapshot,
)
from app.models import OfferCandidateRecord, SourceSnapshot
from app.offer_store import save_offer_candidates
from app.schemas import OfferCandidate


CONTRACT_VERSION = "lidl-weekly-safe-partition-publication-v1"
APPLY_DECISION = "approve_lidl_weekly_safe_partition_apply"
APPLY_SCOPE = "exact_lidl_weekly_safe_partition"
SEMANTIC_VIEW_VERSION = "lidl-weekly-semantic-view-v1"
TRUST_STATE_STRATEGY = "lidl_weekly_trust_state_v1"
TRUST_RECEIPT_STRATEGY = "lidl_weekly_trust_receipt_v1"
SEMANTIC_GATE_VERSION = "lidl-weekly-semantics-v1"
SEMANTIC_FILES = (
    "accepted-physical.tsv",
    "coverage-report.json",
    "excluded.tsv",
    "profile-binding.json",
    "review-required.tsv",
    "semantic-rows.json",
)
_DECIMAL_FIELDS = {
    "price_eur",
    "regular_price_eur",
    "unit_price_eur",
    "regular_unit_price_eur",
    "example_weight_g",
    "app_price_eur",
}
_PLAN_SAFETY_FALSE = {
    "database_write": False,
    "family_visible_offer_write": False,
    "review_write": False,
    "auto_approve": False,
    "corpus_write": False,
    "source_replacement": False,
    "production_deploy": False,
    "systemd_change": False,
    "scheduler_change": False,
}


class LidlWeeklyPublicationError(ValueError):
    pass


def canonical_json_bytes(value: Any) -> bytes:
    def convert(raw: Any) -> Any:
        if isinstance(raw, UUID):
            return str(raw)
        if isinstance(raw, Decimal):
            return format(raw, "f")
        if isinstance(raw, (date, datetime)):
            return raw.isoformat()
        if isinstance(raw, Mapping):
            return {
                str(key): convert(item)
                for key, item in sorted(raw.items(), key=lambda pair: str(pair[0]))
            }
        if isinstance(raw, (list, tuple)):
            return [convert(item) for item in raw]
        return raw

    return (
        json.dumps(
            convert(value),
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _sha_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _sha_file(path: Path, label: str) -> str:
    if path.is_symlink() or not path.is_file():
        raise LidlWeeklyPublicationError(f"{label} must be a regular file")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise LidlWeeklyPublicationError(f"{label} must be a regular file")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise LidlWeeklyPublicationError(f"invalid {label}") from exc
    if not isinstance(value, dict):
        raise LidlWeeklyPublicationError(f"{label} must contain an object")
    return value


def _safe_component(value: Any, label: str) -> str:
    text = str(value or "")
    if not text or Path(text).name != text or text in {".", ".."}:
        raise LidlWeeklyPublicationError(f"unsafe or missing {label}")
    return text


def _read_tsv(path: Path) -> list[dict[str, str]]:
    if path.is_symlink() or not path.is_file():
        raise LidlWeeklyPublicationError("accepted physical partition is unavailable")
    with path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle, delimiter="\t"))


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=UTC) if value.tzinfo is None else value.astimezone(UTC)


def _same_datetime(left: Any, right: Any) -> bool:
    return (
        left == right
        or (
            isinstance(left, datetime)
            and isinstance(right, datetime)
            and _utc(left) == _utc(right)
        )
    )


def _semantic_manifest(semantic_dir: Path) -> tuple[str, dict[str, str]]:
    if semantic_dir.is_symlink() or not semantic_dir.is_dir():
        raise LidlWeeklyPublicationError("semantic evidence directory is unavailable")
    expected = set(SEMANTIC_FILES) | {"manifest.json"}
    actual = {entry.name for entry in semantic_dir.iterdir()}
    if actual != expected:
        raise LidlWeeklyPublicationError(
            "semantic evidence file set mismatch: "
            f"missing={sorted(expected - actual)} extra={sorted(actual - expected)}"
        )

    entries: list[dict[str, Any]] = []
    hashes: dict[str, str] = {}
    for name in sorted(SEMANTIC_FILES):
        path = semantic_dir / name
        raw = path.read_bytes()
        digest = _sha_file(path, f"semantic {name}")
        hashes[name] = digest
        entries.append({"path": name, "sha256": digest, "bytes": len(raw)})
    expected_raw = canonical_json_bytes(
        {
            "schema_version": 1,
            "semantic_gate_version": SEMANTIC_GATE_VERSION,
            "entries": entries,
        }
    )
    if (semantic_dir / "manifest.json").read_bytes() != expected_raw:
        raise LidlWeeklyPublicationError("semantic manifest does not bind evidence files")
    return _sha_bytes(expected_raw), hashes


def _validate_cycle(cycle_dir: Path) -> dict[str, Any]:
    if cycle_dir.is_symlink() or not cycle_dir.is_dir():
        raise LidlWeeklyPublicationError("cycle directory is unavailable")
    summary = _load_json(cycle_dir / "cycle-summary.json", "cycle summary")
    runtime = _load_json(cycle_dir / "runtime-receipt.json", "runtime receipt")
    state_path = cycle_dir / "trust-state.json"
    state = _load_json(state_path, "trust state")
    receipt_path = cycle_dir / "trust-receipt.json"
    receipt = _load_json(receipt_path, "trust receipt")

    if summary.get("result") != "COMPLETE" or runtime.get("result") != "COMPLETE":
        raise LidlWeeklyPublicationError("cycle is not COMPLETE")
    if runtime.get("exit_code") != 0 or runtime.get("trigger_event") != "schedule":
        raise LidlWeeklyPublicationError("runtime receipt is not a successful schedule")
    if state.get("strategy") != TRUST_STATE_STRATEGY or state.get("trigger_event") != "schedule":
        raise LidlWeeklyPublicationError("trust state is not scheduled Lidl evidence")
    if receipt.get("strategy") != TRUST_RECEIPT_STRATEGY:
        raise LidlWeeklyPublicationError("trust receipt strategy mismatch")
    state_sha = _sha_file(state_path, "trust state")
    if receipt.get("state_sha256") != state_sha:
        raise LidlWeeklyPublicationError("trust receipt does not bind trust state")

    safety = (
        (
            summary,
            (
                "corpus_write_authorized",
                "database_write_authorized",
                "review_write_authorized",
                "production_publish_authorized",
                "deployment_authorized",
                "systemd_change_authorized",
            ),
        ),
        (
            runtime,
            (
                "production_write_authorized",
                "database_write_authorized",
                "review_write_authorized",
                "publication_authorized",
                "deployment_authorized",
                "systemd_change_authorized",
            ),
        ),
        (
            state,
            (
                "production_write_authorized",
                "database_write_performed",
                "review_write_performed",
                "publication_performed",
                "deployment_performed",
                "systemd_change_performed",
            ),
        ),
    )
    for payload, keys in safety:
        for key in keys:
            if payload.get(key) is not False:
                raise LidlWeeklyPublicationError(f"cycle safety mismatch: {key}")

    one_shot = _load_json(
        cycle_dir / "controller" / "one-shot" / "one-shot-status.json",
        "one-shot status",
    )
    if one_shot.get("result") != "READY" or one_shot.get("dry_run") is not True:
        raise LidlWeeklyPublicationError("one-shot evidence is not READY dry-run evidence")
    for key in (
        "corpus_write",
        "db_write",
        "review_seed",
        "auto_approve",
        "auto_publish",
        "systemd_change",
    ):
        if one_shot.get(key) is not False:
            raise LidlWeeklyPublicationError(f"one-shot safety mismatch: {key}")

    return {
        "state": state,
        "state_sha256": state_sha,
        "receipt_sha256": _sha_file(receipt_path, "trust receipt"),
        "one_shot": one_shot,
    }


def _snapshot_expected(
    context: Any,
    *,
    raw_root: Path,
    db_raw_prefix: str,
    content_bytes: int,
) -> dict[str, Any]:
    filename = f"flyer-{context.raw_sha256}.json"
    return {
        "id": _snapshot_identity(context.raw_sha256),
        "source_chain": "lidl",
        "source_url": context.api_url,
        "final_url": context.api_url,
        "scope": _snapshot_scope(context),
        "collected_at": context.collected_at,
        "http_status": 200,
        "elapsed_ms": None,
        "content_type": "application/json",
        "content_bytes": content_bytes,
        "sha256": context.raw_sha256,
        "snapshot_path": f"{db_raw_prefix.rstrip('/')}/lidl/{filename}",
        "keyword_hits": {},
        "json_ld_blocks": 0,
        "strategy_hint": SOURCE_STRATEGY,
        "success": True,
        "error": None,
    }


def _snapshot_matches(row: SourceSnapshot, expected: Mapping[str, Any]) -> bool:
    for key, value in expected.items():
        actual = getattr(row, key)
        if key == "collected_at":
            if not _same_datetime(actual, value):
                return False
        elif actual != value:
            return False
    return True


def _offer_payload(offer: OfferCandidate) -> dict[str, Any]:
    payload = offer.model_dump(mode="python")
    payload["source_chain"] = offer.source_chain.value
    payload["source_url"] = str(offer.source_url)
    payload["source_image_url"] = (
        str(offer.source_image_url) if offer.source_image_url else None
    )
    return payload


def _offer_matches(row: OfferCandidateRecord, expected: Mapping[str, Any]) -> bool:
    for key, right in expected.items():
        left = getattr(row, key)
        if key in _DECIMAL_FIELDS:
            if (left is None) != (right is None):
                return False
            if left is not None and Decimal(str(left)) != Decimal(str(right)):
                return False
        elif key == "collected_at":
            if not _same_datetime(left, right):
                return False
        elif left != right:
            return False
    return True


def _snapshot_action(
    db: Session,
    expected: dict[str, Any],
) -> tuple[str, UUID, list[str]]:
    deterministic_id = UUID(str(expected["id"]))
    same_sha = list(
        db.scalars(
            select(SourceSnapshot).where(
                SourceSnapshot.source_chain == "lidl",
                SourceSnapshot.sha256 == expected["sha256"],
                SourceSnapshot.strategy_hint == SOURCE_STRATEGY,
            )
        ).all()
    )
    if len(same_sha) > 1:
        return (
            "CONFLICT",
            deterministic_id,
            ["multiple_source_snapshots_share_raw_sha256"],
        )
    row = db.get(SourceSnapshot, deterministic_id)
    if row is None and same_sha:
        row = same_sha[0]
    if row is None:
        return "CREATE", deterministic_id, []
    candidate = dict(expected)
    candidate["id"] = row.id
    if not _snapshot_matches(row, candidate):
        return "CONFLICT", row.id, ["source_snapshot_payload_conflict"]
    return "NO_OP_IDENTICAL", row.id, []


def _offer_action(
    db: Session,
    snapshot_id: UUID,
    expected: Sequence[tuple[str, dict[str, Any]]],
) -> tuple[str, list[str]]:
    rows = list(
        db.scalars(
            select(OfferCandidateRecord)
            .where(OfferCandidateRecord.snapshot_id == snapshot_id)
            .order_by(OfferCandidateRecord.source_offer_id.asc())
        ).all()
    )
    if not rows:
        return "CREATE", []
    expected_by_id = {source_id: payload for source_id, payload in expected}
    actual_by_id = {str(row.source_offer_id): row for row in rows}
    if len(actual_by_id) != len(rows) or set(actual_by_id) != set(expected_by_id):
        return "CONFLICT", ["snapshot_offer_identity_set_conflict"]
    for source_id, payload in expected_by_id.items():
        if not _offer_matches(actual_by_id[source_id], payload):
            return "CONFLICT", [f"snapshot_offer_payload_conflict:{source_id}"]
    return "NO_OP_IDENTICAL", []


def _raw_action(raw_root: Path, raw_sha256: str) -> tuple[str, list[str]]:
    canonical = raw_root / "lidl" / f"flyer-{raw_sha256}.json"
    if not canonical.exists() and not canonical.is_symlink():
        return "CREATE", []
    if canonical.is_symlink() or not canonical.is_file():
        return "CONFLICT", ["canonical_raw_snapshot_path_unsafe"]
    if _sha_file(canonical, "canonical raw snapshot") != raw_sha256:
        return "CONFLICT", ["canonical_raw_snapshot_hash_conflict"]
    return "NO_OP_IDENTICAL", []


def _required_permissions(plan: Mapping[str, Any]) -> dict[str, Any]:
    delta = plan["expected_deltas"]["first_apply"]
    return {
        "production_database_write": True,
        "source_snapshot_db_write": True,
        "offer_candidate_db_write": True,
        "canonical_raw_snapshot_write": True,
        "family_visible_offer_write": True,
        "max_source_snapshot_writes": int(delta["source_snapshots"]),
        "max_offer_candidate_writes": int(delta["offer_candidates"]),
        "max_canonical_raw_snapshot_writes": int(delta["canonical_raw_snapshots"]),
        "review_write": False,
        "auto_approve": False,
        "corpus_write": False,
        "source_replacement": False,
        "production_deploy": False,
        "systemd_change": False,
        "scheduler_change": False,
    }


def build_lidl_weekly_publication_plan(
    *,
    db: Session,
    cycle_dir: Path,
    corpus_root: Path,
    raw_root: Path,
    db_raw_prefix: str = "/data/raw",
) -> dict[str, Any]:
    cycle = _validate_cycle(cycle_dir)
    match = cycle["one_shot"].get("corpus_match")
    if not isinstance(match, Mapping):
        raise LidlWeeklyPublicationError("one-shot corpus_match is missing")
    flyer_key = _safe_component(match.get("flyer_key"), "flyer_key")
    scan = _safe_component(match.get("scan"), "scan")
    flyer_dir = corpus_root / "flyers" / flyer_key
    scan_dir = flyer_dir / "scans" / scan
    if (
        flyer_dir.is_symlink()
        or not flyer_dir.is_dir()
        or scan_dir.is_symlink()
        or not scan_dir.is_dir()
    ):
        raise LidlWeeklyPublicationError("bound immutable corpus flyer/scan is unavailable")

    raw_sha = str(match.get("source_raw_sha256") or "")
    pdf_sha = str(match.get("source_pdf_sha256") or "")
    context = load_context(
        flyer_dir=flyer_dir,
        scan_name=scan,
        expected_raw_sha256=raw_sha,
        expected_pdf_sha256=pdf_sha,
    )
    semantic_dir = cycle_dir / "semantic"
    semantic_manifest_sha, semantic_hashes = _semantic_manifest(semantic_dir)
    coverage = _load_json(semantic_dir / "coverage-report.json", "coverage report")
    binding = _load_json(semantic_dir / "profile-binding.json", "profile binding")
    if (
        coverage.get("view_version") != SEMANTIC_VIEW_VERSION
        or binding.get("view_version") != SEMANTIC_VIEW_VERSION
    ):
        raise LidlWeeklyPublicationError("semantic view version mismatch")
    if int(coverage.get("unexplained_count") or 0) != 0:
        raise LidlWeeklyPublicationError("semantic evidence contains unexplained rows")
    for key in (
        "database_write",
        "review_seed",
        "auto_approve",
        "auto_publish",
        "production_deploy",
    ):
        if coverage.get(key) is not False:
            raise LidlWeeklyPublicationError(f"semantic coverage safety mismatch: {key}")

    expected_binding = {
        "flyer_key": flyer_key,
        "scan": scan,
        "parser_version": context.parser_version,
        "parser_sha256": context.parser_sha256,
        "source_pdf_sha256": context.pdf_sha256,
        "source_raw_sha256": context.raw_sha256,
    }
    for key, value in expected_binding.items():
        if (
            str(coverage.get(key) or "") != value
            or str(binding.get(key) or "") != value
        ):
            raise LidlWeeklyPublicationError(f"semantic binding mismatch: {key}")

    rows = _read_tsv(semantic_dir / "accepted-physical.tsv")
    if len(rows) != int(coverage.get("production_ready_count") or -1):
        raise LidlWeeklyPublicationError("production-ready partition count mismatch")
    if not rows:
        raise LidlWeeklyPublicationError("production-ready partition is empty")

    expected_snapshot = _snapshot_expected(
        context,
        raw_root=raw_root,
        db_raw_prefix=db_raw_prefix,
        content_bytes=(flyer_dir / "source.json").stat().st_size,
    )
    snapshot_action, snapshot_id, snapshot_conflicts = _snapshot_action(
        db,
        expected_snapshot,
    )
    expected_snapshot["id"] = snapshot_id
    transient_snapshot = SourceSnapshot(**expected_snapshot)
    offers = [
        build_offer(
            row=row,
            ordinal=ordinal,
            context=context,
            snapshot=transient_snapshot,
        )
        for ordinal, row in enumerate(rows, start=1)
    ]
    offer_pairs = sorted(
        (str(offer.source_offer_id), _offer_payload(offer))
        for offer in offers
    )
    offer_action, offer_conflicts = _offer_action(db, snapshot_id, offer_pairs)
    raw_action, raw_conflicts = _raw_action(raw_root, context.raw_sha256)
    conflicts = sorted(set(snapshot_conflicts + offer_conflicts + raw_conflicts))
    if conflicts:
        result = "BLOCKED_CONFLICT"
    elif snapshot_action == offer_action == raw_action == "NO_OP_IDENTICAL":
        result = "NO_OP_IDENTICAL"
    else:
        result = "READY_TO_CREATE"

    evidence = {
        "cycle_identity_sha256": str(
            cycle["state"].get("current_cycle_identity_sha256") or ""
        ),
        "trust_state_sha256": cycle["state_sha256"],
        "trust_receipt_sha256": cycle["receipt_sha256"],
        "flyer_key": flyer_key,
        "scan": scan,
        "source_raw_sha256": context.raw_sha256,
        "source_pdf_sha256": context.pdf_sha256,
        "parser_version": context.parser_version,
        "parser_sha256": context.parser_sha256,
        "semantic_manifest_sha256": semantic_manifest_sha,
        "accepted_physical_sha256": semantic_hashes["accepted-physical.tsv"],
        "coverage_report_sha256": semantic_hashes["coverage-report.json"],
        "profile_binding_sha256": semantic_hashes["profile-binding.json"],
        "valid_from": context.valid_from.isoformat(),
        "valid_until": context.valid_until.isoformat(),
        "region": context.region,
        "safe_count": len(offers),
    }
    offer_material = [
        {"source_offer_id": source_id, "payload": payload}
        for source_id, payload in offer_pairs
    ]
    payload_material = {
        "contract_version": CONTRACT_VERSION,
        "evidence": evidence,
        "source_snapshot": expected_snapshot,
        "canonical_raw_snapshot": {
            "path": str(
                raw_root / "lidl" / f"flyer-{context.raw_sha256}.json"
            ),
            "sha256": context.raw_sha256,
        },
        "offer_candidates": offer_material,
    }
    first_apply = {
        "source_snapshots": int(snapshot_action == "CREATE" and not conflicts),
        "offer_candidates": (
            len(offers) if offer_action == "CREATE" and not conflicts else 0
        ),
        "canonical_raw_snapshots": int(raw_action == "CREATE" and not conflicts),
    }
    plan: dict[str, Any] = {
        "schema_version": 1,
        **payload_material,
        "payload_fingerprint": _sha_bytes(canonical_json_bytes(payload_material)),
        "result": result,
        "source_snapshot_action": snapshot_action,
        "offer_candidate_action": offer_action,
        "canonical_raw_snapshot_action": raw_action,
        "conflicts": conflicts,
        "expected_deltas": {
            "first_apply": first_apply,
            "replay": {
                "source_snapshots": 0,
                "offer_candidates": 0,
                "canonical_raw_snapshots": 0,
            },
        },
        **_PLAN_SAFETY_FALSE,
    }
    plan["required_apply_permissions"] = _required_permissions(plan)
    plan["plan_fingerprint"] = _sha_bytes(canonical_json_bytes(plan))
    return plan


def _authorize_apply(
    authorization: Mapping[str, Any],
    plan: Mapping[str, Any],
) -> None:
    if authorization.get("schema_version") != 1:
        raise LidlWeeklyPublicationError("apply authorization schema mismatch")
    if (
        authorization.get("decision") != APPLY_DECISION
        or authorization.get("scope") != APPLY_SCOPE
    ):
        raise LidlWeeklyPublicationError("apply authorization decision/scope mismatch")
    if plan.get("result") not in {"READY_TO_CREATE", "NO_OP_IDENTICAL"}:
        raise LidlWeeklyPublicationError("apply authorization cannot target blocked plan")
    expected = {
        "plan_fingerprint": plan["plan_fingerprint"],
        "payload_fingerprint": plan["payload_fingerprint"],
        "cycle_identity_sha256": plan["evidence"]["cycle_identity_sha256"],
        "trust_state_sha256": plan["evidence"]["trust_state_sha256"],
        "semantic_manifest_sha256": plan["evidence"]["semantic_manifest_sha256"],
        "safe_count": plan["evidence"]["safe_count"],
    }
    for key, value in expected.items():
        if authorization.get(key) != value:
            raise LidlWeeklyPublicationError(
                f"apply authorization binding mismatch: {key}"
            )
    if authorization.get("permissions") != plan.get("required_apply_permissions"):
        raise LidlWeeklyPublicationError("apply authorization permissions mismatch")


def apply_lidl_weekly_publication_plan(
    *,
    db: Session,
    cycle_dir: Path,
    corpus_root: Path,
    raw_root: Path,
    db_raw_prefix: str,
    authorization: Mapping[str, Any],
) -> dict[str, Any]:
    if db.in_transaction():
        raise LidlWeeklyPublicationError(
            "weekly publication apply requires a fresh database transaction"
        )
    pre = build_lidl_weekly_publication_plan(
        db=db,
        cycle_dir=cycle_dir,
        corpus_root=corpus_root,
        raw_root=raw_root,
        db_raw_prefix=db_raw_prefix,
    )
    _authorize_apply(authorization, pre)
    if pre["result"] == "NO_OP_IDENTICAL":
        db.rollback()
        return {
            "schema_version": 1,
            "result": "APPLY_NO_OP_IDENTICAL",
            "authorized_plan_fingerprint": pre["plan_fingerprint"],
            "payload_fingerprint": pre["payload_fingerprint"],
            "source_snapshot_writes": 0,
            "offer_candidate_writes": 0,
            "canonical_raw_snapshot_writes": 0,
            "family_visible_offer_writes": 0,
            "replay_writes": 0,
        }

    # The read-only planner opens SQLAlchemy's autobegin transaction. End only
    # that planner transaction before starting the separately authorized write.
    db.rollback()
    match = _validate_cycle(cycle_dir)["one_shot"]["corpus_match"]
    flyer_key = _safe_component(match.get("flyer_key"), "flyer_key")
    scan = _safe_component(match.get("scan"), "scan")
    flyer_dir = corpus_root / "flyers" / flyer_key
    semantic_rows = _read_tsv(
        cycle_dir / "semantic" / "accepted-physical.tsv"
    )
    raw_sha = str(match.get("source_raw_sha256") or "")
    pdf_sha = str(match.get("source_pdf_sha256") or "")
    raw_path = raw_root / "lidl" / f"flyer-{raw_sha}.json"
    raw_existed = raw_path.exists()
    snapshot_writes = 0
    offer_writes = 0
    try:
        with db.begin():
            snapshot_id = UUID(str(pre["source_snapshot"]["id"]))
            snapshot_writes = int(db.get(SourceSnapshot, snapshot_id) is None)
            snapshot = register_source_snapshot(
                db,
                flyer_dir=flyer_dir,
                scan_name=scan,
                raw_root=raw_root,
                db_raw_prefix=db_raw_prefix,
                expected_raw_sha256=raw_sha,
                expected_pdf_sha256=pdf_sha,
                commit=False,
            )
            context = load_context(
                flyer_dir=flyer_dir,
                scan_name=scan,
                expected_raw_sha256=raw_sha,
                expected_pdf_sha256=pdf_sha,
            )
            offers = [
                build_offer(
                    row=row,
                    ordinal=ordinal,
                    context=context,
                    snapshot=snapshot,
                )
                for ordinal, row in enumerate(semantic_rows, start=1)
            ]
            offer_writes = save_offer_candidates(db, offers, commit=False)
            post = build_lidl_weekly_publication_plan(
                db=db,
                cycle_dir=cycle_dir,
                corpus_root=corpus_root,
                raw_root=raw_root,
                db_raw_prefix=db_raw_prefix,
            )
            if post["result"] != "NO_OP_IDENTICAL":
                raise LidlWeeklyPublicationError(
                    "post-apply replay is not NO_OP_IDENTICAL"
                )
    except Exception:
        db.rollback()
        raise

    return {
        "schema_version": 1,
        "result": "APPLY_PASS",
        "authorized_plan_fingerprint": pre["plan_fingerprint"],
        "payload_fingerprint": pre["payload_fingerprint"],
        "source_snapshot_writes": snapshot_writes,
        "offer_candidate_writes": offer_writes,
        "canonical_raw_snapshot_writes": int(
            not raw_existed and raw_path.exists()
        ),
        "family_visible_offer_writes": offer_writes,
        "replay_writes": 0,
        "post_apply_result": "NO_OP_IDENTICAL",
    }
