from __future__ import annotations

import importlib.util
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
BRIDGE = ROOT / "tools" / "github_edeka_weekly_monitor_control.py"
OLD = ROOT / "tools" / "runner" / "edeka_weekly_monitor_control.py"
MONDAY = ROOT / "tools" / "runner" / "edeka_weekly_monitor_control_monday.py"
FORWARD = ROOT / "tools" / "runner" / "edeka_monday_forward_cutover.py"

OLD_SHA = "85c3aca4ac62cbffa281365562af52c5e52d8d24"
OLD_FP = "970fac96fd487fe2a027f6dd1055e6563ccec331e53e889511c1e35c5038f947"
NEW_SHA = "684b562084492eebecc76a898b1b5d92e6a8c2e4"
NEW_FP = "19162a6e25844ff21f96f385e11715cecc34d8ede8dad971c03381d911aa0957"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def owner_command(sha: str, fingerprint: str, operation: str = "disable") -> str:
    return (
        "/hermes-edeka monitor " + operation
        + " control=" + "d" * 40
        + " registration=" + sha + " fingerprint=" + fingerprint
        + " refetch=" + ("authorized" if operation == "activate" else "forbidden")
        + " retries=" + ("authorized" if operation == "activate" else "forbidden")
    )


def test_owner_bridge_accepts_only_matched_exact_old_and_monday_bindings() -> None:
    bridge = load_module(BRIDGE, "edeka_cutover_owner_bridge")
    expected = {(OLD_SHA, OLD_FP), (NEW_SHA, NEW_FP)}
    assert bridge.EXACT_REGISTRATION_BINDINGS == expected
    for sha, fp in expected:
        parsed = bridge.parse_comment(owner_command(sha, fp))
        assert (parsed.registration_sha, parsed.fingerprint) == (sha, fp)
        parsed = bridge.parse_comment(owner_command(sha, fp, operation="activate"))
        assert parsed.operation == "activate"

    for sha, fp in (
        (OLD_SHA, NEW_FP), (NEW_SHA, OLD_FP),
        ("0" * 40, OLD_FP), (NEW_SHA, "0" * 64),
    ):
        with pytest.raises(bridge.BridgeAuthorizationError, match="exact reviewed"):
            bridge.parse_comment(owner_command(sha, fp))

    with pytest.raises(bridge.BridgeAuthorizationError):
        bridge.parse_comment(owner_command(NEW_SHA, NEW_FP).replace(
            "refetch=forbidden", "refetch=authorized"
        ))


def test_new_identity_requires_monday_forward_controller_reachable_in_git() -> None:
    bridge = load_module(BRIDGE, "edeka_cutover_owner_files")
    seen = []

    def fake_get(url: str, _token: str):
        seen.append(url)
        return {"type": "file", "sha": "1" * 40}

    bridge._validate_required_control_files(
        bridge.EXPECTED_REPOSITORY, "2" * 40, "token", fake_get,
        registration_sha=NEW_SHA,
    )
    assert any("edeka_monday_forward_cutover.py" in item for item in seen)
    assert any("edeka_weekly_monitor_control_monday.py" in item for item in seen)

    seen.clear()
    bridge._validate_required_control_files(
        bridge.EXPECTED_REPOSITORY, "2" * 40, "token", fake_get,
        registration_sha=OLD_SHA,
    )
    assert not any("edeka_monday_forward_cutover.py" in item for item in seen)
    assert not any("edeka_weekly_monitor_control_monday.py" in item for item in seen)


def test_new_dispatcher_is_exactly_source_bindings_plus_fail_closed_activation() -> None:
    old = OLD.read_text(encoding="utf-8")
    monday = MONDAY.read_text(encoding="utf-8")
    changes = [
        (f'EXPECTED_REGISTRATION_SHA = "{OLD_SHA}"',
         f'EXPECTED_REGISTRATION_SHA = "{NEW_SHA}"'),
        (f'EXPECTED_REGISTRATION_FINGERPRINT = "{OLD_FP}"',
         f'EXPECTED_REGISTRATION_FINGERPRINT = "{NEW_FP}"'),
        ('"hermes-edeka-weekly-monitor.service": "d33710d7bf5b02c948d4e3e089b6fec435457d174b0ef6ca444368bfadc984de"',
         '"hermes-edeka-weekly-monitor.service": "d642a9e922a28dfeb982f9930b5091609fd1eebea7e7e27998a8486ab3f77824"'),
        ('"hermes-edeka-weekly-monitor.timer": "6bc3cddbd77a925546032ae0a22abc75631d5f9ef36d01d98731a1bcb54fc31d"',
         '"hermes-edeka-weekly-monitor.timer": "214a54a9c652dd38169987ba0672ec5853cc8f17f59734a318f7044ffa0d8178"'),
        ('"on_calendar": "Sun *-*-* 00:10:00 Europe/Berlin"',
         '"on_calendar": "Mon *-*-* 00:10:00 Europe/Berlin"'),
    ]
    for before, after in changes:
        assert old.count(before) == 1
        old = old.replace(before, after)

    before = '''    try:
        run(["/usr/bin/systemctl", "daemon-reload"])
        run(["/usr/bin/systemctl", "--no-reload", "enable", TIMER_UNIT])
        run(["/usr/bin/systemctl", "start", TIMER_UNIT])
        require(timer_enabled(), "timer did not become enabled")
        require(unit_active(TIMER_UNIT), "timer did not become active")
    except Exception:
        cleanup_ok = fail_safe_disable()
        if not cleanup_ok:
            raise ControlError("activation failed and fail-safe cleanup could not be verified")
        raise'''
    after = '''    # After an explicitly authorized mutation, never auto-retry or roll back.
    run(["/usr/bin/systemctl", "daemon-reload"])
    run(["/usr/bin/systemctl", "--no-reload", "enable", TIMER_UNIT])
    run(["/usr/bin/systemctl", "start", TIMER_UNIT])
    require(timer_enabled(), "timer did not become enabled")
    require(unit_active(TIMER_UNIT), "timer did not become active")'''
    assert old.count(before) == 1
    old = old.replace(before, after)
    assert monday == old


def test_forward_source_does_not_schedule_source_collection_or_retry_on_failure() -> None:
    source = FORWARD.read_text(encoding="utf-8")
    assert 'LIVE_TOKEN = "EXACT-ONE-SHOT-MONDAY-NO-CATCHUP"' in source
    assert "merge-base" in source
    assert '"--ff-only"' in source
    assert '"daemon-reload"' in source
    assert "os.replace(" in source
    assert "no_automatic_retry_rollback_or_cleanup" in source
    for forbidden in (
        '["/usr/bin/systemctl", "reset-failed"',
        '["/usr/bin/systemctl", "restart"',
        "shutil.rmtree(", "rm -rf", '"fetch"', '"prune"', '"--hard"',
        "os.unlink(", "os.remove(", "temp.unlink(",
    ):
        assert forbidden not in source
