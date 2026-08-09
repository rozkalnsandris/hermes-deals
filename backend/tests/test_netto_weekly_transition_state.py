from __future__ import annotations

from datetime import date, datetime, timezone
import hashlib
from pathlib import Path
import sys

TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

from netto_shadow_promotion import EvidenceBinding
from netto_weekly_transition_state import STRATEGY, build_state, canonical_bytes


def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def selector(tmp_path: Path, campaign: str, start: str, end: str) -> dict:
    root = tmp_path / campaign
    root.mkdir()
    manifest = root / "manifest.json"
    html = root / "store.html"
    pdf = root / "source.pdf"
    manifest.write_text('{"campaign":"%s"}\n' % campaign, encoding="utf-8")
    html.write_text("<html>netto</html>\n", encoding="utf-8")
    pdf.write_bytes(b"%PDF-1.4\nfixture-" + campaign.encode() + b"\n%%EOF\n")
    raw = {
        "manifest_path": str(manifest),
        "manifest_sha256": sha(manifest),
        "html_path": str(html),
        "html_sha256": sha(html),
        "evidence_status": "pdf_bound",
        "pdf_path": str(pdf),
        "pdf_sha256": sha(pdf),
        "parser_identity": "netto_store_prospect_v1",
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "valid_from": start,
        "valid_until": end,
        "no_pdf_reason": None,
    }
    binding = EvidenceBinding.from_mapping(raw)
    binding.validate()
    return {
        "schema_version": 1,
        "strategy": "netto_heldout_verified_source_selector_v1",
        "campaign_key": campaign,
        "campaign_window": {"start": start, "end": end},
        "evidence_identity_sha256": binding.identity_sha256(),
        "binding": raw,
        "selection": {"fallback_to_older_campaign_allowed": False},
        "review_only": True,
        "promotion_ready": False,
    }


def test_two_consecutive_scheduled_campaigns_prove_issue_28(tmp_path: Path) -> None:
    first_selector = selector(tmp_path, "hz33_hasb", "2026-08-10", "2026-08-15")
    first, first_receipt = build_state(
        first_selector,
        today=date(2026, 8, 10),
        observed_at=datetime(2026, 8, 10, 6, 17, tzinfo=timezone.utc),
        trigger_event="schedule",
        previous=None,
        previous_state_sha256=None,
    )
    assert first["strategy"] == STRATEGY
    assert first["current_decision"]["action"] == "run_shadow"
    assert first["transition_recorded"] is True
    assert first["consecutive_unattended_transition_count"] == 1
    assert first["issue_28_two_real_transitions_ready"] is False
    assert first_receipt["state_sha256"] == hashlib.sha256(canonical_bytes(first)).hexdigest()

    second_selector = selector(tmp_path, "hz34_hasb", "2026-08-17", "2026-08-22")
    second, _ = build_state(
        second_selector,
        today=date(2026, 8, 17),
        observed_at=datetime(2026, 8, 17, 6, 17, tzinfo=timezone.utc),
        trigger_event="schedule",
        previous=first,
        previous_state_sha256=first_receipt["state_sha256"],
    )
    assert second["current_decision"]["action"] == "run_shadow"
    assert second["transition_recorded"] is True
    assert len(second["scheduled_transitions"]) == 2
    assert second["consecutive_unattended_transition_count"] == 2
    assert second["issue_28_two_real_transitions_ready"] is True
    assert all(row["production_write_authorized"] is False for row in second["scheduled_transitions"])


def test_manual_canary_never_counts_as_unattended_transition(tmp_path: Path) -> None:
    current = selector(tmp_path, "hz33_hasb", "2026-08-10", "2026-08-15")
    state, _ = build_state(
        current,
        today=date(2026, 8, 10),
        observed_at=datetime(2026, 8, 10, 0, 30, tzinfo=timezone.utc),
        trigger_event="workflow_dispatch",
        previous=None,
        previous_state_sha256=None,
    )
    assert state["current_decision"]["action"] == "run_shadow"
    assert state["transition_recorded"] is False
    assert state["scheduled_transitions"] == []
    assert state["consecutive_unattended_transition_count"] == 0


def test_sunday_before_new_window_waits_without_transition(tmp_path: Path) -> None:
    upcoming = selector(tmp_path, "hz34_hasb", "2026-08-17", "2026-08-22")
    state, _ = build_state(
        upcoming,
        today=date(2026, 8, 16),
        observed_at=datetime(2026, 8, 16, 6, 17, tzinfo=timezone.utc),
        trigger_event="schedule",
        previous=None,
        previous_state_sha256=None,
    )
    assert state["current_decision"]["action"] == "wait_for_window"
    assert state["transition_recorded"] is False
    assert state["scheduled_transitions"] == []


def test_unchanged_campaign_is_noop_and_not_duplicated(tmp_path: Path) -> None:
    current = selector(tmp_path, "hz33_hasb", "2026-08-10", "2026-08-15")
    first, receipt = build_state(
        current,
        today=date(2026, 8, 10),
        observed_at=datetime(2026, 8, 10, 6, 17, tzinfo=timezone.utc),
        trigger_event="schedule",
        previous=None,
        previous_state_sha256=None,
    )
    replay, _ = build_state(
        current,
        today=date(2026, 8, 11),
        observed_at=datetime(2026, 8, 11, 6, 17, tzinfo=timezone.utc),
        trigger_event="schedule",
        previous=first,
        previous_state_sha256=receipt["state_sha256"],
    )
    assert replay["current_decision"]["action"] == "unchanged_noop"
    assert replay["transition_recorded"] is False
    assert len(replay["scheduled_transitions"]) == 1
