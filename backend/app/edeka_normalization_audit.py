from __future__ import annotations

import argparse
from collections import Counter
from datetime import datetime
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
import re
import sys
from typing import Any
from uuid import UUID

from app.edeka_store_offers import parse_edeka_store_offers_snapshot
from app.parsers.edeka import EdekaParserContext
from app.product_normalizer import NORMALIZER_VERSION, normalize_offer_fields
from app.schemas import OfferCandidate, SourceChain


AUDIT_SCHEMA_VERSION = 1
EXPECTED_SOURCE_URL = "https://www.edeka.de/maerkte/071897/angebote/"
EXPECTED_PUBLIC_MARKET_ID = "071897"
EXPECTED_INTERNAL_MARKET_ID = "587881"
EXPECTED_STORE_NAME = "EDEKA Patzer"
EXPECTED_SCOPE = "family_primary_edeka"
_SHA256_RE = re.compile(r"^[0-9a-f]{64}$")


def _stable_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return sha256(_stable_json_bytes(value)).hexdigest()


def _verified_manifest(
    manifest_path: Path,
    expected_sha256: str,
) -> dict[str, object]:
    if _SHA256_RE.fullmatch(expected_sha256) is None:
        raise ValueError("EDEKA normalization audit requires lowercase SHA-256")

    data = manifest_path.read_bytes()
    if sha256(data).hexdigest() != expected_sha256:
        raise ValueError("EDEKA normalization audit manifest SHA mismatch")

    payload = json.loads(data)
    if not isinstance(payload, dict):
        raise ValueError("EDEKA normalization audit manifest must be a JSON object")
    return payload


