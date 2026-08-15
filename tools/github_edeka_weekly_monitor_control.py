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
EXPECTED_ISSUE_NUMBER = 26
EXPECTED_CI_WORKFLOW = "Hermes Deals CI checks"
EXPECTED_CI_PATH = ".github/workflows/ci.yml"
EXPECTED_REGISTRATION_SHA = "85c3aca4ac62cbffa281365562af52c5e52d8d24"
EXPECTED_REGISTRATION_FINGERPRINT = "970fac96fd487fe2a027f6dd1055e6563ccec331e53e889511c1e35c5038f947"
REQUIRED_CONTROL_PATHS = {
    ".github/workflows/hermes-edeka-weekly-monitor-control.yml",
    "tools/github_edeka_weekly_monitor_control.py",
    "tools/runner/edeka_weekly_monitor_control.py",
    "tools/runner/install_edeka_weekly_monitor_control_nonrewind.py",
}
SHA40_RE = re.compile(r"[0-9a-f]{40}")
SHA256_RE = re.compile(r"[0-9a-f]{64}")
COMMAND_RE = re.compile(
    r"/hermes-edeka monitor (?P<operation>activate|disable|rollback) "
    r"control=(?P<control>[0-9a-f]{40}) "
    r"registration=(?P<registration>[0-9a-f]{40}) "
    r"fingerprint=(?P<fingerprint>[0-9a-f]{64}) "
    r"refetch=(?P<refetch>authorized|forbidden) "
    r"retries=(?P<retries>authorized|forbidden)"
)


class BridgeAuthorizationError(ValueError):
    pass


@dataclass(frozen=True)
class EdekaMonitorCommand:
    operation: str
    control_sha: str
    registration_sha: str
    fingerprint: str
    refetch: str
    retries: str


def parse_comment(body: str) -> EdekaMonitorCommand:
    if not isinstance(body, str):
        raise BridgeAuthorizationError("comment body must be text")
    match = COMMAND_RE.fullmatch(body.strip())
    if match is None:
        raise BridgeAuthorizationError("comment does not match the EDEKA monitor control command")
    command = EdekaMonitorCommand(
        operation=match.group("operation"),
        control_sha=match.group("control"),
        registration_sha=match.group("registration"),
        fingerprint=match.group("fingerprint"),
        refetch=match.group("refetch"),
        retries=match.group("retries"),
    )
    if command.registration_sha != EXPECTED_REGISTRATION_SHA:
        raise BridgeAuthorizationError("registration SHA is not the reviewed EDEKA monitor registration")
    if command.fingerprint != EXPECTED_REGISTRATION_FINGERPRINT:
        raise BridgeAuthorizationError("registration fingerprint is not the reviewed EDEKA monitor registration")
    if command.operation == "activate":
        if command.refetch != "authorized" or command.retries != "authorized":
            raise BridgeAuthorizationError("activate requires explicit source-refetch and bounded-retry authority")
    else:
        if command.refetch != "forbidden" or command.retries != "forbidden":
            raise BridgeAuthorizationError("disable/rollback must forbid source-refetch and bounded-retry authority")
    return command


