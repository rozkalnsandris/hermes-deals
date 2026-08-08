#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Mapping
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "lidl_parser_provenance"))

import lidl_source_refresh_audit as r1  # noqa: E402
import lidl_weekly_staging as staging  # noqa: E402
from lidl_gate_b_family_scan import build_scan  # noqa: E402
from lidl_parser_provenance.lidl_v631_runtime import (  # noqa: E402
    PARSER_VERSION,
    SHADOW_SHA256,
)

R2_VERSION = "lidl-source-refresh-r2-staging-scan-v2-semantic-identity"
APPROVED_BY = "Andris Rožkalns"
EXPECTED_AS_OF = "2026-08-08"
EXPECTED_LIVE_PARSER_INPUT_SHA256 = (
    "e6ebe5669551a2d455e7b2c036746e08e3bdd20e8e0562fab6972ab97e2a88e8"
)
EXPECTED_PRODUCT_BINDING_SHA256 = (
    "12ebbb79bb7bfd46e603e766d357549bf4fb381e6afe4dfdcfeaa1844d6ac6dd"
)
EXPECTED_PRODUCT_BINDING_COUNT = 140
EXPECTED_PRODUCT_LINK_COUNT = 141
EXPECTED_CHANGES = {
    "binding_added": 0,
    "binding_removed": 0,
    "binding_title_changed": 0,
}
EXPECTED_REFERENCE_INPUT = {
    "parser_input_identity_sha256": r1.EXPECTED_FROZEN_PARSER_INPUT_SHA256,
    "product_binding_sha256": EXPECTED_PRODUCT_BINDING_SHA256,
    "product_binding_count": EXPECTED_PRODUCT_BINDING_COUNT,
}
EXPECTED_LIVE_INPUT = {
    "parser_input_identity_sha256": EXPECTED_LIVE_PARSER_INPUT_SHA256,
    "product_binding_sha256": EXPECTED_PRODUCT_BINDING_SHA256,
    "product_binding_count": EXPECTED_PRODUCT_BINDING_COUNT,
}
SAFETY = {
    "staging_scan": True,
    "authoritative_corpus_write": False,
    "source_review_promotion": False,
    "database_write": False,
    "review_write": False,
    "auto_approve": False,
    "auto_publish": False,
    "production_deploy": False,
    "systemd_change": False,
    "automatic_retry": False,
    "gate_c_d_authorized": False,
    "b15m2_v08_authorized": False,
}


