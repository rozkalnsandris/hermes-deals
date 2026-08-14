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
EXPECTED_ISSUE_NUMBER = 24
EXPECTED_BRIDGE_PR = 656
SHA40_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
COMMAND_RE = re.compile(
    r"/hermes-lidl gate-d (?P<operation>activate|disable|rollback) "
    r"pr=(?P<pr>[1-9][0-9]*) plan=(?P<plan>[0-9a-f]{64})"
)


class BridgeAuthorizationError(ValueError):
    pass


@dataclass(frozen=True)
class LidlGateDCommand:
    operation: str
    pr_number: int
    plan_fingerprint: str


def parse_comment(body: str) -> LidlGateDCommand:
    if not isinstance(body, str):
        raise BridgeAuthorizationError("comment body must be text")
    match = COMMAND_RE.fullmatch(body.strip())
    if match is None:
        raise BridgeAuthorizationError("comment does not match the Lidl Gate D control command")
    pr_number = int(match.group("pr"))
    if pr_number != EXPECTED_BRIDGE_PR:
        raise BridgeAuthorizationError("bridge PR is not the reviewed Lidl Gate D control PR")
    plan = match.group("plan")
    if SHA256_RE.fullmatch(plan) is None:
        raise BridgeAuthorizationError("plan fingerprint is invalid")
    return LidlGateDCommand(
        operation=match.group("operation"),
        pr_number=pr_number,
        plan_fingerprint=plan,
    )


def _default_get_json(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hermes-deals-lidl-gate-d-control",
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
        raise BridgeAuthorizationError("Lidl Gate D commands are accepted only on issues")
    if issue.get("number") != EXPECTED_ISSUE_NUMBER:
        raise BridgeAuthorizationError("command is bound to issue #24")

    comment = event.get("comment")
    if not isinstance(comment, Mapping):
        raise BridgeAuthorizationError("comment payload is missing")
    if comment.get("author_association") != "OWNER":
        raise BridgeAuthorizationError("comment author association is not OWNER")
    command = parse_comment(str(comment.get("body") or ""))

    pr = get_json(f"https://api.github.com/repos/{repository}/pulls/{command.pr_number}", token)
    if not isinstance(pr, Mapping) or not pr.get("merged") or not pr.get("merged_at"):
        raise BridgeAuthorizationError("Lidl Gate D control PR is not merged")
    base = pr.get("base")
    if not isinstance(base, Mapping):
        raise BridgeAuthorizationError("pull request base metadata is missing")
    base_repo = base.get("repo")
    if not isinstance(base_repo, Mapping):
        raise BridgeAuthorizationError("pull request base repository is missing")
    if base.get("ref") != "main" or base_repo.get("full_name") != repository:
        raise BridgeAuthorizationError("control PR was not merged into repository main")

    sha = str(pr.get("merge_commit_sha") or "")
    if SHA40_RE.fullmatch(sha) is None:
        raise BridgeAuthorizationError("control PR merge SHA is invalid")
    comparison = get_json(f"https://api.github.com/repos/{repository}/compare/{sha}...main", token)
    if not isinstance(comparison, Mapping) or comparison.get("status") not in {"ahead", "identical"}:
        raise BridgeAuthorizationError("reviewed Lidl Gate D merge is not reachable from current main")

    comment_id = comment.get("id")
    if isinstance(comment_id, bool) or not isinstance(comment_id, int) or comment_id <= 0:
        raise BridgeAuthorizationError("comment ID is invalid")

    return {
        "operation": command.operation,
        "pr_number": str(command.pr_number),
        "sha": sha,
        "plan_fingerprint": command.plan_fingerprint,
        "issue_number": str(EXPECTED_ISSUE_NUMBER),
        "comment_id": str(comment_id),
        "trigger_actor": EXPECTED_OWNER_LOGIN,
    }


def write_github_outputs(path: Path, values: Mapping[str, str]) -> None:
    allowed = {
        "operation",
        "pr_number",
        "sha",
        "plan_fingerprint",
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
                **{k: values[k] for k in ("operation", "issue_number", "pr_number", "sha", "plan_fingerprint")},
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
