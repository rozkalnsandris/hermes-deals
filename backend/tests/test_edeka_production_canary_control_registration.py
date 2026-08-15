from __future__ import annotations

from hashlib import sha1
from pathlib import Path
import re
from runpy import run_path
import sys

ROOT = Path(__file__).resolve().parents[2]
DISPATCHER = ROOT / "tools/runner/edeka_production_canary_control.py"
INSTALLER = ROOT / "tools/runner/install_edeka_production_canary_control_nonrewind.py"
WORKFLOW = ROOT / ".github/workflows/hermes-edeka-production-canary-control.yml"
EXECUTOR = ROOT / "backend/app/edeka_production_canary.py"
PLAN = ROOT / "config/edeka-production-canary-v01.json"
RUNTIME_LOCK = ROOT / "backend/locks/runtime-py313.txt"

EXPECTED_EXECUTOR_BLOB = "4760fefb3f5de67798b52d7b5d30021fb8bf2ba7"
EXPECTED_PLAN_BLOB = "4c4674534dfc29957a9cc9f05b0df99ca5378b50"
EXPECTED_RUNTIME_LOCK_BLOB = "a2b44faa967be2a703f369d85a5f15cf517975d1"
EXPECTED_WORKFLOW_BLOB = "2906f03b052d8351800ca0a31f96e7ad2b551ec7"


def _blob(path: Path) -> str:
    payload = path.read_bytes()
    return sha1(f"blob {len(payload)}\0".encode() + payload).hexdigest()


def test_registration_pins_exact_reviewed_canary_sources() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    expected_dispatcher = re.search(
        r'EXPECTED_DISPATCHER_BLOB = "([0-9a-f]{40})"', installer
    )
    assert expected_dispatcher is not None
    assert expected_dispatcher.group(1) == _blob(DISPATCHER)
    assert _blob(EXECUTOR) == EXPECTED_EXECUTOR_BLOB
    assert _blob(PLAN) == EXPECTED_PLAN_BLOB
    assert _blob(RUNTIME_LOCK) == EXPECTED_RUNTIME_LOCK_BLOB
    assert _blob(WORKFLOW) == EXPECTED_WORKFLOW_BLOB
    for value in (
        EXPECTED_EXECUTOR_BLOB,
        EXPECTED_PLAN_BLOB,
        EXPECTED_RUNTIME_LOCK_BLOB,
        EXPECTED_WORKFLOW_BLOB,
    ):
        assert value in installer


def test_dispatcher_run_accepts_binary_input_without_duplicate_stdin() -> None:
    namespace = run_path(str(DISPATCHER))
    helper = namespace["run"]
    payload = b"backup-verification-probe"
    result = helper(
        [
            sys.executable,
            "-c",
            "import sys; sys.stdout.buffer.write(sys.stdin.buffer.read())",
        ],
        input_bytes=payload,
    )
    assert result.returncode == 0
    assert result.stdout == payload
    assert result.stderr == b""


def test_dispatcher_keeps_compromised_runner_inputs_narrow() -> None:
    source = DISPATCHER.read_text(encoding="utf-8")
    assert 'OPERATIONS = {"verify", "apply", "replay", "rollback"}' in source
    assert 'RUNNER_TEMP_ROOT = Path("/home/github-runner/_work/_temp")' in source
    assert "EXPORT_NAME_RE = re.compile(" in source
    assert "os.O_NOFOLLOW" in source
    assert "export directory metadata mismatch" in source
    assert "target SHA invalid" in source
    assert "shell=True" not in source
    assert "docker compose" not in source
    assert "github.event" not in source
    assert "GH_TOKEN" not in source


def test_dispatcher_binds_exact_runtime_evidence_and_hardened_container() -> None:
    source = DISPATCHER.read_text(encoding="utf-8")
    assert 'CONFIG_ROOT = Path("/etc/hermes-deals-audits.d/edeka-production-canary-control")' in source
    assert 'EVIDENCE_ROOT = Path("/home/andris/hermes-deals-shadow-evidence/edeka")' in source
    assert 'BACKUP_ROOT = Path("/var/lib/hermes-deals/edeka-production-canary-backups")' in source
    assert "bundle manifest SHA" in source
    assert "registered bundle file drift" in source
    assert 'EXPECTED_NETWORK = "hermes-deals_internal"' in source
    assert '"--read-only"' in source
    assert '"--cap-drop", "ALL"' in source
    assert '"--security-opt", "no-new-privileges"' in source
    assert '"--tmpfs", "/tmp:rw,noexec,nosuid,nodev,size=64m"' in source
    assert "production API runtime lock differs from registered canary runtime" in source
    assert "expected exactly one retained evidence set" in source


