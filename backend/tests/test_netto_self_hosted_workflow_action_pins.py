from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
CHECKOUT_SHA = "08c6903cd8c0fde910a37f88322edcfb5dd907a8"
UPLOAD_SHA = "b7c566a772e6b6bfb58ed0dc250532a479d7789f"
HELDOUT_WORKFLOWS = (
    "netto-heldout-github-capture.yml",
    "netto-heldout-github-capture-v2.yml",
)
SHADOW_WORKFLOW = "netto-shadow-rpi5-audit.yml"


def _text(name: str) -> str:
    return (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")


def _uses(text: str, action: str) -> list[str]:
    prefix = f"uses: {action}@"
    return [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith(prefix)
    ]


def test_netto_heldout_self_hosted_actions_are_full_sha_pinned() -> None:
    for name in HELDOUT_WORKFLOWS:
        text = _text(name)
        checkout = _uses(text, "actions/checkout")
        upload = _uses(text, "actions/upload-artifact")
        assert checkout == [
            f"uses: actions/checkout@{CHECKOUT_SHA} # v5.0.0"
        ], name
        assert upload == [
            f"uses: actions/upload-artifact@{UPLOAD_SHA} # v6.0.0"
        ], name
        assert "persist-credentials: false" in text
        assert "uses: actions/checkout@v5" not in text
        assert "uses: actions/upload-artifact@v6" not in text
        assert re.fullmatch(r"[0-9a-f]{40}", CHECKOUT_SHA)
        assert re.fullmatch(r"[0-9a-f]{40}", UPLOAD_SHA)


def test_netto_shadow_self_hosted_action_is_full_sha_pinned() -> None:
    text = _text(SHADOW_WORKFLOW)
    assert _uses(text, "actions/checkout") == []
    assert _uses(text, "actions/upload-artifact") == [
        f"uses: actions/upload-artifact@{UPLOAD_SHA} # v6.0.0"
    ]
    assert "uses: actions/upload-artifact@v6" not in text
