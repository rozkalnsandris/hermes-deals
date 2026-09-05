#!/usr/bin/env python3
from __future__ import annotations

import argparse
from collections import defaultdict
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping


MODE = "ALDI_NEW_BASELINE_PAGE_CARD_PARITY_V01"
ISSUE_NUMBER = 682
GATE_A_MODE = "ALDI_NEW_IMMUTABLE_BASELINE_GATE_A_V01"
GATE_A_DECISION = "READY_FOR_NEW_BASELINE_ADJUDICATION"
DECISION = "READY_FOR_NEW_BASELINE_GATE_C"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{3,159}$")
CARD_ID_RE = re.compile(r"^p(\d{3}):c(\d{3})$")
CANDIDATE_ROUTES = {"auto_candidate", "review_required", "excluded"}
CARD_SCOPES = {"in_scope", "review", "excluded"}
CARD_ROUTES = {"candidate", "review", "excluded"}


class ParityGateError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise ParityGateError(message)


def canonical_bytes(value: Any) -> bytes:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")


def canonical_sha256(value: Any) -> str:
    return sha256(canonical_bytes(value)).hexdigest()


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    require(isinstance(value, Mapping), f"{label} must be an object")
    return value


def _nonempty(value: Any, label: str) -> str:
    text = str(value or "").strip()
    require(bool(text), f"{label} must be non-empty")
    return text


def _sha256(value: Any, label: str) -> str:
    text = str(value or "")
    require(bool(SHA256_RE.fullmatch(text)), f"{label} must be lowercase SHA256")
    return text


def _strict_int(value: Any, label: str, *, minimum: int = 0) -> int:
    require(not isinstance(value, bool), f"{label} must be an integer")
    require(isinstance(value, int), f"{label} must be an integer")
    require(value >= minimum, f"{label} must be >= {minimum}")
    return value


def _region(value: Any, label: str) -> dict[str, float]:
    row = _mapping(value, label)
    result: dict[str, float] = {}
    for key in ("x", "y", "width", "height"):
        raw = row.get(key)
        require(
            isinstance(raw, (int, float)) and not isinstance(raw, bool),
            f"{label}.{key} must be numeric",
        )
        number = round(float(raw), 6)
        require(0 <= number <= 1, f"{label}.{key} outside 0..1")
        result[key] = number
    require(result["width"] > 0, f"{label}.width must be positive")
    require(result["height"] > 0, f"{label}.height must be positive")
    require(result["x"] + result["width"] <= 1.000001, f"{label} exceeds page width")
    require(result["y"] + result["height"] <= 1.000001, f"{label} exceeds page height")
    return result


def safety_contract() -> dict[str, bool]:
    return {
        "contract_only": True,
        "network_acquisition_authorized": False,
        "parser_execution_authorized": False,
        "source_or_corpus_write_authorized": False,
        "candidate_creation_authorized": False,
        "review_write_authorized": False,
        "automatic_approval_authorized": False,
        "automatic_publication_authorized": False,
        "production_database_write_authorized": False,
        "production_deployment_authorized": False,
        "scheduler_or_retry_authorized": False,
        "production_canary_authorized": False,
        "historical_corpus_reconstruction_authorized": False,
        "historical_completion_claimed": False,
        "newer_evidence_substitution_authorized": False,
    }


