from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "netto-normal-price-finalizer-audit.yml"


def test_workflow_is_owner_merged_pr_gated() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in text
    assert "audit:netto-normal-price-finalizer-v1" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert '"merged": pr.get("merged") is True' in text


def test_workflow_pins_all_four_known_normal_price_cases() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for needle, price in (
        ("Lederkäse", "1.69"),
        ("Grill-/Pfannenkäse", "1.99"),
        ("Hähnchen-Geschnetzeltes", "3.79"),
        ("Melone Galia", "1.99"),
    ):
        assert needle in text
        assert price in text
    assert "backend/tests/test_netto_normal_price_finalizer.py" in text
    assert "tools/netto_normal_price_finalizer.py" in text


def test_workflow_is_read_only_and_does_not_touch_production() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
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
    assert "actions/upload-artifact@v4" in text
    assert "Repository / DB / Review / publication / deploy writes: **false**" in text
    assert "Review-only / promotion-ready: **true / false**" in text
