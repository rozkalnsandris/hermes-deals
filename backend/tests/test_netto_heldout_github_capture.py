from __future__ import annotations

from datetime import date
import importlib.util
from pathlib import Path
import subprocess
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "netto_heldout_live_source.py"
SPEC = importlib.util.spec_from_file_location("netto_heldout_live_source", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


def bundle(slug: str, start: date, end: date):
    return MODULE.NettoStoreProspectBundle(
        store_url="https://www.netto-online.de/filialen/test/5659",
        prospect_url=f"https://viewer.invalid/{slug}",
        prospect_slug=slug,
        store_html=b"store",
        prospect_html=b"viewer",
        valid_from=start,
        valid_until=end,
        validity_text=f"{start} - {end}",
        selected_store_cookie_present=True,
        elapsed_ms=0,
        prospect_pdf=b"%PDF-fixture",
    )


def test_sunday_gap_selects_published_upcoming_campaign() -> None:
    selected = MODULE.select_latest_nonexpired(
        [
            bundle("hz32_hasb", date(2026, 8, 3), date(2026, 8, 8)),
            bundle("hz33_new", date(2026, 8, 10), date(2026, 8, 15)),
        ],
        as_of=date(2026, 8, 9),
    )
    assert selected.prospect_slug == "hz33_new"
    assert selected.valid_from == date(2026, 8, 10)


def test_latest_window_ambiguity_fails_closed() -> None:
    with pytest.raises(MODULE.HeldoutLiveSourceError, match="ambiguous"):
        MODULE.select_latest_nonexpired(
            [
                bundle("campaign-a", date(2026, 8, 10), date(2026, 8, 15)),
                bundle("campaign-b", date(2026, 8, 10), date(2026, 8, 15)),
            ],
            as_of=date(2026, 8, 9),
        )


def test_no_nonexpired_campaign_fails_closed() -> None:
    with pytest.raises(MODULE.HeldoutLiveSourceError, match="no non-expired"):
        MODULE.select_latest_nonexpired(
            [bundle("expired", date(2026, 8, 3), date(2026, 8, 8))],
            as_of=date(2026, 8, 9),
        )


def test_authoritative_family_source_is_exact_5659() -> None:
    source = MODULE.load_family_source(ROOT)
    assert source.chain == "netto"
    assert source.store_external_id == "5659"
    assert source.scope == "family_primary_netto"
    assert source.url.endswith("/5659")


def test_github_capture_runner_is_read_only_and_exact_sha_bound() -> None:
    runner = ROOT / "tools" / "run-netto-heldout-github-capture-v01.sh"
    subprocess.run(["bash", "-n", str(runner)], check=True)
    text = runner.read_text(encoding="utf-8")
    assert "checkout HEAD mismatch" in text
    assert "PyMuPDF 1.28.0 required" in text
    assert "netto_heldout_live_source.py" in text
    assert "netto_heldout_source_selector.py" in text
    assert "netto_heldout_page_capture.py" in text
    assert "truth_available_at_freeze" in text
    assert "review_only" in text
    assert "promotion_ready" in text
    for forbidden in (
        "sudo ",
        "docker ",
        "psql ",
        "systemctl ",
        "/home/andris",
    ):
        assert forbidden not in text


def test_workflow_is_owner_gated_github_hosted_and_nonproduction() -> None:
    path = ROOT / ".github" / "workflows" / "netto-heldout-github-capture.yml"
    text = path.read_text(encoding="utf-8")
    assert "audit:netto-heldout-github-v1" in text
    assert "pull_request_target:" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert "runs-on: ubuntu-latest" in text
    assert "ref: ${{ needs.authorize.outputs.sha }}" in text
    assert "actions/upload-artifact@v6" in text
    assert "Production deployment: **not authorized**" in text
    assert "Database/Review writes: **not authorized**" in text
    assert "Promotion ready: **false**" in text
    for forbidden in (
        "self-hosted",
        "sudo --non-interactive",
        "docker compose",
        "psql ",
    ):
        assert forbidden not in text
