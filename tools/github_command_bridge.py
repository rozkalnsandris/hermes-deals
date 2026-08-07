from __future__ import annotations

from dataclasses import dataclass
from datetime import date
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping
import urllib.request


EXPECTED_REPOSITORY = "rozkalnsandris/hermes-deals"
EXPECTED_OWNER_LOGIN = "rozkalnsandris"
EXPECTED_OWNER_ID = 277435981
COMMAND_RE = re.compile(
    r"/hermes-bridge lidl-gate-a "
    r"pr=(?P<pr>[1-9][0-9]*) "
    r"target=(?P<target>current|next) "
    r"as_of=(?P<as_of>[0-9]{4}-[0-9]{2}-[0-9]{2}) "
    r"use_previous=(?P<use_previous>true|false)"
)


class BridgeAuthorizationError(ValueError):
    pass


@dataclass(frozen=True)
class BridgeCommand:
    operation: str
    pr_number: int
    target: str
    as_of: str
    use_previous: str


def parse_comment(body: str) -> BridgeCommand:
    if not isinstance(body, str):
        raise BridgeAuthorizationError("comment body must be text")
    match = COMMAND_RE.fullmatch(body.strip())
    if match is None:
        raise BridgeAuthorizationError("comment does not match an allowlisted bridge command")
    as_of = match.group("as_of")
    try:
        parsed = date.fromisoformat(as_of)
    except ValueError as exc:
        raise BridgeAuthorizationError("as_of is not a valid date") from exc
    if parsed.isoformat() != as_of:
        raise BridgeAuthorizationError("as_of is not canonical YYYY-MM-DD")
    return BridgeCommand(
        operation="lidl-gate-a",
        pr_number=int(match.group("pr")),
        target=match.group("target"),
        as_of=as_of,
        use_previous=match.group("use_previous"),
    )


def _default_get_json(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hermes-deals-command-bridge",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def authorize_event(
    event: Mapping[str, Any],
    *,
    repository: str,
    token: str,
    get_json: Callable[[str, str], Any] = _default_get_json,
) -> dict[str, str]:
    if repository != EXPECTED_REPOSITORY:
        raise BridgeAuthorizationError("unexpected repository")
    sender = event.get("sender")
    if not isinstance(sender, Mapping):
        raise BridgeAuthorizationError("event sender is missing")
    if sender.get("login") != EXPECTED_OWNER_LOGIN:
        raise BridgeAuthorizationError("comment sender login is not allowlisted")
    if sender.get("id") != EXPECTED_OWNER_ID:
        raise BridgeAuthorizationError("comment sender numeric ID is not allowlisted")

    issue = event.get("issue")
    if not isinstance(issue, Mapping):
        raise BridgeAuthorizationError("issue payload is missing")
    if issue.get("pull_request") is not None:
        raise BridgeAuthorizationError("bridge commands are accepted only on issues")
    issue_number = issue.get("number")
    if isinstance(issue_number, bool) or not isinstance(issue_number, int) or issue_number <= 0:
        raise BridgeAuthorizationError("issue number is invalid")

    comment = event.get("comment")
    if not isinstance(comment, Mapping):
        raise BridgeAuthorizationError("comment payload is missing")
    command = parse_comment(str(comment.get("body") or ""))

    pr = get_json(
        f"https://api.github.com/repos/{repository}/pulls/{command.pr_number}",
        token,
    )
    if not isinstance(pr, Mapping) or not pr.get("merged") or not pr.get("merged_at"):
        raise BridgeAuthorizationError("Gate A accepts only merged pull requests")
    base = pr.get("base")
    if not isinstance(base, Mapping):
        raise BridgeAuthorizationError("pull request base metadata is missing")
    base_repo = base.get("repo")
    if not isinstance(base_repo, Mapping):
        raise BridgeAuthorizationError("pull request base repository is missing")
    if base.get("ref") != "main" or base_repo.get("full_name") != repository:
        raise BridgeAuthorizationError("pull request was not merged into repository main")

    sha = str(pr.get("merge_commit_sha") or "")
    if re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise BridgeAuthorizationError("merged pull request SHA is invalid")
    comparison = get_json(
        f"https://api.github.com/repos/{repository}/compare/{sha}...main",
        token,
    )
    if not isinstance(comparison, Mapping) or comparison.get("status") not in {"ahead", "identical"}:
        raise BridgeAuthorizationError("merged SHA is not reachable from current main")

    comment_id = comment.get("id")
    if isinstance(comment_id, bool) or not isinstance(comment_id, int) or comment_id <= 0:
        raise BridgeAuthorizationError("comment ID is invalid")

    return {
        "operation": command.operation,
        "pr_number": str(command.pr_number),
        "sha": sha,
        "target": command.target,
        "as_of": command.as_of,
        "use_previous": command.use_previous,
        "issue_number": str(issue_number),
        "comment_id": str(comment_id),
        "trigger_actor": EXPECTED_OWNER_LOGIN,
    }


def write_github_outputs(path: Path, values: Mapping[str, str]) -> None:
    allowed = {
        "operation",
        "pr_number",
        "sha",
        "target",
        "as_of",
        "use_previous",
        "issue_number",
        "comment_id",
        "trigger_actor",
    }
    if set(values) != allowed:
        raise BridgeAuthorizationError("bridge output field set mismatch")
    with path.open("a", encoding="utf-8") as handle:
        for key in sorted(values):
            value = values[key]
            if "\n" in value or "\r" in value:
                raise BridgeAuthorizationError(f"unsafe newline in output: {key}")
            handle.write(f"{key}={value}\n")


def main() -> int:
    event_path = Path(os.environ["GITHUB_EVENT_PATH"])
    output_path = Path(os.environ["GITHUB_OUTPUT"])
    repository = os.environ["GITHUB_REPOSITORY"]
    token = os.environ["GH_TOKEN"]
    event = json.loads(event_path.read_text(encoding="utf-8"))
    values = authorize_event(event, repository=repository, token=token)
    write_github_outputs(output_path, values)
    print(
        json.dumps(
            {
                "result": "AUTHORIZED",
                "operation": values["operation"],
                "issue_number": values["issue_number"],
                "pr_number": values["pr_number"],
                "sha": values["sha"],
                "target": values["target"],
                "as_of": values["as_of"],
                "use_previous": values["use_previous"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
