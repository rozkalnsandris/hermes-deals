from __future__ import annotations

import argparse
import csv
import hashlib
import io
import json
from pathlib import Path
import re
import sys
from typing import Any, Iterable, Mapping


REPO_ROOT = Path(__file__).resolve().parents[1]
for candidate in (Path("/repo/backend"), REPO_ROOT / "backend"):
    value = str(candidate)
    if value not in sys.path:
        sys.path.insert(0, value)

from app.lidl_weekly_completeness_contract import (  # noqa: E402
    require_weekly_target_profile,
)
from app.lidl_weekly_semantics import (  # noqa: E402
    SEMANTIC_GATE_VERSION,
    canonical_evidence_manifest,
    partition_weekly_rows,
)


VIEW_VERSION = "lidl-weekly-semantic-view-v1"
EXPECTED_PARSER_VERSION = "lidl-pdf-v08c-r61-shadow-v631"
_SHA256_RE = re.compile(r"[0-9a-f]{64}")


class SemanticViewError(RuntimeError):
    pass


def _sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SemanticViewError(f"invalid JSON {path}: {exc}") from exc


def _read_scan_rows(scan_dir: Path) -> tuple[list[dict[str, Any]], Path]:
    for filename in ("corrected-rows.json", "parser-rows.json"):
        path = scan_dir / filename
        if not path.is_file():
            continue
        payload = _load_json(path)
        if not isinstance(payload, list):
            raise SemanticViewError(f"{filename} must contain a JSON list")
        rows: list[dict[str, Any]] = []
        for index, row in enumerate(payload, start=1):
            if not isinstance(row, Mapping):
                raise SemanticViewError(
                    f"{filename} row {index} must contain an object"
                )
            rows.append(dict(row))
        return rows, path
    raise SemanticViewError("scan has no corrected-rows.json or parser-rows.json")


def _profile_pages(
    values: Any,
    *,
    label: str,
    page_count: int,
    allow_empty: bool,
) -> list[int]:
    if not isinstance(values, list) or (not values and not allow_empty):
        raise SemanticViewError(f"profile {label} has an invalid page list")
    result: list[int] = []
    for raw in values:
        if isinstance(raw, bool) or not isinstance(raw, int):
            raise SemanticViewError(f"profile {label} contains a non-integer page")
        page = int(raw)
        if page < 1 or page > page_count:
            raise SemanticViewError(
                f"profile {label} page out of range: {page}/{page_count}"
            )
        result.append(page)
    if len(result) != len(set(result)):
        raise SemanticViewError(f"profile {label} contains duplicate pages")
    return result


def _reviewed_row_keys(profile: Mapping[str, Any]) -> set[str]:
    raw_reviews = profile.get("unit_basis_reviews") or []
    if not isinstance(raw_reviews, list):
        raise SemanticViewError("profile unit_basis_reviews must be a list")
    reviewed: set[str] = set()
    expected_fields = {
        "row_sha256",
        "decision",
        "reviewed_by",
        "reviewed_at",
        "note",
    }
    for index, raw in enumerate(raw_reviews, start=1):
        if not isinstance(raw, Mapping) or set(raw) != expected_fields:
            raise SemanticViewError(
                f"unit basis review {index} field set mismatch"
            )
        key = str(raw.get("row_sha256") or "")
        if _SHA256_RE.fullmatch(key) is None:
            raise SemanticViewError(
                f"unit basis review {index} row_sha256 is invalid"
            )
        if raw.get("decision") != "approve_unit_basis_semantics":
            raise SemanticViewError(
                f"unit basis review {index} is not an approval"
            )
        for field in ("reviewed_by", "reviewed_at", "note"):
            if not str(raw.get(field) or "").strip():
                raise SemanticViewError(
                    f"unit basis review {index} lacks {field}"
                )
        if key in reviewed:
            raise SemanticViewError("duplicate unit basis row approval")
        reviewed.add(key)
    return reviewed