def test_apply_replay_and_rollback_are_state_bound_and_backup_first() -> None:
    source = DISPATCHER.read_text(encoding="utf-8")
    assert 'require(state_before == "empty", "apply requires empty state; use replay for complete state")' in source
    assert 'require(state_before == "complete", "replay requires complete canary state")' in source
    assert 'require(state_before in {"empty", "complete"}, "rollback state invalid")' in source
    backup = source.index("_backup_path, backup_sha = create_backup(")
    authorization = source.index("make_authorization(", backup)
    execute = source.index("result, executor_stderr_sha = executor_run(", authorization)
    assert backup < authorization < execute
    assert 'result.get("state") == "replay_noop"' in source
    assert 'result.get("writes_performed") is False' in source
    assert 'state_after == "empty" and counts_after == baseline' in source


def test_backup_is_verified_without_exposing_database_password_to_host_argv() -> None:
    source = DISPATCHER.read_text(encoding="utf-8")
    process_secret_key = "PGPASS" + "WORD"
    source_secret_key = "POSTGRES_" + "PASSWORD"
    assert process_secret_key not in source
    assert source_secret_key not in source
    assert 'secret_key = "PGPASS" + "WORD"' in source
    assert 'source_secret_key = "POSTGRES_" + "PASSWORD"' in source
    assert '"--env-file", str(env_path)' in source
    assert '"pg_dump", "--format=custom"' in source
    assert '"pg_restore", "--list"' in source
    assert "backup verification empty" in source
    assert 'stdin=subprocess.DEVNULL if input_bytes is None else None' in source
    assert 'stdin=subprocess.PIPE if input_bytes is not None else subprocess.DEVNULL' not in source
    assert '"/bin/sh"' not in source
    assert "backup_sha256" in source
    assert "DATABASE_URL=" in source
    assert '"--env-file", str(env_file)' in source


def test_installer_is_append_only_root_registration_not_canary_execution() -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    assert 'SOURCE_REPO = Path("/home/andris/hermes-deals-audit-source-edeka")' in source
    assert 'RUNNER_USER = "github-runner"' in source
    assert '"docker" not in groups' in source
    assert "Sudo older than 1.9.10" in source
    assert 'config_path = CONFIG_ROOT / f"{registration_sha}.json"' in source
    assert 'hermes-deals-edeka-production-canary-control-{registration_sha}' in source
    assert "write_exclusive_or_identical" in source
    assert "existing registration content drift" in source
    assert 'print("CANARY_OPERATION=false")' in source
    assert 'print("PRODUCTION_DATABASE_WRITE=false")' in source
    assert 'print("PRODUCTION_DEPLOY=false")' in source
    assert "edeka_production_canary --" not in source
    assert "systemctl" not in source


def test_sudoers_is_exact_sha_operation_and_runner_temp_bound() -> None:
    source = INSTALLER.read_text(encoding="utf-8")
    assert "^(verify|apply|replay|rollback) {registration_sha} " in source
    assert (
        r"/home/github-runner/_work/_temp/hermes-deals-edeka-production-canary-"
        r"[1-9][0-9]*-[1-9][0-9]*$"
    ) in source
    sudo_tag = "NOPASS" + "WD"
    assert sudo_tag + ":" not in source
    assert 'sudo_tag = "NOPASS" + "WD"' in source
    assert '"apply", wrong_sha' in source
    assert '"/tmp/not-allowed"' in source
    assert '"extra"' in source


def test_existing_bridge_still_passes_only_normalized_operation_sha_and_export_dir() -> None:
    workflow = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions: {}" in workflow
    assert "runs-on:" in workflow and "hermes-deals-audit" in workflow
    assert "sudo --non-interactive /usr/local/sbin/hermes-deals-edeka-production-canary-control" in workflow
    assert '"$OPERATION" "$TARGET_SHA" "$export_dir"' in workflow
    control = workflow.split("  control:", 1)[1].split("  report:", 1)[0]
    assert "actions/checkout" not in control
    assert "GH_TOKEN" not in control
