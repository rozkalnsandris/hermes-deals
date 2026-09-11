from __future__ import annotations

import hashlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "tools/runner/install-aldi-new-baseline-weekly-shadow-dispatcher.sh"
DISPATCHER = ROOT / "tools/runner/aldi-new-baseline-weekly-shadow-dispatcher.sh"
CANONICAL_BRIDGE = (
    "/usr/local/libexec/hermes-deals-audits/aldi-new-baseline-weekly-shadow-v01/"
    "aldi_new_baseline_weekly_shadow_bridge.py"
)


def _valid(config: dict[str, str], expected_main: str, installed: dict[str, str]) -> bool:
    if config["registered_main_sha"] != expected_main:
        return False
    if config["bridge_path"] != CANONICAL_BRIDGE:
        return False
    return installed.get(config["bridge_path"]) == config["bridge_sha256"]


def test_source_contract_uses_one_canonical_bridge_path_and_hash_binding():
    installer = INSTALLER.read_text(encoding="utf-8")
    dispatcher = DISPATCHER.read_text(encoding="utf-8")
    assert "bridge_path='$LIBEXEC/aldi_new_baseline_weekly_shadow_bridge.py'" in installer
    assert CANONICAL_BRIDGE in dispatcher
    digest = hashlib.sha256(b"bridge").hexdigest()
    sha = "a" * 40
    config = {"registered_main_sha": sha, "bridge_path": CANONICAL_BRIDGE, "bridge_sha256": digest}
    assert _valid(config, sha, {CANONICAL_BRIDGE: digest})


def test_one_character_path_drift_is_rejected():
    digest = hashlib.sha256(b"bridge").hexdigest()
    sha = "a" * 40
    drifted = CANONICAL_BRIDGE.replace("weekly_shadow", "weekly-shadow")
    config = {"registered_main_sha": sha, "bridge_path": drifted, "bridge_sha256": digest}
    assert not _valid(config, sha, {drifted: digest})


def test_stale_main_sha_is_rejected():
    digest = hashlib.sha256(b"bridge").hexdigest()
    config = {"registered_main_sha": "a" * 40, "bridge_path": CANONICAL_BRIDGE, "bridge_sha256": digest}
    assert not _valid(config, "b" * 40, {CANONICAL_BRIDGE: digest})


def test_installed_hash_mismatch_is_rejected():
    digest = hashlib.sha256(b"bridge").hexdigest()
    sha = "a" * 40
    config = {"registered_main_sha": sha, "bridge_path": CANONICAL_BRIDGE, "bridge_sha256": digest}
    installed = {CANONICAL_BRIDGE: hashlib.sha256(b"other").hexdigest()}
    assert not _valid(config, sha, installed)
