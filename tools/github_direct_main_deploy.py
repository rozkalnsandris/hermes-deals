from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping
import urllib.error
import urllib.parse
import urllib.request


EXPECTED_REPOSITORY = "rozkalnsandris/hermes-deals"
EXPECTED_OWNER_LOGIN = "rozkalnsandris"
EXPECTED_OWNER_ID = 277435981
EXPECTED_ISSUE_NUMBER = 553
EXPECTED_WORKFLOW_REF = (
    "rozkalnsandris/hermes-deals/.github/workflows/hermes-direct-main-deploy.yml@refs/heads/main"
)
DEPLOY_WORKFLOW = "deploy-main.yml"
COMMAND_RE = re.compile(
    r"/hermes-deploy current-main sha=(?P<sha>[0-9a-f]{40})"
)


class DirectDeployAuthorizationError(ValueError):
    pass


@dataclass(frozen=True)
class AuthorizedDeploy:
    sha: str
    issue_number: int
    comment_id: int
    ci_run_id: int


def parse_comment(body: str) -> str:
    if not isinstance(body, str):
        raise DirectDeployAuthorizationError("comment body must be text")
    match = COMMAND_RE.fullmatch(body.strip())
    if match is None:
        raise DirectDeployAuthorizationError(
            "comment does not match the allowlisted current-main deploy command"
        )
    return match.group("sha")


def _headers(token: str) -> dict[str, str]:
    return {
        "Accept": "application/vnd.github+json",
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "User-Agent": "hermes-deals-direct-main-deploy",
        "X-GitHub-Api-Version": "2026-03-10",
    }


def _default_get_json(url: str, token: str) -> Any:
    request = urllib.request.Request(url, headers=_headers(token))
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def authorize_event(
    event: Mapping[str, Any],
    *,
    repository: str,
    workflow_ref: str,
    token: str,
    get_json: Callable[[str, str], Any] = _default_get_json,
) -> AuthorizedDeploy:
    if repository != EXPECTED_REPOSITORY:
        raise DirectDeployAuthorizationError("unexpected repository")
    if workflow_ref != EXPECTED_WORKFLOW_REF:
        raise DirectDeployAuthorizationError("deploy command workflow is not exact main")

    sender = event.get("sender")
    if not isinstance(sender, Mapping):
        raise DirectDeployAuthorizationError("event sender is missing")
    if sender.get("login") != EXPECTED_OWNER_LOGIN:
        raise DirectDeployAuthorizationError("comment sender login is not allowlisted")
    if sender.get("id") != EXPECTED_OWNER_ID:
        raise DirectDeployAuthorizationError("comment sender numeric ID is not allowlisted")

    issue = event.get("issue")
    if not isinstance(issue, Mapping):
        raise DirectDeployAuthorizationError("issue payload is missing")
    if issue.get("pull_request") is not None:
        raise DirectDeployAuthorizationError("deploy commands are accepted only on issues")
    issue_number = issue.get("number")
    if issue_number != EXPECTED_ISSUE_NUMBER:
        raise DirectDeployAuthorizationError("deploy command was not posted on the control issue")

    comment = event.get("comment")
    if not isinstance(comment, Mapping):
        raise DirectDeployAuthorizationError("comment payload is missing")
    target_sha = parse_comment(str(comment.get("body") or ""))
    comment_id = comment.get("id")
    if isinstance(comment_id, bool) or not isinstance(comment_id, int) or comment_id <= 0:
        raise DirectDeployAuthorizationError("comment ID is invalid")

    branch = get_json(
        f"https://api.github.com/repos/{repository}/branches/main",
        token,
    )
    if not isinstance(branch, Mapping):
        raise DirectDeployAuthorizationError("main branch metadata is invalid")
    current_main = str((branch.get("commit") or {}).get("sha") or "")
    if not re.fullmatch(r"[0-9a-f]{40}", current_main):
        raise DirectDeployAuthorizationError("current main SHA is invalid")
    if target_sha != current_main:
        raise DirectDeployAuthorizationError("command SHA is not exact current main")

    encoded_sha = urllib.parse.quote(target_sha, safe="")
    runs_payload = get_json(
        f"https://api.github.com/repos/{repository}/actions/workflows/ci.yml/runs"
        f"?branch=main&head_sha={encoded_sha}&status=completed&per_page=100",
        token,
    )
    if not isinstance(runs_payload, Mapping):
        raise DirectDeployAuthorizationError("CI workflow metadata is invalid")
    successful = [
        row
        for row in (runs_payload.get("workflow_runs") or [])
        if isinstance(row, Mapping)
        and row.get("event") == "push"
        and row.get("head_branch") == "main"
        and row.get("head_sha") == target_sha
        and row.get("status") == "completed"
        and row.get("conclusion") == "success"
        and isinstance(row.get("id"), int)
    ]
    if not successful:
        raise DirectDeployAuthorizationError(
            "current main has no successful completed push CI run"
        )
    ci_run_id = max(int(row["id"]) for row in successful)
    return AuthorizedDeploy(
        sha=target_sha,
        issue_number=EXPECTED_ISSUE_NUMBER,
        comment_id=comment_id,
        ci_run_id=ci_run_id,
    )


