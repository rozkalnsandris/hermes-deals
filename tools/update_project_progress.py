#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
import sys
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo


START_MARKER = "<!-- project-progress:start -->"
END_MARKER = "<!-- project-progress:end -->"
DEFAULT_API_URL = "https://api.github.com"
EXCLUDED_STATE_REASONS = frozenset({"not_planned", "duplicate"})
STORE_CATEGORIES = (
    ("netto", "Netto"),
    ("lidl", "Lidl"),
    ("aldi", "ALDI Nord"),
    ("edeka", "EDEKA Patzer"),
)


class ProjectProgressError(RuntimeError):
    pass


def _require(condition: bool, message: str) -> None:
    if not condition:
        raise ProjectProgressError(message)


def load_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ProjectProgressError(f"cannot read JSON from {path}: {exc}") from exc


def validate_manifest(manifest: Mapping[str, Any]) -> None:
    _require(manifest.get("schema_version") == 1, "unsupported manifest schema")
    repository = manifest.get("repository")
    _require(
        isinstance(repository, str) and repository.count("/") == 1,
        "manifest repository must be owner/name",
    )
    timezone_name = manifest.get("timezone")
    _require(isinstance(timezone_name, str) and timezone_name, "manifest timezone is required")
    try:
        ZoneInfo(timezone_name)
    except Exception as exc:
        raise ProjectProgressError(f"invalid manifest timezone: {timezone_name}") from exc

    categories = manifest.get("categories")
    _require(isinstance(categories, list) and categories, "manifest categories are required")

    category_ids: set[str] = set()
    item_ids: set[str] = set()
    issue_numbers: set[int] = set()
    total_weight = 0
    total_points = 0

    for category in categories:
        _require(isinstance(category, Mapping), "category must be an object")
        category_id = category.get("id")
        _require(
            isinstance(category_id, str) and category_id and category_id not in category_ids,
            "category ids must be unique non-empty strings",
        )
        category_ids.add(category_id)
        weight = category.get("weight")
        _require(isinstance(weight, int) and weight > 0, f"invalid weight for {category_id}")
        items = category.get("items")
        _require(isinstance(items, list) and items, f"items are required for {category_id}")

        category_points = 0
        for item in items:
            _require(isinstance(item, Mapping), "item must be an object")
            item_id = item.get("id")
            _require(
                isinstance(item_id, str) and item_id and item_id not in item_ids,
                "item ids must be unique non-empty strings",
            )
            item_ids.add(item_id)
            points = item.get("points")
            _require(isinstance(points, int) and points > 0, f"invalid points for {item_id}")
            completion = item.get("completion")
            _require(isinstance(completion, Mapping), f"completion is required for {item_id}")
            completion_type = completion.get("type")
            _require(
                completion_type in {"fixed", "issue"},
                f"unsupported completion type for {item_id}",
            )
            if completion_type == "fixed":
                evidence = completion.get("evidence")
                _require(
                    isinstance(evidence, list)
                    and evidence
                    and all(isinstance(value, str) and value for value in evidence),
                    f"fixed item {item_id} requires evidence",
                )
            else:
                issue_number = completion.get("issue")
                _require(
                    isinstance(issue_number, int)
                    and issue_number > 0
                    and issue_number not in issue_numbers,
                    f"issue items must use unique positive issue numbers: {item_id}",
                )
                issue_numbers.add(issue_number)
            category_points += points

        _require(
            category_points == weight,
            f"category {category_id} points {category_points} do not equal weight {weight}",
        )
        total_weight += weight
        total_points += category_points

    _require(total_weight == 100, f"category weights must total 100, got {total_weight}")
    _require(total_points == 100, f"item points must total 100, got {total_points}")

    missing_store_categories = [
        category_id for category_id, _ in STORE_CATEGORIES if category_id not in category_ids
    ]
    _require(
        not missing_store_categories,
        f"manifest is missing store categories: {', '.join(missing_store_categories)}",
    )

    excluded = manifest.get("excluded_issue_numbers", [])
    _require(
        isinstance(excluded, list)
        and all(isinstance(number, int) and number > 0 for number in excluded),
        "excluded_issue_numbers must contain positive integers",
    )
    prefixes = manifest.get("excluded_issue_title_prefixes", [])
    _require(
        isinstance(prefixes, list)
        and all(isinstance(prefix, str) and prefix for prefix in prefixes),
        "excluded_issue_title_prefixes must contain non-empty strings",
    )


