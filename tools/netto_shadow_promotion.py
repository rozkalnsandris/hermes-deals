from __future__ import annotations

from dataclasses import asdict, dataclass
from datetime import date
from decimal import Decimal, InvalidOperation
from enum import StrEnum
import re
from typing import Any, Iterable, Mapping


FAMILY_PRIMARY_STORE_ID = "5659"
FAMILY_PRIMARY_SCOPE = "family_primary_netto"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
AUDITED_FIELDS = (
    "title",
    "brand",
    "package",
    "price",
    "validity",
    "card_ownership",
)
DEFAULT_PRECISION_THRESHOLDS = {
    "title": Decimal("0.90"),
    "brand": Decimal("0.95"),
    "package": Decimal("0.90"),
    "price": Decimal("0.99"),
    "validity": Decimal("1.00"),
    "card_ownership": Decimal("0.99"),
}
DEFAULT_COVERAGE_THRESHOLDS = {
    "title": Decimal("0.90"),
    "brand": Decimal("0.90"),
    "package": Decimal("0.90"),
    "price": Decimal("0.99"),
    "validity": Decimal("0.99"),
    "card_ownership": Decimal("0.99"),
}
DEFAULT_MINIMUM_SAMPLES = 25


class Classification(StrEnum):
    MATCH = "match"
    PARSER_DEFECT = "parser_defect"
    AMBIGUOUS_SOURCE = "ambiguous_source"
    TRUTH_PACK_CORRECTION = "truth_pack_correction"


class EvidenceStatus(StrEnum):
    PDF_BOUND = "pdf_bound"
    VERIFIED_NO_PDF = "verified_no_pdf"
    MISSING = "missing"
    CORRUPT = "corrupt"


@dataclass(frozen=True)
class EvidenceBinding:
    manifest_path: str
    manifest_sha256: str
    html_sha256: str
    pdf_status: EvidenceStatus
    pdf_path: str | None
    pdf_sha256: str | None
    parser_identity: str
    store_external_id: str
    scope: str
    valid_from: date
    valid_until: date
    no_pdf_reason: str | None = None

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "EvidenceBinding":
        return cls(
            manifest_path=str(raw.get("manifest_path") or ""),
            manifest_sha256=str(raw.get("manifest_sha256") or ""),
            html_sha256=str(raw.get("html_sha256") or ""),
            pdf_status=EvidenceStatus(str(raw.get("pdf_status") or "missing")),
            pdf_path=_optional_text(raw.get("pdf_path")),
            pdf_sha256=_optional_text(raw.get("pdf_sha256")),
            parser_identity=str(raw.get("parser_identity") or ""),
            store_external_id=str(raw.get("store_external_id") or ""),
            scope=str(raw.get("scope") or ""),
            valid_from=_parse_date(raw.get("valid_from"), "valid_from"),
            valid_until=_parse_date(raw.get("valid_until"), "valid_until"),
            no_pdf_reason=_optional_text(raw.get("no_pdf_reason")),
        )

    def validate(self) -> None:
        if self.store_external_id != FAMILY_PRIMARY_STORE_ID:
            raise ValueError(
                f"Netto store binding must be {FAMILY_PRIMARY_STORE_ID}, "
                f"got {self.store_external_id!r}"
            )
        if self.scope != FAMILY_PRIMARY_SCOPE:
            raise ValueError(
                f"Netto scope must be {FAMILY_PRIMARY_SCOPE!r}, got {self.scope!r}"
            )
        if not self.manifest_path:
            raise ValueError("manifest_path is required")
        _require_sha(self.manifest_sha256, "manifest_sha256")
        _require_sha(self.html_sha256, "html_sha256")
        if not self.parser_identity.strip():
            raise ValueError("parser_identity is required")
        if self.valid_from > self.valid_until:
            raise ValueError("campaign validity window is reversed")

        if self.pdf_status is EvidenceStatus.PDF_BOUND:
            if not self.pdf_path:
                raise ValueError("pdf_bound evidence requires pdf_path")
            _require_sha(self.pdf_sha256 or "", "pdf_sha256")
            if self.no_pdf_reason:
                raise ValueError("pdf_bound evidence cannot carry no_pdf_reason")
        elif self.pdf_status is EvidenceStatus.VERIFIED_NO_PDF:
            if self.pdf_path or self.pdf_sha256:
                raise ValueError("verified_no_pdf requires null PDF path and SHA")
            if not self.no_pdf_reason:
                raise ValueError("verified_no_pdf requires an explicit reason")
        elif self.pdf_status in {EvidenceStatus.MISSING, EvidenceStatus.CORRUPT}:
            # These states are valid controller inputs but are always fail-closed.
            return

    def covers(self, requested_date: date) -> bool:
        return self.valid_from <= requested_date <= self.valid_until


