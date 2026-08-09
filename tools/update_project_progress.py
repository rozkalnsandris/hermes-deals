#!/usr/bin/env python3
from __future__ import annotations

import argparse
from datetime import datetime, time, timedelta, timezone
import json
import os
from pathlib import Path
from typing import Any, Iterable, Mapping
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from zoneinfo import ZoneInfo

START_MARKER = "<!-- project-progress:start -->"
END_MARKER = "<!-- project-progress:end -->"
DEFAULT_API_URL = "https://api.github.com"
EXCLUDED_STATE_REASONS = frozenset({"not_planned", "duplicate"})
STORE_CATEGORIES = (("netto", "Netto"), ("lidl", "Lidl"), ("aldi", "ALDI Nord"), ("edeka", "EDEKA Patzer"))
EXPECTED_SCHEMA_VERSION = 2
EXPECTED_UNITS_PER_PERCENTAGE_POINT = 10
EXPECTED_TOTAL_UNITS = 1000


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
    _require(manifest.get("schema_version") == 2, "unsupported manifest schema")
    _require(manifest.get("units_per_percentage_point") == 10, "V2 requires 10 integer units per percentage point")
    repository = manifest.get("repository")
    _require(isinstance(repository, str) and repository.count("/") == 1, "manifest repository must be owner/name")
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
    total_weight = total_items = 0
    for category in categories:
        _require(isinstance(category, Mapping), "category must be an object")
        category_id = category.get("id")
        _require(isinstance(category_id, str) and category_id and category_id not in category_ids, "category ids must be unique non-empty strings")
        category_ids.add(category_id)
        weight = category.get("weight_units")
        _require(isinstance(weight, int) and weight > 0, f"invalid weight_units for {category_id}")
        items = category.get("items")
        _require(isinstance(items, list) and items, f"items are required for {category_id}")
        category_units = 0
        for item in items:
            _require(isinstance(item, Mapping), "item must be an object")
            item_id = item.get("id")
            _require(isinstance(item_id, str) and item_id and item_id not in item_ids, "item ids must be unique non-empty strings")
            item_ids.add(item_id)
            units = item.get("units")
            _require(isinstance(units, int) and units > 0, f"invalid units for {item_id}")
            completion = item.get("completion")
            _require(isinstance(completion, Mapping), f"completion is required for {item_id}")
            kind = completion.get("type")
            _require(kind in {"fixed", "issue"}, f"unsupported completion type for {item_id}")
            if kind == "fixed":
                evidence = completion.get("evidence")
                _require(isinstance(evidence, list) and evidence and all(isinstance(v, str) and v for v in evidence), f"fixed item {item_id} requires evidence")
            else:
                number = completion.get("issue")
                _require(isinstance(number, int) and number > 0 and number not in issue_numbers, f"issue items must use unique positive issue numbers: {item_id}")
                issue_numbers.add(number)
            category_units += units
        _require(category_units == weight, f"category {category_id} item units {category_units} do not equal weight_units {weight}")
        total_weight += weight
        total_items += category_units
    _require(total_weight == 1000, f"category weights must total 1000, got {total_weight}")
    _require(total_items == 1000, f"item units must total 1000, got {total_items}")
    missing = [category_id for category_id, _ in STORE_CATEGORIES if category_id not in category_ids]
    _require(not missing, f"manifest is missing store categories: {', '.join(missing)}")
    excluded = manifest.get("excluded_issue_numbers", [])
    _require(isinstance(excluded, list) and all(isinstance(n, int) and n > 0 for n in excluded), "excluded_issue_numbers must contain positive integers")
    prefixes = manifest.get("excluded_issue_title_prefixes", [])
    _require(isinstance(prefixes, list) and all(isinstance(p, str) and p for p in prefixes), "excluded_issue_title_prefixes must contain non-empty strings")


def configured_issue_numbers(manifest: Mapping[str, Any]) -> list[int]:
    return sorted(int(item["completion"]["issue"]) for category in manifest["categories"] for item in category["items"] if item["completion"]["type"] == "issue")


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