def is_command_for_workflow(event: Mapping[str, Any]) -> bool:
    issue = event.get("issue")
    sender = event.get("sender")
    comment = event.get("comment")
    return bool(
        isinstance(issue, Mapping)
        and issue.get("number") == EXPECTED_ISSUE_NUMBER
        and issue.get("pull_request") is None
        and isinstance(sender, Mapping)
        and sender.get("login") == EXPECTED_OWNER_LOGIN
        and sender.get("id") == EXPECTED_OWNER_ID
        and isinstance(comment, Mapping)
        and comment.get("author_association") == "OWNER"
        and isinstance(comment.get("body"), str)
        and str(comment.get("body")).startswith("/hermes-edeka monitor ")
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


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BridgeAuthorizationError(f"{label} payload is invalid")
    return value


def _validate_control_reachable(
    repository: str,
    control_sha: str,
    token: str,
    get_json: Callable[[str, str], Any],
) -> str:
    branch = _require_mapping(
        get_json(f"https://api.github.com/repos/{repository}/branches/main", token),
        "main branch",
    )
    commit = _require_mapping(branch.get("commit"), "main commit")
    current_main = str(commit.get("sha") or "")
    if SHA40_RE.fullmatch(current_main) is None:
        raise BridgeAuthorizationError("current main SHA is invalid")

    comparison = _require_mapping(
        get_json(
            f"https://api.github.com/repos/{repository}/compare/{control_sha}...{current_main}",
            token,
        ),
        "control/main comparison",
    )
    if comparison.get("status") not in {"ahead", "identical"}:
        raise BridgeAuthorizationError("registered control SHA is not reachable from current main")
    return current_main


def _validate_required_control_files(
    repository: str,
    control_sha: str,
    token: str,
    get_json: Callable[[str, str], Any],
) -> None:
    for path in sorted(REQUIRED_CONTROL_PATHS):
        encoded = urllib.parse.quote(path, safe="/")
        payload = _require_mapping(
            get_json(
                f"https://api.github.com/repos/{repository}/contents/{encoded}?ref={control_sha}",
                token,
            ),
            f"required control file {path}",
        )
        if payload.get("type") != "file" or not payload.get("sha"):
            raise BridgeAuthorizationError(f"required control file is missing: {path}")


def _validate_green_exact_main_ci(
    repository: str,
    sha: str,
    token: str,
    get_json: Callable[[str, str], Any],
) -> str:
    query = urllib.parse.urlencode({"head_sha": sha, "event": "push", "per_page": "100"})
    payload = _require_mapping(
        get_json(f"https://api.github.com/repos/{repository}/actions/runs?{query}", token),
        "workflow runs",
    )
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise BridgeAuthorizationError("workflow run list is invalid")
    successful = [
        run
        for run in runs
        if isinstance(run, Mapping)
        and run.get("name") == EXPECTED_CI_WORKFLOW
        and run.get("path") == EXPECTED_CI_PATH
        and run.get("head_sha") == sha
        and run.get("event") == "push"
        and run.get("status") == "completed"
        and run.get("conclusion") == "success"
    ]
    if not successful:
        raise BridgeAuthorizationError("exact current-main Hermes Deals CI is not completed/success")
    run_id = successful[0].get("id")
    if isinstance(run_id, bool) or not isinstance(run_id, int) or run_id <= 0:
        raise BridgeAuthorizationError("successful CI run ID is invalid")
    return str(run_id)


def authorize_event(
    event: Mapping[str, Any],
    *,
    repository: str,
    token: str,
    get_json: Callable[[str, str], Any] = _default_get_json,
) -> dict[str, str]:
    if repository != EXPECTED_REPOSITORY:
        raise BridgeAuthorizationError("unexpected repository")

    sender = _require_mapping(event.get("sender"), "event sender")
    if sender.get("login") != EXPECTED_OWNER_LOGIN or sender.get("id") != EXPECTED_OWNER_ID:
        raise BridgeAuthorizationError("comment sender is not the allowlisted owner")

    issue = _require_mapping(event.get("issue"), "issue")
    if issue.get("pull_request") is not None:
        raise BridgeAuthorizationError("EDEKA monitor commands are accepted only on issues")
    if issue.get("number") != EXPECTED_ISSUE_NUMBER:
        raise BridgeAuthorizationError("command is bound to issue #26")

    comment = _require_mapping(event.get("comment"), "comment")
    if comment.get("author_association") != "OWNER":
        raise BridgeAuthorizationError("comment author association is not OWNER")
    command = parse_comment(str(comment.get("body") or ""))

    current_main = _validate_control_reachable(repository, command.control_sha, token, get_json)
    _validate_required_control_files(repository, command.control_sha, token, get_json)
    ci_run_id = "not-required"
    if command.operation == "activate":
        ci_run_id = _validate_green_exact_main_ci(repository, current_main, token, get_json)

    comment_id = comment.get("id")
    if isinstance(comment_id, bool) or not isinstance(comment_id, int) or comment_id <= 0:
        raise BridgeAuthorizationError("comment ID is invalid")

    return {
        "operation": command.operation,
        "control_sha": command.control_sha,
        "registration_sha": command.registration_sha,
        "fingerprint": command.fingerprint,
        "refetch": command.refetch,
        "retries": command.retries,
        "current_main": current_main,
        "ci_run_id": ci_run_id,
        "issue_number": str(EXPECTED_ISSUE_NUMBER),
        "comment_id": str(comment_id),
        "trigger_actor": EXPECTED_OWNER_LOGIN,
    }


def write_github_outputs(path: Path, values: Mapping[str, str]) -> None:
    allowed = {
        "operation",
        "control_sha",
        "registration_sha",
        "fingerprint",
        "refetch",
        "retries",
        "current_main",
        "ci_run_id",
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
                "control_sha": values["control_sha"],
                "registration_sha": values["registration_sha"],
                "fingerprint": values["fingerprint"],
                "current_main": values["current_main"],
                "ci_run_id": values["ci_run_id"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
