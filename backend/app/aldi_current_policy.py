from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from datetime import date, datetime
from math import ceil
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

from app.schemas import OfferCandidate


_CURRENT_PATH = "/angebote.html"
_POLICY_PARSER_VERSION = "aldi-nord-v1.1-current"
_LOCAL_TZ = ZoneInfo("Europe/Berlin")


@dataclass(frozen=True)
class AldiCurrentValidityReport:
    applied: bool
    reference_date: date
    page_week_end: date | None
    support_count: int
    offer_count: int
    clamped_count: int


def _is_current_page(source_url: str) -> bool:
    parsed = urlparse(str(source_url))
    return (
        parsed.scheme in {"http", "https"}
        and parsed.netloc.casefold() == "www.aldi-nord.de"
        and parsed.path.rstrip("/") == _CURRENT_PATH
    )


def _derive_current_page_week_end(
    offers: list[OfferCandidate],
    *,
    collected_at: datetime,
) -> tuple[date, int]:
    if not offers:
        raise ValueError("ALDI current-page policy requires at least one offer")

    reference = collected_at.astimezone(_LOCAL_TZ).date()
    # Current page may still show the just-ended week on Sunday, or the new
    # week may already be published. Ignore obviously long-lived source dates
    # and infer the visible campaign end from the strongest near-term signal.
    counts: Counter[date] = Counter()
    for offer in offers:
        end = offer.valid_until
        if end is None:
            continue
        delta = (end - reference).days
        if -2 <= delta <= 8:
            counts[end] += 1

    if not counts:
        raise ValueError(
            "ALDI current page has no near-term validity end signal; refusing normalization"
        )

    page_end, support = max(
        counts.items(),
        key=lambda item: (item[1], item[0]),
    )
    minimum_support = max(10, ceil(len(offers) * 0.10))
    if support < minimum_support:
        raise ValueError(
            "ALDI current-page week-end signal is too weak: "
            f"support={support} required={minimum_support} offers={len(offers)}"
        )

    delta = (page_end - reference).days
    if not -2 <= delta <= 8:
        raise ValueError(
            f"ALDI derived current-page week end is implausible: {page_end}"
        )
    return page_end, support


def apply_aldi_current_page_policy(
    offers: list[OfferCandidate],
    *,
    source_url: str,
    collected_at: datetime,
) -> tuple[list[OfferCandidate], AldiCurrentValidityReport]:
    reference = collected_at.astimezone(_LOCAL_TZ).date()
    if not _is_current_page(source_url):
        return offers, AldiCurrentValidityReport(
            applied=False,
            reference_date=reference,
            page_week_end=None,
            support_count=0,
            offer_count=len(offers),
            clamped_count=0,
        )

    page_end, support = _derive_current_page_week_end(
        offers,
        collected_at=collected_at,
    )

    normalized: list[OfferCandidate] = []
    clamped = 0
    for offer in offers:
        if offer.valid_from is None or offer.valid_until is None:
            raise ValueError(
                "ALDI current-page parser emitted an offer without complete validity"
            )
        if offer.valid_from > page_end:
            raise ValueError(
                "ALDI current-page offer starts after the derived visible week end: "
                f"id={offer.source_offer_id} from={offer.valid_from} end={page_end}"
            )

        effective_end = offer.valid_until
        if effective_end > page_end:
            effective_end = page_end
            clamped += 1

        # raw_payload stays byte-for-byte semantically equal to the parser's
        # source object. The immutable raw HTML snapshot remains the source of
        # truth; parser_version identifies this deterministic derived policy.
        normalized.append(
            offer.model_copy(
                update={
                    "valid_until": effective_end,
                    "parser_version": _POLICY_PARSER_VERSION,
                }
            )
        )

    return normalized, AldiCurrentValidityReport(
        applied=True,
        reference_date=reference,
        page_week_end=page_end,
        support_count=support,
        offer_count=len(normalized),
        clamped_count=clamped,
    )
