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
        "1975cab5cb8d9c27104eb10b85ec7018659bfe2c",
        "69bc685ca5792079fdda1e73c09af94dfc28e29c",
        "5c183c4459275c99c7d0f9d66a7a5c425384a5be",
        "40583d1f37b2b50007f024820c1b457869ae621e",
        "94e18cd9979ce4ad789330187a5228dd42684fc9",
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
    assert "RUNTIME_PARENT='/opt/hermes-deals-audits/lidl-v631-c3-readonly'" in source
    assert 'RUNTIME_ROOT="$RUNTIME_PARENT/runtime-py311-${registered_merge_sha:0:12}-${runtime_lock_sha256:0:16}"' in source
    assert 'RUNTIME_PYTHON="$RUNTIME_ROOT/bin/python"' in source
    assert "runtime_python_sha256" in source
    assert "runtime_python_version" in source
    assert '[[ -f "$RUNTIME_PYTHON" && ! -L "$RUNTIME_PYTHON" && -x "$RUNTIME_PYTHON" ]]' in source
    assert 'sys.prefix != expected' in source
    assert 'sys.base_prefix == sys.prefix' in source
    assert "runtime_lock_sha256" in source
    assert "runtime_inventory_sha256" in source
    assert "runtime_python_sha256" in source
    assert "runtime_python_version" in source
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
    assert "REASON_CODE='unexpected_runner_exit'" in source
    assert "RC=30" in source
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
    assert "sanitize_reason_code()" in source
    assert "'result':'BLOCKED'" in source
    assert "'reason':'preflight_blocked'" in source
    assert "'reason_code':reason_code" in source
    assert "write_blocked_summary dispatcher_preflight_blocked\n  exit 30" in source
    blocked_definition = source.index("write_blocked_summary()")
    runtime_check = source.index("pinned C3 audit runtime missing or unsafe")
    docker_check = source.index("expected exactly one running hermes-deals production db container")
    assert blocked_definition < runtime_check < docker_check


def test_dispatcher_sanitizes_child_failure_without_copying_private_log() -> None:
    source = _text(DISPATCHER)
    for code in (
        "domain_validation",
        "database_read_error",
        "unexpected_internal_error",
        "unexpected_runner_exit",
    ):
        assert code in source
    assert "BLOCKED_CODE=(domain_validation|database_read_error|unexpected_internal_error)" in source
    assert "REASON_CODE=\"${BLOCKED_CODES[0]#BLOCKED_CODE=}\"" in source
    assert "summary['reason_code']=reason_code" in source
    assert "summary['traceback']" not in source
    assert "summary['run_log']" not in source


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
    assert "runtime_python_sha256" in source
    assert "runtime_python_version" in source
    assert "runtime Python version mismatch" in source
    assert "BLOCKED reason code invalid" in source
    assert "PASS result must not expose blocked reason code" in source
    for code in (
        "dispatcher_preflight_blocked",
        "domain_validation",
        "database_read_error",
        "unexpected_internal_error",
        "unexpected_runner_exit",
    ):
        assert code in source


