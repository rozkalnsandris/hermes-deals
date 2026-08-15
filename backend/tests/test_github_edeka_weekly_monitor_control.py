from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "github_edeka_weekly_monitor_control.py"
REGISTRATION = "a" * 64
REGISTERED_SHA = "b" * 40
BRIDGE_SHA = "c" * 40


def load_module():
    spec = importlib.util.spec_from_file_location("github_edeka_weekly_monitor_control", SCRIPT)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["github_edeka_weekly_monitor_control"] = module
    spec.loader.exec_module(module)
    return module


def event(body: str) -> dict:
    return {
        "sender": {"login": "rozkalnsandris", "id": 277435981},
        "issue": {"number": 26, "pull_request": None},
        "comment": {"id": 123456789, "author_association": "OWNER", "body": body},
    }


def fake_get(url: str, _token: str):
    if url.endswith("/pulls/673"):
        return {
            "merged": True,
            "merged_at": "2026-08-15T19:00:00Z",
            "merge_commit_sha": BRIDGE_SHA,
            "base": {"ref": "main", "repo": {"full_name": "rozkalnsandris/hermes-deals"}},
        }
    if url.endswith(f"/compare/{BRIDGE_SHA}...main"):
        return {"status": "ahead"}
    if url.endswith("/branches/main"):
        return {"commit": {"sha": REGISTERED_SHA}}
    raise AssertionError(url)


def test_activate_requires_explicit_refetch_and_retry_authority_and_exact_main() -> None:
    module = load_module()
    body = (
        f"/hermes-edeka monitor activate pr=673 sha={REGISTERED_SHA} "
        f"registration={REGISTRATION} refetch=authorized retries=authorized"
    )
    values = module.authorize_event(event(body), repository="rozkalnsandris/hermes-deals", token="token", get_json=fake_get)
    assert values["operation"] == "activate"
    assert values["registered_sha"] == REGISTERED_SHA
    assert values["registration_fingerprint"] == REGISTRATION
    assert values["source_refetch_authorized"] == "true"
    assert values["bounded_retry_authorized"] == "true"


@pytest.mark.parametrize("operation", ["disable", "rollback"])
def test_safety_operations_do_not_require_current_main_to_equal_registered_sha(operation: str) -> None:
    module = load_module()
    body = f"/hermes-edeka monitor {operation} pr=673 sha={REGISTERED_SHA} registration={REGISTRATION}"
    def no_branch_lookup(url: str, token: str):
        assert not url.endswith("/branches/main")
        return fake_get(url, token)
    values = module.authorize_event(event(body), repository="rozkalnsandris/hermes-deals", token="token", get_json=no_branch_lookup)
    assert values["operation"] == operation
    assert values["source_refetch_authorized"] == "false"
    assert values["bounded_retry_authorized"] == "false"


def test_activate_fails_when_registered_sha_is_not_current_main() -> None:
    module = load_module()
    body = (
        f"/hermes-edeka monitor activate pr=673 sha={REGISTERED_SHA} "
        f"registration={REGISTRATION} refetch=authorized retries=authorized"
    )
    def stale_main(url: str, token: str):
        if url.endswith("/branches/main"):
            return {"commit": {"sha": "d" * 40}}
        return fake_get(url, token)
    with pytest.raises(module.BridgeAuthorizationError, match="current main"):
        module.authorize_event(event(body), repository="rozkalnsandris/hermes-deals", token="token", get_json=stale_main)


@pytest.mark.parametrize(
    "body",
    [
        f"/hermes-edeka monitor activate pr=673 sha={REGISTERED_SHA} registration={REGISTRATION}",
        f"/hermes-edeka monitor activate pr=673 sha={REGISTERED_SHA} registration={REGISTRATION} refetch=authorized retries=no",
        f"/hermes-edeka monitor disable pr=672 sha={REGISTERED_SHA} registration={REGISTRATION}",
        f"/hermes-edeka monitor Disable pr=673 sha={REGISTERED_SHA} registration={REGISTRATION}",
        f"/hermes-edeka monitor rollback pr=673 sha={'B' * 40} registration={REGISTRATION}",
        f"/hermes-edeka monitor rollback pr=673 sha={REGISTERED_SHA} registration={'A' * 64}",
        f"/hermes-edeka monitor disable pr=673 sha={REGISTERED_SHA} registration={REGISTRATION} extra",
        "/hermes-edeka monitor activate pr=673 sha=$(id) registration=" + REGISTRATION + " refetch=authorized retries=authorized",
    ],
)
def test_command_parser_fails_closed(body: str) -> None:
    module = load_module()
    with pytest.raises(module.BridgeAuthorizationError):
        module.parse_comment(body)
