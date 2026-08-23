from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/rpi-source-sync.yml"
DISPATCHER = ROOT / "tools/runner/hermes-deals-rpi-source-sync-dispatch"
INSTALLER = ROOT / "tools/runner/install-rpi-source-sync-bridge.sh"
RUNBOOK = ROOT / "docs/RPI_SOURCE_SYNC_BRIDGE_RUNBOOK.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_shell_sources_are_fail_closed_and_syntax_checked_by_ci_contract():
    dispatcher = _text(DISPATCHER)
    installer = _text(INSTALLER)
    assert "set -Eeuo pipefail" in dispatcher
    assert "set -Eeuo pipefail" in installer
    assert "/usr/bin/bash -n \"$SOURCE\"" in installer
    assert "INSTALL_STAGING_PRESERVED" in installer
    assert "KEEP_TMP=false" in installer


def test_workflow_is_manual_owner_only_and_exact_merged_main_bound():
    workflow = _text(WORKFLOW)
    assert "workflow_dispatch:" in workflow
    assert "target_pr_number:" in workflow
    assert "EXPECTED_OWNER_LOGIN: rozkalnsandris" in workflow
    assert 'EXPECTED_OWNER_ID: "277435981"' in workflow
    assert 'WORKFLOW_REF"] != "refs/heads/main"' in workflow
    assert "source sync requires a merged pull request" in workflow
    assert "same-repository PR head" in workflow
    assert 'comparison.get("status") not in {"ahead", "identical"}' in workflow
    assert "tree_equivalent_pr_head_ci" in workflow
    assert "neither merge SHA nor exact PR head has successful CI" in workflow


def test_self_hosted_job_has_no_checkout_and_only_fixed_dispatcher():
    workflow = _text(WORKFLOW)
    self_hosted = workflow.split("  sync-rpi5:", 1)[1]
    assert "permissions: {}" in self_hosted
    assert "hermes-deals-audit" in self_hosted
    assert "actions/checkout" not in self_hosted
    assert "sudo --non-interactive /usr/local/sbin/hermes-deals-rpi-source-sync-dispatch" in self_hosted
    assert "${{ inputs.target_pr_number }}" not in self_hosted
    assert "APPROVED_SHA: ${{ needs.authorize.outputs.sha }}" in self_hosted


def test_dispatcher_has_exact_checkout_and_fast_forward_contract():
    dispatcher = _text(DISPATCHER)
    assert "REPO='/home/andris/hermes-deals'" in dispatcher
    assert "FIXED_FETCH_URL='https://github.com/rozkalnsandris/hermes-deals.git'" in dispatcher
    assert "status --porcelain=v1 --untracked-files=all" in dispatcher
    assert "branch --show-current" in dispatcher
    assert "rev-parse --is-shallow-repository" in dispatcher
    assert "refs/heads/main:refs/remotes/origin/main" in dispatcher
    assert 'merge-base --is-ancestor "$HEAD_BEFORE" "$TARGET_SHA"' in dispatcher
    assert 'merge-base --is-ancestor "$TARGET_SHA" "$REMOTE_MAIN_SHA"' in dispatcher
    assert '-c core.hooksPath=/dev/null merge --ff-only --quiet "$TARGET_SHA"' in dispatcher
    assert '"$HEAD_AFTER" == "$TARGET_SHA"' in dispatcher
    assert "O_EXCL" in dispatcher
    assert "O_NOFOLLOW" in dispatcher


def test_dispatcher_forbids_broad_mutation_shortcuts():
    dispatcher = _text(DISPATCHER)
    forbidden = [
        "git reset", "git checkout", "git switch", "git pull", "git clean",
        "docker ", "systemctl", "alembic", "psql", "curl ", "wget ",
        "wrangler", "cloudflared",
    ]
    lowered = dispatcher.lower()
    for needle in forbidden:
        assert needle not in lowered
    assert "production_deploy_performed\": False" in dispatcher
    assert "database_write_performed\": False" in dispatcher
    assert "retained_evidence_read_performed\": False" in dispatcher
    assert "diagnostic_execution_performed\": False" in dispatcher


def test_installer_is_registration_only_and_source_bound():
    installer = _text(INSTALLER)
    assert "EXPECTED_SHA=\"$1\"" in installer
    assert 'rev-parse HEAD)" == "$EXPECTED_SHA"' in installer
    assert "github-runner must not be a member of the docker group" in installer
    assert "visudo -cf \"$TMP/sudoers\"" in installer
    assert "github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-rpi-source-sync-dispatch *" in installer
    assert "SOURCE_CHECKOUT_MUTATED=false" in installer
    assert "SOURCE_SYNC_EXECUTED=false" in installer
    assert "git_as_andris -C \"$REPO\" -c credential.helper= fetch" not in installer
    assert "sudo --non-interactive /usr/local/sbin/hermes-deals-rpi-source-sync-dispatch" not in installer


def test_workflow_receipt_is_strict_and_rejects_forbidden_mutations():
    workflow = _text(WORKFLOW)
    assert "expected_fields = {" in workflow
    assert 'if set(payload) != expected_fields:' in workflow
    for field in (
        "production_deploy_performed",
        "database_write_performed",
        "review_write_performed",
        "publication_write_performed",
        "retained_evidence_read_performed",
        "retained_evidence_write_performed",
        "diagnostic_execution_performed",
        "scheduler_change_performed",
        "systemd_change_performed",
        "cloudflare_mutation_performed",
        "container_mutation_performed",
        "package_install_performed",
    ):
        assert field in workflow
    assert 'payload["target_sha"] != os.environ["EXPECTED_SHA"]' in workflow
    assert 'payload["head_after"] != payload["target_sha"]' in workflow


def test_runbook_documents_bootstrap_stop_and_separate_kaufland_gates():
    runbook = _text(RUNBOOK)
    assert "bootstrap registration" in runbook.lower()
    assert "install-rpi-source-sync-bridge.sh" in runbook
    assert "no retry" in runbook.lower()
    assert "#758" in runbook
    assert "Kaufland K3C" in runbook
    assert "Production deploy: **NO**" in runbook
