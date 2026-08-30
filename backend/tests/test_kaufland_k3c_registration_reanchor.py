from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
INSTALLER = ROOT / "tools/runner/install-kaufland-k3c-promo-structure-rpi5-bridge.sh"
RUNBOOK = ROOT / "docs/KAUFLAND_K3C_PROMO_STRUCTURE_RPI5_BRIDGE_RUNBOOK.md"

OLD_REGISTRATION_SHA = "ce1cbedf5ca7a01f360333e72a23c07b46377e9f"


def test_trusted_source_drift_requires_new_reviewed_registration_anchor() -> None:
    text = INSTALLER.read_text(encoding="utf-8")

    assert "trusted source changed after registration SHA" in text
    assert "create and merge a new reviewed K3C registration anchor" in text
    assert "before runtime build/root registration/diagnostic continuation" in text
    assert '[[ "$registration_blob" == "$current_blob" ]]' in text


def test_runbook_records_post_795_registration_invalidation() -> None:
    text = RUNBOOK.read_text(encoding="utf-8")

    assert "#795" in text
    assert OLD_REGISTRATION_SHA in text
    assert "obsolete for post-#795" in text
    assert "new reviewed registration PR" in text
    assert "runtime build" in text
    assert "root registration" in text
    assert "diagnostic" in text
