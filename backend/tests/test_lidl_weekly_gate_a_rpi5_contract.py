from __future__ import annotations

import importlib.util
import json
import os
from pathlib import Path
import subprocess
import textwrap

import pytest
import yaml


ROOT = Path(__file__).resolve().parents[2]
RUNNER = ROOT / "tools" / "run-hermes-deals-lidl-weekly-gate-a-v01.sh"
DISPATCHER = ROOT / "tools" / "runner" / "lidl-weekly-gate-a-dispatcher.sh"
INSTALLER = ROOT / "tools" / "runner" / "install-lidl-weekly-gate-a-dispatcher.sh"
FINALIZER = ROOT / "tools" / "runner" / "run-lidl-weekly-gate-a-owner-finalizer-v01.sh"
SELECTOR = ROOT / "tools" / "lidl_gate_a_previous_manifest.py"
WORKFLOW = ROOT / ".github" / "workflows" / "lidl-weekly-gate-a-rpi5.yml"
RUNBOOK = ROOT / "docs" / "LIDL_WEEKLY_GATE_A_RPI5.md"
CONTROLLER_VERSION = "lidl-weekly-shadow-controller-v1"


def load_selector():
    spec = importlib.util.spec_from_file_location("lidl_gate_a_previous_manifest", SELECTOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def embedded_python(text: str) -> list[str]:
    programs: list[str] = []
    lines = text.splitlines()
    index = 0
    while index < len(lines):
        if "<<'PY'" not in lines[index] and '<<"PY"' not in lines[index]:
            index += 1
            continue
        index += 1
        block: list[str] = []
        while index < len(lines) and lines[index].strip() != "PY":
            block.append(lines[index])
            index += 1
        assert index < len(lines), "unterminated embedded Python heredoc"
        programs.append(textwrap.dedent("\n".join(block)) + "\n")
        index += 1
    return programs


def safe_manifest(*, result: str = "READY", fingerprint: str = "a" * 64) -> dict:
    return {
        "schema_version": 1,
        "controller_version": CONTROLLER_VERSION,
        "result": result,
        "execution_fingerprint": fingerprint,
        "dry_run": True,
        "corpus_write_authorized": False,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "production_publish_authorized": False,
        "systemd_change_authorized": False,
    }


def write_manifest(path: Path, payload: dict, *, mtime_ns: int) -> None:
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps(payload, sort_keys=True) + "\n", encoding="utf-8")
    os.utime(path, ns=(mtime_ns, mtime_ns))


def test_gate_a_shell_and_embedded_python_syntax() -> None:
    for path in (RUNNER, DISPATCHER, INSTALLER, FINALIZER):
        subprocess.run(["bash", "-n", str(path)], check=True)
        for program in embedded_python(path.read_text(encoding="utf-8")):
            compile(program, f"{path}:embedded", "exec")
    subprocess.run(["python", "-m", "py_compile", str(SELECTOR)], check=True)


def test_workflow_is_manual_owner_only_and_uses_real_event_payload_path() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    parsed = yaml.load(text, Loader=yaml.BaseLoader)
    assert isinstance(parsed, dict)
    triggers = parsed.get("on")
    assert isinstance(triggers, dict)
    assert set(triggers) == {"workflow_dispatch"}
    assert "schedule:" not in text
    assert "pull_request:" not in text
    assert "push:" not in text
    assert "EXPECTED_OWNER_LOGIN: rozkalnsandris" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert 'Path(os.environ["GITHUB_EVENT_PATH"])' in text
    assert "github.event_path" not in text
    assert 'pr.get("merged")' in text
    assert 'base.get("ref") != "main"' in text
    assert 'compare/{sha}...main' in text
    assert 'target not in {"current", "next"}' in text
    assert "date.fromisoformat(as_of)" in text
    assert 'text not in {"true", "false"}' in text
    assert "sudo --non-interactive /usr/local/sbin/hermes-deals-lidl-weekly-gate-a-dispatch" in text
    assert "actions/upload-artifact@v4" in text
    assert "retention-days: 30" in text
    for program in embedded_python(text):
        compile(program, f"{WORKFLOW}:embedded", "exec")


