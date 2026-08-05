from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import stat
import subprocess

import pytest


ROOT = Path(__file__).resolve().parents[2]
NORMALIZER = ROOT / "tools" / "runner" / "normalize-actions-runner-metadata.py"
BOOTSTRAP_V2 = ROOT / "tools" / "runner" / "bootstrap-hermes-deals-release-runtime-v2.sh"
EXPECTED_NAME = "rpi5-hermes-deals-release"
EXPECTED_URL = "https://github.com/rozkalnsandris/hermes-deals"


def load_normalizer():
    spec = importlib.util.spec_from_file_location("runner_metadata_normalizer", NORMALIZER)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def metadata_bytes(name: str = EXPECTED_NAME, url: str = EXPECTED_URL) -> bytes:
    return json.dumps({"agentName": name, "gitHubUrl": url}).encode("utf-8")


def test_bom_metadata_is_validated_and_normalized_atomically(tmp_path: Path) -> None:
    module = load_normalizer()
    path = tmp_path / ".runner"
    path.write_bytes(module.UTF8_BOM + metadata_bytes())
    path.chmod(0o640)
    before = path.stat()

    assert module.normalize(
        path,
        expected_name=EXPECTED_NAME,
        expected_url=EXPECTED_URL,
        expected_uid=before.st_uid,
        expected_gid=before.st_gid,
    ) is True

    assert path.read_bytes() == metadata_bytes()
    after = path.stat()
    assert stat.S_IMODE(after.st_mode) == 0o640
    assert after.st_uid == before.st_uid
    assert after.st_gid == before.st_gid
    assert not list(tmp_path.glob("..runner.bomfix.*.tmp"))


def test_non_bom_metadata_is_not_rewritten(tmp_path: Path) -> None:
    module = load_normalizer()
    path = tmp_path / ".runner"
    original = metadata_bytes()
    path.write_bytes(original)
    before = path.stat()

    assert module.normalize(
        path,
        expected_name=EXPECTED_NAME,
        expected_url=EXPECTED_URL,
        expected_uid=before.st_uid,
        expected_gid=before.st_gid,
    ) is False
    assert path.read_bytes() == original


def test_binding_mismatch_fails_without_modifying_file(tmp_path: Path) -> None:
    module = load_normalizer()
    path = tmp_path / ".runner"
    original = module.UTF8_BOM + metadata_bytes(name="unexpected-runner")
    path.write_bytes(original)

    with pytest.raises(module.MetadataError, match="runner name mismatch"):
        module.normalize(
            path,
            expected_name=EXPECTED_NAME,
            expected_url=EXPECTED_URL,
        )
    assert path.read_bytes() == original


def test_v2_wrapper_retries_only_after_valid_bom_repair() -> None:
    subprocess.run(["bash", "-n", str(BOOTSTRAP_V2)], check=True)
    text = BOOTSTRAP_V2.read_text(encoding="utf-8")
    for marker in (
        "origin/main does not equal the authorized bootstrap SHA",
        "bootstrap-hermes-deals-release-runtime.sh",
        "normalize-actions-runner-metadata.py",
        '[[ -f "$RUNNER_META" && ! -L "$RUNNER_META" ]]',
        "no valid BOM-only repair was available; no retry performed",
        "Retrying the exact bootstrap once",
        'env HERMES_GITHUB_TOKEN="$HERMES_GITHUB_TOKEN" bash "$V1" "$EXPECTED_SHA"',
    ):
        assert marker in text
    assert text.count("run_v1\n") == 2
    assert "--replace" not in text
    assert "rm -rf -- /home/github-release-runner" not in text
    assert "docker" not in text
    assert "alembic" not in text
