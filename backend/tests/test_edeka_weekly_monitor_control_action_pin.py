from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-edeka-weekly-monitor-control.yml"
PINNED_UPLOAD_ARTIFACT = (
    "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02"
)


def test_edeka_weekly_monitor_self_hosted_artifact_action_is_immutable() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    control = text.split("  control:\n", 1)[1]

    assert "runs-on:\n      - self-hosted\n      - linux\n      - ARM64\n      - hermes-deals-audit" in control
    assert f"uses: {PINNED_UPLOAD_ARTIFACT} # v4.6.2" in control
    assert "uses: actions/upload-artifact@v4" not in control
    assert "sudo --non-interactive -- \"$DISPATCHER\"" in control
    assert "production_database_write_authorized\": False" in control
    assert "deployment_authorized\": False" in control
