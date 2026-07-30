from __future__ import annotations

import argparse
import csv
from dataclasses import asdict
from datetime import date, datetime, timezone
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import shutil
import tempfile
from typing import Any, Mapping, Sequence
from urllib.parse import urlsplit
from uuid import NAMESPACE_URL, uuid5

import sys
sys.path.insert(0, "/repo/backend")
sys.path.insert(0, "/repo/tools")
sys.path.insert(0, "/repo/tools/lidl_parser_provenance")

from app.lidl_weekly_completeness_contract import (  # noqa: E402
    WEEKLY_PAGE_ROLE_REVIEWED_STATUSES,
    WeeklyTargetProfileGate,
    require_weekly_target_profile,
)
from lidl_parser_provenance.lidl_v631_runtime import (  # noqa: E402
    DiscoveredFlyer,
    FlyerTarget,
    PARSER_VERSION,
    ProductBinding,
    SHADOW_SHA256,
    load_lidl_v631,
)
from lidl_weekly_one_shot import (  # noqa: E402
    load_discovery_evidence,
    source_readiness,
)


WORKFLOW_VERSION = "lidl-family-weekly-staging-v4-reviewed-page-role-profile"
SOURCE_LAYOUT_VERSION = "lidl-family-weekly-staging-v2-input-gate"
EXIT_CODES = {
    "STAGED_SCAN_READY": 0,
    "WAIT_SOURCE": 20,
    "WAIT_SOURCE_REVIEW": 21,
    "WAIT_PROFILE": 22,
    "BLOCKED_SOURCE_DRIFT": 30,
    "BLOCKED_PARSER_DRIFT": 31,
}

TSV_FIELDS = [
    "page",
    "product_name",
    "package_text",
    "price_eur",
    "regular_price_eur",
    "regular_price_source",
    "app_price_eur",
    "valid_from",
    "valid_until",
    "validity_source",
    "channel",
    "channel_source",
    "scope",
    "scope_source",
    "price_basis",
    "production_ready_shadow",
    "comparison_eligible_shadow",
    "r6_classification",
    "recovery_source",
    "warnings",
    "manual_reviewed",
    "manual_corrections",
]


class StagingError(RuntimeError):
    pass


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _atomic_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("x", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, indent=2, sort_keys=True)
            handle.write("\n")
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _write_bytes_once(path: Path, data: bytes) -> bool:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if not path.is_file() or path.read_bytes() != data:
            raise StagingError(f"immutable staging collision: {path}")
        return False
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)
    return True


def _stable_source_identity(source_json: bytes) -> dict[str, Any]:
    try:
        payload = json.loads(source_json)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StagingError(f"source JSON invalid: {type(exc).__name__}") from exc
    if not isinstance(payload, Mapping):
        raise StagingError("source JSON must contain an object")
    flyer = payload.get("flyer")
    if not isinstance(flyer, Mapping):
        raise StagingError("source JSON flyer object missing")
    pages = flyer.get("pages") or []
    if not isinstance(pages, list):
        raise StagingError("source JSON pages must be a list")
    regions = sorted(
        str(row.get("code"))
        for row in (flyer.get("regions") or [])
        if isinstance(row, Mapping) and row.get("code") is not None
    )
    identity = {
        "official_flyer_id": str(flyer.get("id") or ""),
        "viewer_path": urlsplit(str(flyer.get("flyerUrlAbsolute") or "")).path,
        "document_path": urlsplit(
            str(flyer.get("hiResPdfUrl") or flyer.get("pdfUrl") or "")
        ).path,
        "valid_from": str(flyer.get("offerStartDate") or ""),
        "valid_until": str(flyer.get("offerEndDate") or ""),
        "advertised_regions": regions,
        "page_count": len(pages),
    }
    missing = [
        key
        for key in (
            "official_flyer_id",
            "viewer_path",
            "document_path",
            "valid_from",
            "valid_until",
        )
        if not identity[key]
    ]
    if missing:
        raise StagingError("stable source identity incomplete: " + ",".join(missing))
    return identity


def _identity_digest(identity: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        identity,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )
        + "\n"
    ).encode("utf-8")


def _canonical_parser_input(source_json: bytes) -> Mapping[str, Any]:
    try:
        payload = json.loads(source_json)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StagingError(f"source JSON invalid: {type(exc).__name__}") from exc
    if not isinstance(payload, Mapping):
        raise StagingError("source JSON must contain an object")
    canonical = dict(payload)
    canonical.pop("dateTime", None)
    canonical.pop("warnings", None)
    return canonical


def _parser_input_identity(source_json: bytes) -> str:
    return _identity_digest(_canonical_parser_input(source_json))


