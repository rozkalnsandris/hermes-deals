from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-lidl-r3-promotion-status-v2.yml"


def test_status_v2_selects_authorized_run_without_retry_capability() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for marker in (
        "github.event.issue.number == 361",
        "github.event.issue.pull_request == null",
        "sender.get('id')!=277435981",
        "/hermes-lidl-r3-status-v2 command=5227503666",
        "j.get('name')=='authorize'",
        "authorize[0].get('conclusion')=='success'",
        "expected one authorize-success promotion run",
        "actions: read",
        "runs-on: ubuntu-24.04",
        "probe is read-only; promotion was not retried",
    ):
        assert marker in text

    for forbidden in (
        "self-hosted",
        "sudo ",
        "rerun_workflow",
        "rerun_failed",
        "/rerun",
        "lidl_r3_source_refresh_promotion_apply.py",
    ):
        assert forbidden not in text
