from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/hermes-aldi-registration-refresh.yml"
DISPATCHER = ROOT / "tools/runner/hermes-deals-aldi-registration-refresh-dispatch"
INSTALLER = ROOT / "tools/runner/install-aldi-registration-refresh-bridge.sh"
RUNBOOK = ROOT / "docs/ALDI_REGISTRATION_REFRESH_BRIDGE_RUNBOOK.md"
SOURCE_SYNC = ROOT / ".github/workflows/rpi-source-sync.yml"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_shell_sources_are_fail_closed_and_bootstrap_preserves_staging_on_failure():
    dispatcher = _text(DISPATCHER)
    installer = _text(INSTALLER)
    assert "set -Eeuo pipefail" in dispatcher
    assert "set -Eeuo pipefail" in installer
    assert "/usr/bin/bash -n \"$SOURCE\"" in installer
    assert "INSTALL_STAGING_PRESERVED" in installer
    assert "KEEP_TMP=false" in installer


def test_workflow_is_owner_only_exact_current_main_and_exact_push_ci_bound():
    workflow = _text(WORKFLOW)
    assert "workflow_dispatch:" in workflow
    assert "expected_main_sha:" in workflow
    assert "EXPECTED_OWNER_LOGIN: rozkalnsandris" in workflow
    assert 'EXPECTED_OWNER_ID: "277435981"' in workflow
    assert 'WORKFLOW_REF"] != "refs/heads/main"' in workflow
    assert "requested SHA is not exact current main" in workflow
    assert '"event": "push"' in workflow
    assert "exact current main has no successful push CI run" in workflow


def test_self_hosted_job_has_no_checkout_and_only_fixed_registration_dispatcher():
    workflow = _text(WORKFLOW)
    self_hosted = workflow.split("  refresh-rpi5:", 1)[1]
    assert "permissions: {}" in self_hosted
    assert "hermes-deals-audit" in self_hosted
    assert "actions/checkout" not in self_hosted
    assert "sudo --non-interactive /usr/local/sbin/hermes-deals-aldi-registration-refresh-dispatch" in self_hosted
    assert "${{ inputs.expected_main_sha }}" not in self_hosted
    assert "APPROVED_SHA: ${{ needs.authorize.outputs.sha }}" in self_hosted


def test_dispatcher_is_exact_source_bound_and_invokes_only_two_fixed_installers():
    dispatcher = _text(DISPATCHER)
    assert "REPO='/home/andris/hermes-deals'" in dispatcher
    assert "PRODUCER_REL='tools/runner/install-aldi-new-baseline-weekly-shadow-producer-dispatcher.sh'" in dispatcher
    assert "VISUAL_REL='tools/runner/install-aldi-visual-card-bridge-v2-dispatcher.sh'" in dispatcher
    assert 'rev-parse HEAD)" == "$TARGET_SHA"' in dispatcher
    assert "status --porcelain=v1 --untracked-files=all" in dispatcher
    assert "ls-files --error-unmatch" in dispatcher
    assert "/usr/bin/bash -n \"$REPO/$rel\"" in dispatcher
    assert '/usr/bin/bash "$REPO/$PRODUCER_REL" "$TARGET_SHA"' in dispatcher
    assert '/usr/bin/bash "$REPO/$VISUAL_REL" "$TARGET_SHA"' in dispatcher
    assert "/usr/local/sbin/hermes-deals-aldi-new-baseline-weekly-shadow-producer-dispatch" not in dispatcher
    assert "/usr/local/sbin/hermes-deals-aldi-visual-card-bridge-v2" not in dispatcher


def test_dispatcher_verifies_both_registered_shas_and_runner_least_privilege_state():
    dispatcher = _text(DISPATCHER)
    assert "PRODUCER_CONF='/etc/hermes-deals-audits.d/aldi-new-baseline-weekly-shadow-producer.conf'" in dispatcher
    assert "VISUAL_CONF='/etc/hermes-deals-audits.d/aldi-visual-card-bridge-v2.conf'" in dispatcher
    assert '[[ "$PRODUCER_AFTER" == "$TARGET_SHA" ]]' in dispatcher
    assert '[[ "$VISUAL_AFTER" == "$TARGET_SHA" ]]' in dispatcher
    assert "systemctl is-active --quiet \"$RUNNER_SERVICE\"" in dispatcher
    assert "RUNNER_DOCKER_GROUP_FORBIDDEN" in dispatcher
    assert "RUNNER_DOCKER_GROUP_DRIFT_AFTER_REFRESH" in dispatcher


def test_receipt_explicitly_rejects_runtime_data_scheduler_canary_and_deploy_side_effects():
    workflow = _text(WORKFLOW)
    dispatcher = _text(DISPATCHER)
    for field in (
        "network_source_read_performed",
        "weekly_shadow_prepare_performed",
        "visual_diagnostic_performed",
        "request_created",
        "request_accepted",
        "production_database_write_performed",
        "review_write_performed",
        "publication_write_performed",
        "scheduler_change_performed",
        "systemd_change_performed",
        "container_mutation_performed",
        "canary_performed",
        "production_deploy_performed",
        "rollback_performed",
        "cleanup_performed",
    ):
        assert field in dispatcher
        assert field in workflow
    assert 'if any(payload[field] is not False for field in false_fields):' in workflow
    assert 'payload["root_registration_mutation_started"] is not True' in workflow


def test_bootstrap_installer_only_registers_new_bridge_and_never_runs_aldi_refresh():
    installer = _text(INSTALLER)
    assert "EXPECTED_SHA=\"$1\"" in installer
    assert 'rev-parse HEAD)" == "$EXPECTED_SHA"' in installer
    assert "github-runner must not be a member of the docker group" in installer
    assert "visudo -cf \"$TMP/sudoers\"" in installer
    assert "github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-aldi-registration-refresh-dispatch *" in installer
    assert "ALDI_REGISTRATION_REFRESH_EXECUTED=false" in installer
    assert "install-aldi-new-baseline-weekly-shadow-producer-dispatcher.sh" not in installer
    assert "install-aldi-visual-card-bridge-v2-dispatcher.sh" not in installer


def test_source_sync_remains_checkout_only_and_runbook_keeps_live_gates_separate():
    source_sync = _text(SOURCE_SYNC)
    runbook = _text(RUNBOOK)
    assert "Root bridge registration: **not chained**" in source_sync
    assert "hermes-deals-aldi-registration-refresh-dispatch" not in source_sync
    assert "bootstrap registration" in runbook.lower()
    assert "not self-hosting" in runbook.lower()
    assert "separate explicit owner live authorization" in runbook.lower()
    assert "live aldi source read" in runbook.lower()
    assert "request acceptance" in runbook.lower()
    assert "scheduler/systemd" in runbook.lower()
    assert "**production deploy: no.**" in runbook.lower()
