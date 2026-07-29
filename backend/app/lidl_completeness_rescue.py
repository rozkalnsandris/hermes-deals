from __future__ import annotations

import hashlib
import json
import math
import re
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

RESCUE_SCHEMA_VERSION = 1
RESCUE_VERSION = "lidl-completeness-rescue-v1"
ALLOWED_EVIDENCE_KINDS = {"native_geometry", "targeted_ocr"}
ALLOWED_SCOPES = {"review", "in_scope"}
CANDIDATE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._:-]{0,119}$")


def _canonical(record: dict[str, Any]) -> str:
    material = {k: v for k, v in record.items() if k != "record_digest"}
    return json.dumps(
        material,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )


def record_digest(record: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical(record).encode("utf-8")).hexdigest()


def rescue_row_key(scan_name: str, record: dict[str, Any]) -> str:
    return f"{scan_name}:rescue:{record['candidate_key']}"


def _nonempty(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise ValueError(f"Completeness rescue requires {field}")
    return text


def _optional_money(value: Any, field: str) -> str | None:
    if value is None or value == "":
        return None
    try:
        amount = Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"Invalid {field}") from exc
    if not amount.is_finite() or amount <= 0:
        raise ValueError(f"{field} must be positive")
    return format(amount, "f")


def _bbox(value: Any) -> list[float]:
    if not isinstance(value, list) or len(value) != 4:
        raise ValueError("Completeness rescue bbox must contain four numbers")
    result = [float(x) for x in value]
    if not all(math.isfinite(x) for x in result):
        raise ValueError("Completeness rescue bbox must be finite")
    x0, y0, x1, y1 = result
    if x1 <= x0 or y1 <= y0 or min(result) < 0:
        raise ValueError("Completeness rescue bbox is invalid")
    return result


def _confidence(value: Any) -> float | None:
    if value in (None, ""):
        return None
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 1:
        raise ValueError("Completeness rescue confidence must be between 0 and 1")
    return result


def validate_record(
    raw: dict[str, Any],
    *,
    flyer_key: str,
    scan_name: str,
    parser_version: str,
    parser_sha256: str,
    raw_sha256: str,
    pdf_sha256: str,
    valid_pages: set[int],
) -> dict[str, Any]:
    if not isinstance(raw, dict):
        raise ValueError("Completeness rescue record must be a JSON object")
    record = dict(raw)

    if record.get("schema_version") != RESCUE_SCHEMA_VERSION:
        raise ValueError("Unexpected completeness rescue schema_version")
    candidate_key = _nonempty(record.get("candidate_key"), "candidate_key")
    if not CANDIDATE_KEY_RE.fullmatch(candidate_key):
        raise ValueError("Invalid completeness rescue candidate_key")

    expected_identity = {
        "flyer_key": flyer_key,
        "scan": scan_name,
        "parser_version": parser_version,
        "parser_sha256": parser_sha256,
        "source_raw_sha256": raw_sha256,
        "source_pdf_sha256": pdf_sha256,
    }
    for field, expected in expected_identity.items():
        if str(record.get(field) or "") != expected:
            raise ValueError(f"Completeness rescue identity mismatch: {field}")

    try:
        page = int(record.get("page"))
    except (TypeError, ValueError) as exc:
        raise ValueError("Completeness rescue page must be an integer") from exc
    if page not in valid_pages:
        raise ValueError("Completeness rescue page is outside the flyer")

    evidence_kind = _nonempty(record.get("evidence_kind"), "evidence_kind")
    if evidence_kind not in ALLOWED_EVIDENCE_KINDS:
        raise ValueError("Unsupported completeness rescue evidence_kind")

    if record.get("review_required") is not True:
        raise ValueError("Completeness rescue must be review_required=true")
    if record.get("production_ready") is True:
        raise ValueError("Completeness rescue may never be production_ready")

    channel = str(record.get("channel") or "physical_store").strip()
    if channel != "physical_store":
        raise ValueError("Completeness rescue only supports physical_store")

    scope = str(record.get("scope") or "review").strip()
    if scope not in ALLOWED_SCOPES:
        raise ValueError("Completeness rescue scope must be review or in_scope")

    product_name = _nonempty(record.get("product_name"), "product_name")
    evidence_text = _nonempty(record.get("evidence_text"), "evidence_text")

    app_price_eur = _optional_money(
        record.get("app_price_eur"), "app_price_eur"
    )
    requires_app_raw = record.get("requires_app", False)
    if not isinstance(requires_app_raw, bool):
        raise ValueError("Completeness rescue requires_app must be boolean")
    requires_app = requires_app_raw
    if app_price_eur is not None and not requires_app:
        raise ValueError(
            "Completeness rescue app_price_eur requires requires_app=true"
        )
    if requires_app and app_price_eur is None:
        raise ValueError(
            "Completeness rescue requires_app=true requires app_price_eur"
        )

    normalized = dict(record)
    normalized.update(
        {
            "candidate_key": candidate_key,
            "page": page,
            "evidence_kind": evidence_kind,
            "review_required": True,
            "production_ready": False,
            "channel": channel,
            "scope": scope,
            "product_name": product_name,
            "evidence_text": evidence_text,
            "bbox": _bbox(record.get("bbox")),
            "confidence": _confidence(record.get("confidence")),
            "package_text": (
                str(record.get("package_text")).strip()
                if record.get("package_text") not in (None, "")
                else None
            ),
            "price_eur": _optional_money(record.get("price_eur"), "price_eur"),
            "regular_price_eur": _optional_money(
                record.get("regular_price_eur"), "regular_price_eur"
            ),
            "app_price_eur": app_price_eur,
            "requires_app": requires_app,
        }
    )

    digest = record_digest(normalized)
    supplied = str(record.get("record_digest") or "").strip()
    if supplied and supplied != digest:
        raise ValueError("Completeness rescue record_digest mismatch")
    normalized["record_digest"] = digest
    return normalized


def load_rescue_artifact(
    path: Path,
    *,
    flyer_key: str,
    scan_name: str,
    parser_version: str,
    parser_sha256: str,
    raw_sha256: str,
    pdf_sha256: str,
    valid_pages: set[int],
    expected_count: int | None = None,
) -> list[dict[str, Any]]:
    if not path.exists():
        raise FileNotFoundError(path)

    result: list[dict[str, Any]] = []
    keys: set[str] = set()
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        if not line.strip():
            continue
        try:
            raw = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(
                f"Invalid completeness rescue JSON on line {line_no}"
            ) from exc
        record = validate_record(
            raw,
            flyer_key=flyer_key,
            scan_name=scan_name,
            parser_version=parser_version,
            parser_sha256=parser_sha256,
            raw_sha256=raw_sha256,
            pdf_sha256=pdf_sha256,
            valid_pages=valid_pages,
        )
        key = record["candidate_key"]
        if key in keys:
            raise ValueError(f"Duplicate completeness rescue candidate_key: {key}")
        keys.add(key)
        result.append(record)

    if expected_count is not None and len(result) != expected_count:
        raise ValueError(
            f"Completeness rescue count mismatch: expected {expected_count}, got {len(result)}"
        )
    return result


def rescue_reason_codes(record: dict[str, Any]) -> list[str]:
    reasons = ["completeness_rescue_requires_review"]
    if record["evidence_kind"] == "targeted_ocr":
        reasons.append("completeness_targeted_ocr")
    else:
        reasons.append("completeness_native_ownership_miss")
    if record.get("scope") == "review":
        reasons.append("scope_requires_review")
    if record.get("price_eur") in (None, ""):
        reasons.append("price_requires_review")
    return sorted(set(reasons))
