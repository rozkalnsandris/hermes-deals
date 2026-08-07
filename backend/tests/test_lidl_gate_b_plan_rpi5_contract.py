from __future__ import annotations

import re
from pathlib import Path
import subprocess
import textwrap

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "lidl-gate-b-plan-rpi5.yml"
DISPATCHER = ROOT / "tools" / "runner" / "lidl-gate-b-plan-dispatcher.sh"
INSTALLER = ROOT / "tools" / "runner" / "install-lidl-gate-b-plan-dispatcher.sh"
FINALIZER = ROOT / "tools" / "runner" / "run-lidl-gate-b-plan-owner-finalizer-v01.sh"
PLAN_BLOB = "02f85620e4c881e4ef4b518751223bfb92fd91f8"
PLAN_VERSION = "lidl-gate-b-freeze-plan-v2-source-revision"
APPLY_BLOB = "b8e38b52be69aa6f0cdaa5dbb3f76ccb013c772f"


def text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def embedded_python(source: str) -> list[str]:
    snippets = re.findall(r"python3 - <<'PY'\n(.*?)\n\s*PY(?:\n|$)", source, re.S)
    return [textwrap.dedent(snippet) for snippet in snippets]


def test_workflow_is_manual_owner_only_and_read_only() -> None:
    source = text(WORKFLOW)
    document = yaml.load(source, Loader=yaml.BaseLoader)
    assert set(document["on"]) == {"workflow_dispatch"}
    inputs = document["on"]["workflow_dispatch"]["inputs"]
    assert set(inputs) == {"pr_number", "gate_a_run_id", "gate_a_run_attempt"}
    assert document["permissions"] == {"contents": "read", "pull-requests": "read"}
    assert "EXPECTED_OWNER_LOGIN: rozkalnsandris" in source
    assert 'EXPECTED_OWNER_ID: "277435981"' in source
    assert f'EXPECTED_PLAN_BLOB: "{PLAN_BLOB}"' in source
    assert f'EXPECTED_APPLY_BLOB: "{APPLY_BLOB}"' in source
    assert "current main Gate B blob drift" in source
    assert "actions/checkout" not in source
    assert "schedule:" not in source
    assert "push:" not in source
    assert "pull_request:" not in source
    assert "/usr/local/sbin/hermes-deals-lidl-gate-b-plan-dispatch" in source
    assert "actions/upload-artifact@v4" in source
    assert "READY_TO_FREEZE" in source
    assert '"corpus_write_authorized": False' in source
    assert '"parser_scan_authorized": False' in source
    assert '"gate_c_d_authorized": False' in source


def test_workflow_embedded_python_compiles() -> None:
    snippets = embedded_python(text(WORKFLOW))
    assert len(snippets) == 3
    for index, snippet in enumerate(snippets):
        compile(snippet, f"workflow-python-{index}", "exec")


def test_shell_entrypoints_parse() -> None:
    for path in (DISPATCHER, INSTALLER, FINALIZER):
        subprocess.run(["bash", "-n", str(path)], check=True)


def test_installer_pins_exact_blobs_without_installing_apply_capability() -> None:
    source = text(INSTALLER)
    assert f"EXPECTED_PLAN_BLOB='{PLAN_BLOB}'" in source
    assert f"EXPECTED_APPLY_BLOB='{APPLY_BLOB}'" in source
    assert "Gate B planner blob identity drift" in source
    assert "Gate B apply blob identity drift" in source
    assert "INSTALLED_PLAN='/usr/local/libexec/hermes-deals-audits/lidl-gate-b-freeze-plan.py'" in source
    assert "DISPATCHER='/usr/local/sbin/hermes-deals-lidl-gate-b-plan-dispatch'" in source
    assert "github-runner ALL=(root) NOPASSWD:" in source
    assert "APPLY_CAPABILITY_INSTALLED=false" in source
    assert "installer must not install Gate B apply capability" in source
    assert 'git_read show "$EXPECTED_SHA:$APPLY_SOURCE"' not in source
    assert 'install -o root -g root -m 0755 "$TMP/apply' not in source
    assert "docker build" not in source
    assert "RUNNER_HAS_DOCKER_GROUP=false" in source
    assert "CORPUS_WRITE=false" in source
    assert "PARSER_SCAN=false" in source
    assert "GATE_C_D_AUTHORIZED=false" in source


