from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[2]
CONTRACT_PATH = ROOT / "backend" / "app" / "ui" / "ui-architecture-contract.json"
AUDIT_PATH = ROOT / "scripts" / "audit_ui_archaeology.py"


def load_audit_module():
    spec = importlib.util.spec_from_file_location("audit_ui_archaeology", AUDIT_PATH)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_w5_archaeology_inventory_matches_frozen_active_release() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    report = load_audit_module().build_report()

    assert report["active_release"] == {
        "bundle_meta": contract["active_release"]["bundle_meta"],
        "release_meta": contract["active_release"]["release"],
        "body_classes": contract["active_release"]["body_classes"],
        "body_data_ui_release": contract["active_release"]["release"],
    }

    css = report["css_archaeology"]
    assert css["style_fragment_count"] <= contract["w5_freeze"]["max_style_fragment_count"]
    assert css["style_fragment_ids"] == contract["w5_freeze"]["expected_style_fragment_ids"]
    assert css["important_declaration_count"] > 0
    assert css["desktop_body_zoom_workaround_present"] is True
    assert css["cascade_layer_declaration_present"] is False


def test_w5_freeze_blocks_new_html_fix_markers_but_allows_cleanup() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    report = load_audit_module().build_report()
    html = report["html_archaeology"]

    assert html["fix_marker_count"] <= contract["w5_freeze"]["max_html_fix_marker_count"]
    assert html["fix_marker_count"] == 20
    assert html["archived_contract_comment_count"] >= 3
    assert "reference-v11-explicit-daily-special-api" in html["fix_markers"]
    assert "weekly-overview-v1" in html["fix_markers"]


def test_w5_inventory_proves_explicit_daily_special_path_is_authoritative() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    report = load_audit_module().build_report()
    javascript = report["javascript_archaeology"]

    assert all(javascript["explicit_daily_special_contract"].values())
    assert set(javascript["legacy_daily_special_helpers"]) == set(
        contract["w5_freeze"]["legacy_daily_special_helpers"]
    )
    # W5A records these as deletion candidates. W5B is expected to turn these
    # values false while preserving the explicit endpoint contract above.
    assert all(javascript["legacy_daily_special_helpers"].values())


def test_w5_audit_cli_emits_deterministic_json() -> None:
    first = subprocess.run(
        [sys.executable, str(AUDIT_PATH), "--compact"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout
    second = subprocess.run(
        [sys.executable, str(AUDIT_PATH), "--compact"],
        cwd=ROOT,
        check=True,
        capture_output=True,
        text=True,
    ).stdout

    assert first == second
    payload = json.loads(first)
    assert payload["schema_version"] == 1
    assert payload["files"]["styles_css_bytes"] > 0
    assert payload["files"]["index_html_bytes"] > 0
    assert payload["files"]["app_js_bytes"] > 0
    assert payload["target_css_hierarchy"] == [
        "tokens",
        "base",
        "layout",
        "controls",
        "components",
        "features",
        "responsive",
        "utilities",
    ]
