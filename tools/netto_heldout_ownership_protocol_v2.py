from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import re
from typing import Any, Mapping

from netto_heldout_ownership_protocol import (
    ACCEPTANCE,
    OWNERSHIP_CLASSES,
    PROTOCOL_NAME as BASE_PROTOCOL_NAME,
    acceptance_digest,
    validate_freeze_manifest,
    validate_freeze_receipt,
)
from netto_local_span_auto_single_candidate import (
    GRAPH_GAP_MULTIPLIER,
    MAX_COMPONENT_AREA_FRACTION,
    MIN_OWNED_NODE_FRACTION,
    STRATEGY as CANDIDATE_STRATEGY,
    payload_sha256,
)


PROTOCOL_NAME = "netto-heldout-ownership-v2"
SCHEMA_VERSION = 2
FORBIDDEN_HELDOUT_CAMPAIGNS = frozenset({"hz31_hasb_4", "hz32_hasb", "hz33_hasb"})
PARENT_REUSE_METRIC = "candidate_auto_single_prediction_unit_has_exactly_one_exclusive_parent_unit"

EXPECTED_CANDIDATE_CONFIG = {
    "graph_nodes": ["prediction_text_span", "prediction_price_anchor"],
    "graph_gap_multiplier": GRAPH_GAP_MULTIPLIER,
    "graph_local_scale": "page_median_positive_text_span_height",
    "graph_separator_contract": "netto_visual_geometry_shadow.separators_from_layout+separated",
    "minimum_owned_node_fraction": MIN_OWNED_NODE_FRACTION,
    "maximum_parent_area_fraction": MAX_COMPONENT_AREA_FRACTION,
    "requires_exactly_one_parent_unit": True,
    "requires_exactly_one_group_per_parent_unit": True,
}


class HeldoutV2Error(ValueError):
    pass


def _canonical_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")) + "\n").encode("utf-8")


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical_bytes(value)).hexdigest()


def _require_sha256(value: Any, label: str) -> str:
    text = str(value or "")
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise HeldoutV2Error(f"{label} must be a lowercase SHA256")
    return text


def _require_commit_sha(value: Any) -> str:
    text = str(value or "")
    if not re.fullmatch(r"[0-9a-f]{40}", text):
        raise HeldoutV2Error("candidate implementation commit must be an exact lowercase Git SHA")
    return text


