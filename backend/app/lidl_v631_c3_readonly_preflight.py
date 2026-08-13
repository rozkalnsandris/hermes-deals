from __future__ import annotations

from datetime import datetime
import hashlib
import json
from pathlib import Path
import re
import subprocess
from typing import Any, Mapping, Sequence
from uuid import UUID

from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.lidl_v631_semantic_persistence import build_lidl_v631_semantic_persistence_plan
from app.models import OfferCandidateRecord, SourceSnapshot


CONTRACT_VERSION = "lidl-v631-c3-readonly-preflight-v1"
EXPECTED_FAMILY = "aktionsprospekt-10-08-2026-15-08-2026-71933b"
EXPECTED_RECEIPT_SHA256 = "b5670a4cd6cb2fe9c7d31ef3dd1a330e67f636d6a2912a42a00aad89469bb5c9"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")


class LidlC3ReadonlyPreflightError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise LidlC3ReadonlyPreflightError(message)


def _sha256_bytes(raw: bytes) -> str:
    return hashlib.sha256(raw).hexdigest()


def _regular_file(path: Path, *, label: str) -> Path:
    _require(path.is_file() and not path.is_symlink(), f"{label} is missing or unsafe: {path}")
    return path


def _load_json_bytes(raw: bytes, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(raw.decode("utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise LidlC3ReadonlyPreflightError(f"{label} is invalid JSON") from exc
    _require(isinstance(payload, dict), f"{label} root must be an object")
    return payload


def _iso_datetime(value: Any, *, label: str) -> str:
    raw = str(value or "").strip()
    _require(bool(raw), f"{label} is missing")
    try:
        parsed = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError as exc:
        raise LidlC3ReadonlyPreflightError(f"{label} is not an ISO datetime") from exc
    _require(parsed.tzinfo is not None, f"{label} must include a timezone")
    return parsed.isoformat()


def _collected_at(source: Mapping[str, Any], meta: Mapping[str, Any]) -> str:
    candidates: list[str] = []
    for key in ("source_collected_at", "collected_at", "captured_at"):
        if meta.get(key):
            candidates.append(_iso_datetime(meta[key], label=f"discovery metadata {key}"))
    if source.get("dateTime"):
        candidates.append(_iso_datetime(source["dateTime"], label="source JSON dateTime"))
    _require(bool(candidates), "frozen source collection timestamp is unavailable")
    instants = {datetime.fromisoformat(value).timestamp() for value in candidates}
    _require(len(instants) == 1, "frozen source collection timestamp evidence conflicts")
    return candidates[0]


def load_reviewed_receipt(path: Path) -> tuple[bytes, dict[str, Any]]:
    raw = _regular_file(path, label="reviewed canary receipt").read_bytes()
    _require(_sha256_bytes(raw) == EXPECTED_RECEIPT_SHA256, "reviewed canary receipt SHA-256 mismatch")
    receipt = _load_json_bytes(raw, label="reviewed canary receipt")
    _require(receipt.get("family") == EXPECTED_FAMILY, "reviewed canary family mismatch")
    selected = receipt.get("selected")
    _require(isinstance(selected, dict), "reviewed canary selected row is missing")
    return raw, receipt


def load_semantic_row(path: Path) -> dict[str, Any]:
    import base64

    encoded = _regular_file(path, label="reviewed semantic row").read_bytes()
    if encoded.endswith(b"\n"):
        encoded = encoded[:-1]
    try:
        raw = base64.b64decode(encoded, validate=True)
    except ValueError as exc:
        raise LidlC3ReadonlyPreflightError("reviewed semantic row Base64 is invalid") from exc
    row = _load_json_bytes(raw, label="reviewed semantic row")
    return row


def derive_frozen_source_binding(
    *,
    family_dir: Path,
    receipt: Mapping[str, Any],
    receipt_sha256: str,
) -> dict[str, Any]:
    _require(bool(SHA256_RE.fullmatch(receipt_sha256)), "reviewed receipt SHA-256 is invalid")
    _require(family_dir.name == receipt.get("family"), "frozen family directory name mismatch")
    _require(family_dir.is_dir() and not family_dir.is_symlink(), "frozen family directory is missing or unsafe")
    family_dir = family_dir.resolve()

    source_json_path = _regular_file(family_dir / "source.json", label="frozen source JSON")
    source_pdf_path = _regular_file(family_dir / "source.pdf", label="frozen source PDF")
    meta_path = _regular_file(family_dir / "discovery-meta.json", label="frozen discovery metadata")
    source_json_raw = source_json_path.read_bytes()
    source_pdf_raw = source_pdf_path.read_bytes()
    source = _load_json_bytes(source_json_raw, label="frozen source JSON")
    meta = _load_json_bytes(meta_path.read_bytes(), label="frozen discovery metadata")

    raw_sha = _sha256_bytes(source_json_raw)
    pdf_sha = _sha256_bytes(source_pdf_raw)
    _require(raw_sha == receipt.get("source_raw_sha256"), "frozen source JSON SHA-256 mismatch")
    _require(pdf_sha == receipt.get("source_pdf_sha256"), "frozen source PDF SHA-256 mismatch")

    optional_meta_checks = {
        "raw_sha256": raw_sha,
        "pdf_sha256": pdf_sha,
        "raw_bytes": len(source_json_raw),
        "pdf_bytes": len(source_pdf_raw),
        "valid_from": receipt.get("valid_from"),
        "valid_until": receipt.get("valid_until"),
    }
    for key, expected in optional_meta_checks.items():
        if key in meta:
            actual = int(meta[key]) if key.endswith("_bytes") else meta[key]
            _require(actual == expected, f"frozen discovery metadata mismatch: {key}")

    source_url = str(meta.get("source_url") or "").strip()
    if not source_url:
        source_url = (
            "https://endpoints.leaflets.schwarz/v4/flyer?flyer_identifier="
            + str(receipt["family"])
        )
    _require(source_url.startswith("https://"), "frozen source URL must be HTTPS")

    binding = {
        "schema_version": 1,
        "family": receipt["family"],
        "source_pdf_sha256": receipt["source_pdf_sha256"],
        "source_raw_sha256": receipt["source_raw_sha256"],
        "scan_tree_sha256": receipt["scan_tree_sha256"],
        "review_profile_sha256": receipt["review_profile_sha256"],
        "semantic_tree_sha256": receipt["semantic_tree_sha256"],
        "semantic_manifest_sha256": receipt["semantic_manifest_sha256"],
        "semantic_rows_sha256": receipt["semantic_rows_sha256"],
        "valid_from": receipt["valid_from"],
        "valid_until": receipt["valid_until"],
        "reviewed_canary_receipt_sha256": receipt_sha256,
        "source_url": source_url,
        "source_collected_at": _collected_at(source, meta),
        "source_content_bytes": len(source_json_raw),
        "snapshot_path": str(source_json_path.resolve()),
    }
    final_url = str(meta.get("final_url") or "").strip()
    if final_url:
        _require(final_url.startswith("https://"), "frozen final URL must be HTTPS")
        binding["final_url"] = final_url
    return binding


def verify_runtime_head(*, repo_root: Path, expected_head: str) -> None:
    _require(bool(COMMIT_RE.fullmatch(expected_head)), "expected HEAD must be a lowercase commit SHA")
    repo_root = repo_root.resolve()
    commands = (
        (["git", "-C", str(repo_root), "rev-parse", "HEAD"], expected_head),
        (["git", "-C", str(repo_root), "diff", "--quiet", "--"], None),
        (["git", "-C", str(repo_root), "diff", "--cached", "--quiet", "--"], None),
    )
    for command, expected_output in commands:
        completed = subprocess.run(command, capture_output=True, text=True, check=False)
        _require(completed.returncode == 0, "runtime git state is not exact/clean")
        if expected_output is not None:
            _require(completed.stdout.strip() == expected_output, "runtime HEAD differs from authorized SHA")


def enforce_postgres_read_only(db: Session) -> dict[str, str]:
    bind = db.get_bind()
    dialect = str(getattr(getattr(bind, "dialect", None), "name", ""))
    _require(dialect == "postgresql", "C3 production preflight requires PostgreSQL")
    db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    read_only = str(db.execute(text("SHOW transaction_read_only")).scalar_one()).casefold()
    isolation = str(db.execute(text("SHOW transaction_isolation")).scalar_one()).casefold()
    _require(read_only == "on", "PostgreSQL transaction_read_only is not on")
    _require(isolation == "repeatable read", "PostgreSQL transaction isolation is not repeatable read")
    return {"transaction_read_only": read_only, "transaction_isolation": isolation}


def _counts(db: Session) -> dict[str, int]:
    return {
        "source_snapshots": int(db.scalar(select(func.count()).select_from(SourceSnapshot)) or 0),
        "offer_candidates": int(db.scalar(select(func.count()).select_from(OfferCandidateRecord)) or 0),
    }


def _exact_counts(db: Session, plan: Mapping[str, Any]) -> dict[str, int]:
    snapshot_id = UUID(str(plan["source_snapshot"]["id"]))
    source_offer_id = str(plan["offer_candidate"]["source_offer_id"])
    raw_sha = str(plan["bindings"]["source_raw_sha256"])
    return {
        "snapshot_id": int(db.scalar(select(func.count()).select_from(SourceSnapshot).where(SourceSnapshot.id == snapshot_id)) or 0),
        "snapshot_raw_sha256": int(db.scalar(select(func.count()).select_from(SourceSnapshot).where(SourceSnapshot.source_chain == "lidl", SourceSnapshot.sha256 == raw_sha)) or 0),
        "offer_uniqueness_key": int(db.scalar(select(func.count()).select_from(OfferCandidateRecord).where(OfferCandidateRecord.snapshot_id == snapshot_id, OfferCandidateRecord.source_offer_id == source_offer_id)) or 0),
    }


def validate_readonly_baseline(
    *,
    plan: Mapping[str, Any],
    before: Mapping[str, int],
    after: Mapping[str, int],
    exact: Mapping[str, int],
) -> None:
    _require(dict(before) == dict(after), "production DB row counts changed during C3 transaction")
    _require(plan.get("result") == "READY_TO_CREATE", "C3 expected a new one-row canary plan")
    _require(plan.get("source_snapshot_action") == "CREATE", "C3 snapshot action is not CREATE")
    _require(plan.get("offer_candidate_action") == "CREATE", "C3 offer action is not CREATE")
    _require(plan.get("conflicts") == [], "C3 persistence plan has conflicts")
    _require(plan.get("expected_deltas", {}).get("first_apply") == {"source_snapshots": 1, "offer_candidates": 1}, "C3 first-apply delta is not exactly 1/1")
    _require(all(int(value) == 0 for value in exact.values()), "C3 exact production key already exists")
    for flag in (
        "database_write", "review_write", "production_publish", "production_deploy",
        "corpus_write", "source_replacement", "systemd_change", "scheduler_change",
    ):
        _require(plan.get(flag) is False, f"C3 plan safety mismatch: {flag}")


def run_readonly_preflight(
    *,
    db: Session,
    reviewed_receipt_bytes: bytes,
    semantic_rows: Sequence[Mapping[str, Any]],
    row_binding_sha256: str,
    source_binding: Mapping[str, Any],
) -> dict[str, Any]:
    transaction = enforce_postgres_read_only(db)
    before = _counts(db)
    plan = build_lidl_v631_semantic_persistence_plan(
        db=db,
        reviewed_receipt_bytes=reviewed_receipt_bytes,
        semantic_rows=semantic_rows,
        row_binding_sha256=row_binding_sha256,
        source_binding=source_binding,
    )
    exact = _exact_counts(db, plan)
    after = _counts(db)
    validate_readonly_baseline(plan=plan, before=before, after=after, exact=exact)
    return {
        "schema_version": 1,
        "contract_version": CONTRACT_VERSION,
        "result": "C3_READ_ONLY_PASS",
        "transaction": transaction,
        "production_baseline_before": before,
        "production_baseline_after": after,
        "exact_key_counts": exact,
        "plan_result": plan["result"],
        "plan_fingerprint": plan["plan_fingerprint"],
        "payload_fingerprint": plan["payload_fingerprint"],
        "bindings": plan["bindings"],
        "source_snapshot_id": plan["source_snapshot"]["id"],
        "source_offer_id": plan["offer_candidate"]["source_offer_id"],
        "expected_first_apply_delta": plan["expected_deltas"]["first_apply"],
        "database_write": False,
        "review_write": False,
        "production_publish": False,
        "production_deploy": False,
        "corpus_write": False,
        "source_replacement": False,
        "systemd_change": False,
        "scheduler_change": False,
        "rollback_only": True,
    }


def execute_with_rollback(db: Session, **kwargs: Any) -> dict[str, Any]:
    report: dict[str, Any] | None = None
    try:
        report = run_readonly_preflight(db=db, **kwargs)
    finally:
        db.rollback()
    _require(report is not None, "C3 read-only report was not produced")
    report["transaction_rolled_back"] = True
    return report
