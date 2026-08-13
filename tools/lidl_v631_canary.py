#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import func, select, text
from sqlalchemy.exc import SQLAlchemyError

REPO_ROOT = Path(__file__).resolve().parents[1]
BACKEND = REPO_ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.lidl_v631_c3_readonly_preflight import (  # noqa: E402
    EXPECTED_FAMILY,
    EXPECTED_RECEIPT_SHA256,
    LidlC3ReadonlyPreflightError,
    derive_frozen_source_binding,
    load_reviewed_receipt,
    load_semantic_row,
    verify_runtime_head,
)
from app.lidl_v631_semantic_persistence import (  # noqa: E402
    LidlSemanticPersistenceError,
    apply_lidl_v631_semantic_persistence_plan,
    build_lidl_v631_semantic_persistence_plan,
)
from app.models import OfferCandidateRecord, SourceSnapshot  # noqa: E402

ROW_BINDING_SHA256 = "fbe1cc5767b6eae416393d0f701e839ab7b2edf557cee9ac3f257a9b9612d2fe"
PLAN_SCHEMA_VERSION = 1
PLAN_DECISION = "approve_lidl_v631_one_row_canary_apply"
PLAN_SCOPE = "exact_one_row_production_db_canary"
APPLY_PERMISSIONS = {
    "production_database_write": True,
    "max_source_snapshot_writes": 1,
    "max_offer_candidate_writes": 1,
    "review_write": False,
    "production_publish": False,
    "production_deploy": False,
    "corpus_write": False,
    "source_replacement": False,
    "systemd_change": False,
    "scheduler_change": False,
}


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Reusable Lidl V6.3.1 one-row canary PLAN/APPLY tool")
    parser.add_argument("mode", choices=("plan", "apply"))
    parser.add_argument("--expected-head", required=True)
    parser.add_argument("--corpus-root", type=Path, default=Path("/home/andris/hermes-deals-lidl-corpus"))
    parser.add_argument(
        "--receipt",
        type=Path,
        default=REPO_ROOT / "backend/tests/fixtures/lidl/issue_615_reviewed_canary_landliebe.json",
    )
    parser.add_argument(
        "--semantic-row",
        type=Path,
        default=REPO_ROOT / "backend/tests/fixtures/lidl/issue_620_full_semantic_row_landliebe.json.b64",
    )
    parser.add_argument("--authorization", type=Path)
    return parser


def _load_inputs(args: argparse.Namespace) -> tuple[bytes, dict[str, Any], dict[str, Any]]:
    verify_runtime_head(repo_root=REPO_ROOT, expected_head=args.expected_head)
    receipt_raw, receipt = load_reviewed_receipt(args.receipt)
    row = load_semantic_row(args.semantic_row)
    family_dir = args.corpus_root / "flyers" / EXPECTED_FAMILY
    source_binding = derive_frozen_source_binding(
        family_dir=family_dir,
        receipt=receipt,
        receipt_sha256=EXPECTED_RECEIPT_SHA256,
    )
    return receipt_raw, row, source_binding


def _counts(db: Any) -> dict[str, int]:
    return {
        "source_snapshots": int(db.scalar(select(func.count()).select_from(SourceSnapshot)) or 0),
        "offer_candidates": int(db.scalar(select(func.count()).select_from(OfferCandidateRecord)) or 0),
    }


def _authorization(plan: dict[str, Any]) -> dict[str, Any]:
    return {
        "schema_version": PLAN_SCHEMA_VERSION,
        "decision": PLAN_DECISION,
        "scope": PLAN_SCOPE,
        "payload_fingerprint": plan["payload_fingerprint"],
        "plan_fingerprint": plan["plan_fingerprint"],
        "reviewed_canary_receipt_sha256": plan["bindings"]["reviewed_canary_receipt_sha256"],
        "semantic_row_key": plan["bindings"]["semantic_row_key"],
        "source_offer_id": plan["offer_candidate"]["source_offer_id"],
        "permissions": dict(APPLY_PERMISSIONS),
    }


