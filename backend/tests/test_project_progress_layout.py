from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "update_project_progress.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("hermes_project_progress_layout", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_previous_day_overall_progress_is_directly_below_overall() -> None:
    tool = load_tool()
    snapshot = {
        "overall_percent": 56,
        "previous_day": "2026-08-04",
        "previous_day_percentage_points": 5,
        "completed_issue_count": 24,
        "previous_day_completed_issue_count": 3,
        "previous_day_completed_issues": [
            {
                "number": 12,
                "html_url": "https://github.com/rozkalnsandris/hermes-deals/issues/12",
            }
        ],
        "generated_at_local": "2026-08-05T20:09:00+02:00",
        "timezone": "Europe/Berlin",
        "store_catalogues": [
            {"label": "Netto", "completion_percent": 36},
            {"label": "Lidl", "completion_percent": 71},
            {"label": "ALDI Nord", "completion_percent": 60},
            {"label": "EDEKA Patzer", "completion_percent": 50},
        ],
    }

    block = tool.render_readme_block(snapshot)

    overall_line = "**Overall:** **56%**"
    progress_line = (
        "**Overall project progress (04.08.2026):** "
        "**+5 percentage points** **(51% → 56%)**"
    )
    store_heading = "**Store catalogues**"

    assert overall_line in block
    assert progress_line in block
    assert block.index(overall_line) < block.index(progress_line) < block.index(store_heading)
    assert "**Previous day (04.08.2026):**" not in block
