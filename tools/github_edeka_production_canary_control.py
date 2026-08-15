from __future__ import annotations

from dataclasses import dataclass
import base64
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
REQUIRED_PATHS = {
    "backend/app/edeka_production_canary.py",
    "config/edeka-production-canary-v01.json",
    ".github/workflows/hermes-edeka-production-canary-control.yml",
    "tools/github_edeka_production_canary_control.py",
}
SHA40_RE = re.compile(r"[0-9a-f]{40}")
COMMAND_RE = re.compile(
    r"/hermes-edeka canary (?P<operation>verify|apply|replay|rollback) "
    r"sha=(?P<sha>[0-9a-f]{40})"
)


class BridgeAuthorizationError(ValueError):
    pass


@dataclass(frozen=True)
class EdekaCanaryCommand:
    operation: str
    sha: str


def parse_comment(body: str) -> EdekaCanaryCommand:
    if not isinstance(body, str):
        raise BridgeAuthorizationError("comment body must be text")
    match = COMMAND_RE.fullmatch(body.strip())
    if match is None:
        raise BridgeAuthorizationError(
            "comment does not match the EDEKA production canary command"
        )
    return EdekaCanaryCommand(
        operation=match.group("operation"),
        sha=match.group("sha"),
    )


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
        and str(comment.get("body")).startswith("/hermes-edeka canary ")
    )


def _default_get_json(url: str, token: str) -> Any:
    request = urllib.request.Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "hermes-deals-edeka-production-canary-control",
        },
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        return json.load(response)


def _require_mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise BridgeAuthorizationError(f"{label} payload is invalid")
    return value


def _validate_plan_contract(plan_file: Mapping[str, Any]) -> None:
    if plan_file.get("type") != "file":
        raise BridgeAuthorizationError("EDEKA canary plan is not a file")
    encoding = plan_file.get("encoding")
    content = plan_file.get("content")
    if encoding != "base64" or not isinstance(content, str):
        raise BridgeAuthorizationError("EDEKA canary plan content is unavailable")
    try:
        payload = json.loads(base64.b64decode(content, validate=True))
    except (ValueError, UnicodeDecodeError, json.JSONDecodeError) as exc:
        raise BridgeAuthorizationError("EDEKA canary plan JSON is invalid") from exc
    if not isinstance(payload, dict):
        raise BridgeAuthorizationError("EDEKA canary plan root is invalid")
    if payload.get("schema_version") != 1:
        raise BridgeAuthorizationError("EDEKA canary plan schema mismatch")
    if payload.get("plan_id") != "edeka-production-canary-v0.1":
        raise BridgeAuthorizationError("EDEKA canary plan identity mismatch")
    if payload.get("state") != "preparation_only":
        raise BridgeAuthorizationError("EDEKA canary plan is not preparation_only")
    if payload.get("production_apply_authorized") is not False:
        raise BridgeAuthorizationError("EDEKA canary plan must not self-authorize apply")

    market = _require_mapping(payload.get("market"), "market")
    expected_market = {
        "source_chain": "edeka",
        "scope": "family_primary_edeka",
        "public_market_id": "071897",
        "internal_market_id": "587881",
        "store_name": "EDEKA Patzer",
        "source_url": "https://www.edeka.de/maerkte/071897/angebote/",
    }
    for key, expected in expected_market.items():
        if market.get(key) != expected:
            raise BridgeAuthorizationError(f"EDEKA canary market {key} mismatch")

    first = _require_mapping(
        payload.get("expected_first_apply_delta"), "first apply delta"
    )
    replay = _require_mapping(
        payload.get("expected_exact_replay_delta"), "replay delta"
    )
    expected_first = {
        "source_snapshots": 1,
        "offer_candidates": 3,
        "offer_normalizations": 3,
        "product_match_candidates": 0,
        "offer_product_links": 0,
        "canonical_products": 0,
        "offer_review_items": 0,
        "offer_review_revisions": 0,
    }
    if dict(first) != expected_first:
        raise BridgeAuthorizationError("EDEKA canary first-apply contract drift")
    if set(replay) != set(expected_first) or any(value != 0 for value in replay.values()):
        raise BridgeAuthorizationError("EDEKA canary replay contract drift")

    rows = payload.get("canary_rows")
    if not isinstance(rows, list) or len(rows) != 3:
        raise BridgeAuthorizationError("EDEKA canary must contain exactly three rows")
    ids = [row.get("source_offer_id") for row in rows if isinstance(row, Mapping)]
    if len(ids) != 3 or len(set(ids)) != 3 or any(not value for value in ids):
        raise BridgeAuthorizationError("EDEKA canary source_offer_id set is invalid")
    if any(not isinstance(row, Mapping) or row.get("review_required") is not False for row in rows):
        raise BridgeAuthorizationError("EDEKA canary rows must all be resolved")


