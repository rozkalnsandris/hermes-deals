from __future__ import annotations

import argparse
from copy import deepcopy
from hashlib import sha256
import json
from pathlib import Path
import sys
from typing import Any, Mapping

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
TOOLS = ROOT / "tools"
for path in (BACKEND, TOOLS):
    if str(path) not in sys.path:
        sys.path.insert(0, str(path))

from app.edeka_source_card_accounting import (  # noqa: E402
    audit_edeka_source_card_manifest,
)
import edeka_candidate_provenance as gate_c  # noqa: E402
import edeka_live_provenance_bridge as base_bridge  # noqa: E402


ACCOUNTED_BRIDGE_SCHEMA_VERSION = 1


def _stable_json_bytes(value: object) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _sha256(value: object) -> str:
    return sha256(_stable_json_bytes(value)).hexdigest()


def _safe_cycle_manifest(cycle_dir: Path) -> tuple[Path, str]:
    root = cycle_dir.expanduser().resolve()
    if cycle_dir.is_symlink() or not root.is_dir():
        raise ValueError("EDEKA accounted provenance cycle directory is unsafe")
    cycle_path = root / "cycle-evidence.json"
    if cycle_path.is_symlink() or not cycle_path.is_file():
        raise ValueError("EDEKA accounted provenance cycle evidence is missing")
    cycle = json.loads(cycle_path.read_text(encoding="utf-8"))
    if not isinstance(cycle, dict):
        raise ValueError("EDEKA accounted provenance cycle evidence is invalid")
    files = cycle.get("files")
    if not isinstance(files, Mapping):
        raise ValueError("EDEKA accounted provenance files are missing")
    record = files.get("manifest")
    if not isinstance(record, Mapping):
        raise ValueError("EDEKA accounted provenance manifest record is missing")
    relative_value = record.get("path")
    expected_sha = record.get("sha256")
    if not isinstance(relative_value, str) or not relative_value:
        raise ValueError("EDEKA accounted provenance manifest path is missing")
    if not isinstance(expected_sha, str) or len(expected_sha) != 64:
        raise ValueError("EDEKA accounted provenance manifest SHA is invalid")
    relative = Path(relative_value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError("EDEKA accounted provenance manifest path is unsafe")
    manifest_path = (root / relative).resolve()
    try:
        manifest_path.relative_to(root)
    except ValueError as exc:
        raise ValueError("EDEKA accounted provenance manifest escaped cycle") from exc
    if manifest_path.is_symlink() or not manifest_path.is_file():
        raise ValueError("EDEKA accounted provenance manifest is not a regular file")
    if sha256(manifest_path.read_bytes()).hexdigest() != expected_sha:
        raise ValueError("EDEKA accounted provenance manifest SHA mismatch")
    return manifest_path, expected_sha


def augment_live_candidate_provenance(
    base: Mapping[str, Any],
    accounting: Mapping[str, Any],
) -> dict[str, Any]:
    payload = deepcopy(dict(base))
    manifest = payload.get("manifest")
    candidates = payload.get("candidates")
    live_evidence = payload.get("live_evidence")
    summary = accounting.get("summary")
    excluded_cards = accounting.get("excluded_cards")
    source = accounting.get("source")
    if not isinstance(manifest, dict):
        raise ValueError("EDEKA accounted provenance manifest is missing")
    if not isinstance(candidates, list):
        raise ValueError("EDEKA accounted provenance candidates are missing")
    if not isinstance(live_evidence, dict):
        raise ValueError("EDEKA accounted provenance live evidence is missing")
    if not isinstance(summary, Mapping):
        raise ValueError("EDEKA source-card accounting summary is missing")
    if not isinstance(excluded_cards, list):
        raise ValueError("EDEKA source-card accounting exclusions are missing")
    if not isinstance(source, Mapping):
        raise ValueError("EDEKA source-card accounting source is missing")

    source_card_count = summary.get("source_card_count")
    parsed_offer_count = summary.get("parsed_offer_count")
    excluded_count = summary.get("excluded_count")
    if not all(isinstance(value, int) for value in (
        source_card_count,
        parsed_offer_count,
        excluded_count,
    )):
        raise ValueError("EDEKA source-card accounting counts are invalid")
    if source_card_count != parsed_offer_count + excluded_count:
        raise ValueError("EDEKA source-card accounting count invariant failed")
    if summary.get("accounting_complete") is not True:
        raise ValueError("EDEKA source-card accounting is incomplete")
    if summary.get("unexplained_source_card_loss") is not False:
        raise ValueError("EDEKA source-card accounting reports unexplained loss")

    parsed_ids = {str(row.get("candidate_id")) for row in candidates}
    if len(parsed_ids) != len(candidates) or "None" in parsed_ids:
        raise ValueError("EDEKA accounted provenance base candidate IDs are invalid")
    if len(parsed_ids) != parsed_offer_count:
        raise ValueError("EDEKA accounted provenance parsed count mismatch")

    snapshot_id = live_evidence.get("source_snapshot_id")
    if source.get("snapshot_id") != snapshot_id:
        raise ValueError("EDEKA accounted provenance snapshot mismatch")
    if accounting.get("manifest_sha256") != manifest.get("manifest_sha256"):
        raise ValueError("EDEKA accounted provenance manifest binding mismatch")
    if accounting.get("raw_html_sha256") != manifest.get("source_sha256"):
        raise ValueError("EDEKA accounted provenance raw source binding mismatch")
    if accounting.get("parser_version") != manifest.get("parser_identity"):
        raise ValueError("EDEKA accounted provenance parser identity mismatch")

    excluded_ids: set[str] = set()
    for raw in excluded_cards:
        if not isinstance(raw, Mapping):
            raise ValueError("EDEKA accounted provenance exclusion must be an object")
        source_offer_id = raw.get("source_offer_id")
        dialog_id = raw.get("dialog_id")
        route = raw.get("route")
        reason = raw.get("exclusion_reason")
        if not isinstance(source_offer_id, str) or not source_offer_id:
            raise ValueError("EDEKA accounted provenance excluded ID is missing")
        if source_offer_id in parsed_ids or source_offer_id in excluded_ids:
            raise ValueError("EDEKA accounted provenance candidate IDs overlap")
        if dialog_id != f"dialog-angebot-{source_offer_id}":
            raise ValueError("EDEKA accounted provenance dialog binding mismatch")
        if route != "excluded" or not isinstance(reason, str) or not reason:
            raise ValueError("EDEKA accounted provenance exclusion route is invalid")
        excluded_ids.add(source_offer_id)
        candidates.append(
            {
                "candidate_id": source_offer_id,
                "campaign_id": manifest.get("campaign_id"),
                "source_sha256": manifest.get("source_sha256"),
                "manifest_sha256": manifest.get("manifest_sha256"),
                "parser_identity": manifest.get("parser_identity"),
                "page_number": 1,
                "card_id": dialog_id,
                "route": "excluded",
                "ambiguous": False,
                "provenance_complete": True,
                "exclusion_reason": reason,
            }
        )

    if len(excluded_ids) != excluded_count:
        raise ValueError("EDEKA accounted provenance excluded count mismatch")
    candidates.sort(key=lambda row: str(row.get("candidate_id")))

    live_evidence["source_card_accounting_schema_version"] = (
        ACCOUNTED_BRIDGE_SCHEMA_VERSION
    )
    live_evidence["source_card_count"] = source_card_count
    live_evidence["parsed_offer_count"] = parsed_offer_count
    live_evidence["excluded_count"] = excluded_count
    live_evidence["source_card_accounting_sha256"] = accounting.get(
        "report_sha256"
    )
    live_evidence["unexplained_source_card_loss"] = False
    payload["accounted_candidate_count"] = source_card_count
    payload["source_card_accounting_sha256"] = accounting.get("report_sha256")

    validated = gate_c.validate_candidate_provenance(payload)
    if validated["candidate_count"] != source_card_count:
        raise ValueError("EDEKA accounted Gate C candidate count mismatch")
    if validated["route_counts"].get("excluded") != excluded_count:
        raise ValueError("EDEKA accounted Gate C excluded count mismatch")
    return payload


def build_accounted_live_candidate_provenance(cycle_dir: Path) -> dict[str, Any]:
    base = base_bridge.build_live_candidate_provenance(cycle_dir)
    manifest_path, manifest_sha = _safe_cycle_manifest(cycle_dir)
    accounting = audit_edeka_source_card_manifest(manifest_path, manifest_sha)
    return augment_live_candidate_provenance(base, accounting)


def write_accounted_live_candidate_provenance(
    output_file: Path,
    payload: Mapping[str, Any],
) -> None:
    target = output_file.expanduser().resolve()
    target.parent.mkdir(parents=True, exist_ok=True)
    data = _stable_json_bytes(payload) + b"\n"
    if target.exists():
        if target.is_symlink() or not target.is_file():
            raise ValueError("EDEKA accounted provenance output path is unsafe")
        if target.read_bytes() != data:
            raise ValueError(
                "refusing to replace different accounted provenance evidence"
            )
        return
    with target.open("xb") as handle:
        handle.write(data)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Derive Gate C provenance with explicit EDEKA source-card exclusions"
    )
    parser.add_argument("--cycle-dir", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    try:
        payload = build_accounted_live_candidate_provenance(args.cycle_dir)
        write_accounted_live_candidate_provenance(args.output, payload)
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(
        json.dumps(
            {
                "result": "pass",
                "output": str(args.output),
                "accounted_candidate_count": payload["accounted_candidate_count"],
                "source_card_accounting_sha256": payload[
                    "source_card_accounting_sha256"
                ],
                "payload_sha256": _sha256(payload),
            },
            ensure_ascii=False,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
