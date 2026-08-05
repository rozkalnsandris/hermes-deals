from __future__ import annotations

import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[2]
REGISTER = ROOT / "tools/runner/release/hermes-deals-release-register"
DOCKERFILE = ROOT / "backend/Dockerfile"
REQUIREMENTS = ROOT / "backend/requirements.txt"
CI = ROOT / ".github/workflows/ci.yml"


def read(path: pathlib.Path) -> str:
    return path.read_text(encoding="utf-8")


def test_release_register_uses_runtime_only_image_smoke() -> None:
    subprocess.run(["bash", "-n", str(REGISTER)], check=True)
    text = read(REGISTER)

    for marker in (
        "IMAGE_SMOKE_OUTPUT=",
        "EXPECTED_APP_VERSION",
        "from fastapi.testclient import TestClient",
        "schema = app.openapi()",
        'client.get("/api/health")',
        'client.get("/ui")',
        "IMAGE_SMOKE_RESULT=PASS",
        "production image runtime smoke validation failed",
    ):
        assert marker in text

    assert "python -m pytest" not in text
    assert "pip install pytest" not in text


def test_production_image_excludes_tests_and_pytest() -> None:
    dockerfile = read(DOCKERFILE)
    requirements = read(REQUIREMENTS).lower()
    ci = read(CI)

    assert "COPY tests ./tests" not in dockerfile
    assert "pytest" not in requirements
    assert "python -m pip install pytest==8.4.1" in ci
    assert "python -m pytest -q" in ci
