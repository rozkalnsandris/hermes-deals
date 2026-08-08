#!/usr/bin/env python3
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "tools"))

import lidl_source_refresh_audit as r1  # noqa: E402


AUTHORITY_VERSION = "lidl-source-refresh-authority-v1"
AUTHORITY_DECISION = "accept_reviewed_parser_input_refresh"
AUTHORITY_SCOPE = "gate_a_authoritative_scan_only"
AUTHORITY_ROOT_NAME = "source-refresh"
AUTHORITY_FILE_NAME = "authority.json"
SOURCE_REVIEW_FILE_NAME = "source-review.json"


class SourceRefreshAuthorityError(RuntimeError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _require_sha(value: Any, label: str) -> str:
    text = str(value or "")
    if re.fullmatch(r"[0-9a-f]{64}", text) is None:
        raise SourceRefreshAuthorityError(f"{label} must be a lowercase SHA-256")
    return text


def _load_object(path: Path, label: str, *, max_bytes: int = 128 * 1024) -> dict[str, Any]:
    if not path.is_file() or path.is_symlink():
        raise SourceRefreshAuthorityError(f"{label} is missing or unsafe")
    if path.stat().st_size > max_bytes:
        raise SourceRefreshAuthorityError(f"{label} exceeds size limit")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceRefreshAuthorityError(f"{label} is invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise SourceRefreshAuthorityError(f"{label} must contain an object")
    return dict(payload)


def _tree_manifest(root: Path) -> list[dict[str, Any]]:
    if not root.is_dir() or root.is_symlink():
        raise SourceRefreshAuthorityError("authoritative refresh scan is missing or unsafe")
    rows: list[dict[str, Any]] = []
    for path in sorted(root.rglob("*")):
        if path.is_symlink():
            raise SourceRefreshAuthorityError("authoritative refresh scan contains a symlink")
        if path.is_dir():
            continue
        if not path.is_file():
            raise SourceRefreshAuthorityError("authoritative refresh scan contains an unsupported entry")
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return rows


def _scan_tree_digest(rows: list[dict[str, Any]]) -> str:
    content = "\n".join(
        f"{row['path']}|{row['bytes']}|{row['sha256']}" for row in rows
    ) + "\n"
    return sha256(content.encode("utf-8")).hexdigest()


def _expected_reference_input(frozen_source_json: bytes) -> dict[str, Any]:
    return {
        "parser_input_identity_sha256": r1.parser_input_identity(frozen_source_json),
        "product_binding_sha256": r1.product_binding_digest(frozen_source_json),
        "product_binding_count": len(r1.product_bindings(frozen_source_json)),
    }


def _expected_live_input(live_source_json: bytes) -> dict[str, Any]:
    return {
        "parser_input_identity_sha256": r1.parser_input_identity(live_source_json),
        "product_binding_sha256": r1.product_binding_digest(live_source_json),
        "product_binding_count": len(r1.product_bindings(live_source_json)),
        "product_link_count": r1.product_link_count(live_source_json),
    }


def _validate_source_review(
    review: Mapping[str, Any],
    *,
    flyer_key: str,
    pdf_sha256: str,
    reference_input: Mapping[str, Any],
    live_input: Mapping[str, Any],
    observed_changes: Mapping[str, int],
) -> None:
    expected_fields = {
        "schema_version",
        "decision",
        "scope",
        "approved_by",
        "approved_at",
        "note",
        "flyer_key",
        "pdf_sha256",
        "reference_input",
        "approved_live_input",
        "observed_changes",
        "permissions",
    }
    if set(review) != expected_fields:
        raise SourceRefreshAuthorityError("source-review field set mismatch")
    if review.get("schema_version") != 1:
        raise SourceRefreshAuthorityError("source-review schema mismatch")
    if review.get("decision") != "approve_parser_input_refresh":
        raise SourceRefreshAuthorityError("source-review decision mismatch")
    if review.get("scope") != "authoritative_staging_scan_only":
        raise SourceRefreshAuthorityError("source-review scope mismatch")
    if review.get("flyer_key") != flyer_key or review.get("pdf_sha256") != pdf_sha256:
        raise SourceRefreshAuthorityError("source-review flyer/PDF binding mismatch")
    expected_reference = {
        "parser_input_identity_sha256": reference_input["parser_input_identity_sha256"],
        "product_binding_sha256": reference_input["product_binding_sha256"],
        "product_binding_count": reference_input["product_binding_count"],
    }
    if review.get("reference_input") != expected_reference:
        raise SourceRefreshAuthorityError("source-review reference input mismatch")
    expected_live = {
        "parser_input_identity_sha256": live_input["parser_input_identity_sha256"],
        "product_binding_sha256": live_input["product_binding_sha256"],
        "product_binding_count": live_input["product_binding_count"],
    }
    if review.get("approved_live_input") != expected_live:
        raise SourceRefreshAuthorityError("source-review approved live input mismatch")
    if review.get("observed_changes") != dict(observed_changes):
        raise SourceRefreshAuthorityError("source-review observed changes mismatch")
    if review.get("permissions") != {
        "staging_scan": True,
        "corpus_write": False,
        "db_write": False,
        "review_seed": False,
        "auto_approve": False,
        "auto_publish": False,
        "systemd_change": False,
    }:
        raise SourceRefreshAuthorityError("source-review permissions are unsafe")
    if not str(review.get("approved_by") or "").strip():
        raise SourceRefreshAuthorityError("source-review approver is missing")
    if not str(review.get("approved_at") or "").strip():
        raise SourceRefreshAuthorityError("source-review timestamp is missing")
    if not str(review.get("note") or "").strip():
        raise SourceRefreshAuthorityError("source-review note is missing")


def validate_authoritative_refresh(
    *,
    flyer_dir: Path,
    live_source_json: bytes,
    live_pdf_sha256: str,
    parser_version: str,
    parser_sha256: str,
) -> dict[str, Any] | None:
    """Validate a promoted same-PDF parser-input refresh for Gate A.

    Returns None when the current live parser-input has no promoted authority.
    Raises on any partial, malformed, stale, or unsafe authority evidence.
    Raw source SHA is intentionally provenance-only; semantic acceptance is bound
    to PDF + stable identity + parser-input + product-binding identities.
    """
    flyer_dir = flyer_dir.resolve()
    if not flyer_dir.is_dir() or flyer_dir.is_symlink():
        raise SourceRefreshAuthorityError("flyer directory is missing or unsafe")

    source_pdf = flyer_dir / "source.pdf"
    source_json = flyer_dir / "source.json"
    if not source_pdf.is_file() or source_pdf.is_symlink():
        raise SourceRefreshAuthorityError("immutable source PDF is missing or unsafe")
    if not source_json.is_file() or source_json.is_symlink():
        raise SourceRefreshAuthorityError("immutable source JSON is missing or unsafe")
    if _sha256_file(source_pdf) != live_pdf_sha256:
        raise SourceRefreshAuthorityError("immutable source PDF does not match live PDF")

    frozen_source_json = source_json.read_bytes()
    live_stable_sha = r1._canonical_digest(r1.stable_source_identity(live_source_json))
    frozen_stable_sha = r1._canonical_digest(r1.stable_source_identity(frozen_source_json))
    if frozen_stable_sha != live_stable_sha:
        raise SourceRefreshAuthorityError("immutable/live stable source identity mismatch")

    reference_input = _expected_reference_input(frozen_source_json)
    live_input = _expected_live_input(live_source_json)
    observed_changes = r1.binding_change_summary(frozen_source_json, live_source_json)
    live_parser_input_sha = live_input["parser_input_identity_sha256"]

    authority_root = flyer_dir / AUTHORITY_ROOT_NAME
    if not authority_root.exists():
        return None
    if not authority_root.is_dir() or authority_root.is_symlink():
        raise SourceRefreshAuthorityError("source-refresh authority root is unsafe")

    authority_dir = authority_root / live_parser_input_sha
    if not authority_dir.exists():
        return None
    if not authority_dir.is_dir() or authority_dir.is_symlink():
        raise SourceRefreshAuthorityError("source-refresh authority directory is unsafe")

    authority_path = authority_dir / AUTHORITY_FILE_NAME
    authority = _load_object(authority_path, "source-refresh authority")
    expected_fields = {
        "schema_version",
        "authority_version",
        "decision",
        "scope",
        "flyer_key",
        "pdf_sha256",
        "stable_source_identity_sha256",
        "reference_input",
        "approved_live_input",
        "observed_changes",
        "source_review",
        "parser",
        "scan",
        "promotion",
        "permissions",
    }
    if set(authority) != expected_fields:
        raise SourceRefreshAuthorityError("source-refresh authority field set mismatch")
    if authority.get("schema_version") != 1:
        raise SourceRefreshAuthorityError("source-refresh authority schema mismatch")
    if authority.get("authority_version") != AUTHORITY_VERSION:
        raise SourceRefreshAuthorityError("source-refresh authority version mismatch")
    if authority.get("decision") != AUTHORITY_DECISION:
        raise SourceRefreshAuthorityError("source-refresh authority decision mismatch")
    if authority.get("scope") != AUTHORITY_SCOPE:
        raise SourceRefreshAuthorityError("source-refresh authority scope mismatch")
    if authority.get("flyer_key") != flyer_dir.name:
        raise SourceRefreshAuthorityError("source-refresh authority flyer mismatch")
    if authority.get("pdf_sha256") != live_pdf_sha256:
        raise SourceRefreshAuthorityError("source-refresh authority PDF mismatch")
    if authority.get("stable_source_identity_sha256") != live_stable_sha:
        raise SourceRefreshAuthorityError("source-refresh authority stable identity mismatch")
    if authority.get("reference_input") != reference_input:
        raise SourceRefreshAuthorityError("source-refresh authority reference input mismatch")
    if authority.get("approved_live_input") != live_input:
        raise SourceRefreshAuthorityError("source-refresh authority approved live input mismatch")
    if authority.get("observed_changes") != observed_changes:
        raise SourceRefreshAuthorityError("source-refresh authority observed changes mismatch")

    permissions = authority.get("permissions")
    if permissions != {
        "gate_a_refresh_acceptance": True,
        "source_pdf_replace": False,
        "source_json_replace": False,
        "db_write": False,
        "review_write": False,
        "auto_approve": False,
        "auto_publish": False,
        "production_deploy": False,
        "systemd_change": False,
    }:
        raise SourceRefreshAuthorityError("source-refresh authority permissions are unsafe")

    parser = authority.get("parser")
    if parser != {"version": parser_version, "sha256": parser_sha256}:
        raise SourceRefreshAuthorityError("source-refresh authority parser mismatch")

    source_review_meta = authority.get("source_review")
    if not isinstance(source_review_meta, Mapping):
        raise SourceRefreshAuthorityError("source-refresh authority source-review binding missing")
    if set(source_review_meta) != {"sha256"}:
        raise SourceRefreshAuthorityError("source-refresh authority source-review fields mismatch")
    review_sha = _require_sha(source_review_meta.get("sha256"), "source-review SHA")
    review_path = authority_dir / SOURCE_REVIEW_FILE_NAME
    if _sha256_file(review_path) != review_sha:
        raise SourceRefreshAuthorityError("source-review SHA mismatch")
    review = _load_object(review_path, "source-review")
    _validate_source_review(
        review,
        flyer_key=flyer_dir.name,
        pdf_sha256=live_pdf_sha256,
        reference_input=reference_input,
        live_input=live_input,
        observed_changes=observed_changes,
    )

    scan = authority.get("scan")
    if not isinstance(scan, Mapping):
        raise SourceRefreshAuthorityError("source-refresh authority scan binding missing")
    if set(scan) != {"name", "tree_sha256", "scan_time_raw_sha256"}:
        raise SourceRefreshAuthorityError("source-refresh authority scan fields mismatch")
    scan_name = str(scan.get("name") or "")
    if re.fullmatch(r"scan-v631-[0-9a-f]{12}", scan_name) is None:
        raise SourceRefreshAuthorityError("source-refresh authority scan name is invalid")
    tree_sha = _require_sha(scan.get("tree_sha256"), "scan tree SHA")
    scan_time_raw_sha = _require_sha(scan.get("scan_time_raw_sha256"), "scan-time raw SHA")
    scan_root = flyer_dir / "scans" / scan_name
    manifest = _tree_manifest(scan_root)
    if _scan_tree_digest(manifest) != tree_sha:
        raise SourceRefreshAuthorityError("authoritative refresh scan tree mismatch")

    summary = _load_object(scan_root / "summary.json", "authoritative refresh scan summary")
    if summary.get("flyer_key") != flyer_dir.name:
        raise SourceRefreshAuthorityError("authoritative refresh scan flyer mismatch")
    if summary.get("scan") != scan_name:
        raise SourceRefreshAuthorityError("authoritative refresh scan name mismatch")
    if summary.get("parser_version") != parser_version:
        raise SourceRefreshAuthorityError("authoritative refresh scan parser version mismatch")
    if summary.get("parser_sha256") != parser_sha256:
        raise SourceRefreshAuthorityError("authoritative refresh scan parser SHA mismatch")
    scan_source = summary.get("source")
    if not isinstance(scan_source, Mapping):
        raise SourceRefreshAuthorityError("authoritative refresh scan source binding missing")
    if scan_source.get("pdf_sha256") != live_pdf_sha256:
        raise SourceRefreshAuthorityError("authoritative refresh scan PDF mismatch")
    if scan_source.get("raw_sha256") != scan_time_raw_sha:
        raise SourceRefreshAuthorityError("authoritative refresh scan raw provenance mismatch")

    promotion = authority.get("promotion")
    if not isinstance(promotion, Mapping):
        raise SourceRefreshAuthorityError("source-refresh authority promotion binding missing")
    if set(promotion) != {
        "approved_by",
        "approved_at",
        "authorization_comment_id",
        "r2_artifact_id",
        "r2_artifact_digest",
    }:
        raise SourceRefreshAuthorityError("source-refresh authority promotion fields mismatch")
    if not str(promotion.get("approved_by") or "").strip():
        raise SourceRefreshAuthorityError("source-refresh promotion approver is missing")
    if not str(promotion.get("approved_at") or "").strip():
        raise SourceRefreshAuthorityError("source-refresh promotion timestamp is missing")
    if isinstance(promotion.get("authorization_comment_id"), bool) or not isinstance(
        promotion.get("authorization_comment_id"), int
    ) or int(promotion["authorization_comment_id"]) <= 0:
        raise SourceRefreshAuthorityError("source-refresh promotion authorization ID is invalid")
    if isinstance(promotion.get("r2_artifact_id"), bool) or not isinstance(
        promotion.get("r2_artifact_id"), int
    ) or int(promotion["r2_artifact_id"]) <= 0:
        raise SourceRefreshAuthorityError("source-refresh promotion artifact ID is invalid")
    _require_sha(promotion.get("r2_artifact_digest"), "R2 artifact digest")

    return {
        "authority_version": AUTHORITY_VERSION,
        "authority_sha256": _sha256_file(authority_path),
        "parser_input_identity_sha256": live_parser_input_sha,
        "product_binding_sha256": live_input["product_binding_sha256"],
        "product_binding_count": live_input["product_binding_count"],
        "product_link_count": live_input["product_link_count"],
        "scan_name": scan_name,
        "scan_tree_sha256": tree_sha,
        "scan_time_raw_sha256": scan_time_raw_sha,
        "current_live_raw_sha256": _sha256_bytes(live_source_json),
        "raw_sha_is_provenance_only": True,
        "source_review_sha256": review_sha,
    }