def test_installer_provisions_only_hash_pinned_audit_runtime_and_registration() -> None:
    source = _text(INSTALLER)
    assert "[[ ${EUID:-$(id -u)} -eq 0 ]]" in source
    assert "audit clone is not clean main" in source
    assert 'merge-base --is-ancestor "$EXPECTED_SHA" "$HEAD_SHA"' in source
    assert "current audit main blob identity drift" in source
    assert "EXPECTED_C3_BLOB='1975cab5cb8d9c27104eb10b85ec7018659bfe2c'" in source
    assert "EXPECTED_CORE_BLOB='69bc685ca5792079fdda1e73c09af94dfc28e29c'" in source
    assert "EXPECTED_PLANNER_BLOB='5c183c4459275c99c7d0f9d66a7a5c425384a5be'" in source
    assert "EXPECTED_DISPATCHER_BLOB='40583d1f37b2b50007f024820c1b457869ae621e'" in source
    assert "EXPECTED_LOCK_BLOB='d6a64564901ce38dd4a790d44ead89be917f1b21'" in source
    assert "EXPECTED_MANIFEST_BLOB='bb0e40363afeb89a176b95bc3b9314dbef075a5d'" in source
    assert "EXPECTED_VERIFIER_BLOB='5c7c8d5e32ef84308b688213224b2528d99378e0'" in source
    assert "RUNTIME_PARENT='/opt/hermes-deals-audits/lidl-v631-c3-readonly'" in source
    assert 'RUNTIME_ROOT="$RUNTIME_PARENT/runtime-py311-${EXPECTED_SHA:0:12}-${LOCK_SHA:0:16}"' in source
    assert 'run_owner python3 -m venv --copies "$RUNTIME_ROOT"' in source
    assert "--require-hashes --only-binary=:all:" in source
    assert "PIP_CONFIG_FILE=/dev/null" in source
    assert "verify-python-lock-environment.py" in source
    assert '[[ ! -e "$RUNTIME_ROOT" ]]' in source
    assert 'chown -hR root:root "$RUNTIME_ROOT"' in source
    assert 'BUILD_UMASK="$(umask)"' in source
    assert "umask 022" in source
    assert 'umask "$BUILD_UMASK"' in source
    assert 'chmod -R a+rX,go-w "$RUNTIME_ROOT"' in source
    assert r'find "$RUNTIME_ROOT" -xdev \( ! -user root -o ! -group root \)' in source
    assert r'find "$RUNTIME_ROOT" -xdev \( -type f -o -type d \) -perm /022' in source
    assert '[[ -f "$RUNTIME_PYTHON" && ! -L "$RUNTIME_PYTHON" && -x "$RUNTIME_PYTHON" ]]' in source
    assert 'run_owner test -x "$RUNTIME_ROOT"' in source
    assert 'run_owner test -x "$RUNTIME_PYTHON"' in source
    assert "installed C3 runtime Python cannot execute as audit owner" in source
    assert "RUNTIME_PYTHON_SHA" in source
    assert "sys.prefix != expected" in source
    assert "sys.base_prefix == sys.prefix" in source
    assert "RUNTIME_COMMITTED=false" in source
    assert "RUNTIME_COMMITTED=true" in source
    assert "RUNTIME_NEXT" not in source
    assert "BUILD_VENV" not in source
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


def test_installer_keeps_build_umask_until_pinned_runtime_is_verified() -> None:
    source = _text(INSTALLER)
    enable = source.index("umask 022")
    pip_install = source.index("-m pip install --no-cache-dir --require-hashes --only-binary=:all:")
    inventory = source.index("pinned C3 runtime inventory SHA invalid")
    import_check = source.index("pinned C3 runtime import failed")
    restore = source.index('umask "$BUILD_UMASK"')
    assert enable < pip_install < inventory < import_check < restore


def test_installer_runtime_is_traversable_after_root_ownership_transfer() -> None:
    source = _text(INSTALLER)
    ownership = source.index('chown -hR root:root "$RUNTIME_ROOT"')
    permissions = source.index('chmod -R a+rX,go-w "$RUNTIME_ROOT"')
    owner_traverse = source.index('run_owner test -x "$RUNTIME_ROOT"')
    owner_python = source.index('run_owner test -x "$RUNTIME_PYTHON"')
    execute_probe = source.index("installed C3 runtime Python cannot execute as audit owner")
    identity = source.index("RUNTIME_PYTHON_VERSION=")
    assert ownership < permissions < owner_traverse < owner_python < execute_probe < identity


def test_workflow_never_invokes_installer() -> None:
    source = _text(WORKFLOW)
    assert "install-lidl-v631-c3-readonly-dispatcher.sh" in source  # blob identity only
    assert "sudo --non-interactive tools/runner/install" not in source
    assert "sudo --non-interactive ./tools/runner/install" not in source
