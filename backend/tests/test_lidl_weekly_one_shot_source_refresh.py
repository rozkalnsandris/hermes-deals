from __future__ import annotations

from datetime import date
import importlib.util
import json
from pathlib import Path
from types import SimpleNamespace
import sys


ROOT = Path(__file__).resolve().parents[2]
for candidate in (ROOT / "tools", ROOT / "backend"):
    value = str(candidate)
    if value not in sys.path:
        sys.path.insert(0, value)

SPEC = importlib.util.spec_from_file_location(
    "lidl_weekly_one_shot_source_refresh_tested",
    ROOT / "tools" / "lidl_weekly_one_shot.py",
)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


TODAY = date(2026, 8, 8)
PDF_SHA = "6" * 64
LIVE_RAW_SHA = "3" * 64
FROZEN_RAW_SHA = "d" * 64
FROZEN_INPUT = "8" * 64
LIVE_INPUT = "e" * 64
STABLE_SHA = "7" * 64
SCAN_NAME = "scan-v631-7191e910f07b"


def make_selected() -> SimpleNamespace:
    return SimpleNamespace(
        source_json=b"live-source",
        pdf_sha256=PDF_SHA,
        raw_sha256=LIVE_RAW_SHA,
        page_count=69,
    )


def make_match(family: Path) -> MODULE.CorpusMatch:
    return MODULE.CorpusMatch(
        flyer_dir=family,
        flyer_key=family.name,
        scan=None,
        source_pdf_sha256=PDF_SHA,
        source_raw_sha256=FROZEN_RAW_SHA,
        live_raw_sha256=LIVE_RAW_SHA,
        raw_refresh=True,
        stable_source_identity_sha256=STABLE_SHA,
        parser_input_identity_sha256=FROZEN_INPUT,
        live_parser_input_identity_sha256=LIVE_INPUT,
        parser_input_changed=True,
    )


def install_common(monkeypatch, tmp_path: Path) -> tuple[Path, Path]:
    family = tmp_path / "corpus" / "flyers" / "family-rev05"
    family.mkdir(parents=True)
    discovery_dir = tmp_path / "discovery"
    discovery_dir.mkdir()
    selected = make_selected()
    discovery = {
        "today_berlin": TODAY.isoformat(),
        "store_external_id": "5659",
        "route_region_hardcoded": "21",
        "targets": {"current": {"pdf_sha256": PDF_SHA, "raw_sha256": LIVE_RAW_SHA}},
    }
    monkeypatch.setattr(
        MODULE,
        "load_discovery_evidence",
        lambda _: (discovery, {"current": selected}),
    )
    monkeypatch.setattr(
        MODULE,
        "source_readiness",
        lambda _: {
            "state": "SOURCE_AVAILABLE",
            "reason": "source_payload_usable",
            "product_link_count": 141,
            "page_count": 69,
            "nonfood_signal": True,
        },
    )
    monkeypatch.setattr(
        MODULE,
        "find_corpus_match",
        lambda *args, **kwargs: make_match(family),
    )
    return family, discovery_dir


def run(monkeypatch, tmp_path: Path) -> dict:
    return MODULE.run_one_shot(
        corpus=tmp_path / "corpus",
        output_dir=tmp_path / "output",
        target="current",
        today=TODAY,
        binding=MODULE.StoreBinding(),
        discovery_dir=tmp_path / "discovery",
    )


def test_missing_refresh_authority_preserves_wait_source_review(monkeypatch, tmp_path: Path) -> None:
    _, _ = install_common(monkeypatch, tmp_path)
    monkeypatch.setattr(MODULE, "validate_authoritative_refresh", lambda **kwargs: None)
    result = run(monkeypatch, tmp_path)
    assert result["result"] == "WAIT_SOURCE_REVIEW"
    assert result["reason"] == "parser_input_identity_changed_for_existing_pdf"
    assert result["corpus_write"] is False
    assert result["db_write"] is False
    assert result["auto_publish"] is False


def test_invalid_refresh_authority_fails_closed(monkeypatch, tmp_path: Path) -> None:
    _, _ = install_common(monkeypatch, tmp_path)

    def blocked(**kwargs):
        raise MODULE.SourceRefreshAuthorityError("tampered authority")

    monkeypatch.setattr(MODULE, "validate_authoritative_refresh", blocked)
    result = run(monkeypatch, tmp_path)
    assert result["result"] == "BLOCKED_SOURCE_DRIFT"
    assert result["reason"] == "source_refresh_authority_invalid:tampered authority"
    assert result["corpus_write"] is False
    assert result["db_write"] is False


def test_valid_refresh_authority_advances_to_missing_profile(monkeypatch, tmp_path: Path) -> None:
    family, _ = install_common(monkeypatch, tmp_path)
    scan = family / "scans" / SCAN_NAME
    scan.mkdir(parents=True)
    (scan / "summary.json").write_text(json.dumps({"schema_version": 1}) + "\n", encoding="utf-8")
    authority = {
        "authority_version": "lidl-source-refresh-authority-v1",
        "authority_sha256": "a" * 64,
        "parser_input_identity_sha256": LIVE_INPUT,
        "product_binding_sha256": "b" * 64,
        "product_binding_count": 140,
        "product_link_count": 141,
        "scan_name": SCAN_NAME,
        "scan_tree_sha256": "c" * 64,
        "scan_time_raw_sha256": LIVE_RAW_SHA,
        "current_live_raw_sha256": "4" * 64,
        "raw_sha_is_provenance_only": True,
        "source_review_sha256": "5" * 64,
    }
    monkeypatch.setattr(MODULE, "validate_authoritative_refresh", lambda **kwargs: authority)
    monkeypatch.setattr(
        MODULE,
        "require_weekly_target_profile",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            MODULE.WeeklyTargetProfileGate("WAIT_PROFILE", "review-profile.json is missing")
        ),
    )

    result = run(monkeypatch, tmp_path)
    assert result["result"] == "WAIT_PROFILE"
    assert result["reason"] == "review-profile.json is missing"
    assert result["corpus_match"]["scan"] == SCAN_NAME
    assert result["corpus_match"]["parser_input_changed"] is False
    assert result["source"]["source_refresh_authority"] == authority
    assert result["corpus_write"] is False
    assert result["db_write"] is False
    assert result["auto_publish"] is False
