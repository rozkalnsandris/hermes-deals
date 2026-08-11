from __future__ import annotations

import hashlib
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
LOCKS = BACKEND / "locks"
MANIFEST = LOCKS / "manifest.json"
COMPILER = ROOT / "scripts" / "compile-python-locks.sh"
LOCK_WORKFLOW = ROOT / ".github" / "workflows" / "python-dependency-locks.yml"
ARM64_PREFLIGHT = ROOT / "tools" / "verify-python-runtime-lock-arm64.sh"
DOCKERFILE = BACKEND / "Dockerfile"


def _direct_requirements(path: Path) -> list[str]:
    return [
        line.strip()
        for line in path.read_text(encoding="utf-8").splitlines()
        if line.strip() and not line.lstrip().startswith("#")
    ]


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _requirement_blocks(text: str) -> list[str]:
    lines = text.splitlines()
    starts = [
        index
        for index, line in enumerate(lines)
        if re.match(r"^[A-Za-z0-9_.-]+==[^\s\\]+", line)
    ]
    blocks: list[str] = []
    for offset, start in enumerate(starts):
        end = starts[offset + 1] if offset + 1 < len(starts) else len(lines)
        blocks.append("\n".join(lines[start:end]))
    return blocks


def test_runtime_direct_intent_matches_legacy_rpi5_input() -> None:
    assert _direct_requirements(BACKEND / "requirements.in") == _direct_requirements(
        BACKEND / "requirements.txt"
    )
    assert _direct_requirements(BACKEND / "requirements-ci.in") == [
        "-r requirements.in",
        "pytest==8.4.1",
    ]


def test_lock_manifest_binds_reviewed_bytes_and_toolchain() -> None:
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    assert manifest["schema_version"] == 1
    assert manifest["compiler"] == {
        "pip": "26.0.1",
        "pip_tools": "7.6.0",
        "resolver": "backtracking",
        "wheel_only": True,
        "generate_hashes": True,
    }
    assert set(manifest["locks"]) == {
        "runtime-py311.txt",
        "ci-py311.txt",
        "runtime-py313.txt",
    }
    for filename, identity in manifest["locks"].items():
        assert identity["python"] in {"3.11", "3.13"}
        assert re.fullmatch(r"[0-9a-f]{64}", identity["sha256"])
        assert _sha256(LOCKS / filename) == identity["sha256"]


def test_every_lock_is_wheel_only_exact_and_hash_bound() -> None:
    for filename in ("runtime-py311.txt", "ci-py311.txt", "runtime-py313.txt"):
        text = (LOCKS / filename).read_text(encoding="utf-8")
        assert "--only-binary :all:" in text
        assert "--index-url" not in text
        assert "--extra-index-url" not in text
        assert "--trusted-host" not in text
        assert " @ " not in text
        blocks = _requirement_blocks(text)
        assert blocks
        for block in blocks:
            first_line = block.splitlines()[0]
            assert re.match(r"^[A-Za-z0-9_.-]+==[^\s\\]+", first_line)
            assert "--hash=sha256:" in block


def test_compiler_pins_toolchain_and_fails_closed_to_wheels() -> None:
    text = COMPILER.read_text(encoding="utf-8")
    for marker in (
        'PIP_VERSION="26.0.1"',
        'PIP_TOOLS_VERSION="7.6.0"',
        "--resolver=backtracking",
        "--generate-hashes",
        "--no-emit-index-url",
        "--no-emit-trusted-host",
        '--pip-args="--only-binary=:all:"',
    ):
        assert marker in text
    assert "pip install --upgrade pip" not in text


def test_lock_verification_workflow_is_read_only() -> None:
    text = LOCK_WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in text
    assert "contents: write" not in text
    assert "git push" not in text
    assert "git diff --exit-code" in text
    assert "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f" in text


def test_production_image_installs_only_from_python313_hash_lock() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "COPY locks/runtime-py313.txt ./locks/runtime-py313.txt" in text
    assert "--require-hashes" in text
    assert "--only-binary=:all:" in text
    assert "-r locks/runtime-py313.txt" in text
    assert "python -m pip check" in text
    assert "COPY requirements.txt" not in text
    assert "-r requirements.txt" not in text


def test_arm64_preflight_is_exact_commit_clean_and_production_safe() -> None:
    text = ARM64_PREFLIGHT.read_text(encoding="utf-8")
    for marker in (
        'EXPECTED_SHA="${1:-}"',
        'ACTUAL_SHA="$(git rev-parse HEAD)"',
        "git status --porcelain --untracked-files=all",
        "aarch64|arm64",
        '[[ "$PYTHON_LINE" != "3.11" ]]',
        'LOCK_REL="backend/locks/runtime-py311.txt"',
        "--require-hashes",
        "--only-binary=:all:",
        '"$VENV_PYTHON" -m pip check',
        "PRODUCTION_DATABASE_WRITE=false",
        "PRODUCTION_DEPLOYMENT=false",
        "SCHEDULER_ACTIVATION=false",
        "SYSTEMD_MUTATION=false",
        "DOCKER_MUTATION=false",
    ):
        assert marker in text
    for forbidden in (
        "sudo ",
        "docker ",
        "systemctl ",
        "psql ",
        "alembic ",
        "git push",
    ):
        assert forbidden not in text
