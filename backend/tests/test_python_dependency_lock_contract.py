from __future__ import annotations

import hashlib
import importlib.util
import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
LOCKS = BACKEND / "locks"
MANIFEST = LOCKS / "manifest.json"
COMPILER = ROOT / "scripts" / "compile-python-locks.sh"
ENV_VERIFIER = ROOT / "scripts" / "verify-python-lock-environment.py"
LOCK_WORKFLOW = ROOT / ".github" / "workflows" / "python-dependency-locks.yml"
CI_WORKFLOW = ROOT / ".github" / "workflows" / "ci.yml"
ARM64_PREFLIGHT = ROOT / "tools" / "verify-python-runtime-lock-arm64.sh"
DOCKERFILE = BACKEND / "Dockerfile"


REQUIREMENT_LINE_RE = re.compile(
    r"^[A-Za-z0-9_.-]+(?:\[[A-Za-z0-9_,.-]+\])?==[^\s\\]+"
)


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
        if REQUIREMENT_LINE_RE.match(line)
    ]
    blocks: list[str] = []
    for offset, start in enumerate(starts):
        end = starts[offset + 1] if offset + 1 < len(starts) else len(lines)
        blocks.append("\n".join(lines[start:end]))
    return blocks


def _load_environment_verifier():
    spec = importlib.util.spec_from_file_location("python_lock_env_verifier", ENV_VERIFIER)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_runtime_and_ci_direct_intent_are_separated() -> None:
    assert _direct_requirements(BACKEND / "requirements.in") == _direct_requirements(
        BACKEND / "requirements.txt"
    )
    assert _direct_requirements(BACKEND / "requirements-ci.in") == ["pytest==8.4.1"]
    ci_lock = (LOCKS / "ci-py313.txt").read_text(encoding="utf-8")
    assert "-r runtime-py313.txt" in ci_lock


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
    assert set(manifest["locks"]) == {"runtime-py313.txt", "ci-py313.txt"}
    for filename, identity in manifest["locks"].items():
        assert identity["python"] == "3.13"
        assert re.fullmatch(r"[0-9a-f]{64}", identity["sha256"])
        assert _sha256(LOCKS / filename) == identity["sha256"]


def test_active_locks_are_wheel_only_exact_and_hash_bound() -> None:
    runtime_text = (LOCKS / "runtime-py313.txt").read_text(encoding="utf-8")
    ci_text = (LOCKS / "ci-py313.txt").read_text(encoding="utf-8")
    assert "-r runtime-py313.txt" in ci_text
    assert any(
        block.startswith("psycopg[binary]==3.3.4")
        for block in _requirement_blocks(runtime_text)
    )
    for text in (runtime_text, ci_text):
        assert "--only-binary :all:" in text
        assert "--index-url" not in text
        assert "--extra-index-url" not in text
        assert "--trusted-host" not in text
        assert " @ " not in text
        blocks = _requirement_blocks(text)
        assert blocks
        for block in blocks:
            first_line = block.splitlines()[0]
            assert REQUIREMENT_LINE_RE.match(first_line)
            assert "--hash=sha256:" in block


def test_environment_verifier_parses_extras_and_rejects_unreviewed_extras() -> None:
    module = _load_environment_verifier()
    expected = module.expected_distributions(LOCKS / "runtime-py313.txt")
    assert expected["psycopg"] == "3.3.4"
    assert expected["psycopg-binary"] == "3.3.4"
    assert module.BOOTSTRAP_ALLOWLIST == {"pip", "setuptools"}
    text = ENV_VERIFIER.read_text(encoding="utf-8")
    for marker in (
        "missing locked distributions:",
        "locked distribution version mismatch:",
        "unexpected installed distributions:",
        "PYTHON_LOCK_ENVIRONMENT=PASS",
        "LOCKED_INVENTORY_SHA256=",
    ):
        assert marker in text


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
        'compile_lock "$EXPECTED_INPUT" "backend/locks/runtime-py313.txt"',
        'compile_lock "$CI_INPUT" "$CI_OVERLAY_TMP"',
        "'-r runtime-py313.txt'",
    ):
        assert marker in text
    assert "3.11" not in text
    assert "pip install --upgrade pip" not in text


