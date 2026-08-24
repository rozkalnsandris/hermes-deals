from __future__ import annotations

import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "tools/runner/install-kaufland-k3c-promo-structure-rpi5-bridge.sh"
WORKFLOW = ROOT / ".github/workflows/kaufland-k3c-promo-structure-rpi5.yml"
RUNBOOK = ROOT / "docs/KAUFLAND_K3C_PROMO_STRUCTURE_RPI5_BRIDGE_RUNBOOK.md"


def _parse_registration_line(line: str, expected_sha: str) -> subprocess.CompletedProcess[str]:
    script = r"""
set -Eeuo pipefail
IFS=$'\n\t'
REGISTRATION_LINE="$1"
REGISTRATION_SHA="$2"
REGISTRATION_PARENT_RE='^([0-9a-f]{40}) ([0-9a-f]{40})$'
[[ "$REGISTRATION_LINE" =~ $REGISTRATION_PARENT_RE ]] || exit 20
REGISTRATION_COMMIT="${BASH_REMATCH[1]}"
REGISTRATION_PARENT="${BASH_REMATCH[2]}"
[[ "$REGISTRATION_COMMIT" == "$REGISTRATION_SHA" ]] || exit 21
printf '%s\n' "$REGISTRATION_PARENT"
"""
    return subprocess.run(
        ["bash", "-c", script, "--", line, expected_sha],
        capture_output=True,
        text=True,
        check=False,
    )


def _registration_anchor_allowed(*, workflow_changed: bool, installer_changed: bool) -> bool:
    return workflow_changed or installer_changed


def _execution_anchor_allowed(
    *,
    registration_is_ancestor: bool,
    execution_is_reachable_from_current_main: bool,
    trusted_execution_matches_registration: bool,
    trusted_current_main_matches_registration: bool,
) -> bool:
    return all(
        (
            registration_is_ancestor,
            execution_is_reachable_from_current_main,
            trusted_execution_matches_registration,
            trusted_current_main_matches_registration,
        )
    )


def _execution_ci_mode(
    *, execution_equals_registration: bool, exact_execution_push_ci: bool
) -> str | None:
    if execution_equals_registration:
        return "registration_ci_reuse"
    if exact_execution_push_ci:
        return "exact_execution_push_ci"
    return None


def test_installer_binds_registration_anchor_and_descendant_execution() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)

    assert "REGISTRATION_SHA" in text
    assert "CURRENT_HEAD" in text
    assert "rev-parse --is-shallow-repository" in text
    assert 'merge-base --is-ancestor "$REGISTRATION_SHA" "$CURRENT_HEAD"' in text
    assert "REGISTRATION_PARENT_RE='^([0-9a-f]{40}) ([0-9a-f]{40})$'" in text
    assert '[[ "$REGISTRATION_LINE" =~ $REGISTRATION_PARENT_RE ]]' in text
    assert 'REGISTRATION_COMMIT="${BASH_REMATCH[1]}"' in text
    assert 'REGISTRATION_PARENT="${BASH_REMATCH[2]}"' in text
    assert "read -r REGISTRATION_COMMIT REGISTRATION_PARENT REGISTRATION_EXTRA" not in text
    assert "registration SHA must be a single-parent reviewed merge" in text
    assert "REGISTRATION_INSTALLER_CHANGED=false" in text
    assert "REGISTRATION_WORKFLOW_CHANGED=false" in text
    assert 'if [[ "$REGISTRATION_INSTALLER_CHANGED" != true && "$REGISTRATION_WORKFLOW_CHANGED" != true ]]; then' in text
    assert "registration SHA did not introduce or update the K3C bridge control plane" in text
    assert "registration SHA did not introduce or update the bridge installer" not in text
    assert "registration SHA did not introduce or update the bridge workflow" not in text
    assert "trusted source changed after registration SHA" in text
    assert "registration_checkout_sha" in text
    assert "kaufland-k3c-promo-structure-rpi5-bridge-v2" in text
    assert "[[ $# -eq 3 ]]" in text
    assert 'merge-base --is-ancestor "$REGISTRATION_SHA" "$EXECUTION_SHA"' in text
    assert "execution_checkout_sha" in text
    assert "EXECUTION_IDENTITY_STAMP_FAILED" in text
    assert "SOURCE_CHECKOUT_MUTATED=false" in text
    assert "SOURCE_SYNC_EXECUTED=false" in text
    assert "DIAGNOSTIC_EXECUTED=false" in text
    assert "PRODUCTION_DEPLOY_PERFORMED=false" in text

    for forbidden in (
        "git checkout",
        "git reset",
        "git switch",
        "git pull",
        "git fetch",
        "docker exec",
        "systemctl ",
        "curl ",
        "wget ",
    ):
        assert forbidden not in text


def test_registration_parent_parse_is_strict_ifs_safe_and_fail_closed() -> None:
    commit = "1" * 40
    parent = "2" * 40
    other_parent = "3" * 40

    valid = _parse_registration_line(f"{commit} {parent}", commit)
    assert valid.returncode == 0
    assert valid.stdout == f"{parent}\n"

    for line, expected in (
        (commit, commit),
        (f"{commit} {parent} {other_parent}", commit),
        (f"{commit}\t{parent}", commit),
        (f"{commit}  {parent}", commit),
        (f"{commit} {'z' * 40}", commit),
        (f"{commit} {parent}", "4" * 40),
    ):
        result = _parse_registration_line(line, expected)
        assert result.returncode != 0