def configured_issue_numbers(manifest: Mapping[str, Any]) -> list[int]:
    return sorted(
        int(item["completion"]["issue"])
        for category in manifest["categories"]
        for item in category["items"]
        if item["completion"]["type"] == "issue"
    )


def parse_now(value: str | None) -> datetime:
    if value is None:
        return datetime.now(timezone.utc)
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ProjectProgressError(f"invalid --now value: {value}") from exc
    _require(parsed.tzinfo is not None, "--now must include a UTC offset")
    return parsed


def previous_day_window(
    now: datetime,
    timezone_name: str,
) -> tuple[str, datetime, datetime]:
    zone = ZoneInfo(timezone_name)
    local_now = now.astimezone(zone)
    previous_date = local_now.date() - timedelta(days=1)
    start_local = datetime.combine(previous_date, time.min, tzinfo=zone)
    end_local = datetime.combine(previous_date + timedelta(days=1), time.min, tzinfo=zone)
    return (
        previous_date.isoformat(),
        start_local.astimezone(timezone.utc),
        end_local.astimezone(timezone.utc),
    )


def parse_github_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value:
        return None
    normalized = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(normalized)
    except ValueError as exc:
        raise ProjectProgressError(f"invalid GitHub timestamp: {value}") from exc
    _require(parsed.tzinfo is not None, f"GitHub timestamp lacks offset: {value}")
    return parsed.astimezone(timezone.utc)


def issue_is_valid_completion(
    issue: Mapping[str, Any],
    *,
    excluded_numbers: set[int],
    excluded_prefixes: tuple[str, ...],
) -> bool:
    number = issue.get("number")
    if not isinstance(number, int) or number in excluded_numbers:
        return False
    if "pull_request" in issue:
        return False
    if issue.get("state") != "closed":
        return False
    if issue.get("state_reason") in EXCLUDED_STATE_REASONS:
        return False
    title = issue.get("title")
    if not isinstance(title, str) or any(title.startswith(prefix) for prefix in excluded_prefixes):
        return False
    return parse_github_timestamp(issue.get("closed_at")) is not None


def issue_closed_in_window(
    issue: Mapping[str, Any],
    start_utc: datetime,
    end_utc: datetime,
) -> bool:
    closed_at = parse_github_timestamp(issue.get("closed_at"))
    return closed_at is not None and start_utc <= closed_at < end_utc


