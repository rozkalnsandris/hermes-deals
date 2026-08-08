from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-lidl-r3-promotion-status.yml"


def test_r3_status_bridge_is_owner_only_github_hosted_and_read_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    required = (
        "github.event.issue.number == 361",
        "github.actor == 'rozkalnsandris'",
        "sender.get('id') != 277435981",
        "github.event.comment.body == '/hermes-lidl-r3-status command=5227503666'",
        "runs-on: ubuntu-24.04",
        "actions: read",
        "issues: write",
        "hermes-lidl-source-refresh-r3-promotion.yml/runs",
        "expected exactly one R3 promotion run after command",
        "promotion command comment: `5227503666`",
        "status probe: read-only; no rerun/retry/promotion command issued",
    )
    for marker in required:
        assert marker in text

    forbidden = (
        "self-hosted",
        "sudo ",
        "workflow_dispatch",
        "rerun_failed",
        "rerun_workflow",
        "/rerun",
        "POST /repos/",
        "corpus_write",
        "lidl_r3_source_refresh_promotion_apply.py",
    )
    for marker in forbidden:
        assert marker not in text


def test_r3_status_bridge_binds_exact_promotion_command() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    exact = (
        "/hermes-lidl-source-refresh-r3-promote pr=410 "
        "fingerprint=8aaf1f96a119e51c980a45da80031d5abd2db65d4cdc3516bd5368fd0537c7f9 "
        "auth=5227260615"
    )
    assert exact in text
    assert "issues/comments/5227503666" in text
    assert "run.get('event') != 'issue_comment'" in text
    assert "run.get('head_branch') != 'main'" in text
