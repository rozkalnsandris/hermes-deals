from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from app import kaufland_k3c_promo_structure_diagnostic as promo

ROOT = Path(__file__).resolve().parents[2]
INSTALLER_PATH = ROOT / "tools/runner/install-kaufland-k3c-promo-structure-rpi5-bridge.sh"
VALIDATOR_PATH = ROOT / "tools/runner/kaufland_k3c_promo_structure_bridge_validator.py"

_spec = importlib.util.spec_from_file_location("kaufland_k3c_bridge_validator", VALIDATOR_PATH)
assert _spec is not None and _spec.loader is not None
validator = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(validator)


def _captured_payload(capsys) -> dict[str, object]:
    output = capsys.readouterr().out.strip()
    assert output
    payload = json.loads(output)
    assert isinstance(payload, dict)
    return payload


def test_unexpected_exception_is_sanitized_and_validator_compatible(monkeypatch, capsys):
    secret = "SECRET TRACEBACK DETAIL 9.99 /private/retained/path"

    def raise_unexpected(_retained_root: Path) -> dict[str, object]:
        raise RuntimeError(secret)

    monkeypatch.setattr(promo, "run_promo_structure_diagnostic", raise_unexpected)

    rc = promo.main(["--retained-root", "/path-must-not-be-read"])
    payload = _captured_payload(capsys)

    assert rc == 20
    assert payload["status"] == "BLOCKED"
    assert payload["reason_code"] == "UNEXPECTED_DIAGNOSTIC_EXCEPTION"
    assert payload["evidence_only"] is True
    assert payload["promo_role_promoted"] is False
    encoded = json.dumps(payload, sort_keys=True)
    assert secret not in encoded
    assert "9.99" not in encoded
    assert "/private/retained/path" not in encoded

    artifact, summary = validator.validate_and_sanitize(
        payload,
        expected_sha="1" * 40,
        diagnostic_rc=20,
    )
    assert artifact["diagnostic_status"] == "BLOCKED"
    assert artifact["reason_code"] == "UNEXPECTED_DIAGNOSTIC_EXCEPTION"
    assert summary["bridge_execution_status"] == "PASS"
    assert summary["diagnostic_status"] == "BLOCKED"
    assert summary["promo_role_promoted"] is False


def test_known_k3c_error_keeps_exact_reason_without_message(monkeypatch, capsys):
    secret = "PRIVATE KNOWN ERROR DETAIL"

    def raise_known(_retained_root: Path) -> dict[str, object]:
        raise promo.k3c.K3CDerivationError("HTML_PARSER_VERSION_MISMATCH", secret)

    monkeypatch.setattr(promo, "run_promo_structure_diagnostic", raise_known)

    rc = promo.main(["--retained-root", "/path-must-not-be-read"])
    payload = _captured_payload(capsys)

    assert rc == 20
    assert payload["reason_code"] == "HTML_PARSER_VERSION_MISMATCH"
    assert secret not in json.dumps(payload, sort_keys=True)


def test_dispatcher_preflights_exact_isolated_diagnostic_import_before_execution():
    text = INSTALLER_PATH.read_text(encoding="utf-8")
    import_marker = "exec /usr/bin/python3 -c 'import app.kaufland_k3c_promo_structure_diagnostic'"
    diagnostic_marker = (
        "exec /usr/bin/python3 -m app.kaufland_k3c_promo_structure_diagnostic "
        "--retained-root /home/andris/hermes-deals-retained-evidence"
    )

    assert "DIAGNOSTIC_RUNTIME_IMPORT_FAILED" in text
    assert import_marker in text
    assert diagnostic_marker in text
    assert text.index(import_marker) < text.index(diagnostic_marker)

    preflight_region = text[text.index(import_marker) - 500 : text.index(import_marker) + 500]
    assert "runuser -u andris" in preflight_region
    assert "/usr/bin/env -i" in preflight_region
    assert "PYTHONNOUSERSITE=1" in preflight_region
    assert "PYTHONDONTWRITEBYTECODE=1" in preflight_region
    assert "PYTHONHASHSEED=0" in preflight_region
