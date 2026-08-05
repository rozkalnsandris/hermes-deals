from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "rpi5-release-command.yml"


def test_release_authorizer_uses_default_github_event_path() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")

    assert 'os.environ["GITHUB_EVENT_PATH"]' in text
    assert "github.event_path" not in text
    assert "EVENT_PATH:" not in text