def test_registration_anchor_accepts_reviewed_maintenance_truth_table() -> None:
    assert _registration_anchor_allowed(workflow_changed=True, installer_changed=False) is True
    assert _registration_anchor_allowed(workflow_changed=False, installer_changed=True) is True
    assert _registration_anchor_allowed(workflow_changed=True, installer_changed=True) is True
    assert _registration_anchor_allowed(workflow_changed=False, installer_changed=False) is False


def test_execution_anchor_truth_table_keeps_current_main_as_upper_bound_witness() -> None:
    assert _execution_anchor_allowed(
        registration_is_ancestor=True,
        execution_is_reachable_from_current_main=True,
        trusted_execution_matches_registration=True,
        trusted_current_main_matches_registration=True,
    )

    for rejected in (
        {
            "registration_is_ancestor": False,
            "execution_is_reachable_from_current_main": True,
            "trusted_execution_matches_registration": True,
            "trusted_current_main_matches_registration": True,
        },
        {
            "registration_is_ancestor": True,
            "execution_is_reachable_from_current_main": False,
            "trusted_execution_matches_registration": True,
            "trusted_current_main_matches_registration": True,
        },
        {
            "registration_is_ancestor": True,
            "execution_is_reachable_from_current_main": True,
            "trusted_execution_matches_registration": False,
            "trusted_current_main_matches_registration": True,
        },
        {
            "registration_is_ancestor": True,
            "execution_is_reachable_from_current_main": True,
            "trusted_execution_matches_registration": True,
            "trusted_current_main_matches_registration": False,
        },
    ):
        assert not _execution_anchor_allowed(**rejected)


def test_execution_ci_reuses_registration_only_for_identical_checkout() -> None:
    assert (
        _execution_ci_mode(execution_equals_registration=True, exact_execution_push_ci=False)
        == "registration_ci_reuse"
    )
    assert (
        _execution_ci_mode(execution_equals_registration=False, exact_execution_push_ci=True)
        == "exact_execution_push_ci"
    )
    assert _execution_ci_mode(
        execution_equals_registration=False, exact_execution_push_ci=False
    ) is None


def test_workflow_authorizes_bridge_revision_and_bounded_execution_checkout() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert "actions: read" in text
    assert "registration_sha:" in text
    assert "execution_sha:" in text
    assert "current_main_sha:" in text
    assert "REQUESTED_EXECUTION_SHA: ${{ inputs.execution_sha }}" in text
    assert 'execution_sha = os.environ["REQUESTED_EXECUTION_SHA"].strip()' in text
    assert 're.fullmatch(r"[0-9a-f]{40}", execution_sha)' in text
    assert "/branches/main" in text
    assert "bridge registration SHA must be a single-parent reviewed merge" in text
    assert "workflow_changed = content_blob(workflow_path, registration_sha) != content_blob(" in text
    assert "installer_changed = content_blob(installer_path, registration_sha) != content_blob(" in text
    assert "if not (workflow_changed or installer_changed):" in text
    assert "selected PR did not introduce or update the K3C bridge control plane" in text
    assert "selected PR did not introduce or update the K3C bridge workflow" not in text
    assert "selected PR did not introduce or update the K3C bridge installer" not in text
    assert "requested execution checkout is not a registration descendant" in text
    assert "requested execution checkout is not reachable from current main" in text
    assert "if execution_sha == registration_sha:" in text
    assert 'execution_ci_mode = "registration_ci_reuse"' in text
    assert 'execution_ci_mode = "exact_execution_push_ci"' in text
    assert "exact execution checkout does not have successful main push CI" in text
    assert "trusted K3C source drift at execution checkout" in text
    assert "trusted K3C source drift on current main" in text
    assert 'execution_sha = str((main_branch.get("commit") or {}).get("sha") or "")' not in text
    assert "exact execution main does not have successful push CI" not in text
    assert "workflow_runs(current_main_sha" not in text
    assert '"$REGISTRATION_SHA"' in text
    assert '"$EXECUTION_SHA"' in text
    assert "bridge_schema_version\") != 2" in text
    assert "kaufland-k3c-promo-structure-rpi5-bridge-v2" in text
    assert "execution_checkout_sha" in text
    assert "Registered bridge revision" in text
    assert "Exact execution checkout" in text
    assert "Current-main witness" in text

    for forbidden in (
        "pull_request_target:",
        "issue_comment:",
        "repository_dispatch:",
        "schedule:",
        "actions/checkout@",
        "gh api --method POST",
        "docker ",
    ):
        assert forbidden not in text


def test_runbook_documents_non_rewind_bounded_execution_contract_and_separate_live_gates() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")

    assert "bridge-v2" in text
    assert "registration SHA" in text
    assert "execution checkout SHA" in text
    assert "descendant" in text
    assert "never rewind" in text.lower()
    assert "trusted" in text.lower()
    assert "at least one" in text.lower()
    assert "workflow or installer" in text.lower()
    assert "exact execution SHA" in text
    assert "current GitHub `main`" in text
    assert "upper-bound" in text
    assert "registration CI" in text
    assert "source-sync bridge" in text
    assert "root registration" in text
    assert "diagnostic execution" in text
    assert "no automatic retry" in text.lower()
    assert "**Production deploy: NO.**" in text
