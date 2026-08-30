from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/kaufland-k3c-promo-structure-rpi5.yml"


def test_k3c_workflow_binds_reviewed_sanitizer_reason_taxonomy() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    for reason in (
        "SANITIZER_PRICE_CLASS_REJECTED",
        "SANITIZER_LOCATOR_REJECTED",
        "SANITIZER_IDENTITY_REJECTED",
        "SANITIZER_SCHEMA_REJECTED",
        "SANITIZER_BOUND_REJECTED",
        "SANITIZER_INPUT_READ_REJECTED",
        "SANITIZER_OUTPUT_REJECTED",
    ):
        assert f'"{reason}"' in text

    assert 'reason_code.startswith("SANITIZER_")' in text
    assert 'reason_code not in sanitizer_reason_codes' in text
    assert 'raise SystemExit("unreviewed sanitizer reason code")' in text


def test_k3c_workflow_change_is_registration_anchor_path() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert 'workflow_path = ".github/workflows/kaufland-k3c-promo-structure-rpi5.yml"' in text
    assert 'if not (workflow_changed or installer_changed):' in text
    assert 'selected PR did not introduce or update the K3C bridge control plane' in text