def test_runner_uses_exact_read_only_image_boundary_without_production_access() -> None:
    text = RUNNER.read_text(encoding="utf-8")
    for marker in (
        "lidl-weekly-gate-a-rpi5-v01",
        "/home/andris/hermes-deals-audit-source",
        "/home/andris/hermes-deals-lidl-corpus",
        "tools/lidl_gate_a_previous_manifest.py",
        "docker image inspect --format '{{.Id}}'",
        "--network bridge",
        "--read-only",
        "--cap-drop ALL",
        "--security-opt no-new-privileges:true",
        "--pids-limit 256",
        "--memory 1536m",
        "--cpus 2",
        'dst=/repo,readonly',
        'dst=/corpus,readonly',
        "python /repo/tools/lidl_weekly_shadow_controller.py",
        "--corpus /corpus",
        "PRIMARY_WORKTREE_MODIFIED=false",
        "PRODUCTION_DATABASE_WRITE=false",
        "REVIEW_WRITE=false",
        "PRODUCTION_PUBLISH=false",
        "PRODUCTION_DEPLOY=false",
        "SYSTEMD_CHANGE=false",
        "BOUNDED_RETRY=false",
    ):
        assert marker in text
    for forbidden in (
        "DATABASE_URL=",
        "docker compose",
        "alembic ",
        "psql ",
        "review_seed=true",
        "auto_approve=true",
        "auto_publish=true",
        "systemctl start",
        "systemctl enable",
    ):
        assert forbidden not in text


def test_installer_builds_and_registers_an_exact_sha_image_without_weakening_runner() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    for marker in (
        "docker build --pull=false",
        'net.rozkalns.hermes-deals.audit=lidl-weekly-gate-a',
        'net.rozkalns.hermes-deals.commit=$EXPECTED_SHA',
        'net.rozkalns.hermes-deals.dockerfile-sha256=$DOCKERFILE_SHA',
        'net.rozkalns.hermes-deals.requirements-sha256=$REQUIREMENTS_SHA',
        "IMAGE_ID=",
        "sha256:[0-9a-f]{64}",
        "/usr/local/sbin/hermes-deals-lidl-weekly-gate-a-dispatch",
        "github-runner must not belong to docker group",
        "AUDIT_GIT_INDEX_UNCHANGED=true",
        "PRODUCTION_DATABASE_WRITE=false",
        "REVIEW_WRITE=false",
        "PRODUCTION_PUBLISH=false",
        "PRODUCTION_DEPLOY=false",
        "SYSTEMD_CHANGE=false",
    ):
        assert marker in text
    assert "docker compose" not in text
    assert "docker run" not in text
    assert "alembic" not in text
    assert "psql" not in text


def test_dispatcher_exports_only_bounded_sanitized_evidence() -> None:
    text = DISPATCHER.read_text(encoding="utf-8")
    for marker in (
        "gate-a-summary.json",
        "safety-result.txt",
        "run-request.txt",
        "runner-exit-code.txt",
        "dispatcher-evidence-manifest.json",
        "sanitization_passed",
        "production_apply_authorized",
        "artifact directory is outside runner temp allowlist",
        "registered script content drift",
        "registered image is unavailable or drifted",
    ):
        assert marker in text
    assert "source.pdf" not in text
    assert "source.json" not in text
    assert "controller-execution.log" not in text
    assert "shutil.copy2(Path" not in text
    assert "PRODUCTION_DATABASE_WRITE=false" in text
    assert "REVIEW_WRITE=false" in text
    assert "PRODUCTION_PUBLISH=false" in text
    assert "PRODUCTION_DEPLOY=false" in text
    assert "SYSTEMD_CHANGE=false" in text