def test_dispatcher_runs_plan_twice_and_exports_only_sanitized_fields() -> None:
    source = text(DISPATCHER)
    assert f'"${{planner_blob_sha:-}}" == {PLAN_BLOB}' in source
    assert f"plan.get('plan_version') != '{PLAN_VERSION}'" in source
    assert "543cae6923eb461038109cdc6ee98e9b64782d83" not in source
    assert "lidl-gate-b-freeze-plan-v1" not in source
    assert source.count('run_owner python3 "$planner_path"') == 2
    assert 'cmp -s "$PLAN_A" "$PLAN_B"' in source
    assert "repeated Gate B plans are not byte-identical" in source
    assert "authoritative corpus changed during read-only planning" in source
    assert "PRIMARY_WORKTREE_UNCHANGED=true" in source
    assert "PRIMARY_GIT_INDEX_UNCHANGED=true" in source
    assert "PRIMARY_V08_UNCHANGED=true" in source
    assert "gate-b-plan-summary.json" in source
    assert "dispatcher-evidence-manifest.json" in source
    assert "planner-exit-code.txt" in source
    assert "shutil.copy" not in source
    assert "lidl_gate_b_freeze_apply.py" not in source
    assert "corpus_write_authorized': False" in source
    assert "parser_scan_authorized': False" in source
    assert "database_write_authorized': False" in source
    assert "review_write_authorized': False" in source
    assert "production_publish_authorized': False" in source
    assert "production_deploy_authorized': False" in source
    assert "systemd_change_authorized': False" in source
    assert "automatic_retry_authorized': False" in source
    assert "gate_c_d_authorized': False" in source


def test_dispatcher_does_not_mutate_protected_repositories_or_corpus() -> None:
    source = text(DISPATCHER)
    forbidden = (
        'git -C "$PRIMARY" switch',
        'git -C "$PRIMARY" checkout',
        'git -C "$PRIMARY" reset',
        'git -C "$PRIMARY" clean',
        'git -C "$PRIMARY" pull',
        'git -C "$PRIMARY" fetch',
        'rm -rf -- "$CORPUS_ROOT"',
        'mv -f -- "$STAGING" "$CORPUS_ROOT',
    )
    for marker in forbidden:
        assert marker not in source
    assert "GIT_OPTIONAL_LOCKS=0" in source
    assert "CORPUS_BEFORE" in source
    assert "CORPUS_AFTER" in source


def test_owner_finalizer_preserves_primary_and_requires_separate_merge() -> None:
    source = text(FINALIZER)
    assert "WORKFLOW='lidl-gate-b-plan-rpi5.yml'" in source
    assert "install-lidl-gate-b-plan-dispatcher.sh" in source
    assert "verify_primary_unchanged" in source
    assert "verify_audit_registered_state" in source
    assert "PRIMARY_V08_VERIFIED_UNCHANGED=true" in source
    assert f"PLANNER_BLOB_SHA={PLAN_BLOB}" in source
    assert f"APPLY_BLOB_SHA={APPLY_BLOB}" in source
    assert "APPLY_CAPABILITY_INSTALLED=false" in source
    assert 'gh workflow run "$WORKFLOW"' in source
    assert "CORPUS_WRITE=false" in source
    assert "PARSER_SCAN=false" in source
    assert "PRODUCTION_DATABASE_WRITE=false" in source
    assert "PRODUCTION_DEPLOY=false" in source
    assert "GATE_C_D_AUTHORIZED=false" in source
    for command in ("switch", "checkout", "reset", "clean", "pull", "fetch"):
        assert f'git -C "$PRIMARY" {command}' not in source


def test_contract_paths_are_issue_scoped() -> None:
    assert WORKFLOW.name == "lidl-gate-b-plan-rpi5.yml"
    assert DISPATCHER.name == "lidl-gate-b-plan-dispatcher.sh"
    assert INSTALLER.name == "install-lidl-gate-b-plan-dispatcher.sh"
    assert FINALIZER.name == "run-lidl-gate-b-plan-owner-finalizer-v01.sh"
