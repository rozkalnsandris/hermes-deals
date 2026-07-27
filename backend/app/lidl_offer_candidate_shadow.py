from __future__ import annotations

import hashlib
import json
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path
from typing import Any
from urllib.parse import urlencode
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError

from app.schemas import OfferCandidate, SourceChain

_PARSER_VERSION = "lidl-ocr-shadow-2b17"
_STRATEGY = "lidl_offer_candidate_contract_shadow_mapping"


def _resolve_source_report(precision_report_path: Path, source_value: str) -> Path:
    source = Path(source_value)
    if source.exists():
        return source
    fallback = precision_report_path.parent / source.name
    if fallback.exists():
        return fallback
    raise FileNotFoundError(f"Referenced full-grocery report not found: {source_value}")


def _parse_datetime(value: Any) -> datetime:
    if not value:
        return datetime.now(timezone.utc)
    parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed


def _parse_date(value: Any) -> date | None:
    if not value:
        return None
    return date.fromisoformat(str(value)[:10])


def _page_download_urls(full_report: dict[str, Any]) -> dict[int, str]:
    urls: dict[int, str] = {}
    for page in full_report.get("pages") or []:
        if not isinstance(page, dict) or not page.get("success"):
            continue
        number = int(page.get("page") or 0)
        download = page.get("download") if isinstance(page.get("download"), dict) else {}
        url = str(download.get("final_url") or download.get("url") or "").strip()
        if number > 0 and url:
            urls[number] = url
    return urls


