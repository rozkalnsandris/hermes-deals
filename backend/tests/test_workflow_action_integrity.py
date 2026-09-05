from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
SPEC = importlib.util.spec_from_file_location("workflow_actions", ROOT / "scripts/audit-workflow-actions.py")
assert SPEC and SPEC.loader
AUDIT = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDIT)
SHA = "fbc6f3992d24b796d5a048ff273f7fcc4a7b6c09"


def workflow(ref: str = f"actions/checkout@{SHA}", setting: str = "false", comment: str = "# v5.1.0") -> str:
    return f"""on: pull_request
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: {ref} {comment}
        with:
          persist-credentials: {setting}
"""


def test_all_repository_workflows_are_immutable_and_credentials_are_bounded() -> None:
    assert AUDIT.main() == 0


@pytest.mark.parametrize("revision", ["v5", "main", "fbc6f39", "${{ inputs.ref }}"])
def test_mutable_refs_are_rejected_on_github_hosted_jobs(revision: str) -> None:
    assert AUDIT.audit_text(workflow(f"actions/checkout@{revision}"), "example.yml")


@pytest.mark.parametrize("setting", ["true", "", "null", "${{ inputs.persist }}"])
def test_credentials_fail_closed(setting: str) -> None:
    assert AUDIT.audit_text(workflow(setting=setting), "example.yml")


def test_missing_setting_and_version_comment_are_rejected() -> None:
    assert AUDIT.audit_text(workflow().replace("          persist-credentials: false\n", ""), "example.yml")
    assert AUDIT.audit_text(workflow(comment=""), "example.yml")


def test_quoted_refs_and_flow_yaml_cannot_bypass_guard() -> None:
    assert not AUDIT.audit_text(workflow(ref=f"'actions/checkout@{SHA}'"), "example.yml")
    assert AUDIT.audit_text("jobs: {test: {steps: [{uses: 'actions/checkout@v5'}]}}", "example.yml")


def test_reusable_workflows_are_checked() -> None:
    assert AUDIT.audit_text("jobs:\n  call:\n    uses: owner/repo/.github/workflows/ci.yml@main\n", "example.yml")


def test_local_actions_and_script_text_are_not_external_actions() -> None:
    assert not AUDIT.audit_text(workflow(ref="./.github/actions/local", comment=""), "example.yml")
    assert not AUDIT.audit_text("jobs:\n  test:\n    steps:\n      - run: |\n          uses: actions/checkout@v5\n", "example.yml")


def test_duplicate_keys_and_aliases_fail_closed() -> None:
    assert AUDIT.audit_text(workflow().replace("        with:", "        uses: actions/checkout@v5\n        with:"), "example.yml")
    assert AUDIT.audit_text("jobs: {test: {steps: [&s {uses: './local'}, *s]}}", "example.yml")


@pytest.mark.parametrize("identity,reason", list(AUDIT.CREDENTIAL_EXCEPTIONS.items()))
def test_only_exact_documented_existing_writer_can_persist(identity, reason) -> None:
    filename, job, name = identity
    text = workflow(setting="true").replace("  test:", f"  {job}:").replace(
        "      - uses:", f"      - name: {name}\n        uses:"
    ).replace("          persist-credentials:", f"          # {reason}\n          persist-credentials:")
    assert not AUDIT.audit_text(text, filename)
    assert AUDIT.audit_text(text, "unreviewed.yml")
    assert AUDIT.audit_text(text.replace(reason, "Needed for Git operations"), filename)


def test_guard_runs_in_required_backend_ci_after_locked_dependencies() -> None:
    text = (ROOT / ".github/workflows/ci.yml").read_text()
    assert "python ../scripts/audit-workflow-actions.py" in text
    assert text.index("-r locks/ci-py313.txt") < text.index("python ../scripts/audit-workflow-actions.py")
