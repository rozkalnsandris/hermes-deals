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


BASELINE_CLOSED = {12, 13, 15, 17, 18, 21, 22, 23, 25, 32}
PREVIOUSLY_COMPLETED_EDEKA = {166, 167, 168, 236, 237, 246, 257, 265, 267}
AUGUST_7_WEIGHTED_GATES = {
    124,
    213,
    215,
    222,
    223,
    228,
    230,
    247,
    249,
    250,
    261,
    266,
    270,
    273,
    278,
    280,
    294,
    295,
    301,
    303,
    306,
    313,
    318,
}


def configured_issues(manifest: dict) -> list[dict]:
    closed_at: dict[int, str] = {
        **{number: "2026-08-05T10:00:00Z" for number in BASELINE_CLOSED},
        **{number: "2026-08-06T10:00:00Z" for number in PREVIOUSLY_COMPLETED_EDEKA},
        **{number: "2026-08-07T12:00:00Z" for number in AUGUST_7_WEIGHTED_GATES},
    }
    return [
        issue(
            number,
            state="closed" if number in closed_at else "open",
            closed_at=closed_at.get(number),
            state_reason="completed" if number in closed_at else None,
        )
        for number in load_tool().configured_issue_numbers(manifest)
    ]


def test_manifest_is_auditable_v2_1000_unit_contract() -> None:
    tool = load_tool()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    tool.validate_manifest(manifest)

    assert manifest["schema_version"] == 2
    assert manifest["units_per_percentage_point"] == 10
    assert sum(category["weight_units"] for category in manifest["categories"]) == 1000
    assert sum(item["units"] for category in manifest["categories"] for item in category["items"]) == 1000
    assert [category_id for category_id, _ in tool.STORE_CATEGORIES] == ["netto", "lidl", "aldi", "edeka"]


def test_invalid_manifest_total_fails_closed() -> None:
    tool = load_tool()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    manifest["categories"][0]["weight_units"] += 1
    with pytest.raises(tool.ProjectProgressError, match="do not equal weight_units"):
        tool.validate_manifest(manifest)


def test_v2_baseline_recovers_real_gate_progress_and_august_7_delta() -> None:
    tool = load_tool()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    snapshot = tool.calculate_snapshot(manifest, configured_issues(manifest), now=datetime(2026, 8, 8, 4, 44, tzinfo=timezone.utc))

    assert snapshot["overall_completed_units"] == 720
    assert snapshot["overall_percent_tenths"] == 720
    assert snapshot["previous_day"] == "2026-08-07"
    assert snapshot["previous_day_progress_units"] == 120
    assert snapshot["overall_percent_tenths"] - snapshot["previous_day_progress_units"] == 600
    assert snapshot["previous_day_completed_gate_count"] == 23
    assert snapshot["completed_weighted_gate_count"] == 54
    assert snapshot["weighted_gate_count"] == 67
    assert snapshot["completed_issue_count"] == 39
    assert {item["id"]: item["completion_percent_tenths"] for item in snapshot["store_catalogues"]} == {
        "netto": 786,
        "lidl": 857,
        "aldi": 750,
        "edeka": 750,
    }


def test_open_parent_trackers_do_not_hide_completed_child_gates() -> None:
    tool = load_tool()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    snapshot = tool.calculate_snapshot(manifest, configured_issues(manifest), now=datetime(2026, 8, 8, 4, 44, tzinfo=timezone.utc))
    categories = {item["id"]: item for item in snapshot["categories"]}
    assert categories["lidl"]["completion_percent_tenths"] == 857
    assert next(item for item in categories["lidl"]["items"] if item["issue"] == 24)["completed"] is False
    assert categories["edeka"]["completion_percent_tenths"] == 750
    assert next(item for item in categories["edeka"]["items"] if item["issue"] == 26)["completed"] is False


def test_readme_block_renders_tenths_gate_counts_and_issue_counts() -> None:
    tool = load_tool()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    snapshot = tool.calculate_snapshot(manifest, configured_issues(manifest), now=datetime(2026, 8, 8, 4, 44, tzinfo=timezone.utc))
    block = tool.render_readme_block(snapshot)
    assert "**Overall:** **72.0%**" in block
    assert "**+12.0 percentage points** **(60.0% → 72.0%)**" in block
    assert "**Netto:** **78.6%**" in block
    assert "**Lidl:** **85.7%**" in block
    assert "**ALDI Nord:** **75.0%**" in block
    assert "**EDEKA Patzer:** **75.0%**" in block
    assert "**Weighted roadmap gates:** **54/67 complete** · **23 during the previous day**" in block
    assert "**Issues fixed:** **39 total** · **23 during the previous day**" in block
    assert "Measurement V2 rules" in block


def test_completion_percent_tenths_is_integer_only_and_deterministic() -> None:
    tool = load_tool()
    assert tool.completion_percent_tenths(110, 140) == 786
    assert tool.completion_percent_tenths(120, 140) == 857
    assert tool.completion_percent_tenths(75, 100) == 750
    assert tool.format_percent_tenths(786) == "78.6"
    assert tool.format_project_units(120) == "12.0"