class R2ScanError(RuntimeError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _write_json(path: Path, payload: Mapping[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )


def fetch_exact_live_source() -> tuple[bytes, bytes]:
    query = urlencode(
        {
            "version": "4",
            "flyer_identifier": r1.EXPECTED_FLYER_IDENTIFIER,
            "client": "lidl",
            "region_id": r1.EXPECTED_ROUTE_REGION,
        }
    )
    request = Request(
        f"{r1.FLYER_API_URL}?{query}",
        headers={
            "User-Agent": "HermesDeals-LidlR2StagingScan/2.0",
            "Accept": "application/json",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.4",
        },
    )
    with urlopen(request, timeout=45) as response:
        if response.status != 200:
            raise R2ScanError(f"Schwarz source HTTP status {response.status}")
        source_json = response.read(16 * 1024 * 1024 + 1)
    if len(source_json) > 16 * 1024 * 1024:
        raise R2ScanError("live source JSON exceeds size limit")

    payload = r1._load_object(source_json, label="live source JSON")
    flyer = payload.get("flyer")
    if not isinstance(flyer, Mapping):
        raise R2ScanError("live source flyer object is missing")
    document_url = str(flyer.get("hiResPdfUrl") or flyer.get("pdfUrl") or "")
    parsed = urlsplit(document_url)
    if (
        parsed.scheme != "https"
        or not parsed.hostname
        or not parsed.hostname.endswith(".schwarz")
    ):
        raise R2ScanError("live PDF host is outside the Schwarz allowlist")

    pdf_request = Request(
        document_url,
        headers={"User-Agent": "HermesDeals-LidlR2StagingScan/2.0"},
    )
    chunks: list[bytes] = []
    total = 0
    with urlopen(pdf_request, timeout=90) as response:
        if response.status != 200:
            raise R2ScanError(f"live PDF HTTP status {response.status}")
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > 128 * 1024 * 1024:
                raise R2ScanError("live PDF exceeds size limit")
            chunks.append(chunk)
    return source_json, b"".join(chunks)


def validate_live_identity(source_json: bytes, source_pdf: bytes) -> dict[str, Any]:
    """Validate only parser-relevant identity; retain raw SHA as provenance.

    The existing source-review contract canonically removes top-level dateTime and
    warnings before hashing parser input. Raw source bytes may therefore change
    while the reviewed parser input and product bindings remain byte-identical.
    """
    pdf_sha = _sha256_bytes(source_pdf)
    if pdf_sha != r1.EXPECTED_PDF_SHA256:
        raise R2ScanError("live PDF differs from the exact approved rev05 PDF")

    identity = r1.stable_source_identity(source_json)
    stable_sha = r1._canonical_digest(identity)
    if stable_sha != r1.EXPECTED_STABLE_SOURCE_IDENTITY_SHA256:
        raise R2ScanError("live stable source identity changed after R1 review")

    parser_input_sha = r1.parser_input_identity(source_json)
    if parser_input_sha != EXPECTED_LIVE_PARSER_INPUT_SHA256:
        raise R2ScanError("live parser-input identity changed after R1 review")

    binding_sha = r1.product_binding_digest(source_json)
    binding_count = len(r1.product_bindings(source_json))
    link_count = r1.product_link_count(source_json)
    if binding_sha != EXPECTED_PRODUCT_BINDING_SHA256:
        raise R2ScanError("live product-binding digest changed after R1 review")
    if binding_count != EXPECTED_PRODUCT_BINDING_COUNT:
        raise R2ScanError("live product-binding count changed after R1 review")
    if link_count != EXPECTED_PRODUCT_LINK_COUNT:
        raise R2ScanError("live product-link count changed after R1 review")

    return {
        "raw_sha256": _sha256_bytes(source_json),
        "raw_sha_is_provenance_only": True,
        "parser_input_identity_sha256": parser_input_sha,
        "product_binding_sha256": binding_sha,
        "product_binding_count": binding_count,
        "product_link_count": link_count,
        "stable_source_identity_sha256": stable_sha,
        "pdf_sha256": pdf_sha,
    }


def _validated_approved_at(value: str) -> str:
    candidate = value.strip()
    if not candidate:
        raise R2ScanError("owner authorization timestamp is missing")
    try:
        parsed = datetime.fromisoformat(candidate.replace("Z", "+00:00"))
    except ValueError as exc:
        raise R2ScanError("owner authorization timestamp is invalid") from exc
    if parsed.tzinfo is None:
        raise R2ScanError("owner authorization timestamp must be timezone-aware")
    return candidate


def build_approved_source_review(
    *, authorization_comment_id: int, approved_at: str
) -> dict[str, Any]:
    if authorization_comment_id <= 0:
        raise R2ScanError("R2 authorization comment ID is invalid")
    approved_at = _validated_approved_at(approved_at)
    return {
        "schema_version": 1,
        "decision": "approve_parser_input_refresh",
        "scope": "authoritative_staging_scan_only",
        "approved_by": APPROVED_BY,
        "approved_at": approved_at,
        "note": (
            "Owner approved exact Lidl rev05 canonical parser-input and product-binding "
            "identity for isolated R2 V6.3.1 staging scans only; raw source SHA is "
            "provenance-only because canonical parser input excludes volatile top-level "
            f"fields; GitHub issue #345 authorization comment {authorization_comment_id}."
        ),
        "flyer_key": r1.EXPECTED_FAMILY,
        "pdf_sha256": r1.EXPECTED_PDF_SHA256,
        "reference_input": dict(EXPECTED_REFERENCE_INPUT),
        "approved_live_input": dict(EXPECTED_LIVE_INPUT),
        "observed_changes": dict(EXPECTED_CHANGES),
        "permissions": {
            "staging_scan": True,
            "corpus_write": False,
            "db_write": False,
            "review_seed": False,
            "auto_approve": False,
            "auto_publish": False,
            "systemd_change": False,
        },
    }


def validate_source_review(review: Mapping[str, Any], *, work_dir: Path) -> str:
    path = work_dir / "approved-source-review.json"
    path.write_bytes(staging._canonical_json_bytes(dict(review)))
    validated, digest = staging._validate_source_review(
        source_review_file=path,
        flyer_key=r1.EXPECTED_FAMILY,
        pdf_sha256=r1.EXPECTED_PDF_SHA256,
        reference_input=EXPECTED_REFERENCE_INPUT,
        live_parser_input_sha256=EXPECTED_LIVE_PARSER_INPUT_SHA256,
        live_product_binding_sha256=EXPECTED_PRODUCT_BINDING_SHA256,
        live_product_binding_count=EXPECTED_PRODUCT_BINDING_COUNT,
        binding_changes=EXPECTED_CHANGES,
    )
    if validated != dict(review):
        raise R2ScanError("approved source-review validation changed payload")
    return digest


def tree_manifest(root: Path) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted(item for item in root.rglob("*") if item.is_file()):
        rows.append(
            {
                "path": path.relative_to(root).as_posix(),
                "bytes": path.stat().st_size,
                "sha256": _sha256_file(path),
            }
        )
    return rows


def scan_tree_digest(rows: list[dict[str, Any]]) -> str:
    content = "\n".join(
        f"{row['path']}|{row['bytes']}|{row['sha256']}" for row in rows
    ) + "\n"
    return sha256(content.encode("utf-8")).hexdigest()


def manifest_digest(rows: list[dict[str, Any]]) -> str:
    encoded = json.dumps(
        rows,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _scan_path(root: Path, scan_name: str) -> Path:
    return root / "flyers" / r1.EXPECTED_FAMILY / "scans" / scan_name


def run_r2(
    *,
    as_of: str,
    output_dir: Path,
    authorization_comment_id: int,
    approved_at: str,
) -> dict[str, Any]:
    if as_of != EXPECTED_AS_OF:
        raise R2ScanError("R2 as-of must match the exact reviewed flyer date")
    if authorization_comment_id <= 0:
        raise R2ScanError("R2 authorization comment ID is invalid")
    approved_at = _validated_approved_at(approved_at)

    output_dir = output_dir.resolve()
    if output_dir.exists():
        if not output_dir.is_dir() or output_dir.is_symlink() or any(output_dir.iterdir()):
            raise R2ScanError("output directory must be an empty safe directory")
    else:
        output_dir.mkdir(parents=True, mode=0o700)

    source_json, source_pdf = fetch_exact_live_source()
    live = validate_live_identity(source_json, source_pdf)
    review = build_approved_source_review(
        authorization_comment_id=authorization_comment_id,
        approved_at=approved_at,
    )

    with tempfile.TemporaryDirectory(prefix="lidl-r2-", dir=output_dir.parent) as raw:
        work = Path(raw)
        review_sha = validate_source_review(review, work_dir=work)

        family = work / r1.EXPECTED_FAMILY
        family.mkdir(mode=0o700)
        (family / "source.json").write_bytes(source_json)
        (family / "source.pdf").write_bytes(source_pdf)

        scan_a_root = work / "scan-a"
        scan_b_root = work / "scan-b"
        result_a = build_scan(
            frozen_family=family,
            output_root=scan_a_root,
            route_region=r1.EXPECTED_ROUTE_REGION,
            target="current",
        )
        result_b = build_scan(
            frozen_family=family,
            output_root=scan_b_root,
            route_region=r1.EXPECTED_ROUTE_REGION,
            target="current",
        )
        if result_a.get("result") != "STAGED_SCAN_READY":
            raise R2ScanError("scan A did not create a fresh isolated staging scan")
        if result_b.get("result") != "STAGED_SCAN_READY":
            raise R2ScanError("scan B did not create a fresh isolated staging scan")
        if result_a.get("scan") != result_b.get("scan"):
            raise R2ScanError("scan names differ between isolated replays")
        if result_a.get("scan_tree_sha256") != result_b.get("scan_tree_sha256"):
            raise R2ScanError("scan tree digests differ between isolated replays")
        if result_a.get("parser_sha256") != SHADOW_SHA256:
            raise R2ScanError("scan A parser SHA is not the frozen V6.3.1 runtime")
        if result_b.get("parser_sha256") != SHADOW_SHA256:
            raise R2ScanError("scan B parser SHA is not the frozen V6.3.1 runtime")

        scan_name = str(result_a["scan"])
        scan_a = _scan_path(scan_a_root, scan_name)
        scan_b = _scan_path(scan_b_root, scan_name)
        manifest_a = tree_manifest(scan_a)
        manifest_b = tree_manifest(scan_b)
        if manifest_a != manifest_b:
            raise R2ScanError("isolated scan trees are not byte-identical")
        tree_sha = scan_tree_digest(manifest_a)
        if tree_sha != result_a["scan_tree_sha256"]:
            raise R2ScanError("independent scan tree digest mismatch")

        scan_summary = json.loads((scan_a / "summary.json").read_text(encoding="utf-8"))
        if scan_summary.get("source") != {
            "pdf_sha256": r1.EXPECTED_PDF_SHA256,
            "raw_sha256": live["raw_sha256"],
        }:
            raise R2ScanError("scan summary source provenance mismatch")
        if scan_summary.get("parser_version") != PARSER_VERSION:
            raise R2ScanError("scan summary parser version mismatch")
        if scan_summary.get("parser_sha256") != SHADOW_SHA256:
            raise R2ScanError("scan summary parser SHA mismatch")

        retained = output_dir / "staging-scan" / scan_name
        retained.parent.mkdir(parents=True, exist_ok=True)
        shutil.copytree(scan_a, retained)

        evidence = output_dir / "evidence"
        evidence.mkdir(mode=0o700)
        review_path = evidence / "approved-source-review.json"
        review_path.write_bytes(staging._canonical_json_bytes(review))
        if _sha256_file(review_path) != review_sha:
            raise R2ScanError("retained source-review SHA mismatch")
        _write_json(evidence / "scan-tree-manifest.json", {"files": manifest_a})

        summary = {
            "schema_version": 1,
            "r2_version": R2_VERSION,
            "result": "R2_STAGING_SCAN_READY",
            "as_of": as_of,
            "authorization_comment_id": authorization_comment_id,
            "source": live,
            "reference_input": dict(EXPECTED_REFERENCE_INPUT),
            "approved_live_input": dict(EXPECTED_LIVE_INPUT),
            "observed_changes": dict(EXPECTED_CHANGES),
            "source_review": {
                "sha256": review_sha,
                "decision": review["decision"],
                "scope": review["scope"],
                "approved_by": review["approved_by"],
                "approved_at": review["approved_at"],
            },
            "parser": {"version": PARSER_VERSION, "sha256": SHADOW_SHA256},
            "scan": {
                "name": scan_name,
                "tree_sha256": tree_sha,
                "manifest_sha256": manifest_digest(manifest_a),
                "file_count": len(manifest_a),
                "rows": int(scan_summary.get("rows") or 0),
                "physical_rows": int(scan_summary.get("physical_rows") or 0),
                "online_only_rows": int(scan_summary.get("online_only_rows") or 0),
                "in_scope_rows": int(scan_summary.get("in_scope_rows") or 0),
                "review_required_rows": int(scan_summary.get("review_required_rows") or 0),
                "accepted_physical_rows": int(scan_summary.get("accepted_physical_rows") or 0),
            },
            "replay": {
                "isolated_runs": 2,
                "byte_identical": True,
                "scan_a_tree_sha256": result_a["scan_tree_sha256"],
                "scan_b_tree_sha256": result_b["scan_tree_sha256"],
            },
            "safety": dict(SAFETY),
        }
        _write_json(evidence / "r2-summary.json", summary)

        retained_manifest = tree_manifest(output_dir)
        if any(
            row["path"].endswith("/source.json")
            or row["path"].endswith("/source.pdf")
            or row["path"] in {"source.json", "source.pdf"}
            for row in retained_manifest
        ):
            raise R2ScanError("raw source material leaked into retained R2 artifact")
        artifact_manifest = {
            "schema_version": 1,
            "r2_version": R2_VERSION,
            "result": summary["result"],
            "payload_tree_sha256": manifest_digest(retained_manifest),
            "files": retained_manifest,
            "raw_source_exported": False,
            "safety": dict(SAFETY),
        }
        _write_json(evidence / "artifact-manifest.json", artifact_manifest)

    return summary


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Owner-authorized Lidl rev05 semantic R2 isolated staging scan"
    )
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--authorization-comment-id", type=int, required=True)
    parser.add_argument("--approved-at", required=True)
    args = parser.parse_args()
    try:
        result = run_r2(
            as_of=args.as_of,
            output_dir=args.output_dir,
            authorization_comment_id=args.authorization_comment_id,
            approved_at=args.approved_at,
        )
    except Exception as exc:  # one fail-closed CLI boundary
        print(f"R2_BLOCKED: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 30
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