def dispatch_deploy(
    authorized: AuthorizedDeploy,
    *,
    repository: str,
    token: str,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> dict[str, Any]:
    url = (
        f"https://api.github.com/repos/{repository}/actions/workflows/"
        f"{DEPLOY_WORKFLOW}/dispatches"
    )
    body = json.dumps(
        {
            "ref": "main",
            "inputs": {
                "target_sha": authorized.sha,
                "confirmation": f"DEPLOY {authorized.sha}",
            },
        },
        separators=(",", ":"),
    ).encode("utf-8")
    request = urllib.request.Request(
        url,
        data=body,
        method="POST",
        headers=_headers(token),
    )
    try:
        with opener(request, timeout=20) as response:
            status = int(response.status)
            raw = response.read()
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise DirectDeployAuthorizationError(
            f"deploy workflow dispatch failed with HTTP {exc.code}: {detail}"
        ) from exc
    if status not in {200, 204}:
        raise DirectDeployAuthorizationError(
            f"unexpected deploy workflow dispatch status: {status}"
        )
    payload: dict[str, Any] = {}
    if raw:
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise DirectDeployAuthorizationError(
                "deploy workflow dispatch returned invalid JSON"
            ) from exc
        if isinstance(parsed, dict):
            payload = parsed
    return {
        "status": status,
        "workflow_run_id": payload.get("workflow_run_id"),
        "html_url": payload.get("html_url"),
    }


def report_dispatch(
    authorized: AuthorizedDeploy,
    dispatch_result: Mapping[str, Any],
    *,
    repository: str,
    token: str,
    opener: Callable[..., Any] = urllib.request.urlopen,
) -> None:
    run_id = dispatch_result.get("workflow_run_id")
    run_url = dispatch_result.get("html_url")
    lines = [
        "## Direct current-main deploy dispatched",
        "",
        f"- target SHA: `{authorized.sha}`",
        f"- successful main CI: `{authorized.ci_run_id}`",
        f"- command comment: `{authorized.comment_id}`",
        f"- downstream workflow: `{DEPLOY_WORKFLOW}`",
        "- database writes authorized: **false**",
        "- the downstream deploy workflow independently re-authorizes exact SHA/CI before RPi5 execution.",
    ]
    if isinstance(run_id, int):
        lines.append(f"- workflow run ID: `{run_id}`")
    if isinstance(run_url, str) and run_url.startswith("https://github.com/"):
        lines.append(f"- workflow: {run_url}")
    body = json.dumps({"body": "\n".join(lines)}).encode("utf-8")
    request = urllib.request.Request(
        f"https://api.github.com/repos/{repository}/issues/{authorized.issue_number}/comments",
        data=body,
        method="POST",
        headers=_headers(token),
    )
    with opener(request, timeout=20) as response:
        if int(response.status) != 201:
            raise DirectDeployAuthorizationError(
                f"unexpected dispatch report status: {response.status}"
            )


def main() -> int:
    event = json.loads(Path(os.environ["GITHUB_EVENT_PATH"]).read_text(encoding="utf-8"))
    repository = os.environ["GITHUB_REPOSITORY"]
    workflow_ref = os.environ["GITHUB_WORKFLOW_REF"]
    token = os.environ["GH_TOKEN"]
    authorized = authorize_event(
        event,
        repository=repository,
        workflow_ref=workflow_ref,
        token=token,
    )
    result = dispatch_deploy(
        authorized,
        repository=repository,
        token=token,
    )
    report_dispatch(
        authorized,
        result,
        repository=repository,
        token=token,
    )
    print(
        json.dumps(
            {
                "result": "DISPATCHED",
                "sha": authorized.sha,
                "ci_run_id": authorized.ci_run_id,
                "workflow_run_id": result.get("workflow_run_id"),
                "database_writes_authorized": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
