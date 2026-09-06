from __future__ import annotations

from tools.github_deploy_main_authorization import (
    BOT_ACTOR, DeployMainAuthorizationError, EXPECTED_WORKFLOW_REF, authorize_deploy_main,
)

SHA = "a" * 40


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
        "triggering_actor": "rozkalnsandris",
        "target_sha": SHA,
        "confirmation": f"DEPLOY {SHA}",
        "authorization_issue": "",
        "authorization_comment_id": "",
        "token": "token",
        "get_json": _get_json,
    }
    values.update(overrides)
    return authorize_deploy_main(**values)


def test_manual_owner_dispatch_remains_authorized_without_comment_binding() -> None:
    result = _authorize()
    assert result.sha == SHA
    assert result.ci_run_id == 99
    assert result.authorization_mode == "manual_owner"
    assert result.authorization_comment_id is None


def test_bot_dispatch_requires_and_verifies_exact_owner_comment() -> None:
    result = _authorize(
        actor=BOT_ACTOR, triggering_actor=BOT_ACTOR,
        authorization_issue="553", authorization_comment_id="12345",
    )
    assert result.authorization_mode == "owner_comment_via_bot"
    assert result.authorization_comment_id == 12345


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
    for actor, triggering in ((BOT_ACTOR, "rozkalnsandris"), ("rozkalnsandris", BOT_ACTOR), ("someone", "someone")):
        try:
            _authorize(actor=actor, triggering_actor=triggering)
        except DeployMainAuthorizationError:
            pass
        else:
            raise AssertionError((actor, triggering))


def test_manual_owner_dispatch_rejects_spoofed_comment_inputs() -> None:
    try:
        _authorize(authorization_issue="553", authorization_comment_id="12345")
    except DeployMainAuthorizationError as exc:
        assert "must not include comment authorization" in str(exc)
    else:
        raise AssertionError("manual path accepted comment authorization inputs")
