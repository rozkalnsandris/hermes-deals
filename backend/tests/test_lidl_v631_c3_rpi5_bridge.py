from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/lidl-v631-c3-readonly-rpi5.yml"
DISPATCHER = ROOT / "tools/runner/lidl-v631-c3-readonly-dispatcher.sh"
INSTALLER = ROOT / "tools/runner/install-lidl-v631-c3-readonly-dispatcher.sh"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_c3_rpi5_workflow_is_owner_gated_and_does_not_checkout_pr_code() -> None:
    source = _text(WORKFLOW)
    assert "workflow_dispatch:" in source
    assert "EXPECTED_OWNER_LOGIN: rozkalnsandris" in source
    assert "EXPECTED_OWNER_ID: '277435981'" in source
    assert "runs-on:\n      - self-hosted\n      - Linux\n      - ARM64\n      - hermes-deals-audit" in source
    assert "actions/checkout" not in source
    assert "pull_request:" not in source
    assert "pull_request_target:" not in source
    assert "sudo --non-interactive /usr/local/sbin/hermes-deals-lidl-v631-c3-readonly" in source
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in source
    assert "issues: write" not in source
    assert "pull-requests: write" not in source


def test_c3_authorizer_binds_registration_current_main_and_runtime_blobs() -> None:
    source = _text(WORKFLOW)
    for marker in (
        "if not pr.get('merged') or not pr.get('merged_at')",
        "registration merge is not reachable from current main",
        "c31df993e94707ffa35b82c4976f4b79e1154add",
        "65273e99a855e3ea26c65329745c5101d4d2d742",
        "5c183c4459275c99c7d0f9d66a7a5c425384a5be",
        "eed8e2d6b8d3054c741ad71b433c53518f5fec3e",
        "3f19e354a5ede64d064f532f31490a1404ea946e",
        "d6a64564901ce38dd4a790d44ead89be917f1b21",
        "bb0e40363afeb89a176b95bc3b9314dbef075a5d",
        "5c7c8d5e32ef84308b688213224b2528d99378e0",
        "backend/locks/runtime-py311.txt",
        "scripts/verify-python-lock-environment.py",
        "current main C3 blob drift",
    ):
        assert marker in source


def test_dispatcher_uses_root_owned_pinned_runtime_and_stays_read_only() -> None:
    source = _text(DISPATCHER)
    assert "RUNTIME_ROOT='/opt/hermes-deals-audits/lidl-v631-c3-readonly/runtime-py311'" in source
    assert 'RUNTIME_PYTHON="$RUNTIME_ROOT/bin/python"' in source
    assert "runtime_lock_sha256" in source
    assert "runtime_inventory_sha256" in source
    assert "verify-python-lock-environment.py" in source
    assert 'run_owner "$RUNTIME_PYTHON" -c "import $module"' in source
    assert "docker ps" in source
    assert "docker inspect" in source
    assert "postgres:18.4-bookworm" in source
    assert "DATABASE_URL=\"$DATABASE_URL\"" in source
    assert "PYTHONDONTWRITEBYTECODE=1" in source
    assert "lidl_v631_c3_readonly_preflight.py" in source
    assert "--expected-head \"$CURRENT_SHA\"" in source
    assert "--corpus-root \"$CORPUS_ROOT\"" in source
    assert "merge-base --is-ancestor \"$registered_merge_sha\" \"$CURRENT_SHA\"" in source
    assert "[[ \"$RC\" -eq 0 || \"$RC\" -eq 30 ]]" in source
    assert "production_baseline_before') != report.get('production_baseline_after" in source
    assert "'transaction_read_only':'on'" in source
    assert "'transaction_isolation':'repeatable read'" in source
    assert "'snapshot_id':0" in source
    assert "'source_snapshots':1,'offer_candidates':1" in source
    assert "report.get('transaction_rolled_back') is not True" in source
    assert "CORPUS_AFTER=\"$(corpus_tree)\"" in source
    assert "audit Git index changed" in source

    forbidden = (
        "docker exec",
        "docker run",
        "docker compose up",
        "docker start",
        "docker restart",
        "pip install",
        "python3 -m pip",
        "apt install",
        "apt-get install",
        "apply_lidl_v631_semantic_persistence_plan",
        "git checkout",
        "git reset",
        "git pull",
        "git fetch",
    )
    for token in forbidden:
        assert token not in source


def test_dispatcher_emits_sanitized_blocked_evidence_before_runtime_or_db_access() -> None:
    source = _text(DISPATCHER)
    assert "write_blocked_summary()" in source
    assert "'result':'BLOCKED'" in source
    assert "'reason':'preflight_blocked'" in source
    assert "write_blocked_summary\n  exit 30" in source
    blocked_definition = source.index("write_blocked_summary()")
    runtime_check = source.index("pinned C3 audit runtime missing or unsafe")
    docker_check = source.index("expected exactly one running hermes-deals production db container")
    assert blocked_definition < runtime_check < docker_check