@dataclass(frozen=True)
class AuditRow:
    campaign_id: str
    field: str
    expected: Any
    predicted: Any
    classification: Classification
    page_number: int
    card_id: str
    manifest_sha256: str
    pdf_sha256: str
    parser_identity: str
    store_external_id: str = FAMILY_PRIMARY_STORE_ID
    scope: str = FAMILY_PRIMARY_SCOPE

    @classmethod
    def from_mapping(cls, raw: Mapping[str, Any]) -> "AuditRow":
        field = str(raw.get("field") or "")
        if field not in AUDITED_FIELDS:
            raise ValueError(f"unsupported audited field: {field!r}")
        page_number = int(raw.get("page_number") or 0)
        if page_number < 1:
            raise ValueError("page_number must be positive")
        row = cls(
            campaign_id=str(raw.get("campaign_id") or ""),
            field=field,
            expected=raw.get("expected"),
            predicted=raw.get("predicted"),
            classification=Classification(str(raw.get("classification") or "")),
            page_number=page_number,
            card_id=str(raw.get("card_id") or ""),
            manifest_sha256=str(raw.get("manifest_sha256") or ""),
            pdf_sha256=str(raw.get("pdf_sha256") or ""),
            parser_identity=str(raw.get("parser_identity") or ""),
            store_external_id=str(raw.get("store_external_id") or ""),
            scope=str(raw.get("scope") or ""),
        )
        row.validate()
        return row

    def validate(self) -> None:
        if not self.campaign_id:
            raise ValueError("campaign_id is required")
        if not self.card_id:
            raise ValueError("card_id is required")
        if not self.parser_identity:
            raise ValueError("parser_identity is required")
        if self.store_external_id != FAMILY_PRIMARY_STORE_ID:
            raise ValueError("audit row is not bound to family-primary store 5659")
        if self.scope != FAMILY_PRIMARY_SCOPE:
            raise ValueError("audit row has the wrong scope")
        _require_sha(self.manifest_sha256, "manifest_sha256")
        _require_sha(self.pdf_sha256, "pdf_sha256")
        if self.classification is Classification.MATCH and not values_equal(
            self.field, self.expected, self.predicted
        ):
            raise ValueError("classification=match contradicts expected/predicted values")
        if self.classification is Classification.PARSER_DEFECT and values_equal(
            self.field, self.expected, self.predicted
        ):
            raise ValueError("parser_defect requires a real disagreement")


@dataclass(frozen=True)
class FieldMetrics:
    field: str
    audited_count: int
    denominator_count: int
    selected_count: int
    correct_count: int
    precision: str | None
    coverage: str
    precision_threshold: str
    coverage_threshold: str
    minimum_samples: int
    promoted: bool
    route: str
    disagreement_counts: dict[str, int]


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{label} must be a JSON object")
    return value


def _optional_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _parse_date(value: Any, label: str) -> date:
    if not isinstance(value, str):
        raise ValueError(f"{label} must be an ISO date")
    try:
        return date.fromisoformat(value)
    except ValueError as exc:
        raise ValueError(f"{label} must be an ISO date") from exc


