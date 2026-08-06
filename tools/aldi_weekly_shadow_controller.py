#!/usr/bin/env python3
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from enum import StrEnum
from hashlib import sha256
import json
import re
from typing import Any, Mapping
from urllib.parse import urlparse

SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ALDI_HOSTS = {"aldi-nord.de", "www.aldi-nord.de", "prospekt.aldi-nord.de"}
SOURCE_STATES = {
    "available",
    "not_published_yet",
    "source_unavailable",
    "evidence_mismatch",
    "parser_failed",
    "review_pending",
}


class AldiWeeklyError(ValueError):
    pass


class Decision(StrEnum):
    READY = "READY"
    NO_OP = "NO_OP"
    WAIT = "WAIT"
    BLOCKED = "BLOCKED"


@dataclass(frozen=True)
class Safety:
    dry_run: bool = True
    source_fetch_authorized: bool = False
    corpus_write_authorized: bool = False
    database_write_authorized: bool = False
    review_write_authorized: bool = False
    automatic_approval_authorized: bool = False
    production_publish_authorized: bool = False
    scheduler_change_authorized: bool = False
    production_canary_authorized: bool = False


def _sha(value: Any, field: str) -> str:
    text = str(value or "")
    if not SHA256_RE.fullmatch(text):
        raise AldiWeeklyError(f"{field} must be a lowercase SHA256")
    return text


def _text(value: Any, field: str) -> str:
    text = str(value or "").strip()
    if not text:
        raise AldiWeeklyError(f"{field} is required")
    return text


def _date(value: Any, field: str) -> date:
    try:
        return date.fromisoformat(str(value))
    except ValueError as exc:
        raise AldiWeeklyError(f"{field} must be ISO date") from exc


def _canonical(value: Any) -> bytes:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":")
    ).encode("utf-8")


def validate_manifest(raw: Mapping[str, Any]) -> dict[str, Any]:
    if raw.get("schema_version") != 1:
        raise AldiWeeklyError("unsupported schema_version")
    if raw.get("retailer") != "aldi_nord":
        raise AldiWeeklyError("retailer must be aldi_nord")
    if raw.get("scope") != "physical_store_flyer":
        raise AldiWeeklyError("scope must be physical_store_flyer")
    if raw.get("region") != "aldi_nord":
        raise AldiWeeklyError("region fallback is forbidden")

    state = str(raw.get("source_state") or "")
    if state not in SOURCE_STATES:
        raise AldiWeeklyError("unsupported source_state")

    source_url = _text(raw.get("source_url"), "source_url")
    parsed = urlparse(source_url)
    if parsed.scheme != "https" or parsed.hostname not in ALDI_HOSTS:
        raise AldiWeeklyError("source_url must use an allowlisted official ALDI Nord host")
    if parsed.username or parsed.password or parsed.fragment:
        raise AldiWeeklyError("source_url contains forbidden identity or fragment")

    valid_from = _date(raw.get("valid_from"), "valid_from")
    valid_to = _date(raw.get("valid_to"), "valid_to")
    if valid_to < valid_from or (valid_to - valid_from).days > 7:
        raise AldiWeeklyError("campaign window must be ordered and at most 8 days inclusive")

    manifest = {
        "schema_version": 1,
        "retailer": "aldi_nord",
        "scope": "physical_store_flyer",
        "region": "aldi_nord",
        "campaign_id": _text(raw.get("campaign_id"), "campaign_id"),
        "valid_from": valid_from.isoformat(),
        "valid_to": valid_to.isoformat(),
        "source_url": source_url,
        "source_state": state,
        "source_sha256": _sha(raw.get("source_sha256"), "source_sha256"),
        "page_manifest_sha256": _sha(
            raw.get("page_manifest_sha256"), "page_manifest_sha256"
        ),
        "parser_identity": _text(raw.get("parser_identity"), "parser_identity"),
        "ledger_identity": _text(raw.get("ledger_identity"), "ledger_identity"),
        "ledger_sha256": _sha(raw.get("ledger_sha256"), "ledger_sha256"),
        "automatic_candidate_count": int(raw.get("automatic_candidate_count", -1)),
        "review_required_count": int(raw.get("review_required_count", -1)),
        "unexplained_card_count": int(raw.get("unexplained_card_count", -1)),
        "promotion_ready": raw.get("promotion_ready"),
        "immutable_evidence": raw.get("immutable_evidence"),
    }
    for field in (
        "automatic_candidate_count",
        "review_required_count",
        "unexplained_card_count",
    ):
        if manifest[field] < 0:
            raise AldiWeeklyError(f"{field} must be non-negative")
    if manifest["promotion_ready"] is not False:
        raise AldiWeeklyError("promotion_ready must remain false")
    if manifest["immutable_evidence"] is not True:
        raise AldiWeeklyError("immutable_evidence must be true")
    return manifest


def fingerprint(manifest: Mapping[str, Any]) -> str:
    identity = {
        key: manifest[key]
        for key in (
            "retailer",
            "scope",
            "region",
            "campaign_id",
            "valid_from",
            "valid_to",
            "source_url",
            "source_sha256",
            "page_manifest_sha256",
            "parser_identity",
            "ledger_identity",
            "ledger_sha256",
            "automatic_candidate_count",
            "review_required_count",
            "unexplained_card_count",
        )
    }
    return sha256(_canonical(identity)).hexdigest()


def decide(
    raw: Mapping[str, Any], prior: Mapping[str, Any] | None = None
) -> dict[str, Any]:
    manifest = validate_manifest(raw)
    state = manifest["source_state"]
    reasons: list[str] = []

    if state in {"not_published_yet", "source_unavailable"}:
        decision = Decision.WAIT
        reasons.append(state)
    elif state in {"evidence_mismatch", "parser_failed"}:
        decision = Decision.BLOCKED
        reasons.append(state)
    elif manifest["unexplained_card_count"] != 0:
        decision = Decision.BLOCKED
        reasons.append("unexplained_cards")
    elif state == "review_pending":
        decision = Decision.WAIT
        reasons.append("review_pending")
    else:
        current_fingerprint = fingerprint(manifest)
        prior_fingerprint = None
        if prior is not None:
            if prior.get("schema_version") != 1:
                raise AldiWeeklyError("prior result has unsupported schema_version")
            prior_fingerprint = _sha(prior.get("fingerprint"), "prior fingerprint")
        if prior_fingerprint == current_fingerprint:
            decision = Decision.NO_OP
            reasons.append("unchanged_exact_identity")
        else:
            decision = Decision.READY
            reasons.append("new_verified_identity")

    current_fingerprint = fingerprint(manifest)
    return {
        "schema_version": 1,
        "strategy": "aldi_weekly_shadow_controller_gate_a_v1",
        "decision": decision.value,
        "reasons": reasons,
        "fingerprint": current_fingerprint,
        "campaign_id": manifest["campaign_id"],
        "valid_from": manifest["valid_from"],
        "valid_to": manifest["valid_to"],
        "source_state": state,
        "automatic_candidate_count": manifest["automatic_candidate_count"],
        "review_required_count": manifest["review_required_count"],
        "unexplained_card_count": manifest["unexplained_card_count"],
        "safety": Safety().__dict__,
    }
