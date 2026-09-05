from __future__ import annotations

import importlib.util
from pathlib import Path
from types import ModuleType
from typing import Any

import pytest


ROOT = Path(__file__).resolve().parents[2]
AUTHOR_PATH = ROOT / "tools" / "github_edeka_weekly_monitor_control.py"
CONTROL_PATH = ROOT / "tools" / "runner" / "edeka_weekly_monitor_control.py"


def load_module(path: Path, name: str) -> ModuleType:
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def owner_event(body: str) -> dict[str, Any]:
    return {
        "issue": {"number": 26},
        "sender": {"login": "rozkalnsandris", "id": 277435981},
        "comment": {
            "id": 123,
            "author_association": "OWNER",
            "body": body,
        },
    }


def command(operation: str, *, refetch: str, retries: str) -> str:
    return (
        f"/hermes-edeka monitor {operation} "
        f"control={'1' * 40} "
        "registration=85c3aca4ac62cbffa281365562af52c5e52d8d24 "
        "fingerprint=970fac96fd487fe2a027f6dd1055e6563ccec331e53e889511c1e35c5038f947 "
        f"refetch={refetch} retries={retries}"
    )


def test_authorizer_requires_explicit_activate_authorities() -> None:
    module = load_module(AUTHOR_PATH, "edeka_monitor_authorizer")
    parsed = module.parse_comment(command("activate", refetch="authorized", retries="authorized"))
    assert parsed.operation == "activate"
    with pytest.raises(module.BridgeAuthorizationError):
        module.parse_comment(command("activate", refetch="forbidden", retries="authorized"))
    with pytest.raises(module.BridgeAuthorizationError):
        module.parse_comment(command("activate", refetch="authorized", retries="forbidden"))


@pytest.mark.parametrize("operation", ["disable", "rollback"])
def test_authorizer_forbids_refetch_and_retries_for_escape_hatches(operation: str) -> None:
    module = load_module(AUTHOR_PATH, f"edeka_monitor_authorizer_{operation}")
    parsed = module.parse_comment(command(operation, refetch="forbidden", retries="forbidden"))
    assert parsed.operation == operation
    with pytest.raises(module.BridgeAuthorizationError):
        module.parse_comment(command(operation, refetch="authorized", retries="forbidden"))


def test_disable_does_not_depend_on_green_main_ci() -> None:
    module = load_module(AUTHOR_PATH, "edeka_monitor_authorizer_disable")
    calls: list[str] = []

    def fake_get(url: str, _token: str) -> Any:
        calls.append(url)
        if url.endswith("/branches/main"):
            return {"commit": {"sha": "2" * 40}}
        if "/compare/" in url:
            return {"status": "ahead"}
        if "/contents/" in url:
            return {"type": "file", "sha": "3" * 40}
        raise AssertionError(f"unexpected URL: {url}")

    result = module.authorize_event(
        owner_event(command("disable", refetch="forbidden", retries="forbidden")),
        repository="rozkalnsandris/hermes-deals",
        token="x",
        get_json=fake_get,
    )
    assert result["ci_run_id"] == "not-required"
    assert not any("/actions/runs?" in url for url in calls)


def test_activate_requires_green_current_main_ci() -> None:
    module = load_module(AUTHOR_PATH, "edeka_monitor_authorizer_activate")

    def fake_get(url: str, _token: str) -> Any:
        if url.endswith("/branches/main"):
            return {"commit": {"sha": "2" * 40}}
        if "/compare/" in url:
            return {"status": "ahead"}
        if "/contents/" in url:
            return {"type": "file", "sha": "3" * 40}
        if "/actions/runs?" in url:
            return {
                "workflow_runs": [
                    {
                        "id": 456,
                        "name": "Hermes Deals CI checks",
                        "path": ".github/workflows/ci.yml",
                        "head_sha": "2" * 40,
                        "event": "push",
                        "status": "completed",
                        "conclusion": "success",
                    }
                ]
            }
        raise AssertionError(f"unexpected URL: {url}")

    result = module.authorize_event(
        owner_event(command("activate", refetch="authorized", retries="authorized")),
        repository="rozkalnsandris/hermes-deals",
        token="x",
        get_json=fake_get,
    )
    assert result["ci_run_id"] == "456"
    assert result["current_main"] == "2" * 40


def test_control_activate_sequence_and_fail_safe(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module(CONTROL_PATH, "edeka_monitor_control_activate")
    calls: list[list[str]] = []

    monkeypatch.setattr(module, "validate_runtime_checkout", lambda _config: None)
    monkeypatch.setattr(module, "preflight_units", lambda _config: None)

    states = {"enabled": False, "timer_active": False, "service_active": False}
    monkeypatch.setattr(module, "timer_enabled", lambda: states["enabled"])
    monkeypatch.setattr(
        module,
        "unit_active",
        lambda unit: states["timer_active"] if unit == module.TIMER_UNIT else states["service_active"],
    )
    monkeypatch.setattr(module, "unit_failed", lambda _unit: False)

    def fake_run(argv: list[str], *, check: bool = True, timeout: int = 120):
        calls.append(argv)
        if argv[:3] == ["/usr/bin/systemctl", "--no-reload", "enable"]:
            states["enabled"] = True
        if argv[:2] == ["/usr/bin/systemctl", "start"] and argv[-1] == module.TIMER_UNIT:
            states["timer_active"] = True

        class Result:
            returncode = 0
            stdout = ""
            stderr = ""

        return Result()

    monkeypatch.setattr(module, "run", fake_run)
    result = module.activate({})
    assert result["timer_enabled"] is True
    assert result["source_refetch_authorized"] is True
    assert result["bounded_retry_authorized"] is True
    assert ["/usr/bin/systemctl", "daemon-reload"] in calls
    assert ["/usr/bin/systemctl", "--no-reload", "enable", module.TIMER_UNIT] in calls
    assert ["/usr/bin/systemctl", "start", module.TIMER_UNIT] in calls


def test_control_treats_runtime_enabled_state_as_enabled(monkeypatch: pytest.MonkeyPatch) -> None:
    module = load_module(CONTROL_PATH, "edeka_monitor_control_enabled_state")

    class Result:
        returncode = 0
        stdout = "enabled-runtime\n"
        stderr = ""

    monkeypatch.setattr(module, "run", lambda _argv, check=False: Result())
    assert module.timer_enabled() is True


def test_control_disable_and_rollback_are_refetch_free_in_source() -> None:
    source = CONTROL_PATH.read_text(encoding="utf-8")
    assert 'source-refetch=authorized' in source
    assert 'disable must forbid source refetch' in source
    assert 'rollback must forbid source refetch' in source
    assert 'production_database_write_authorized": False' in source


def test_control_runtime_requires_pinned_registered_checkout() -> None:
    source = CONTROL_PATH.read_text(encoding="utf-8")
    assert 'git_text("rev-parse", "HEAD") == EXPECTED_REGISTRATION_SHA' in source
    assert "dedicated EDEKA audit HEAD drifted from registration SHA" in source
    assert "monitor service unexpectedly failed before activation" in source
    assert "timer unexpectedly failed before activation" in source