def validate_baseline_binding(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(payload.get("baseline"), "baseline")
    require(raw.get("gate_a_mode") == GATE_A_MODE, "Gate A mode binding mismatch")
    require(raw.get("gate_a_decision") == GATE_A_DECISION, "Gate A decision binding mismatch")
    baseline_id = _nonempty(raw.get("baseline_id"), "baseline.baseline_id")
    require(bool(ID_RE.fullmatch(baseline_id)), "baseline_id has invalid format")
    require(
        "a30" not in baseline_id and "a31" not in baseline_id and "49+41" not in baseline_id,
        "baseline_id must not reuse legacy A3.0/A3.1 identity",
    )
    page_count = _strict_int(raw.get("page_count"), "baseline.page_count", minimum=1)
    require(page_count <= 128, "baseline.page_count exceeds bounded limit")
    require(
        raw.get("historical_issue_56_completion_claimed") is False,
        "historical issue #56 completion must remain false",
    )
    return {
        "gate_a_mode": GATE_A_MODE,
        "gate_a_decision": GATE_A_DECISION,
        "baseline_id": baseline_id,
        "baseline_fingerprint": _sha256(raw.get("baseline_fingerprint"), "baseline.baseline_fingerprint"),
        "page_manifest_sha256": _sha256(raw.get("page_manifest_sha256"), "baseline.page_manifest_sha256"),
        "page_count": page_count,
        "historical_issue_56_completion_claimed": False,
    }


def validate_candidates(
    payload: Mapping[str, Any],
    *,
    page_count: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    projection = _mapping(payload.get("candidate_projection"), "candidate_projection")
    rows = projection.get("candidates")
    require(isinstance(rows, list), "candidate_projection.candidates must be a list")
    require(len(rows) <= 4096, "candidate projection exceeds bounded row limit")

    normalized: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, raw in enumerate(rows, start=1):
        row = _mapping(raw, f"candidate row {index}")
        candidate_id = _nonempty(row.get("candidate_id"), f"candidate row {index} candidate_id")
        require(bool(ID_RE.fullmatch(candidate_id)), f"candidate {candidate_id!r} has invalid ID")
        require(candidate_id not in ids, f"duplicate candidate_id: {candidate_id}")
        ids.add(candidate_id)
        page_number = _strict_int(row.get("page_number"), f"candidate {candidate_id} page_number", minimum=1)
        require(page_number <= page_count, f"candidate {candidate_id} page_number outside baseline")
        card_id = _nonempty(row.get("card_id"), f"candidate {candidate_id} card_id")
        match = CARD_ID_RE.fullmatch(card_id)
        require(bool(match), f"candidate {candidate_id} has invalid card_id")
        require(int(match.group(1)) == page_number, f"candidate {candidate_id} page/card mismatch")
        route = _nonempty(row.get("route"), f"candidate {candidate_id} route")
        require(route in CANDIDATE_ROUTES, f"candidate {candidate_id} route invalid")
        reason = str(row.get("reason") or "").strip()
        if route == "auto_candidate":
            require(not reason, f"auto candidate {candidate_id} must not carry review/exclusion reason")
        else:
            require(bool(reason), f"{route} candidate {candidate_id} requires reason")
        normalized.append(
            {
                "candidate_id": candidate_id,
                "payload_sha256": _sha256(row.get("payload_sha256"), f"candidate {candidate_id} payload_sha256"),
                "page_number": page_number,
                "card_id": card_id,
                "route": route,
                "reason": reason,
            }
        )

    normalized.sort(key=lambda row: row["candidate_id"])
    projection_sha = canonical_sha256(normalized)
    require(projection.get("projection_sha256") == projection_sha, "candidate projection SHA256 mismatch")
    return ({"projection_sha256": projection_sha, "candidate_count": len(normalized)}, normalized)


def validate_cards(
    payload: Mapping[str, Any],
    *,
    page_count: int,
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    ledger = _mapping(payload.get("card_ledger"), "card_ledger")
    rows = ledger.get("cards")
    require(isinstance(rows, list), "card_ledger.cards must be a list")
    require(1 <= len(rows) <= 8192, "card ledger must contain 1..8192 cards")

    normalized: list[dict[str, Any]] = []
    ids: set[str] = set()
    for index, raw in enumerate(rows, start=1):
        row = _mapping(raw, f"card row {index}")
        card_id = _nonempty(row.get("card_id"), f"card row {index} card_id")
        match = CARD_ID_RE.fullmatch(card_id)
        require(bool(match), f"card {card_id!r} has invalid stable card_id")
        require(card_id not in ids, f"duplicate card_id: {card_id}")
        ids.add(card_id)
        page_number = _strict_int(row.get("page_number"), f"card {card_id} page_number", minimum=1)
        require(page_number <= page_count, f"card {card_id} page outside baseline")
        require(int(match.group(1)) == page_number, f"card {card_id} page/card mismatch")
        scope = _nonempty(row.get("scope"), f"card {card_id} scope")
        route = _nonempty(row.get("route"), f"card {card_id} route")
        require(scope in CARD_SCOPES, f"card {card_id} scope invalid")
        require(route in CARD_ROUTES, f"card {card_id} route invalid")
        require(
            (scope, route) in {("in_scope", "candidate"), ("review", "review"), ("excluded", "excluded")},
            f"card {card_id} scope/route mismatch",
        )
        candidate_ids_raw = row.get("candidate_ids")
        require(isinstance(candidate_ids_raw, list), f"card {card_id} candidate_ids must be a list")
        candidate_ids = sorted(str(value).strip() for value in candidate_ids_raw if str(value).strip())
        require(len(candidate_ids) == len(set(candidate_ids)), f"card {card_id} candidate_ids contain duplicates")
        reason = str(row.get("reason") or "").strip()
        if route == "candidate":
            require(candidate_ids, f"in-scope card {card_id} requires candidate binding")
            require(not reason, f"candidate card {card_id} must not carry review/exclusion reason")
        else:
            require(bool(reason), f"{route} card {card_id} requires reason")
        normalized.append(
            {
                "card_id": card_id,
                "page_number": page_number,
                "page_sha256": _sha256(row.get("page_sha256"), f"card {card_id} page_sha256"),
                "region": _region(row.get("region"), f"card {card_id} region"),
                "scope": scope,
                "route": route,
                "candidate_ids": candidate_ids,
                "reason": reason,
            }
        )

    normalized.sort(key=lambda row: row["card_id"])
    ledger_sha = canonical_sha256(normalized)
    require(ledger.get("ledger_sha256") == ledger_sha, "card ledger SHA256 mismatch")
    return ({"ledger_sha256": ledger_sha, "card_count": len(normalized)}, normalized)


def validate_bidirectional(
    candidates: list[dict[str, Any]],
    cards: list[dict[str, Any]],
) -> dict[str, Any]:
    candidate_by_id = {row["candidate_id"]: row for row in candidates}
    card_by_id = {row["card_id"]: row for row in cards}
    referenced_by_card: dict[str, list[str]] = defaultdict(list)

    for candidate in candidates:
        card = card_by_id.get(candidate["card_id"])
        require(card is not None, f"candidate {candidate['candidate_id']} references unknown card")
        require(candidate["page_number"] == card["page_number"], f"candidate {candidate['candidate_id']} page differs from card")
        expected = {
            "auto_candidate": ("in_scope", "candidate"),
            "review_required": ("review", "review"),
            "excluded": ("excluded", "excluded"),
        }[candidate["route"]]
        require(
            (card["scope"], card["route"]) == expected,
            f"candidate {candidate['candidate_id']} route conflicts with card route",
        )
        referenced_by_card[card["card_id"]].append(candidate["candidate_id"])

    for card in cards:
        declared = card["candidate_ids"]
        observed = sorted(referenced_by_card.get(card["card_id"], []))
        require(declared == observed, f"card {card['card_id']} reverse candidate binding mismatch")
        if card["route"] == "candidate":
            require(observed, f"in-scope card {card['card_id']} is unexplained")
        for candidate_id in declared:
            require(candidate_id in candidate_by_id, f"card {card['card_id']} references unknown candidate {candidate_id}")

    return {
        "candidate_count": len(candidates),
        "card_count": len(cards),
        "auto_candidate_count": sum(row["route"] == "auto_candidate" for row in candidates),
        "review_candidate_count": sum(row["route"] == "review_required" for row in candidates),
        "excluded_candidate_count": sum(row["route"] == "excluded" for row in candidates),
        "in_scope_card_count": sum(row["scope"] == "in_scope" for row in cards),
        "review_card_count": sum(row["scope"] == "review" for row in cards),
        "excluded_card_count": sum(row["scope"] == "excluded" for row in cards),
        "unexplained_card_count": 0,
    }


def validate_parity(payload: Mapping[str, Any]) -> dict[str, Any]:
    require(payload.get("schema_version") == 1, "unexpected parity schema")
    require(payload.get("mode") == MODE, "unexpected parity mode")
    require(payload.get("issue_number") == ISSUE_NUMBER, "issue binding mismatch")

    baseline = validate_baseline_binding(payload)
    projection_meta, candidates = validate_candidates(payload, page_count=baseline["page_count"])
    ledger_meta, cards = validate_cards(payload, page_count=baseline["page_count"])
    summary = validate_bidirectional(candidates, cards)

    identity = {
        "baseline": baseline,
        "candidate_projection_sha256": projection_meta["projection_sha256"],
        "card_ledger_sha256": ledger_meta["ledger_sha256"],
        "candidates": candidates,
        "cards": cards,
    }
    parity_fingerprint = canonical_sha256(identity)

    return {
        "schema_version": 1,
        "mode": MODE,
        "issue_number": ISSUE_NUMBER,
        "decision": DECISION,
        "baseline": baseline,
        "candidate_projection": projection_meta,
        "card_ledger": ledger_meta,
        "parity_fingerprint": parity_fingerprint,
        "summary": summary,
        "candidates": candidates,
        "cards": cards,
        "parity_complete": True,
        "gate_c_continuation_ready": True,
        "historical_issue_56_completion_claimed": False,
        "production_eligible": False,
        "promotion_ready": False,
        "next_gate": {
            "name": "new_baseline_gate_c_shadow_replay",
            "requires_exact_baseline_fingerprint": baseline["baseline_fingerprint"],
            "requires_exact_parity_fingerprint": parity_fingerprint,
            "requires_replay_no_duplicate_candidates": True,
            "requires_immutable_payload_no_drift": True,
        },
        "safety": safety_contract(),
    }


def load_input(path: Path) -> dict[str, Any]:
    require(path.is_file(), f"parity input is missing: {path}")
    require(not path.is_symlink(), "symlinked parity input forbidden")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise ParityGateError(f"invalid parity JSON: {exc}") from exc
    require(isinstance(payload, dict), "parity input must be a JSON object")
    return payload


def write_create_only(path: Path, result: Mapping[str, Any]) -> None:
    require(not path.exists(), f"output already exists: {path}")
    require(path.parent.is_dir(), f"output parent missing: {path.parent}")
    require(not path.parent.is_symlink(), "symlinked output parent forbidden")
    path.write_bytes(canonical_bytes(result))


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Validate one explicit ALDI new-baseline page/card parity ledger."
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        result = validate_parity(load_input(args.input))
        if args.output is not None:
            write_create_only(args.output, result)
    except ParityGateError as exc:
        print(f"PARITY_GATE_RESULT=BLOCKED reason={exc}")
        return 20

    print(f"PARITY_GATE_RESULT={result['decision']}")
    print(f"PARITY_FINGERPRINT={result['parity_fingerprint']}")
    print("UNEXPLAINED_CARD_COUNT=0")
    print("HISTORICAL_ISSUE_56_COMPLETION_CLAIMED=false")
    print("PRODUCTION_ELIGIBLE=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
