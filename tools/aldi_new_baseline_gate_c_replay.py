#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import re
from typing import Any, Mapping


MODE = "ALDI_NEW_BASELINE_GATE_C_REPLAY_V01"
ISSUE_NUMBER = 682
GATE_B_MODE = "ALDI_NEW_BASELINE_PAGE_CARD_PARITY_V01"
GATE_B_DECISION = "READY_FOR_NEW_BASELINE_GATE_C"
READY_DECISION = "READY_FOR_TWO_CONSECUTIVE_WEEKLY_SHADOW_CYCLES"
NO_OP_DECISION = "NO_OP"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
ID_RE = re.compile(r"^[a-z0-9][a-z0-9._:-]{3,159}$")
REPLAY_ID_RE = re.compile(r"^replay-[0-9]{2}$")


class GateCError(ValueError):
    pass


def require(condition: bool, message: str) -> None:
    if not condition:
        raise GateCError(message)


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
        "weekly_shadow_cycle_execution_authorized": False,
    }


def validate_gate_b_binding(payload: Mapping[str, Any]) -> dict[str, Any]:
    raw = _mapping(payload.get("gate_b"), "gate_b")
    require(raw.get("mode") == GATE_B_MODE, "Gate B mode binding mismatch")
    require(raw.get("decision") == GATE_B_DECISION, "Gate B decision binding mismatch")

    baseline_id = _nonempty(raw.get("baseline_id"), "gate_b.baseline_id")
    require(bool(ID_RE.fullmatch(baseline_id)), "Gate B baseline_id has invalid format")
    require(
        "a30" not in baseline_id
        and "a31" not in baseline_id
        and "49+41" not in baseline_id,
        "Gate B baseline_id must not reuse legacy A3.0/A3.1 identity",
    )

    candidate_count = _strict_int(
        raw.get("candidate_count"),
        "gate_b.candidate_count",
    )
    card_count = _strict_int(raw.get("card_count"), "gate_b.card_count", minimum=1)
    require(
        raw.get("unexplained_card_count") == 0,
        "Gate B unexplained_card_count must be zero",
    )
    require(
        raw.get("historical_issue_56_completion_claimed") is False,
        "historical issue #56 completion must remain false",
    )
    require(
        raw.get("production_eligible") is False,
        "Gate B production eligibility must remain false",
    )

    return {
        "mode": GATE_B_MODE,
        "decision": GATE_B_DECISION,
        "baseline_id": baseline_id,
        "baseline_fingerprint": _sha256(
            raw.get("baseline_fingerprint"),
            "gate_b.baseline_fingerprint",
        ),
        "parity_fingerprint": _sha256(
            raw.get("parity_fingerprint"),
            "gate_b.parity_fingerprint",
        ),
        "candidate_projection_sha256": _sha256(
            raw.get("candidate_projection_sha256"),
            "gate_b.candidate_projection_sha256",
        ),
        "card_ledger_sha256": _sha256(
            raw.get("card_ledger_sha256"),
            "gate_b.card_ledger_sha256",
        ),
        "candidate_count": candidate_count,
        "card_count": card_count,
        "unexplained_card_count": 0,
        "historical_issue_56_completion_claimed": False,
        "production_eligible": False,
    }


def expected_replay_input_sha256(gate_b: Mapping[str, Any]) -> str:
    return canonical_sha256(
        {
            "baseline_id": gate_b["baseline_id"],
            "baseline_fingerprint": gate_b["baseline_fingerprint"],
            "parity_fingerprint": gate_b["parity_fingerprint"],
            "candidate_projection_sha256": gate_b["candidate_projection_sha256"],
            "card_ledger_sha256": gate_b["card_ledger_sha256"],
        }
    )


