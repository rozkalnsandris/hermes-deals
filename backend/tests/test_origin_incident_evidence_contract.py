from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import re
import subprocess
import textwrap

import pytest

ROOT = Path(__file__).resolve().parents[2]
COLLECTOR = ROOT / "tools/origin_incident_evidence.py"
INSTALLER = ROOT / "tools/runner/install-origin-incident-evidence.sh"
DISPATCHER = ROOT / "tools/runner/origin-incident-evidence-dispatcher.sh"
WORKFLOW = ROOT / ".github/workflows/origin-incident-evidence-rpi5.yml"
DOC = ROOT / "docs/operations/origin-incident-evidence-rpi5.md"


def load_collector():
    spec = importlib.util.spec_from_file_location("origin_incident_evidence", COLLECTOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_timestamp_and_window_inputs_fail_closed():
    module = load_collector()
    assert module.iso_z(module.parse_incident_at("2026-08-04T23:11:00Z")) == "2026-08-04T23:11:00Z"
    assert module.parse_window("15") == 15
    for invalid in (
        "2026-08-04 23:11:00Z",
        "2026-08-04T23:11:00+00:00",
        "2026-08-04T23:11Z",
        "2026-02-30T23:11:00Z",
    ):
        with pytest.raises(module.CollectorError):
            module.parse_incident_at(invalid)
    for invalid in (0, 10, 120, "fifteen"):
        with pytest.raises(module.CollectorError):
            module.parse_window(invalid)


def test_log_text_is_reduced_to_allowlisted_integer_counters():
    module = load_collector()
    secret = "token=super-secret-value"
    text = "\n".join(
        [
            "502 origin_bad_gateway upstream prematurely closed connection",
            "database connection timeout psycopg exception",
            "connection reset by peer; reconnecting HA connection",
            "out of memory: killed process",
            secret,
        ]
    )
    counts = module.count_signatures(text)
    assert set(counts) == set(module.SIGNATURE_KEYS)
    assert all(type(value) is int and value >= 0 for value in counts.values())
    assert counts["gateway_502"] == 1
    assert counts["database"] == 1
    assert counts["oom"] == 1
    assert secret not in json.dumps(counts)


def test_docker_inventory_returns_only_fixed_service_roles():
    module = load_collector()
    text = "\n".join(
        [
            "a" * 64 + "\tprivate-api-image\thermes-deals-api-1\thermes-deals\tapi",
            "b" * 64 + "\tprivate-web-image\thermes-deals-web-1\thermes-deals\tweb",
            "c" * 64 + "\tprivate-db-image\thermes-deals-db-1\thermes-deals\tdb",
            "d" * 64 + "\tcloudflare/cloudflared:latest\tsecret-tunnel-name\tother\tproxy",
            "e" * 64 + "\tprivate-image\tunrelated\tother\tworker",
        ]
    )
    inventory = module.parse_docker_inventory(text)
    assert set(inventory) == {"api", "web", "db", "cloudflared"}
    assert inventory["api"] == ["a" * 64]
    assert inventory["cloudflared"] == ["d" * 64]
    rendered = json.dumps(inventory)
    assert "private" not in rendered
    assert "secret-tunnel-name" not in rendered


def test_state_normalization_discards_error_health_logs_pid_and_ids():
    module = load_collector()
    normalized = module.normalize_state(
        {
            "Status": "running",
            "Running": True,
            "Restarting": False,
            "OOMKilled": False,
            "Dead": False,
            "Pid": 1234,
            "ExitCode": 0,
            "Error": "postgresql://user:password@db/internal",
            "StartedAt": "2026-08-05T12:00:00.000000000Z",
            "FinishedAt": "0001-01-01T00:00:00Z",
            "Health": {
                "Status": "healthy",
                "Log": [{"Output": "Authorization: Bearer secret"}],
            },
        },
        2,
    )
    assert set(normalized) == {
        "status",
        "running",
        "restarting",
        "oom_killed",
        "dead",
        "exit_code",
        "restart_count",
        "health_status",
        "started_at",
        "finished_at",
    }
    rendered = json.dumps(normalized)
    assert "password" not in rendered
    assert "Bearer" not in rendered
    assert "1234" not in rendered
    assert normalized["finished_at"] is None


def test_report_writer_is_exclusive_canonical_and_bounded(tmp_path: Path):
    module = load_collector()
    target = tmp_path / "report.json"
    report = {"z": 1, "a": {"value": True}}
    module.write_report(target, report)
    assert target.stat().st_mode & 0o777 == 0o600
    assert target.read_text(encoding="utf-8") == json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    with pytest.raises(module.CollectorError):
        module.write_report(target, report)


def test_collector_uses_bounded_commands_without_shell_or_environment_dump():
    text = read(COLLECTOR)
    assert "shell=True" not in text
    assert "subprocess.Popen(" in text
    assert "MAX_COMMAND_BYTES = 2 * 1024 * 1024" in text
    assert "COMMAND_TIMEOUT_SECONDS = 12" in text
    assert "stderr=subprocess.STDOUT" in text
    assert '"docker", "logs"' in text
    assert '"journalctl"' in text
    for forbidden in ("docker inspect --format", "os.environ.copy", "Config.Env", "Config.Cmd", "Mounts", "Labels"):
        assert forbidden not in text


def test_workflow_is_manual_owner_authorized_checkout_free_and_serialized():
    text = read(WORKFLOW)
    assert "workflow_dispatch:" in text
    assert "ACTOR_ID: ${{ github.actor_id }}" in text
    assert 'os.environ["ACTOR"] != "rozkalnsandris"' in text
    assert 'os.environ["ACTOR_ID"] != "277435981"' in text
    assert "audit accepts only merged pull requests" in text
    assert "merged SHA is not reachable from current main" in text
    assert "incident_at must use canonical YYYY-MM-DDTHH:MM:SSZ format" in text
    assert 'window_minutes not in {"5", "15", "30", "60"}' in text
    assert "actions/checkout@" not in text
    assert "group: hermes-deals-rpi5-audit" in text
    assert "/usr/local/sbin/hermes-deals-origin-incident-evidence-dispatch" in text
    assert "actions/upload-artifact@v6" in text


def test_workflow_requires_exact_registered_files_and_compiles_embedded_python():
    text = read(WORKFLOW)
    for path in (
        "tools/origin_incident_evidence.py",
        "tools/runner/install-origin-incident-evidence.sh",
        "tools/runner/origin-incident-evidence-dispatcher.sh",
        ".github/workflows/origin-incident-evidence-rpi5.yml",
        "docs/operations/origin-incident-evidence-rpi5.md",
    ):
        assert f'"{path}"' in text
    blocks = re.findall(r"python3 - <<'PY'\n(.*?)\n          PY", text, flags=re.S)
    assert len(blocks) == 2
    for block in blocks:
        compile(textwrap.dedent(block), "<workflow-python>", "exec")


def test_installer_is_detached_fail_closed_and_does_not_execute_audit():
    text = read(INSTALLER)
    assert "primary production worktree is forbidden" in text
    assert "source worktree must be detached" in text
    assert "source worktree is not clean" in text
    assert "merge-base --is-ancestor" in text
    assert "python3 -m py_compile" in text
    assert "bash -n" in text
    assert "visudo -cf" in text
    assert "WORKFLOW_EXECUTED=false" in text
    for forbidden in ("systemctl", "docker ", "journalctl", "alembic", "psql ", "pg_dump"):
        assert forbidden not in text


def test_dispatcher_is_fixed_sha_bound_and_exports_only_sanitized_json():
    text = read(DISPATCHER)
    assert "/usr/local/libexec/hermes-deals-audits/origin-incident-evidence.py" in text
    assert "/home/github-runner/_work/_temp/hermes-deals-origin-incident-evidence-*" in text
    assert "collector content drift" in text
    assert "dispatcher content drift" in text
    assert "unexpected collector report fields" in text
    assert "signature counter schema mismatch" in text
    assert "PARTIAL_REASONS" in text
    assert 'destination="$EXPORT_DIR/audit-evidence"' in text
    assert "RAW_LOGS_UPLOADED=false" in text
    assert "PRODUCTION_DATABASE_READ=false" in text
    assert "PRODUCTION_DATABASE_WRITE=false" in text
    assert "RESTART_OR_CONFIGURATION_MUTATION=false" in text
    for forbidden in ("cp collector-stdout", "cp collector-stderr", "tar ", "pg_dump", "psql ", "docker exec"):
        assert forbidden not in text


def test_shell_entrypoints_parse():
    for path in (INSTALLER, DISPATCHER):
        subprocess.run(["bash", "-n", str(path)], check=True, capture_output=True, text=True)


def test_documentation_states_separate_install_and_execution_authorization():
    text = read(DOC)
    for phrase in (
        "does not install",
        "does not execute",
        "separate explicit owner authorization",
        "No raw journal or container log lines",
        "does not claim a root cause",
        "B15M2 V08",
    ):
        assert phrase in text