def _require_sha(value: str, label: str) -> None:
    if not SHA256_RE.fullmatch(value):
        raise ValueError(f"{label} must be 64 lowercase hexadecimal characters")


def _decimal(value: Any) -> Decimal:
    try:
        return Decimal(str(value).replace(",", "."))
    except (InvalidOperation, ValueError) as exc:
        raise ValueError(f"invalid decimal value: {value!r}") from exc


def values_equal(field: str, expected: Any, predicted: Any) -> bool:
    if expected is None or predicted is None:
        return expected is predicted
    if field == "price":
        return _decimal(expected).quantize(Decimal("0.01")) == _decimal(predicted).quantize(
            Decimal("0.01")
        )
    if field == "validity":
        return tuple(expected) == tuple(predicted)
    if field == "card_ownership":
        return str(expected).strip() == str(predicted).strip()
    normalized_expected = re.sub(r"\s+", " ", str(expected)).strip().casefold()
    normalized_predicted = re.sub(r"\s+", " ", str(predicted)).strip().casefold()
    return normalized_expected == normalized_predicted


def evaluate_corpus(
    rows: Iterable[AuditRow | Mapping[str, Any]],
    *,
    thresholds: Mapping[str, Decimal | str | float] | None = None,
    coverage_thresholds: Mapping[str, Decimal | str | float] | None = None,
    minimum_samples: int = DEFAULT_MINIMUM_SAMPLES,
    require_multiple_campaigns: bool = True,
) -> dict[str, Any]:
    parsed = [row if isinstance(row, AuditRow) else AuditRow.from_mapping(row) for row in rows]
    if not parsed:
        raise ValueError("audit corpus is empty")
    campaigns = sorted({row.campaign_id for row in parsed})
    if require_multiple_campaigns and len(campaigns) < 2:
        raise ValueError("promotion audit requires at least two frozen campaign families")
    if minimum_samples < 1:
        raise ValueError("minimum_samples must be positive")

    configured_precision = dict(DEFAULT_PRECISION_THRESHOLDS)
    configured_coverage = dict(DEFAULT_COVERAGE_THRESHOLDS)
    if thresholds:
        for field, value in thresholds.items():
            if field not in AUDITED_FIELDS:
                raise ValueError(f"unsupported threshold field: {field}")
            configured_precision[field] = Decimal(str(value))
    if coverage_thresholds:
        for field, value in coverage_thresholds.items():
            if field not in AUDITED_FIELDS:
                raise ValueError(f"unsupported coverage threshold field: {field}")
            configured_coverage[field] = Decimal(str(value))

    results: dict[str, FieldMetrics] = {}
    for field in AUDITED_FIELDS:
        field_rows = [row for row in parsed if row.field == field]
        disagreements = {classification.value: 0 for classification in Classification}
        for row in field_rows:
            disagreements[row.classification.value] += 1
        denominator = [
            row
            for row in field_rows
            if row.classification
            not in {Classification.AMBIGUOUS_SOURCE, Classification.TRUTH_PACK_CORRECTION}
        ]
        selected = [row for row in denominator if row.predicted is not None]
        correct = [
            row
            for row in selected
            if row.classification is Classification.MATCH
            and values_equal(field, row.expected, row.predicted)
        ]
        precision = (
            Decimal(len(correct)) / Decimal(len(selected)) if selected else None
        )
        coverage = (
            Decimal(len(selected)) / Decimal(len(denominator))
            if denominator
            else Decimal("0")
        )
        precision_threshold = configured_precision[field]
        coverage_threshold = configured_coverage[field]
        promoted = (
            precision is not None
            and len(denominator) >= minimum_samples
            and precision >= precision_threshold
            and coverage >= coverage_threshold
        )
        results[field] = FieldMetrics(
            field=field,
            audited_count=len(field_rows),
            denominator_count=len(denominator),
            selected_count=len(selected),
            correct_count=len(correct),
            precision=_ratio(precision),
            coverage=_ratio(coverage) or "0.000000",
            precision_threshold=_ratio(precision_threshold) or "0.000000",
            coverage_threshold=_ratio(coverage_threshold) or "0.000000",
            minimum_samples=minimum_samples,
            promoted=promoted,
            route="automatic_candidate" if promoted else "review_required",
            disagreement_counts=disagreements,
        )

    return {
        "schema_version": 1,
        "strategy": "netto_independent_field_promotion_gate_v1",
        "campaign_ids": campaigns,
        "campaign_count": len(campaigns),
        "store_external_id": FAMILY_PRIMARY_STORE_ID,
        "scope": FAMILY_PRIMARY_SCOPE,
        "review_only_default": True,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "production_write_performed": False,
        "fields": {field: asdict(metrics) for field, metrics in results.items()},
    }


