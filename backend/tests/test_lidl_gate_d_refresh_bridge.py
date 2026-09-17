from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
SYNC_WORKFLOW = ROOT / ".github/workflows/hermes-lidl-source-sync.yml"
SYNC_DISPATCHER = ROOT / "tools/runner/hermes-deals-lidl-source-sync-dispatch"
SYNC_INSTALLER = ROOT / "tools/runner/install-lidl-source-sync-bridge.sh"
REFRESH_WORKFLOW = ROOT / ".github/workflows/hermes-lidl-gate-d-registration-refresh.yml"
REFRESH_DISPATCHER = ROOT / "tools/runner/hermes-deals-lidl-gate-d-registration-refresh-dispatch"
REFRESH_INSTALLER = ROOT / "tools/runner/install-lidl-gate-d-registration-refresh-bridge.sh"
RUNBOOK = ROOT / "docs/LIDL_GATE_D_REFRESH_BRIDGE_RUNBOOK.md"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_lidl_source_sync_is_fixed_checkout_and_fast_forward_only():
    source = _text(SYNC_DISPATCHER)
    assert "REPO='/home/andris/hermes-deals-audit-source-lidl'" in source
    assert "FIXED_FETCH_URL='https://github.com/rozkalnsandris/hermes-deals.git'" in source
    assert "artifact directory symlink or alias rejected" in source
    assert "/home/github-runner/_work/_temp/lidl-source-sync-*" in source
    assert "SOURCE_CHECKOUT_OWNER_DRIFT" in source
    assert "SHALLOW_CHECKOUT_UNSUPPORTED" in source
    assert "SOURCE_BRANCH_NOT_MAIN" in source
    assert "SOURCE_CHECKOUT_DIRTY" in source
    assert "SOURCE_ORIGIN_MISMATCH" in source
    assert "'refs/heads/main:refs/remotes/origin/main'" in source
    assert 'merge-base --is-ancestor "$HEAD_BEFORE" "$TARGET_SHA"' in source
    assert 'merge-base --is-ancestor "$TARGET_SHA" "$REMOTE_MAIN_SHA"' in source
    assert '-c core.hooksPath=/dev/null merge --ff-only --quiet "$TARGET_SHA"' in source
    assert "TARGET_NOT_REACHABLE_FROM_REMOTE_MAIN" in source
    assert "TARGET_NOT_FAST_FORWARD" in source
    lowered = source.lower()
    for forbidden in ("git reset", "git rebase", "git checkout", "git switch", "git pull", "git clean", "--force", "systemctl", "docker ", "psql", "alembic"):
        assert forbidden not in lowered


def test_source_sync_bridge_bootstrap_is_inert_and_source_bound():
    installer = _text(SYNC_INSTALLER)
    assert "EXPECTED_SHA=\"$1\"" in installer
    assert "REPO='/home/andris/hermes-deals'" in installer
    assert "SOURCE_REL='tools/runner/hermes-deals-lidl-source-sync-dispatch'" in installer
    assert "github-runner must not be a member of the docker group" in installer
    assert "visudo -cf \"$TMP/sudoers\"" in installer
    assert "github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-lidl-source-sync-dispatch *" in installer
    assert "Bootstrap registration only. It never fetches or runs the dispatcher." in installer
    assert "LIDL_SOURCE_SYNC_EXECUTED=false" not in installer
    assert "SOURCE_SYNC_EXECUTED=false" in installer
    assert "sudo --non-interactive /usr/local/sbin/hermes-deals-lidl-source-sync-dispatch" not in installer


def test_source_sync_workflow_is_owner_exact_main_ci_bound_and_no_checkout():
    workflow = _text(SYNC_WORKFLOW)
    assert "workflow_dispatch:" in workflow
    assert "expected_main_sha:" in workflow
    assert "EXPECTED_OWNER_LOGIN: rozkalnsandris" in workflow
    assert 'EXPECTED_OWNER_ID: "277435981"' in workflow
    assert "requested SHA is not exact current main" in workflow
    assert "exact current main has no successful push CI run" in workflow
    assert "'event':'push'" in workflow
    self_hosted = workflow.split("  sync-rpi5:", 1)[1]
    assert "permissions: {}" in self_hosted
    assert "actions/checkout" not in self_hosted
    assert "sudo --non-interactive /usr/local/sbin/hermes-deals-lidl-source-sync-dispatch" in self_hosted
    assert "${{ inputs.expected_main_sha }}" not in self_hosted
    assert "APPROVED_SHA: ${{ needs.authorize.outputs.sha }}" in self_hosted
    assert "registration-refresh" not in self_hosted


