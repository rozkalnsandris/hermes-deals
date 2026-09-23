from __future__ import annotations

from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.github_deploy_main_authorization import (
    BOT_ACTOR,
    CONTROL_APP_ACTOR,
    CONTROL_APP_ACTOR_ID,
    DeployMainAuthorizationError,
    EXPECTED_WORKFLOW_REF,
    authorize_deploy_main,
)

SHA = "a" * 40
CONTROL_REQUEST_ID = "control_live_20260923_abcd1234"


def _ci():
    return {"workflow_runs": [{
        "id": 99, "event": "push", "head_branch": "main", "head_sha": SHA,
        "status": "completed", "conclusion": "success",
    }]}


def _get_json(url: str, token: str):
    assert token == "token"
    if url.endswith("/issues/comments/12345"):
        return {
            "id": 12345,
            "issue_url": "https://api.github.com/repos/rozkalnsandris/hermes-deals/issues/553",
            "user": {"login": "rozkalnsandris", "id": 277435981},
            "body": f"/hermes-deploy current-main sha={SHA}",
        }
    if url.endswith("/branches/main"):
        return {"commit": {"sha": SHA}}
    if "/actions/workflows/ci.yml/runs?" in url:
        return _ci()
    raise AssertionError(url)


def _authorize(**overrides):
    values = {
        "repository": "rozkalnsandris/hermes-deals",
        "repository_owner": "rozkalnsandris",
        "event_name": "workflow_dispatch",
        "event_ref": "refs/heads/main",
        "workflow_ref": EXPECTED_WORKFLOW_REF,
        "actor": "rozkalnsandris",
        "actor_id": "277435981",
        "triggering_actor": "rozkalnsandris",
        "run_attempt": "1",
        "target_sha": SHA,
        "confirmation": f"DEPLOY {SHA}",
        "authorization_issue": "",
        "authorization_comment_id": "",
        "control_action": "",
        "expected_main_sha": "",
        "control_request_id": "",
        "token": "token",
        "get_json": _get_json,
    }
    values.update(overrides)
    return authorize_deploy_main(**values)


def _control_authorize(**overrides):
    values = {
        "actor": CONTROL_APP_ACTOR,
        "actor_id": str(CONTROL_APP_ACTOR_ID),
        "triggering_actor": CONTROL_APP_ACTOR,
        "target_sha": "",
        "confirmation": "",
        "control_action": "LIVE",
        "expected_main_sha": SHA,
        "control_request_id": CONTROL_REQUEST_ID,
    }
    values.update(overrides)
    return _authorize(**values)


def test_manual_owner_dispatch_remains_authorized_without_comment_binding() -> None:
    result = _authorize()
    assert result.sha == SHA
    assert result.ci_run_id == 99
    assert result.authorization_mode == "manual_owner"
    assert result.authorization_comment_id is None
    assert result.control_request_id is None


def test_bot_dispatch_requires_and_verifies_exact_owner_comment() -> None:
    result = _authorize(
        actor=BOT_ACTOR, triggering_actor=BOT_ACTOR,
        authorization_issue="553", authorization_comment_id="12345",
    )
    assert result.authorization_mode == "owner_comment_via_bot"
    assert result.authorization_comment_id == 12345
    assert result.control_request_id is None


def test_control_app_dispatch_binds_exact_principal_live_sha_and_request() -> None:
    result = _control_authorize()
    assert result.sha == SHA
    assert result.ci_run_id == 99
    assert result.authorization_mode == "control_app"
    assert result.authorization_comment_id is None
    assert result.control_request_id == CONTROL_REQUEST_ID


def test_control_app_dispatch_rejects_wrong_principal_rerun_or_action() -> None:
    variants = (
        {"actor_id": "1"},
        {"triggering_actor": "rozkalnsandris"},
        {"run_attempt": "2"},
        {"control_action": "CONTINUE"},
        {"control_action": ""},
    )
    for overrides in variants:
        try:
            _control_authorize(**overrides)
        except DeployMainAuthorizationError:
            pass
        else:
            raise AssertionError(overrides)


def test_control_app_dispatch_rejects_invalid_sha_request_or_legacy_mix() -> None:
    variants = (
        {"expected_main_sha": "b" * 39},
        {"control_request_id": "short"},
        {"control_request_id": "control request with spaces"},
        {"target_sha": SHA},
        {"confirmation": f"DEPLOY {SHA}"},
        {"authorization_issue": "553"},
        {"authorization_comment_id": "12345"},
    )
    for overrides in variants:
        try:
            _control_authorize(**overrides)
        except DeployMainAuthorizationError:
            pass
        else:
            raise AssertionError(overrides)


