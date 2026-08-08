from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-lidl-source-refresh-r3-promotion-retry.yml"
INSTALLER = ROOT / "tools" / "runner" / "install-lidl-r3-promotion-retry-dispatcher.sh"
FINALIZER = ROOT / "tools" / "runner" / "run-lidl-r3-promotion-retry-owner-finalizer.sh"
DISPATCHER = ROOT / "tools" / "runner" / "lidl_r3_promotion_retry_dispatcher.py"


def test_retry_workflow_binds_explicit_runtime_and_fresh_authorization() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for marker in (
        "github.event.issue.number == 361",
        "github.actor == 'rozkalnsandris'",
        "sender.get('id')!=int(os.environ['EXPECTED_OWNER_ID'])",
        "runtime=([0-9a-f]{40})",
        "commits/{runtime}/pulls",
        "compare/{runtime}...main",
        "retired R3 authorization comment cannot be reused",
        "Owner authorization — R3 promotion retry",
        "Previous authorization comment `5227260615` is retired and may not be reused",
        "authorization_version':'lidl-source-refresh-r3-promotion-authorization-v2-retry'",
        "decision':'approve_exact_r3_promotion_retry'",
        "automatic_retry':False",
        "/usr/local/sbin/hermes-deals-lidl-r3-promotion-retry-dispatch",
        "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a",
    ):
        assert marker in text
    assert "merge_commit_sha" not in text
    assert "actions/checkout" not in text


def test_retry_workflow_self_hosted_surface_is_fixed_and_non_general() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "runs-on: [self-hosted, Linux, ARM64, hermes-deals-audit]" in text
    assert "sudo --non-interactive /usr/local/sbin/hermes-deals-lidl-r3-promotion-retry-dispatch" in text
    for forbidden in (
        "workflow_dispatch:",
        "pull_request_target:",
        "repository_dispatch:",
        "sudo bash",
        "docker.sock",
        "permissions: write-all",
        "automatic_retry':True",
        "profile_promotion':True",
        "database_write':True",
        "review_write':True",
        "production_deploy':True",
    ):
        assert forbidden not in text


def test_retry_installer_and_finalizer_only_register_capability() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    finalizer = FINALIZER.read_text(encoding="utf-8")
    for marker in (
        "PROMOTION_EXECUTED=false",
        "CORPUS_WRITE=false",
        "AUTOMATIC_RETRY=false",
        "RUNNER_HAS_DOCKER_GROUP=false",
        "/usr/local/sbin/hermes-deals-lidl-r3-promotion-retry-dispatch",
        "/etc/sudoers.d/hermes-deals-lidl-r3-promotion-retry",
    ):
        assert marker in installer
        assert marker in finalizer
    assert "commits/$TARGET_SHA/pulls" in finalizer
    assert "merge_commit_sha" not in finalizer
    assert "NEXT_GITHUB_COMMAND=/hermes-lidl-source-refresh-r3-promote-retry" in finalizer
    assert "auth=<fresh-auth-comment-id>" in finalizer


def test_retry_dispatcher_binds_fresh_auth_to_committed_receipt_and_evidence() -> None:
    text = DISPATCHER.read_text(encoding="utf-8")
    for marker in (
        "RETIRED_AUTH_ID = 5227260615",
        "retry authorization comment ID invalid/retired",
        "receipt.get(\"authorization_comment_id\") != auth_id",
        "authority.get(\"promotion\")",
        "fresh_authorization_comment_id",
        "fresh_live_raw_sha256_provenance_only",
        "expected_gate_a_state\": \"WAIT_PROFILE\"",
        "PROFILE_PROMOTION=false",
        "AUTOMATIC_RETRY=false",
    ):
        assert marker in text
    for forbidden in (
        "review-profile.json\").write",
        "docker",
        "systemctl restart",
        "git checkout",
        "git reset",
    ):
        assert forbidden not in text
