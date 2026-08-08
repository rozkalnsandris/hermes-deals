from __future__ import annotations

import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping
import urllib.request


EXPECTED_REPOSITORY = "rozkalnsandris/hermes-deals"
EXPECTED_OWNER_LOGIN = "rozkalnsandris"
EXPECTED_OWNER_ID = 277435981
EXPECTED_ISSUE_NUMBER = 307
EXPECTED_COMMANDS = {
    "/hermes-307 apply-dual": "apply-dual",
    "/hermes-307 verify-dual": "verify-dual",
    "/hermes-307 finalize-loopback": "finalize-loopback",
    "/hermes-307 verify-loopback": "verify-loopback",
}
RUNTIME_SHA = "654ec9739f8cea74ee8a4ee93e25e12bf06482cc"
PHASE_D_RUNTIME_SHA = "b7a94a8a3d150db43ac051c59a304c31e901ef21"


class BridgeAuthorizationError(ValueError):
    pass


def parse_comment(body: str) -> str:
    if not isinstance(body, str):
        raise BridgeAuthorizationError("comment body must be text")
    if body != body.strip():
        raise BridgeAuthorizationError("comment does not match an exact allowlisted command")
    operation = EXPECTED_COMMANDS.get(body)
    if operation is None:
        raise BridgeAuthorizationError("comment does not match an exact allowlisted command")
    return operation


def _default_get_json(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hermes-deals-307-bridge",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def _assert_registered_runtime_reachable(
    runtime_sha: str,
    *,
    repository: str,
    token: str,
    get_json: Callable[[str, str], Any],
) -> None:
    if re.fullmatch(r"[0-9a-f]{40}", runtime_sha) is None:
        raise BridgeAuthorizationError("registered runtime SHA is invalid")
    comparison = get_json(
        f"https://api.github.com/repos/{repository}/compare/{runtime_sha}...main",
        token,
    )
    if not isinstance(comparison, Mapping) or comparison.get("status") not in {"ahead", "identical"}:
        raise BridgeAuthorizationError("registered runtime SHA is not reachable from current main")


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
    if issue_number != EXPECTED_ISSUE_NUMBER:
        raise BridgeAuthorizationError("bridge command is accepted only on issue 307")

    comment = event.get("comment")
    if not isinstance(comment, Mapping):
        raise BridgeAuthorizationError("issue comment payload is missing")
    operation = parse_comment(str(comment.get("body") or ""))
    comment_id = comment.get("id")
    if isinstance(comment_id, bool) or not isinstance(comment_id, int) or comment_id <= 0:
        raise BridgeAuthorizationError("comment ID is invalid")

    _assert_registered_runtime_reachable(
        RUNTIME_SHA,
        repository=repository,
        token=token,
        get_json=get_json,
    )
    _assert_registered_runtime_reachable(
        PHASE_D_RUNTIME_SHA,
        repository=repository,
        token=token,
        get_json=get_json,
    )

    return {
        "operation": operation,
        "issue_number": str(EXPECTED_ISSUE_NUMBER),
        "comment_id": str(comment_id),
        "runtime_sha": RUNTIME_SHA,
        "phase_d_runtime_sha": PHASE_D_RUNTIME_SHA,
        "trigger_actor": EXPECTED_OWNER_LOGIN,
    }


def write_github_outputs(path: Path, values: Mapping[str, str]) -> None:
    allowed = {
        "operation",
        "issue_number",
        "comment_id",
        "runtime_sha",
        "phase_d_runtime_sha",
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
                "runtime_sha": values["runtime_sha"],
                "phase_d_runtime_sha": values["phase_d_runtime_sha"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