def load_reviewed_profile(
    flyer_dir: Path,
    *,
    page_count: int,
) -> tuple[dict[str, Any], bytes, set[str]]:
    summary = require_weekly_target_profile(
        flyer_dir,
        page_count=page_count,
    )
    path = flyer_dir / "review-profile.json"
    raw = path.read_bytes()
    payload = _load_json(path)
    if not isinstance(payload, Mapping):
        raise SemanticViewError("review-profile.json must contain an object")
    profile = dict(payload)

    target_pages = _profile_pages(
        profile.get("target_pages"),
        label="target_pages",
        page_count=page_count,
        allow_empty=False,
    )
    baseline_pages = _profile_pages(
        profile.get("baseline_pages", []),
        label="baseline_pages",
        page_count=page_count,
        allow_empty=True,
    )
    excluded_raw = profile.get("excluded_page_roles")
    if not isinstance(excluded_raw, Mapping):
        raise SemanticViewError("profile excluded_page_roles must be an object")
    excluded_pages: list[int] = []
    for role, values in sorted(excluded_raw.items()):
        if not str(role).strip():
            raise SemanticViewError("profile excluded page role is empty")
        excluded_pages.extend(
            _profile_pages(
                values,
                label=f"excluded_page_roles.{role}",
                page_count=page_count,
                allow_empty=True,
            )
        )

    assigned = target_pages + baseline_pages + excluded_pages
    expected = set(range(1, page_count + 1))
    if len(assigned) != len(set(assigned)):
        raise SemanticViewError("review profile page partitions overlap")
    if set(assigned) != expected:
        missing = sorted(expected - set(assigned))
        extra = sorted(set(assigned) - expected)
        raise SemanticViewError(
            f"review profile does not partition every page: "
            f"missing={missing} extra={extra}"
        )
    if target_pages != list(summary["target_pages"]):
        raise SemanticViewError("review profile target-page summary drift")

    reviewed = _reviewed_row_keys(profile)
    profile["target_pages"] = target_pages
    return profile, raw, reviewed


def _tsv_bytes(rows: Iterable[Mapping[str, Any]]) -> bytes:
    values = [dict(row) for row in rows]
    fields = sorted({key for row in values for key in row})
    if not fields:
        fields = ["semantic_row_key"]
    buffer = io.StringIO(newline="")
    writer = csv.DictWriter(
        buffer,
        fieldnames=fields,
        delimiter="\t",
        lineterminator="\n",
        extrasaction="raise",
    )
    writer.writeheader()
    for source in values:
        row: dict[str, str] = {}
        for field in fields:
            value = source.get(field)
            if value is None:
                row[field] = ""
            elif isinstance(value, bool):
                row[field] = "true" if value else "false"
            elif isinstance(value, (dict, list, tuple)):
                row[field] = json.dumps(
                    value,
                    ensure_ascii=False,
                    sort_keys=True,
                    separators=(",", ":"),
                )
            else:
                row[field] = str(value)
        writer.writerow(row)
    return buffer.getvalue().encode("utf-8")


def _write_files_once(output_dir: Path, files: Mapping[str, bytes]) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise SemanticViewError(f"output directory must be empty: {output_dir}")
    for relative, content in sorted(files.items()):
        path = output_dir / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(content)