def previous_day_window(now: datetime, timezone_name: str) -> tuple[str, datetime, datetime]:
    zone = ZoneInfo(timezone_name)
    previous_date = now.astimezone(zone).date() - timedelta(days=1)
    start = datetime.combine(previous_date, time.min, tzinfo=zone)
    end = datetime.combine(previous_date + timedelta(days=1), time.min, tzinfo=zone)
    return previous_date.isoformat(), start.astimezone(timezone.utc), end.astimezone(timezone.utc)


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


def issue_is_valid_completion(issue: Mapping[str, Any], *, excluded_numbers: set[int], excluded_prefixes: tuple[str, ...]) -> bool:
    number = issue.get("number")
    if not isinstance(number, int) or number in excluded_numbers or "pull_request" in issue or issue.get("state") != "closed":
        return False
    if issue.get("state_reason") in EXCLUDED_STATE_REASONS:
        return False
    title = issue.get("title")
    if not isinstance(title, str) or any(title.startswith(prefix) for prefix in excluded_prefixes):
        return False
    return parse_github_timestamp(issue.get("closed_at")) is not None


def issue_closed_in_window(issue: Mapping[str, Any], start_utc: datetime, end_utc: datetime) -> bool:
    closed_at = parse_github_timestamp(issue.get("closed_at"))
    return closed_at is not None and start_utc <= closed_at < end_utc


