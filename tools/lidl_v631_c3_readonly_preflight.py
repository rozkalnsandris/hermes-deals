#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

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
    execute_with_rollback,
    load_reviewed_receipt,
    load_semantic_row,
    verify_runtime_head,
)
from app.lidl_v631_semantic_persistence import LidlSemanticPersistenceError  # noqa: E402


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Run issue #615 C3 against the exact frozen Lidl canary in a PostgreSQL "
            "REPEATABLE READ, READ ONLY transaction. The transaction is always rolled back."
        )
    )
    parser.add_argument("--expected-head", required=True)
    parser.add_argument(
        "--corpus-root",
        type=Path,
        default=Path("/home/andris/hermes-deals-lidl-corpus"),
    )
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
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        verify_runtime_head(repo_root=REPO_ROOT, expected_head=args.expected_head)
        receipt_raw, receipt = load_reviewed_receipt(args.receipt)
        row = load_semantic_row(args.semantic_row)
        family_dir = args.corpus_root / "flyers" / EXPECTED_FAMILY
        source_binding = derive_frozen_source_binding(
            family_dir=family_dir,
            receipt=receipt,
            receipt_sha256=EXPECTED_RECEIPT_SHA256,
        )
        selected = receipt["selected"]
        row_binding = str(selected["row_binding_sha256"])

        from app.db import SessionLocal

        db = SessionLocal()
        try:
            report = execute_with_rollback(
                db,
                reviewed_receipt_bytes=receipt_raw,
                semantic_rows=[row],
                row_binding_sha256=row_binding,
                source_binding=source_binding,
            )
        finally:
            db.close()
    except (LidlC3ReadonlyPreflightError, LidlSemanticPersistenceError):
        print("BLOCKED_CODE=domain_validation", file=sys.stderr)
        return 30
    except SQLAlchemyError:
        print("BLOCKED_CODE=database_read_error", file=sys.stderr)
        return 30
    except Exception:
        print("BLOCKED_CODE=unexpected_internal_error", file=sys.stderr)
        return 30

    print(json.dumps(report, ensure_ascii=False, sort_keys=True))
    print("RESULT=C3_READ_ONLY_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
