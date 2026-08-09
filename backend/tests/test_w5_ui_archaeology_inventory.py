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


def is_ordered_subsequence(items: list[str], baseline: list[str]) -> bool:
    cursor = iter(baseline)
    return all(any(candidate == item for candidate in cursor) for item in items)


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
    known = contract["w5_freeze"]["known_style_fragment_ids"]
    assert css["style_fragment_count"] <= contract["w5_freeze"]["max_style_fragment_count"]
    assert set(css["style_fragment_ids"]) <= set(known)
    assert is_ordered_subsequence(css["style_fragment_ids"], known)
    assert isinstance(css["important_declaration_count"], int)
    assert isinstance(css["desktop_body_zoom_workaround_present"], bool)
    assert isinstance(css["cascade_layer_declaration_present"], bool)


def test_w5_freeze_blocks_new_html_fix_markers_but_allows_cleanup() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    report = load_audit_module().build_report()
    html = report["html_archaeology"]
    known = contract["w5_freeze"]["known_html_fix_markers"]

    assert html["fix_marker_count"] <= contract["w5_freeze"]["max_html_fix_marker_count"]
    assert set(html["fix_markers"]) <= set(known)
    assert is_ordered_subsequence(html["fix_markers"], known)
    assert html["archived_contract_comment_count"] >= 0


def test_w5_inventory_keeps_explicit_daily_special_contract_visible() -> None:
    contract = json.loads(CONTRACT_PATH.read_text(encoding="utf-8"))
    report = load_audit_module().build_report()
    javascript = report["javascript_archaeology"]

    assert all(javascript["explicit_daily_special_contract"].values())
    assert set(javascript["legacy_daily_special_helpers"]) == set(
        contract["w5_freeze"]["legacy_daily_special_helpers"]
    )
    # Presence values are inventory, not a permanent requirement: W5B may turn
    # any/all of these false while the explicit endpoint contract stays true.
    assert all(isinstance(value, bool) for value in javascript["legacy_daily_special_helpers"].values())


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