def _schema_sha256() -> str:
    payload = json.dumps(
        OfferCandidate.model_json_schema(),
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return hashlib.sha256(payload).hexdigest()


def _shadow_snapshot_id(full_report: dict[str, Any]) -> UUID:
    material = "|".join(
        [
            "hermes-deals-lidl-shadow-snapshot",
            str(full_report.get("leaflet_key") or "unknown"),
            str(full_report.get("offer_start") or ""),
            str(full_report.get("offer_end") or ""),
            str(full_report.get("generated_at") or ""),
        ]
    )
    return uuid5(NAMESPACE_URL, material)


def _source_offer_id(leaflet_key: str, candidate: dict[str, Any]) -> str:
    material = json.dumps(
        {
            "leaflet_key": leaflet_key,
            "page": int(candidate.get("page") or 0),
            "product": str(candidate.get("product_name_clean") or candidate.get("product_name_raw") or ""),
            "price": candidate.get("ocr_price_eur"),
            "bbox": candidate.get("bbox"),
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    )
    digest = hashlib.sha256(material.encode("utf-8")).hexdigest()[:16]
    return f"lidl:{leaflet_key}:p{int(candidate.get('page') or 0)}:{digest}"


def _source_url(leaflet_key: str) -> str:
    return "https://endpoints.leaflets.schwarz/v4/flyer?" + urlencode(
        {"flyer_identifier": leaflet_key}
    )



def _shadow_price(candidate: dict[str, Any]) -> Any:
    tier = str(candidate.get("evidence_tier") or "")
    if tier != "math_corrected_verified":
        return candidate.get("ocr_price_eur")

    if candidate.get("corrected_price_verified") is not True:
        raise ValueError("Corrected strict-ready candidate is not explicitly verified")

    corrected = candidate.get("proposed_corrected_price_eur")
    expected = candidate.get("math_expected_price_eur")
    effective = candidate.get("effective_price_eur")

    if corrected is None or expected is None or effective is None:
        raise ValueError("Corrected strict-ready candidate is missing correction provenance")

    corrected_d = Decimal(str(corrected)).quantize(Decimal("0.01"))
    expected_d = Decimal(str(expected)).quantize(Decimal("0.01"))
    effective_d = Decimal(str(effective)).quantize(Decimal("0.01"))

    if corrected_d != expected_d or corrected_d != effective_d:
        raise ValueError("Corrected strict-ready candidate price does not match unit-price math")

    return corrected


def _raw_payload(candidate: dict[str, Any], *, precision_report_path: Path, shadow_snapshot_id: UUID) -> dict[str, Any]:
    return {
        "shadow_mapping": True,
        "db_write_eligible": False,
        "shadow_snapshot_id_is_synthetic": True,
        "shadow_snapshot_id": str(shadow_snapshot_id),
        "source_precision_report": str(precision_report_path),
        "page": int(candidate.get("page") or 0),
        "ocr_product_name_raw": (
            candidate.get("original_semantic_product_name_raw")
            or candidate.get("product_name_raw")
        ),
        "original_semantic_product_name_raw": candidate.get("original_semantic_product_name_raw"),
        "recovered_product_name": candidate.get("recovered_product_name"),
        "product_name_recovery_reason": candidate.get("product_name_recovery_reason"),
        "product_name_recovery_psm_modes": candidate.get("product_name_recovery_psm_modes") or [],
        "product_name_clean": candidate.get("product_name_clean"),
        "ocr_price_eur": candidate.get("ocr_price_eur"),
        "math_expected_price_eur": candidate.get("math_expected_price_eur"),
        "proposed_corrected_price_eur": candidate.get("proposed_corrected_price_eur"),
        "effective_price_eur": _shadow_price(candidate),
        "corrected_price_verified": candidate.get("corrected_price_verified") is True,
        "evidence_tier": candidate.get("evidence_tier"),
        "precision_disposition": candidate.get("precision_disposition"),
        "strict_disposition": candidate.get("strict_disposition"),
        "strict_reasons": candidate.get("strict_reasons") or [],
        "psm_modes": candidate.get("psm_modes") or [],
        "psm_support": candidate.get("psm_support"),
        "semantic_score": candidate.get("semantic_score"),
        "keyword_overlap": candidate.get("keyword_overlap") or [],
        "bbox": candidate.get("bbox"),
    }


def _candidate_to_offer(
    candidate: dict[str, Any],
    *,
    leaflet_key: str,
    full_report: dict[str, Any],
    precision_report_path: Path,
    page_urls: dict[int, str],
    shadow_snapshot_id: UUID,
) -> OfferCandidate:
    page = int(candidate.get("page") or 0)
    product_name = str(candidate.get("product_name_clean") or candidate.get("product_name_raw") or "").strip()
    if not product_name:
        raise ValueError("Strict-ready candidate has no product name")

    price = _shadow_price(candidate)
    if price is None:
        raise ValueError("Strict-ready candidate has no effective price")

    unit_price = candidate.get("unit_price")
    unit_kind = str(candidate.get("unit_kind") or "").strip() or None
    package_text = str(candidate.get("package_text") or "").strip() or None

    return OfferCandidate(
        source_chain=SourceChain.LIDL,
        source_store_external_id=None,
        source_store_name="Lidl",
        source_offer_id=_source_offer_id(leaflet_key, candidate),
        product_name_raw=product_name,
        brand_raw=None,
        description_raw=None,
        package_text_raw=package_text,
        price_eur=Decimal(str(price)),
        regular_price_eur=None,
        unit_price_eur=Decimal(str(unit_price)) if unit_price is not None else None,
        unit_label=unit_kind,
        discount_percent=None,
        app_price_eur=None,
        requires_app=False,
        coupon_required=False,
        valid_from=_parse_date(full_report.get("offer_start")),
        valid_until=_parse_date(full_report.get("offer_end")),
        source_url=_source_url(leaflet_key),
        source_image_url=page_urls.get(page),
        snapshot_id=shadow_snapshot_id,
        collected_at=_parse_datetime(full_report.get("generated_at")),
        parser_version=_PARSER_VERSION,
        raw_payload=_raw_payload(
            candidate,
            precision_report_path=precision_report_path,
            shadow_snapshot_id=shadow_snapshot_id,
        ),
    )


def map_strict_ready_offer_candidates(*, precision_report_path: Path, output_dir: Path) -> dict[str, Any]:
    precision = json.loads(precision_report_path.read_text(encoding="utf-8"))
    if precision.get("strategy") != "lidl_full_grocery_candidate_precision_audit":
        raise ValueError("Input is not a Lidl candidate precision audit")
    if precision.get("db_write_performed") is not False:
        raise ValueError("Shadow mapping only accepts non-writing precision reports")

    source_report_value = str(precision.get("source_report") or "").strip()
    if not source_report_value:
        raise ValueError("Precision report does not reference the full-grocery source report")
    full_report_path = _resolve_source_report(precision_report_path, source_report_value)
    full_report = json.loads(full_report_path.read_text(encoding="utf-8"))
    if full_report.get("strategy") != "full_grocery_ocr_dry_run":
        raise ValueError("Referenced source is not a full-grocery dry-run report")
    if full_report.get("db_write_performed") is not False:
        raise ValueError("Referenced full-grocery report is not non-writing")

    leaflet_key = str(full_report.get("leaflet_key") or precision.get("source_leaflet_key") or "").strip()
    if not leaflet_key:
        raise ValueError("Lidl leaflet key is missing")

    strict_ready = [
        c
        for c in (precision.get("candidates") or [])
        if isinstance(c, dict) and c.get("strict_disposition") == "strict_ready"
    ]
    page_urls = _page_download_urls(full_report)
    shadow_snapshot_id = _shadow_snapshot_id(full_report)

    mapped: list[dict[str, Any]] = []
    errors: list[dict[str, Any]] = []
    for candidate in strict_ready:
        try:
            offer = _candidate_to_offer(
                candidate,
                leaflet_key=leaflet_key,
                full_report=full_report,
                precision_report_path=precision_report_path,
                page_urls=page_urls,
                shadow_snapshot_id=shadow_snapshot_id,
            )
            mapped.append(
                {
                    "page": int(candidate.get("page") or 0),
                    "strict_evidence_tier": candidate.get("evidence_tier"),
                    "db_write_eligible": False,
                    "offer_candidate": offer.model_dump(mode="json"),
                }
            )
        except (ValidationError, ValueError, TypeError) as exc:
            errors.append(
                {
                    "page": int(candidate.get("page") or 0),
                    "product_name": candidate.get("product_name_clean") or candidate.get("product_name_raw"),
                    "error": f"{type(exc).__name__}: {exc}",
                }
            )

    source_ids = [entry["offer_candidate"]["source_offer_id"] for entry in mapped]
    report: dict[str, Any] = {
        "schema_version": 1,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "strategy": _STRATEGY,
        "db_write_performed": False,
        "source_precision_report": str(precision_report_path),
        "source_full_grocery_report": str(full_report_path),
        "source_leaflet_key": leaflet_key,
        "source_offer_start": full_report.get("offer_start"),
        "source_offer_end": full_report.get("offer_end"),
        "source_strict_ready_total": len(strict_ready),
        "mapped_offer_candidate_total": len(mapped),
        "validation_error_total": len(errors),
        "shadow_snapshot_id": str(shadow_snapshot_id),
        "shadow_snapshot_id_is_synthetic": True,
        "offer_candidate_schema_sha256": _schema_sha256(),
        "mapped_candidates": mapped,
        "validation_errors": errors,
        "gate": {
            "source_precision_nonwriting": precision.get("db_write_performed") is False,
            "source_full_grocery_nonwriting": full_report.get("db_write_performed") is False,
            "only_strict_ready_mapped": len(strict_ready) == int(precision.get("strict_ready_total") or len(strict_ready)),
            "mapped_count_matches_strict_ready": len(mapped) == len(strict_ready),
            "no_validation_errors": not errors,
            "all_source_chain_lidl": all(
                entry["offer_candidate"].get("source_chain") == "lidl" for entry in mapped
            ),
            "all_shadow_nonwriting": all(entry.get("db_write_eligible") is False for entry in mapped),
            "source_offer_ids_unique": len(source_ids) == len(set(source_ids)),
            "all_source_image_provenance_present": all(
                bool(entry["offer_candidate"].get("source_image_url")) for entry in mapped
            ),
            "all_validity_dates_present": all(
                bool(entry["offer_candidate"].get("valid_from"))
                and bool(entry["offer_candidate"].get("valid_until"))
                for entry in mapped
            ),
            "all_snapshot_ids_match_shadow": all(
                entry["offer_candidate"].get("snapshot_id") == str(shadow_snapshot_id) for entry in mapped
            ),
            # Legacy key retained for report compatibility. It now means each
            # shadow price matches its evidence-backed effective value.
            "no_corrected_price_persisted": all(
                entry["offer_candidate"].get("price_eur")
                == str(
                    _shadow_price(
                        next(
                            c
                            for c in strict_ready
                            if _source_offer_id(leaflet_key, c)
                            == entry["offer_candidate"].get("source_offer_id")
                        )
                    )
                )
                for entry in mapped
            ),
            "all_corrected_price_provenance_preserved": all(
                c.get("evidence_tier") != "math_corrected_verified"
                or (
                    c.get("corrected_price_verified") is True
                    and c.get("proposed_corrected_price_eur") is not None
                    and c.get("math_expected_price_eur") is not None
                    and c.get("effective_price_eur") == c.get("proposed_corrected_price_eur")
                )
                for c in strict_ready
            ),
        },
    }

    gates_ok = all(report["gate"].values())
    if gates_ok and len(mapped) >= 4:
        recommendation = "lidl_offer_candidate_shadow_contract_valid"
    elif gates_ok and mapped:
        recommendation = "lidl_offer_candidate_shadow_small_subset"
    else:
        recommendation = "lidl_offer_candidate_shadow_fix_required"
    report["recommendation"] = recommendation

    output_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    report_path = output_dir / f"{stamp}-lidl-offer-candidate-shadow.json"
    report["report_path"] = str(report_path)
    report_path.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")
    return report
