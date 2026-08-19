from __future__ import annotations

from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "rpi5-audit-command.yml"
UPLOAD_SHA = "b7c566a772e6b6bfb58ed0dc250532a479d7789f"


def test_rpi5_audit_upload_action_is_full_sha_pinned() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    lines = [
        line.strip()
        for line in text.splitlines()
        if line.strip().startswith("uses: actions/upload-artifact@")
    ]
    assert lines == [
        f"uses: actions/upload-artifact@{UPLOAD_SHA} # v6.0.0"
    ]
    assert re.fullmatch(r"[0-9a-f]{40}", UPLOAD_SHA)
    assert "uses: actions/upload-artifact@v6" not in text


def test_rpi5_audit_command_allowlist_is_unchanged() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'approved_audits = {"runner-smoke", "b15m2-v08"}' in text
    assert '"audit:runner-smoke": "runner-smoke"' in text
    assert '"audit:b15m2-v08": "b15m2-v08"' in text
    assert "- runner-smoke" in text
    assert "- b15m2-v08" in text
    assert "Production deployment: **not authorized**" in text
