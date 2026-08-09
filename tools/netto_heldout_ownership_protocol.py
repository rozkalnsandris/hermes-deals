from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import sys
from typing import Any


TOOLS_DIR = Path(__file__).resolve().parent
if str(TOOLS_DIR) not in sys.path:
    sys.path.insert(0, str(TOOLS_DIR))

from netto_shadow_promotion import (  # noqa: E402
    EvidenceBinding,
    EvidenceStatus,
    verify_binding_files,
)


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


def acceptance_digest() -> str:
    return hashlib.sha256(_canonical_bytes(ACCEPTANCE)).hexdigest()


def file_sha256(path: Path, label: str) -> str:
    if path.is_symlink():
        raise ValueError(f"{label} must not be a symlink")
    if not path.exists():
        raise ValueError(f"{label} is missing")
    if not path.is_file():
        raise ValueError(f"{label} must be a regular file")
    digest = hashlib.sha256()
    try:
        with path.open("rb") as handle:
            for chunk in iter(lambda: handle.read(1024 * 1024), b""):
                digest.update(chunk)
    except OSError as exc:
        raise ValueError(f"{label} cannot be read: {exc}") from exc
    return digest.hexdigest()


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
        "acceptance_sha256": acceptance_digest(),
        "truth_available_at_freeze": False,
        "review_only": True,
        "promotion_ready": False,
    }


def validate_freeze_receipt(payload: dict[str, Any], receipt: dict[str, Any]) -> None:
    validate_freeze_manifest(payload)
    expected = freeze_receipt(payload)
    if receipt != expected:
        raise ValueError("freeze receipt does not match the immutable prediction/evidence freeze")


def prepare_freeze(
    binding_payload: dict[str, Any],
    campaign_key: str,
    prediction_parser_identity: str,
    evidence_path: Path,
    predictions_path: Path,
) -> tuple[dict[str, Any], dict[str, Any]]:
    binding = EvidenceBinding.from_mapping(binding_payload)
    binding.validate()
    if binding.evidence_status is not EvidenceStatus.PDF_BOUND:
        raise ValueError("held-out ownership capture requires pdf_bound evidence")
    verification = verify_binding_files(binding)
    if verification.status is not EvidenceStatus.PDF_BOUND:
        raise ValueError(f"held-out source binding is not verified: {verification.reason}")
    if not binding.pdf_sha256:
        raise ValueError("held-out ownership capture requires a PDF SHA256")
    if not isinstance(prediction_parser_identity, str) or not prediction_parser_identity.strip():
        raise ValueError("prediction parser identity is required")

    try:
        same_input = evidence_path.resolve() == predictions_path.resolve()
    except OSError as exc:
        raise ValueError(f"held-out evidence paths cannot be resolved: {exc}") from exc
    if same_input:
        raise ValueError("evidence and predictions must be separate frozen files")

    manifest = {
        "schema_version": SCHEMA_VERSION,
        "protocol": PROTOCOL_NAME,
        "store_external_id": binding.store_external_id,
        "campaign_key": campaign_key,
        "campaign_window": {
            "start": binding.valid_from.isoformat(),
            "end": binding.valid_until.isoformat(),
        },
        # Source identity includes store/scope, validity, immutable manifest/HTML/PDF
        # bindings and the source-side parser identity. The separate parser_identity
        # below names the parser that produced the frozen held-out predictions.
        "source_sha256": binding.identity_sha256(),
        "parser_identity": prediction_parser_identity.strip(),
        "evidence_sha256": file_sha256(evidence_path, "held-out evidence"),
        "predictions_sha256": file_sha256(predictions_path, "held-out predictions"),
        "truth_sha256": None,
        "adjudication_sha256": None,
        "acceptance": dict(ACCEPTANCE),
        "ownership_classes": list(OWNERSHIP_CLASSES),
        "review_only": True,
        "promotion_ready": False,
    }
    validate_freeze_manifest(manifest)
    return manifest, freeze_receipt(manifest)


def adjudication_binding(
    freeze_manifest: dict[str, Any],
    receipt: dict[str, Any],
    truth_sha256: str,
    adjudication_sha256: str,
) -> dict[str, Any]:
    validate_freeze_receipt(freeze_manifest, receipt)
    truth_sha256 = _require_sha256(truth_sha256, "truth_sha256")
    adjudication_sha256 = _require_sha256(adjudication_sha256, "adjudication_sha256")
    return {
        "schema_version": SCHEMA_VERSION,
        "protocol": PROTOCOL_NAME,
        "campaign_key": freeze_manifest["campaign_key"],
        "freeze_manifest_sha256": receipt["freeze_manifest_sha256"],
        "acceptance_sha256": receipt["acceptance_sha256"],
        "predictions_sha256": receipt["predictions_sha256"],
        "truth_sha256": truth_sha256,
        "adjudication_sha256": adjudication_sha256,
        "truth_available_at_freeze": False,
        "review_only": True,
        "promotion_ready": False,
    }


def _load(path: Path) -> dict[str, Any]:
    value = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise ValueError(f"{path} must contain a JSON object")
    return value


def _write(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def _require_new_outputs(*paths: Path) -> None:
    if len({path.resolve() for path in paths}) != len(paths):
        raise ValueError("output paths must be distinct")
    existing = [str(path) for path in paths if path.exists() or path.is_symlink()]
    if existing:
        raise ValueError(f"freeze outputs already exist: {existing}")


def main() -> int:
    parser = argparse.ArgumentParser(description="Validate the predeclared Netto held-out ownership protocol")
    sub = parser.add_subparsers(dest="command", required=True)

    prepare = sub.add_parser("prepare")
    prepare.add_argument("binding", type=Path)
    prepare.add_argument("--campaign-key", required=True)
    prepare.add_argument("--prediction-parser-identity", required=True)
    prepare.add_argument("--evidence", type=Path, required=True)
    prepare.add_argument("--predictions", type=Path, required=True)
    prepare.add_argument("--manifest-output", type=Path, required=True)
    prepare.add_argument("--receipt-output", type=Path, required=True)

    freeze = sub.add_parser("freeze")
    freeze.add_argument("manifest", type=Path)
    freeze.add_argument("--output", type=Path, required=True)

    adjudicate = sub.add_parser("adjudicate")
    adjudicate.add_argument("manifest", type=Path)
    adjudicate.add_argument("receipt", type=Path)
    adjudicate.add_argument("--truth-sha256", required=True)
    adjudicate.add_argument("--adjudication-sha256", required=True)
    adjudicate.add_argument("--output", type=Path, required=True)

    args = parser.parse_args()
    if args.command == "prepare":
        _require_new_outputs(args.manifest_output, args.receipt_output)
        manifest, receipt = prepare_freeze(
            _load(args.binding),
            args.campaign_key,
            args.prediction_parser_identity,
            args.evidence,
            args.predictions,
        )
        _write(args.manifest_output, manifest)
        _write(args.receipt_output, receipt)
        return 0
    if args.command == "freeze":
        _write(args.output, freeze_receipt(_load(args.manifest)))
        return 0
    if args.command == "adjudicate":
        _write(
            args.output,
            adjudication_binding(
                _load(args.manifest),
                _load(args.receipt),
                args.truth_sha256,
                args.adjudication_sha256,
            ),
        )
        return 0
    raise AssertionError("unreachable")


if __name__ == "__main__":
    raise SystemExit(main())