def test_finalizer_changes_only_isolated_clone_and_rechecks_primary_snapshot() -> None:
    text = FINALIZER.read_text(encoding="utf-8")
    for marker in (
        "run-hermes-deals-b15m2-least-privilege-shadow-migration-api-regression-v08.sh",
        'git -C "$AUDIT_REPO" switch -C main "$TARGET_SHA"',
        "install-lidl-weekly-gate-a-dispatcher.sh",
        'gh workflow run "$WORKFLOW"',
        '-f "target=$TARGET"',
        '-f "as_of=$AS_OF"',
        '-f "use_previous=$USE_PREVIOUS"',
        "PRIMARY_STATUS_SHA256_BEFORE=",
        "PRIMARY_INDEX_STATE_BEFORE=",
        "PRIMARY_GIT_STDERR_POLICY=empty-required",
        "PRIMARY_WORKTREE_VERIFIED_UNCHANGED_AFTER_WORKFLOW=true",
        "PRIMARY_INDEX_VERIFIED_UNCHANGED_AFTER_WORKFLOW=true",
        "PRIMARY_V08_VERIFIED_UNCHANGED_AFTER_WORKFLOW=true",
        "AUDIT_INDEX_STATE_REGISTERED=",
    ):
        assert marker in text
    for forbidden in (
        "PRIMARY_EXPECTED_BRANCH",
        "PRIMARY_EXPECTED_HEAD",
        "protected primary branch differs from expected baseline",
        "protected primary HEAD differs from expected baseline",
        "audit/b15m2-v08-preparation",
        "a2d9e20039275832286b229984b8261f9394554f",
        'git -C "$PRIMARY" switch',
        'git -C "$PRIMARY" checkout',
        'git -C "$PRIMARY" reset',
        'git -C "$PRIMARY" stash',
        'git -C "$PRIMARY" clean',
        'git -C "$PRIMARY" pull',
        'git -C "$PRIMARY" fetch',
        'git -C "$PRIMARY" merge',
        'git -C "$PRIMARY" rebase',
        "docker compose",
        "alembic",
        "psql",
    ):
        assert forbidden not in text


def test_previous_selector_ignores_newer_wait_and_unsafe_manifests(tmp_path: Path) -> None:
    selector = load_selector()
    root = tmp_path / "evidence"
    root.mkdir()
    current = root / "lidl-gate-a-current"
    current.mkdir()
    ready = root / "lidl-gate-a-ready" / "controller" / "controller-manifest.json"
    wait = root / "lidl-gate-a-wait" / "controller" / "controller-manifest.json"
    unsafe = root / "lidl-gate-a-unsafe" / "controller" / "controller-manifest.json"
    write_manifest(ready, safe_manifest(), mtime_ns=1_000_000_000)
    write_manifest(wait, safe_manifest(result="WAIT"), mtime_ns=3_000_000_000)
    unsafe_payload = safe_manifest(result="NO_OP", fingerprint="b" * 64)
    unsafe_payload["database_write_authorized"] = True
    write_manifest(unsafe, unsafe_payload, mtime_ns=4_000_000_000)

    assert selector.select_previous_manifest(root, current) == ready.resolve()


def test_previous_selector_prefers_newest_completed_safe_manifest(tmp_path: Path) -> None:
    selector = load_selector()
    root = tmp_path / "evidence"
    root.mkdir()
    current = root / "lidl-gate-a-current"
    current.mkdir()
    older = root / "lidl-gate-a-older" / "controller" / "controller-manifest.json"
    newer = root / "lidl-gate-a-newer" / "controller" / "controller-manifest.json"
    write_manifest(older, safe_manifest(fingerprint="a" * 64), mtime_ns=1_000_000_000)
    write_manifest(
        newer,
        safe_manifest(result="NO_OP", fingerprint="b" * 64),
        mtime_ns=2_000_000_000,
    )

    assert selector.select_previous_manifest(root, current) == newer.resolve()


def test_previous_selector_fails_when_no_safe_completed_manifest_exists(tmp_path: Path) -> None:
    selector = load_selector()
    root = tmp_path / "evidence"
    root.mkdir()
    current = root / "lidl-gate-a-current"
    current.mkdir()
    wait = root / "lidl-gate-a-wait" / "controller" / "controller-manifest.json"
    write_manifest(wait, safe_manifest(result="WAIT"), mtime_ns=1_000_000_000)

    with pytest.raises(selector.PreviousManifestError, match="no completed safe"):
        selector.select_previous_manifest(root, current)


def test_gate_a_runbook_keeps_later_gates_separately_authorized() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")
    for marker in (
        "READY",
        "NO_OP",
        "WAIT",
        "BLOCKED",
        "exact-SHA audit image",
        "source PDF",
        "source JSON",
        "Gate B",
        "Production canary",
        "separately owner-authorized",
    ):
        assert marker in text
