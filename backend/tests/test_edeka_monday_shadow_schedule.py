from __future__ import annotations

from dataclasses import replace
from datetime import datetime, timezone
import hashlib
import importlib.util
from pathlib import Path
from uuid import UUID

import pytest

from app.parsers.edeka import EdekaParserContext, parse_edeka_html


ROOT = Path(__file__).resolve().parents[2]
PLANNER_PATH = ROOT / "tools" / "edeka_weekly_monitor_activation_plan.py"
CANDIDATE_PATH = ROOT / "config" / "hermes-edeka-weekly-monitor-monday.timer.example"
HEADER_FIXTURE = Path(__file__).parent / "fixtures" / "edeka_weekly_header_offers.html"

SUNDAY_CALENDAR = "Sun *-*-* 00:10:00 Europe/Berlin"
MONDAY_CALENDAR = "Mon *-*-* 00:10:00 Europe/Berlin"
INSTALLED_SUNDAY_TIMER_SHA256 = (
    "6bc3cddbd77a925546032ae0a22abc75631d5f9ef36d01d98731a1bcb54fc31d"
)
MONDAY_CANDIDATE_SHA256 = (
    "214a54a9c652dd38169987ba0672ec5853cc8f17f59734a318f7044ffa0d8178"
)


def _load_planner():
    spec = importlib.util.spec_from_file_location("edeka_monday_shadow_planner", PLANNER_PATH)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def _november_week_html() -> str:
    # Only date substitutions on the already-reviewed, market-bound #945 fixture.
    # Neither the market/link nor product/price identities are invented.
    original = HEADER_FIXTURE.read_text(encoding="utf-8")
    assert "28.09.2026" in original
    assert "03.10.2026" in original
    return original.replace("28.09.2026", "16.11.2026").replace(
        "03.10.2026", "21.11.2026"
    )


def _context(observed_day: int) -> EdekaParserContext:
    return EdekaParserContext(
        snapshot_id=UUID("11111111-2222-4333-8444-555555555555"),
        source_url="https://www.edeka.de/maerkte/071897/angebote/",
        collected_at=datetime(2026, 11, observed_day, 12, tzinfo=timezone.utc),
        public_market_id="071897",
        internal_market_id="587881",
        store_name="EDEKA Patzer",
    )


def test_candidate_changes_only_sunday_to_monday_on_exact_installed_timer() -> None:
    candidate = CANDIDATE_PATH.read_bytes()
    old_line = ("OnCalendar=" + SUNDAY_CALENDAR + "\n").encode()
    new_line = ("OnCalendar=" + MONDAY_CALENDAR + "\n").encode()

    assert candidate.count(b"OnCalendar=") == 1
    assert candidate.count(new_line) == 1
    assert hashlib.sha256(candidate).hexdigest() == MONDAY_CANDIDATE_SHA256

    # Reconstruct the exact reviewed, read-only installed Sunday timer bytes.
    baseline = candidate.replace(new_line, old_line)
    assert hashlib.sha256(baseline).hexdigest() == INSTALLED_SUNDAY_TIMER_SHA256
    assert baseline.replace(old_line, new_line) == candidate
    assert b"Persistent=true\n" in candidate
    assert b"Unit=hermes-edeka-weekly-monitor.service\n" in candidate
    assert b"OnFailure=hermes-edeka-weekly-monitor-failure@%n.service\n" in candidate


def test_existing_nonactivating_planner_emits_exact_monday_candidate(
    tmp_path: Path,
) -> None:
    planner = _load_planner()
    plan = planner.build_activation_plan(
        output_dir=tmp_path / "plan",
        repo_root=Path("/home/andris/hermes-deals-audit-source-edeka"),
        repo_sha="c" * 40,
        python_path=Path("/usr/bin/python3"),
        shadow_evidence_root=Path("/home/andris/hermes-deals-shadow-evidence/edeka"),
        monitor_evidence_root=Path("/home/andris/hermes-deals-edeka-weekly-monitor"),
        cache_root=Path("/home/andris/.cache/hermes-deals-edeka-shadow"),
        on_calendar=MONDAY_CALENDAR,
        retry_delay="30min",
        retry_window="6h",
        max_attempts=3,
        timeout_start="50min",
    )
    generated = (tmp_path / "plan" / planner.TIMER_UNIT).read_bytes()
    assert generated == CANDIDATE_PATH.read_bytes()
    assert plan["schedule"]["on_calendar"] == MONDAY_CALENDAR
    assert plan["unit_sha256"][planner.TIMER_UNIT] == MONDAY_CANDIDATE_SHA256
    assert plan["activation_requires_explicit_owner_authorization"] is True
    assert plan["dry_run"] is True
    for flag in (
        "source_refetch_authorized",
        "systemd_change_authorized",
        "systemd_change_performed",
        "bounded_retry_authorized",
        "production_database_write_authorized",
        "review_write_authorized",
        "publication_authorized",
        "deployment_authorized",
    ):
        assert plan[flag] is False


def test_monday_validity_is_accepted_but_sunday_preview_stays_blocked() -> None:
    html = _november_week_html()
    assert "Gültig ab" not in html
    monday = _context(16)
    offers = parse_edeka_html(html, monday)
    assert len(offers) == 2
    assert offers == parse_edeka_html(html, monday)
    for offer in offers:
        assert str(offer.valid_from) == "2026-11-16"
        assert str(offer.valid_until) == "2026-11-21"
        assert offer.source_store_external_id == "071897"
        assert offer.raw_payload["internal_market_id"] == "587881"
        assert offer.snapshot_id == monday.snapshot_id

    with pytest.raises(ValueError, match="stale or future"):
        parse_edeka_html(html, _context(15))
    with pytest.raises(ValueError, match="stale or future"):
        parse_edeka_html(html, _context(22))
    with pytest.raises(ValueError, match="stale or future"):
        parse_edeka_html(html, _context(1))


def test_monday_run_does_not_relax_market_header_or_footer_guards() -> None:
    html = _november_week_html()
    monday = _context(16)
    with pytest.raises(ValueError, match="configured market"):
        parse_edeka_html(
            html.replace('href="/maerkte/071897/"', 'href="/maerkte/999999/"'),
            monday,
        )
    with pytest.raises(ValueError, match="configured market"):
        parse_edeka_html(
            html.replace(
                "Angebote der Woche bei EDEKA Patzer",
                "Angebote der Woche bei EDEKA Anders",
            ),
            monday,
        )
    with pytest.raises(ValueError, match="no complete validity range"):
        parse_edeka_html(html.replace("bis zum", "bis auf Weiteres"), monday)
    with pytest.raises(ValueError, match="header and footer validity disagree"):
        parse_edeka_html(
            html.replace("<strong>21.11.2026</strong>", "<strong>20.11.2026</strong>"),
            monday,
        )
    # Do not infer an alternative store binding from the same source body.
    with pytest.raises(ValueError, match="configured market"):
        parse_edeka_html(
            html,
            replace(monday, public_market_id="999999"),
        )
