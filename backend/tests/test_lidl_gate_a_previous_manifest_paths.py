from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
SELECTOR = ROOT / "tools" / "lidl_gate_a_previous_manifest.py"


def load_selector():
    spec = importlib.util.spec_from_file_location("lidl_gate_a_previous_manifest_paths", SELECTOR)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_symlinked_evidence_root_is_rejected(tmp_path: Path) -> None:
    selector = load_selector()
    real = tmp_path / "real"
    real.mkdir()
    current = real / "lidl-gate-a-current"
    current.mkdir()
    linked = tmp_path / "evidence-link"
    linked.symlink_to(real, target_is_directory=True)

    with pytest.raises(selector.PreviousManifestError, match="evidence root.*unsafe"):
        selector.select_previous_manifest(linked, current)


def test_symlinked_current_run_is_rejected(tmp_path: Path) -> None:
    selector = load_selector()
    root = tmp_path / "evidence"
    root.mkdir()
    real_current = root / "lidl-gate-a-current-real"
    real_current.mkdir()
    linked_current = root / "lidl-gate-a-current"
    linked_current.symlink_to(real_current, target_is_directory=True)

    with pytest.raises(selector.PreviousManifestError, match="current run.*unsafe"):
        selector.select_previous_manifest(root, linked_current)
