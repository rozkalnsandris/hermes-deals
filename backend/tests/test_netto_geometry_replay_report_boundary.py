from __future__ import annotations

from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/netto-geometry-rpi5-replay.yml"


def test_reporting_is_best_effort_but_replay_job_remains_a_hard_workflow_gate() -> None:
    source = WORKFLOW.read_text(encoding="utf-8")
    payload = yaml.safe_load(source)

    report = payload["jobs"]["report"]
    assert set(report["needs"]) == {"authorize", "rpi5-replay"}
    assert "needs.rpi5-replay.result" in source
    assert "RPI5_RESULT: ${{ needs.rpi5-replay.result }}" in source

    # Metadata publication/cleanup must not raise after the evidence job has
    # already succeeded. A genuine replay failure still remains a failed job in
    # the same workflow DAG and cannot be converted to success by the reporter.
    report_source = source.split("\n  report:\n", 1)[1]
    assert "REPORT_METADATA_BEST_EFFORT=PASS" in report_source
    assert "best_effort_comment()" in report_source
    assert "best_effort_label_cleanup()" in report_source
    assert "raise" not in report_source
