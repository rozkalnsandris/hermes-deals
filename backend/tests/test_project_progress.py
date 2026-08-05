from __future__ import annotations

from datetime import datetime, timezone
import importlib.util
import json
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "update_project_progress.py"
MANIFEST = ROOT / "docs" / "project-progress.json"
WORKFLOW = ROOT / ".github" / "workflows" / "project-progress.yml"


def load_tool():
    spec = importlib.util.spec_from_file_location("hermes_project_progress", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def issue(
    number: int,
    *,
    state: str = "open",
    closed_at: str | None = None,
    state_reason: str | None = None,
    title: str | None = None,
    pull_request: bool = False,
) -> dict:
    payload = {
        "number": number,
        "title": title or f"Issue {number}",
        "state": state,
        "state_reason": state_reason,
        "closed_at": closed_at,
        "html_url": f"https://github.com/rozkalnsandris/hermes-deals/issues/{number}",
    }
    if pull_request:
        payload["pull_request"] = {"url": "https://api.github.test/pulls/1"}
    return payload


def configured_issues(manifest: dict) -> list[dict]:
    closed = {
        12: "2026-08-04T10:00:00Z",
        13: "2026-08-04T12:00:00Z",
        15: "2026-08-04T18:00:00Z",
        17: "2026-08-04T22:05:00Z",
        18: "2026-08-05T08:00:00Z",
        22: "2026-08-05T10:00:00Z",
        23: "2026-08-05T11:00:00Z",
        25: "2026-08-05T12:00:00Z",
        32: "2026-08-05T09:00:00Z",
    }
    return [
        issue(
            number,
            state="closed" if number in closed else "open",
            closed_at=closed.get(number),
            state_reason="completed" if number in closed else None,
        )
        for number in load_tool().configured_issue_numbers(manifest)
    ]


def test_manifest_is_auditable_100_point_contract() -> None:
    tool = load_tool()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tool.validate_manifest(manifest)

    assert sum(category["weight"] for category in manifest["categories"]) == 100
    assert (
        sum(
            item["points"]
            for category in manifest["categories"]
            for item in category["items"]
        )
        == 100
    )
    assert [category_id for category_id, _ in tool.STORE_CATEGORIES] == [
        "netto",
        "lidl",
        "aldi",
        "edeka",
    ]


def test_invalid_manifest_total_fails_closed() -> None:
    tool = load_tool()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["categories"][0]["weight"] += 1

    with pytest.raises(tool.ProjectProgressError, match="do not equal weight"):
        tool.validate_manifest(manifest)


def test_current_baseline_includes_store_percentages_and_issue_totals() -> None:
    tool = load_tool()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    issues = configured_issues(manifest)

    snapshot = tool.calculate_snapshot(
        manifest,
        issues,
        now=datetime(2026, 8, 5, 17, 45, tzinfo=timezone.utc),
    )

    assert snapshot["overall_percent"] == 56
    assert snapshot["completed_issue_count"] == 9
    assert snapshot["previous_day"] == "2026-08-04"
    assert snapshot["previous_day_percentage_points"] == 5
    assert snapshot["previous_day_completed_issue_count"] == 3
    assert [item["number"] for item in snapshot["previous_day_completed_issues"]] == [
        12,
        13,
        15,
    ]
    assert {
        item["id"]: item["completion_percent"]
        for item in snapshot["store_catalogues"]
    } == {
        "netto": 36,
        "lidl": 71,
        "aldi": 60,
        "edeka": 50,
    }


def test_readme_block_renders_store_catalogues_and_both_issue_counts() -> None:
    tool = load_tool()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    snapshot = tool.calculate_snapshot(
        manifest,
        configured_issues(manifest),
        now=datetime(2026, 8, 5, 17, 45, tzinfo=timezone.utc),
    )

    block = tool.render_readme_block(snapshot)

    assert "**Store catalogues**" in block
    assert "**Netto:** **36%**" in block
    assert "**Lidl:** **71%**" in block
    assert "**ALDI Nord:** **60%**" in block
    assert "**EDEKA Patzer:** **50%**" in block
    assert "**Issues fixed:** **9 total** · **3 during the previous day**" in block
    assert "[#12]" in block and "[#13]" in block and "[#15]" in block


def test_completion_percent_is_deterministic_nearest_whole_percent() -> None:
    tool = load_tool()
    assert tool.completion_percent(5, 14) == 36
    assert tool.completion_percent(10, 14) == 71
    assert tool.completion_percent(6, 10) == 60
    assert tool.completion_percent(5, 10) == 50


def test_berlin_previous_day_uses_real_dst_boundaries() -> None:
    tool = load_tool()

    spring_date, spring_start, spring_end = tool.previous_day_window(
        datetime(2026, 3, 30, 4, 0, tzinfo=timezone.utc),
        "Europe/Berlin",
    )
    assert spring_date == "2026-03-29"
    assert spring_start.isoformat() == "2026-03-28T23:00:00+00:00"
    assert spring_end.isoformat() == "2026-03-29T22:00:00+00:00"
    assert spring_end - spring_start == tool.timedelta(hours=23)

    autumn_date, autumn_start, autumn_end = tool.previous_day_window(
        datetime(2026, 10, 26, 5, 0, tzinfo=timezone.utc),
        "Europe/Berlin",
    )
    assert autumn_date == "2026-10-25"
    assert autumn_start.isoformat() == "2026-10-24T22:00:00+00:00"
    assert autumn_end.isoformat() == "2026-10-25T23:00:00+00:00"
    assert autumn_end - autumn_start == tool.timedelta(hours=25)


@pytest.mark.parametrize(
    "candidate",
    [
        issue(200, state="open"),
        issue(
            201,
            state="closed",
            closed_at="2026-08-04T12:00:00Z",
            pull_request=True,
        ),
        issue(
            202,
            state="closed",
            closed_at="2026-08-04T12:00:00Z",
            state_reason="not_planned",
        ),
        issue(
            203,
            state="closed",
            closed_at="2026-08-04T12:00:00Z",
            state_reason="duplicate",
        ),
        issue(
            57,
            state="closed",
            closed_at="2026-08-04T12:00:00Z",
            title="Accidental placeholder — ignore",
        ),
        issue(
            204,
            state="closed",
            closed_at="2026-08-04T12:00:00Z",
            title="[Hermes deploy] generated request",
        ),
    ],
)
def test_non_completed_or_operational_items_are_excluded(candidate: dict) -> None:
    tool = load_tool()
    assert (
        tool.issue_is_valid_completion(
            candidate,
            excluded_numbers={57, 58, 66, 67, 68, 107, 111},
            excluded_prefixes=("[Hermes deploy]",),
        )
        is False
    )


def test_total_issue_count_is_repository_wide_and_deduplicated() -> None:
    tool = load_tool()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    issues = configured_issues(manifest)
    issues.extend(
        [
            issue(200, state="closed", state_reason="completed", closed_at="2026-08-03T12:00:00Z"),
            issue(200, state="closed", state_reason="completed", closed_at="2026-08-03T12:00:00Z"),
            issue(201, state="closed", state_reason="not_planned", closed_at="2026-08-03T12:00:00Z"),
            issue(202, state="closed", state_reason="completed", closed_at="2026-08-03T12:00:00Z", pull_request=True),
        ]
    )

    snapshot = tool.calculate_snapshot(
        manifest,
        issues,
        now=datetime(2026, 8, 5, 17, 45, tzinfo=timezone.utc),
    )

    assert snapshot["completed_issue_count"] == 10


def test_fetch_github_issues_reads_full_repository_inventory(monkeypatch) -> None:
    tool = load_tool()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    configured = configured_issues(manifest)
    first_page = configured + [issue(500, state="closed", closed_at="2026-01-01T00:00:00Z")]
    first_page.extend(issue(1000 + index) for index in range(100 - len(first_page)))
    second_page = [issue(600, state="closed", closed_at="2026-01-02T00:00:00Z")]
    seen_queries: list[dict[str, list[str]]] = []

    def fake_github_json(url: str, *, token: str, api_version: str = "2022-11-28"):
        assert token == "token"
        assert api_version == "2022-11-28"
        query = parse_qs(urlparse(url).query)
        seen_queries.append(query)
        return first_page if query["page"] == ["1"] else second_page

    monkeypatch.setattr(tool, "_github_json", fake_github_json)

    result = tool.fetch_github_issues(
        manifest,
        token="token",
        api_url="https://api.github.test",
        start_utc=datetime(2026, 8, 4, tzinfo=timezone.utc),
    )

    assert {item["number"] for item in result} >= {500, 600}
    assert [query["page"] for query in seen_queries] == [["1"], ["2"]]
    assert all(query["state"] == ["all"] for query in seen_queries)
    assert all("since" not in query for query in seen_queries)


def test_readme_replacement_preserves_everything_outside_markers() -> None:
    tool = load_tool()
    original = (
        "# Title\n\nBefore\n\n"
        f"{tool.START_MARKER}\nold\n{tool.END_MARKER}"
        "\n\nAfter\n"
    )
    replacement = f"{tool.START_MARKER}\nnew\n{tool.END_MARKER}"

    updated = tool.replace_readme_block(original, replacement)

    assert updated == (
        "# Title\n\nBefore\n\n"
        f"{tool.START_MARKER}\nnew\n{tool.END_MARKER}"
        "\n\nAfter\n"
    )
    assert tool.replace_readme_block(updated, replacement) == updated


def test_readme_replacement_requires_exactly_one_marker_pair() -> None:
    tool = load_tool()

    with pytest.raises(tool.ProjectProgressError, match="exactly one start marker"):
        tool.replace_readme_block("# no markers\n", "block")

    duplicated = (
        f"{tool.START_MARKER}{tool.END_MARKER}"
        f"{tool.START_MARKER}{tool.END_MARKER}"
    )
    with pytest.raises(tool.ProjectProgressError, match="exactly one start marker"):
        tool.replace_readme_block(duplicated, "block")


def test_workflow_is_daily_berlin_only_and_minimally_scoped() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'cron: "0 6 * * *"' in text
    assert 'timezone: "Europe/Berlin"' in text
    assert "workflow_dispatch:" in text
    assert "contents: write" in text
    assert "issues: read" in text
    assert "pull-requests: write" not in text
    assert "runs-on: ubuntu-latest" in text
    assert "self-hosted" not in text
    assert "docs/project-progress-latest.json" in text
    assert "README.md" in text
    assert "database" not in text.lower()
    assert "docker" not in text.lower()


def test_tool_compiles_and_uses_only_bounded_readme_markers() -> None:
    tool = load_tool()
    compile(TOOL.read_text(encoding="utf-8"), str(TOOL), "exec")
    assert tool.START_MARKER == "<!-- project-progress:start -->"
    assert tool.END_MARKER == "<!-- project-progress:end -->"