def validate_replays(
    payload: Mapping[str, Any],
    *,
    gate_b: Mapping[str, Any],
) -> list[dict[str, Any]]:
    raw_rows = payload.get("replays")
    require(isinstance(raw_rows, list), "replays must be a list")
    require(len(raw_rows) == 2, "Gate C requires exactly two deterministic replay observations")

    expected_input = expected_replay_input_sha256(gate_b)
    normalized: list[dict[str, Any]] = []
    seen_ids: set[str] = set()

    for index, raw_value in enumerate(raw_rows, start=1):
        raw = _mapping(raw_value, f"replay row {index}")
        replay_id = _nonempty(raw.get("replay_id"), f"replay row {index} replay_id")
        require(bool(REPLAY_ID_RE.fullmatch(replay_id)), f"invalid replay_id: {replay_id}")
        require(replay_id not in seen_ids, f"duplicate replay_id: {replay_id}")
        seen_ids.add(replay_id)
        require(
            replay_id == f"replay-{index:02d}",
            "replay observations must be ordered replay-01 then replay-02",
        )

        require(
            raw.get("execution_class") == "offline_shadow_replay",
            f"{replay_id} execution_class mismatch",
        )
        require(
            raw.get("input_identity_sha256") == expected_input,
            f"{replay_id} input identity drift",
        )
        require(
            raw.get("candidate_projection_sha256")
            == gate_b["candidate_projection_sha256"],
            f"{replay_id} candidate projection drift",
        )
        require(
            raw.get("card_ledger_sha256") == gate_b["card_ledger_sha256"],
            f"{replay_id} card ledger drift",
        )

        candidate_count = _strict_int(
            raw.get("candidate_count"),
            f"{replay_id}.candidate_count",
        )
        card_count = _strict_int(
            raw.get("card_count"),
            f"{replay_id}.card_count",
            minimum=1,
        )
        require(
            candidate_count == gate_b["candidate_count"],
            f"{replay_id} candidate count drift",
        )
        require(card_count == gate_b["card_count"], f"{replay_id} card count drift")
        require(
            raw.get("unexplained_card_count") == 0,
            f"{replay_id} has unexplained cards",
        )
        require(
            raw.get("duplicate_candidate_count") == 0,
            f"{replay_id} duplicate candidates detected",
        )

        state_write_count = _strict_int(
            raw.get("state_write_count"),
            f"{replay_id}.state_write_count",
        )
        candidate_write_count = _strict_int(
            raw.get("candidate_write_count"),
            f"{replay_id}.candidate_write_count",
        )
        review_write_count = _strict_int(
            raw.get("review_write_count"),
            f"{replay_id}.review_write_count",
        )
        database_write_count = _strict_int(
            raw.get("database_write_count"),
            f"{replay_id}.database_write_count",
        )
        require(
            state_write_count
            + candidate_write_count
            + review_write_count
            + database_write_count
            == 0,
            f"{replay_id} replay must be read-only",
        )

        normalized.append(
            {
                "replay_id": replay_id,
                "execution_class": "offline_shadow_replay",
                "input_identity_sha256": expected_input,
                "semantic_output_sha256": _sha256(
                    raw.get("semantic_output_sha256"),
                    f"{replay_id}.semantic_output_sha256",
                ),
                "candidate_projection_sha256": gate_b[
                    "candidate_projection_sha256"
                ],
                "card_ledger_sha256": gate_b["card_ledger_sha256"],
                "candidate_count": candidate_count,
                "card_count": card_count,
                "unexplained_card_count": 0,
                "duplicate_candidate_count": 0,
                "state_write_count": 0,
                "candidate_write_count": 0,
                "review_write_count": 0,
                "database_write_count": 0,
            }
        )

    first, second = normalized
    require(
        first["semantic_output_sha256"] == second["semantic_output_sha256"],
        "deterministic replay semantic output drift",
    )
    require(
        first["candidate_projection_sha256"]
        == second["candidate_projection_sha256"],
        "deterministic replay candidate projection drift",
    )
    require(
        first["card_ledger_sha256"] == second["card_ledger_sha256"],
        "deterministic replay card ledger drift",
    )
    require(
        first["candidate_count"] == second["candidate_count"]
        and first["card_count"] == second["card_count"],
        "deterministic replay count drift",
    )
    return normalized


def build_ready_result(
    payload: Mapping[str, Any],
) -> dict[str, Any]:
    require(payload.get("schema_version") == 1, "unexpected Gate C schema")
    require(payload.get("mode") == MODE, "unexpected Gate C mode")
    require(payload.get("issue_number") == ISSUE_NUMBER, "issue binding mismatch")

    gate_b = validate_gate_b_binding(payload)
    replays = validate_replays(payload, gate_b=gate_b)

    identity = {
        "gate_b": gate_b,
        "replay_input_sha256": expected_replay_input_sha256(gate_b),
        "semantic_output_sha256": replays[0]["semantic_output_sha256"],
        "replays": replays,
    }
    replay_identity_sha256 = canonical_sha256(identity)

    return {
        "schema_version": 1,
        "mode": MODE,
        "issue_number": ISSUE_NUMBER,
        "decision": READY_DECISION,
        "identity": identity,
        "replay_identity_sha256": replay_identity_sha256,
        "deterministic_replay_verified": True,
        "duplicate_free_verified": True,
        "idempotency_verified": True,
        "second_replay_no_mutation_verified": True,
        "historical_issue_56_completion_claimed": False,
        "production_eligible": False,
        "promotion_ready": False,
        "weekly_shadow_cycles_complete": False,
        "next_gate": {
            "name": "two_consecutive_weekly_shadow_cycles",
            "required_cycle_count": 2,
            "requires_distinct_weekly_campaigns": True,
            "requires_exact_gate_c_replay_identity": replay_identity_sha256,
            "requires_zero_unexplained_cards": True,
            "requires_ambiguity_to_review_or_excluded": True,
            "requires_duplicate_free_replay": True,
            "production_canary_authorized": False,
        },
        "safety": safety_contract(),
    }


