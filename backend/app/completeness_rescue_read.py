from __future__ import annotations

from collections.abc import Iterable
from typing import Any


def _normalized_name(value: object) -> str:
    return " ".join(str(value or "").casefold().split())


def _is_completeness_rescue_publication(row: Any) -> bool:
    raw = getattr(row, "raw_payload", None)
    if not isinstance(raw, dict):
        return False
    if raw.get("price_basis") != "completeness_rescue_review":
        return False

    original = raw.get("review_original_payload")
    if not isinstance(original, dict):
        return False
    rescue = original.get("completeness_rescue")
    return isinstance(rescue, dict) and bool(rescue.get("candidate_key"))


def _signature(state: str, row: Any) -> tuple[object, ...]:
    return (
        state,
        getattr(row, "source_chain", None),
        getattr(row, "source_store_external_id", None),
        _normalized_name(getattr(row, "product_name_raw", None)),
        getattr(row, "price_eur", None),
        getattr(row, "valid_from", None),
        getattr(row, "valid_until", None),
        getattr(row, "source_url", None),
    )


def _newness(row: Any) -> tuple[object, str]:
    return (
        getattr(row, "collected_at", None),
        str(getattr(row, "id", "")),
    )


def dedupe_completeness_rescue_publications(
    state_rows: Iterable[tuple[str, Any]],
) -> list[tuple[str, Any]]:
    # Prefer reviewed rescue evidence over an exact physical-deal duplicate.
    # This is a second-stage read policy after stable source_offer_id dedup.
    rows = list(state_rows)
    groups: dict[tuple[object, ...], list[int]] = {}
    for index, (state, row) in enumerate(rows):
        groups.setdefault(_signature(state, row), []).append(index)

    suppressed: set[int] = set()
    for indexes in groups.values():
        rescue_indexes = [
            i for i in indexes
            if _is_completeness_rescue_publication(rows[i][1])
        ]
        non_rescue_indexes = [i for i in indexes if i not in rescue_indexes]

        # Never broaden generic source dedup. The rescue lane is the only
        # authority that may override a second stable source identity here.
        if not rescue_indexes or not non_rescue_indexes:
            continue

        winner = max(rescue_indexes, key=lambda i: _newness(rows[i][1]))
        for i in indexes:
            if i != winner:
                suppressed.add(i)

    return [row for i, row in enumerate(rows) if i not in suppressed]