def run_plan(db: Any, *, receipt_raw: bytes, row: dict[str, Any], source_binding: dict[str, Any]) -> dict[str, Any]:
    db.execute(text("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY"))
    read_only = str(db.execute(text("SHOW transaction_read_only")).scalar_one()).casefold()
    isolation = str(db.execute(text("SHOW transaction_isolation")).scalar_one()).casefold()
    if read_only != "on" or isolation != "repeatable read":
        raise LidlC3ReadonlyPreflightError("PLAN transaction is not PostgreSQL repeatable-read/read-only")

    before = _counts(db)
    try:
        plan = build_lidl_v631_semantic_persistence_plan(
            db=db,
            reviewed_receipt_bytes=receipt_raw,
            semantic_rows=[row],
            row_binding_sha256=ROW_BINDING_SHA256,
            source_binding=source_binding,
        )
        after = _counts(db)
    finally:
        db.rollback()

    if before != after:
        raise LidlC3ReadonlyPreflightError("PLAN changed production row counts")
    if plan["result"] not in {"READY_TO_CREATE", "NO_OP_IDENTICAL"}:
        raise LidlC3ReadonlyPreflightError("PLAN is blocked by a persistence conflict")
    if plan["expected_deltas"].get("replay") != {"source_snapshots": 0, "offer_candidates": 0}:
        raise LidlC3ReadonlyPreflightError("PLAN replay delta is not zero")

    return {
        "schema_version": 1,
        "result": "PLAN_PASS",
        "plan_result": plan["result"],
        "transaction_read_only": read_only,
        "transaction_isolation": isolation,
        "baseline": before,
        "expected_first_apply_delta": plan["expected_deltas"]["first_apply"],
        "source_snapshot_id": plan["source_snapshot"]["id"],
        "offer_candidate_id": plan["offer_candidate"]["id"],
        "source_offer_id": plan["offer_candidate"]["source_offer_id"],
        "plan_fingerprint": plan["plan_fingerprint"],
        "payload_fingerprint": plan["payload_fingerprint"],
        "authorization": _authorization(plan),
        "production_database_write": False,
        "review_write": False,
        "corpus_write": False,
        "production_publish": False,
        "production_deploy": False,
        "source_replacement": False,
        "systemd_change": False,
        "scheduler_change": False,
    }


def _load_authorization(path: Path | None) -> dict[str, Any]:
    if path is None:
        raise LidlSemanticPersistenceError("APPLY requires --authorization")
    if not path.is_file() or path.is_symlink():
        raise LidlSemanticPersistenceError("authorization file is missing or unsafe")
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, dict):
        raise LidlSemanticPersistenceError("authorization root must be an object")
    return payload


def run_apply(
    db: Any,
    *,
    receipt_raw: bytes,
    row: dict[str, Any],
    source_binding: dict[str, Any],
    authorization: dict[str, Any],
) -> dict[str, Any]:
    before = _counts(db)
    result = apply_lidl_v631_semantic_persistence_plan(
        db=db,
        reviewed_receipt_bytes=receipt_raw,
        semantic_rows=[row],
        row_binding_sha256=ROW_BINDING_SHA256,
        source_binding=source_binding,
        authorization=authorization,
    )
    after = _counts(db)

    source_writes = int(result.get("source_snapshot_writes", 0))
    offer_writes = int(result.get("offer_candidate_writes", 0))
    if source_writes not in {0, 1} or offer_writes not in {0, 1}:
        raise LidlSemanticPersistenceError("APPLY write count exceeded one-row scope")
    if after["source_snapshots"] - before["source_snapshots"] != source_writes:
        raise LidlSemanticPersistenceError("APPLY SourceSnapshot delta mismatch")
    if after["offer_candidates"] - before["offer_candidates"] != offer_writes:
        raise LidlSemanticPersistenceError("APPLY OfferCandidate delta mismatch")
    if int(result.get("replay_writes", 0)) != 0:
        raise LidlSemanticPersistenceError("APPLY replay wrote rows")
    if result["result"] == "APPLY_PASS" and result.get("post_apply_result") != "NO_OP_IDENTICAL":
        raise LidlSemanticPersistenceError("APPLY post-write replay is not identical")
    if result["result"] not in {"APPLY_PASS", "APPLY_NO_OP_IDENTICAL"}:
        raise LidlSemanticPersistenceError("APPLY returned unexpected result")

    return {
        "schema_version": 1,
        "result": "APPLY_PASS" if result["result"] == "APPLY_PASS" else "APPLY_NO_OP_IDENTICAL",
        "source_snapshot_writes": source_writes,
        "offer_candidate_writes": offer_writes,
        "replay_writes": 0,
        "post_apply_result": result.get("post_apply_result", "NO_OP_IDENTICAL"),
        "baseline_before": before,
        "baseline_after": after,
        "plan_fingerprint": result["authorized_plan_fingerprint"],
        "payload_fingerprint": result["payload_fingerprint"],
        "production_database_write": source_writes + offer_writes > 0,
        "review_write": False,
        "corpus_write": False,
        "production_publish": False,
        "production_deploy": False,
        "source_replacement": False,
        "systemd_change": False,
        "scheduler_change": False,
        "done": True,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        receipt_raw, row, source_binding = _load_inputs(args)
        from app.db import SessionLocal

        db = SessionLocal()
        try:
            if args.mode == "plan":
                report = run_plan(db, receipt_raw=receipt_raw, row=row, source_binding=source_binding)
            else:
                report = run_apply(
                    db,
                    receipt_raw=receipt_raw,
                    row=row,
                    source_binding=source_binding,
                    authorization=_load_authorization(args.authorization),
                )
        finally:
            db.close()
    except (LidlC3ReadonlyPreflightError, LidlSemanticPersistenceError, SQLAlchemyError, OSError, ValueError, json.JSONDecodeError):
        print("RESULT=BLOCKED", file=sys.stderr)
        return 30

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    print(f"RESULT={report['result']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
