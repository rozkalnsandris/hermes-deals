from __future__ import annotations

import argparse
from pathlib import Path
import sys

from app.db import SessionLocal
from app.edeka_store_offers import (
    collect_edeka_store_offers,
    parse_edeka_store_offers_snapshot,
)
from app.offer_store import save_offer_candidates
from app.parsers.edeka import EdekaParserContext
from app.settings import get_settings
from app.source_config import SourceConfig, load_sources


def _edeka_source() -> SourceConfig:
    settings = get_settings()
    sources = [
        source
        for source in load_sources(settings.sources_config)
        if source.enabled and source.chain == "edeka"
    ]
    if len(sources) != 1:
        raise ValueError(
            "Expected exactly one enabled EDEKA source, "
            f"found={len(sources)}"
        )
    return sources[0]


def collect_edeka(min_offers: int) -> int:
    source = _edeka_source()
    with SessionLocal() as db:
        result = collect_edeka_store_offers(db, source)
        snapshot = result.snapshot

        if not snapshot.success or not snapshot.snapshot_path or not snapshot.sha256:
            print(
                "ERROR: EDEKA immutable source collection failed: "
                f"{snapshot.error or snapshot.http_status}",
                file=sys.stderr,
            )
            return 2

        if result.unchanged:
            print(
                "[collect] edeka unchanged source; safe no-op "
                f"snapshot={snapshot.id}",
                flush=True,
            )
            return 0

        context = EdekaParserContext(
            snapshot_id=snapshot.id,
            source_url=snapshot.final_url or snapshot.source_url,
            collected_at=snapshot.collected_at,
            public_market_id=source.store_external_id or "",
            internal_market_id=source.store_internal_id or "",
            store_name=source.store_name or "",
        )
        offers = parse_edeka_store_offers_snapshot(
            Path(snapshot.snapshot_path),
            snapshot.sha256,
            context,
        )
        if len(offers) < min_offers:
            print(
                f"ERROR: EDEKA parser produced only {len(offers)} offers; "
                f"minimum gate is {min_offers}. No offer rows were written. "
                "The immutable SourceSnapshot remains as provenance.",
                file=sys.stderr,
            )
            return 3

        count = save_offer_candidates(db, offers)
        windows = sorted(
            {
                (str(offer.valid_from), str(offer.valid_until))
                for offer in offers
            }
        )
        print(
            f"[collect] edeka parser={offers[0].parser_version} "
            f"saved={count} snapshot={snapshot.id} windows={windows}",
            flush=True,
        )
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Collect immutable EDEKA Patzer weekly offers"
    )
    parser.add_argument(
        "--min-offers",
        type=int,
        default=150,
        help="Minimum parsed offer count required before persistence",
    )
    args = parser.parse_args()

    try:
        return collect_edeka(max(args.min_offers, 1))
    except Exception as exc:
        print(
            f"ERROR: {type(exc).__name__}: {exc}",
            file=sys.stderr,
        )
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