def _product_binding_projection(source_json: bytes) -> list[dict[str, Any]]:
    return [
        {
            "page": row.page,
            "product_id": row.product_id,
            "title": row.title,
            "bbox": list(row.bbox),
        }
        for row in product_bindings(source_json)
    ]


def _product_binding_digest(source_json: bytes) -> str:
    encoded = json.dumps(
        _product_binding_projection(source_json),
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _reference_parser_input(
    *,
    reference_corpus_root: Path | None,
    flyer_key: str,
    expected_pdf_sha256: str,
) -> dict[str, Any] | None:
    if reference_corpus_root is None:
        return None
    flyer_root = reference_corpus_root.resolve() / "flyers" / flyer_key
    source_json_path = flyer_root / "source.json"
    source_pdf_path = flyer_root / "source.pdf"
    if not source_json_path.exists() and not source_pdf_path.exists():
        return None
    if not source_json_path.is_file() or not source_pdf_path.is_file():
        raise StagingError("reference corpus source is incomplete")
    if _sha256_file(source_pdf_path) != expected_pdf_sha256:
        raise StagingError("reference corpus PDF identity mismatch")
    source_json = source_json_path.read_bytes()
    return {
        "raw_sha256": _sha256_bytes(source_json),
        "parser_input_identity_sha256": _parser_input_identity(source_json),
        "product_binding_sha256": _product_binding_digest(source_json),
        "product_binding_count": len(product_bindings(source_json)),
    }


def _binding_change_summary(
    reference_source_json: bytes,
    live_source_json: bytes,
) -> dict[str, int]:
    def keyed(source_json: bytes) -> dict[tuple[Any, ...], ProductBinding]:
        return {
            (row.page, row.product_id, row.bbox): row
            for row in product_bindings(source_json)
        }

    reference = keyed(reference_source_json)
    live = keyed(live_source_json)
    reference_keys = set(reference)
    live_keys = set(live)
    common = reference_keys & live_keys
    return {
        "binding_added": len(live_keys - reference_keys),
        "binding_removed": len(reference_keys - live_keys),
        "binding_title_changed": sum(
            reference[key].title != live[key].title
            for key in common
        ),
    }


def _load_reference_source_json(
    *,
    reference_corpus_root: Path | None,
    flyer_key: str,
    expected_pdf_sha256: str,
) -> bytes | None:
    if reference_corpus_root is None:
        return None
    flyer_root = reference_corpus_root.resolve() / "flyers" / flyer_key
    source_json_path = flyer_root / "source.json"
    source_pdf_path = flyer_root / "source.pdf"
    if not source_json_path.exists() and not source_pdf_path.exists():
        return None
    if not source_json_path.is_file() or not source_pdf_path.is_file():
        raise StagingError("reference corpus source is incomplete")
    if _sha256_file(source_pdf_path) != expected_pdf_sha256:
        raise StagingError("reference corpus PDF identity mismatch")
    return source_json_path.read_bytes()


def _validate_source_review(
    *,
    source_review_file: Path,
    flyer_key: str,
    pdf_sha256: str,
    reference_input: Mapping[str, Any],
    live_parser_input_sha256: str,
    live_product_binding_sha256: str,
    live_product_binding_count: int,
    binding_changes: Mapping[str, int],
) -> tuple[dict[str, Any], str]:
    if not source_review_file.is_file():
        raise StagingError("source review file is missing")
    if source_review_file.stat().st_size > 64 * 1024:
        raise StagingError("source review file is too large")
    try:
        payload = json.loads(source_review_file.read_text(encoding="utf-8"))
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StagingError(
            f"source review JSON invalid: {type(exc).__name__}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise StagingError("source review must contain an object")
    review = dict(payload)
    required_top_level = {
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
    if set(review) != required_top_level:
        raise StagingError("source review field set mismatch")
    if review["schema_version"] != 1:
        raise StagingError("source review schema version mismatch")
    if review["decision"] != "approve_parser_input_refresh":
        raise StagingError("source review decision is not approval")
    if review["scope"] != "authoritative_staging_scan_only":
        raise StagingError("source review scope is unsafe")
    if not str(review["approved_by"]).strip():
        raise StagingError("source review approver is missing")
    if not str(review["approved_at"]).strip():
        raise StagingError("source review timestamp is missing")
    if not str(review["note"]).strip():
        raise StagingError("source review note is missing")
    if review["flyer_key"] != flyer_key:
        raise StagingError("source review flyer key mismatch")
    if review["pdf_sha256"] != pdf_sha256:
        raise StagingError("source review PDF identity mismatch")

    expected_reference = {
        "parser_input_identity_sha256": reference_input[
            "parser_input_identity_sha256"
        ],
        "product_binding_sha256": reference_input["product_binding_sha256"],
        "product_binding_count": reference_input["product_binding_count"],
    }
    if review["reference_input"] != expected_reference:
        raise StagingError("source review reference input mismatch")

    expected_live = {
        "parser_input_identity_sha256": live_parser_input_sha256,
        "product_binding_sha256": live_product_binding_sha256,
        "product_binding_count": live_product_binding_count,
    }
    if review["approved_live_input"] != expected_live:
        raise StagingError("source review approved live input mismatch")
    if review["observed_changes"] != dict(binding_changes):
        raise StagingError("source review change summary mismatch")

    expected_permissions = {
        "staging_scan": True,
        "corpus_write": False,
        "db_write": False,
        "review_seed": False,
        "auto_approve": False,
        "auto_publish": False,
        "systemd_change": False,
    }
    if review["permissions"] != expected_permissions:
        raise StagingError("source review permissions are unsafe")
    return review, _sha256_bytes(_canonical_json_bytes(review))


def _review_profile_pages(
    values: Any,
    *,
    label: str,
    page_count: int,
    allow_empty: bool = False,
) -> list[int]:
    if not isinstance(values, list) or (not values and not allow_empty):
        requirement = "a list" if allow_empty else "a non-empty list"
        raise StagingError(f"review profile {label} must be {requirement}")
    pages: list[int] = []
    for value in values:
        if isinstance(value, bool) or not isinstance(value, int):
            raise StagingError(
                f"review profile {label} page must be an integer: {value!r}"
            )
        page = int(value)
        if page < 1 or page > int(page_count):
            raise StagingError(
                f"review profile {label} page out of range: "
                f"page={page} page_count={page_count}"
            )
        pages.append(page)
    if len(pages) != len(set(pages)):
        raise StagingError(f"review profile {label} contains duplicates")
    return pages


def _validate_review_profile(
    *,
    review_profile_file: Path,
    pdf_sha256: str,
    page_count: int,
) -> tuple[dict[str, Any], bytes, str]:
    if not review_profile_file.is_file():
        raise StagingError("review profile file is missing")
    if review_profile_file.stat().st_size > 128 * 1024:
        raise StagingError("review profile file is too large")
    raw = review_profile_file.read_bytes()
    try:
        payload = json.loads(raw)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise StagingError(
            f"review profile JSON invalid: {type(exc).__name__}"
        ) from exc
    if not isinstance(payload, Mapping):
        raise StagingError("review profile must contain an object")
    profile = dict(payload)
    expected_fields = {
        "schema_version",
        "status",
        "target_kind",
        "target_pages",
        "baseline_pages",
        "excluded_page_roles",
        "reference_expectations",
        "unit_basis_reviews",
        "source",
        "note",
    }
    if set(profile) != expected_fields:
        raise StagingError("review profile field set mismatch")
    if profile["schema_version"] != 1:
        raise StagingError("review profile schema version mismatch")
    if profile["status"] not in WEEKLY_PAGE_ROLE_REVIEWED_STATUSES:
        raise StagingError("review profile page-role status is not reviewed")
    if profile["target_kind"] != "weekly_physical_deals":
        raise StagingError("review profile target kind mismatch")

    target_pages = _review_profile_pages(
        profile["target_pages"],
        label="target_pages",
        page_count=page_count,
    )
    baseline_pages = _review_profile_pages(
        profile["baseline_pages"],
        label="baseline_pages",
        page_count=page_count,
        allow_empty=True,
    )
    excluded_raw = profile["excluded_page_roles"]
    if not isinstance(excluded_raw, Mapping) or not excluded_raw:
        raise StagingError(
            "review profile excluded_page_roles must be a non-empty object"
        )
    excluded_pages: list[int] = []
    for role, values in sorted(excluded_raw.items()):
        if not isinstance(role, str) or not role.strip():
            raise StagingError("review profile excluded page role is invalid")
        excluded_pages.extend(
            _review_profile_pages(
                values,
                label=f"excluded_page_roles.{role}",
                page_count=page_count,
            )
        )

    assigned = target_pages + baseline_pages + excluded_pages
    if len(assigned) != len(set(assigned)):
        raise StagingError("review profile page roles overlap")
    expected_pages = set(range(1, int(page_count) + 1))
    if set(assigned) != expected_pages:
        missing = sorted(expected_pages - set(assigned))
        extra = sorted(set(assigned) - expected_pages)
        raise StagingError(
            "review profile does not partition all pages: "
            f"missing={missing} extra={extra}"
        )

    expectations = profile["reference_expectations"]
    if not isinstance(expectations, Mapping):
        raise StagingError("review profile reference expectations are invalid")
    if expectations.get("target_page_count") != len(target_pages):
        raise StagingError("review profile target page count mismatch")
    if not isinstance(profile["unit_basis_reviews"], list):
        raise StagingError("review profile unit_basis_reviews must be a list")
    source = str(profile["source"] or "")
    if pdf_sha256 not in source:
        raise StagingError("review profile source PDF identity mismatch")
    if not str(profile["note"] or "").strip():
        raise StagingError("review profile note is missing")

    return profile, raw, _sha256_bytes(raw)


def staging_flyer_key(
    *, valid_from: str, valid_until: str, route_region: str, pdf_sha256: str
) -> str:
    if not re.fullmatch(r"[0-9a-f]{64}", pdf_sha256):
        raise StagingError("PDF SHA256 must be a lowercase full digest")
    if not re.fullmatch(r"[0-9A-Za-z_-]+", route_region):
        raise StagingError("route region contains unsupported characters")
    return (
        f"{valid_from.replace('-', '')}-{valid_until.replace('-', '')}"
        f"-r{route_region}-{pdf_sha256[:12]}"
    )


def _normalized_fraction(value: Any) -> float:
    number = float(value)
    if number > 1.0:
        number /= 100.0
    return number


def product_bindings(source_json: bytes) -> tuple[ProductBinding, ...]:
    payload = json.loads(source_json)
    flyer = payload.get("flyer") if isinstance(payload, Mapping) else None
    if not isinstance(flyer, Mapping):
        return ()
    products_raw = flyer.get("products") or {}
    if isinstance(products_raw, Mapping):
        products = [row for row in products_raw.values() if isinstance(row, Mapping)]
    elif isinstance(products_raw, list):
        products = [row for row in products_raw if isinstance(row, Mapping)]
    else:
        products = []
    by_id = {
        str(row.get("productId")): row
        for row in products
        if row.get("productId") is not None
    }
    result: list[ProductBinding] = []
    pages = flyer.get("pages") or []
    if not isinstance(pages, list):
        return ()
    for page_index, page in enumerate(pages):
        if not isinstance(page, Mapping):
            continue
        for link in page.get("links") or []:
            if not isinstance(link, Mapping):
                continue
            details = link.get("productDetails")
            if not isinstance(details, Mapping) or details.get("productId") is None:
                continue
            product_id = str(details.get("productId"))
            product = by_id.get(product_id)
            title = str(details.get("title") or "").strip()
            if not title and isinstance(product, Mapping):
                title = str(product.get("title") or product.get("name") or "").strip()
            if not title:
                title = str(link.get("title") or "").strip()
            try:
                left = _normalized_fraction(link.get("left"))
                top = _normalized_fraction(link.get("top"))
                width = _normalized_fraction(link.get("width"))
                height = _normalized_fraction(link.get("height"))
            except (TypeError, ValueError):
                continue
            bbox = (left, top, left + width, top + height)
            if not (
                0.0 <= bbox[0] < bbox[2] <= 1.000001
                and 0.0 <= bbox[1] < bbox[3] <= 1.000001
            ):
                continue
            result.append(
                ProductBinding(
                    page=page_index,
                    product_id=product_id,
                    title=title,
                    bbox=tuple(round(value, 8) for value in bbox),
                )
            )
    return tuple(
        sorted(
            result,
            key=lambda row: (row.page, row.product_id, row.title, row.bbox),
        )
    )


def _make_flyer(meta: Mapping[str, Any], source_json: bytes) -> DiscoveredFlyer:
    payload = json.loads(source_json)
    flyer = payload["flyer"]
    advertised = tuple(
        str(row.get("code"))
        for row in (flyer.get("regions") or [])
        if isinstance(row, Mapping) and row.get("code") is not None
    )
    target = FlyerTarget(str(meta.get("target") or "next"))
    return DiscoveredFlyer(
        target=target,
        hub_url="https://www.lidl.de/c/online-prospekte/s10005610/",
        viewer_url=str(meta["viewer_url"]),
        flyer_identifier=str(meta["flyer_identifier"]),
        route_region=str(meta["route_region"]),
        advertised_regions=advertised,
        schwarz_json_url=(
            "https://endpoints.leaflets.schwarz/v4/flyer?"
            f"version=4&flyer_identifier={meta['flyer_identifier']}"
            f"&client=lidl&region_id={meta['route_region']}"
        ),
        document_url=str(meta["document_url"]),
        official_flyer_id=str(meta["official_flyer_id"]),
        valid_from=date.fromisoformat(str(meta["valid_from"])),
        valid_until=date.fromisoformat(str(meta["valid_until"])),
        raw_fetch=source_json,
        raw_fetch_sha256=_sha256_bytes(source_json),
        etag=None,
        last_modified=None,
        hub_etag=None,
        hub_last_modified=None,
        viewer_etag=None,
        viewer_last_modified=None,
        discovered_at=datetime.now(timezone.utc),
        product_bindings=product_bindings(source_json),
    )


def _write_tsv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(
            handle,
            delimiter="\t",
            fieldnames=TSV_FIELDS,
            extrasaction="ignore",
        )
        writer.writeheader()
        for source in rows:
            row = dict(source)
            for key in ("warnings", "manual_corrections"):
                if isinstance(row.get(key), (list, dict)):
                    row[key] = json.dumps(
                        row[key], ensure_ascii=False, sort_keys=True
                    )
            writer.writerow(row)


def _write_sha256s(root: Path) -> str:
    lines = []
    for path in sorted(
        row for row in root.rglob("*") if row.is_file() and row.name != "SHA256SUMS"
    ):
        lines.append(f"{_sha256_file(path)}  {path.relative_to(root)}")
    content = "\n".join(lines) + "\n"
    (root / "SHA256SUMS").write_text(content, encoding="utf-8")
    return sha256(content.encode("utf-8")).hexdigest()


def _verify_sha256s(root: Path) -> None:
    sums = root / "SHA256SUMS"
    if not sums.is_file():
        raise StagingError(f"staging checksum manifest missing: {sums}")
    for line in sums.read_text(encoding="utf-8").splitlines():
        digest, relative = line.split("  ", 1)
        path = root / relative
        if not path.is_file() or _sha256_file(path) != digest:
            raise StagingError(f"staging checksum mismatch: {relative}")


def _scan_summary(report: Mapping[str, Any], *, flyer_key: str, raw_sha: str, pdf_sha: str) -> dict[str, Any]:
    rows = [dict(row) for row in report.get("shadow_rows") or []]
    review_rows = [
        row
        for row in rows
        if row.get("channel") == "physical_store"
        and (
            row.get("scope") == "review"
            or not bool(row.get("production_ready_shadow"))
        )
    ]
    accepted_rows = [
        row
        for row in rows
        if row.get("channel") == "physical_store"
        and row.get("scope") == "in_scope"
        and bool(row.get("production_ready_shadow"))
    ]
    return {
        "schema_version": 1,
        "workflow_version": WORKFLOW_VERSION,
        "flyer_key": flyer_key,
        "scan": f"v631-{SHADOW_SHA256[:12]}",
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "pdf_sha256": pdf_sha,
            "raw_sha256": raw_sha,
        },
        "parser_sha256": SHADOW_SHA256,
        "parser_version": report.get("parser_version"),
        "base_parser_version": report.get("base_parser_version"),
        "base_metrics": report.get("base_metrics"),
        "shadow_metrics": report.get("v6_metrics"),
        "rows": len(rows),
        "physical_rows": sum(row.get("channel") == "physical_store" for row in rows),
        "online_only_rows": sum(row.get("channel") == "online_only" for row in rows),
        "in_scope_rows": sum(row.get("scope") == "in_scope" for row in rows),
        "review_required_rows": len(review_rows),
        "accepted_physical_rows": len(accepted_rows),
        "manual_corrections": 0,
        "correction_errors": 0,
        "fixtures_total": 0,
        "fixtures_failed": 0,
    }


def _materialize_scan(
    *,
    flyer_root: Path,
    observation_root: Path,
    meta: Mapping[str, Any],
    source_pdf: bytes,
    source_json: bytes,
) -> tuple[Path, dict[str, Any], bool]:
    scan_name = f"v631-{SHADOW_SHA256[:12]}"
    scans_root = observation_root / "scans"
    scan_root = scans_root / scan_name
    if scan_root.is_dir():
        _verify_sha256s(scan_root)
        summary = json.loads((scan_root / "summary.json").read_text(encoding="utf-8"))
        if (
            summary.get("parser_version") != PARSER_VERSION
            or summary.get("parser_sha256") != SHADOW_SHA256
            or summary.get("source", {}).get("pdf_sha256") != _sha256_bytes(source_pdf)
            or summary.get("source", {}).get("raw_sha256") != _sha256_bytes(source_json)
        ):
            raise StagingError("existing staging scan identity mismatch")
        return scan_root, summary, False

    runtime = load_lidl_v631()
    flyer = _make_flyer(meta, source_json)
    pdf_sha = _sha256_bytes(source_pdf)
    raw_sha = _sha256_bytes(source_json)
    report = runtime.shadow.analyze_lidl_pdf(
        document=source_pdf,
        flyer=flyer,
        snapshot_id=uuid5(
            NAMESPACE_URL,
            f"hermes:lidl-staging:{flyer_root.name}:{raw_sha}:{SHADOW_SHA256}",
        ),
        collected_at=datetime.now(timezone.utc),
    )
    if report.get("parser_version") != PARSER_VERSION:
        raise StagingError("V6.3.1 parser version drift")
    rows = [dict(row) for row in report.get("shadow_rows") or []]
    corrected_rows = []
    for source in rows:
        row = dict(source)
        row["manual_reviewed"] = False
        row["manual_corrections"] = []
        corrected_rows.append(row)
    summary = _scan_summary(
        report,
        flyer_key=flyer_root.name,
        raw_sha=raw_sha,
        pdf_sha=pdf_sha,
    )

    scans_root.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=f".{scan_name}.", dir=scans_root))
    try:
        _atomic_json(
            temporary / "parser-report.json",
            {
                "flyer_key": flyer_root.name,
                "parser_sha256": SHADOW_SHA256,
                "parser_version": report.get("parser_version"),
                "base_parser_version": report.get("base_parser_version"),
                "base_metrics": report.get("base_metrics"),
                "shadow_metrics": report.get("v6_metrics"),
                "shadow_rows": rows,
            },
        )
        _atomic_json(temporary / "parser-rows.json", rows)
        _atomic_json(temporary / "corrected-rows.json", corrected_rows)
        _write_tsv(temporary / "parser-rows.tsv", rows)
        _write_tsv(temporary / "corrected-rows.tsv", corrected_rows)
        _write_tsv(
            temporary / "review-required.tsv",
            [
                row
                for row in corrected_rows
                if row.get("channel") == "physical_store"
                and (
                    row.get("scope") == "review"
                    or not bool(row.get("production_ready_shadow"))
                )
            ],
        )
        _write_tsv(
            temporary / "accepted-physical.tsv",
            [
                row
                for row in corrected_rows
                if row.get("channel") == "physical_store"
                and row.get("scope") == "in_scope"
                and bool(row.get("production_ready_shadow"))
            ],
        )
        _atomic_json(temporary / "summary.json", summary)
        _atomic_json(temporary / "correction-errors.json", [])
        _atomic_json(
            temporary / "fixture-report.json",
            {"total": 0, "passed": 0, "failed": 0, "results": []},
        )
        _write_sha256s(temporary)
        os.replace(temporary, scan_root)
    finally:
        shutil.rmtree(temporary, ignore_errors=True)
    return scan_root, summary, True


