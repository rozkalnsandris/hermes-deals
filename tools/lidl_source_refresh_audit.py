#!/usr/bin/env python3
from __future__ import annotations

import argparse
from dataclasses import dataclass
from datetime import date
from hashlib import sha256
import json
import os
from pathlib import Path
import re
import stat
from typing import Any, Mapping
from urllib.parse import urlencode, urlsplit
from urllib.request import Request, urlopen


AUDIT_VERSION = "lidl-source-refresh-audit-v1"
FLYER_API_URL = "https://endpoints.leaflets.schwarz/v4/flyer"
EXPECTED_FAMILY = (
    "aktionsprospekt-03-08-2026-08-08-2026-b1cf3b--src-6da2135ea984"
)
EXPECTED_FLYER_IDENTIFIER = "aktionsprospekt-03-08-2026-08-08-2026-b1cf3b"
EXPECTED_ROUTE_REGION = "21"
EXPECTED_VALID_FROM = "2026-08-03"
EXPECTED_VALID_UNTIL = "2026-08-08"
EXPECTED_OFFICIAL_FLYER_ID = "019fa95c-4c2d-704c-a2ad-cfe2c622c4e8"
EXPECTED_PAGE_COUNT = 69
EXPECTED_PDF_SHA256 = (
    "6da2135ea984d1f79bdb311dfa0d8affd1d2f8d46c63a1bba25b202a30a5fb16"
)
EXPECTED_FROZEN_RAW_SHA256 = (
    "d1af2062f10f5fd25d4ac197fe74459bf0c313d7f5890f5d96c3db9572b7ddf1"
)
EXPECTED_STABLE_SOURCE_IDENTITY_SHA256 = (
    "7486e32f837869b3dedc36b5a129c034129f653bf698df4ad55649510623ff17"
)
EXPECTED_FROZEN_PARSER_INPUT_SHA256 = (
    "8d63c989fd1897215f9556942aec16636ce7c0e5a8bb05b5a672693f58519c5a"
)


class SourceRefreshAuditError(RuntimeError):
    pass


@dataclass(frozen=True)
class ProductBinding:
    page: int
    product_id: str
    title: str
    bbox: tuple[float, float, float, float]


