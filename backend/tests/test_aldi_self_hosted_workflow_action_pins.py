from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
UPLOAD_SHA = "b7c566a772e6b6bfb58ed0dc250532a479d7789f"
WORKFLOWS = (
    "aldi-a30-authoritative-cycle-rpi5.yml",
    "aldi-a30-source-discovery-rpi5.yml",
    "aldi-gate-d1-evidence-discovery-overlay-v2.yml",
    "aldi-gate-d1-evidence-discovery-rpi5.yml",
    "aldi-gate-d2-legacy-family-diagnostic-rpi5.yml",
)


def test_aldi_self_hosted_artifact_actions_are_full_sha_pinned() -> None:
    for name in WORKFLOWS:
        path = ROOT / ".github" / "workflows" / name
        text = path.read_text(encoding="utf-8")
        uses_lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip().startswith("uses: actions/upload-artifact@")
        ]
        assert uses_lines == [
            f"uses: actions/upload-artifact@{UPLOAD_SHA} # v6.0.0"
        ], name
        ref = uses_lines[0].split(maxsplit=1)[1].split("#", 1)[0].strip()
        sha = ref.rsplit("@", 1)[1]
        assert re.fullmatch(r"[0-9a-f]{40}", sha)
        assert "actions/upload-artifact@v6" not in text
