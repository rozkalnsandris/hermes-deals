from __future__ import annotations

from decimal import Decimal
from hashlib import sha256
import json
from typing import Any, Iterable, Mapping

from netto_shadow_promotion import (
    AUDITED_FIELDS,
    AuditRow,
    evaluate_corpus as _evaluate_corpus,
)


DEFAULT_MINIMUM_CAMPAIGNS_PER_FIELD = 2


def _validate_thresholds(
    values: Mapping[str, Decimal | str | float] | None,
    label: str,
) -> None:
    if not values:
        return
    for field, value in values.items():
        if field not in AUDITED_FIELDS:
            raise ValueError(f"unsupported {label} threshold field: {field}")
        threshold = Decimal(str(value))
        if threshold < 0 or threshold > 1:
            raise ValueError(f"{label} threshold for {field} must be between 0 and 1")


def _normalized_row(row: AuditRow) -> dict[str, Any]:
    return {
        "campaign_id": row.campaign_id,
        "field": row.field,
        "expected": row.expected,
        "predicted": row.predicted,
        "classification": row.classification.value,
        "page_number": row.page_number,
        "card_id": row.card_id,
        "manifest_sha256": row.manifest_sha256,
        "pdf_sha256": row.pdf_sha256,
        "parser_identity": row.parser_identity,
        "store_external_id": row.store_external_id,
        "scope": row.scope,
    }


def _corpus_identity(rows: list[AuditRow]) -> str:
    normalized = [_normalized_row(row) for row in rows]
    normalized.sort(
        key=lambda row: (
            row["campaign_id"],
            row["field"],
            row["page_number"],
            row["card_id"],
            json.dumps(row["expected"], sort_keys=True),
            json.dumps(row["predicted"], sort_keys=True),
        )
    )
    return sha256(
        json.dumps(
            normalized,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def evaluate_corpus(
    rows: Iterable[AuditRow | Mapping[str, Any]],
    *,
    thresholds: Mapping[str, Decimal | str | float] | None = None,
    coverage_thresholds: Mapping[str, Decimal | str | float] | None = None,
    minimum_samples: int = 25,
    require_multiple_campaigns: bool = True,
    minimum_campaigns_per_field: int = DEFAULT_MINIMUM_CAMPAIGNS_PER_FIELD,
) -> dict[str, Any]:
    if minimum_campaigns_per_field < 1:
        raise ValueError("minimum_campaigns_per_field must be positive")
    _validate_thresholds(thresholds, "precision")
    _validate_thresholds(coverage_thresholds, "coverage")

    parsed = [
        row if isinstance(row, AuditRow) else AuditRow.from_mapping(row)
        for row in rows
    ]
    report = _evaluate_corpus(
        parsed,
        thresholds=thresholds,
        coverage_thresholds=coverage_thresholds,
        minimum_samples=minimum_samples,
        require_multiple_campaigns=require_multiple_campaigns,
    )

    for field in AUDITED_FIELDS:
        metrics = report["fields"][field]
        campaign_ids = sorted(
            {row.campaign_id for row in parsed if row.field == field}
        )
        metrics["campaign_ids"] = campaign_ids
        metrics["campaign_count"] = len(campaign_ids)
        metrics["minimum_campaigns"] = minimum_campaigns_per_field
        if len(campaign_ids) < minimum_campaigns_per_field:
            metrics["promoted"] = False
            metrics["route"] = "review_required"

    report["minimum_campaigns_per_field"] = minimum_campaigns_per_field
    report["corpus_row_count"] = len(parsed)
    report["corpus_sha256"] = _corpus_identity(parsed)
    report["parser_identities"] = sorted({row.parser_identity for row in parsed})
    report["manifest_sha256s"] = sorted({row.manifest_sha256 for row in parsed})
    report["pdf_sha256s"] = sorted({row.pdf_sha256 for row in parsed})
    return report
