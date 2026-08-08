from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = REPO_ROOT / ".github" / "workflows" / "w2-production-smoke.yml"


def test_w2_production_smoke_is_owner_only_and_read_only() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")

    assert "issue_comment:" in source
    assert 'expected_command = "/hermes-319 w2-smoke"' in source
    assert 'if os.environ["ISSUE_NUMBER"] != "319":' in source
    assert 'if os.environ["ACTOR"] != owner:' in source
    assert 'if os.environ["TRIGGERING_ACTOR"] != owner:' in source
    assert 'if os.environ["COMMENT_AUTHOR"] != owner:' in source
    assert "w2-production-smoke.yml@refs/heads/main" in source

    assert "hermes-deals-release" in source
    assert "permissions: {}" in source
    assert "actions/checkout" not in source
    assert "secrets." not in source
    assert "sudo " not in source
    assert "docker " not in source.casefold()

    assert 'origin = "http://127.0.0.1:9128"' in source
    assert 'measure("/api/v1/catalog?limit=100", validate_catalog)' in source
    assert 'measure("/api/v1/ui/overview", validate_overview)' in source
    assert 'expected_engine = "batched-current-offers-v1"' in source

    assert "DB/Review/collector/parser/scheduler write authority" in source
