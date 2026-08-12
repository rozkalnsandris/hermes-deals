from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping
import urllib.request

EXPECTED_REPOSITORY = "rozkalnsandris/hermes-deals"
EXPECTED_OWNER_LOGIN = "rozkalnsandris"
EXPECTED_OWNER_ID = 277435981
EXPECTED_ISSUE_NUMBER = 631
EXPECTED_RUNTIME_PR = 637
EXPECTED_RUNTIME_SHA = "c53665477a91a8b2b69cc5b63810c091c3072b8e"
COMMAND_RE = re.compile(r"/hermes-aldi gate-d4 pr=(?P<pr>[1-9][0-9]*)")


class BridgeAuthorizationError(ValueError):
    pass


@dataclass(frozen=True)
class AldiGateD4Command:
    operation: str
    pr_number: int


def parse_comment(body: str) -> AldiGateD4Command:
    if not isinstance(body, str):
        raise BridgeAuthorizationError("comment body must be text")
    match = COMMAND_RE.fullmatch(body.strip())
    if match is None:
        raise BridgeAuthorizationError("comment does not match the ALDI Gate D4 command")
    pr_number = int(match.group("pr"))
    if pr_number != EXPECTED_RUNTIME_PR:
        raise BridgeAuthorizationError("runtime PR is not the reviewed Gate D4 runtime PR")
    return AldiGateD4Command(operation="aldi-gate-d4", pr_number=pr_number)


def _default_get_json(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hermes-deals-aldi-gate-d4-bridge",
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
    if sender.get("login") != EXPECTED_OWNER_LOGIN or sender.get("id") != EXPECTED_OWNER_ID:
        raise BridgeAuthorizationError("comment sender is not the allowlisted owner")

    issue = event.get("issue")
    if not isinstance(issue, Mapping):
        raise BridgeAuthorizationError("issue payload is missing")
    if issue.get("pull_request") is not None:
        raise BridgeAuthorizationError("ALDI Gate D4 commands are accepted only on issues")
    if issue.get("number") != EXPECTED_ISSUE_NUMBER:
        raise BridgeAuthorizationError("command is bound to issue #631")

    comment = event.get("comment")
    if not isinstance(comment, Mapping):
        raise BridgeAuthorizationError("comment payload is missing")
    if comment.get("author_association") != "OWNER":
        raise BridgeAuthorizationError("comment author association is not OWNER")
    command = parse_comment(str(comment.get("body") or ""))

    pr = get_json(f"https://api.github.com/repos/{repository}/pulls/{command.pr_number}", token)
    if not isinstance(pr, Mapping) or not pr.get("merged") or not pr.get("merged_at"):
        raise BridgeAuthorizationError("Gate D4 runtime PR is not merged")
    base = pr.get("base")
    if not isinstance(base, Mapping):
        raise BridgeAuthorizationError("pull request base metadata is missing")
    base_repo = base.get("repo")
    if not isinstance(base_repo, Mapping):
        raise BridgeAuthorizationError("pull request base repository is missing")
    if base.get("ref") != "main" or base_repo.get("full_name") != repository:
        raise BridgeAuthorizationError("runtime PR was not merged into repository main")

    sha = str(pr.get("merge_commit_sha") or "")
    if sha != EXPECTED_RUNTIME_SHA:
        raise BridgeAuthorizationError("runtime PR merge SHA does not match reviewed Gate D4 SHA")
    comparison = get_json(f"https://api.github.com/repos/{repository}/compare/{sha}...main", token)
    if not isinstance(comparison, Mapping) or comparison.get("status") not in {"ahead", "identical"}:
        raise BridgeAuthorizationError("reviewed Gate D4 SHA is not reachable from current main")

    comment_id = comment.get("id")
    if isinstance(comment_id, bool) or not isinstance(comment_id, int) or comment_id <= 0:
        raise BridgeAuthorizationError("comment ID is invalid")

    return {
        "operation": command.operation,
        "pr_number": str(command.pr_number),
        "sha": sha,
        "issue_number": str(EXPECTED_ISSUE_NUMBER),
        "comment_id": str(comment_id),
        "trigger_actor": EXPECTED_OWNER_LOGIN,
    }


def write_github_outputs(path: Path, values: Mapping[str, str]) -> None:
    allowed = {"operation", "pr_number", "sha", "issue_number", "comment_id", "trigger_actor"}
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
    print(json.dumps({"result": "AUTHORIZED", **{k: values[k] for k in ("operation", "issue_number", "pr_number", "sha")}}, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