def _sha256_bytes(data: bytes) -> str:
    return sha256(data).hexdigest()


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _canonical_json_bytes(payload: Mapping[str, Any]) -> bytes:
    return (
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def _canonical_digest(payload: Mapping[str, Any]) -> str:
    return sha256(_canonical_json_bytes(payload).rstrip(b"\n")).hexdigest()


def _load_object(data: bytes, *, label: str) -> dict[str, Any]:
    try:
        payload = json.loads(data)
    except (UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise SourceRefreshAuditError(f"{label} is invalid JSON") from exc
    if not isinstance(payload, Mapping):
        raise SourceRefreshAuditError(f"{label} root must be an object")
    return dict(payload)


def stable_source_identity(source_json: bytes) -> dict[str, Any]:
    payload = _load_object(source_json, label="source JSON")
    flyer = payload.get("flyer")
    if not isinstance(flyer, Mapping):
        raise SourceRefreshAuditError("source JSON flyer object is missing")
    pages = flyer.get("pages") or []
    if not isinstance(pages, list):
        raise SourceRefreshAuditError("source JSON pages must be a list")
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
    for key in (
        "official_flyer_id",
        "viewer_path",
        "document_path",
        "valid_from",
        "valid_until",
    ):
        if not identity[key]:
            raise SourceRefreshAuditError(f"stable identity field missing: {key}")
    return identity


def parser_input_identity(source_json: bytes) -> str:
    payload = _load_object(source_json, label="source JSON")
    payload.pop("dateTime", None)
    payload.pop("warnings", None)
    return _canonical_digest(payload)


def _normalized_fraction(value: Any) -> float:
    number = float(value)
    if number > 1.0:
        number /= 100.0
    return number


def product_bindings(source_json: bytes) -> tuple[ProductBinding, ...]:
    payload = _load_object(source_json, label="source JSON")
    flyer = payload.get("flyer")
    if not isinstance(flyer, Mapping):
        raise SourceRefreshAuditError("source JSON flyer object is missing")
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


def product_binding_projection(source_json: bytes) -> list[dict[str, Any]]:
    return [
        {
            "page": row.page,
            "product_id": row.product_id,
            "title": row.title,
            "bbox": list(row.bbox),
        }
        for row in product_bindings(source_json)
    ]


def product_binding_digest(source_json: bytes) -> str:
    encoded = json.dumps(
        product_binding_projection(source_json),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def binding_change_summary(reference: bytes, live: bytes) -> dict[str, int]:
    def keyed(source_json: bytes) -> dict[tuple[Any, ...], ProductBinding]:
        return {
            (row.page, row.product_id, row.bbox): row
            for row in product_bindings(source_json)
        }

    old = keyed(reference)
    new = keyed(live)
    old_keys = set(old)
    new_keys = set(new)
    common = old_keys & new_keys
    return {
        "binding_added": len(new_keys - old_keys),
        "binding_removed": len(old_keys - new_keys),
        "binding_title_changed": sum(old[key].title != new[key].title for key in common),
    }


def product_link_count(source_json: bytes) -> int:
    payload = _load_object(source_json, label="source JSON")
    flyer = payload.get("flyer")
    if not isinstance(flyer, Mapping):
        return 0
    count = 0
    for page in flyer.get("pages") or []:
        if not isinstance(page, Mapping):
            continue
        for link in page.get("links") or []:
            if not isinstance(link, Mapping):
                continue
            if (
                str(link.get("displayType") or "").casefold() == "product"
                or isinstance(link.get("productDetails"), Mapping)
            ):
                count += 1
    return count


def _validate_expected_identity(source_json: bytes, *, label: str) -> dict[str, Any]:
    identity = stable_source_identity(source_json)
    digest = _canonical_digest(identity)
    if digest != EXPECTED_STABLE_SOURCE_IDENTITY_SHA256:
        raise SourceRefreshAuditError(f"{label} stable source identity mismatch")
    if identity["official_flyer_id"] != EXPECTED_OFFICIAL_FLYER_ID:
        raise SourceRefreshAuditError(f"{label} official flyer ID mismatch")
    if identity["valid_from"] != EXPECTED_VALID_FROM:
        raise SourceRefreshAuditError(f"{label} valid-from mismatch")
    if identity["valid_until"] != EXPECTED_VALID_UNTIL:
        raise SourceRefreshAuditError(f"{label} valid-until mismatch")
    if identity["page_count"] != EXPECTED_PAGE_COUNT:
        raise SourceRefreshAuditError(f"{label} page count mismatch")
    if not identity["viewer_path"].endswith(f"/{EXPECTED_FLYER_IDENTIFIER}/ar/{EXPECTED_ROUTE_REGION}"):
        raise SourceRefreshAuditError(f"{label} viewer path mismatch")
    return identity


def _fetch_live_source() -> tuple[bytes, str]:
    query = urlencode(
        {
            "version": "4",
            "flyer_identifier": EXPECTED_FLYER_IDENTIFIER,
            "client": "lidl",
            "region_id": EXPECTED_ROUTE_REGION,
        }
    )
    request = Request(
        f"{FLYER_API_URL}?{query}",
        headers={
            "User-Agent": "HermesDeals-LidlSourceRefreshAudit/1.0",
            "Accept": "application/json",
            "Accept-Language": "de-DE,de;q=0.9,en;q=0.4",
        },
    )
    with urlopen(request, timeout=45) as response:
        if response.status != 200:
            raise SourceRefreshAuditError(f"Schwarz source HTTP status {response.status}")
        live_json = response.read(16 * 1024 * 1024 + 1)
    if len(live_json) > 16 * 1024 * 1024:
        raise SourceRefreshAuditError("live source JSON exceeds size limit")

    payload = _load_object(live_json, label="live source JSON")
    flyer = payload.get("flyer")
    if not isinstance(flyer, Mapping):
        raise SourceRefreshAuditError("live source flyer object is missing")
    document_url = str(flyer.get("hiResPdfUrl") or flyer.get("pdfUrl") or "")
    parsed = urlsplit(document_url)
    if parsed.scheme != "https" or not parsed.hostname or not parsed.hostname.endswith(".schwarz"):
        raise SourceRefreshAuditError("live PDF host is outside the Schwarz allowlist")

    pdf_request = Request(
        document_url,
        headers={"User-Agent": "HermesDeals-LidlSourceRefreshAudit/1.0"},
    )
    digest = sha256()
    total = 0
    with urlopen(pdf_request, timeout=90) as response:
        if response.status != 200:
            raise SourceRefreshAuditError(f"live PDF HTTP status {response.status}")
        while True:
            chunk = response.read(1024 * 1024)
            if not chunk:
                break
            total += len(chunk)
            if total > 128 * 1024 * 1024:
                raise SourceRefreshAuditError("live PDF exceeds size limit")
            digest.update(chunk)
    return live_json, digest.hexdigest()


def build_review_template(
    *,
    frozen_parser_input: str,
    frozen_binding_sha: str,
    frozen_binding_count: int,
    live_parser_input: str,
    live_binding_sha: str,
    live_binding_count: int,
    changes: Mapping[str, int],
) -> dict[str, Any]:
    return {
        "schema_version": 1,
        "decision": "PENDING_OWNER_REVIEW",
        "scope": "authoritative_staging_scan_only",
        "approved_by": "",
        "approved_at": "",
        "note": "",
        "flyer_key": EXPECTED_FAMILY,
        "pdf_sha256": EXPECTED_PDF_SHA256,
        "reference_input": {
            "parser_input_identity_sha256": frozen_parser_input,
            "product_binding_sha256": frozen_binding_sha,
            "product_binding_count": frozen_binding_count,
        },
        "approved_live_input": {
            "parser_input_identity_sha256": live_parser_input,
            "product_binding_sha256": live_binding_sha,
            "product_binding_count": live_binding_count,
        },
        "observed_changes": dict(changes),
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


def compare_sources(*, frozen_source_json: bytes, live_source_json: bytes) -> tuple[dict[str, Any], dict[str, Any]]:
    frozen_identity = _validate_expected_identity(frozen_source_json, label="frozen")
    live_identity = _validate_expected_identity(live_source_json, label="live")
    if frozen_identity != live_identity:
        raise SourceRefreshAuditError("live stable identity differs from frozen rev05")

    frozen_raw_sha = _sha256_bytes(frozen_source_json)
    if frozen_raw_sha != EXPECTED_FROZEN_RAW_SHA256:
        raise SourceRefreshAuditError("frozen rev05 source JSON SHA mismatch")
    frozen_parser_input = parser_input_identity(frozen_source_json)
    if frozen_parser_input != EXPECTED_FROZEN_PARSER_INPUT_SHA256:
        raise SourceRefreshAuditError("frozen rev05 parser-input identity mismatch")

    live_raw_sha = _sha256_bytes(live_source_json)
    live_parser_input = parser_input_identity(live_source_json)
    frozen_binding_sha = product_binding_digest(frozen_source_json)
    live_binding_sha = product_binding_digest(live_source_json)
    frozen_binding_count = len(product_bindings(frozen_source_json))
    live_binding_count = len(product_bindings(live_source_json))
    changes = binding_change_summary(frozen_source_json, live_source_json)

    result = (
        "NO_SEMANTIC_REFRESH"
        if live_parser_input == frozen_parser_input
        else "SOURCE_REFRESH_REVIEW_REQUIRED"
    )
    template = build_review_template(
        frozen_parser_input=frozen_parser_input,
        frozen_binding_sha=frozen_binding_sha,
        frozen_binding_count=frozen_binding_count,
        live_parser_input=live_parser_input,
        live_binding_sha=live_binding_sha,
        live_binding_count=live_binding_count,
        changes=changes,
    )
    summary = {
        "schema_version": 1,
        "audit_version": AUDIT_VERSION,
        "result": result,
        "reason": (
            "parser_input_identity_changed_for_existing_pdf"
            if result == "SOURCE_REFRESH_REVIEW_REQUIRED"
            else "canonical_parser_input_unchanged"
        ),
        "family": EXPECTED_FAMILY,
        "flyer_identifier": EXPECTED_FLYER_IDENTIFIER,
        "route_region": EXPECTED_ROUTE_REGION,
        "valid_from": EXPECTED_VALID_FROM,
        "valid_until": EXPECTED_VALID_UNTIL,
        "official_flyer_id": EXPECTED_OFFICIAL_FLYER_ID,
        "page_count": EXPECTED_PAGE_COUNT,
        "pdf_sha256": EXPECTED_PDF_SHA256,
        "stable_source_identity_sha256": EXPECTED_STABLE_SOURCE_IDENTITY_SHA256,
        "reference_input": {
            "raw_sha256": frozen_raw_sha,
            "parser_input_identity_sha256": frozen_parser_input,
            "product_binding_sha256": frozen_binding_sha,
            "product_binding_count": frozen_binding_count,
            "product_link_count": product_link_count(frozen_source_json),
        },
        "live_input": {
            "raw_sha256": live_raw_sha,
            "parser_input_identity_sha256": live_parser_input,
            "product_binding_sha256": live_binding_sha,
            "product_binding_count": live_binding_count,
            "product_link_count": product_link_count(live_source_json),
        },
        "observed_changes": changes,
        "review_template_sha256": _sha256_bytes(_canonical_json_bytes(template)),
        "safety": {
            "raw_source_exported": False,
            "corpus_write": False,
            "parser_scan": False,
            "database_write": False,
            "review_write": False,
            "production_publish": False,
            "production_deploy": False,
            "systemd_change": False,
            "automatic_retry": False,
            "gate_c_d_authorized": False,
        },
    }
    return summary, template


def _write_json_once(path: Path, payload: Mapping[str, Any]) -> None:
    data = json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with path.open("x", encoding="utf-8") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.chmod(path, 0o600)


def run_audit(*, frozen_family: Path, as_of: str, output_dir: Path) -> dict[str, Any]:
    try:
        parsed_date = date.fromisoformat(as_of)
    except ValueError as exc:
        raise SourceRefreshAuditError("as_of is not a valid date") from exc
    if parsed_date.isoformat() != as_of:
        raise SourceRefreshAuditError("as_of is not canonical YYYY-MM-DD")
    if not (date.fromisoformat(EXPECTED_VALID_FROM) <= parsed_date <= date.fromisoformat(EXPECTED_VALID_UNTIL)):
        raise SourceRefreshAuditError("as_of is outside the exact flyer validity window")

    frozen_family = frozen_family.resolve()
    if frozen_family.name != EXPECTED_FAMILY:
        raise SourceRefreshAuditError("frozen family path is not the exact rev05 sibling")
    if not frozen_family.is_dir() or frozen_family.is_symlink():
        raise SourceRefreshAuditError("frozen rev05 family is missing or unsafe")
    source_pdf = frozen_family / "source.pdf"
    source_json = frozen_family / "source.json"
    receipt = frozen_family / "gate-b-freeze-receipt.json"
    meta = frozen_family / "discovery-meta.json"
    if {row.name for row in frozen_family.iterdir()} != {
        "source.pdf",
        "source.json",
        "gate-b-freeze-receipt.json",
        "discovery-meta.json",
    }:
        raise SourceRefreshAuditError("frozen rev05 file set mismatch")
    for path in (source_pdf, source_json, receipt, meta):
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or path.is_symlink():
            raise SourceRefreshAuditError(f"unsafe frozen rev05 member: {path.name}")
        if stat.S_IMODE(info.st_mode) != 0o600:
            raise SourceRefreshAuditError(f"frozen rev05 member mode mismatch: {path.name}")
    if _sha256_file(source_pdf) != EXPECTED_PDF_SHA256:
        raise SourceRefreshAuditError("frozen rev05 PDF SHA mismatch")

    frozen_json = source_json.read_bytes()
    live_json, live_pdf_sha = _fetch_live_source()
    if live_pdf_sha != EXPECTED_PDF_SHA256:
        raise SourceRefreshAuditError("live PDF differs from the frozen rev05 PDF")
    summary, template = compare_sources(
        frozen_source_json=frozen_json,
        live_source_json=live_json,
    )
    summary["as_of"] = as_of

    output_dir = output_dir.resolve()
    if output_dir.exists():
        if not output_dir.is_dir() or output_dir.is_symlink() or any(output_dir.iterdir()):
            raise SourceRefreshAuditError("output directory must be an empty safe directory")
    else:
        output_dir.mkdir(mode=0o700, parents=False)
    _write_json_once(output_dir / "source-refresh-summary.json", summary)
    _write_json_once(output_dir / "source-review-template.json", template)

    files = {}
    for path in sorted(output_dir.iterdir()):
        files[path.name] = {
            "bytes": path.stat().st_size,
            "sha256": _sha256_file(path),
        }
    manifest = {
        "schema_version": 1,
        "audit": "lidl-source-refresh",
        "audit_version": AUDIT_VERSION,
        "result": summary["result"],
        "sanitization_passed": True,
        "raw_source_exported": False,
        "files": files,
        "safety": summary["safety"],
    }
    _write_json_once(output_dir / "audit-manifest.json", manifest)
    return summary


def main() -> int:
    parser = argparse.ArgumentParser(description="Read-only Lidl rev05 same-PDF source-refresh audit")
    parser.add_argument("--frozen-family", type=Path, required=True)
    parser.add_argument("--as-of", required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    args = parser.parse_args()
    try:
        result = run_audit(
            frozen_family=args.frozen_family,
            as_of=args.as_of,
            output_dir=args.output_dir,
        )
    except SourceRefreshAuditError as exc:
        print(f"BLOCKED: {exc}")
        return 30
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
