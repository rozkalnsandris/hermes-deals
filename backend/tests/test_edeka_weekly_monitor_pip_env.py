from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
RUNTIME = ROOT / "tools" / "edeka_weekly_monitor_runtime.py"


def test_scheduled_shadow_runtime_disables_pip_cache_and_input() -> None:
    source = RUNTIME.read_text(encoding="utf-8")

    assert '"PIP_NO_CACHE_DIR": "1"' in source
    assert '"PIP_DISABLE_PIP_VERSION_CHECK": "1"' in source
    assert '"PIP_NO_INPUT": "1"' in source
