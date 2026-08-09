from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "netto-normal-price-historical-replay-audit.yml"


def test_workflow_is_owner_merged_pr_and_exact_run_gated() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in text
    assert "audit:netto-normal-price-historical-v1" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert '"merged": pr.get("merged") is True' in text
    assert 'HISTORICAL_RUN_ID: "31216060947"' in text
    assert "075ec36fa6c3a2e71029da5e573f783a40e001c501c520815793b2da982b4888" in text


def test_workflow_requires_all_four_historical_cases() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for needle, price in (
        ("Lederkäse", "1.69"),
        ("Grill-/Pfannenkäse", "1.99"),
        ("Hähnchen-Geschnetzeltes", "3.79"),
        ("Melone Galia", "1.99"),
    ):
        assert needle in text
        assert price in text
    assert "historical replay artifact must be unique" in text
    assert "historical replay member SHA must be unique" in text


def test_workflow_binds_current_finalizer_and_junit_without_production_writes() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "tools/netto_normal_price_finalizer.py" in text
    assert "backend/tests/test_netto_normal_price_finalizer.py" in text
    assert "--junitxml=.netto-normal-price-historical/junit.xml" in text
    assert "artifact ZIP/API digest mismatch" in text
    assert "actions/upload-artifact@v4" in text
    for forbidden in (
        "self-hosted",
        "sudo ",
        "docker ",
        "psql ",
        "systemctl ",
        "/home/andris",
        "git push",
    ):
        assert forbidden not in text
    assert "Repository / DB / Review / publication / deploy writes: **false**" in text
    assert "Review-only / promotion-ready: **true / false**" in text