def test_control_app_dispatch_rejects_stale_expected_main() -> None:
    def stale_json(url: str, token: str):
        if url.endswith("/branches/main"):
            return {"commit": {"sha": "b" * 40}}
        raise AssertionError(url)

    try:
        _control_authorize(get_json=stale_json)
    except DeployMainAuthorizationError as exc:
        assert "exact current main" in str(exc)
    else:
        raise AssertionError("stale Control App SHA accepted")


def test_bot_dispatch_rejects_missing_wrong_or_stale_comment_binding() -> None:
    for issue, comment_id in (("", ""), ("554", "12345"), ("553", "0")):
        try:
            _authorize(
                actor=BOT_ACTOR, triggering_actor=BOT_ACTOR,
                authorization_issue=issue, authorization_comment_id=comment_id,
            )
        except DeployMainAuthorizationError:
            pass
        else:
            raise AssertionError((issue, comment_id))

    def stale_json(url: str, token: str):
        if url.endswith("/issues/comments/12345"):
            return {
                "id": 12345,
                "issue_url": "https://api.github.com/repos/rozkalnsandris/hermes-deals/issues/553",
                "user": {"login": "rozkalnsandris", "id": 277435981},
                "body": f"/hermes-deploy current-main sha={SHA}",
            }
        if url.endswith("/branches/main"):
            return {"commit": {"sha": "b" * 40}}
        raise AssertionError(url)

    try:
        _authorize(
            actor=BOT_ACTOR, triggering_actor=BOT_ACTOR,
            authorization_issue="553", authorization_comment_id="12345", get_json=stale_json,
        )
    except DeployMainAuthorizationError as exc:
        assert "exact current main" in str(exc)
    else:
        raise AssertionError("stale bot-authorized SHA accepted")


def test_bot_dispatch_rejects_wrong_comment_owner_issue_body_or_id() -> None:
    variants = [
        {"id": 999, "issue_url": "https://api.github.com/repos/rozkalnsandris/hermes-deals/issues/553", "user": {"login": "rozkalnsandris", "id": 277435981}, "body": f"/hermes-deploy current-main sha={SHA}"},
        {"id": 12345, "issue_url": "https://api.github.com/repos/rozkalnsandris/hermes-deals/issues/552", "user": {"login": "rozkalnsandris", "id": 277435981}, "body": f"/hermes-deploy current-main sha={SHA}"},
        {"id": 12345, "issue_url": "https://api.github.com/repos/rozkalnsandris/hermes-deals/issues/553", "user": {"login": "someone", "id": 277435981}, "body": f"/hermes-deploy current-main sha={SHA}"},
        {"id": 12345, "issue_url": "https://api.github.com/repos/rozkalnsandris/hermes-deals/issues/553", "user": {"login": "rozkalnsandris", "id": 1}, "body": f"/hermes-deploy current-main sha={SHA}"},
        {"id": 12345, "issue_url": "https://api.github.com/repos/rozkalnsandris/hermes-deals/issues/553", "user": {"login": "rozkalnsandris", "id": 277435981}, "body": f"/hermes-deploy current-main sha={SHA} extra"},
    ]
    for comment in variants:
        def get_json(url: str, token: str, comment=comment):
            if url.endswith("/issues/comments/12345"):
                return comment
            raise AssertionError(url)
        try:
            _authorize(
                actor=BOT_ACTOR, triggering_actor=BOT_ACTOR,
                authorization_issue="553", authorization_comment_id="12345", get_json=get_json,
            )
        except DeployMainAuthorizationError:
            pass
        else:
            raise AssertionError(comment)


def test_mixed_or_untrusted_actors_fail_closed() -> None:
    for actor, triggering in (
        (BOT_ACTOR, "rozkalnsandris"),
        ("rozkalnsandris", BOT_ACTOR),
        (CONTROL_APP_ACTOR, "rozkalnsandris"),
        ("someone", "someone"),
    ):
        try:
            _authorize(actor=actor, triggering_actor=triggering)
        except DeployMainAuthorizationError:
            pass
        else:
            raise AssertionError((actor, triggering))


def test_manual_owner_dispatch_rejects_spoofed_comment_or_control_inputs() -> None:
    for overrides in (
        {"authorization_issue": "553", "authorization_comment_id": "12345"},
        {"control_action": "LIVE"},
        {"expected_main_sha": SHA},
        {"control_request_id": CONTROL_REQUEST_ID},
    ):
        try:
            _authorize(**overrides)
        except DeployMainAuthorizationError:
            pass
        else:
            raise AssertionError(overrides)
