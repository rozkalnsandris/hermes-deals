from __future__ import annotations

from dataclasses import dataclass
import json
import os
from pathlib import Path
import re
from typing import Any, Callable, Mapping
import urllib.parse
import urllib.request


EXPECTED_REPOSITORY = "rozkalnsandris/hermes-deals"
EXPECTED_OWNER_LOGIN = "rozkalnsandris"
EXPECTED_OWNER_ID = 277435981
EXPECTED_PLAN_BLOB = "73abec6752d251b02bf6f47379689400dee106ff"
EXPECTED_APPLY_BLOB = "b8e38b52be69aa6f0cdaa5dbb3f76ccb013c772f"
COMMAND_RE = re.compile(
    r"/hermes-gate-b-plan "
    r"pr=(?P<pr>[1-9][0-9]*) "
    r"gate_a_run_id=(?P<run_id>[1-9][0-9]*) "
    r"gate_a_run_attempt=(?P<attempt>[1-9][0-9]*)"
)


class GateBPlanBridgeAuthorizationError(ValueError):
    pass


@dataclass(frozen=True)
class GateBPlanBridgeCommand:
    pr_number: int
    gate_a_run_id: int
    gate_a_run_attempt: int


def parse_comment(body: str) -> GateBPlanBridgeCommand:
    if not isinstance(body, str):
        raise GateBPlanBridgeAuthorizationError("comment body must be text")
    match = COMMAND_RE.fullmatch(body.strip())
    if match is None:
        raise GateBPlanBridgeAuthorizationError(
            "comment does not match the allowlisted Gate B plan bridge command"
        )
    return GateBPlanBridgeCommand(
        pr_number=int(match.group("pr")),
        gate_a_run_id=int(match.group("run_id")),
        gate_a_run_attempt=int(match.group("attempt")),
    )


def _default_get_json(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hermes-deals-gate-b-plan-bridge",
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
        raise GateBPlanBridgeAuthorizationError("unexpected repository")

    sender = event.get("sender")
    if not isinstance(sender, Mapping):
        raise GateBPlanBridgeAuthorizationError("event sender is missing")
    if sender.get("login") != EXPECTED_OWNER_LOGIN:
        raise GateBPlanBridgeAuthorizationError(
            "comment sender login is not allowlisted"
        )
    if sender.get("id") != EXPECTED_OWNER_ID:
        raise GateBPlanBridgeAuthorizationError(
            "comment sender numeric ID is not allowlisted"
        )

    issue = event.get("issue")
    if not isinstance(issue, Mapping):
        raise GateBPlanBridgeAuthorizationError("issue payload is missing")
    if issue.get("pull_request") is not None:
        raise GateBPlanBridgeAuthorizationError(
            "Gate B plan bridge commands are accepted only on issues"
        )
    issue_number = issue.get("number")
    if (
        isinstance(issue_number, bool)
        or not isinstance(issue_number, int)
        or issue_number <= 0
    ):
        raise GateBPlanBridgeAuthorizationError("issue number is invalid")

    comment = event.get("comment")
    if not isinstance(comment, Mapping):
        raise GateBPlanBridgeAuthorizationError("comment payload is missing")
    command = parse_comment(str(comment.get("body") or ""))

    pr = get_json(
        f"https://api.github.com/repos/{repository}/pulls/{command.pr_number}",
        token,
    )
    if (
        not isinstance(pr, Mapping)
        or not pr.get("merged")
        or not pr.get("merged_at")
    ):
        raise GateBPlanBridgeAuthorizationError(
            "Gate B plan accepts only merged pull requests"
        )
    base = pr.get("base")
    if not isinstance(base, Mapping):
        raise GateBPlanBridgeAuthorizationError(
            "pull request base metadata is missing"
        )
    base_repo = base.get("repo")
    if not isinstance(base_repo, Mapping):
        raise GateBPlanBridgeAuthorizationError(
            "pull request base repository is missing"
        )
    if base.get("ref") != "main" or base_repo.get("full_name") != repository:
        raise GateBPlanBridgeAuthorizationError(
            "pull request was not merged into repository main"
        )

    sha = str(pr.get("merge_commit_sha") or "")
    if re.fullmatch(r"[0-9a-f]{40}", sha) is None:
        raise GateBPlanBridgeAuthorizationError(
            "merged pull request SHA is invalid"
        )
    comparison = get_json(
        f"https://api.github.com/repos/{repository}/compare/{sha}...main",
        token,
    )
    if (
        not isinstance(comparison, Mapping)
        or comparison.get("status") not in {"ahead", "identical"}
    ):
        raise GateBPlanBridgeAuthorizationError(
            "merged SHA is not reachable from current main"
        )

    expected_blobs = {
        "tools/lidl_gate_b_freeze_plan.py": EXPECTED_PLAN_BLOB,
        "tools/lidl_gate_b_freeze_apply.py": EXPECTED_APPLY_BLOB,
    }
    for path, expected_blob in expected_blobs.items():
        encoded = urllib.parse.quote(path, safe="/")
        at_sha = get_json(
            f"https://api.github.com/repos/{repository}/contents/{encoded}?ref={sha}",
            token,
        )
        at_main = get_json(
            f"https://api.github.com/repos/{repository}/contents/{encoded}?ref=main",
            token,
        )
        if not isinstance(at_sha, Mapping) or at_sha.get("sha") != expected_blob:
            raise GateBPlanBridgeAuthorizationError(
                f"registered Gate B blob mismatch: {path}"
            )
        if not isinstance(at_main, Mapping) or at_main.get("sha") != expected_blob:
            raise GateBPlanBridgeAuthorizationError(
                f"current main Gate B blob drift: {path}"
            )

    comment_id = comment.get("id")
    if (
        isinstance(comment_id, bool)
        or not isinstance(comment_id, int)
        or comment_id <= 0
    ):
        raise GateBPlanBridgeAuthorizationError("comment ID is invalid")

    return {
        "pr_number": str(command.pr_number),
        "sha": sha,
        "gate_a_run_id": str(command.gate_a_run_id),
        "gate_a_run_attempt": str(command.gate_a_run_attempt),
        "gate_a_run_key": (
            f"lidl-gate-a-{command.gate_a_run_id}-{command.gate_a_run_attempt}"
        ),
        "issue_number": str(issue_number),
        "comment_id": str(comment_id),
        "trigger_actor": EXPECTED_OWNER_LOGIN,
    }


def write_github_outputs(path: Path, values: Mapping[str, str]) -> None:
    allowed = {
        "pr_number",
        "sha",
        "gate_a_run_id",
        "gate_a_run_attempt",
        "gate_a_run_key",
        "issue_number",
        "comment_id",
        "trigger_actor",
    }
    if set(values) != allowed:
        raise GateBPlanBridgeAuthorizationError("bridge output field set mismatch")
    with path.open("a", encoding="utf-8") as handle:
        for key in sorted(values):
            value = values[key]
            if "\n" in value or "\r" in value:
                raise GateBPlanBridgeAuthorizationError(
                    f"unsafe newline in output: {key}"
                )
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
                "pr_number": values["pr_number"],
                "sha": values["sha"],
                "gate_a_run_key": values["gate_a_run_key"],
                "issue_number": values["issue_number"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
