from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import edeka_candidate_provenance as gate_c  # noqa: E402
import edeka_live_provenance_bridge as bridge  # noqa: E402


SNAPSHOT_ID = "11111111-2222-3333-4444-555555555555"
VALID_FROM = "2026-08-03"
VALID_UNTIL = "2026-08-08"


def _stable_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _file_record(path: Path, root: Path) -> dict[str, object]:
    return {
        "path": path.relative_to(root).as_posix(),
        "sha256": _sha256_file(path),
        "bytes": path.stat().st_size,
    }


def _write_json(path: Path, payload: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_stable_json_bytes(payload) + b"\n")


def _make_cycle(
    tmp_path: Path,
    *,
    bad_dialog: bool = False,
    unsafe_production_write: bool = False,
    duplicate_normalization_id: bool = False,
) -> Path:
    root = tmp_path / "cycle"
    raw_dir = root / "raw" / "edeka"
    raw_dir.mkdir(parents=True)

    raw_html = raw_dir / "071897-offers.html"
    raw_html.write_text("<html>EDEKA Patzer fixture</html>\n", encoding="utf-8")
    raw_html_sha = _sha256_file(raw_html)

    source_manifest = raw_dir / "071897-offers-manifest.json"
    _write_json(
        source_manifest,
        {
            "schema_version": 1,
            "public_market_id": "071897",
            "internal_market_id": "587881",
            "valid_from": VALID_FROM,
            "valid_until": VALID_UNTIL,
            "raw_html_sha256": raw_html_sha,
        },
    )
    manifest_sha = _sha256_file(source_manifest)

    offer_ids = [
        "aaaaaaaa-1111-2222-3333-444444444444",
        "bbbbbbbb-1111-2222-3333-444444444444",
    ]
    database = root / "shadow.sqlite3"
    connection = sqlite3.connect(database)
    try:
        connection.execute(
            "CREATE TABLE offer_candidates ("
            "source_offer_id TEXT NOT NULL, "
            "source_store_external_id TEXT NOT NULL, "
            "source_store_name TEXT NOT NULL, "
            "source_url TEXT NOT NULL, "
            "snapshot_id TEXT NOT NULL, "
            "parser_version TEXT NOT NULL, "
            "valid_from TEXT NOT NULL, "
            "valid_until TEXT NOT NULL, "
            "raw_payload TEXT NOT NULL"
            ")"
        )
        for index, offer_id in enumerate(offer_ids):
            dialog_id = f"dialog-angebot-{offer_id}"
            if bad_dialog and index == 0:
                dialog_id = "dialog-angebot-wrong"
            raw_payload = {
                "public_market_id": "071897",
                "internal_market_id": "587881",
                "fragment_href": f"#angebot-{offer_id}",
                "dialog_id": dialog_id,
            }
            connection.execute(
                "INSERT INTO offer_candidates VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    offer_id,
                    "071897",
                    "EDEKA Patzer",
                    "https://www.edeka.de/maerkte/071897/angebote/",
                    SNAPSHOT_ID.replace("-", ""),
                    "edeka-v1",
                    VALID_FROM,
                    VALID_UNTIL,
                    json.dumps(raw_payload, sort_keys=True),
                ),
            )
        connection.commit()
    finally:
        connection.close()

    normalization_ids = list(offer_ids)
    if duplicate_normalization_id:
        normalization_ids[1] = normalization_ids[0]
    normalization_rows = [
        {"source_offer_id": normalization_ids[0], "status": "resolved"},
        {"source_offer_id": normalization_ids[1], "status": "review_required"},
    ]
    rows_sha = sha256(_stable_json_bytes(normalization_rows)).hexdigest()
    report_sha = sha256(b"normalizer-v1.2-fixture").hexdigest()
    normalization = {
        "schema_version": 1,
        "audit_type": "edeka_package_normalization_coverage",
        "normalizer_version": "normalizer-v1.2",
        "report_sha256": report_sha,
        "source": {
            "public_market_id": "071897",
            "internal_market_id": "587881",
            "scope": "family_primary_edeka",
            "source_url": "https://www.edeka.de/maerkte/071897/angebote/",
            "snapshot_id": SNAPSHOT_ID,
            "valid_from": VALID_FROM,
            "valid_until": VALID_UNTIL,
            "parser_version": "edeka-v1",
        },
        "summary": {
            "offer_count": 2,
            "resolved_count": 1,
            "review_required_count": 1,
            "rows_sha256": rows_sha,
        },
        "rows": normalization_rows,
    }
    normalization_path = root / "normalization-report.json"
    _write_json(normalization_path, normalization)

    cycle = {
        "schema_version": 1,
        "audit_type": "edeka_single_shadow_cycle_capture",
        "result": "pass",
        "source": {
            "source_chain": "edeka",
            "scope": "family_primary_edeka",
            "public_market_id": "071897",
            "internal_market_id": "587881",
            "store_name": "EDEKA Patzer",
            "source_url": "https://www.edeka.de/maerkte/071897/angebote/",
            "snapshot_id": SNAPSHOT_ID,
            "valid_from": VALID_FROM,
            "valid_until": VALID_UNTIL,
            "parser_version": "edeka-v1",
            "manifest_sha256": manifest_sha,
            "raw_html_sha256": raw_html_sha,
        },
        "normalization": {
            "normalizer_version": "normalizer-v1.2",
            "resolved_count": 1,
            "review_required_count": 1,
            "rows_sha256": rows_sha,
            "report_sha256": report_sha,
        },
        "isolated_persistence": {
            "database_engine": "sqlite",
            "source_snapshot_count": 1,
            "parsed_offer_count": 2,
            "first_write_offer_delta": 2,
            "same_snapshot_replay_offer_delta": 0,
            "persisted_offer_count": 2,
            "production_database_write": False,
        },
        "safety": {
            "production_deployment": False,
            "production_database_write": unsafe_production_write,
            "review_write": False,
            "publication_write": False,
            "scheduler_activation": False,
        },
        "files": {
            "manifest": _file_record(source_manifest, root),
            "raw_html": _file_record(raw_html, root),
            "normalization_report": _file_record(normalization_path, root),
            "isolated_database": _file_record(database, root),
        },
    }
    cycle["evidence_sha256"] = sha256(_stable_json_bytes(cycle)).hexdigest()
    _write_json(root / "cycle-evidence.json", cycle)
    return root