def test_berlin_previous_day_uses_real_dst_boundaries() -> None:
    tool = load_tool()
    spring_date, spring_start, spring_end = tool.previous_day_window(datetime(2026, 3, 30, 4, 0, tzinfo=timezone.utc), "Europe/Berlin")
    assert spring_date == "2026-03-29"
    assert spring_start.isoformat() == "2026-03-28T23:00:00+00:00"
    assert spring_end.isoformat() == "2026-03-29T22:00:00+00:00"
    assert spring_end - spring_start == tool.timedelta(hours=23)
    autumn_date, autumn_start, autumn_end = tool.previous_day_window(datetime(2026, 10, 26, 5, 0, tzinfo=timezone.utc), "Europe/Berlin")
    assert autumn_date == "2026-10-25"
    assert autumn_start.isoformat() == "2026-10-24T22:00:00+00:00"
    assert autumn_end.isoformat() == "2026-10-25T23:00:00+00:00"
    assert autumn_end - autumn_start == tool.timedelta(hours=25)


@pytest.mark.parametrize(
    "candidate",
    [
        issue(200, state="open"),
        issue(201, state="closed", closed_at="2026-08-07T12:00:00Z", pull_request=True),
        issue(202, state="closed", closed_at="2026-08-07T12:00:00Z", state_reason="not_planned"),
        issue(203, state="closed", closed_at="2026-08-07T12:00:00Z", state_reason="duplicate"),
        issue(57, state="closed", closed_at="2026-08-07T12:00:00Z", title="Accidental placeholder — ignore"),
        issue(204, state="closed", closed_at="2026-08-07T12:00:00Z", title="[Hermes deploy] generated request"),
    ],
)
def test_non_completed_or_operational_items_are_excluded(candidate: dict) -> None:
    tool = load_tool()
    assert tool.issue_is_valid_completion(candidate, excluded_numbers={57, 58, 66, 67, 68, 107, 111}, excluded_prefixes=("[Hermes deploy]",)) is False


def test_total_issue_count_is_repository_wide_and_deduplicated() -> None:
    tool = load_tool()
    manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    issues = configured_issues(manifest)
    issues.extend([
        issue(500, state="closed", state_reason="completed", closed_at="2026-08-06T12:00:00Z"),
        issue(500, state="closed", state_reason="completed", closed_at="2026-08-06T12:00:00Z"),
        issue(501, state="closed", state_reason="not_planned", closed_at="2026-08-06T12:00:00Z"),
        issue(502, state="closed", state_reason="completed", closed_at="2026-08-06T12:00:00Z", pull_request=True),
    ])
    snapshot = tool.calculate_snapshot(manifest, issues, now=datetime(2026, 8, 8, 4, 44, tzinfo=timezone.utc))
    assert snapshot["completed_issue_count"] == 40


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
    result = tool.fetch_github_issues(manifest, token="token", api_url="https://api.github.test", start_utc=datetime(2026, 8, 7, tzinfo=timezone.utc))
    assert {item["number"] for item in result} >= {500, 600}
    assert [query["page"] for query in seen_queries] == [["1"], ["2"]]
    assert all(query["state"] == ["all"] for query in seen_queries)
    assert all("since" not in query for query in seen_queries)


def test_readme_replacement_preserves_everything_outside_markers() -> None:
    tool = load_tool()
    original = "# Title\n\nBefore\n\n" f"{tool.START_MARKER}\nold\n{tool.END_MARKER}" "\n\nAfter\n"
    replacement = f"{tool.START_MARKER}\nnew\n{tool.END_MARKER}"
    updated = tool.replace_readme_block(original, replacement)
    assert updated == "# Title\n\nBefore\n\n" f"{tool.START_MARKER}\nnew\n{tool.END_MARKER}" "\n\nAfter\n"
    assert tool.replace_readme_block(updated, replacement) == updated


def test_readme_replacement_requires_exactly_one_marker_pair() -> None:
    tool = load_tool()
    with pytest.raises(tool.ProjectProgressError, match="exactly one start marker"):
        tool.replace_readme_block("# no markers\n", "block")
    duplicated = f"{tool.START_MARKER}{tool.END_MARKER}" f"{tool.START_MARKER}{tool.END_MARKER}"
    with pytest.raises(tool.ProjectProgressError, match="exactly one start marker"):
        tool.replace_readme_block(duplicated, "block")


def test_workflow_uses_ruleset_safe_app_pr_publisher() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'cron: "17 6 * * *"' in text
    assert 'cron: "17 7 * * *"' in text
    assert 'cron: "0 6 * * *"' not in text
    assert text.count('timezone: "Europe/Berlin"') == 2
    assert "push:" in text
    assert "- main" in text
    assert '".github/workflows/project-progress.yml"' in text
    assert '"docs/project-progress.json"' in text
    assert '"tools/update_project_progress.py"' in text
    assert "workflow_dispatch:" in text
    assert "Check scheduled freshness" in text
    assert 'os.environ["GITHUB_EVENT_NAME"] == "schedule"' in text
    assert 'snapshot["generated_at_local"]' in text
    assert "snapshot already generated today" in text
    assert "permissions:\n  contents: read\n  issues: read" in text
    assert "actions/create-github-app-token@v3" in text
    assert "PROJECT_PROGRESS_APP_CLIENT_ID" in text
    assert "PROJECT_PROGRESS_APP_PRIVATE_KEY" in text
    assert "permission-checks: read" in text
    assert "permission-contents: write" in text
    assert "permission-pull-requests: write" in text
    assert "UPDATE_BRANCH: automation/project-progress" in text
    assert "gh auth setup-git" in text
    assert "gh pr create" in text
    assert "gh pr diff" in text
    assert "gh pr checks" in text
    assert "--watch --fail-fast" in text
    assert "gh pr merge" in text
    assert "--squash" in text
    assert "--match-head-commit" in text
    assert "git push origin HEAD:main" not in text
    assert "--admin" not in text
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