from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
from typing import Any


PROTOCOL_NAME = "netto-heldout-ownership-v1"
SCHEMA_VERSION = 1
STORE_EXTERNAL_ID = "5659"
EXISTING_EVALUATION_CAMPAIGNS = frozenset({"hz31_hasb_4", "hz32_hasb"})
OWNERSHIP_CLASSES = ("single_source", "mixed_source", "excluded_control")

# Frozen before any held-out ownership truth is inspected. If the sample cannot
# satisfy these evidence minima, the result is insufficient evidence rather
# than a reason to relax the thresholds against the observed truth.
ACCEPTANCE = {
    "minimum_reviewed_cells": 50,
    "minimum_mixed_source_cells": 5,
    "maximum_mixed_source_auto_single": 0,
    "maximum_excluded_control_auto_eligible": 0,
    "minimum_auto_single_precision": 0.98,
    "maximum_cross_cell_group_reuse": 0,
}

_REQUIRED_FREEZE_KEYS = {
    "schema_version",
    "protocol",
    "store_external_id",
    "campaign_key",
    "campaign_window",
    "source_sha256",
    "parser_identity",
    "evidence_sha256",
    "predictions_sha256",
    "truth_sha256",
    "adjudication_sha256",
    "acceptance",
    "ownership_classes",
    "review_only",
    "promotion_ready",
}


def _require_sha256(value: Any, name: str) -> str:
    if not isinstance(value, str) or len(value) != 64:
        raise ValueError(f"{name} must be a lowercase SHA256 hex digest")
    if any(ch not in "0123456789abcdef" for ch in value):
        raise ValueError(f"{name} must be a lowercase SHA256 hex digest")
    return value


def _canonical_bytes(payload: dict[str, Any]) -> bytes:
    return (json.dumps(payload, sort_keys=True, separators=(",", ":")) + "\n").encode()


def protocol_digest(payload: dict[str, Any]) -> str:
    return hashlib.sha256(_canonical_bytes(payload)).hexdigest()


def validate_freeze_manifest(payload: dict[str, Any]) -> dict[str, Any]:
    if set(payload) != _REQUIRED_FREEZE_KEYS:
        missing = sorted(_REQUIRED_FREEZE_KEYS - set(payload))
        extra = sorted(set(payload) - _REQUIRED_FREEZE_KEYS)
        raise ValueError(f"freeze manifest keys mismatch: missing={missing} extra={extra}")
    if payload["schema_version"] != SCHEMA_VERSION:
        raise ValueError("schema_version mismatch")
    if payload["protocol"] != PROTOCOL_NAME:
        raise ValueError("protocol mismatch")
    if payload["store_external_id"] != STORE_EXTERNAL_ID:
        raise ValueError("held-out campaign must use Netto family store 5659")

    campaign_key = payload["campaign_key"]
    if not isinstance(campaign_key, str) or not campaign_key.strip():
        raise ValueError("campaign_key is required")
    if campaign_key in EXISTING_EVALUATION_CAMPAIGNS:
        raise ValueError("held-out campaign overlaps the existing evaluation corpus")

    window = payload["campaign_window"]
    if not isinstance(window, dict) or set(window) != {"start", "end"}:
        raise ValueError("campaign_window must contain exactly start/end")
    if not all(isinstance(window[key], str) and window[key] for key in ("start", "end")):
        raise ValueError("campaign_window dates are required")
    if window["start"] > window["end"]:
        raise ValueError("campaign_window start must not be after end")

    _require_sha256(payload["source_sha256"], "source_sha256")
    _require_sha256(payload["evidence_sha256"], "evidence_sha256")
    _require_sha256(payload["predictions_sha256"], "predictions_sha256")
    if not isinstance(payload["parser_identity"], str) or not payload["parser_identity"].strip():
        raise ValueError("parser_identity is required")

    # Truth must not be available in the prediction/evidence freeze artifact.
    if payload["truth_sha256"] is not None or payload["adjudication_sha256"] is not None:
        raise ValueError("truth/adjudication must be absent before evidence freeze")
    if payload["acceptance"] != ACCEPTANCE:
        raise ValueError("acceptance contract drift")
    if payload["ownership_classes"] != list(OWNERSHIP_CLASSES):
        raise ValueError("ownership class contract drift")
    if payload["review_only"] is not True or payload["promotion_ready"] is not False:
        raise ValueError("held-out evidence must remain Review-only and non-promotable")

    return payload


def freeze_receipt(payload: dict[str, Any]) -> dict[str, Any]:
    validate_freeze_manifest(payload)
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol": PROTOCOL_NAME,
        "campaign_key": payload["campaign_key"],
        "source_sha256": payload["source_sha256"],
        "evidence_sha256": payload["evidence_sha256"],
        "predictions_sha256": payload["predictions_sha256"],
        "freeze_manifest_sha256": protocol_digest(payload),
        "acceptance_sha256": hashlib.sha256(_canonical_bytes(ACCEPTANCE)).hexdigest(),
        "truth_available_at_freeze": False,
        "review_only": True,
        "promotion_ready": False,
    }


def validate_adjudication_binding(payload: dict[str, Any], receipt: dict[str, Any]) -> None:
    validate_freeze_manifest(payload)
    if receipt.get("protocol") != PROTOCOL_NAME or receipt.get("campaign_key") != payload["campaign_key"]:
        raise ValueError("freeze receipt identity mismatch")
    if receipt.get("freeze_manifest_sha256") != protocol_digest(payload):
        raise ValueError("freeze manifest changed after prediction/evidence freeze")
    if receipt.get("truth_available_at_freeze") is not False:
        raise ValueError("truth-leak boundary is not proven")


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the predeclared Netto held-out ownership protocol")
    sub = parser.add_subparsers(dest="command", required=True)
    freeze = sub.add_parser("freeze")
    freeze.add_argument("manifest", type=Path)
    freeze.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()

    if args.command == "freeze":
        receipt = freeze_receipt(_load(args.manifest))
        args.output.write_text(json.dumps(receipt, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        return 0
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
