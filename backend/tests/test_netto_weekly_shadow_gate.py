"""Synthetic-only source guard regressions; no collector or host execution."""
from __future__ import annotations

from datetime import date
from hashlib import sha256
from pathlib import Path
import sys

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import netto_weekly_shadow_gate as gate
from netto_shadow_promotion import EvidenceBinding
from netto_weekly_transition_state import canonical_bytes


DAY = date(2026, 10, 19)


def observation(*, status="pdf_bound", action="run_shadow", recorded=True):
    binding = {
        "manifest_path": "/synthetic/manifest.json",
        "manifest_sha256": "a" * 64,
        "html_path": "/synthetic/store.html",
        "html_sha256": "b" * 64,
        "pdf_path": "/synthetic/prospect.pdf" if status == "pdf_bound" else None,
        "pdf_sha256": "c" * 64 if status == "pdf_bound" else None,
        "evidence_status": status,
        "parser_identity": "netto_store_page_plus_current_prospect_pdf_v3",
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "valid_from": "2026-10-19",
        "valid_until": "2026-10-24",
        "no_pdf_reason": None if status == "pdf_bound" else "verified source has no PDF",
    }
    evidence_identity = EvidenceBinding.from_mapping(binding).identity_sha256()
    selector = {
        "schema_version": 1,
        "strategy": "netto_weekly_verified_source_selector_v1",
        "campaign_key": "synthetic-only-campaign",
        "campaign_window": {"start": "2026-10-19", "end": "2026-10-24"},
        "evidence_identity_sha256": evidence_identity,
        "binding": binding,
        "selection": {"fallback_to_older_campaign_allowed": False},
        "review_only": True,
        "promotion_ready": False,
    }
    state = {
        "schema_version": 1,
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "trigger_event": "schedule",
        "today": DAY.isoformat(),
        "current_campaign_key": selector["campaign_key"],
        "current_evidence_identity": evidence_identity,
        "current_evidence_status": status,
        "current_validity": selector["campaign_window"],
        "current_decision": {"action": action},
        "transition_recorded": recorded,
        "production_write_authorized": False,
        "issue_28_two_real_transitions_ready": False,
    }
    receipt = {
        "state_sha256": sha256(canonical_bytes(state)).hexdigest(),
        "current_campaign_key": selector["campaign_key"],
        "current_evidence_identity": evidence_identity,
        "current_action": action,
        "transition_recorded": recorded,
        "production_write_authorized": False,
        "issue_28_two_real_transitions_ready": False,
    }
    return state, receipt, selector


def eligible(state, receipt, selector, *, event="schedule", run_attempt=1, today=DAY):
    return gate.is_scheduled_shadow_eligible(
        state, receipt, selector, event=event, run_attempt=run_attempt, today=today,
    )


def test_scheduled_bound_pdf_new_campaign_qualifies_for_extraction_only():
    state, receipt, selector = observation()
    assert eligible(state, receipt, selector) is True
    assert state["issue_28_two_real_transitions_ready"] is False
    assert receipt["issue_28_two_real_transitions_ready"] is False


@pytest.mark.parametrize("event,attempt", [
    ("workflow_dispatch", 1), ("push", 1), ("schedule", 2), ("schedule", 0),
])
def test_manual_and_rerun_events_never_qualify(event, attempt):
    state, receipt, selector = observation()
    assert eligible(state, receipt, selector, event=event, run_attempt=attempt) is False


@pytest.mark.parametrize("change", [
    lambda s, r, x: s.update(current_campaign_key="wrong"),
    lambda s, r, x: s.update(current_evidence_identity="d" * 64),
    lambda s, r, x: s.update(current_evidence_status="verified_no_pdf"),
    lambda s, r, x: s.update(current_validity={"start": "2026-10-20", "end": "2026-10-24"}),
    lambda s, r, x: s.update(trigger_event="workflow_dispatch"),
    lambda s, r, x: s.update(production_write_authorized=True),
    lambda s, r, x: r.update(production_write_authorized=True),
    lambda s, r, x: r.update(issue_28_two_real_transitions_ready=True),
    lambda s, r, x: r.update(state_sha256="0" * 64),
    lambda s, r, x: r.update(current_action="skip"),
    lambda s, r, x: x.update(evidence_identity_sha256="0" * 64),
])
def test_mismatched_campaign_or_write_authority_fails_closed(change):
    state, receipt, selector = observation()
    change(state, receipt, selector)
    with pytest.raises(ValueError):
        eligible(state, receipt, selector)


@pytest.mark.parametrize("action,recorded", [
    ("skip_unchanged", False), ("wait_for_validity", False),
    ("run_shadow", False),
])
def test_no_action_or_duplicate_transition_cannot_create_proof(action, recorded):
    state, receipt, selector = observation(action=action, recorded=recorded)
    assert eligible(state, receipt, selector) is False


def test_verified_no_pdf_and_early_or_expired_day_skip():
    state, receipt, selector = observation(status="verified_no_pdf")
    assert eligible(state, receipt, selector) is False
    state, receipt, selector = observation()
    for day in (date(2026, 10, 18), date(2026, 10, 25)):
        state["today"] = day.isoformat()
        receipt["state_sha256"] = sha256(canonical_bytes(state)).hexdigest()
        assert eligible(state, receipt, selector, today=day) is False


def test_workflow_remains_statically_disarmed_and_has_exact_safe_step_wiring():
    content = (TOOLS.parent / ".github/workflows/netto-weekly-transition-state.yml").read_text(encoding="utf-8")
    assert "NETTO_SHADOW_RUN_ENABLED: 'false'" in content
    assert content.count("NETTO_SHADOW_RUN_ENABLED") >= 2
    assert "name: Build offline shadow extraction receipt" in content
    assert "name: Upload scheduled shadow extraction artifact" in content
    assert "name: Gate first-attempt scheduled shadow extraction" in content
    assert "steps.shadow_gate.outputs.eligible == 'true'" in content
    assert "steps.shadow_stage.outcome == 'success'" in content
    assert "netto-weekly-shadow-scheduled-\${{ github.run_id }}" in content
    assert "tools/netto_weekly_shadow_report.py" in content
    assert "tools/netto_weekly_shadow_artifact.py" in content
    assert content.index("name: Upload immutable transition artifact") < content.index("name: Build offline shadow extraction receipt")
    assert "DATABASE_URL: sqlite+pysqlite:///:memory:" in content
