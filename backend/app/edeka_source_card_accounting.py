from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from hashlib import sha256
import json
from pathlib import Path
import re
from uuid import UUID

from bs4 import BeautifulSoup, Tag

from app.edeka_store_offers import (
    _read_manifest_bytes,
    _read_raw_html,
    parse_edeka_store_offers_snapshot,
)
from app.parsers.edeka import (
    EdekaParserContext,
    _PAYBACK_POINTS_ONLY_RE,
    _TITLE_PREFIX_RE,
    _is_pfand_only_unpriced_card,
    _norm,
    _offer_id_from_href,
)


ACCOUNTING_SCHEMA_VERSION = 1
EXPECTED_SOURCE_URL = "https://www.edeka.de/maerkte/071897/angebote/"
EXPECTED_PUBLIC_MARKET_ID = "071897"
EXPECTED_INTERNAL_MARKET_ID = "587881"
EXPECTED_STORE_NAME = "EDEKA Patzer"
EXPECTED_SCOPE = "family_primary_edeka"
_PRICE_STRUCTURE_TOKENS = ("price", "preis", "amount", "value")
_FULL_DATE_RE = re.compile(r"\b\d{2}\.\d{2}\.\d{4}\b")
_DECIMAL_LIKE_RE = re.compile(r"\b\d{1,4}[.,]\d{1,2}\b")


@dataclass(frozen=True)
class EdekaExcludedSourceCard:
    source_offer_id: str
    product_name_raw: str
    fragment_href: str
    dialog_id: str
    exclusion_reason: str

    def as_dict(self) -> dict[str, str]:
        return {
            "source_offer_id": self.source_offer_id,
            "product_name_raw": self.product_name_raw,
            "fragment_href": self.fragment_href,
            "dialog_id": self.dialog_id,
            "route": "excluded",
            "exclusion_reason": self.exclusion_reason,
        }


def _stable_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return sha256(_stable_json_bytes(value)).hexdigest()


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
            raise ValueError(f"EDEKA source-card accounting manifest {key} mismatch")

    try:
        snapshot_id = UUID(str(manifest["snapshot_id"]))
        collected_at = datetime.fromisoformat(str(manifest["collected_at"]))
    except (KeyError, TypeError, ValueError) as exc:
        raise ValueError(
            "EDEKA source-card accounting manifest identity is incomplete"
        ) from exc
    if collected_at.tzinfo is None or collected_at.utcoffset() is None:
        raise ValueError(
            "EDEKA source-card accounting collected_at must be timezone-aware"
        )

    return EdekaParserContext(
        snapshot_id=snapshot_id,
        source_url=EXPECTED_SOURCE_URL,
        collected_at=collected_at,
        public_market_id=EXPECTED_PUBLIC_MARKET_ID,
        internal_market_id=EXPECTED_INTERNAL_MARKET_ID,
        store_name=EXPECTED_STORE_NAME,
    )


def _source_cards(
    raw_html: bytes | str,
    context: EdekaParserContext,
) -> dict[str, tuple[str, str, Tag, Tag]]:
    soup = BeautifulSoup(raw_html, "html.parser")
    cards: dict[str, tuple[str, str, Tag, Tag]] = {}
    for anchor in soup.find_all("a", href=True):
        href = str(anchor.get("href") or "")
        source_offer_id = _offer_id_from_href(href, context.source_url)
        if source_offer_id is None or source_offer_id in cards:
            continue
        article = anchor.find_parent("article")
        if not isinstance(article, Tag):
            raise ValueError(
                "EDEKA source-card accounting offer fragment has no article: "
                f"{source_offer_id}"
            )
        dialog_id = f"dialog-angebot-{source_offer_id}"
        dialog = soup.find("dialog", id=dialog_id)
        if not isinstance(dialog, Tag):
            raise ValueError(
                "EDEKA source-card accounting offer fragment has no dialog: "
                f"{source_offer_id}"
            )
        raw_title = _norm(anchor.get_text(" ", strip=True))
        product_name = _TITLE_PREFIX_RE.sub("", raw_title).strip()
        if not product_name:
            raise ValueError(
                "EDEKA source-card accounting blank product name: "
                f"{source_offer_id}"
            )
        cards[source_offer_id] = (href, product_name, article, dialog)
    return cards


def _attribute_value(raw_attr: object) -> str:
    if isinstance(raw_attr, list):
        return _norm(" ".join(str(item) for item in raw_attr))
    return _norm(str(raw_attr))


def _has_hidden_price_evidence(article: Tag, dialog: Tag) -> bool:
    """Reject exclusion if any attribute exposes non-Pfand price evidence."""

    for container in (article, dialog):
        for node in container.find_all(True):
            for key, raw_attr in node.attrs.items():
                value = _attribute_value(raw_attr)
                if not value:
                    continue
                key_folded = key.casefold()
                value_folded = value.casefold()

                if any(token in key_folded for token in _PRICE_STRUCTURE_TOKENS):
                    return True
                if "preis" in value_folded or "rabatt" in value_folded:
                    return True
                if (
                    ("€" in value or "eur" in value_folded)
                    and "pfand" not in value_folded
                ):
                    return True
                # HTML class values are presentation/classification tokens, not
                # hidden source data. Tailwind classes legitimately contain
                # decimal sizing values such as h-62.5; treating those numbers
                # as possible prices creates false unexplained-loss failures.
                # Structural price class names remain fail-closed in
                # _is_pfand_only_unpriced_card().
                if key_folded == "class":
                    continue
                without_dates = _FULL_DATE_RE.sub("", value)
                if (
                    "pfand" not in value_folded
                    and _DECIMAL_LIKE_RE.search(without_dates)
                ):
                    return True

    return False