def build_semantic_view(
    *,
    flyer_dir: Path,
    scan_dir: Path,
    output_dir: Path,
    page_count: int,
) -> dict[str, Any]:
    if page_count < 1:
        raise SemanticViewError("page_count must be positive")
    if not flyer_dir.is_dir() or not scan_dir.is_dir():
        raise SemanticViewError("flyer or scan directory is missing")

    summary_path = scan_dir / "summary.json"
    if not summary_path.is_file():
        raise SemanticViewError("scan summary.json is missing")
    summary_raw = summary_path.read_bytes()
    summary = _load_json(summary_path)
    if not isinstance(summary, Mapping):
        raise SemanticViewError("scan summary must contain an object")
    if summary.get("parser_version") != EXPECTED_PARSER_VERSION:
        raise SemanticViewError("scan parser version is not frozen V6.3.1")

    rows, rows_path = _read_scan_rows(scan_dir)
    rows_raw = rows_path.read_bytes()
    profile, profile_raw, reviewed_keys = load_reviewed_profile(
        flyer_dir,
        page_count=page_count,
    )

    partition = partition_weekly_rows(
        rows,
        target_pages=profile["target_pages"],
        page_role_reviewed=True,
        product_reviewed_row_keys=reviewed_keys,
    )
    all_keys = {row["semantic_row_key"] for row in partition["rows"]}
    unknown_reviews = sorted(reviewed_keys - all_keys)
    if unknown_reviews:
        raise SemanticViewError(
            "unit basis approval does not match a scan row: "
            + ",".join(unknown_reviews)
        )

    coverage = dict(partition["coverage"])
    coverage.update(
        {
            "view_version": VIEW_VERSION,
            "flyer_key": str(summary.get("flyer_key") or flyer_dir.name),
            "scan": str(summary.get("scan") or scan_dir.name),
            "parser_version": summary["parser_version"],
            "parser_sha256": str(summary.get("parser_sha256") or ""),
            "source_pdf_sha256": str(
                (summary.get("source") or {}).get("pdf_sha256")
                or summary.get("pdf_sha256")
                or ""
            ),
            "source_raw_sha256": str(
                (summary.get("source") or {}).get("raw_sha256")
                or summary.get("raw_sha256")
                or ""
            ),
            "review_profile_sha256": _sha256_bytes(profile_raw),
            "scan_summary_sha256": _sha256_bytes(summary_raw),
            "scan_rows_sha256": _sha256_bytes(rows_raw),
            "database_write": False,
            "review_seed": False,
            "auto_approve": False,
            "auto_publish": False,
            "production_deploy": False,
        }
    )
    if coverage["unexplained_count"] != 0:
        raise SemanticViewError("semantic view has unexplained rows")

    binding = {
        "schema_version": 1,
        "view_version": VIEW_VERSION,
        "semantic_gate_version": SEMANTIC_GATE_VERSION,
        "flyer_key": coverage["flyer_key"],
        "scan": coverage["scan"],
        "parser_version": coverage["parser_version"],
        "parser_sha256": coverage["parser_sha256"],
        "source_pdf_sha256": coverage["source_pdf_sha256"],
        "source_raw_sha256": coverage["source_raw_sha256"],
        "review_profile_sha256": coverage["review_profile_sha256"],
        "scan_summary_sha256": coverage["scan_summary_sha256"],
        "scan_rows_sha256": coverage["scan_rows_sha256"],
    }
    files: dict[str, bytes] = {
        "semantic-rows.json": _json_bytes(partition["rows"]),
        "accepted-physical.tsv": _tsv_bytes(
            partition["partitions"]["production_ready"]
        ),
        "review-required.tsv": _tsv_bytes(
            partition["partitions"]["review_required"]
        ),
        "excluded.tsv": _tsv_bytes(partition["partitions"]["excluded"]),
        "coverage-report.json": _json_bytes(coverage),
        "profile-binding.json": _json_bytes(binding),
    }
    manifest_raw, manifest_sha = canonical_evidence_manifest(files)
    files["manifest.json"] = manifest_raw
    _write_files_once(output_dir, files)

    return {
        "result": "SEMANTIC_VIEW_READY",
        "view_version": VIEW_VERSION,
        "manifest_sha256": manifest_sha,
        "coverage": coverage,
        "files": sorted(files),
    }


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Build an immutable reviewed Lidl weekly semantic view"
    )
    parser.add_argument("--flyer-dir", required=True, type=Path)
    parser.add_argument("--scan-dir", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--page-count", required=True, type=int)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        result = build_semantic_view(
            flyer_dir=args.flyer_dir,
            scan_dir=args.scan_dir,
            output_dir=args.output_dir,
            page_count=args.page_count,
        )
    except (SemanticViewError, ValueError) as exc:
        print(
            json.dumps(
                {
                    "result": "BLOCKED_SEMANTIC_VIEW",
                    "reason": str(exc),
                },
                ensure_ascii=False,
                sort_keys=True,
            )
        )
        return 2
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
