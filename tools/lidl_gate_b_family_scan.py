from __future__ import annotations

import argparse
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import shutil
import sys
import tempfile
from typing import Any, Mapping
from uuid import NAMESPACE_URL, uuid5


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "backend"))
sys.path.insert(0, str(ROOT / "tools"))
sys.path.insert(0, str(ROOT / "tools" / "lidl_parser_provenance"))

import lidl_weekly_staging as staging  # noqa: E402
from lidl_gate_b_family_promotion import (  # noqa: E402
    GateBPromotionError,
    canonical_scan_name,
    source_observed_at,
)
from lidl_parser_provenance.lidl_v631_runtime import (  # noqa: E402
    PARSER_VERSION,
    SHADOW_SHA256,
    load_lidl_v631,
)


WORKFLOW_VERSION = "lidl-gate-b-family-scan-v1"


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _meta_from_source(source_json: bytes, *, route_region: str, target: str) -> dict[str, str]:
    try:
        payload = json.loads(source_json)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateBPromotionError("source JSON is invalid") from exc
    flyer = payload.get("flyer") if isinstance(payload, Mapping) else None
    if not isinstance(flyer, Mapping):
        raise GateBPromotionError("source JSON flyer object is missing")
    official_id = str(flyer.get("id") or "").strip()
    viewer = str(flyer.get("flyerUrlAbsolute") or "").strip()
    document = str(flyer.get("hiResPdfUrl") or flyer.get("pdfUrl") or "").strip()
    valid_from = str(flyer.get("offerStartDate") or "").strip()
    valid_until = str(flyer.get("offerEndDate") or "").strip()
    if not all((official_id, viewer, document, valid_from, valid_until, route_region)):
        raise GateBPromotionError("source metadata is incomplete")
    return {
        "target": target,
        "viewer_url": viewer,
        "flyer_identifier": official_id,
        "route_region": route_region,
        "document_url": document,
        "official_flyer_id": official_id,
        "valid_from": valid_from,
        "valid_until": valid_until,
    }


def _scan_digest(scan_root: Path) -> str:
    rows: list[str] = []
    for path in sorted(p for p in scan_root.rglob("*") if p.is_file()):
        rows.append(
            f"{path.relative_to(scan_root).as_posix()}|{path.stat().st_size}|{staging._sha256_file(path)}"
        )
    return _sha256_bytes(("\n".join(rows) + "\n").encode("utf-8"))


