from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path
import sys
from tempfile import TemporaryDirectory
from typing import Any, Mapping

from app.edeka_source_card_accounting import (
    audit_edeka_source_card_manifest,
    write_source_card_accounting,
)
from edeka_accounted_live_provenance_bridge import (
    _safe_cycle_manifest,
    build_accounted_live_candidate_provenance,
    write_accounted_live_candidate_provenance,
)
from edeka_candidate_provenance import validate_candidate_provenance
from edeka_live_provenance_derivation import derive_live_provenance_from_artifact


ACCOUNTED_DERIVATION_SCHEMA_VERSION = 1


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


def _full_commit(value: str) -> str:
    if len(value) != 40 or any(char not in "0123456789abcdef" for char in value):
        raise ValueError("EDEKA accounted derivation requires a full commit SHA")
    return value


def _positive_int(value: object, label: str) -> int:
    if isinstance(value, bool):
        raise ValueError(f"EDEKA accounted derivation {label} must be positive")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            f"EDEKA accounted derivation {label} must be positive"
        ) from exc
    if parsed < 1:
        raise ValueError(f"EDEKA accounted derivation {label} must be positive")
    return parsed


def _mapping(value: object, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"EDEKA accounted derivation {label} must be an object")
    return value


def _only_extracted_cycle(legacy_output: Path) -> Path:
    extracted = legacy_output / "extracted"
    if extracted.is_symlink() or not extracted.is_dir():
        raise ValueError("EDEKA accounted derivation legacy extraction is missing")
    roots = [
        path
        for path in extracted.iterdir()
        if path.is_dir() and not path.is_symlink()
    ]
    if len(roots) != 1:
        raise ValueError("EDEKA accounted derivation requires one extracted root")
    cycle = roots[0] / "cycle"
    if cycle.is_symlink() or not cycle.is_dir():
        raise ValueError("EDEKA accounted derivation cycle directory is missing")
    return cycle.resolve()