def completion_percent_tenths(completed_units: int, weight_units: int) -> int:
    _require(weight_units > 0, "weight_units must be positive")
    _require(0 <= completed_units <= weight_units, "completed units must fit category weight")
    return (completed_units * 1000 + weight_units // 2) // weight_units


def format_percent_tenths(value: int) -> str:
    _require(0 <= value <= 1000, "percent tenths must be between 0 and 1000")
    return f"{value // 10}.{value % 10}"


def format_project_units(units: int) -> str:
    _require(units >= 0, "project units cannot be negative")
    return f"{units // 10}.{units % 10}"


def calculate_snapshot(manifest: Mapping[str, Any], issues: Iterable[Mapping[str, Any]], *, now: datetime) -> dict[str, Any]:
    validate_manifest(manifest)
    issue_list = list(issues)
    issues_by_number = {int(i["number"]): i for i in issue_list if isinstance(i, Mapping) and isinstance(i.get("number"), int)}
    excluded_numbers = set(manifest.get("excluded_issue_numbers", []))
    excluded_prefixes = tuple(manifest.get("excluded_issue_title_prefixes", []))
    previous_date, start_utc, end_utc = previous_day_window(now, manifest["timezone"])
    completed_units = previous_day_units = completed_gate_count = total_gate_count = 0
    previous_day_completed_gates: list[dict[str, Any]] = []
    categories: list[dict[str, Any]] = []

    for category in manifest["categories"]:
        category_completed = 0
        rendered_items = []
        for item in category["items"]:
            total_gate_count += 1
            completion = item["completion"]
            completed = completion["type"] == "fixed"
            issue_number = None
            issue_payload = None
            if completion["type"] == "issue":
                issue_number = int(completion["issue"])
                issue_payload = issues_by_number.get(issue_number)
                _require(issue_payload is not None, f"GitHub issue #{issue_number} is missing")
                completed = issue_is_valid_completion(issue_payload, excluded_numbers=excluded_numbers, excluded_prefixes=excluded_prefixes)
            if completed:
                units = int(item["units"])
                completed_gate_count += 1
                completed_units += units
                category_completed += units
                if issue_payload is not None and issue_closed_in_window(issue_payload, start_utc, end_utc):
                    previous_day_units += units
                    previous_day_completed_gates.append({"category_id": category["id"], "id": item["id"], "label": item["label"], "units": units, "issue": issue_number, "closed_at": str(issue_payload["closed_at"])})
            rendered_items.append({"id": item["id"], "label": item["label"], "units": item["units"], "completed": completed, "issue": issue_number})
        weight = int(category["weight_units"])
        categories.append({"id": category["id"], "label": category["label"], "completed_units": category_completed, "weight_units": weight, "completion_percent_tenths": completion_percent_tenths(category_completed, weight), "items": rendered_items})

    completed_issues = [i for i in issue_list if issue_is_valid_completion(i, excluded_numbers=excluded_numbers, excluded_prefixes=excluded_prefixes)]
    completed_issue_numbers = {int(i["number"]) for i in completed_issues}
    completed_yesterday = [{"number": int(i["number"]), "title": str(i["title"]), "closed_at": str(i["closed_at"]), "html_url": str(i.get("html_url") or f"https://github.com/{manifest['repository']}/issues/{i['number']}")} for i in completed_issues if issue_closed_in_window(i, start_utc, end_utc)]
    completed_yesterday.sort(key=lambda item: item["number"])
    previous_day_completed_gates.sort(key=lambda item: (item["category_id"], item["id"]))
    by_id = {category["id"]: category for category in categories}
    stores = [{"id": category_id, "label": label, "completed_units": by_id[category_id]["completed_units"], "weight_units": by_id[category_id]["weight_units"], "completion_percent_tenths": by_id[category_id]["completion_percent_tenths"]} for category_id, label in STORE_CATEGORIES]
    generated_local = now.astimezone(ZoneInfo(manifest["timezone"]))
    return {
        "schema_version": 2,
        "project": manifest["project"],
        "repository": manifest["repository"],
        "timezone": manifest["timezone"],
        "units_per_percentage_point": 10,
        "total_units": 1000,
        "overall_completed_units": completed_units,
        "overall_percent_tenths": completion_percent_tenths(completed_units, 1000),
        "weighted_gate_count": total_gate_count,
        "completed_weighted_gate_count": completed_gate_count,
        "completed_issue_count": len(completed_issue_numbers),
        "previous_day": previous_date,
        "previous_day_progress_units": previous_day_units,
        "previous_day_completed_gate_count": len(previous_day_completed_gates),
        "previous_day_completed_gates": previous_day_completed_gates,
        "previous_day_completed_issue_count": len(completed_yesterday),
        "previous_day_completed_issues": completed_yesterday,
        "generated_at": now.astimezone(timezone.utc).isoformat().replace("+00:00", "Z"),
        "generated_at_local": generated_local.isoformat(),
        "store_catalogues": stores,
        "categories": categories,
    }


def render_progress_bar(percent_tenths: int, width: int = 20) -> str:
    _require(0 <= percent_tenths <= 1000, "percent tenths must be between 0 and 1000")
    filled = (percent_tenths * width + 500) // 1000
    return "█" * filled + "░" * (width - filled)


def render_readme_block(snapshot: Mapping[str, Any]) -> str:
    previous_day = datetime.fromisoformat(str(snapshot["previous_day"])).strftime("%d.%m.%Y")
    generated_local = datetime.fromisoformat(str(snapshot["generated_at_local"]))
    issue_links = [f"[#{item['number']}]({item['html_url']})" for item in snapshot["previous_day_completed_issues"]]
    delta = int(snapshot["previous_day_progress_units"])
    overall = int(snapshot["overall_percent_tenths"])
    _require(0 <= delta <= overall, "previous-day units must fit overall progress")
    previous = overall - delta
    stores = [f"- **{store['label']}:** **{format_percent_tenths(int(store['completion_percent_tenths']))}%** `{render_progress_bar(int(store['completion_percent_tenths']), width=10)}`" for store in snapshot["store_catalogues"]]
    activity_details: list[str] = []
    if issue_links:
        link_rows = [" · ".join(issue_links[index:index + 8]) for index in range(0, len(issue_links), 8)]
        activity_details = [
            "<details>",
            f"<summary>Show {len(issue_links)} issues fixed on {previous_day}</summary>",
            "",
            *link_rows,
            "",
            "</details>",
            "",
        ]
    return "\n".join([
        START_MARKER,
        "## Project progress",
        "",
        f"**Overall:** **{format_percent_tenths(overall)}%** `{render_progress_bar(overall)}` — weighted project completion",
        "",
        f"**Weighted roadmap progress during {previous_day}:** **+{format_project_units(delta)} percentage points** **({format_percent_tenths(previous)}% → {format_percent_tenths(overall)}%)**",
        "",
        "**Store catalogues**",
        *stores,
        "",
        f"**Weighted roadmap gates:** **{snapshot['completed_weighted_gate_count']}/{snapshot['weighted_gate_count']} complete** · **{snapshot['previous_day_completed_gate_count']} during the previous day**",
        "",
        f"**Development activity:** **Issues fixed:** **{snapshot['completed_issue_count']} total** · **{snapshot['previous_day_completed_issue_count']} during the previous day** ({previous_day})",
        "",
        *activity_details,
        "_Issue activity is informative; only completed weighted roadmap gates move project completion._",
        "",
        f"_Last updated automatically: {generated_local.strftime('%d.%m.%Y %H:%M')} {snapshot['timezone']}. [Measurement V2 rules](docs/PROJECT_PROGRESS.md)._",
        END_MARKER,
    ])


def replace_readme_block(readme: str, block: str) -> str:
    _require(readme.count(START_MARKER) == 1, "README must contain exactly one start marker")
    _require(readme.count(END_MARKER) == 1, "README must contain exactly one end marker")
    start = readme.index(START_MARKER)
    end = readme.index(END_MARKER) + len(END_MARKER)
    _require(start < end, "README project-progress markers are out of order")
    return readme[:start] + block + readme[end:]


def _github_json(url: str, *, token: str, api_version: str = "2022-11-28") -> Any:
    request = Request(url, headers={"Accept": "application/vnd.github+json", "Authorization": f"Bearer {token}", "X-GitHub-Api-Version": api_version, "User-Agent": "hermes-deals-project-progress-v2"})
    try:
        with urlopen(request, timeout=30) as response:
            return json.load(response)
    except (HTTPError, URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise ProjectProgressError(f"GitHub API request failed for {url}: {exc}") from exc


def fetch_github_issues(manifest: Mapping[str, Any], *, token: str, api_url: str = DEFAULT_API_URL, start_utc: datetime | None = None) -> list[dict[str, Any]]:
    del start_utc
    owner, repository = str(manifest["repository"]).split("/", 1)
    page = 1
    issues: list[dict[str, Any]] = []
    while True:
        query = urlencode({"state": "all", "per_page": "100", "page": str(page)})
        payload = _github_json(f"{api_url.rstrip('/')}/repos/{owner}/{repository}/issues?{query}", token=token)
        _require(isinstance(payload, list), "GitHub issues response must be a list")
        issues.extend(item for item in payload if isinstance(item, dict))
        if len(payload) < 100:
            return issues
        page += 1


def write_if_changed(path: Path, content: str) -> None:
    try:
        existing = path.read_text(encoding="utf-8") if path.exists() else None
        if existing != content:
            path.write_text(content, encoding="utf-8")
    except OSError as exc:
        raise ProjectProgressError(f"cannot write {path}: {exc}") from exc


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Update Hermes Deals Project Progress V2")
    parser.add_argument("--manifest", type=Path, default=Path("docs/project-progress.json"))
    parser.add_argument("--readme", type=Path, default=Path("README.md"))
    parser.add_argument("--snapshot", type=Path, default=Path("docs/project-progress-latest.json"))
    parser.add_argument("--issues-json", type=Path)
    parser.add_argument("--now")
    parser.add_argument("--api-url", default=os.environ.get("GITHUB_API_URL", DEFAULT_API_URL))
    args = parser.parse_args(argv)
    manifest = load_json(args.manifest)
    validate_manifest(manifest)
    now = parse_now(args.now)
    if args.issues_json is not None:
        issues = load_json(args.issues_json)
        _require(isinstance(issues, list), "--issues-json must contain a JSON list")
    else:
        token = os.environ.get("GITHUB_TOKEN")
        _require(bool(token), "GITHUB_TOKEN is required when --issues-json is not supplied")
        issues = fetch_github_issues(manifest, token=str(token), api_url=args.api_url)
    snapshot = calculate_snapshot(manifest, issues, now=now)
    try:
        readme = args.readme.read_text(encoding="utf-8")
    except OSError as exc:
        raise ProjectProgressError(f"cannot read {args.readme}: {exc}") from exc
    write_if_changed(args.readme, replace_readme_block(readme, render_readme_block(snapshot)))
    write_if_changed(args.snapshot, json.dumps(snapshot, indent=2, sort_keys=True, ensure_ascii=False) + "\n")
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ProjectProgressError as exc:
        raise SystemExit(f"ERROR: {exc}") from exc