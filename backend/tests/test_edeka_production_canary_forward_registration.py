from __future__ import annotations

from pathlib import Path
import subprocess
from runpy import run_path

import pytest

ROOT = Path(__file__).resolve().parents[2]
WRAPPER = ROOT / "tools/runner/install_edeka_production_canary_control_forward_nonrewind.py"
DISPATCHER = ROOT / "tools/runner/edeka_production_canary_control.py"

TARGET_DISPATCHER_BLOB = "95339e076907e43eb2307fce66f4768a60ef2296"
PREDECESSOR_DISPATCHER_BLOB = "f4c54c91ded3edcd631f3e83f37a54229dfb2413"
EXPECTED_INSTALLER_BLOB = "4285d3b1bdbaeddfc2d6698a96cb91c40f7d7946"


def test_forward_wrapper_classifies_only_absent_target_or_exact_predecessor() -> None:
    namespace = run_path(str(WRAPPER))
    classify = namespace["classify_dispatcher_blob"]
    error = namespace["ForwardUpgradeError"]

    assert classify(None) == "absent"
    assert classify(TARGET_DISPATCHER_BLOB) == "identical"
    assert classify(PREDECESSOR_DISPATCHER_BLOB) == "forward_upgrade"

    with pytest.raises(error):
        classify("0" * 40)


def test_forward_wrapper_target_blob_matches_current_dispatcher_and_predecessor_exists() -> None:
    namespace = run_path(str(WRAPPER))
    blob_oid = namespace["git_blob_oid"]

    assert blob_oid(DISPATCHER.read_bytes()) == TARGET_DISPATCHER_BLOB

    predecessor = subprocess.run(
        ["git", "cat-file", "blob", PREDECESSOR_DISPATCHER_BLOB],
        cwd=ROOT,
        check=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    ).stdout
    assert predecessor
    assert blob_oid(predecessor) == PREDECESSOR_DISPATCHER_BLOB
    assert predecessor != DISPATCHER.read_bytes()


def test_forward_wrapper_is_exact_main_atomic_and_registration_only() -> None:
    source = WRAPPER.read_text(encoding="utf-8")

    assert f'EXPECTED_INSTALLER_BLOB = "{EXPECTED_INSTALLER_BLOB}"' in source
    assert f'TARGET_DISPATCHER_BLOB = "{TARGET_DISPATCHER_BLOB}"' in source
    assert f'PREDECESSOR_DISPATCHER_BLOB = "{PREDECESSOR_DISPATCHER_BLOB}"' in source
    assert 'SOURCE_REPO = Path("/home/andris/hermes-deals-audit-source-edeka")' in source
    assert 'git_text("rev-parse", "HEAD") == target_sha' in source
    assert 'git_text("rev-parse", "refs/remotes/origin/main") == target_sha' in source
    assert 'git("status", "--porcelain=v1", "-z", "--untracked-files=all").stdout == b""' in source
    assert 'os.replace(temp, DISPATCH_DST)' in source
    assert 'fsync_directory(DISPATCH_DST.parent)' in source
    assert 'before_now == before' in source
    assert 'state_after == "identical"' in source
    assert '[ "/usr/bin/python3"' not in source
    assert '["/usr/bin/python3", str(installer), "--registration-sha", target_sha]' in source
    assert "systemctl" not in source
    assert "docker run" not in source
    assert "edeka_production_canary --" not in source
    assert 'print("CANARY_OPERATION=false")' in source
    assert 'print("PRODUCTION_DATABASE_WRITE=false")' in source
    assert 'print("PRODUCTION_DEPLOY=false")' in source


def test_forward_wrapper_does_not_create_a_generic_upgrade_allowlist() -> None:
    source = WRAPPER.read_text(encoding="utf-8")

    assert "PREDECESSOR_DISPATCHER_BLOB" in source
    assert "TARGET_DISPATCHER_BLOB" in source
    assert "ALLOWED_PREDECESSORS" not in source
    assert "KNOWN_PREDECESSORS" not in source
    assert 'current_blob == PREDECESSOR_DISPATCHER_BLOB' in source
