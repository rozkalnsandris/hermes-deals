"""Synthetic staging regression tests. These do NOT prove any real scheduled run."""
from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sys

import pytest

TOOLS = Path(__file__).resolve().parents[2] / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import netto_weekly_shadow_artifact as stage
from netto_shadow_promotion import EvidenceBinding


def fixture(tmp_path):
    root = tmp_path / "raw"
    root.mkdir()
    binding = {
        "manifest_path": str(root / "manifest.json"),
        "manifest_sha256": "a" * 64,
        "html_path": str(root / "store.html"),
        "html_sha256": "b" * 64,
        "pdf_path": str(root / "offer.pdf"),
        "pdf_sha256": "c" * 64,
        "evidence_status": "pdf_bound",
        "parser_identity": "netto_store_page_plus_current_prospect_pdf_v3",
        "store_external_id": "5659", "scope": "family_primary_netto",
        "valid_from": "2026-10-19", "valid_until": "2026-10-24",
    }
    identity = EvidenceBinding.from_mapping(binding).identity_sha256()
    selector = {
        "strategy": "netto_weekly_verified_source_selector_v1",
        "campaign_key": "synthetic-test-only",
        "campaign_window": {"start": "2026-10-19", "end": "2026-10-24"},
        "evidence_identity_sha256": identity,
        "binding": binding,
        "selection": {"fallback_to_older_campaign_allowed": False},
        "review_only": True, "promotion_ready": False,
    }
    report = {
        "schema_version": 1, "strategy": stage.SHADOW_STRATEGY,
        "store_external_id": "5659", "scope": "family_primary_netto",
        "campaign_key": "synthetic-test-only",
        "valid_from": "2026-10-19", "valid_until": "2026-10-24",
        "manifest_sha256": binding["manifest_sha256"],
        "html_sha256": binding["html_sha256"],
        "pdf_sha256": binding["pdf_sha256"],
        "parser_identity": binding["parser_identity"],
        "evidence_identity_sha256": identity,
        "source_card_accounting": "unknown",
        "source_card_breakdown": dict(stage.UNKNOWN_BREAKDOWN),
        "execution_outcome": "extraction_complete_coverage_unverified",
        "failure_category": None, "shadow_extraction_completed": True,
        "shadow_acceptance_passed": False, "issue_28_two_real_transitions_ready": False,
        "review_only": True, "promotion_ready": False,
        "production_write_authorized": False, "database_write_performed": False,
        "review_write_performed": False, "publication_write_performed": False,
        "html_extracted_offer_count": 5, "pdf_daily_special_page_count": 0,
        "pdf_daily_special_candidate_count": 0,
    }
    selector_path = tmp_path / "selector.json"
    report_path = tmp_path / "shadow-report.json"
    selector_path.write_text(json.dumps(selector), encoding="utf-8")
    report_path.write_text(json.dumps(report), encoding="utf-8")
    return root, selector_path, report_path, selector, report


def test_staged_files_are_exactly_the_future_attestor_members(tmp_path):
    root, selector, report, _, _ = fixture(tmp_path)
    target = tmp_path / "scheduled-artifact"
    result = stage.stage_shadow_members(selector, report, target, raw_root=root, event="schedule")
    assert result["shadow_acceptance_passed"] is False
    assert result["issue_28_two_real_transitions_ready"] is False
    assert sorted(p.name for p in target.iterdir()) == ["SHA256SUMS", "selector.json", "shadow-report.json"]
    assert (target / "selector.json").read_bytes() == selector.read_bytes()
    assert (target / "shadow-report.json").read_bytes() == report.read_bytes()
    sums = (target / "SHA256SUMS").read_text().splitlines()
    expected = {
        f"{sha256((target / name).read_bytes()).hexdigest()}  {name}"
        for name in ("selector.json", "shadow-report.json")
    }
    assert set(sums) == expected
    with pytest.raises(stage.ShadowArtifactStageError, match="already exists"):
        stage.stage_shadow_members(selector, report, target, raw_root=root, event="schedule")


@pytest.mark.parametrize("event", ["workflow_dispatch", "push", "manual", ""])
def test_non_scheduled_events_do_not_create_files(tmp_path, event):
    root, selector, report, _, _ = fixture(tmp_path)
    target = tmp_path / "out"
    with pytest.raises(stage.ShadowArtifactStageError, match="manual"):
        stage.stage_shadow_members(selector, report, target, raw_root=root, event=event)
    assert not target.exists()


@pytest.mark.parametrize("changes", [
    {"source_card_breakdown": {"total_source_cards": 0}},
    {"source_card_accounting": "complete"},
    {"shadow_acceptance_passed": True},
    {"issue_28_two_real_transitions_ready": True},
    {"execution_outcome": "failed"},
    {"pdf_sha256": "d" * 64},
    {"html_extracted_offer_count": -1},
    {"pdf_daily_special_candidate_count": False},
])
def test_unverified_or_mismatched_input_fails_before_staging(tmp_path, changes):
    root, selector, report, _, payload = fixture(tmp_path)
    payload.update(changes)
    report.write_text(json.dumps(payload), encoding="utf-8")
    target = tmp_path / "out"
    with pytest.raises(stage.ShadowArtifactStageError):
        stage.stage_shadow_members(selector, report, target, raw_root=root, event="schedule")
    assert not target.exists()


def test_outside_source_safety_and_symlink_rejections(tmp_path):
    root, selector, report, _, _ = fixture(tmp_path)
    nested = root / "artifact"
    with pytest.raises(stage.ShadowArtifactStageError, match="raw evidence"):
        stage.stage_shadow_members(selector, report, nested, raw_root=root, event="schedule")
    link = tmp_path / "selector-link.json"
    link.symlink_to(selector)
    with pytest.raises(stage.ShadowArtifactStageError, match="non-symlink"):
        stage.stage_shadow_members(link, report, tmp_path / "out", raw_root=root, event="schedule")
    assert not (tmp_path / "out").exists()
