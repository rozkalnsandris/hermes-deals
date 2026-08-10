from __future__ import annotations

from datetime import datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from uuid import UUID

import pytest

from app.edeka_source_card_accounting import (
    audit_edeka_source_card_manifest,
    build_edeka_source_card_accounting,
)
from app.parsers.edeka import EdekaParserContext


SOURCE_URL = "https://www.edeka.de/maerkte/071897/angebote/"
SNAPSHOT_ID = UUID("11111111-2222-4333-8444-555555555555")


def _context() -> EdekaParserContext:
    return EdekaParserContext(
        snapshot_id=SNAPSHOT_ID,
        source_url=SOURCE_URL,
        collected_at=datetime(2026, 8, 10, 18, 0, tzinfo=timezone.utc),
        public_market_id="071897",
        internal_market_id="587881",
        store_name="EDEKA Patzer",
    )


def _page(*, granini_extra: str = "", include_payback: bool = False) -> str:
    payback = ""
    if include_payback:
        payback = """
        <article>
          <h3><a href="#angebot-cccccccc-3333-4333-8333-cccccccccccc">
            Angebot: PAYBACK Aktion
          </a></h3>
          <p>10 Extra°Punkte Mit PAYBACK Extra Punkte sammeln</p>
        </article>
        <dialog id="dialog-angebot-cccccccc-3333-4333-8333-cccccccccccc">
          <span class="sr-only">Angebot:</span>
          <strong>Gültig ab 10.08.2026</strong>
          <p>Alle Angebote gültig bis Samstag, den 15.08.2026.</p>
        </dialog>
        """
    return f"""
    <!doctype html>
    <html lang="de">
      <head><title>Angebote EDEKA Patzer</title></head>
      <body>
        <article>
          <h3><a href="#angebot-68aa5875-e4e1-4a5b-8d6c-221a2319dc2b">
            Angebot: granini Die Limo
          </a></h3>
          <span class="sr-only">Produktbild granini Die Limo</span>
          <p class="line-clmap-2">
            versch. Sorten, je 1 l Flasche zzgl. € 0.25 Pfand
          </p>
          {granini_extra}
        </article>
        <dialog id="dialog-angebot-68aa5875-e4e1-4a5b-8d6c-221a2319dc2b">
          <span class="sr-only">Dialog schließen</span>
          <span class="sr-only">Angebot:</span>
          <strong>Gültig ab 10.08.2026</strong>
          <span>versch. Sorten, je 1 l Flasche zzgl. € 0.25 Pfand</span>
          <p>Alle Angebote gültig bis Samstag, den 15.08.2026.</p>
        </dialog>

        <article>
          <h3><a href="#angebot-bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb">
            Angebot: Kontrollprodukt
          </a></h3>
          <div class="sr-only">Festpreis von 1.49 €</div>
        </article>
        <dialog id="dialog-angebot-bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb">
          <strong>Gültig ab 10.08.2026</strong>
          <p>Alle Angebote gültig bis Samstag, den 15.08.2026.</p>
        </dialog>
        {payback}
      </body>
    </html>
    """


def test_pfand_only_card_is_explicitly_accounted_as_excluded() -> None:
    report = build_edeka_source_card_accounting(
        _page(),
        _context(),
        parsed_offer_ids={"bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"},
    )

    assert report["summary"]["source_card_count"] == 2
    assert report["summary"]["parsed_offer_count"] == 1
    assert report["summary"]["excluded_count"] == 1
    assert report["summary"]["accounting_complete"] is True
    assert report["summary"]["unexplained_source_card_loss"] is False
    assert report["excluded_cards"] == [
        {
            "source_offer_id": "68aa5875-e4e1-4a5b-8d6c-221a2319dc2b",
            "product_name_raw": "granini Die Limo",
            "fragment_href": "#angebot-68aa5875-e4e1-4a5b-8d6c-221a2319dc2b",
            "dialog_id": "dialog-angebot-68aa5875-e4e1-4a5b-8d6c-221a2319dc2b",
            "route": "excluded",
            "exclusion_reason": "source_card_missing_offer_price_pfand_only",
        }
    ]


def test_payback_points_only_card_is_also_explicitly_accounted() -> None:
    report = build_edeka_source_card_accounting(
        _page(include_payback=True),
        _context(),
        parsed_offer_ids={"bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"},
    )

    assert report["summary"]["source_card_count"] == 3
    assert report["summary"]["parsed_offer_count"] == 1
    assert report["summary"]["excluded_count"] == 2
    reasons = {
        row["source_offer_id"]: row["exclusion_reason"]
        for row in report["excluded_cards"]
    }
    assert reasons["cccccccc-3333-4333-8333-cccccccccccc"] == (
        "payback_points_only_no_offer_price"
    )


def test_unexplained_split_price_shape_remains_fail_closed() -> None:
    with pytest.raises(ValueError, match="unexplained parser losses"):
        build_edeka_source_card_accounting(
            _page(granini_extra='<div class="price-shell" data-price="1.79">1.79</div>'),
            _context(),
            parsed_offer_ids={"bbbbbbbb-2222-4222-8222-bbbbbbbbbbbb"},
        )


def _write_manifest(tmp_path: Path) -> tuple[Path, str]:
    raw = _page().encode("utf-8")
    raw_path = tmp_path / "071897-offers.html"
    raw_path.write_bytes(raw)
    raw_sha = sha256(raw).hexdigest()
    manifest = {
        "schema_version": 1,
        "strategy": "edeka_patzer_store_offers_v1",
        "snapshot_id": str(SNAPSHOT_ID),
        "source_chain": "edeka",
        "scope": "family_primary_edeka",
        "public_market_id": "071897",
        "internal_market_id": "587881",
        "store_name": "EDEKA Patzer",
        "source_url": SOURCE_URL,
        "final_url": SOURCE_URL,
        "collected_at": "2026-08-10T18:00:00+00:00",
        "valid_from": "2026-08-10",
        "valid_until": "2026-08-15",
        "offer_count": 1,
        "raw_html_path": str(raw_path),
        "raw_html_sha256": raw_sha,
        "raw_content_type": "text/html",
        "raw_content_bytes": len(raw),
    }
    data = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    manifest_path = tmp_path / "manifest.json"
    manifest_path.write_bytes(data)
    return manifest_path, sha256(data).hexdigest()


def test_retained_manifest_derivation_accounts_source_cards_without_refetch(
    tmp_path: Path,
) -> None:
    manifest_path, manifest_sha = _write_manifest(tmp_path)

    report = audit_edeka_source_card_manifest(manifest_path, manifest_sha)

    assert report["manifest_sha256"] == manifest_sha
    assert report["summary"]["source_card_count"] == 2
    assert report["summary"]["parsed_offer_count"] == 1
    assert report["summary"]["excluded_count"] == 1
    assert report["valid_from"] == "2026-08-10"
    assert report["valid_until"] == "2026-08-15"
    assert report["parser_version"] == "edeka-v1"