def _is_accountable_pfand_only_no_price(article: Tag, dialog: Tag) -> bool:
    return (
        _is_pfand_only_unpriced_card(article, dialog)
        and not _has_hidden_price_evidence(article, dialog)
    )


def build_edeka_source_card_accounting(
    raw_html: bytes | str,
    context: EdekaParserContext,
    *,
    parsed_offer_ids: set[str],
) -> dict[str, object]:
    cards = _source_cards(raw_html, context)
    source_ids = set(cards)
    missing_source_cards = sorted(parsed_offer_ids - source_ids)
    if missing_source_cards:
        raise ValueError(
            "EDEKA parsed offers are missing source cards: "
            f"{missing_source_cards[:5]}"
        )

    excluded: list[EdekaExcludedSourceCard] = []
    unexplained: list[str] = []
    for source_offer_id in sorted(source_ids - parsed_offer_ids):
        href, product_name, article, dialog = cards[source_offer_id]
        article_text = _norm(article.get_text(" ", strip=True))
        if _PAYBACK_POINTS_ONLY_RE.search(article_text):
            reason = "payback_points_only_no_offer_price"
        elif _is_accountable_pfand_only_no_price(article, dialog):
            reason = "source_card_missing_offer_price_pfand_only"
        else:
            unexplained.append(source_offer_id)
            continue
        excluded.append(
            EdekaExcludedSourceCard(
                source_offer_id=source_offer_id,
                product_name_raw=product_name[:160],
                fragment_href=href,
                dialog_id=f"dialog-angebot-{source_offer_id}",
                exclusion_reason=reason,
            )
        )

    if unexplained:
        raise ValueError(
            "EDEKA source-card accounting found unexplained parser losses: "
            f"{unexplained[:10]}"
        )

    excluded_rows = [item.as_dict() for item in excluded]
    source_card_ids = sorted(source_ids)
    parsed_ids = sorted(parsed_offer_ids)
    excluded_ids = [str(row["source_offer_id"]) for row in excluded_rows]
    source_card_count = len(source_card_ids)
    parsed_offer_count = len(parsed_ids)
    excluded_count = len(excluded_rows)
    if source_card_count != parsed_offer_count + excluded_count:
        raise ValueError(
            "EDEKA source-card accounting invariant failed: "
            f"source={source_card_count} parsed={parsed_offer_count} "
            f"excluded={excluded_count}"
        )

    report: dict[str, object] = {
        "schema_version": ACCOUNTING_SCHEMA_VERSION,
        "audit_type": "edeka_source_card_accounting",
        "source": {
            "source_chain": "edeka",
            "scope": EXPECTED_SCOPE,
            "public_market_id": EXPECTED_PUBLIC_MARKET_ID,
            "internal_market_id": EXPECTED_INTERNAL_MARKET_ID,
            "store_name": EXPECTED_STORE_NAME,
            "source_url": EXPECTED_SOURCE_URL,
            "snapshot_id": str(context.snapshot_id),
            "collected_at": context.collected_at.isoformat(),
        },
        "summary": {
            "source_card_count": source_card_count,
            "parsed_offer_count": parsed_offer_count,
            "excluded_count": excluded_count,
            "accounting_complete": True,
            "unexplained_source_card_loss": False,
            "source_card_ids_sha256": _sha256(source_card_ids),
            "parsed_offer_ids_sha256": _sha256(parsed_ids),
            "excluded_source_offer_ids_sha256": _sha256(excluded_ids),
        },
        "excluded_cards": excluded_rows,
    }
    report["report_sha256"] = _sha256(report)
    return report


def audit_edeka_source_card_manifest(
    manifest_path: Path,
    expected_sha256: str,
) -> dict[str, object]:
    manifest = _read_manifest_bytes(manifest_path, expected_sha256)
    context = _manifest_context(manifest)
    offers = parse_edeka_store_offers_snapshot(
        manifest_path,
        expected_sha256,
        context,
    )
    parsed_offer_ids = {
        str(offer.source_offer_id)
        for offer in offers
        if isinstance(offer.source_offer_id, str) and offer.source_offer_id
    }
    if len(parsed_offer_ids) != len(offers):
        raise ValueError(
            "EDEKA source-card accounting parsed offer IDs are not unique"
        )
    raw_html = _read_raw_html(manifest)
    report = build_edeka_source_card_accounting(
        raw_html,
        context,
        parsed_offer_ids=parsed_offer_ids,
    )
    report["manifest_sha256"] = expected_sha256
    report["raw_html_sha256"] = manifest.get("raw_html_sha256")
    report["valid_from"] = manifest.get("valid_from")
    report["valid_until"] = manifest.get("valid_until")
    report["parser_version"] = offers[0].parser_version if offers else None
    unsigned = dict(report)
    unsigned.pop("report_sha256", None)
    report["report_sha256"] = _sha256(unsigned)
    return report


def write_source_card_accounting(path: Path, report: dict[str, object]) -> None:
    data = _stable_json_bytes(report) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except FileExistsError:
        if path.read_bytes() != data:
            raise ValueError(
                "Refusing to replace different EDEKA source-card accounting evidence"
            )