def test_dispatcher_private_material_is_root_owned_and_sanitized_output_is_fixed() -> None:
    source = _text(DISPATCHER)
    assert "PRIVATE_ROOT='/var/lib/hermes-deals/lidl-v631-c3-readonly-private'" in source
    assert "EVIDENCE_ROOT='/var/lib/hermes-deals/lidl-v631-c3-readonly'" in source
    assert "root:root:700" in source
    assert "root:root:755" in source
    assert "db-inspect.json" in source
    assert "root:root:600" in source
    assert "chown root:root \"$SUMMARY\"" in source
    assert "chmod 0644 \"$SUMMARY\"" in source
    assert "POSTGRES_PASSWORD" in source
    assert "summary.update" in source
    summary_block = source[source.index("summary={", source.index("SUMMARY=\"$DEST/summary.json\"")) :]
    assert "DATABASE_URL" not in summary_block
    assert "POSTGRES_PASSWORD" not in summary_block
    assert "github-runner:github-runner" not in source
    assert "artifact-dir" not in source


def test_workflow_reads_only_fixed_sanitized_evidence_path() -> None:
    source = _text(WORKFLOW)
    fixed = "/var/lib/hermes-deals/lidl-v631-c3-readonly/${{ github.run_id }}-${{ github.run_attempt }}/summary.json"
    assert fixed in source
    assert "ARTIFACT_DIR" not in source
    assert "RUNNER_TEMP" not in source
    for key in (
        "production_database_write",
        "review_write",
        "production_publish",
        "production_deploy",
        "corpus_write",
        "source_replacement",
        "systemd_change",
        "scheduler_change",
        "docker_exec",
        "container_create",
        "package_install",
    ):
        assert key in source
    assert "transaction_rolled_back" in source
    assert "expected_first_apply_delta" in source
    assert "exact_key_counts" in source
    assert "runtime_lock_sha256" in source
    assert "runtime_inventory_sha256" in source


def test_installer_provisions_only_hash_pinned_audit_runtime_and_registration() -> None:
    source = _text(INSTALLER)
    assert "[[ ${EUID:-$(id -u)} -eq 0 ]]" in source
    assert "audit clone is not exact clean main at installer SHA" in source
    assert "EXPECTED_C3_BLOB='c31df993e94707ffa35b82c4976f4b79e1154add'" in source
    assert "EXPECTED_CORE_BLOB='65273e99a855e3ea26c65329745c5101d4d2d742'" in source
    assert "EXPECTED_PLANNER_BLOB='5c183c4459275c99c7d0f9d66a7a5c425384a5be'" in source
    assert "EXPECTED_DISPATCHER_BLOB='eed8e2d6b8d3054c741ad71b433c53518f5fec3e'" in source
    assert "EXPECTED_LOCK_BLOB='d6a64564901ce38dd4a790d44ead89be917f1b21'" in source
    assert "EXPECTED_MANIFEST_BLOB='bb0e40363afeb89a176b95bc3b9314dbef075a5d'" in source
    assert "EXPECTED_VERIFIER_BLOB='5c7c8d5e32ef84308b688213224b2528d99378e0'" in source
    assert "RUNTIME_PARENT='/opt/hermes-deals-audits/lidl-v631-c3-readonly'" in source
    assert "python3 -m venv" in source
    assert "--require-hashes --only-binary=:all:" in source
    assert "PIP_CONFIG_FILE=/dev/null" in source
    assert "verify-python-lock-environment.py" in source
    assert "chown -hR root:root \"$BUILD_VENV\"" in source
    assert "AUDIT_RUNTIME_PACKAGE_INSTALL=true" in source
    assert "SYSTEM_PACKAGE_INSTALL=false" in source
    assert "/usr/local/sbin/hermes-deals-lidl-v631-c3-readonly" in source
    assert "/etc/sudoers.d/hermes-deals-lidl-v631-c3-readonly" in source
    assert "RUNNER_HAS_DOCKER_GROUP=false" in source
    assert "systemctl is-active" in source
    assert "systemctl enable" not in source
    assert "systemctl restart" not in source
    assert "apt install" not in source
    assert "apt-get install" not in source
    assert "docker exec" not in source
    assert "docker run" not in source
    assert "apply_lidl_v631" not in source
    assert "production_database_write=true" not in source.casefold()


def test_workflow_never_invokes_installer() -> None:
    source = _text(WORKFLOW)
    assert "install-lidl-v631-c3-readonly-dispatcher.sh" in source  # blob identity only
    assert "sudo --non-interactive tools/runner/install" not in source
    assert "sudo --non-interactive ./tools/runner/install" not in source