def file_sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise HeldoutV2Error(f"input must be a regular non-symlink file: {path}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise HeldoutV2Error(f"input must be a regular non-symlink file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HeldoutV2Error(f"invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise HeldoutV2Error(f"JSON input must contain an object: {path}")
    return value


def _candidate_groups(candidate: Mapping[str, Any]) -> list[dict[str, Any]]:
    pages = candidate.get("pages")
    if not isinstance(pages, list):
        raise HeldoutV2Error("candidate pages are missing")
    rows: list[dict[str, Any]] = []
    seen: set[str] = set()
    for page in pages:
        if not isinstance(page, Mapping):
            raise HeldoutV2Error("candidate page must be an object")
        groups = page.get("groups")
        if not isinstance(groups, list):
            raise HeldoutV2Error("candidate page group list is missing")
        for raw in groups:
            if not isinstance(raw, dict):
                raise HeldoutV2Error("candidate group must be an object")
            unit_id = str(raw.get("prediction_unit_id") or "")
            if not unit_id or unit_id in seen:
                raise HeldoutV2Error("candidate prediction_unit_id must be globally unique")
            seen.add(unit_id)
            rows.append(raw)
    return rows


def automatic_candidate_parent_reuse_count(candidate: Mapping[str, Any]) -> int:
    """Count auto-single decisions that do not have one exclusive frozen parent.

    This is deliberately distinct from candidate.cross_parent_group_reuse_count,
    which counts any parser group whose owned atoms span multiple graph parents.
    The #459 reuse gate applies to automatic decisions: one automatic prediction
    unit must not be silently reused across multiple parent/cell units.
    """
    pages = candidate.get("pages")
    if not isinstance(pages, list):
        raise HeldoutV2Error("candidate pages are missing")
    parent_membership: dict[str, set[str]] = {}
    for page in pages:
        if not isinstance(page, Mapping):
            raise HeldoutV2Error("candidate page must be an object")
        parents = page.get("parent_units")
        if not isinstance(parents, list):
            raise HeldoutV2Error("candidate parent units are missing")
        for parent in parents:
            if not isinstance(parent, Mapping):
                raise HeldoutV2Error("candidate parent unit must be an object")
            parent_id = str(parent.get("parent_unit_id") or "")
            if not parent_id or parent_id in parent_membership:
                raise HeldoutV2Error("candidate parent_unit_id must be globally unique")
            units = parent.get("prediction_unit_ids")
            if not isinstance(units, list):
                raise HeldoutV2Error("parent prediction_unit_ids must be a list")
            parent_membership[parent_id] = {str(unit) for unit in units}

    reused = 0
    for group in _candidate_groups(candidate):
        if group.get("candidate_auto_single") is not True:
            continue
        unit_id = str(group["prediction_unit_id"])
        parent_ids = group.get("parent_unit_ids")
        primary = group.get("primary_parent_unit_id")
        if not isinstance(parent_ids, list) or len(parent_ids) != 1 or primary != parent_ids[0]:
            reused += 1
            continue
        parent_id = str(primary)
        if parent_membership.get(parent_id) != {unit_id}:
            reused += 1
    return reused


def candidate_decisions_sha256(candidate: Mapping[str, Any]) -> str:
    rows = []
    for group in _candidate_groups(candidate):
        rows.append(
            {
                "prediction_unit_id": group["prediction_unit_id"],
                "parent_unit_ids": group.get("parent_unit_ids"),
                "primary_parent_unit_id": group.get("primary_parent_unit_id"),
                "candidate_auto_single": group.get("candidate_auto_single"),
                "candidate_reasons": group.get("candidate_reasons"),
            }
        )
    return _digest(rows)


def validate_candidate(candidate: Mapping[str, Any], base_manifest: Mapping[str, Any]) -> dict[str, Any]:
    if candidate.get("strategy") != CANDIDATE_STRATEGY:
        raise HeldoutV2Error("candidate strategy mismatch")
    if candidate.get("config") != EXPECTED_CANDIDATE_CONFIG:
        raise HeldoutV2Error("candidate config drift")
    if candidate.get("truth_used_for_candidate_construction") is not False:
        raise HeldoutV2Error("candidate construction must remain truth-free")
    if candidate.get("automatic_candidate_decisions_frozen") is not True:
        raise HeldoutV2Error("candidate decisions are not frozen")
    if candidate.get("review_only") is not True or candidate.get("promotion_ready") is not False:
        raise HeldoutV2Error("candidate safety state mismatch")
    if candidate.get("parser_behavior_changed") is not False:
        raise HeldoutV2Error("candidate must not change parser behavior")

    identity_pairs = {
        "campaign_key": "campaign_key",
        "store_external_id": "store_external_id",
        "source_identity_sha256": "source_sha256",
        "prediction_parser_identity": "parser_identity",
        "source_evidence_sha256": "evidence_sha256",
        "predictions_sha256": "predictions_sha256",
    }
    for candidate_key, manifest_key in identity_pairs.items():
        if candidate.get(candidate_key) != base_manifest.get(manifest_key):
            raise HeldoutV2Error(f"candidate/base freeze identity mismatch: {candidate_key}")

    frozen_provenance = _require_sha256(candidate.get("candidate_provenance_sha256"), "candidate provenance")
    candidate_without_digest = dict(candidate)
    candidate_without_digest.pop("candidate_provenance_sha256", None)
    if payload_sha256(candidate_without_digest) != frozen_provenance:
        raise HeldoutV2Error("candidate provenance digest mismatch")

    groups = _candidate_groups(candidate)
    auto_count = sum(row.get("candidate_auto_single") is True for row in groups)
    if int(candidate.get("prediction_group_count") or -1) != len(groups):
        raise HeldoutV2Error("candidate prediction group count mismatch")
    if int(candidate.get("candidate_auto_single_count") or -1) != auto_count:
        raise HeldoutV2Error("candidate auto-single count mismatch")

    return {
        "candidate_strategy": CANDIDATE_STRATEGY,
        "candidate_config_sha256": _digest(EXPECTED_CANDIDATE_CONFIG),
        "candidate_provenance_sha256": frozen_provenance,
        "candidate_decisions_sha256": candidate_decisions_sha256(candidate),
        "candidate_auto_single_count": auto_count,
        "automatic_candidate_parent_reuse_count": automatic_candidate_parent_reuse_count(candidate),
    }


def prepare_v2_freeze(
    base_manifest: dict[str, Any],
    base_receipt: dict[str, Any],
    candidate: dict[str, Any],
    *,
    candidate_file_sha256: str,
    candidate_implementation_commit: str,
) -> tuple[dict[str, Any], dict[str, Any]]:
    validate_freeze_manifest(base_manifest)
    validate_freeze_receipt(base_manifest, base_receipt)
    campaign = str(base_manifest["campaign_key"])
    if campaign in FORBIDDEN_HELDOUT_CAMPAIGNS:
        raise HeldoutV2Error("v2 held-out campaign overlaps exposed evaluation/training evidence")
    candidate_file_sha256 = _require_sha256(candidate_file_sha256, "candidate file")
    candidate_implementation_commit = _require_commit_sha(candidate_implementation_commit)
    candidate_binding = validate_candidate(candidate, base_manifest)

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol": PROTOCOL_NAME,
        "base_protocol": BASE_PROTOCOL_NAME,
        "store_external_id": base_manifest["store_external_id"],
        "campaign_key": campaign,
        "campaign_window": base_manifest["campaign_window"],
        "source_sha256": base_manifest["source_sha256"],
        "parser_identity": base_manifest["parser_identity"],
        "evidence_sha256": base_manifest["evidence_sha256"],
        "predictions_sha256": base_manifest["predictions_sha256"],
        "base_freeze_manifest_sha256": base_receipt["freeze_manifest_sha256"],
        "candidate_implementation_commit": candidate_implementation_commit,
        "candidate_file_sha256": candidate_file_sha256,
        **candidate_binding,
        "parent_reuse_metric": PARENT_REUSE_METRIC,
        "acceptance": dict(ACCEPTANCE),
        "ownership_classes": list(OWNERSHIP_CLASSES),
        "truth_sha256": None,
        "adjudication_sha256": None,
        "truth_available_at_freeze": False,
        "review_only": True,
        "promotion_ready": False,
    }
    receipt = {
        "schema_version": SCHEMA_VERSION,
        "protocol": PROTOCOL_NAME,
        "campaign_key": campaign,
        "v2_freeze_manifest_sha256": _digest(manifest),
        "base_freeze_manifest_sha256": base_receipt["freeze_manifest_sha256"],
        "acceptance_sha256": acceptance_digest(),
        "candidate_implementation_commit": candidate_implementation_commit,
        "candidate_file_sha256": candidate_file_sha256,
        "candidate_config_sha256": candidate_binding["candidate_config_sha256"],
        "candidate_provenance_sha256": candidate_binding["candidate_provenance_sha256"],
        "candidate_decisions_sha256": candidate_binding["candidate_decisions_sha256"],
        "candidate_auto_single_count": candidate_binding["candidate_auto_single_count"],
        "automatic_candidate_parent_reuse_count": candidate_binding["automatic_candidate_parent_reuse_count"],
        "parent_reuse_metric": PARENT_REUSE_METRIC,
        "truth_available_at_freeze": False,
        "review_only": True,
        "promotion_ready": False,
    }
    return manifest, receipt


def _write_create_only(path: Path, payload: Mapping[str, Any]) -> None:
    if path.exists() or path.is_symlink():
        raise HeldoutV2Error(f"output already exists: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(_canonical_bytes(dict(payload)))


def main() -> int:
    parser = argparse.ArgumentParser(description="Freeze held-out ownership v2 candidate provenance before truth")
    parser.add_argument("--base-manifest", type=Path, required=True)
    parser.add_argument("--base-receipt", type=Path, required=True)
    parser.add_argument("--candidate", type=Path, required=True)
    parser.add_argument("--candidate-implementation-commit", required=True)
    parser.add_argument("--manifest-output", type=Path, required=True)
    parser.add_argument("--receipt-output", type=Path, required=True)
    args = parser.parse_args()
    candidate = _load(args.candidate)
    manifest, receipt = prepare_v2_freeze(
        _load(args.base_manifest),
        _load(args.base_receipt),
        candidate,
        candidate_file_sha256=file_sha256(args.candidate),
        candidate_implementation_commit=args.candidate_implementation_commit,
    )
    _write_create_only(args.manifest_output, manifest)
    _write_create_only(args.receipt_output, receipt)
    print(json.dumps(receipt, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
