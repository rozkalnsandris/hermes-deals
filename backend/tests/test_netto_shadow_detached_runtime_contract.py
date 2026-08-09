from __future__ import annotations

from pathlib import Path
import subprocess
import tempfile


ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "tools/runner/install-netto-shadow-rpi5-audit-worktree.sh"
SOURCE_INSTALLER = ROOT / "tools/runner/install-netto-shadow-rpi5-audit.sh"
SOURCE_RUNNER = ROOT / "tools/run-hermes-deals-netto-shadow-evidence-v01.sh"
SOURCE_TOOL = ROOT / "tools/netto_rpi5_shadow_audit.py"
SOURCE_REPO = "/home/andris/hermes-deals-worktrees/netto-shadow-audit-install"


def _transform_program() -> str:
    text = INSTALLER.read_text(encoding="utf-8")
    marker = 'python3 - "$PATCHED_INSTALLER" "$PATCHED_RUNNER" "$PATCHED_TOOL" "$SOURCE_REPO" <<\'PY\'\n'
    start = text.index(marker) + len(marker)
    end = text.index("\nPY\n\n/bin/bash -n \"$PATCHED_INSTALLER\"", start)
    return text[start:end]


def _patched_runtime(tmp: Path) -> tuple[Path, Path, Path]:
    installer = tmp / "install-netto-shadow-rpi5-audit.sh"
    runner = tmp / "netto-shadow-v1.sh"
    tool = tmp / "netto-shadow-v1.py"
    installer.write_text(SOURCE_INSTALLER.read_text(encoding="utf-8"), encoding="utf-8")
    runner.write_text(SOURCE_RUNNER.read_text(encoding="utf-8"), encoding="utf-8")
    tool.write_text(SOURCE_TOOL.read_text(encoding="utf-8"), encoding="utf-8")
    subprocess.run(
        ["python3", "-", str(installer), str(runner), str(tool), SOURCE_REPO],
        input=_transform_program(),
        text=True,
        check=True,
    )
    return installer, runner, tool


def test_transform_program_compiles() -> None:
    compile(_transform_program(), str(INSTALLER), "exec")


def test_registered_runtime_accepts_detached_exact_sha_contract() -> None:
    with tempfile.TemporaryDirectory() as raw:
        _, runner, tool = _patched_runtime(Path(raw))
        subprocess.run(["bash", "-n", str(runner)], check=True)
        compile(tool.read_text(encoding="utf-8"), str(tool), "exec")

        runner_text = runner.read_text(encoding="utf-8")
        assert "repository branch is not main" not in runner_text
        assert "branch --show-current" not in runner_text
        assert "repository origin is not the Hermes Deals repository" in runner_text
        assert "show-ref --verify --quiet refs/remotes/origin/main" in runner_text
        assert 'merge-base --is-ancestor "$HERMES_AUDIT_EXPECTED_HEAD" refs/remotes/origin/main' in runner_text
        assert 'rev-parse HEAD)" == "$HERMES_AUDIT_EXPECTED_HEAD"' in runner_text
        assert "repository worktree is not clean" in runner_text

        tool_text = tool.read_text(encoding="utf-8")
        assert "main-branch Git checkout" not in tool_text
        assert 'git(resolved, "branch", "--show-current")' not in tool_text
        assert "audit repository must be a Git worktree" in tool_text
        assert "audit repository HEAD mismatch" in tool_text
        assert "audit repository must be clean" in tool_text
        assert "audit repository origin is not the Hermes Deals repository" in tool_text
        assert "audit repository origin/main is unavailable" in tool_text
        assert "audit repository HEAD is not reachable from origin/main" in tool_text
        assert '"merge-base", "--is-ancestor", expected_head, "refs/remotes/origin/main"' in tool_text


def test_registration_source_still_requires_named_main_branch() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert "source worktree branch must be main" in text
    assert "source worktree HEAD mismatch" in text
    assert "source worktree is not clean" in text
    assert "source origin is not the Hermes Deals repository" in text
    assert "PRIMARY_GIT_COMMON_DIR='/home/andris/hermes-deals/.git'" in text


def test_detached_runtime_fix_preserves_read_only_boundary() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    for forbidden in (
        "docker exec",
        "docker compose",
        "psql ",
        "git reset --hard",
        "git clean",
        "systemctl enable",
    ):
        assert forbidden not in text
    assert "PRODUCTION_APPLY_AUTHORIZED=false" in text
    assert "/usr/local/sbin/hermes-deals-netto-shadow-audit-dispatch" in text
