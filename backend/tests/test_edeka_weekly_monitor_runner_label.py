from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW_PATH = ROOT / ".github" / "workflows" / "hermes-edeka-weekly-monitor-control.yml"


def test_edeka_monitor_control_targets_dedicated_audit_runner() -> None:
    source = WORKFLOW_PATH.read_text(encoding="utf-8")
    control = source.split("\n  control:\n", 1)[1]
    runs_on = control.split("\n    timeout-minutes:", 1)[0]

    assert "- self-hosted" in runs_on
    assert "- linux" in runs_on
    assert "- ARM64" in runs_on
    assert "- hermes-deals-audit" in runs_on
    assert "- rpi5" not in runs_on
