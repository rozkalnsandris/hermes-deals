from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "update_project_progress.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("hermes_project_progress_compact_activity", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def snapshot_with_issues(count: int) -> dict:
    issues = [
        {
            "number": 300 + index,
            "html_url": f"https://github.com/rozkalnsandris/hermes-deals/issues/{300 + index}",
        }
        for index in range(count)
    ]
    return {
        "previous_day": "2026-08-08",
        "generated_at_local": "2026-08-09T15:21:00+02:00",
        "previous_day_completed_issues": issues,
        "previous_day_progress_units": 0,
        "overall_percent_tenths": 720,
        "store_catalogues": [
            {"label": "Netto", "completion_percent_tenths": 786},
            {"label": "Lidl", "completion_percent_tenths": 857},
            {"label": "ALDI Nord", "completion_percent_tenths": 750},
            {"label": "EDEKA Patzer", "completion_percent_tenths": 750},
        ],
        "completed_weighted_gate_count": 54,
        "weighted_gate_count": 67,
        "previous_day_completed_gate_count": 0,
        "completed_issue_count": 123,
        "previous_day_completed_issue_count": count,
        "timezone": "Europe/Berlin",
    }


def test_activity_keeps_counts_visible_and_collapses_long_issue_list() -> None:
    tool = load_tool()
    block = tool.render_readme_block(snapshot_with_issues(17))

    assert "**Development activity:** **123 issues fixed total** · **17 during 08.08.2026**" in block
    assert "<details>" in block
    assert "<summary>Show 17 issues fixed on 08.08.2026</summary>" in block
    assert "[#300](https://github.com/rozkalnsandris/hermes-deals/issues/300)" in block
    assert "[#316](https://github.com/rozkalnsandris/hermes-deals/issues/316)" in block
    assert block.count("<details>") == 1
    assert block.count("</details>") == 1


def test_activity_omits_empty_details_when_no_issues_closed_yesterday() -> None:
    tool = load_tool()
    block = tool.render_readme_block(snapshot_with_issues(0))

    assert "**Development activity:** **123 issues fixed total** · **0 during 08.08.2026**" in block
    assert "<details>" not in block
    assert "Show 0 issues" not in block