def build_scan(
    *,
    frozen_family: Path,
    output_root: Path,
    route_region: str,
    target: str = "next",
) -> dict[str, Any]:
    frozen_family = frozen_family.resolve()
    if not frozen_family.is_dir() or frozen_family.is_symlink():
        raise GateBPromotionError("frozen family is missing or unsafe")
    source_pdf_path = frozen_family / "source.pdf"
    source_json_path = frozen_family / "source.json"
    if not source_pdf_path.is_file() or source_pdf_path.is_symlink():
        raise GateBPromotionError("frozen source PDF is missing or unsafe")
    if not source_json_path.is_file() or source_json_path.is_symlink():
        raise GateBPromotionError("frozen source JSON is missing or unsafe")
    source_pdf = source_pdf_path.read_bytes()
    source_json = source_json_path.read_bytes()
    observed_at = source_observed_at(source_json)
    meta = _meta_from_source(source_json, route_region=route_region, target=target)

    runtime = load_lidl_v631()
    flyer = replace(staging._make_flyer(meta, source_json), discovered_at=observed_at)
    pdf_sha = _sha256_bytes(source_pdf)
    raw_sha = _sha256_bytes(source_json)
    report = runtime.shadow.analyze_lidl_pdf(
        document=source_pdf,
        flyer=flyer,
        snapshot_id=uuid5(
            NAMESPACE_URL,
            f"hermes:lidl-gate-b:{frozen_family.name}:{raw_sha}:{SHADOW_SHA256}",
        ),
        collected_at=observed_at,
    )
    if report.get("parser_version") != PARSER_VERSION:
        raise GateBPromotionError("V6.3.1 parser version drift")

    scan_name = canonical_scan_name(SHADOW_SHA256)
    output_root = output_root.resolve()
    scan_root = output_root / "flyers" / frozen_family.name / "scans" / scan_name
    if scan_root.exists():
        if not scan_root.is_dir() or scan_root.is_symlink():
            raise GateBPromotionError("existing staged scan is unsafe")
        staging._verify_sha256s(scan_root)
        summary = json.loads((scan_root / "summary.json").read_text(encoding="utf-8"))
        if (
            summary.get("flyer_key") != frozen_family.name
            or summary.get("scan") != scan_name
            or summary.get("parser_sha256") != SHADOW_SHA256
            or summary.get("source", {}).get("pdf_sha256") != pdf_sha
            or summary.get("source", {}).get("raw_sha256") != raw_sha
            or summary.get("scanned_at") != observed_at.isoformat()
        ):
            raise GateBPromotionError("existing staged scan identity mismatch")
        return {
            "schema_version": 1,
            "workflow_version": WORKFLOW_VERSION,
            "result": "NO_OP_IDENTICAL",
            "flyer_key": frozen_family.name,
            "scan": scan_name,
            "scan_tree_sha256": _scan_digest(scan_root),
            "observed_at": observed_at.isoformat(),
            "parser_sha256": SHADOW_SHA256,
            "staging_write": False,
            "corpus_write": False,
        }

    rows = [dict(row) for row in report.get("shadow_rows") or []]
    corrected_rows: list[dict[str, Any]] = []
    for source in rows:
        row = dict(source)
        row["manual_reviewed"] = False
        row["manual_corrections"] = []
        corrected_rows.append(row)
    summary = staging._scan_summary(
        report,
        flyer_key=frozen_family.name,
        raw_sha=raw_sha,
        pdf_sha=pdf_sha,
    )
    summary["workflow_version"] = WORKFLOW_VERSION
    summary["scan"] = scan_name
    summary["scanned_at"] = observed_at.isoformat()

    scan_root.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{scan_name}.", dir=scan_root.parent))
    try:
        staging._atomic_json(
            temporary / "parser-report.json",
            {
                "flyer_key": frozen_family.name,
                "parser_sha256": SHADOW_SHA256,
                "parser_version": report.get("parser_version"),
                "base_parser_version": report.get("base_parser_version"),
                "base_metrics": report.get("base_metrics"),
                "shadow_metrics": report.get("v6_metrics"),
                "shadow_rows": rows,
            },
        )
        staging._atomic_json(temporary / "parser-rows.json", rows)
        staging._atomic_json(temporary / "corrected-rows.json", corrected_rows)
        staging._write_tsv(temporary / "parser-rows.tsv", rows)
        staging._write_tsv(temporary / "corrected-rows.tsv", corrected_rows)
        staging._write_tsv(
            temporary / "review-required.tsv",
            [
                row for row in corrected_rows
                if row.get("channel") == "physical_store"
                and (row.get("scope") == "review" or not bool(row.get("production_ready_shadow")))
            ],
        )
        staging._write_tsv(
            temporary / "accepted-physical.tsv",
            [
                row for row in corrected_rows
                if row.get("channel") == "physical_store"
                and row.get("scope") == "in_scope"
                and bool(row.get("production_ready_shadow"))
            ],
        )
        staging._atomic_json(temporary / "summary.json", summary)
        staging._atomic_json(temporary / "correction-errors.json", [])
        staging._atomic_json(
            temporary / "fixture-report.json",
            {"total": 0, "passed": 0, "failed": 0, "results": []},
        )
        staging._write_sha256s(temporary)
        try:
            temporary.rename(scan_root)
        except FileExistsError as exc:
            raise GateBPromotionError("canonical staged scan appeared concurrently") from exc
    finally:
        shutil.rmtree(temporary, ignore_errors=True)

    staging._verify_sha256s(scan_root)
    return {
        "schema_version": 1,
        "workflow_version": WORKFLOW_VERSION,
        "result": "STAGED_SCAN_READY",
        "flyer_key": frozen_family.name,
        "scan": scan_name,
        "scan_tree_sha256": _scan_digest(scan_root),
        "observed_at": observed_at.isoformat(),
        "parser_sha256": SHADOW_SHA256,
        "parser_version": PARSER_VERSION,
        "staging_write": True,
        "corpus_write": False,
        "db_write": False,
        "review_write": False,
        "auto_approve": False,
        "auto_publish": False,
        "production_deploy": False,
        "systemd_change": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a deterministic staging-only Lidl Gate B V6.3.1 scan")
    parser.add_argument("--frozen-family", type=Path, required=True)
    parser.add_argument("--output-root", type=Path, required=True)
    parser.add_argument("--route-region", required=True)
    parser.add_argument("--target", choices=("current", "next"), default="next")
    args = parser.parse_args()
    try:
        result = build_scan(
            frozen_family=args.frozen_family,
            output_root=args.output_root,
            route_region=args.route_region,
            target=args.target,
        )
    except GateBPromotionError as exc:
        print(f"ERROR: {exc}")
        return 2
    print(json.dumps(result, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