def _manifest_context(manifest: dict[str, object]) -> EdekaParserContext:
    expected = {
        "source_chain": "edeka",
        "scope": EXPECTED_SCOPE,
        "public_market_id": EXPECTED_PUBLIC_MARKET_ID,
        "internal_market_id": EXPECTED_INTERNAL_MARKET_ID,
        "store_name": EXPECTED_STORE_NAME,
        "source_url": EXPECTED_SOURCE_URL,
        "final_url": EXPECTED_SOURCE_URL,
    }
    for key, value in expected.items():
        if manifest.get(key) != value:
            raise ValueError(f"EDEKA normalization audit manifest {key} mismatch")

    try:
        snapshot_id = UUID(str(manifest["snapshot_id"]))
        collected_at = datetime.fromisoformat(str(manifest["collected_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "EDEKA normalization audit manifest identity is incomplete"
        ) from exc

    if collected_at.tzinfo is None or collected_at.utcoffset() is None:
        raise ValueError(
            "EDEKA normalization audit collected_at must be timezone-aware"
        )

    return EdekaParserContext(
        snapshot_id=snapshot_id,
        source_url=EXPECTED_SOURCE_URL,
        collected_at=collected_at,
        public_market_id=EXPECTED_PUBLIC_MARKET_ID,
        internal_market_id=EXPECTED_INTERNAL_MARKET_ID,
        store_name=EXPECTED_STORE_NAME,
    )


def _review_reasons(offer: OfferCandidate) -> list[str]:
    reasons: list[str] = []
    if offer.package_text_raw and offer.package_text_raw.strip():
        reasons.append("package_text_unresolved")
    if offer.source_image_url is not None:
        reasons.append("image_filename_unresolved")

    description = offer.raw_payload.get("description")
    if isinstance(description, str) and description.strip():
        reasons.append("description_unresolved")

    if not reasons:
        reasons.append("package_evidence_missing")
    return reasons


def _validate_offer_batch(offers: list[OfferCandidate]) -> dict[str, str]:
    if not offers:
        raise ValueError("EDEKA normalization audit requires at least one offer")

    snapshot_ids = {str(offer.snapshot_id) for offer in offers}
    source_urls = {str(offer.source_url) for offer in offers}
    collected_values = {offer.collected_at.isoformat() for offer in offers}
    parser_versions = {offer.parser_version for offer in offers}
    windows = {
        (
            offer.valid_from.isoformat() if offer.valid_from else None,
            offer.valid_until.isoformat() if offer.valid_until else None,
        )
        for offer in offers
    }

    if len(snapshot_ids) != 1:
        raise ValueError("EDEKA normalization audit requires one snapshot")
    if source_urls != {EXPECTED_SOURCE_URL}:
        raise ValueError("EDEKA normalization audit source URL mismatch")
    if len(collected_values) != 1:
        raise ValueError("EDEKA normalization audit collected_at mismatch")
    if len(parser_versions) != 1:
        raise ValueError("EDEKA normalization audit parser version mismatch")
    if len(windows) != 1 or None in next(iter(windows)):
        raise ValueError("EDEKA normalization audit validity window mismatch")

    source_offer_ids: list[str] = []
    for offer in offers:
        if offer.source_chain != SourceChain.EDEKA:
            raise ValueError("EDEKA normalization audit source chain mismatch")
        if offer.source_store_external_id != EXPECTED_PUBLIC_MARKET_ID:
            raise ValueError("EDEKA normalization audit public market mismatch")
        if offer.source_store_name != EXPECTED_STORE_NAME:
            raise ValueError("EDEKA normalization audit store name mismatch")
        source_offer_id = offer.source_offer_id
        if (
            not isinstance(source_offer_id, str)
            or not source_offer_id.strip()
            or source_offer_id != source_offer_id.strip()
        ):
            raise ValueError(
                "EDEKA normalization audit requires canonical source_offer_id"
            )
        source_offer_ids.append(source_offer_id)

    if len(set(source_offer_ids)) != len(source_offer_ids):
        raise ValueError("EDEKA normalization audit source_offer_id duplicate")

    valid_from, valid_until = next(iter(windows))
    return {
        "snapshot_id": next(iter(snapshot_ids)),
        "source_url": next(iter(source_urls)),
        "collected_at": next(iter(collected_values)),
        "parser_version": next(iter(parser_versions)),
        "valid_from": str(valid_from),
        "valid_until": str(valid_until),
    }


def _normalization_row(offer: OfferCandidate) -> dict[str, object]:
    source_offer_id = str(offer.source_offer_id)
    normalized = normalize_offer_fields(
        offer_candidate_id=f"{offer.snapshot_id}:{source_offer_id}",
        source_chain=offer.source_chain.value,
        source_store_external_id=offer.source_store_external_id,
        source_offer_id=source_offer_id,
        product_name_raw=offer.product_name_raw,
        brand_raw=offer.brand_raw,
        package_text_raw=offer.package_text_raw,
        raw_payload=offer.raw_payload,
        source_image_url=(
            str(offer.source_image_url)
            if offer.source_image_url is not None
            else None
        ),
    )

    signature = normalized.package_signature()
    resolved = normalized.package_parse_method is not None
    review_reasons = [] if resolved else _review_reasons(offer)

    return {
        "source_offer_id": source_offer_id,
        "product_name_raw": offer.product_name_raw,
        "normalized_name": normalized.normalized_name,
        "normalized_brand": normalized.normalized_brand,
        "price_eur": format(offer.price_eur, "f"),
        "package_signature": {
            "item_quantity_value": signature[0],
            "item_quantity_unit": signature[1],
            "pack_count": signature[2],
        },
        "package_parse_method": normalized.package_parse_method,
        "package_evidence_source": normalized.package_evidence_source,
        "package_evidence_text": normalized.package_evidence_text,
        "status": "resolved" if resolved else "review_required",
        "review_reasons": review_reasons,
    }


def build_edeka_normalization_report(
    offers: list[OfferCandidate],
    *,
    manifest_sha256: str,
) -> dict[str, object]:
    if _SHA256_RE.fullmatch(manifest_sha256) is None:
        raise ValueError("EDEKA normalization audit requires manifest SHA-256")

    source = _validate_offer_batch(offers)
    rows = sorted(
        (_normalization_row(offer) for offer in offers),
        key=lambda row: str(row["source_offer_id"]),
    )

    status_counts = Counter(str(row["status"]) for row in rows)
    method_counts = Counter(
        str(row["package_parse_method"] or "unresolved")
        for row in rows
    )
    evidence_source_counts = Counter(
        str(row["package_evidence_source"] or "none")
        for row in rows
    )
    review_reason_counts = Counter(
        reason
        for row in rows
        for reason in row["review_reasons"]
    )

    total = len(rows)
    resolved = status_counts.get("resolved", 0)
    resolved_percent = (
        Decimal(resolved) * Decimal("100") / Decimal(total)
    ).quantize(Decimal("0.01"))

    rows_sha256 = _sha256(rows)
    report: dict[str, object] = {
        "schema_version": AUDIT_SCHEMA_VERSION,
        "audit_type": "edeka_package_normalization_coverage",
        "normalizer_version": NORMALIZER_VERSION,
        "manifest_sha256": manifest_sha256,
        "source": {
            **source,
            "source_chain": "edeka",
            "scope": EXPECTED_SCOPE,
            "public_market_id": EXPECTED_PUBLIC_MARKET_ID,
            "internal_market_id": EXPECTED_INTERNAL_MARKET_ID,
            "store_name": EXPECTED_STORE_NAME,
        },
        "summary": {
            "offer_count": total,
            "resolved_count": resolved,
            "review_required_count": status_counts.get(
                "review_required",
                0,
            ),
            "resolved_percent": format(resolved_percent, "f"),
            "status_counts": dict(sorted(status_counts.items())),
            "package_method_counts": dict(sorted(method_counts.items())),
            "evidence_source_counts": dict(
                sorted(evidence_source_counts.items())
            ),
            "review_reason_counts": dict(
                sorted(review_reason_counts.items())
            ),
            "rows_sha256": rows_sha256,
        },
        "rows": rows,
    }
    report["report_sha256"] = _sha256(report)
    return report


def audit_edeka_manifest(
    manifest_path: Path,
    expected_sha256: str,
) -> dict[str, object]:
    manifest = _verified_manifest(manifest_path, expected_sha256)
    context = _manifest_context(manifest)
    offers = parse_edeka_store_offers_snapshot(
        manifest_path,
        expected_sha256,
        context,
    )
    return build_edeka_normalization_report(
        offers,
        manifest_sha256=expected_sha256,
    )


def write_deterministic_report(
    output_path: Path,
    report: dict[str, object],
) -> None:
    data = _stable_json_bytes(report) + b"\n"
    output_path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output_path.open("xb") as handle:
            handle.write(data)
    except FileExistsError:
        if output_path.read_bytes() != data:
            raise ValueError(
                "Refusing to replace a different EDEKA normalization report"
            )


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Audit immutable EDEKA package normalization coverage"
    )
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--sha256", required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    try:
        report = audit_edeka_manifest(args.manifest, args.sha256)
        write_deterministic_report(args.output, report)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1

    print(
        json.dumps(
            {
                "result": "pass",
                "output": str(args.output),
                "report_sha256": report["report_sha256"],
                "summary": report["summary"],
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