def test_registration_refresh_is_fixed_existing_installer_and_reviewed_source_bound():
    source = _text(REFRESH_DISPATCHER)
    assert "REPO='/home/andris/hermes-deals-audit-source-lidl'" in source
    assert "INSTALLER_REL='tools/runner/install_lidl_gate_d_control_nonrewind.py'" in source
    assert "GATE_DISPATCHER_REL='tools/runner/lidl_gate_d_control.py'" in source
    assert "PLANNER_REL='tools/lidl_weekly_gate_d_activation_plan.py'" in source
    assert "RUNTIME_REL='tools/lidl_weekly_gate_d_runtime.py'" in source
    assert "SOURCE_HEAD_NOT_TARGET" in source
    assert "REVIEWED_SOURCE_IDENTITY_DRIFT" in source
    assert "RUNNER_DOCKER_GROUP_FORBIDDEN" in source
    assert "installed dispatcher content drift" in source
    assert "/home/github-runner/_work/_temp/lidl-gate-d-registration-refresh-*" in source
    assert "artifact directory metadata invalid" in source
    assert "--registration-sha \"$TARGET_SHA\"" in source
    assert "--on-calendar \"$ON_CALENDAR\"" in source
    assert "--retry-delay \"$RETRY_DELAY\"" in source
    assert "--retry-window \"$RETRY_WINDOW\"" in source
    assert "--max-attempts \"$MAX_ATTEMPTS\"" in source
    assert "--timeout-start \"$TIMEOUT_START\"" in source
    assert "shell=True" not in source
    assert "py_compile" not in source
    assert "compile(source, str(path), 'exec')" in source


def test_registration_refresh_validates_prior_identity_and_only_moves_forward():
    source = _text(REFRESH_DISPATCHER)
    assert "Gate D plan fingerprint drift" in source
    assert "Gate D staged unit content drift" in source
    assert "PRIOR_DISPATCHER_CONTENT_DRIFT" in source
    assert "PRIOR_SUDOERS_CONTENT_DRIFT" in source
    assert 'merge-base --is-ancestor "$PRIOR_SHA" "$TARGET_SHA"' in source
    assert "PRIOR_REGISTRATION_NOT_ANCESTOR" in source
    assert "retired-${PRIOR_SHA}-to-${TARGET_SHA}" in source
    assert "RETIREMENT_PATH_ALREADY_EXISTS" in source
    assert "RETIRE_SUDOERS_FAILED" in source
    assert "RETIRE_CONFIG_FAILED" in source
    assert "RETIRE_DISPATCHER_FAILED" in source
    lowered = source.lower()
    for forbidden in ("git reset", "git rebase", "git checkout", "git switch", "git pull", "git clean", "--force", "curl ", "wget "):
        assert forbidden not in lowered
    assert "rollback_performed':False" in source
    assert "cleanup_performed':False" in source


def test_registration_refresh_bootstrap_only_registers_fixed_bridge():
    installer = _text(REFRESH_INSTALLER)
    assert "REPO='/home/andris/hermes-deals'" in installer
    assert "SOURCE_REL='tools/runner/hermes-deals-lidl-gate-d-registration-refresh-dispatch'" in installer
    assert "github-runner must not be a member of the docker group" in installer
    assert "github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-lidl-gate-d-registration-refresh-dispatch *" in installer
    assert "Bootstrap registration only. It never syncs the dedicated checkout or refreshes Gate D." in installer
    assert "LIDL_GATE_D_REGISTRATION_REFRESH_EXECUTED=false" in installer
    assert "LIDL_SOURCE_SYNC_EXECUTED=false" in installer
    assert "install_lidl_gate_d_control_nonrewind.py" not in installer
    assert "sudo --non-interactive /usr/local/sbin/hermes-deals-lidl-gate-d-registration-refresh-dispatch" not in installer


def test_registration_workflow_exact_main_ci_receipt_and_privileged_surface():
    workflow = _text(REFRESH_WORKFLOW)
    assert "workflow_dispatch:" in workflow
    assert "expected_main_sha:" in workflow
    assert "EXPECTED_OWNER_LOGIN: rozkalnsandris" in workflow
    assert 'EXPECTED_OWNER_ID: "277435981"' in workflow
    assert "requested SHA is not exact current main" in workflow
    assert "exact current main has no successful push CI run" in workflow
    self_hosted = workflow.split("  refresh-rpi5:", 1)[1]
    assert "permissions: {}" in self_hosted
    assert "actions/checkout" not in self_hosted
    assert "sudo --non-interactive /usr/local/sbin/hermes-deals-lidl-gate-d-registration-refresh-dispatch" in self_hosted
    assert "${{ inputs.expected_main_sha }}" not in self_hosted
    assert "APPROVED_SHA: ${{ needs.authorize.outputs.sha }}" in self_hosted
    assert "Dedicated checkout source sync: **not chained**" in workflow
    assert "registration summary field set mismatch" in workflow
    assert "registration receipt contains forbidden mutation" in workflow
    for field in ("gate_d_runtime_performed", "collector_execution_performed", "production_database_write_performed", "review_write_performed", "publication_write_performed", "scheduler_change_performed", "systemd_change_performed", "timer_activation_performed", "production_deploy_performed", "rollback_performed", "cleanup_performed"):
        assert field in workflow


def test_source_tests_never_execute_live_bridges_and_runbook_separates_owner_gates():
    test_source = Path(__file__).read_text(encoding="utf-8")
    assert "import " + "subprocess" not in test_source
    assert "from " + "subprocess" not in test_source
    runbook = _text(RUNBOOK)
    assert "Bootstrap registration — separate LIVE authorization" in runbook
    assert "Dedicated checkout sync — separate LIVE authorization" in runbook
    assert "Gate D registration refresh — separate LIVE authorization" in runbook
    assert "Activation — separate LIVE authorization" in runbook
    assert "451aabbd432a8776bed70209f966690ab647ac66b69947b77545fc1638e44c9e" in runbook
    assert "non-authoritative after #910 source drift" in runbook
    assert "no automatic retry, rollback, cleanup" in runbook.lower()
    assert "**Production deploy: NO.**" in runbook
