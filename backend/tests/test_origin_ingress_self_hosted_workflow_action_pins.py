from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
UPLOAD_SHA = "b7c566a772e6b6bfb58ed0dc250532a479d7789f"
WORKFLOWS = (
    "cloudflare-ingress-rpi5-audit.yml",
    "origin-incident-evidence-rpi5.yml",
    "origin-monitor-install-disabled.yml",
    "origin-path-rpi5-audit.yml",
)


def test_origin_ingress_self_hosted_upload_actions_are_full_sha_pinned() -> None:
    expected = f"uses: actions/upload-artifact@{UPLOAD_SHA} # v6.0.0"
    for name in WORKFLOWS:
        text = (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        lines = [
            line.strip()
            for line in text.splitlines()
            if line.strip().startswith("uses: actions/upload-artifact@")
        ]
        assert lines == [expected], name
        assert "uses: actions/upload-artifact@v6" not in text
        assert re.fullmatch(r"[0-9a-f]{40}", UPLOAD_SHA)


def test_origin_ingress_pin_pr_does_not_activate_runtime_controls() -> None:
    texts = {
        name: (ROOT / ".github" / "workflows" / name).read_text(encoding="utf-8")
        for name in WORKFLOWS
    }
    assert "workflow_dispatch:" in texts["cloudflare-ingress-rpi5-audit.yml"]
    assert "workflow_dispatch:" in texts["origin-incident-evidence-rpi5.yml"]
    assert "workflow_dispatch:" in texts["origin-monitor-install-disabled.yml"]
    assert "workflow_dispatch:" in texts["origin-path-rpi5-audit.yml"]
    assert "actions/checkout@" not in texts["cloudflare-ingress-rpi5-audit.yml"]
    assert "actions/checkout@" not in texts["origin-incident-evidence-rpi5.yml"]
    assert "actions/checkout@" not in texts["origin-path-rpi5-audit.yml"]
