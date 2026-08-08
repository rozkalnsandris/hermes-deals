from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-lidl-r3-status-push-once.yml"


def test_push_probe_is_path_scoped_github_hosted_and_read_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for marker in (
        "push:",
        "branches: [main]",
        ".github/workflows/hermes-lidl-r3-status-push-once.yml",
        "runs-on: ubuntu-24.04",
        "actions: read",
        "issues: write",
        "j.get('name')=='authorize'",
        "auth[0].get('conclusion')=='success'",
        "NO_AUTHORIZE_SUCCESS_RUN_FOUND",
        "AMBIGUOUS_MULTIPLE_AUTHORIZE_SUCCESS_RUNS",
        "promotion retry issued: `false`",
    ):
        assert marker in text
    for forbidden in (
        "self-hosted",
        "sudo ",
        "workflow_dispatch",
        "rerun_workflow",
        "rerun_failed",
        "/rerun",
        "lidl_r3_source_refresh_promotion_apply.py",
    ):
        assert forbidden not in text