def _validate_required_files(
    repository: str,
    sha: str,
    token: str,
    get_json: Callable[[str, str], Any],
) -> None:
    for path in sorted(REQUIRED_PATHS):
        encoded = urllib.parse.quote(path, safe="/")
        payload = _require_mapping(
            get_json(
                f"https://api.github.com/repos/{repository}/contents/{encoded}?ref={sha}",
                token,
            ),
            f"required file {path}",
        )
        if payload.get("type") != "file" or not payload.get("sha"):
            raise BridgeAuthorizationError(f"required file is missing: {path}")
        if path == "config/edeka-production-canary-v01.json":
            _validate_plan_contract(payload)


def _validate_green_exact_main_ci(
    repository: str,
    sha: str,
    token: str,
    get_json: Callable[[str, str], Any],
) -> str:
    query = urllib.parse.urlencode(
        {"head_sha": sha, "event": "push", "per_page": "100"}
    )
    payload = _require_mapping(
        get_json(
            f"https://api.github.com/repos/{repository}/actions/runs?{query}",
            token,
        ),
        "workflow runs",
    )
    runs = payload.get("workflow_runs")
    if not isinstance(runs, list):
        raise BridgeAuthorizationError("workflow run list is invalid")
    candidates = [
        run
        for run in runs
        if isinstance(run, Mapping)
        and run.get("name") == EXPECTED_CI_WORKFLOW
        and run.get("path") == EXPECTED_CI_PATH
        and run.get("head_sha") == sha
        and run.get("event") == "push"
    ]
    successful = [
        run
        for run in candidates
        if run.get("status") == "completed" and run.get("conclusion") == "success"
    ]
    if not successful:
        raise BridgeAuthorizationError(
            "exact current-main Hermes Deals CI is not completed/success"
        )
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
        raise BridgeAuthorizationError("EDEKA canary commands are accepted only on issues")
    if issue.get("number") != EXPECTED_ISSUE_NUMBER:
        raise BridgeAuthorizationError("command is bound to issue #26")

    comment = _require_mapping(event.get("comment"), "comment")
    if comment.get("author_association") != "OWNER":
        raise BridgeAuthorizationError("comment author association is not OWNER")
    command = parse_comment(str(comment.get("body") or ""))

    branch = _require_mapping(
        get_json(f"https://api.github.com/repos/{repository}/branches/main", token),
        "main branch",
    )
    commit = _require_mapping(branch.get("commit"), "main commit")
    current_main = str(commit.get("sha") or "")
    if SHA40_RE.fullmatch(current_main) is None:
        raise BridgeAuthorizationError("current main SHA is invalid")
    if command.sha != current_main:
        raise BridgeAuthorizationError(
            "authorized SHA must equal the current main commit exactly"
        )

    _validate_required_files(repository, command.sha, token, get_json)
    ci_run_id = _validate_green_exact_main_ci(
        repository, command.sha, token, get_json
    )

    comment_id = comment.get("id")
    if isinstance(comment_id, bool) or not isinstance(comment_id, int) or comment_id <= 0:
        raise BridgeAuthorizationError("comment ID is invalid")

    return {
        "operation": command.operation,
        "sha": command.sha,
        "issue_number": str(EXPECTED_ISSUE_NUMBER),
        "comment_id": str(comment_id),
        "trigger_actor": EXPECTED_OWNER_LOGIN,
        "ci_run_id": ci_run_id,
    }


def write_github_outputs(path: Path, values: Mapping[str, str]) -> None:
    allowed = {
        "operation",
        "sha",
        "issue_number",
        "comment_id",
        "trigger_actor",
        "ci_run_id",
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
                "sha": values["sha"],
                "ci_run_id": values["ci_run_id"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
