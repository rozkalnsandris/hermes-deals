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
EXPECTED_ISSUE_NUMBER = 26
EXPECTED_BRIDGE_PR = 673
SHA40_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
ACTIVATE_RE = re.compile(
    r"/hermes-edeka monitor activate "
    r"pr=(?P<pr>[1-9][0-9]*) "
    r"sha=(?P<sha>[0-9a-f]{40}) "
    r"registration=(?P<registration>[0-9a-f]{64}) "
    r"refetch=authorized retries=authorized"
)
CONTROL_RE = re.compile(
    r"/hermes-edeka monitor (?P<operation>disable|rollback) "
    r"pr=(?P<pr>[1-9][0-9]*) "
    r"sha=(?P<sha>[0-9a-f]{40}) "
    r"registration=(?P<registration>[0-9a-f]{64})"
)


class BridgeAuthorizationError(ValueError):
    pass


@dataclass(frozen=True)
class EdekaMonitorCommand:
    operation: str
    pr_number: int
    registered_sha: str
    registration_fingerprint: str
    source_refetch_authorized: bool
    bounded_retry_authorized: bool


def parse_comment(body: str) -> EdekaMonitorCommand:
    if not isinstance(body, str):
        raise BridgeAuthorizationError("comment body must be text")
    value = body.strip()
    match = ACTIVATE_RE.fullmatch(value)
    if match is not None:
        operation = "activate"
        refetch = True
        retries = True
    else:
        match = CONTROL_RE.fullmatch(value)
        if match is None:
            raise BridgeAuthorizationError("comment does not match the EDEKA monitor control command")
        operation = match.group("operation")
        refetch = False
        retries = False
    pr_number = int(match.group("pr"))
    if pr_number != EXPECTED_BRIDGE_PR:
        raise BridgeAuthorizationError("bridge PR is not the reviewed EDEKA monitor control PR")
    registered_sha = match.group("sha")
    registration = match.group("registration")
    if SHA40_RE.fullmatch(registered_sha) is None:
        raise BridgeAuthorizationError("registered SHA is invalid")
    if SHA256_RE.fullmatch(registration) is None:
        raise BridgeAuthorizationError("registration fingerprint is invalid")
    return EdekaMonitorCommand(
        operation=operation,
        pr_number=pr_number,
        registered_sha=registered_sha,
        registration_fingerprint=registration,
        source_refetch_authorized=refetch,
        bounded_retry_authorized=retries,
    )


def _default_get_json(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hermes-deals-edeka-weekly-monitor-control",
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
        raise BridgeAuthorizationError("EDEKA monitor commands are accepted only on issues")
    if issue.get("number") != EXPECTED_ISSUE_NUMBER:
        raise BridgeAuthorizationError("command is bound to issue #26")

    comment = event.get("comment")
    if not isinstance(comment, Mapping):
        raise BridgeAuthorizationError("comment payload is missing")
    if comment.get("author_association") != "OWNER":
        raise BridgeAuthorizationError("comment author association is not OWNER")
    command = parse_comment(str(comment.get("body") or ""))

    pr = get_json(f"https://api.github.com/repos/{repository}/pulls/{command.pr_number}", token)
    if not isinstance(pr, Mapping) or not pr.get("merged") or not pr.get("merged_at"):
        raise BridgeAuthorizationError("EDEKA monitor control PR is not merged")
    base = pr.get("base")
    if not isinstance(base, Mapping):
        raise BridgeAuthorizationError("pull request base metadata is missing")
    base_repo = base.get("repo")
    if not isinstance(base_repo, Mapping):
        raise BridgeAuthorizationError("pull request base repository is missing")
    if base.get("ref") != "main" or base_repo.get("full_name") != repository:
        raise BridgeAuthorizationError("control PR was not merged into repository main")

    bridge_sha = str(pr.get("merge_commit_sha") or "")
    if SHA40_RE.fullmatch(bridge_sha) is None:
        raise BridgeAuthorizationError("control PR merge SHA is invalid")
    comparison = get_json(f"https://api.github.com/repos/{repository}/compare/{bridge_sha}...main", token)
    if not isinstance(comparison, Mapping) or comparison.get("status") not in {"ahead", "identical"}:
        raise BridgeAuthorizationError("reviewed EDEKA monitor bridge is not reachable from current main")

    if command.operation == "activate":
        main_branch = get_json(f"https://api.github.com/repos/{repository}/branches/main", token)
        if not isinstance(main_branch, Mapping):
            raise BridgeAuthorizationError("main branch metadata is missing")
        commit = main_branch.get("commit")
        if not isinstance(commit, Mapping) or commit.get("sha") != command.registered_sha:
            raise BridgeAuthorizationError("activate requires registration SHA to equal current main")

    comment_id = comment.get("id")
    if isinstance(comment_id, bool) or not isinstance(comment_id, int) or comment_id <= 0:
        raise BridgeAuthorizationError("comment ID is invalid")

    return {
        "operation": command.operation,
        "pr_number": str(command.pr_number),
        "bridge_sha": bridge_sha,
        "registered_sha": command.registered_sha,
        "registration_fingerprint": command.registration_fingerprint,
        "source_refetch_authorized": "true" if command.source_refetch_authorized else "false",
        "bounded_retry_authorized": "true" if command.bounded_retry_authorized else "false",
        "issue_number": str(EXPECTED_ISSUE_NUMBER),
        "comment_id": str(comment_id),
        "trigger_actor": EXPECTED_OWNER_LOGIN,
    }


def write_github_outputs(path: Path, values: Mapping[str, str]) -> None:
    allowed = {
        "operation",
        "pr_number",
        "bridge_sha",
        "registered_sha",
        "registration_fingerprint",
        "source_refetch_authorized",
        "bounded_retry_authorized",
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
                **{
                    key: values[key]
                    for key in (
                        "operation",
                        "issue_number",
                        "pr_number",
                        "bridge_sha",
                        "registered_sha",
                        "registration_fingerprint",
                        "source_refetch_authorized",
                        "bounded_retry_authorized",
                    )
                },
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
