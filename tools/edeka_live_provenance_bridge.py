from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sqlite3
import sys
from typing import Any, Mapping
from urllib.parse import quote

EXPECTED_PUBLIC_MARKET_CODE = "071897"
EXPECTED_SOURCE_MARKET_ID = "587881"
EXPECTED_SCOPE = "family_primary_edeka"
EXPECTED_STORE_NAME = "EDEKA Patzer"
EXPECTED_SOURCE_URL = "https://www.edeka.de/maerkte/071897/angebote/"
EXPECTED_AUDIT_TYPE = "edeka_single_shadow_cycle_capture"
REGIONAL_STRATEGY = "edeka_regional_source_manifest_v1"
CANDIDATE_STRATEGY = "edeka_candidate_provenance_v1"


class EdekaLiveProvenanceBridgeError(ValueError):
    pass


def _stable_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256_file(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load_json(path: Path, label: str) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise EdekaLiveProvenanceBridgeError(f"{label} must be a regular file")
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EdekaLiveProvenanceBridgeError(f"invalid {label}") from exc
    if not isinstance(payload, dict):
        raise EdekaLiveProvenanceBridgeError(f"{label} root must be an object")
    return payload


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EdekaLiveProvenanceBridgeError(f"{label} must be an object")
    return value


def _nonempty_string(value: Any, label: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise EdekaLiveProvenanceBridgeError(f"{label} must be a non-empty string")
    return value.strip()


def _nonnegative_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise EdekaLiveProvenanceBridgeError(f"{label} must be an integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise EdekaLiveProvenanceBridgeError(f"{label} must be an integer") from exc
    if parsed < 0:
        raise EdekaLiveProvenanceBridgeError(f"{label} must not be negative")
    return parsed


def _resolve_evidence_file(
    cycle_dir: Path,
    record: Any,
    label: str,
) -> Path:
    data = _mapping(record, f"files.{label}")
    relative = Path(_nonempty_string(data.get("path"), f"files.{label}.path"))
    if relative.is_absolute() or ".." in relative.parts:
        raise EdekaLiveProvenanceBridgeError(f"files.{label}.path is unsafe")
    root = cycle_dir.resolve()
    target = (root / relative).resolve()
    try:
        target.relative_to(root)
    except ValueError as exc:
        raise EdekaLiveProvenanceBridgeError(
            f"files.{label}.path escaped the cycle directory"
        ) from exc
    if target.is_symlink() or not target.is_file():
        raise EdekaLiveProvenanceBridgeError(f"files.{label} is not a regular file")
    expected_sha = _nonempty_string(data.get("sha256"), f"files.{label}.sha256")
    actual_sha = _sha256_file(target)
    if actual_sha != expected_sha:
        raise EdekaLiveProvenanceBridgeError(
            f"files.{label} sha256 mismatch: expected={expected_sha} actual={actual_sha}"
        )
    expected_bytes = _nonnegative_int(data.get("bytes"), f"files.{label}.bytes")
    if target.stat().st_size != expected_bytes:
        raise EdekaLiveProvenanceBridgeError(f"files.{label} byte length mismatch")
    return target


def _verify_cycle_evidence_hash(cycle: Mapping[str, Any]) -> str:
    expected = _nonempty_string(cycle.get("evidence_sha256"), "evidence_sha256")
    unsigned = deepcopy(dict(cycle))
    unsigned.pop("evidence_sha256", None)
    actual = sha256(_stable_json_bytes(unsigned)).hexdigest()
    if actual != expected:
        raise EdekaLiveProvenanceBridgeError(
            f"cycle evidence hash mismatch: expected={expected} actual={actual}"
        )
    return expected


def _campaign_id(source: Mapping[str, Any]) -> str:
    return "-".join(
        (
            "edeka",
            _nonempty_string(source.get("public_market_id"), "source.public_market_id"),
            _nonempty_string(source.get("valid_from"), "source.valid_from"),
            _nonempty_string(source.get("valid_until"), "source.valid_until"),
            _nonempty_string(source.get("raw_html_sha256"), "source.raw_html_sha256")[:16],
        )
    )


def _readonly_sqlite(path: Path) -> sqlite3.Connection:
    uri = f"file:{quote(str(path.resolve()))}?mode=ro&immutable=1"
    return sqlite3.connect(uri, uri=True)


def build_live_candidate_provenance(cycle_dir: Path) -> dict[str, Any]:
    root = cycle_dir.expanduser().resolve()
    if cycle_dir.is_symlink() or not root.is_dir():
        raise EdekaLiveProvenanceBridgeError("cycle directory must be a regular directory")

    cycle = _load_json(root / "cycle-evidence.json", "cycle evidence")
    if cycle.get("schema_version") != 1:
        raise EdekaLiveProvenanceBridgeError("unsupported cycle schema_version")
    if cycle.get("audit_type") != EXPECTED_AUDIT_TYPE or cycle.get("result") != "pass":
        raise EdekaLiveProvenanceBridgeError("cycle is not a passing EDEKA shadow capture")
    cycle_evidence_sha256 = _verify_cycle_evidence_hash(cycle)

    source = _mapping(cycle.get("source"), "source")
    expected_source_values = {
        "source_chain": "edeka",
        "scope": EXPECTED_SCOPE,
        "public_market_id": EXPECTED_PUBLIC_MARKET_CODE,
        "internal_market_id": EXPECTED_SOURCE_MARKET_ID,
        "store_name": EXPECTED_STORE_NAME,
        "source_url": EXPECTED_SOURCE_URL,
    }
    for field, expected in expected_source_values.items():
        if source.get(field) != expected:
            raise EdekaLiveProvenanceBridgeError(
                f"source.{field} mismatch: expected={expected!r} actual={source.get(field)!r}"
            )

    source_snapshot_id = _nonempty_string(source.get("snapshot_id"), "source.snapshot_id")
    valid_from = _nonempty_string(source.get("valid_from"), "source.valid_from")
    valid_until = _nonempty_string(source.get("valid_until"), "source.valid_until")
    parser_identity = _nonempty_string(source.get("parser_version"), "source.parser_version")
    manifest_sha256 = _nonempty_string(source.get("manifest_sha256"), "source.manifest_sha256")
    source_sha256 = _nonempty_string(source.get("raw_html_sha256"), "source.raw_html_sha256")

    safety = _mapping(cycle.get("safety"), "safety")
    for key in (
        "production_deployment",
        "production_database_write",
        "review_write",
        "publication_write",
        "scheduler_activation",
    ):
        if safety.get(key) is not False:
            raise EdekaLiveProvenanceBridgeError(f"safety.{key} must be false")

    persistence = _mapping(cycle.get("isolated_persistence"), "isolated_persistence")
    if persistence.get("database_engine") != "sqlite":
        raise EdekaLiveProvenanceBridgeError("isolated persistence must use sqlite")
    if persistence.get("production_database_write") is not False:
        raise EdekaLiveProvenanceBridgeError("production database write must remain false")
    offer_count = _nonnegative_int(persistence.get("parsed_offer_count"), "parsed_offer_count")
    first_delta = _nonnegative_int(
        persistence.get("first_write_offer_delta"), "first_write_offer_delta"
    )
    replay_delta = _nonnegative_int(
        persistence.get("same_snapshot_replay_offer_delta"),
        "same_snapshot_replay_offer_delta",
    )
    persisted_count = _nonnegative_int(
        persistence.get("persisted_offer_count"), "persisted_offer_count"
    )
    snapshot_count = _nonnegative_int(
        persistence.get("source_snapshot_count"), "source_snapshot_count"
    )
    if offer_count <= 0 or first_delta != offer_count or persisted_count != offer_count:
        raise EdekaLiveProvenanceBridgeError("isolated persistence offer counts do not bind")
    if replay_delta != 0 or snapshot_count != 1:
        raise EdekaLiveProvenanceBridgeError("isolated replay/snapshot gate failed")

    files = _mapping(cycle.get("files"), "files")
    manifest_path = _resolve_evidence_file(root, files.get("manifest"), "manifest")
    raw_html_path = _resolve_evidence_file(root, files.get("raw_html"), "raw_html")
    normalization_path = _resolve_evidence_file(
        root, files.get("normalization_report"), "normalization_report"
    )
    database_path = _resolve_evidence_file(
        root, files.get("isolated_database"), "isolated_database"
    )
    if _sha256_file(manifest_path) != manifest_sha256:
        raise EdekaLiveProvenanceBridgeError("source manifest hash is not bound to cycle evidence")
    if _sha256_file(raw_html_path) != source_sha256:
        raise EdekaLiveProvenanceBridgeError("raw HTML hash is not bound to cycle evidence")

    normalization = _load_json(normalization_path, "normalization report")
    normalization_source = _mapping(normalization.get("source"), "normalization.source")
    for field in (
        "public_market_id",
        "internal_market_id",
        "scope",
        "source_url",
        "snapshot_id",
        "valid_from",
        "valid_until",
        "parser_version",
    ):
        if normalization_source.get(field) != source.get(field):
            raise EdekaLiveProvenanceBridgeError(
                f"normalization.source.{field} is not bound to cycle source"
            )

    summary = _mapping(normalization.get("summary"), "normalization.summary")
    normalized_offer_count = _nonnegative_int(summary.get("offer_count"), "summary.offer_count")
    resolved_count = _nonnegative_int(summary.get("resolved_count"), "summary.resolved_count")
    review_count = _nonnegative_int(
        summary.get("review_required_count"), "summary.review_required_count"
    )
    if normalized_offer_count != offer_count or resolved_count + review_count != offer_count:
        raise EdekaLiveProvenanceBridgeError("normalization counts do not bind to parsed offers")

    cycle_normalization = _mapping(cycle.get("normalization"), "normalization")
    for key, actual in (
        ("resolved_count", resolved_count),
        ("review_required_count", review_count),
        ("rows_sha256", summary.get("rows_sha256")),
        ("report_sha256", normalization.get("report_sha256")),
    ):
        if cycle_normalization.get(key) != actual:
            raise EdekaLiveProvenanceBridgeError(
                f"cycle normalization {key} is not bound to normalization report"
            )

    rows = normalization.get("rows")
    if not isinstance(rows, list) or len(rows) != offer_count:
        raise EdekaLiveProvenanceBridgeError("normalization rows do not match offer count")
    normalization_status: dict[str, str] = {}
    for row in rows:
        data = _mapping(row, "normalization row")
        source_offer_id = _nonempty_string(data.get("source_offer_id"), "source_offer_id")
        if source_offer_id in normalization_status:
            raise EdekaLiveProvenanceBridgeError("duplicate normalization source_offer_id")
        status = _nonempty_string(data.get("status"), "normalization status")
        if status not in {"resolved", "review_required"}:
            raise EdekaLiveProvenanceBridgeError(f"unsupported normalization status: {status}")
        normalization_status[source_offer_id] = status

    try:
        connection = _readonly_sqlite(database_path)
    except sqlite3.Error as exc:
        raise EdekaLiveProvenanceBridgeError("unable to open isolated sqlite read-only") from exc
    try:
        cursor = connection.execute(
            "SELECT source_offer_id, source_store_external_id, source_store_name, "
            "source_url, snapshot_id, parser_version, valid_from, valid_until, raw_payload "
            "FROM offer_candidates ORDER BY source_offer_id"
        )
        database_rows = cursor.fetchall()
    except sqlite3.Error as exc:
        raise EdekaLiveProvenanceBridgeError("unable to read offer_candidates") from exc
    finally:
        connection.close()

    if len(database_rows) != offer_count:
        raise EdekaLiveProvenanceBridgeError("isolated database rows do not match offer count")

    campaign_id = _campaign_id(source)
    candidates: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    for (
        raw_offer_id,
        public_market_id,
        store_name,
        source_url,
        raw_snapshot_id,
        parser_version,
        raw_valid_from,
        raw_valid_until,
        raw_payload_text,
    ) in database_rows:
        source_offer_id = _nonempty_string(raw_offer_id, "database source_offer_id")
        if source_offer_id in seen_ids:
            raise EdekaLiveProvenanceBridgeError("duplicate database source_offer_id")
        seen_ids.add(source_offer_id)
        if source_offer_id not in normalization_status:
            raise EdekaLiveProvenanceBridgeError(
                f"database offer missing normalization row: {source_offer_id}"
            )
        if public_market_id != EXPECTED_PUBLIC_MARKET_CODE or store_name != EXPECTED_STORE_NAME:
            raise EdekaLiveProvenanceBridgeError("database market identity mismatch")
        normalized_snapshot_id = str(raw_snapshot_id).replace("-", "").lower()
        expected_snapshot_id = source_snapshot_id.replace("-", "").lower()
        if source_url != EXPECTED_SOURCE_URL or normalized_snapshot_id != expected_snapshot_id:
            raise EdekaLiveProvenanceBridgeError("database source/snapshot identity mismatch")
        if parser_version != parser_identity:
            raise EdekaLiveProvenanceBridgeError("database parser identity mismatch")
        if str(raw_valid_from) != valid_from or str(raw_valid_until) != valid_until:
            raise EdekaLiveProvenanceBridgeError("database campaign window mismatch")
        try:
            raw_payload = json.loads(raw_payload_text)
        except (TypeError, json.JSONDecodeError) as exc:
            raise EdekaLiveProvenanceBridgeError("invalid database raw_payload") from exc
        payload = _mapping(raw_payload, "database raw_payload")
        if payload.get("public_market_id") != EXPECTED_PUBLIC_MARKET_CODE:
            raise EdekaLiveProvenanceBridgeError("raw payload public market mismatch")
        if payload.get("internal_market_id") != EXPECTED_SOURCE_MARKET_ID:
            raise EdekaLiveProvenanceBridgeError("raw payload internal market mismatch")
        expected_fragment = f"#angebot-{source_offer_id}"
        expected_dialog = f"dialog-angebot-{source_offer_id}"
        if payload.get("fragment_href") != expected_fragment:
            raise EdekaLiveProvenanceBridgeError("raw payload offer fragment mismatch")
        if payload.get("dialog_id") != expected_dialog:
            raise EdekaLiveProvenanceBridgeError("raw payload dialog provenance mismatch")

        status = normalization_status[source_offer_id]
        route = "automatic_candidate" if status == "resolved" else "review_required"
        candidates.append(
            {
                "candidate_id": source_offer_id,
                "campaign_id": campaign_id,
                "source_sha256": source_sha256,
                "manifest_sha256": manifest_sha256,
                "parser_identity": parser_identity,
                "page_number": 1,
                "card_id": expected_dialog,
                "route": route,
                "ambiguous": route == "review_required",
                "provenance_complete": True,
            }
        )

    if set(normalization_status) != seen_ids:
        raise EdekaLiveProvenanceBridgeError("normalization/database offer-id sets differ")

    regional_manifest = {
        "schema_version": 1,
        "strategy": REGIONAL_STRATEGY,
        "retailer": "edeka",
        "public_market_code": EXPECTED_PUBLIC_MARKET_CODE,
        "source_market_id": EXPECTED_SOURCE_MARKET_ID,
        "scope": EXPECTED_SCOPE,
        "campaign_id": campaign_id,
        "valid_from": valid_from,
        "valid_to": valid_until,
        "source_url": EXPECTED_SOURCE_URL,
        "source_sha256": source_sha256,
        "manifest_sha256": manifest_sha256,
        "parser_identity": parser_identity,
        "source_state": "review_pending" if review_count else "available",
        "fallback_allowed": False,
        "ambiguous_rows_route": "review_required",
        "database_write_authorized": False,
        "review_write_authorized": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "production_apply_authorized": False,
    }

    return {
        "schema_version": 1,
        "strategy": CANDIDATE_STRATEGY,
        "manifest": regional_manifest,
        "candidates": candidates,
        "database_write_authorized": False,
        "review_write_authorized": False,
        "automatic_approval_enabled": False,
        "automatic_publish_enabled": False,
        "production_apply_authorized": False,
        "live_evidence": {
            "evidence_kind": "edeka_html_offer_card_provenance",
            "source_snapshot_id": source_snapshot_id,
            "cycle_evidence_sha256": cycle_evidence_sha256,
            "raw_html_sha256": source_sha256,
            "manifest_sha256": manifest_sha256,
            "parser_identity": parser_identity,
            "normalizer_version": normalization.get("normalizer_version"),
            "normalization_rows_sha256": summary.get("rows_sha256"),
            "offer_count": offer_count,
            "automatic_candidate_count": resolved_count,
            "review_required_count": review_count,
            "same_snapshot_replay_offer_delta": replay_delta,
            "source_document_kind": "html_offer_cards",
            "page_number_semantics": "single_html_document_compatibility_ordinal",
            "production_database_write": False,
            "production_deployment": False,
            "scheduler_activation": False,
        },
    }


def write_live_candidate_provenance(output_file: Path, payload: Mapping[str, Any]) -> None:
    target = output_file.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = _stable_json_bytes(payload) + b"\n"
    if target.exists():
        if target.is_symlink() or not target.is_file():
            raise EdekaLiveProvenanceBridgeError("output path is unsafe")
        if target.read_bytes() != data:
            raise EdekaLiveProvenanceBridgeError(
                "refusing to replace different provenance evidence"
            )
        return
    with target.open("xb") as handle:
        handle.write(data)
        handle.flush()


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Bridge an immutable EDEKA shadow cycle into Gate B/C live provenance evidence"
        )
    )
    parser.add_argument("--cycle-dir", type=Path, required=True)
    parser.add_argument("--output-file", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = build_live_candidate_provenance(args.cycle_dir)
        write_live_candidate_provenance(args.output_file, payload)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    live = payload["live_evidence"]
    print(
        json.dumps(
            {
                "result": "pass",
                "campaign_id": payload["manifest"]["campaign_id"],
                "candidate_count": len(payload["candidates"]),
                "automatic_candidate_count": live["automatic_candidate_count"],
                "review_required_count": live["review_required_count"],
                "same_snapshot_replay_offer_delta": live[
                    "same_snapshot_replay_offer_delta"
                ],
                "output_file": str(args.output_file.expanduser().resolve()),
                "output_sha256": _sha256_file(args.output_file.expanduser().resolve()),
                "production_database_write": False,
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
