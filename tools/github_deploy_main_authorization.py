from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any, Callable, Mapping
import urllib.parse
import urllib.request
import json

EXPECTED_REPOSITORY = "rozkalnsandris/hermes-deals"
EXPECTED_OWNER = "rozkalnsandris"
EXPECTED_OWNER_ID = 277435981
EXPECTED_ISSUE = 553
EXPECTED_WORKFLOW_REF = (
    "rozkalnsandris/hermes-deals/.github/workflows/deploy-main.yml@refs/heads/main"
)
BOT_ACTOR = "github-actions[bot]"
CONTROL_APP_ACTOR = "rozkalns-control[bot]"
CONTROL_APP_ACTOR_ID = 316106438
COMMAND_RE = re.compile(r"/hermes-deploy current-main sha=(?P<sha>[0-9a-f]{40})")
CONTROL_REQUEST_ID_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_-]{15,127}")


class DeployMainAuthorizationError(ValueError):
    pass


@dataclass(frozen=True)
class AuthorizedDeployMain:
    sha: str
    ci_run_id: int
    authorization_mode: str
    authorization_comment_id: int | None
    control_request_id: str | None


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "X-GitHub-Api-Version": "2022-11-28",
        "User-Agent": "hermes-deals-deploy-main-authorizer",
    }


def _default_get_json(url: str, token: str) -> Any:
    request = urllib.request.Request(url, headers=_headers(token))
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def _parse_positive_int(value: str, name: str) -> int:
    if not re.fullmatch(r"[1-9][0-9]*", value):
        raise DeployMainAuthorizationError(f"{name} must be a positive integer")
    return int(value)


def _validate_bot_comment(
    *, repository: str, target_sha: str, authorization_issue: str,
    authorization_comment_id: str, token: str, get_json: Callable[[str, str], Any],
) -> int:
    issue_number = _parse_positive_int(authorization_issue, "authorization issue")
    if issue_number != EXPECTED_ISSUE:
        raise DeployMainAuthorizationError("authorization issue is not the deploy control issue")
    comment_id = _parse_positive_int(authorization_comment_id, "authorization comment ID")
    comment = get_json(
        f"https://api.github.com/repos/{repository}/issues/comments/{comment_id}", token
    )
    if not isinstance(comment, Mapping) or comment.get("id") != comment_id:
        raise DeployMainAuthorizationError("authorization comment identity mismatch")
    expected_issue_url = f"https://api.github.com/repos/{repository}/issues/{EXPECTED_ISSUE}"
    if comment.get("issue_url") != expected_issue_url:
        raise DeployMainAuthorizationError("authorization comment issue mismatch")
    user = comment.get("user")
    if not isinstance(user, Mapping):
        raise DeployMainAuthorizationError("authorization comment owner is missing")
    if user.get("login") != EXPECTED_OWNER or user.get("id") != EXPECTED_OWNER_ID:
        raise DeployMainAuthorizationError("authorization comment owner mismatch")
    body = comment.get("body")
    if not isinstance(body, str):
        raise DeployMainAuthorizationError("authorization comment body is invalid")
    match = COMMAND_RE.fullmatch(body.strip())
    if match is None or match.group("sha") != target_sha:
        raise DeployMainAuthorizationError("authorization comment command mismatch")
    return comment_id


