from __future__ import annotations

import importlib.util
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "update_project_progress.py"


def load_tool():
    spec = importlib.util.spec_from_file_location("hermes_project_progress_presentation", TOOL)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_readme_separates_weighted_progress_from_issue_activity() -> None:
    tool = load_tool()
    snapshot = {
        "previous_day": "2026-08-08",
        "generated_at_local": "2026-08-09T14:59:00+02:00",
        "previous_day_completed_issues": [
            {
                "number": 300,
                "html_url": "https://github.com/rozkalnsandris/hermes-deals/issues/300",
            }
        ],
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
        "completed_issue_count": 122,
        "previous_day_completed_issue_count": 34,
        "timezone": "Europe/Berlin",
    }

    block = tool.render_readme_block(snapshot)

    assert "**Overall:** **72.0%**" in block
    assert "weighted project completion" in block
    assert "**Weighted roadmap progress during 08.08.2026:** **+0.0 percentage points** **(72.0% → 72.0%)**" in block
    assert "**Development activity:** **Issues fixed:** **122 total** · **34 during the previous day**" in block
    assert "[#300](https://github.com/rozkalnsandris/hermes-deals/issues/300)" in block