def validate_prior_result(
    prior: Mapping[str, Any],
    *,
    expected_ready: Mapping[str, Any],
) -> None:
    require(prior.get("schema_version") == 1, "prior Gate C schema mismatch")
    require(prior.get("mode") == MODE, "prior Gate C mode mismatch")
    require(prior.get("issue_number") == ISSUE_NUMBER, "prior Gate C issue mismatch")
    require(
        prior.get("decision") in {READY_DECISION, NO_OP_DECISION},
        "prior Gate C result is not complete",
    )
    require(
        prior.get("replay_identity_sha256")
        == expected_ready["replay_identity_sha256"],
        "prior Gate C replay identity differs",
    )
    require(
        prior.get("deterministic_replay_verified") is True,
        "prior deterministic replay proof missing",
    )
    require(
        prior.get("duplicate_free_verified") is True,
        "prior duplicate-free proof missing",
    )
    require(
        prior.get("idempotency_verified") is True,
        "prior idempotency proof missing",
    )
    require(
        prior.get("second_replay_no_mutation_verified") is True,
        "prior no-mutation proof missing",
    )
    require(
        prior.get("historical_issue_56_completion_claimed") is False,
        "unsafe prior historical completion claim",
    )
    require(
        prior.get("production_eligible") is False,
        "unsafe prior Gate C production eligibility",
    )
    require(
        prior.get("promotion_ready") is False,
        "unsafe prior Gate C promotion readiness",
    )
    require(
        prior.get("weekly_shadow_cycles_complete") is False,
        "prior Gate C must not claim weekly shadow completion",
    )
    require(prior.get("safety") == safety_contract(), "prior Gate C safety mismatch")

    normalized = dict(prior)
    normalized["decision"] = READY_DECISION
    require(
        normalized == expected_ready,
        "prior Gate C result bytes differ from current replay identity",
    )


def build_result(
    payload: Mapping[str, Any],
    *,
    prior: Mapping[str, Any] | None = None,
) -> dict[str, Any]:
    ready = build_ready_result(payload)
    if prior is None:
        return ready

    validate_prior_result(prior, expected_ready=ready)
    result = dict(ready)
    result["decision"] = NO_OP_DECISION
    return result


def load_json(path: Path, label: str) -> dict[str, Any]:
    require(path.is_file(), f"{label} is missing: {path}")
    require(not path.is_symlink(), f"symlinked {label} forbidden: {path}")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise GateCError(f"invalid {label} JSON: {exc}") from exc
    require(isinstance(payload, dict), f"{label} must be a JSON object")
    return payload


def write_create_only(path: Path, result: Mapping[str, Any]) -> None:
    require(not path.exists(), f"output already exists: {path}")
    require(path.parent.is_dir(), f"output parent missing: {path.parent}")
    require(not path.parent.is_symlink(), "symlinked output parent forbidden")
    path.write_bytes(canonical_bytes(result))


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Validate deterministic read-only replay and NO_OP/idempotency evidence "
            "for the distinct ALDI weekly baseline."
        )
    )
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--prior", type=Path)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()

    try:
        payload = load_json(args.input, "Gate C input")
        prior = load_json(args.prior, "prior Gate C result") if args.prior else None
        result = build_result(payload, prior=prior)
        if args.output is not None:
            write_create_only(args.output, result)
    except GateCError as exc:
        print(f"NEW_BASELINE_GATE_C_RESULT=BLOCKED reason={exc}")
        return 20

    print(f"NEW_BASELINE_GATE_C_RESULT={result['decision']}")
    print(f"REPLAY_IDENTITY_SHA256={result['replay_identity_sha256']}")
    print("DETERMINISTIC_REPLAY_VERIFIED=true")
    print("SECOND_REPLAY_NO_MUTATION_VERIFIED=true")
    print("HISTORICAL_ISSUE_56_COMPLETION_CLAIMED=false")
    print("PRODUCTION_ELIGIBLE=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
