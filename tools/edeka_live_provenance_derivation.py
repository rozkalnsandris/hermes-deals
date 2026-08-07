from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import sys
import tarfile
from typing import Any, Mapping

from edeka_candidate_provenance import validate_candidate_provenance
from edeka_live_provenance_bridge import (
    build_live_candidate_provenance,
    write_live_candidate_provenance,
)

BRIDGE_ORIGIN_COMMIT = "71ce804f9b9e2a0e7810fa1f035cb6e27592f45f"
SHA256_RE = re.compile(r"^[0-9a-f]{64}$")
COMMIT_RE = re.compile(r"^[0-9a-f]{40}$")
ARTIFACT_NAME_RE = re.compile(
    r"^edeka-shadow-cycle-(?P<commit>[0-9a-f]{40})-run-(?P<run>[0-9]+)$"
)


class EdekaLiveProvenanceDerivationError(ValueError):
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


def _regular_file(path: Path, label: str) -> Path:
    resolved = path.resolve()
    if path.is_symlink() or not resolved.is_file():
        raise EdekaLiveProvenanceDerivationError(f"{label} must be a regular file")
    return resolved


def _load_json(path: Path, label: str) -> dict[str, Any]:
    target = _regular_file(path, label)
    try:
        payload = json.loads(target.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise EdekaLiveProvenanceDerivationError(f"invalid {label}") from exc
    if not isinstance(payload, dict):
        raise EdekaLiveProvenanceDerivationError(f"{label} root must be an object")
    return payload


def _mapping(value: Any, label: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise EdekaLiveProvenanceDerivationError(f"{label} must be an object")
    return value


def _positive_int(value: Any, label: str) -> int:
    if isinstance(value, bool):
        raise EdekaLiveProvenanceDerivationError(f"{label} must be a positive integer")
    try:
        parsed = int(value)
    except (TypeError, ValueError) as exc:
        raise EdekaLiveProvenanceDerivationError(
            f"{label} must be a positive integer"
        ) from exc
    if parsed < 1:
        raise EdekaLiveProvenanceDerivationError(f"{label} must be positive")
    return parsed


def _sha256(value: Any, label: str) -> str:
    if not isinstance(value, str):
        raise EdekaLiveProvenanceDerivationError(f"{label} must be a SHA256")
    normalized = value.removeprefix("sha256:")
    if not SHA256_RE.fullmatch(normalized):
        raise EdekaLiveProvenanceDerivationError(f"{label} must be a SHA256")
    return normalized


def _commit(value: Any, label: str) -> str:
    if not isinstance(value, str) or not COMMIT_RE.fullmatch(value):
        raise EdekaLiveProvenanceDerivationError(f"{label} must be a full commit SHA")
    return value


def _read_key_values(path: Path, label: str) -> dict[str, str]:
    target = _regular_file(path, label)
    values: dict[str, str] = {}
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        key, separator, value = line.partition("=")
        if not separator or not key:
            raise EdekaLiveProvenanceDerivationError(f"invalid {label} line")
        if key in values:
            raise EdekaLiveProvenanceDerivationError(f"duplicate {label} key: {key}")
        values[key] = value
    return values


def _require_false_flags(values: Mapping[str, Any], keys: tuple[str, ...], label: str) -> None:
    for key in keys:
        value = values.get(key)
        if value not in (False, "false"):
            raise EdekaLiveProvenanceDerivationError(f"{label}.{key} must be false")


def _verify_sha256s(path: Path, root: Path, label: str) -> None:
    target = _regular_file(path, label)
    root_resolved = root.resolve()
    seen: set[str] = set()
    for line in target.read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        digest, separator, relative_text = line.partition("  ")
        if not separator or not SHA256_RE.fullmatch(digest):
            raise EdekaLiveProvenanceDerivationError(f"invalid {label} entry")
        relative = PurePosixPath(relative_text.removeprefix("./"))
        if relative.is_absolute() or ".." in relative.parts or not relative.parts:
            raise EdekaLiveProvenanceDerivationError(f"unsafe {label} path")
        key = relative.as_posix()
        if key in seen:
            raise EdekaLiveProvenanceDerivationError(f"duplicate {label} path")
        seen.add(key)
        file_path = (root_resolved / Path(*relative.parts)).resolve()
        try:
            file_path.relative_to(root_resolved)
        except ValueError as exc:
            raise EdekaLiveProvenanceDerivationError(f"escaped {label} path") from exc
        _regular_file(file_path, f"{label} member")
        if _sha256_file(file_path) != digest:
            raise EdekaLiveProvenanceDerivationError(f"{label} digest mismatch: {key}")
    if not seen:
        raise EdekaLiveProvenanceDerivationError(f"{label} is empty")


def _safe_tar_members(archive: tarfile.TarFile) -> tuple[list[tarfile.TarInfo], str]:
    members = archive.getmembers()
    if not members:
        raise EdekaLiveProvenanceDerivationError("inner archive is empty")
    roots: set[str] = set()
    for member in members:
        path = PurePosixPath(member.name)
        if path.is_absolute() or ".." in path.parts or not path.parts:
            raise EdekaLiveProvenanceDerivationError("unsafe inner archive path")
        roots.add(path.parts[0])
        if member.issym() or member.islnk() or member.isdev() or member.isfifo():
            raise EdekaLiveProvenanceDerivationError("unsafe inner archive member type")
        if not member.isfile() and not member.isdir():
            raise EdekaLiveProvenanceDerivationError("unsupported inner archive member type")
    if len(roots) != 1:
        raise EdekaLiveProvenanceDerivationError("inner archive must have one root directory")
    return members, next(iter(roots))


def _safe_extract_archive(archive_path: Path, destination: Path) -> tuple[Path, int]:
    source = _regular_file(archive_path, "inner archive")
    if destination.exists() and any(destination.iterdir()):
        raise EdekaLiveProvenanceDerivationError("extract destination must be empty")
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(source, "r:gz") as archive:
        members, root_name = _safe_tar_members(archive)
        regular_file_count = sum(member.isfile() for member in members)
        for member in members:
            target = destination / Path(*PurePosixPath(member.name).parts)
            if member.isdir():
                target.mkdir(parents=True, exist_ok=True)
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            source_handle = archive.extractfile(member)
            if source_handle is None:
                raise EdekaLiveProvenanceDerivationError("unable to read archive member")
            with source_handle, target.open("xb") as output:
                while True:
                    chunk = source_handle.read(1024 * 1024)
                    if not chunk:
                        break
                    output.write(chunk)
    return (destination / root_name).resolve(), regular_file_count


def _write_exclusive_json(path: Path, payload: Mapping[str, Any]) -> None:
    data = _stable_json_bytes(payload) + b"\n"
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        if path.is_symlink() or not path.is_file() or path.read_bytes() != data:
            raise EdekaLiveProvenanceDerivationError(
                "refusing to replace different derivation evidence"
            )
        return
    with path.open("xb") as handle:
        handle.write(data)
        handle.flush()


def derive_live_provenance_from_artifact(
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
    root = artifact_dir.expanduser().resolve()
    if artifact_dir.is_symlink() or not root.is_dir():
        raise EdekaLiveProvenanceDerivationError("artifact directory must be a directory")
    result_root = output_dir.expanduser().resolve()
    if output_dir.is_symlink():
        raise EdekaLiveProvenanceDerivationError("output directory must not be a symlink")
    if result_root.exists() and any(result_root.iterdir()):
        raise EdekaLiveProvenanceDerivationError("output directory must be empty")
    result_root.mkdir(parents=True, exist_ok=True)

    source_run_id = _positive_int(source_run_id, "source_run_id")
    source_run_attempt = _positive_int(source_run_attempt, "source_run_attempt")
    artifact_id = _positive_int(artifact_id, "artifact_id")
    metadata_digest = _sha256(artifact_digest, "artifact_digest")
    derivation_commit = _commit(derivation_commit, "derivation_commit")

    name_match = ARTIFACT_NAME_RE.fullmatch(artifact_name)
    if name_match is None or int(name_match.group("run")) != source_run_id:
        raise EdekaLiveProvenanceDerivationError("artifact name/run binding mismatch")
    source_commit = _commit(name_match.group("commit"), "artifact source commit")

    runner_request = _read_key_values(root / "runner-request.txt", "runner request")
    expected_request = {
        "audit": "edeka-shadow-cycle",
        "commit_sha": source_commit,
        "run_id": str(source_run_id),
        "run_attempt": str(source_run_attempt),
    }
    if runner_request != expected_request:
        raise EdekaLiveProvenanceDerivationError("runner request binding mismatch")
    if _regular_file(root / "runner-dispatch-exit-code.txt", "runner exit code").read_text(
        encoding="utf-8"
    ).strip() != "0":
        raise EdekaLiveProvenanceDerivationError("runner dispatcher did not exit zero")

    audit_root = root / "audit-evidence"
    if audit_root.is_symlink() or not audit_root.is_dir():
        raise EdekaLiveProvenanceDerivationError("audit-evidence directory is missing")
    dispatcher = _load_json(
        audit_root / "dispatcher-evidence-manifest.json", "dispatcher manifest"
    )
    if dispatcher.get("schema_version") != 1 or dispatcher.get("audit") != "edeka-shadow-cycle":
        raise EdekaLiveProvenanceDerivationError("unexpected dispatcher manifest")
    if dispatcher.get("audit_exit_code") != 0 or dispatcher.get("sanitization_passed") is not True:
        raise EdekaLiveProvenanceDerivationError("dispatcher audit/sanitization gate failed")
    if dispatcher.get("production_apply_authorized") is not False:
        raise EdekaLiveProvenanceDerivationError("production apply must remain unauthorized")
    if dispatcher.get("commit_sha") != source_commit:
        raise EdekaLiveProvenanceDerivationError("dispatcher commit mismatch")

    archive_record = _mapping(dispatcher.get("archive"), "archive")
    archive_name = archive_record.get("name")
    if not isinstance(archive_name, str) or Path(archive_name).name != archive_name:
        raise EdekaLiveProvenanceDerivationError("unsafe archive name")
    archive_path = _regular_file(audit_root / archive_name, "inner archive")
    archive_sha = _sha256(archive_record.get("sha256"), "archive.sha256")
    if _sha256_file(archive_path) != archive_sha:
        raise EdekaLiveProvenanceDerivationError("inner archive SHA256 mismatch")
    if archive_path.stat().st_size != _positive_int(archive_record.get("bytes"), "archive.bytes"):
        raise EdekaLiveProvenanceDerivationError("inner archive byte length mismatch")
    expected_member_count = _positive_int(archive_record.get("member_count"), "member_count")
    offer_count = _positive_int(archive_record.get("offer_count"), "offer_count")

    checksum_sidecar = _regular_file(
        audit_root / f"{archive_name}.sha256", "archive checksum sidecar"
    )
    sidecar_digest = checksum_sidecar.read_text(encoding="utf-8").split()[0]
    if sidecar_digest != archive_sha:
        raise EdekaLiveProvenanceDerivationError("archive sidecar SHA256 mismatch")

    safety = _read_key_values(audit_root / "safety-result.txt", "audit safety result")
    _require_false_flags(
        safety,
        ("PRIMARY_WORKTREE_MODIFIED", "PRODUCTION_DATABASE_WRITE", "PRODUCTION_DEPLOYMENT", "SCHEDULER_ACTIVATION"),
        "audit safety",
    )
    if safety.get("PRIMARY_GIT_INDEX_UNCHANGED") != "true" or safety.get(
        "AUDIT_GIT_INDEX_UNCHANGED"
    ) != "true":
        raise EdekaLiveProvenanceDerivationError("git index safety evidence is not clean")

    extracted_root, actual_member_count = _safe_extract_archive(
        archive_path, result_root / "extracted"
    )
    if actual_member_count != expected_member_count:
        raise EdekaLiveProvenanceDerivationError("inner archive member count mismatch")
    if _regular_file(extracted_root / "registered-commit.txt", "registered commit").read_text(
        encoding="utf-8"
    ).strip() != source_commit:
        raise EdekaLiveProvenanceDerivationError("inner registered commit mismatch")
    if _regular_file(extracted_root / "capture-exit-code.txt", "capture exit code").read_text(
        encoding="utf-8"
    ).strip() != "0":
        raise EdekaLiveProvenanceDerivationError("inner capture did not exit zero")
    inner_safety = _read_key_values(extracted_root / "safety-result.txt", "inner safety")
    _require_false_flags(
        inner_safety,
        ("PRIMARY_WORKTREE_MODIFIED", "PRODUCTION_DATABASE_WRITE", "PRODUCTION_DEPLOYMENT", "SCHEDULER_ACTIVATION"),
        "inner safety",
    )
    _verify_sha256s(extracted_root / "SHA256SUMS", extracted_root, "inner SHA256SUMS")
    cycle_dir = extracted_root / "cycle"
    _verify_sha256s(cycle_dir / "SHA256SUMS", cycle_dir, "cycle SHA256SUMS")

    top_cycle = _regular_file(audit_root / "cycle-evidence.json", "sanitized cycle evidence")
    top_normalization = _regular_file(
        audit_root / "normalization-report.json", "sanitized normalization report"
    )
    if top_cycle.read_bytes() != _regular_file(
        cycle_dir / "cycle-evidence.json", "inner cycle evidence"
    ).read_bytes():
        raise EdekaLiveProvenanceDerivationError("sanitized/inner cycle evidence mismatch")
    if top_normalization.read_bytes() != _regular_file(
        cycle_dir / "normalization-report.json", "inner normalization report"
    ).read_bytes():
        raise EdekaLiveProvenanceDerivationError("sanitized/inner normalization mismatch")

    provenance = build_live_candidate_provenance(cycle_dir)
    validation = validate_candidate_provenance(provenance)
    if validation.get("candidate_count") != offer_count:
        raise EdekaLiveProvenanceDerivationError("Gate C candidate count mismatch")
    if validation.get("promotion_ready") is not False:
        raise EdekaLiveProvenanceDerivationError("Gate C promotion must remain false")

    provenance_path = result_root / "edeka-live-candidate-provenance.json"
    write_live_candidate_provenance(provenance_path, provenance)
    provenance_sha = _sha256_file(provenance_path)
    live = _mapping(provenance.get("live_evidence"), "live_evidence")

    attestation: dict[str, Any] = {
        "schema_version": 1,
        "audit_type": "edeka_live_gate_c_provenance_derivation",
        "result": "pass",
        "source": {
            "workflow_run_id": source_run_id,
            "workflow_run_attempt": source_run_attempt,
            "artifact_id": artifact_id,
            "artifact_name": artifact_name,
            "artifact_metadata_digest": f"sha256:{metadata_digest}",
            "registered_commit": source_commit,
            "archive_sha256": archive_sha,
            "archive_member_count": actual_member_count,
            "cycle_evidence_sha256": live.get("cycle_evidence_sha256"),
        },
        "derivation": {
            "commit_sha": derivation_commit,
            "bridge_origin_commit": BRIDGE_ORIGIN_COMMIT,
            "provenance_sha256": provenance_sha,
            "campaign_id": provenance["manifest"]["campaign_id"],
            "candidate_count": validation["candidate_count"],
            "route_counts": validation["route_counts"],
            "all_candidates_provenance_bound": validation[
                "all_candidates_provenance_bound"
            ],
            "promotion_ready": False,
        },
        "safety": {
            "source_refetch": False,
            "production_database_write": False,
            "review_write": False,
            "publication_write": False,
            "production_deployment": False,
            "scheduler_activation": False,
            "production_apply_authorized": False,
        },
    }
    attestation["attestation_sha256"] = sha256(_stable_json_bytes(attestation)).hexdigest()
    attestation_path = result_root / "derivation-attestation.json"
    _write_exclusive_json(attestation_path, attestation)

    sums_path = result_root / "SHA256SUMS"
    sums_path.write_text(
        f"{_sha256_file(attestation_path)}  {attestation_path.name}\n"
        f"{provenance_sha}  {provenance_path.name}\n",
        encoding="utf-8",
    )

    return {
        "result": "pass",
        "source_run_id": source_run_id,
        "artifact_id": artifact_id,
        "registered_commit": source_commit,
        "campaign_id": provenance["manifest"]["campaign_id"],
        "candidate_count": validation["candidate_count"],
        "automatic_candidate_count": validation["route_counts"]["automatic_candidate"],
        "review_required_count": validation["route_counts"]["review_required"],
        "provenance_sha256": provenance_sha,
        "attestation_sha256": attestation["attestation_sha256"],
        "production_database_write": False,
        "production_deployment": False,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Derive authoritative EDEKA Gate C provenance from a prior shadow-cycle artifact"
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
        result = derive_live_provenance_from_artifact(
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