def _ratio(value: Decimal | None) -> str | None:
    if value is None:
        return None
    return f"{value.quantize(Decimal('0.000001'))}"


def resolve_field_evidence(
    *,
    field: str,
    pdf_value: Any,
    html_value: Any,
    field_promoted: bool,
) -> dict[str, Any]:
    if field not in AUDITED_FIELDS:
        raise ValueError(f"unsupported field: {field}")
    conflict = (
        pdf_value is not None
        and html_value is not None
        and not values_equal(field, pdf_value, html_value)
    )
    # HTML is supplementary evidence only. It can never replace contradictory
    # immutable PDF evidence. Conflicting title/package data is always reviewed.
    forced_review = conflict and field in {"title", "package"}
    selected = pdf_value if field_promoted and not forced_review else None
    return {
        "field": field,
        "selected": selected,
        "candidate_pdf": pdf_value,
        "candidate_html": html_value,
        "source_of_truth": "pdf" if pdf_value is not None else "html_candidate_only",
        "conflict": conflict,
        "route": "review_required" if (not field_promoted or forced_review) else "automatic_candidate",
    }


def build_shadow_candidate(
    *,
    binding: EvidenceBinding,
    campaign_key: str,
    page_number: int,
    card_id: str,
    field_values: Mapping[str, Mapping[str, Any]],
    promotion_report: Mapping[str, Any],
) -> dict[str, Any]:
    binding.validate()
    if binding.pdf_status is not EvidenceStatus.PDF_BOUND:
        raise ValueError("shadow candidates require bound immutable PDF evidence")
    if page_number < 1 or not card_id:
        raise ValueError("page/card provenance is required")
    fields = _mapping(promotion_report.get("fields"), "promotion_report.fields")
    resolved: dict[str, Any] = {}
    for field in AUDITED_FIELDS:
        values = _mapping(field_values.get(field, {}), f"field_values.{field}")
        metrics = _mapping(fields.get(field, {}), f"promotion_report.fields.{field}")
        resolved[field] = resolve_field_evidence(
            field=field,
            pdf_value=values.get("pdf"),
            html_value=values.get("html"),
            field_promoted=bool(metrics.get("promoted")),
        )
    return {
        "schema_version": 1,
        "strategy": "netto_shadow_candidate_v1",
        "campaign_key": campaign_key,
        "review_only": any(value["route"] == "review_required" for value in resolved.values()),
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "production_write_performed": False,
        "provenance": {
            "store_external_id": binding.store_external_id,
            "scope": binding.scope,
            "manifest_path": binding.manifest_path,
            "manifest_sha256": binding.manifest_sha256,
            "html_sha256": binding.html_sha256,
            "pdf_path": binding.pdf_path,
            "pdf_sha256": binding.pdf_sha256,
            "parser_identity": binding.parser_identity,
            "page_number": page_number,
            "card_id": card_id,
        },
        "fields": resolved,
    }
