from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "netto-normal-price-finalizer-integration-audit.yml"


def test_workflow_is_owner_merged_pr_gated() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in text
    assert "audit:netto-normal-price-integration-v1" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert '"merged": pr.get("merged") is True' in text


def test_workflow_requires_real_non_test_python_integration() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "netto_normal_price_finalizer" in text
    assert "backend/tests/" in text
    assert "integration_present" in text
    assert "integration_reference_count" in text
    assert "Fail closed when finalizer is not integrated" in text
    assert "exit 2" in text


def test_workflow_preserves_evidence_before_fail_closed_gate() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Run focused four-case finalizer regression" in text
    assert "actions/upload-artifact@v4" in text
    assert text.index("Upload integration evidence before pass/fail gate") < text.index("Fail closed when finalizer is not integrated")
    assert "Focused four-case regression: **PASS**" in text


def test_workflow_never_mutates_parser_or_production() -> None:
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
    assert "Repository / DB / Review / publication / deploy writes: **false**" in text
    assert "Review-only / promotion-ready: **true / false**" in text
