#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Mapping

import lidl_source_refresh_r3_apply as base


APPLY_VERSION = "lidl-source-refresh-r3-promotion-apply-v2-retry"
AUTHORIZATION_VERSION = "lidl-source-refresh-r3-promotion-authorization-v2-retry"
AUTHORIZATION_DECISION = "approve_exact_r3_promotion_retry"
RETIRED_AUTHORIZATION_COMMENT_ID = 5227260615


def _validate_retry_authorization(path: Path) -> dict[str, Any]:
    auth = base._load_object(path, "R3 retry promotion authorization")
    expected_fields = {
        "schema_version",
        "authorization_version",
        "decision",
        "approved_by",
        "approved_at",
        "authorization_comment_id",
        "plan_fingerprint",
        "r2_artifact_id",
        "r2_artifact_digest",
        "r3_plan_artifact_id",
        "r3_plan_artifact_digest",
        "permissions",
    }
    if set(auth) != expected_fields:
        raise base.R3ApplyError("R3 retry authorization field set mismatch")
    if auth.get("schema_version") != 1:
        raise base.R3ApplyError("R3 retry authorization schema mismatch")
    if auth.get("authorization_version") != AUTHORIZATION_VERSION:
        raise base.R3ApplyError("R3 retry authorization version mismatch")
    if auth.get("decision") != AUTHORIZATION_DECISION:
        raise base.R3ApplyError("R3 retry authorization decision mismatch")
    if auth.get("approved_by") != base.EXPECTED_APPROVED_BY:
        raise base.R3ApplyError("R3 retry authorization approver mismatch")
    approved_at = str(auth.get("approved_at") or "")
    try:
        parsed = datetime.fromisoformat(approved_at.replace("Z", "+00:00"))
    except ValueError as exc:
        raise base.R3ApplyError("R3 retry authorization timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise base.R3ApplyError("R3 retry authorization timestamp must be timezone-aware")
    comment_id = auth.get("authorization_comment_id")
    if not isinstance(comment_id, int) or isinstance(comment_id, bool) or comment_id <= 0:
        raise base.R3ApplyError("R3 retry authorization comment ID is invalid")
    if comment_id == RETIRED_AUTHORIZATION_COMMENT_ID:
        raise base.R3ApplyError("R3 retry cannot reuse retired authorization comment")
    if auth.get("plan_fingerprint") != base.EXPECTED_PLAN_FINGERPRINT:
        raise base.R3ApplyError("R3 retry authorization fingerprint mismatch")
    if auth.get("r2_artifact_id") != base.EXPECTED_R2_ARTIFACT_ID:
        raise base.R3ApplyError("R3 retry authorization R2 artifact ID mismatch")
    if auth.get("r2_artifact_digest") != base.EXPECTED_R2_ARTIFACT_DIGEST:
        raise base.R3ApplyError("R3 retry authorization R2 artifact digest mismatch")
    if auth.get("r3_plan_artifact_id") != base.EXPECTED_R3_PLAN_ARTIFACT_ID:
        raise base.R3ApplyError("R3 retry authorization plan artifact ID mismatch")
    if auth.get("r3_plan_artifact_digest") != base.EXPECTED_R3_PLAN_ARTIFACT_DIGEST:
        raise base.R3ApplyError("R3 retry authorization plan artifact digest mismatch")
    expected_permissions = {
        "corpus_write": True,
        "scan_promotion": True,
        "source_review_promotion": True,
        "authority_promotion": True,
        "profile_promotion": False,
        "database_write": False,
        "review_write": False,
        "auto_approve": False,
        "auto_publish": False,
        "production_deploy": False,
        "systemd_change": False,
        "automatic_retry": False,
        "gate_c_d": False,
        "b15m2_v08": False,
    }
    if auth.get("permissions") != expected_permissions:
        raise base.R3ApplyError("R3 retry authorization permissions mismatch")
    return auth


def apply_exact_promotion_retry(
    *,
    corpus_root: Path,
    r2_zip: Path,
    r3_plan_zip: Path,
    authorization_file: Path,
) -> dict[str, Any]:
    auth = _validate_retry_authorization(authorization_file)
    comment_id = int(auth["authorization_comment_id"])

    original_validator = base._validate_authorization
    original_comment_id = base.EXPECTED_AUTHORIZATION_COMMENT_ID
    original_apply_version = base.APPLY_VERSION

    try:
        base._validate_authorization = _validate_retry_authorization
        base.EXPECTED_AUTHORIZATION_COMMENT_ID = comment_id
        base.APPLY_VERSION = APPLY_VERSION
        result = base.apply_exact_promotion(
            corpus_root=corpus_root,
            r2_zip=r2_zip,
            r3_plan_zip=r3_plan_zip,
            authorization_file=authorization_file,
        )
    finally:
        base._validate_authorization = original_validator
        base.EXPECTED_AUTHORIZATION_COMMENT_ID = original_comment_id
        base.APPLY_VERSION = original_apply_version

    if result.get("authorization_comment_id") != comment_id:
        raise base.R3ApplyError("R3 retry result authorization binding mismatch")
    if result.get("apply_version") != APPLY_VERSION:
        raise base.R3ApplyError("R3 retry apply version binding mismatch")
    return result


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Apply the exact fresh-owner-authorized Lidl rev05 R3 promotion retry"
    )
    parser.add_argument("--corpus-root", type=Path, required=True)
    parser.add_argument("--r2-artifact-zip", type=Path, required=True)
    parser.add_argument("--r3-plan-artifact-zip", type=Path, required=True)
    parser.add_argument("--authorization", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        if args.output.exists() or args.output.is_symlink():
            raise base.R3ApplyError("output path already exists")
        result = apply_exact_promotion_retry(
            corpus_root=args.corpus_root,
            r2_zip=args.r2_artifact_zip,
            r3_plan_zip=args.r3_plan_artifact_zip,
            authorization_file=args.authorization,
        )
        base._write_exclusive(args.output, base._canonical_bytes(result))
    except Exception as exc:
        print(f"R3_PROMOTION_RETRY_BLOCKED: {type(exc).__name__}: {exc}", file=__import__("sys").stderr)
        return 30
    print(json.dumps(result, sort_keys=True))
    print("RESULT=R3_PROMOTION_PASS")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
