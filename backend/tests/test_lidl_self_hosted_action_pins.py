from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
V4_SHA = "ea165f8d65b6e75b540449e92b4886f43607fa02"
V6_SHA = "b7c566a772e6b6bfb58ed0dc250532a479d7789f"

EXPECTED_UPLOAD_ARTIFACT_PINS = {
    ".github/workflows/hermes-gate-b-plan-bridge.yml": (V4_SHA, "v4.6.2"),
    ".github/workflows/hermes-lidl-source-refresh-audit.yml": (V4_SHA, "v4.6.2"),
    ".github/workflows/lidl-gate-b-plan-rpi5.yml": (V4_SHA, "v4.6.2"),
    ".github/workflows/lidl-semantic-corpus-rpi5-audit.yml": (V6_SHA, "v6.0.0"),
}

MUTABLE_UPLOAD_ARTIFACT = re.compile(
    r"^\s*uses:\s*actions/upload-artifact@(?![0-9a-f]{40}(?:\s|#|$))\S+",
    re.MULTILINE,
)


def test_lidl_self_hosted_upload_artifact_actions_are_exactly_pinned() -> None:
    for relative_path, (sha, version) in EXPECTED_UPLOAD_ARTIFACT_PINS.items():
        text = (ROOT / relative_path).read_text(encoding="utf-8")
        expected = f"uses: actions/upload-artifact@{sha} # {version}"

        assert text.count("uses: actions/upload-artifact@") == 1, relative_path
        assert expected in text, relative_path
        assert MUTABLE_UPLOAD_ARTIFACT.search(text) is None, relative_path
