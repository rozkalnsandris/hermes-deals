from __future__ import annotations

import argparse
import base64
from collections import Counter
from decimal import Decimal, InvalidOperation
import gzip
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping
import unicodedata


EXPECTED_SOURCE_ARCHIVE_SHA256 = (
    "882d61ad18ddca13680b97c0a27adf1a1db7874cabe337b61fc3ebc9b9d329f2"
)
EXPECTED_FIXTURE_MANIFEST_SHA256 = (
    "2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147"
)
EXPECTED_CAMPAIGN_COUNTS = {"hz31_hasb_4": 26, "hz32_hasb": 74}


class ReviewReconciliationError(ValueError):
    pass


def load_json(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise ReviewReconciliationError("review input must be a regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise ReviewReconciliationError("review input is not valid UTF-8 JSON") from exc
    if not isinstance(payload, dict):
        raise ReviewReconciliationError("review input root must be an object")
    return payload


def _canonical_sha256(payload: Mapping[str, Any]) -> str:
    encoded = json.dumps(
        payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    return sha256(encoded).hexdigest()


def _require_false(payload: Mapping[str, Any], keys: tuple[str, ...], label: str) -> None:
    for key in keys:
        if payload.get(key) is not False:
            raise ReviewReconciliationError(f"{label}.{key} must be false")


def _text(value: Any) -> str | None:
    if value is None:
        return None
    normalized = " ".join(str(value).split()).strip()
    return normalized or None


def _normalized_text(value: Any) -> str | None:
    text = _text(value)
    if text is None:
        return None
    text = unicodedata.normalize("NFKC", text).casefold()
    return " ".join(part for part in re.split(r"[^\w]+", text) if part)


def _price(value: Any) -> Decimal | None:
    text = _text(value)
    if text is None:
        return None
    try:
        parsed = Decimal(text.replace(",", "."))
    except InvalidOperation as exc:
        raise ReviewReconciliationError(f"invalid reviewed price: {value!r}") from exc
    if not parsed.is_finite() or parsed < 0:
        raise ReviewReconciliationError(f"invalid reviewed price: {value!r}")
    return parsed


def _rows(payload: Mapping[str, Any], key: str, expected_count: int) -> list[Mapping[str, Any]]:
    rows = payload.get(key)
    if not isinstance(rows, list) or len(rows) != expected_count:
        raise ReviewReconciliationError(
            f"{key} must contain exactly {expected_count} rows"
        )
    if not all(isinstance(row, Mapping) for row in rows):
        raise ReviewReconciliationError(f"{key} rows must be objects")
    return rows


def _decode_first_review(payload: Mapping[str, Any]) -> dict[str, Any]:
    if payload.get("strategy") != "netto_visual_shadow_corpus_v1_gzip":
        return dict(payload)
    if payload.get("encoding") != "gzip+base64":
        raise ReviewReconciliationError("unexpected first-review wrapper encoding")
    chunks = payload.get("payload_chunks")
    if not isinstance(chunks, list) or not all(isinstance(chunk, str) for chunk in chunks):
        raise ReviewReconciliationError("invalid first-review payload chunks")
    try:
        packed = base64.b64decode("".join(chunks), validate=True)
        if sha256(packed).hexdigest() != payload.get("payload_sha256"):
            raise ReviewReconciliationError("first-review compressed SHA mismatch")
        decoded = gzip.decompress(packed)
        if sha256(decoded).hexdigest() != payload.get("decoded_sha256"):
            raise ReviewReconciliationError("first-review decoded SHA mismatch")
        corpus = json.loads(decoded.decode("utf-8"))
    except ReviewReconciliationError:
        raise
    except (ValueError, UnicodeError, gzip.BadGzipFile, json.JSONDecodeError) as exc:
        raise ReviewReconciliationError("invalid compressed first-review corpus") from exc
    if not isinstance(corpus, dict):
        raise ReviewReconciliationError("decoded first-review root must be an object")
    return corpus


def _first_review_rows(payload: Mapping[str, Any]) -> list[Mapping[str, Any]]:
    encoded = payload.get("rows")
    fields = payload.get("row_fields")
    if fields is None:
        return _rows(payload, "rows", 100)
    if not isinstance(fields, list) or len(fields) != len(set(fields)):
        raise ReviewReconciliationError("first-review row fields must be unique")
    if not isinstance(encoded, list) or len(encoded) != 100:
        raise ReviewReconciliationError("first-review rows must contain 100 rows")
    rows: list[Mapping[str, Any]] = []
    for values in encoded:
        if not isinstance(values, list) or len(values) != len(fields):
            raise ReviewReconciliationError("first-review encoded row shape mismatch")
        rows.append(dict(zip(fields, values, strict=True)))
    return rows


def _field(row: Mapping[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in row:
            return row[key]
    raise ReviewReconciliationError(
        f"review row is missing all supported fields: {', '.join(keys)}"
    )


def normalize_first_review(source: Mapping[str, Any]) -> dict[str, Any]:
    payload = _decode_first_review(source)
    if payload.get("page_count") != 17 or payload.get("cell_count") != 100:
        raise ReviewReconciliationError("first review must bind 17 pages and 100 cells")
    if payload.get("campaign_cell_counts") != EXPECTED_CAMPAIGN_COUNTS:
        raise ReviewReconciliationError("first-review campaign counts do not match")
    if payload.get("source_archive_sha256") != EXPECTED_SOURCE_ARCHIVE_SHA256:
        raise ReviewReconciliationError("first-review source archive SHA mismatch")
    if (
        payload.get("source_fixture_manifest_sha256")
        != EXPECTED_FIXTURE_MANIFEST_SHA256
    ):
        raise ReviewReconciliationError("first-review fixture manifest SHA mismatch")
    safety_value = payload.get("safety", payload)
    if not isinstance(safety_value, Mapping):
        raise ReviewReconciliationError("first-review safety binding must be an object")
    safety = safety_value
    if safety.get("review_only_default") is not True:
        raise ReviewReconciliationError("first review must remain review-only")
    _require_false(
        safety,
        (
            "automatic_approval_enabled",
            "automatic_publish_enabled",
            "database_write_performed",
            "deployment_performed",
            "production_apply_authorized",
        ),
        "first_review",
    )

    normalized: dict[str, dict[str, Any]] = {}
    indexes: set[int] = set()
    campaign_counts: Counter[str] = Counter()
    for row in _first_review_rows(payload):
        cell_id = _text(_field(row, "cell_id", "card_id"))
        campaign_id = _text(_field(row, "campaign_id"))
        page_number = _field(row, "page_number")
        visual_index = _field(row, "visual_index")
        if not cell_id or cell_id in normalized:
            raise ReviewReconciliationError("first-review cell IDs must be unique")
        if campaign_id not in EXPECTED_CAMPAIGN_COUNTS:
            raise ReviewReconciliationError("first-review campaign binding is invalid")
        if not isinstance(page_number, int) or page_number <= 0:
            raise ReviewReconciliationError("first-review page number is invalid")
        if not isinstance(visual_index, int) or visual_index in indexes:
            raise ReviewReconciliationError("first-review visual indexes must be unique")
        indexes.add(visual_index)
        campaign_counts[campaign_id] += 1
        normalized[cell_id] = {
            "cell_id": cell_id,
            "campaign_id": campaign_id,
            "page_number": page_number,
            "visual_index": visual_index,
            "expected_title": _text(
                _field(row, "expected_title_first_pass", "expected_title")
            ),
            "expected_price": _price(
                _field(
                    row,
                    "expected_price_eur_first_pass",
                    "expected_primary_price_eur",
                    "expected_normal_price",
                    "expected_price",
                )
            ),
            "title_verdict": _text(
                row.get("title_verdict", row.get("first_pass_title_verdict"))
            ),
            "price_verdict": _text(
                row.get("price_verdict", row.get("first_pass_price_verdict"))
            ),
        }
    if indexes != set(range(100)):
        raise ReviewReconciliationError("first-review visual indexes must cover 0..99")
    if dict(campaign_counts) != EXPECTED_CAMPAIGN_COUNTS:
        raise ReviewReconciliationError("first-review row campaign counts do not match")
    return {
        "source_sha256": _canonical_sha256(payload),
        "fixture_manifest_sha256": EXPECTED_FIXTURE_MANIFEST_SHA256,
        "rows": normalized,
    }


def normalize_second_review(payload: Mapping[str, Any]) -> dict[str, Any]:
    expected_counts = {
        "reviewed_page_count": 17,
        "reviewed_cell_count": 100,
        "target_or_review_cell_count": 98,
        "scope_control_count": 2,
    }
    for key, value in expected_counts.items():
        if payload.get(key) != value:
            raise ReviewReconciliationError(f"second-review {key} must equal {value}")
    if (
        payload.get("source_n9_fixture_manifest_sha256")
        != EXPECTED_FIXTURE_MANIFEST_SHA256
    ):
        raise ReviewReconciliationError("second-review fixture manifest SHA mismatch")
    _require_false(
        payload,
        ("automatic_approval", "automatic_publish", "production_write_performed"),
        "second_review",
    )

    normalized: dict[str, dict[str, Any]] = {}
    indexes: set[int] = set()
    campaign_counts: Counter[str] = Counter()
    for row in _rows(payload, "cell_reviews", 100):
        cell_id = _text(row.get("cell_id"))
        campaign_id = _text(row.get("publication_slug"))
        page_number = row.get("page_number")
        visual_index = row.get("visual_index")
        if not cell_id or cell_id in normalized:
            raise ReviewReconciliationError("second-review cell IDs must be unique")
        if campaign_id not in EXPECTED_CAMPAIGN_COUNTS:
            raise ReviewReconciliationError("second-review campaign binding is invalid")
        if not isinstance(page_number, int) or page_number <= 0:
            raise ReviewReconciliationError("second-review page number is invalid")
        if not isinstance(visual_index, int) or visual_index in indexes:
            raise ReviewReconciliationError("second-review visual indexes must be unique")
        if row.get("automatic_approval_allowed") is not False:
            raise ReviewReconciliationError("second-review approval must remain blocked")
        if row.get("automatic_publish_allowed") is not False:
            raise ReviewReconciliationError("second-review publication must remain blocked")
        indexes.add(visual_index)
        campaign_counts[campaign_id] += 1
        normalized[cell_id] = {
            "cell_id": cell_id,
            "campaign_id": campaign_id,
            "page_number": page_number,
            "visual_index": visual_index,
            "expected_title": _text(row.get("expected_title")),
            "expected_price": _price(row.get("expected_primary_price_eur")),
            "visual_verdict": _text(row.get("visual_verdict")),
        }
    if indexes != set(range(1, 101)):
        raise ReviewReconciliationError("second-review visual indexes must cover 1..100")
    if dict(campaign_counts) != EXPECTED_CAMPAIGN_COUNTS:
        raise ReviewReconciliationError("second-review row campaign counts do not match")
    return {
        "source_sha256": _canonical_sha256(payload),
        "fixture_manifest_sha256": EXPECTED_FIXTURE_MANIFEST_SHA256,
        "rows": normalized,
    }


def reconcile_reviews(
    first_payload: Mapping[str, Any],
    second_payload: Mapping[str, Any],
) -> dict[str, Any]:
    first = normalize_first_review(first_payload)
    second = normalize_second_review(second_payload)
    first_rows = first["rows"]
    second_rows = second["rows"]
    if set(first_rows) != set(second_rows):
        missing_second = sorted(set(first_rows) - set(second_rows))
        missing_first = sorted(set(second_rows) - set(first_rows))
        raise ReviewReconciliationError(
            "review cell ID sets differ: "
            f"missing_second={missing_second}, missing_first={missing_first}"
        )

    title_exact_agreement = 0
    title_normalized_agreement = 0
    price_agreement = 0
    disagreements: list[dict[str, Any]] = []
    verdict_pairs: Counter[str] = Counter()
    for cell_id in sorted(first_rows):
        left = first_rows[cell_id]
        right = second_rows[cell_id]
        if (
            left["campaign_id"] != right["campaign_id"]
            or left["page_number"] != right["page_number"]
            or left["visual_index"] + 1 != right["visual_index"]
        ):
            raise ReviewReconciliationError(f"review identity drift for cell {cell_id}")

        exact_title = left["expected_title"] == right["expected_title"]
        normalized_title = (
            _normalized_text(left["expected_title"])
            == _normalized_text(right["expected_title"])
        )
        same_price = left["expected_price"] == right["expected_price"]
        title_exact_agreement += int(exact_title)
        title_normalized_agreement += int(normalized_title)
        price_agreement += int(same_price)
        verdict_pairs[
            f"{left['title_verdict'] or 'missing'} -> "
            f"{right['visual_verdict'] or 'missing'}"
        ] += 1
        if not exact_title or not same_price:
            disagreements.append(
                {
                    "cell_id": cell_id,
                    "campaign_id": left["campaign_id"],
                    "page_number": left["page_number"],
                    "first_visual_index": left["visual_index"],
                    "second_visual_index": right["visual_index"],
                    "title_exact_agreement": exact_title,
                    "title_normalized_agreement": normalized_title,
                    "price_agreement": same_price,
                    "first_expected_title": left["expected_title"],
                    "second_expected_title": right["expected_title"],
                    "first_expected_price_eur": (
                        str(left["expected_price"])
                        if left["expected_price"] is not None
                        else None
                    ),
                    "second_expected_price_eur": (
                        str(right["expected_price"])
                        if right["expected_price"] is not None
                        else None
                    ),
                    "first_title_verdict": left["title_verdict"],
                    "second_visual_verdict": right["visual_verdict"],
                }
            )

    title_disagreement_count = 100 - title_exact_agreement
    price_disagreement_count = 100 - price_agreement
    return {
        "schema_version": 1,
        "strategy": "netto_visual_review_reconciliation_v1",
        "source_archive_sha256": EXPECTED_SOURCE_ARCHIVE_SHA256,
        "source_fixture_manifest_sha256": EXPECTED_FIXTURE_MANIFEST_SHA256,
        "first_review_sha256": first["source_sha256"],
        "second_review_sha256": second["source_sha256"],
        "cell_count": 100,
        "identity_match_count": 100,
        "title_exact_agreement_count": title_exact_agreement,
        "title_normalized_agreement_count": title_normalized_agreement,
        "title_disagreement_count": title_disagreement_count,
        "price_agreement_count": price_agreement,
        "price_disagreement_count": price_disagreement_count,
        "row_disagreement_count": len(disagreements),
        "verdict_pair_counts": dict(sorted(verdict_pairs.items())),
        "reconciliation_status": (
            "reconciled_consistent"
            if not disagreements
            else "reconciled_with_disagreements"
        ),
        "adjudication_required": bool(disagreements),
        "promotion_ready": False,
        "review_only_default": True,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "database_write_performed": False,
        "deployment_performed": False,
        "production_apply_authorized": False,
        "disagreements": disagreements,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Reconcile two independently produced Netto visual-review ledgers."
    )
    parser.add_argument("--first-review", type=Path, required=True)
    parser.add_argument("--second-review", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    result = reconcile_reviews(
        load_json(args.first_review),
        load_json(args.second_review),
    )
    encoded = json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    if args.output:
        args.output.write_text(encoded, encoding="utf-8")
    else:
        print(encoded, end="")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