def test_live_bridge_produces_gate_c_compatible_html_card_provenance(
    tmp_path: Path,
) -> None:
    cycle_dir = _make_cycle(tmp_path)

    payload = bridge.build_live_candidate_provenance(cycle_dir)
    validated = gate_c.validate_candidate_provenance(payload)

    assert validated["candidate_count"] == 2
    assert validated["route_counts"] == {
        "automatic_candidate": 1,
        "excluded": 0,
        "review_required": 1,
    }
    assert validated["all_candidates_provenance_bound"] is True
    assert validated["promotion_ready"] is False
    assert payload["manifest"]["public_market_code"] == "071897"
    assert payload["manifest"]["source_market_id"] == "587881"
    assert payload["manifest"]["source_state"] == "review_pending"
    assert payload["live_evidence"]["source_document_kind"] == "html_offer_cards"
    assert payload["live_evidence"]["page_number_semantics"] == (
        "single_html_document_compatibility_ordinal"
    )
    assert {row["page_number"] for row in payload["candidates"]} == {1}
    assert all(
        row["card_id"] == f"dialog-angebot-{row['candidate_id']}"
        for row in payload["candidates"]
    )


def test_live_bridge_fails_closed_on_raw_html_hash_drift(tmp_path: Path) -> None:
    cycle_dir = _make_cycle(tmp_path)
    raw_html = cycle_dir / "raw" / "edeka" / "071897-offers.html"
    raw_html.write_text("tampered", encoding="utf-8")

    with pytest.raises(bridge.EdekaLiveProvenanceBridgeError, match="sha256 mismatch"):
        bridge.build_live_candidate_provenance(cycle_dir)


def test_live_bridge_fails_closed_on_dialog_provenance_drift(tmp_path: Path) -> None:
    cycle_dir = _make_cycle(tmp_path, bad_dialog=True)

    with pytest.raises(
        bridge.EdekaLiveProvenanceBridgeError,
        match="dialog provenance mismatch",
    ):
        bridge.build_live_candidate_provenance(cycle_dir)


def test_live_bridge_fails_closed_on_duplicate_normalization_offer_id(
    tmp_path: Path,
) -> None:
    cycle_dir = _make_cycle(tmp_path, duplicate_normalization_id=True)

    with pytest.raises(
        bridge.EdekaLiveProvenanceBridgeError,
        match="duplicate normalization source_offer_id",
    ):
        bridge.build_live_candidate_provenance(cycle_dir)


def test_live_bridge_fails_closed_if_production_write_is_claimed(tmp_path: Path) -> None:
    cycle_dir = _make_cycle(tmp_path, unsafe_production_write=True)

    with pytest.raises(
        bridge.EdekaLiveProvenanceBridgeError,
        match="safety.production_database_write must be false",
    ):
        bridge.build_live_candidate_provenance(cycle_dir)


def test_live_bridge_output_is_idempotent_but_refuses_different_replacement(
    tmp_path: Path,
) -> None:
    cycle_dir = _make_cycle(tmp_path)
    payload = bridge.build_live_candidate_provenance(cycle_dir)
    output = tmp_path / "out" / "live-provenance.json"

    bridge.write_live_candidate_provenance(output, payload)
    first = output.read_bytes()
    bridge.write_live_candidate_provenance(output, payload)
    assert output.read_bytes() == first

    changed = dict(payload)
    changed["production_apply_authorized"] = True
    with pytest.raises(
        bridge.EdekaLiveProvenanceBridgeError,
        match="refusing to replace different provenance evidence",
    ):
        bridge.write_live_candidate_provenance(output, changed)
