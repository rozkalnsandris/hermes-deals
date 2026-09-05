from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "edeka-shadow-cycle-rpi5.yml"
UPLOAD_ARTIFACT_SHA = "b7c566a772e6b6bfb58ed0dc250532a479d7789f"


def test_edeka_self_hosted_external_action_is_immutable_and_annotated() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    uses_lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("uses: ")
    ]

    assert uses_lines == [
        f"uses: actions/upload-artifact@{UPLOAD_ARTIFACT_SHA} # v6.0.0"
    ]
    action_ref = uses_lines[0].removeprefix("uses: ").split(maxsplit=1)[0]
    action, sha = action_ref.rsplit("@", 1)
    assert action == "actions/upload-artifact"
    assert sha == UPLOAD_ARTIFACT_SHA
    assert re.fullmatch(r"[0-9a-f]{40}", sha)
    assert "actions/upload-artifact@v6" not in text
