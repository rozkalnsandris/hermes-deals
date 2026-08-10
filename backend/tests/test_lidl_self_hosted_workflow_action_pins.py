from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
UPLOAD_V4_SHA = "ea165f8d65b6e75b5404" + "49e92b4886f43607fa02"
UPLOAD_V6_SHA = "b7c566a772e6b6bfb58ed0dc250532a479d7789f"
V4_WORKFLOWS = (
    "hermes-gate-b-plan-bridge.yml",
    "hermes-lidl-source-refresh-audit.yml",
    "lidl-gate-b-plan-rpi5.yml",
)
V6_WORKFLOWS = ("lidl-semantic-corpus-rpi5-audit.yml",)


def _upload_uses(name: str) -> list[str]:
    text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("uses: actions/upload-artifact@")
    ]


def test_lidl_gate_b_v4_artifact_actions_are_full_sha_pinned() -> None:
    expected = f"uses: actions/upload-artifact@{UPLOAD_V4_SHA} # v4.6.2"
    for name in V4_WORKFLOWS:
        lines = _upload_uses(name)
        assert lines == [expected], name
        sha = lines[0].split("@", 1)[1].split(maxsplit=1)[0]
        assert re.fullmatch(r"[0-9a-f]{40}", sha)
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "uses: actions/upload-artifact@v4" not in text


def test_lidl_semantic_v6_artifact_action_is_full_sha_pinned() -> None:
    expected = f"uses: actions/upload-artifact@{UPLOAD_V6_SHA} # v6.0.0"
    for name in V6_WORKFLOWS:
        lines = _upload_uses(name)
        assert lines == [expected], name
        sha = lines[0].split("@", 1)[1].split(maxsplit=1)[0]
        assert re.fullmatch(r"[0-9a-f]{40}", sha)
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        assert "uses: actions/upload-artifact@v6" not in text