def test_lock_verification_workflow_is_read_only() -> None:
    text = LOCK_WORKFLOW.read_text(encoding="utf-8")
    assert "permissions:\n  contents: read" in text
    assert "contents: write" not in text
    assert "git push" not in text
    assert "git diff --exit-code" in text
    assert "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f" in text


def test_python_ci_jobs_install_only_from_hash_lock() -> None:
    text = CI_WORKFLOW.read_text(encoding="utf-8")
    assert text.count('python-version: "3.13"') == 2
    assert text.count("cache-dependency-path: backend/locks/ci-py313.txt") == 2
    assert text.count("- name: Install hash-locked dependencies") == 2
    assert text.count("--require-hashes") == 2
    assert text.count("--only-binary=:all:") == 2
    assert text.count("-r locks/ci-py313.txt") == 2
    assert text.count("python -m pip check") == 2
    for forbidden in (
        'python-version: "3.11"',
        "ci-py311.txt",
        "cache-dependency-path: backend/requirements.txt",
        "python -m pip install --upgrade pip",
        "python -m pip install -r requirements.txt",
        "python -m pip install pytest==8.4.1",
    ):
        assert forbidden not in text


def test_production_image_installs_only_from_python313_hash_lock() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")
    assert "FROM python:3.13.14-slim-bookworm@sha256:" in text
    assert "COPY locks/runtime-py313.txt ./locks/runtime-py313.txt" in text
    assert "--require-hashes" in text
    assert "--only-binary=:all:" in text
    assert "-r locks/runtime-py313.txt" in text
    assert "python -m pip check" in text
    assert "COPY requirements.txt" not in text
    assert "-r requirements.txt" not in text


def test_arm64_preflight_is_exact_commit_clean_capacity_guarded_and_production_safe() -> None:
    text = ARM64_PREFLIGHT.read_text(encoding="utf-8")
    for marker in (
        'EXPECTED_SHA="${1:-}"',
        'ACTUAL_SHA="$(git rev-parse HEAD)"',
        "git status --porcelain --untracked-files=all",
        "aarch64|arm64",
        '[[ "$PYTHON_LINE" != "3.13" ]]',
        'LOCK_REL="backend/locks/runtime-py313.txt"',
        'identity = manifest["locks"]["runtime-py313.txt"]',
        'identity["python"] != "3.13"',
        'VERIFIER_REL="scripts/verify-python-lock-environment.py"',
        'TMP_BASE="${HERMES_LOCK_TMPDIR:-/var/tmp}"',
        "MIN_TMP_KIB=$((1024 * 1024))",
        'LC_ALL=C df -Pk -- "$TMP_BASE"',
        'AVAILABLE_TMP_KIB < MIN_TMP_KIB',
        'mktemp -d -- "$TMP_BASE/hermes-python-lock-arm64.XXXXXX"',
        "--require-hashes",
        "--only-binary=:all:",
        '"$VENV_PYTHON" -m pip check',
        '"$VENV_PYTHON" "$VERIFIER_REL" "$LOCK_REL"',
        "LOCKED_INVENTORY_SHA256=$INVENTORY_SHA",
        "TEMP_BASE=$TMP_BASE",
        "TEMP_AVAILABLE_KIB_BEFORE=$AVAILABLE_TMP_KIB",
        "PRODUCTION_DATABASE_WRITE=false",
        "PRODUCTION_DEPLOYMENT=false",
        "SCHEDULER_ACTIVATION=false",
        "SYSTEMD_MUTATION=false",
        "DOCKER_MUTATION=false",
    ):
        assert marker in text
    assert "runtime-py311" not in text
    assert '${TMPDIR:-/tmp}/hermes-python-lock-arm64' not in text
    for forbidden in (
        "sudo ",
        "docker ",
        "systemctl ",
        "psql ",
        "alembic ",
        "git push",
    ):
        assert forbidden not in text
