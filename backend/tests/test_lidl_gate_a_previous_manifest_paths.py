from __future__ import annotations

import importlib.util
import json
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


def test_retry_authorized_previous_manifest_is_rejected(tmp_path: Path) -> None:
    selector = load_selector()
    root = tmp_path / "evidence"
    root.mkdir()
    current = root / "lidl-gate-a-current"
    current.mkdir()
    manifest = root / "lidl-gate-a-unsafe" / "controller" / "controller-manifest.json"
    manifest.parent.mkdir(parents=True)
    manifest.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "controller_version": "lidl-weekly-shadow-controller-v1",
                "result": "READY",
                "execution_fingerprint": "a" * 64,
                "dry_run": True,
                "corpus_write_authorized": False,
                "database_write_authorized": False,
                "review_write_authorized": False,
                "production_publish_authorized": False,
                "systemd_change_authorized": False,
                "bounded_retry_authorized": True,
            }
        )
        + "\n",
        encoding="utf-8",
    )

    with pytest.raises(selector.PreviousManifestError, match="no completed safe"):
        selector.select_previous_manifest(root, current)