def completion_percent(completed_points: int, weight: int) -> int:
    _require(weight > 0, "weight must be positive")
    _require(0 <= completed_points <= weight, "completed points must fit category weight")
    return (completed_points * 100 + weight // 2) // weight


def calculate_snapshot(
    manifest: Mapping[str, Any],
    issues: Iterable[Mapping[str, Any]],
    *,
    now: datetime,
) -> dict[str, Any]:
    validate_manifest(manifest)
    issue_list = list(issues)
    issues_by_number = {
        int(issue["number"]): issue
        for issue in issue_list
        if isinstance(issue, Mapping) and isinstance(issue.get("number"), int)
    }
    excluded_numbers = set(manifest.get("excluded_issue_numbers", []))
    excluded_prefixes = tuple(manifest.get("excluded_issue_title_prefixes", []))
    previous_date, start_utc, end_utc = previous_day_window(now, manifest["timezone"])

    completed_points = 0
    previous_day_points = 0
    categories: list[dict[str, Any]] = []

    for category in manifest["categories"]:
        category_completed = 0
        rendered_items: list[dict[str, Any]] = []
        for item in category["items"]:
            completion = item["completion"]
            completed = completion["type"] == "fixed"
            issue_number = None
            if completion["type"] == "issue":
                issue_number = int(completion["issue"])
                issue_payload = issues_by_number.get(issue_number)
                _require(issue_payload is not None, f"GitHub issue #{issue_number} is missing")
                completed = issue_is_valid_completion(
                    issue_payload,
                    excluded_numbers=excluded_numbers,
                    excluded_prefixes=excluded_prefixes,
                )
                if completed and issue_closed_in_window(issue_payload, start_utc, end_utc):
                    previous_day_points += int(item["points"])

            if completed:
                completed_points += int(item["points"])
                category_completed += int(item["points"])

            rendered_items.append(
                {
                    "id": item["id"],
                    "label": item["label"],
                    "points": item["points"],
                    "completed": completed,
                    "issue": issue_number,
                }
            )

        weight = int(category["weight"])
        categories.append(
            {
                "id": category["id"],
                "label": category["label"],
                "completed_points": category_completed,
                "weight": weight,
                "completion_percent": completion_percent(category_completed, weight),
                "items": rendered_items,
            }
        )

    completed_issues = [
        issue_payload
        for issue_payload in issue_list
        if issue_is_valid_completion(
            issue_payload,
            excluded_numbers=excluded_numbers,
            excluded_prefixes=excluded_prefixes,
        )
    ]
    completed_issue_numbers = {int(issue_payload["number"]) for issue_payload in completed_issues}

    completed_yesterday = [
        {
            "number": int(issue_payload["number"]),
            "title": str(issue_payload["title"]),
            "closed_at": str(issue_payload["closed_at"]),
            "html_url": str(
                issue_payload.get("html_url")
                or f"https://github.com/{manifest['repository']}/issues/{issue_payload['number']}"
            ),
        }
        for issue_payload in completed_issues
        if issue_closed_in_window(issue_payload, start_utc, end_utc)
    ]
    completed_yesterday.sort(key=lambda item: item["number"])

    category_by_id = {category["id"]: category for category in categories}
    store_catalogues = [
        {
            "id": category_id,
            "label": label,
            "completed_points": category_by_id[category_id]["completed_points"],
            "weight": category_by_id[category_id]["weight"],
            "completion_percent": category_by_id[category_id]["completion_percent"],
        }
        for category_id, label in STORE_CATEGORIES
    ]

    zone = ZoneInfo(manifest["timezone"])
    generated_local = now.astimezone(zone)

    return {
        "schema_version": 1,
        "project": manifest["project"],
        "repository": manifest["repository"],
        "timezone": manifest["timezone"],
        "overall_percent": completed_points,
        "completed_issue_count": len(completed_issue_numbers),
        "previous_day": previous_date,
        "previous_day_percentage_points": previous_day_points,
        "previous_day_completed_issue_count": len(completed_yesterday),
        "previous_day_completed_issues": completed_yesterday,
        "generated_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "generated_at_local": generated_local.isoformat(),
        "store_catalogues": store_catalogues,
        "categories": categories,
    }


def render_progress_bar(percent: int, width: int = 20) -> str:
    _require(0 <= percent <= 100, "percent must be between 0 and 100")
    filled = round(percent * width / 100)
    return "█" * filled + "░" * (width - filled)


def render_readme_block(snapshot: Mapping[str, Any]) -> str:
    previous_day = datetime.fromisoformat(str(snapshot["previous_day"])).strftime("%d.%m.%Y")
    generated_local = datetime.fromisoformat(str(snapshot["generated_at_local"]))
    issue_links = ", ".join(
        f"[#{item['number']}]({item['html_url']})"
        for item in snapshot["previous_day_completed_issues"]
    )
    if not issue_links:
        issue_links = "none"

    delta = int(snapshot["previous_day_percentage_points"])
    delta_text = f"+{delta}" if delta >= 0 else str(delta)
    overall = int(snapshot["overall_percent"])
    bar = render_progress_bar(overall)

    store_lines = []
    for store in snapshot["store_catalogues"]:
        percent = int(store["completion_percent"])
        store_lines.append(
            f"- **{store['label']}:** **{percent}%** "
            f"`{render_progress_bar(percent, width=10)}`"
        )

    return "\n".join(
        [
            START_MARKER,
            "## Project progress",
            "",
            f"**Overall:** **{overall}%** `{bar}`",
            "",
            "**Store catalogues**",
            *store_lines,
            "",
            f"**Previous day ({previous_day}):** **{delta_text} percentage points**",
            "",
            (
                "**Issues fixed:** "
                f"**{snapshot['completed_issue_count']} total** · "
                f"**{snapshot['previous_day_completed_issue_count']} during the previous day**"
                f" — {issue_links}"
            ),
            "",
            (
                "_Last updated automatically: "
                f"{generated_local.strftime('%d.%m.%Y %H:%M')} "
                f"{snapshot['timezone']}. "
                "[Measurement rules](docs/PROJECT_PROGRESS.md)._"
            ),
            END_MARKER,
        ]
    )


def replace_readme_block(readme: str, block: str) -> str:
    _require(readme.count(START_MARKER) == 1, "README must contain exactly one start marker")
    _require(readme.count(END_MARKER) == 1, "README must contain exactly one end marker")
    start = readme.index(START_MARKER)
    end = readme.index(END_MARKER, start) + len(END_MARKER)
    _require(start < end, "README progress markers are out of order")
    return readme[:start] + block + readme[end:]


def atomic_write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.tmp-{os.getpid()}")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def _github_json(
    url: str,
    *,
    token: str,
    api_version: str = "2022-11-28",
) -> Any:
    request = Request(
        url,
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "X-GitHub-Api-Version": api_version,
            "User-Agent": "hermes-deals-project-progress",
        },
    )
    try:
        with urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:500]
        raise ProjectProgressError(f"GitHub API HTTP {exc.code}: {detail}") from exc
    except (URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ProjectProgressError(f"GitHub API request failed: {exc}") from exc


def fetch_github_issues(
    manifest: Mapping[str, Any],
    *,
    token: str,
    api_url: str,
    start_utc: datetime,
) -> list[dict[str, Any]]:
    del start_utc  # Retained in the API for compatibility with older callers/tests.
    repository = manifest["repository"]
    issues: dict[int, dict[str, Any]] = {}

    page = 1
    while True:
        query = urlencode({"state": "all", "per_page": 100, "page": page})
        payload = _github_json(
            f"{api_url.rstrip('/')}/repos/{repository}/issues?{query}",
            token=token,
        )
        _require(isinstance(payload, list), "invalid GitHub issue list payload")
        for issue_payload in payload:
            if isinstance(issue_payload, Mapping) and isinstance(issue_payload.get("number"), int):
                issues[int(issue_payload["number"])] = dict(issue_payload)
        if len(payload) < 100:
            break
        page += 1
        _require(page <= 20, "GitHub issue pagination exceeded safety limit")

    missing = sorted(set(configured_issue_numbers(manifest)) - set(issues))
    _require(not missing, f"GitHub issues are missing: {', '.join(f'#{n}' for n in missing)}")
    return [issues[number] for number in sorted(issues)]


def load_fixture_issues(path: Path) -> list[dict[str, Any]]:
    payload = load_json(path)
    if isinstance(payload, Mapping):
        payload = payload.get("issues")
    _require(isinstance(payload, list), "fixture issue JSON must be a list or {issues: [...]}")
    _require(all(isinstance(issue, Mapping) for issue in payload), "fixture issues must be objects")
    return [dict(issue) for issue in payload]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Update the auditable Hermes Deals project-progress snapshot and README block."
    )
    parser.add_argument("--manifest", type=Path, default=Path("docs/project-progress.json"))
    parser.add_argument("--readme", type=Path, default=Path("README.md"))
    parser.add_argument(
        "--snapshot",
        type=Path,
        default=Path("docs/project-progress-latest.json"),
    )
    parser.add_argument("--issues-json", type=Path)
    parser.add_argument("--now", help="ISO-8601 timestamp with offset; tests/manual audit only")
    parser.add_argument("--api-url", default=DEFAULT_API_URL)
    args = parser.parse_args(argv)

    manifest = load_json(args.manifest)
    _require(isinstance(manifest, Mapping), "manifest root must be an object")
    validate_manifest(manifest)
    now = parse_now(args.now)
    _, start_utc, _ = previous_day_window(now, manifest["timezone"])

    if args.issues_json is not None:
        issues = load_fixture_issues(args.issues_json)
    else:
        token = os.environ.get("GITHUB_TOKEN", "")
        _require(token != "", "GITHUB_TOKEN is required without --issues-json")
        issues = fetch_github_issues(
            manifest,
            token=token,
            api_url=args.api_url,
            start_utc=start_utc,
        )

    snapshot = calculate_snapshot(manifest, issues, now=now)
    snapshot_text = json.dumps(snapshot, ensure_ascii=False, indent=2, sort_keys=True) + "\n"

    readme = args.readme.read_text(encoding="utf-8")
    updated_readme = replace_readme_block(readme, render_readme_block(snapshot))

    atomic_write_text(args.snapshot, snapshot_text)
    atomic_write_text(args.readme, updated_readme)
    print(
        json.dumps(
            {
                "overall_percent": snapshot["overall_percent"],
                "completed_issue_count": snapshot["completed_issue_count"],
                "previous_day": snapshot["previous_day"],
                "previous_day_percentage_points": snapshot[
                    "previous_day_percentage_points"
                ],
                "previous_day_completed_issue_count": snapshot[
                    "previous_day_completed_issue_count"
                ],
                "store_catalogues": snapshot["store_catalogues"],
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProjectProgressError as exc:
        print(f"ERROR: {exc}", file=sys.stderr)
        raise SystemExit(2)
