from __future__ import annotations

import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[2]
RELEASE_INSTALLER = ROOT / "tools/runner/install-rpi5-release-dispatcher.sh"
OPERATOR_INSTALLER = ROOT / "tools/runner/install-hermes-deals-operator.sh"


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def test_release_installer_queries_exact_commands_instead_of_grepping_sudo_list() -> None:
    subprocess.run(["bash", "-n", str(RELEASE_INSTALLER)], check=True)
    text = read(RELEASE_INSTALLER)

    assert (
        'sudo -n -l -U github-release-runner -- "$DISPATCHER" '
        ">/dev/null 2>&1"
    ) in text
    assert (
        'sudo -n -l -U github-release-runner -- "$root_only" '
        ">/dev/null 2>&1"
    ) in text
    assert "command-specific Defaults entries" in text

    for forbidden in (
        "sudo -l -U github-release-runner | grep",
        "sudo -l -U github-release-runner |grep",
        'grep -Fq "$root_only"',
    ):
        assert forbidden not in text


def test_operator_installer_checks_exact_intended_invocations() -> None:
    subprocess.run(["bash", "-n", str(OPERATOR_INSTALLER)], check=True)
    text = read(OPERATOR_INSTALLER)

    for marker in (
        'sudo -n -l -U "$OWNER" -- "$DEST" "$HEAD_SHA" >/dev/null 2>&1',
        'sudo -n -l -U "$OWNER" -- "$MAIN_DEPLOY" "$HEAD_SHA" >/dev/null 2>&1',
        "not a valid authorization check",
    ):
        assert marker in text

    for forbidden in (
        'sudo -l -U "$OWNER" | grep',
        'sudo -l -U "$OWNER" |grep',
        'grep -Fq "$MAIN_DEPLOY"',
    ):
        assert forbidden not in text