def _status_payload(
    *,
    result: str,
    reason: str,
    target: str,
    source: Mapping[str, Any] | None = None,
    staging: Mapping[str, Any] | None = None,
    scan: Mapping[str, Any] | None = None,
    review_profile: Mapping[str, Any] | None = None,
    source_review: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "workflow_version": WORKFLOW_VERSION,
        "result": result,
        "reason": reason,
        "target": target,
        "source": dict(source or {}),
        "staging": dict(staging or {}),
        "scan": dict(scan or {}),
        "review_profile": dict(review_profile or {}),
        "source_review": dict(source_review or {}),
        "parser_version": PARSER_VERSION,
        "parser_sha256": SHADOW_SHA256,
        "staging_write": True,
        "corpus_write": False,
        "db_write": False,
        "review_seed": False,
        "auto_approve": False,
        "auto_publish": False,
        "systemd_change": False,
    }


def run_staging(
    *,
    discovery_dir: Path,
    staging_root: Path,
    output_dir: Path,
    target: str,
    reference_corpus_root: Path | None = None,
    source_review_file: Path | None = None,
    review_profile_file: Path | None = None,
) -> dict[str, Any]:
    output_dir.mkdir(parents=True, exist_ok=True)
    if any(output_dir.iterdir()):
        raise StagingError(f"output directory must be empty: {output_dir}")
    discovery, evidence = load_discovery_evidence(discovery_dir)
    selected = evidence.get(target)
    source_meta = dict(discovery.get("targets", {}).get(target) or {})
    if selected is None:
        payload = _status_payload(
            result="WAIT_SOURCE",
            reason="selected_store_target_not_available",
            target=target,
            source=source_meta,
        )
        _atomic_json(output_dir / "staging-status.json", payload)
        return payload
    readiness = source_readiness(selected.source_json)
    source_meta["readiness"] = readiness
    if readiness["state"] != "SOURCE_AVAILABLE":
        payload = _status_payload(
            result=str(readiness["state"]),
            reason=str(readiness["reason"]),
            target=target,
            source=source_meta,
        )
        _atomic_json(output_dir / "staging-status.json", payload)
        return payload

    identity = _stable_source_identity(selected.source_json)
    identity_sha = _identity_digest(identity)
    flyer_key = staging_flyer_key(
        valid_from=selected.valid_from,
        valid_until=selected.valid_until,
        route_region=selected.route_region,
        pdf_sha256=selected.pdf_sha256,
    )
    flyer_root = staging_root.resolve() / "flyers" / flyer_key
    source_manifest = {
        "schema_version": 1,
        "workflow_version": SOURCE_LAYOUT_VERSION,
        "flyer_key": flyer_key,
        "source": {
            "pdf_sha256": selected.pdf_sha256,
            "pdf_bytes": selected.pdf_bytes,
            "stable_source_identity_sha256": identity_sha,
        },
        "flyer": {
            "target": selected.target,
            "flyer_identifier": selected.flyer_identifier,
            "route_region": selected.route_region,
            "valid_from": selected.valid_from,
            "valid_until": selected.valid_until,
            "viewer_url": selected.viewer_url,
            "viewer_final_url": selected.viewer_final_url,
            "official_flyer_id": selected.official_flyer_id,
            "document_url": selected.document_url,
            "advertised_regions": list(selected.advertised_regions),
            "page_count": selected.page_count,
        },
        "stable_source_identity": identity,
    }

    source_created = _write_bytes_once(flyer_root / "source.pdf", selected.source_pdf)
    manifest_path = flyer_root / "source-manifest.json"
    if manifest_path.exists():
        old_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if old_manifest != source_manifest:
            raise StagingError("existing staging source manifest mismatch")
        manifest_created = False
    else:
        _atomic_json(manifest_path, source_manifest)
        manifest_created = True

    raw_sha = selected.raw_sha256
    parser_input_sha = _parser_input_identity(selected.source_json)
    product_binding_sha = _product_binding_digest(selected.source_json)
    product_binding_count = len(product_bindings(selected.source_json))
    reference_input = _reference_parser_input(
        reference_corpus_root=reference_corpus_root,
        flyer_key=flyer_key,
        expected_pdf_sha256=selected.pdf_sha256,
    )
    reference_source_json = _load_reference_source_json(
        reference_corpus_root=reference_corpus_root,
        flyer_key=flyer_key,
        expected_pdf_sha256=selected.pdf_sha256,
    )

    observation_root = flyer_root / "observations" / raw_sha
    raw_created = _write_bytes_once(
        observation_root / "source.json",
        selected.source_json,
    )
    observation_meta = {
        "schema_version": 1,
        "workflow_version": SOURCE_LAYOUT_VERSION,
        "raw_sha256": raw_sha,
        "raw_bytes": selected.raw_bytes,
        "stable_source_identity_sha256": identity_sha,
        "source_pdf_sha256": selected.pdf_sha256,
        "parser_input_identity_sha256": parser_input_sha,
        "product_binding_sha256": product_binding_sha,
        "product_binding_count": product_binding_count,
        "reference_input": reference_input or {},
    }
    observation_meta_path = observation_root / "observation.json"
    if observation_meta_path.exists():
        if json.loads(observation_meta_path.read_text(encoding="utf-8")) != observation_meta:
            raise StagingError("existing staging observation metadata mismatch")
        observation_meta_created = False
    else:
        _atomic_json(observation_meta_path, observation_meta)
        observation_meta_created = True

    staging_before_scan = {
        "flyer_key": flyer_key,
        "flyer_root": str(flyer_root),
        "observation_root": str(observation_root),
        "scan_root": "",
        "source_created": source_created,
        "source_manifest_created": manifest_created,
        "observation_created": raw_created,
        "observation_meta_created": observation_meta_created,
        "scan_created": False,
        "reused": not any(
            (
                source_created,
                manifest_created,
                raw_created,
                observation_meta_created,
            )
        ),
        "stable_source_identity_sha256": identity_sha,
        "source_pdf_sha256": selected.pdf_sha256,
        "source_raw_sha256": raw_sha,
        "parser_input_identity_sha256": parser_input_sha,
        "product_binding_sha256": product_binding_sha,
        "product_binding_count": product_binding_count,
        "reference_input": reference_input or {},
    }

    parser_input_changed = (
        reference_input is not None
        and reference_input["parser_input_identity_sha256"] != parser_input_sha
    )
    source_review_payload: dict[str, Any] = {}
    if parser_input_changed:
        if reference_source_json is None:
            raise StagingError("reference source JSON is unavailable")
        binding_changes = _binding_change_summary(
            reference_source_json,
            selected.source_json,
        )
        if source_review_file is None:
            payload = _status_payload(
                result="WAIT_SOURCE_REVIEW",
                reason="parser_input_identity_changed_for_existing_pdf",
                target=target,
                source=source_meta,
                staging=staging_before_scan,
            )
            _atomic_json(output_dir / "staging-status.json", payload)
            return payload
        review, review_sha = _validate_source_review(
            source_review_file=source_review_file,
            flyer_key=flyer_key,
            pdf_sha256=selected.pdf_sha256,
            reference_input=reference_input,
            live_parser_input_sha256=parser_input_sha,
            live_product_binding_sha256=product_binding_sha,
            live_product_binding_count=product_binding_count,
            binding_changes=binding_changes,
        )
        review_path = observation_root / "source-review.json"
        review_created = _write_bytes_once(
            review_path,
            _canonical_json_bytes(review),
        )
        source_review_payload = {
            "approved": True,
            "created": review_created,
            "path": str(review_path),
            "sha256": review_sha,
            "decision": review["decision"],
            "scope": review["scope"],
            "approved_by": review["approved_by"],
            "approved_at": review["approved_at"],
            "observed_changes": binding_changes,
        }
        staging_before_scan["source_review_created"] = review_created
        staging_before_scan["source_review_sha256"] = review_sha
        staging_before_scan["source_review_path"] = str(review_path)
        staging_before_scan["reused"] = (
            staging_before_scan["reused"] and not review_created
        )
    elif source_review_file is not None:
        raise StagingError(
            "source review was provided without parser-input drift"
        )

    try:
        scan_root, summary, scan_created = _materialize_scan(
            flyer_root=flyer_root,
            observation_root=observation_root,
            meta=source_meta,
            source_pdf=selected.source_pdf,
            source_json=selected.source_json,
        )
    except Exception as exc:
        payload = _status_payload(
            result="BLOCKED_PARSER_DRIFT",
            reason=f"authoritative_scan_failed:{type(exc).__name__}:{exc}",
            target=target,
            source=source_meta,
            staging={
                "flyer_key": flyer_key,
                "flyer_root": str(flyer_root),
                "observation_root": str(observation_root),
            },
        )
        _atomic_json(output_dir / "staging-status.json", payload)
        return payload

    review_profile_created = False
    review_profile_sha = ""
    review_profile_path = flyer_root / "review-profile.json"
    if review_profile_file is not None:
        _, review_profile_raw, review_profile_sha = _validate_review_profile(
            review_profile_file=review_profile_file,
            pdf_sha256=selected.pdf_sha256,
            page_count=selected.page_count,
        )
        review_profile_created = _write_bytes_once(
            review_profile_path,
            review_profile_raw,
        )

    staging_payload = dict(staging_before_scan)
    staging_payload["scan_root"] = str(scan_root)
    staging_payload["scan_created"] = scan_created
    staging_payload["review_profile_created"] = review_profile_created
    staging_payload["review_profile_path"] = (
        str(review_profile_path) if review_profile_path.is_file() else ""
    )
    staging_payload["review_profile_sha256"] = (
        review_profile_sha
        if review_profile_sha
        else (
            _sha256_file(review_profile_path)
            if review_profile_path.is_file()
            else ""
        )
    )
    staging_payload["reused"] = not any(
        (
            source_created,
            manifest_created,
            raw_created,
            observation_meta_created,
            scan_created,
            review_profile_created,
        )
    )

    try:
        profile = require_weekly_target_profile(
            flyer_root,
            page_count=selected.page_count,
        )
    except WeeklyTargetProfileGate as exc:
        payload = _status_payload(
            result=exc.result,
            reason=str(exc),
            target=target,
            source=source_meta,
            staging=staging_payload,
            scan=summary,
            source_review=source_review_payload,
        )
        _atomic_json(output_dir / "staging-status.json", payload)
        return payload

    payload = _status_payload(
        result="STAGED_SCAN_READY",
        reason="source_staged_scan_and_profile_ready_for_controlled_promotion",
        target=target,
        source=source_meta,
        staging=staging_payload,
        scan=summary,
        review_profile=profile,
        source_review=source_review_payload,
    )
    _atomic_json(output_dir / "staging-status.json", payload)
    return payload


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser()
    parser.add_argument("--discovery-dir", required=True, type=Path)
    parser.add_argument("--staging-root", required=True, type=Path)
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--target", choices=("current", "next"), default="next")
    parser.add_argument("--reference-corpus-root", type=Path)
    parser.add_argument("--source-review-file", type=Path)
    parser.add_argument("--review-profile-file", type=Path)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    try:
        payload = run_staging(
            discovery_dir=args.discovery_dir,
            staging_root=args.staging_root,
            output_dir=args.output_dir,
            target=args.target,
            reference_corpus_root=args.reference_corpus_root,
            source_review_file=args.source_review_file,
            review_profile_file=args.review_profile_file,
        )
    except StagingError as exc:
        payload = _status_payload(
            result="BLOCKED_SOURCE_DRIFT",
            reason=f"staging_integrity_failed:{exc}",
            target=args.target,
        )
        args.output_dir.mkdir(parents=True, exist_ok=True)
        _atomic_json(args.output_dir / "staging-status.json", payload)
    print(json.dumps(payload, ensure_ascii=False, sort_keys=True))
    print(f"RESULT={payload['result']}")
    return EXIT_CODES.get(str(payload["result"]), 1)


if __name__ == "__main__":
    raise SystemExit(main())
