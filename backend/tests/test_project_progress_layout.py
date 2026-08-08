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
        "overall_percent_tenths": 720,
        "previous_day": "2026-08-07",
        "previous_day_progress_units": 120,
        "completed_weighted_gate_count": 54,
        "weighted_gate_count": 67,
        "previous_day_completed_gate_count": 23,
        "completed_issue_count": 87,
        "previous_day_completed_issue_count": 28,
        "previous_day_completed_issues": [
            {
                "number": 294,
                "html_url": "https://github.com/rozkalnsandris/hermes-deals/issues/294",
            }
        ],
        "generated_at_local": "2026-08-08T06:44:00+02:00",
        "timezone": "Europe/Berlin",
        "store_catalogues": [
            {"label": "Netto", "completion_percent_tenths": 786},
            {"label": "Lidl", "completion_percent_tenths": 857},
            {"label": "ALDI Nord", "completion_percent_tenths": 750},
            {"label": "EDEKA Patzer", "completion_percent_tenths": 750},
        ],
    }

    block = tool.render_readme_block(snapshot)

    overall_line = "**Overall:** **72.0%**"
    progress_line = (
        "**Progress during 07.08.2026:** "
        "**+12.0 percentage points** **(60.0% → 72.0%)**"
    )
    store_heading = "**Store catalogues**"

    assert overall_line in block
    assert progress_line in block
    assert block.index(overall_line) < block.index(progress_line) < block.index(store_heading)
    assert "**Overall project progress (07.08.2026):**" not in block
