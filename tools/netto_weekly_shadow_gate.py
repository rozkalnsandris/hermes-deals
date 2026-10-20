#!/usr/bin/env python3
"""Fail-closed scheduled Netto shadow decision gate; does not parse or publish."""
from __future__ import annotations

import argparse
from datetime import date
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping

from netto_weekly_transition_state import canonical_bytes, load_json, normalize_selector


class NettoShadowGateError(ValueError):
    pass


def is_scheduled_shadow_eligible(
    state: Mapping[str, Any],
    receipt: Mapping[str, Any],
    selector: Mapping[str, Any],
    *,
    event: str,
    run_attempt: int,
    today: date,
) -> bool:
    """Verify the local immutable observation; no coverage/acceptance claims."""
    if event != "schedule" or type(run_attempt) is not int or run_attempt != 1:
        return False
    binding, campaign, identity = normalize_selector(selector)
    decision = state.get("current_decision")
    if not isinstance(decision, Mapping):
        raise NettoShadowGateError("missing transition decision")
    if (
        state.get("schema_version") != 1
        or state.get("store_external_id") != "5659"
        or state.get("scope") != "family_primary_netto"
        or state.get("trigger_event") != "schedule"
        or state.get("today") != today.isoformat()
        or state.get("current_campaign_key") != campaign
        or state.get("current_evidence_identity") != identity
        or state.get("current_evidence_status") != binding.evidence_status.value
        or state.get("current_validity") != {
            "start": binding.valid_from.isoformat(),
            "end": binding.valid_until.isoformat(),
        }
        or receipt.get("state_sha256") != sha256(canonical_bytes(state)).hexdigest()
        or receipt.get("current_campaign_key") != campaign
        or receipt.get("current_evidence_identity") != identity
        or receipt.get("current_action") != decision.get("action")
        or receipt.get("transition_recorded") is not state.get("transition_recorded")
        or state.get("production_write_authorized") is not False
        or receipt.get("production_write_authorized") is not False
        or state.get("issue_28_two_real_transitions_ready") is not False
        or receipt.get("issue_28_two_real_transitions_ready") is not False
    ):
        raise NettoShadowGateError("transition/selector/receipt binding mismatch")

    # Unchanged campaigns, non-shadow decisions and verified no-PDF state
    # cannot manufacture a successful shadow parser step or artifact.
    if decision.get("action") != "run_shadow" or receipt.get("transition_recorded") is not True:
        return False
    if binding.evidence_status.value != "pdf_bound":
        return False
    if not binding.valid_from <= today <= binding.valid_until:
        return False
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Gate one nonpromoting scheduled shadow extraction")
    parser.add_argument("--state", type=Path, required=True)
    parser.add_argument("--receipt", type=Path, required=True)
    parser.add_argument("--selector", type=Path, required=True)
    parser.add_argument("--event", required=True)
    parser.add_argument("--run-attempt", type=int, required=True)
    parser.add_argument("--today", type=date.fromisoformat, required=True)
    parser.add_argument("--github-output", type=Path, required=True)
    args = parser.parse_args()
    try:
        eligible = is_scheduled_shadow_eligible(
            load_json(args.state),
            load_json(args.receipt),
            load_json(args.selector),
            event=args.event,
            run_attempt=args.run_attempt,
            today=args.today,
        )
        # GitHub owns this environment file; do not create retained source
        # artifacts, append only the fixed boolean output.
        with args.github_output.open("a", encoding="utf-8") as handle:
            handle.write("eligible=" + ("true" if eligible else "false") + "\n")
    except (OSError, ValueError, TypeError):
        print("ERROR|netto_scheduled_shadow_gate_failed", file=sys.stderr)
        return 2
    print("NETTO_SCHEDULED_SHADOW_ELIGIBLE=" + ("true" if eligible else "false"))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
