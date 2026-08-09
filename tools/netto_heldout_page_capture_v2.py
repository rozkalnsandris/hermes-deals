from __future__ import annotations

import argparse
import hashlib
import json
from pathlib import Path
import shutil
from typing import Any, Mapping

from netto_heldout_ownership_protocol_v2 import prepare_v2_freeze
from netto_heldout_page_capture import capture_heldout
from netto_local_span_auto_single_candidate import freeze_candidate


STRATEGY = "netto_heldout_all_pages_candidate_capture_v2"
CANDIDATE_IMPLEMENTATION_COMMIT = "17ceedf0fdb0342acb594ed20679519ec4910e3c"
V2_MEMBERS = (
    "freeze-manifest.json",
    "freeze-receipt.json",
    "candidate-provenance.json",
    "freeze-manifest-v2.json",
    "freeze-receipt-v2.json",
)


class HeldoutCaptureV2Error(ValueError):
    pass


def _json_bytes(value: Any) -> bytes:
    return (json.dumps(value, ensure_ascii=False, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _file_sha256(path: Path) -> str:
    if path.is_symlink() or not path.is_file():
        raise HeldoutCaptureV2Error(f"capture member is missing or unsafe: {path.name}")
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _load(path: Path) -> dict[str, Any]:
    if path.is_symlink() or not path.is_file():
        raise HeldoutCaptureV2Error(f"input must be a regular non-symlink file: {path}")
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise HeldoutCaptureV2Error(f"invalid JSON input: {path}") from exc
    if not isinstance(value, dict):
        raise HeldoutCaptureV2Error(f"JSON input must contain an object: {path}")
    return value


def _write_create_only(path: Path, value: Mapping[str, Any]) -> str:
    if path.exists() or path.is_symlink():
        raise HeldoutCaptureV2Error(f"v2 output already exists: {path.name}")
    payload = _json_bytes(dict(value))
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def _write_v2_sums(root: Path) -> str:
    path = root / "SHA256SUMS.v2"
    if path.exists() or path.is_symlink():
        raise HeldoutCaptureV2Error("v2 checksum manifest must be create-only")
    lines = [f"{_file_sha256(root / name)}  {name}" for name in V2_MEMBERS]
    payload = ("\n".join(lines) + "\n").encode("utf-8")
    path.write_bytes(payload)
    return hashlib.sha256(payload).hexdigest()


def capture_heldout_v2(
    binding_payload: Mapping[str, Any],
    output: Path,
    *,
    candidate_implementation_commit: str = CANDIDATE_IMPLEMENTATION_COMMIT,
) -> dict[str, Any]:
    if output.exists() or output.is_symlink():
        raise HeldoutCaptureV2Error("held-out v2 output directory must not already exist")

    completed = False
    try:
        v1_summary = capture_heldout(binding_payload, output)
        source_path = output / "source-evidence.json"
        predictions_path = output / "predictions.json"
        v1_manifest_path = output / "freeze-manifest.json"
        v1_receipt_path = output / "freeze-receipt.json"

        source_sha = _file_sha256(source_path)
        predictions_sha = _file_sha256(predictions_path)
        if source_sha != v1_summary["evidence_sha256"]:
            raise HeldoutCaptureV2Error("v1 source evidence SHA changed before candidate freeze")
        if predictions_sha != v1_summary["predictions_sha256"]:
            raise HeldoutCaptureV2Error("v1 predictions SHA changed before candidate freeze")

        candidate = freeze_candidate(
            _load(source_path),
            _load(predictions_path),
            source_evidence_sha256=source_sha,
            predictions_sha256=predictions_sha,
        )
        candidate_path = output / "candidate-provenance.json"
        candidate_file_sha = _write_create_only(candidate_path, candidate)

        v2_manifest, v2_receipt = prepare_v2_freeze(
            _load(v1_manifest_path),
            _load(v1_receipt_path),
            candidate,
            candidate_file_sha256=candidate_file_sha,
            candidate_implementation_commit=candidate_implementation_commit,
        )
        v2_manifest_file_sha = _write_create_only(output / "freeze-manifest-v2.json", v2_manifest)
        v2_receipt_file_sha = _write_create_only(output / "freeze-receipt-v2.json", v2_receipt)
        sums_sha = _write_v2_sums(output)

        if v2_receipt.get("truth_available_at_freeze") is not False:
            raise HeldoutCaptureV2Error("v2 freeze unexpectedly contains truth")
        if v2_receipt.get("review_only") is not True or v2_receipt.get("promotion_ready") is not False:
            raise HeldoutCaptureV2Error("v2 freeze safety state mismatch")
        if v2_receipt.get("candidate_provenance_sha256") != candidate.get("candidate_provenance_sha256"):
            raise HeldoutCaptureV2Error("candidate provenance changed across v2 freeze")

        completed = True
        return {
            "schema_version": 2,
            "strategy": STRATEGY,
            "campaign_key": v2_receipt["campaign_key"],
            "base_freeze_manifest_sha256": v2_receipt["base_freeze_manifest_sha256"],
            "v2_freeze_manifest_sha256": v2_receipt["v2_freeze_manifest_sha256"],
            "candidate_implementation_commit": v2_receipt["candidate_implementation_commit"],
            "candidate_file_sha256": candidate_file_sha,
            "candidate_provenance_sha256": v2_receipt["candidate_provenance_sha256"],
            "candidate_decisions_sha256": v2_receipt["candidate_decisions_sha256"],
            "candidate_auto_single_count": v2_receipt["candidate_auto_single_count"],
            "automatic_candidate_parent_reuse_count": v2_receipt["automatic_candidate_parent_reuse_count"],
            "parent_reuse_metric": v2_receipt["parent_reuse_metric"],
            "freeze_manifest_v2_file_sha256": v2_manifest_file_sha,
            "freeze_receipt_v2_file_sha256": v2_receipt_file_sha,
            "sha256sums_v2_sha256": sums_sha,
            "truth_available_at_freeze": False,
            "candidate_decisions_frozen_before_truth": True,
            "review_only": True,
            "promotion_ready": False,
            "database_write_performed": False,
            "review_write_performed": False,
            "deployment_performed": False,
        }
    finally:
        if not completed and output.exists():
            shutil.rmtree(output)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Freeze v1 held-out evidence plus truth-free local-span candidate provenance for hz34+."
    )
    parser.add_argument("binding", type=Path)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument(
        "--candidate-implementation-commit",
        default=CANDIDATE_IMPLEMENTATION_COMMIT,
    )
    args = parser.parse_args()
    summary = capture_heldout_v2(
        _load(args.binding),
        args.output,
        candidate_implementation_commit=args.candidate_implementation_commit,
    )
    print(json.dumps(summary, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
