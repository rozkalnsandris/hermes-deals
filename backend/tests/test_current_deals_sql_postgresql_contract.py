from __future__ import annotations

from datetime import date

from sqlalchemy.dialects import postgresql

from app.current_deals_sql_loader import _winner_metadata_query


def test_current_deals_winner_query_compiles_for_postgresql() -> None:
    query = _winner_metadata_query(date(2026, 8, 6))

    compiled = str(
        query.compile(
            dialect=postgresql.dialect(),
            compile_kwargs={"literal_binds": True},
        )
    )
    normalized = " ".join(compiled.casefold().split())

    assert "row_number() over" in normalized
    assert "partition by" in normalized
    assert "classified_current_deals" in normalized
    assert "ranked_current_deals" in normalized
    assert "current_deal_winner_ids" in normalized
    assert "offer_candidates.raw_payload" in normalized
    assert "winner_rank = 1" in normalized
