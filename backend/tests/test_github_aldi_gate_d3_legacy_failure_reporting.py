from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess

import yaml

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-aldi-gate-d3-bridge.yml"
EXPECTED_SHA = "530a6b6d2b31f635f182788ccace01003b1cbc7d"


def inspect_script() -> str:
    parsed = yaml.load(WORKFLOW.read_text(encoding="utf-8"), Loader=yaml.BaseLoader)
    steps = parsed["jobs"]["audit"]["steps"]
    for step in steps:
        if step.get("id") == "inspect":
            return step["run"]
    raise AssertionError("Gate D3 inspect step missing")


def run_inspector(tmp_path: Path, failure: dict) -> subprocess.CompletedProcess[str]:
    artifact = tmp_path / "artifact"
    artifact.mkdir()
    (artifact / "diagnostic-failure.json").write_text(
        json.dumps(failure, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    output = tmp_path / "github-output"
    env = os.environ.copy()
    env.update(
        ARTIFACT_DIR=str(artifact),
        EXPECTED_SHA=EXPECTED_SHA,
        RUNNER_RC="1",
        GITHUB_OUTPUT=str(output),
    )
    return subprocess.run(
        ["bash", "-c", inspect_script()],
        cwd=ROOT,
        env=env,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
    )


def read_outputs(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        key, value = line.split("=", 1)
        values[key] = value
    return values


def test_legacy_gate_d3_failure_schema_is_bounded_registration_blocker(tmp_path: Path) -> None:
    failure = {
        "schema_version": 1,
        "audit": "aldi-gate-d3-recovery-inventory",
        "error_type": "DispatchError",
        "raw_exception_exported": False,
    }

    completed = run_inspector(tmp_path, failure)

    assert completed.returncode == 0, completed.stderr
    outputs = read_outputs(tmp_path / "github-output")
    assert outputs["decision"] == "RUNTIME_REGISTRATION_REQUIRED"
    assert outputs["failure_type"] == "LegacyGateD3FailureSchema"
    assert outputs["failure_stage"] == "runtime_registration"
    assert (
        outputs["reason_code"]
        == "legacy_gate_d3_failure_schema_requires_exact_pr_281_registration"
    )

    bridge = json.loads((tmp_path / "artifact" / "bridge-result.json").read_text(encoding="utf-8"))
    assert bridge["registered_commit"] == EXPECTED_SHA
    assert bridge["runner_rc"] == 1
    assert bridge["raw_evidence_exported"] is False
    assert bridge["raw_stderr_exported"] is False
    assert bridge["archive_extraction_authorized"] is False
    assert bridge["corpus_mutation_authorized"] is False
    assert bridge["review_write_authorized"] is False
    assert bridge["production_database_write_authorized"] is False
    assert bridge["production_deploy_authorized"] is False
    assert bridge["scheduler_change_authorized"] is False


def test_legacy_gate_d3_failure_rejects_any_extra_unreviewed_field(tmp_path: Path) -> None:
    failure = {
        "schema_version": 1,
        "audit": "aldi-gate-d3-recovery-inventory",
        "error_type": "DispatchError",
        "raw_exception_exported": False,
        "unexpected": "value",
    }

    completed = run_inspector(tmp_path, failure)

    assert completed.returncode != 0
    assert "unsupported Gate D3 failure field set" in completed.stderr
    assert not (tmp_path / "artifact" / "bridge-result.json").exists()


def test_modern_gate_d3_failure_schema_stays_fail_closed_and_reportable(tmp_path: Path) -> None:
    failure = {
        "schema_version": 1,
        "audit": "aldi-gate-d3-recovery-inventory",
        "error_type": "DispatchError",
        "failure_stage": "config_validation",
        "reason_code": "dispatch_error",
        "raw_exception_exported": False,
        "raw_stderr_exported": False,
    }

    completed = run_inspector(tmp_path, failure)

    assert completed.returncode == 0, completed.stderr
    outputs = read_outputs(tmp_path / "github-output")
    assert outputs["decision"] == "INVENTORY_EXECUTION_BLOCKED"
    assert outputs["failure_type"] == "DispatchError"
    assert outputs["failure_stage"] == "config_validation"
    assert outputs["reason_code"] == "dispatch_error"
