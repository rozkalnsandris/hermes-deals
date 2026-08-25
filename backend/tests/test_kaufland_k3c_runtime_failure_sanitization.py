from __future__ import annotations

import importlib.util
import json
from pathlib import Path

from app import kaufland_k3c_promo_structure_diagnostic as promo

ROOT = Path(__file__).resolve().parents[2]
INSTALLER_PATH = ROOT / "tools/runner/install-kaufland-k3c-promo-structure-rpi5-bridge.sh"
VALIDATOR_PATH = ROOT / "tools/runner/kaufland_k3c_promo_structure_bridge_validator.py"

IMPORT_STAGES = (
    ("bs4", "DIAGNOSTIC_IMPORT_BS4_FAILED"),
    ("httpx", "DIAGNOSTIC_IMPORT_HTTPX_FAILED"),
    ("app.kaufland_source_card_contract", "DIAGNOSTIC_IMPORT_SOURCE_CARD_CONTRACT_FAILED"),
    ("app.kaufland_source_discovery", "DIAGNOSTIC_IMPORT_SOURCE_DISCOVERY_FAILED"),
    ("app.kaufland_evidence_preflight", "DIAGNOSTIC_IMPORT_EVIDENCE_PREFLIGHT_FAILED"),
    ("app.kaufland_evidence_freeze", "DIAGNOSTIC_IMPORT_EVIDENCE_FREEZE_FAILED"),
    ("app.kaufland_real_k2_v2_derivation", "DIAGNOSTIC_IMPORT_K2_DERIVATION_FAILED"),
    ("app.kaufland_k3c_promo_structure_diagnostic", "DIAGNOSTIC_IMPORT_PROMO_MODULE_FAILED"),
)

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


def test_dispatcher_verifies_registered_runtime_before_exact_import_stages_and_execution():
    text = INSTALLER_PATH.read_text(encoding="utf-8")
    runtime_verify_marker = 'RUNTIME_VERIFY_REPORT="$(runuser -u andris'
    function_marker = "probe_python_import() {"
    diagnostic_marker = (
        "exec \"$2\" -m app.kaufland_k3c_promo_structure_diagnostic "
        "--retained-root \"$3\""
    )

    assert runtime_verify_marker in text
    assert function_marker in text
    assert diagnostic_marker in text
    assert text.index(runtime_verify_marker) < text.index(function_marker)

    function_start = text.index(function_marker)
    function_end = text.index("\n}\n", function_start) + 3
    function_region = text[function_start:function_end]

    for required in (
        "runuser -u andris",
        "/usr/bin/env -i",
        "HOME=/home/andris USER=andris LOGNAME=andris",
        "PATH=/usr/local/sbin:/usr/local/bin:/usr/sbin:/usr/bin:/sbin:/bin",
        "LANG=C.UTF-8",
        "PYTHONNOUSERSITE=1",
        "PYTHONDONTWRITEBYTECODE=1",
        "PYTHONHASHSEED=0",
        '"$repo/backend" "$RUNTIME_PYTHON" "$module"',
        "importlib.import_module(sys.argv[1])",
        "exit 20",
        '2>"$IMPORT_STDERR_PRIVATE"',
        '20) bridge_block "$reason" ;;',
        '*) bridge_block "DIAGNOSTIC_RUNTIME_IMPORT_FAILED" ;;',
    ):
        assert required in function_region

    assert "/usr/bin/python3 -c" not in function_region

    stage_positions: list[int] = []
    for module, reason in IMPORT_STAGES:
        marker = f"probe_python_import '{module}' '{reason}'"
        assert marker in text
        stage_positions.append(text.index(marker))

    assert stage_positions == sorted(stage_positions)
    assert len(set(stage_positions)) == len(IMPORT_STAGES)
    assert function_end < stage_positions[0]
    assert stage_positions[-1] < text.index(diagnostic_marker)

    private_stderr_marker = 'IMPORT_STDERR_PRIVATE="$STAGING_DIR/diagnostic-import-stderr.private"'
    cleanup_marker = 'rm -f -- "$IMPORT_STDERR_PRIVATE"'
    assert text.index(private_stderr_marker) < function_start
    assert stage_positions[-1] < text.index(cleanup_marker) < text.index(diagnostic_marker)


def test_import_preflight_exports_no_private_stderr_or_dynamic_exception_detail():
    text = INSTALLER_PATH.read_text(encoding="utf-8")
    copy_start = text.index("copy_exports() {")
    copy_end = text.index("\n}\n", copy_start) + 3
    copy_region = text[copy_start:copy_end]
    probe_start = text.index("probe_python_import() {")
    probe_end = text.index("\n}\n", probe_start) + 3
    probe_region = text[probe_start:probe_end]

    assert "diagnostic-import-stderr.private" not in copy_region
    assert "runtime-contract-stderr.private" not in copy_region
    assert "traceback" not in probe_region.casefold()
    assert "exception" not in probe_region.casefold()
    assert "ImportError" not in probe_region
    assert "ModuleNotFoundError" not in probe_region
    assert '20) bridge_block "$reason" ;;' in probe_region
    assert '*) bridge_block "DIAGNOSTIC_RUNTIME_IMPORT_FAILED" ;;' in probe_region

    for _module, reason in IMPORT_STAGES:
        assert reason.isascii()
        assert reason.replace("_", "").isalnum()
        assert reason == reason.upper()
        assert len(reason) <= 96