def derive_accounted_live_provenance_from_artifact(
    artifact_dir: Path,
    output_dir: Path,
    *,
    source_run_id: int,
    source_run_attempt: int,
    artifact_id: int,
    artifact_name: str,
    artifact_digest: str,
    derivation_commit: str,
) -> dict[str, Any]:
    derivation_commit = _full_commit(derivation_commit)
    source_run_id = _positive_int(source_run_id, "source_run_id")
    source_run_attempt = _positive_int(source_run_attempt, "source_run_attempt")
    artifact_id = _positive_int(artifact_id, "artifact_id")

    target = output_dir.expanduser().resolve()
    if output_dir.is_symlink():
        raise ValueError("EDEKA accounted derivation output must not be a symlink")
    if target.exists() and any(target.iterdir()):
        raise ValueError("EDEKA accounted derivation output directory must be empty")
    target.mkdir(parents=True, exist_ok=True)

    with TemporaryDirectory(prefix="edeka-accounted-derive-") as temporary:
        legacy_output = Path(temporary) / "legacy"
        legacy = derive_live_provenance_from_artifact(
            artifact_dir,
            legacy_output,
            source_run_id=source_run_id,
            source_run_attempt=source_run_attempt,
            artifact_id=artifact_id,
            artifact_name=artifact_name,
            artifact_digest=artifact_digest,
            derivation_commit=derivation_commit,
        )
        if legacy.get("result") != "pass":
            raise ValueError("EDEKA legacy provenance derivation did not pass")

        cycle_dir = _only_extracted_cycle(legacy_output)
        accounted = build_accounted_live_candidate_provenance(cycle_dir)
        validation = validate_candidate_provenance(accounted)
        live = _mapping(accounted.get("live_evidence"), "live_evidence")

        parsed_offer_count = _positive_int(
            live.get("parsed_offer_count"),
            "parsed_offer_count",
        )
        source_card_count = _positive_int(
            live.get("source_card_count"),
            "source_card_count",
        )
        excluded_raw = live.get("excluded_count")
        if isinstance(excluded_raw, bool):
            raise ValueError("EDEKA accounted derivation excluded_count is invalid")
        try:
            excluded_count = int(excluded_raw)
        except (TypeError, ValueError) as exc:
            raise ValueError(
                "EDEKA accounted derivation excluded_count is invalid"
            ) from exc
        if excluded_count < 0:
            raise ValueError("EDEKA accounted derivation excluded_count is invalid")
        if source_card_count != parsed_offer_count + excluded_count:
            raise ValueError("EDEKA accounted derivation source-card count mismatch")
        if live.get("unexplained_source_card_loss") is not False:
            raise ValueError("EDEKA accounted derivation has unexplained source-card loss")
        if legacy.get("candidate_count") != parsed_offer_count:
            raise ValueError("EDEKA accounted derivation legacy parsed count mismatch")
        if validation.get("candidate_count") != source_card_count:
            raise ValueError("EDEKA accounted derivation Gate C count mismatch")

        route_counts = _mapping(validation.get("route_counts"), "route_counts")
        if route_counts.get("excluded") != excluded_count:
            raise ValueError("EDEKA accounted derivation excluded route mismatch")
        automatic_count = int(route_counts.get("automatic_candidate") or 0)
        review_count = int(route_counts.get("review_required") or 0)
        if automatic_count + review_count != parsed_offer_count:
            raise ValueError("EDEKA accounted derivation parsed route totals mismatch")
        if validation.get("promotion_ready") is not False:
            raise ValueError("EDEKA accounted derivation promotion must remain false")

        manifest_path, manifest_sha = _safe_cycle_manifest(cycle_dir)
        accounting = audit_edeka_source_card_manifest(manifest_path, manifest_sha)
        if accounting.get("report_sha256") != live.get(
            "source_card_accounting_sha256"
        ):
            raise ValueError("EDEKA accounted derivation accounting hash mismatch")

        provenance_path = target / "edeka-live-candidate-provenance.json"
        accounting_path = target / "source-card-accounting.json"
        write_accounted_live_candidate_provenance(provenance_path, accounted)
        write_source_card_accounting(accounting_path, accounting)
        provenance_sha = _sha256_file(provenance_path)
        accounting_sha = _sha256_file(accounting_path)

        attestation: dict[str, Any] = {
            "schema_version": ACCOUNTED_DERIVATION_SCHEMA_VERSION,
            "audit_type": "edeka_accounted_live_gate_c_provenance_derivation",
            "result": "pass",
            "source": {
                "workflow_run_id": source_run_id,
                "workflow_run_attempt": source_run_attempt,
                "artifact_id": artifact_id,
                "artifact_name": artifact_name,
                "artifact_metadata_digest": artifact_digest,
                "registered_commit": legacy.get("registered_commit"),
                "legacy_campaign_id": legacy.get("campaign_id"),
                "legacy_candidate_count": legacy.get("candidate_count"),
                "legacy_provenance_sha256": legacy.get("provenance_sha256"),
                "legacy_attestation_sha256": legacy.get("attestation_sha256"),
            },
            "derivation": {
                "commit_sha": derivation_commit,
                "campaign_id": accounted["manifest"]["campaign_id"],
                "source_card_count": source_card_count,
                "parsed_offer_count": parsed_offer_count,
                "excluded_count": excluded_count,
                "automatic_candidate_count": automatic_count,
                "review_required_count": review_count,
                "route_counts": dict(route_counts),
                "all_candidates_provenance_bound": validation.get(
                    "all_candidates_provenance_bound"
                ),
                "unexplained_source_card_loss": False,
                "provenance_sha256": provenance_sha,
                "source_card_accounting_file_sha256": accounting_sha,
                "source_card_accounting_report_sha256": accounting.get(
                    "report_sha256"
                ),
                "promotion_ready": False,
            },
            "safety": {
                "source_refetch": False,
                "raw_source_uploaded": False,
                "isolated_database_uploaded": False,
                "production_database_write": False,
                "review_write": False,
                "publication_write": False,
                "production_deployment": False,
                "scheduler_activation": False,
                "production_apply_authorized": False,
            },
        }
        unsigned = _stable_json_bytes(attestation)
        attestation["attestation_sha256"] = sha256(unsigned).hexdigest()
        attestation_path = target / "derivation-attestation.json"
        attestation_path.write_bytes(_stable_json_bytes(attestation) + b"\n")

        sums = {
            provenance_path.name: provenance_sha,
            accounting_path.name: accounting_sha,
            attestation_path.name: _sha256_file(attestation_path),
        }
        sums_path = target / "SHA256SUMS"
        sums_path.write_text(
            "".join(
                f"{digest}  {name}\n"
                for name, digest in sorted(sums.items())
            ),
            encoding="utf-8",
        )

    return {
        "result": "pass",
        "source_run_id": source_run_id,
        "artifact_id": artifact_id,
        "registered_commit": attestation["source"]["registered_commit"],
        "campaign_id": attestation["derivation"]["campaign_id"],
        "source_card_count": source_card_count,
        "parsed_offer_count": parsed_offer_count,
        "excluded_count": excluded_count,
        "candidate_count": source_card_count,
        "automatic_candidate_count": automatic_count,
        "review_required_count": review_count,
        "provenance_sha256": provenance_sha,
        "source_card_accounting_sha256": accounting_sha,
        "attestation_sha256": attestation["attestation_sha256"],
        "production_database_write": False,
        "production_deployment": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Derive authoritative accounted EDEKA Gate C provenance from a "
            "successful retained shadow artifact"
        )
    )
    parser.add_argument("--artifact-dir", type=Path, required=True)
    parser.add_argument("--output-dir", type=Path, required=True)
    parser.add_argument("--source-run-id", type=int, required=True)
    parser.add_argument("--source-run-attempt", type=int, required=True)
    parser.add_argument("--artifact-id", type=int, required=True)
    parser.add_argument("--artifact-name", required=True)
    parser.add_argument("--artifact-digest", required=True)
    parser.add_argument("--derivation-commit", required=True)
    args = parser.parse_args()
    try:
        result = derive_accounted_live_provenance_from_artifact(
            args.artifact_dir,
            args.output_dir,
            source_run_id=args.source_run_id,
            source_run_attempt=args.source_run_attempt,
            artifact_id=args.artifact_id,
            artifact_name=args.artifact_name,
            artifact_digest=args.artifact_digest,
            derivation_commit=args.derivation_commit,
        )
    except Exception as exc:
        print(f"ERROR: {type(exc).__name__}: {exc}", file=sys.stderr)
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
