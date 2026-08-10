from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = (
    ROOT
    / ".github"
    / "workflows"
    / "edeka-accounted-live-provenance-derivation.yml"
)


def test_accounted_workflow_is_owner_only_manual_and_sanitized() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for required in (
        "workflow_dispatch:",
        'ACTOR: ${{ github.actor }}',
        'ACTOR_ID: ${{ github.actor_id }}',
        'os.environ["ACTOR"] != "rozkalnsandris"',
        'os.environ["ACTOR_ID"] != "277435981"',
        'run.get("name") != "EDEKA shadow cycle RPi5 audit"',
        'run.get("conclusion") != "success"',
        "tools/edeka_accounted_live_provenance_derivation.py",
        "source-card-accounting.json",
        "excluded_count",
        "Source refetch: **false**",
        "Raw HTML / SQLite uploaded in derived artifact: **false**",
    ):
        assert required in text
    assert "schedule:" not in text
    assert "pull_request:" not in text
    assert "self-hosted" not in text
    assert "/raw/" not in text
    assert "shadow.sqlite3" not in text


def test_accounted_workflow_external_actions_are_full_sha_pinned() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    expected = {
        "actions/checkout": (
            "08c6903cd8c0fde910a37f88322edcfb5dd907a8",
            "v5.0.0",
        ),
        "actions/download-artifact": (
            "018cc2cf5baa6db3ef3c5f8a56943fffe632ef53",
            "v6.0.0",
        ),
        "actions/upload-artifact": (
            "b7c566a772e6b6bfb58ed0dc250532a479d7789f",
            "v6.0.0",
        ),
    }
    uses_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("uses: ")
    ]
    assert len(uses_lines) == len(expected)
    for line in uses_lines:
        action_ref = line.removeprefix("uses: ").split(maxsplit=1)[0]
        action, sha = action_ref.rsplit("@", 1)
        assert action in expected
        expected_sha, version = expected[action]
        assert sha == expected_sha
        assert re.fullmatch(r"[0-9a-f]{40}", sha)
        assert line.endswith(f"# {version}")