def authorize_deploy_main(
    *, repository: str, repository_owner: str, event_name: str, event_ref: str,
    workflow_ref: str, actor: str, actor_id: str, triggering_actor: str,
    run_attempt: str, target_sha: str, confirmation: str,
    authorization_issue: str, authorization_comment_id: str,
    control_action: str, expected_main_sha: str, control_request_id: str,
    token: str, get_json: Callable[[str, str], Any] = _default_get_json,
) -> AuthorizedDeployMain:
    if repository != EXPECTED_REPOSITORY or repository_owner != EXPECTED_OWNER:
        raise DeployMainAuthorizationError("unexpected repository owner")
    if event_name != "workflow_dispatch" or event_ref != "refs/heads/main":
        raise DeployMainAuthorizationError("production deploy requires main workflow_dispatch")
    if workflow_ref != EXPECTED_WORKFLOW_REF:
        raise DeployMainAuthorizationError("production deploy workflow ref is not exact main")

    comment_id: int | None = None
    bound_control_request_id: str | None = None
    control_fields = (control_action, expected_main_sha, control_request_id)

    if actor == EXPECTED_OWNER and triggering_actor == EXPECTED_OWNER:
        if any(control_fields):
            raise DeployMainAuthorizationError("manual owner dispatch must not include Control inputs")
        if authorization_issue or authorization_comment_id:
            raise DeployMainAuthorizationError("manual owner dispatch must not include comment authorization")
        requested_sha = target_sha
        mode = "manual_owner"
    elif actor == BOT_ACTOR and triggering_actor == BOT_ACTOR:
        if any(control_fields):
            raise DeployMainAuthorizationError("owner-comment dispatch must not include Control inputs")
        requested_sha = target_sha
        comment_id = _validate_bot_comment(
            repository=repository, target_sha=requested_sha,
            authorization_issue=authorization_issue,
            authorization_comment_id=authorization_comment_id, token=token, get_json=get_json,
        )
        mode = "owner_comment_via_bot"
    elif actor == CONTROL_APP_ACTOR and triggering_actor == CONTROL_APP_ACTOR:
        if actor_id != str(CONTROL_APP_ACTOR_ID):
            raise DeployMainAuthorizationError("Control App actor ID mismatch")
        if run_attempt != "1":
            raise DeployMainAuthorizationError("Control App dispatch reruns are not authorized")
        if target_sha or confirmation or authorization_issue or authorization_comment_id:
            raise DeployMainAuthorizationError("Control App dispatch mixed legacy deploy inputs")
        if control_action != "LIVE":
            raise DeployMainAuthorizationError("Control App action is not LIVE")
        if not re.fullmatch(r"[0-9a-f]{40}", expected_main_sha):
            raise DeployMainAuthorizationError("Control expected main SHA is invalid")
        if CONTROL_REQUEST_ID_RE.fullmatch(control_request_id) is None:
            raise DeployMainAuthorizationError("Control request ID is invalid")
        requested_sha = expected_main_sha
        bound_control_request_id = control_request_id
        mode = "control_app"
    else:
        raise DeployMainAuthorizationError("workflow actor is not an allowed deploy authorization path")

    if not re.fullmatch(r"[0-9a-f]{40}", requested_sha):
        raise DeployMainAuthorizationError("target SHA must be exact lowercase 40-character SHA")
    if mode != "control_app" and confirmation != f"DEPLOY {requested_sha}":
        raise DeployMainAuthorizationError("typed production confirmation does not match target SHA")

    main = get_json(f"https://api.github.com/repos/{repository}/branches/main", token)
    if not isinstance(main, Mapping):
        raise DeployMainAuthorizationError("current main metadata is invalid")
    current_main = str((main.get("commit") or {}).get("sha") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", current_main):
        raise DeployMainAuthorizationError("current main SHA is invalid")
    if mode in {"owner_comment_via_bot", "control_app"}:
        if requested_sha != current_main:
            raise DeployMainAuthorizationError("externally authorized target is not exact current main")
    elif requested_sha != current_main:
        comparison = get_json(
            f"https://api.github.com/repos/{repository}/compare/{requested_sha}...{current_main}", token
        )
        merge_base = str((comparison.get("merge_base_commit") or {}).get("sha") or "")
        if comparison.get("status") != "ahead" or merge_base != requested_sha:
            raise DeployMainAuthorizationError("target SHA is not an ancestor of current main")

    encoded = urllib.parse.quote(requested_sha, safe="")
    runs = get_json(
        f"https://api.github.com/repos/{repository}/actions/workflows/ci.yml/runs"
        f"?branch=main&head_sha={encoded}&status=completed&per_page=100", token
    )
    if not isinstance(runs, Mapping):
        raise DeployMainAuthorizationError("CI workflow metadata is invalid")
    successful = [
        row for row in (runs.get("workflow_runs") or [])
        if isinstance(row, Mapping)
        and row.get("event") == "push" and row.get("head_branch") == "main"
        and row.get("head_sha") == requested_sha and row.get("status") == "completed"
        and row.get("conclusion") == "success" and isinstance(row.get("id"), int)
    ]
    if not successful:
        raise DeployMainAuthorizationError("target SHA has no successful main push CI run")
    return AuthorizedDeployMain(
        sha=requested_sha, ci_run_id=max(int(row["id"]) for row in successful),
        authorization_mode=mode, authorization_comment_id=comment_id,
        control_request_id=bound_control_request_id,
    )
