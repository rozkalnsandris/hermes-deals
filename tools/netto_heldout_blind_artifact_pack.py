#!/usr/bin/env python3
from __future__ import annotations

import argparse
from hashlib import sha256
import json
from pathlib import Path, PurePosixPath
import re
import shutil
import stat
import tempfile
from typing import Any
import zipfile

from netto_heldout_blind_review_pack import (
    HeldoutBlindReviewPackError,
    generate_pack,
)

STRATEGY = "netto_heldout_blind_artifact_adapter_v1"
STORE_ID = "5659"
SCOPE = "family_primary_netto"
MAX_ARCHIVE_MEMBERS = 64
MAX_ARCHIVE_UNCOMPRESSED_BYTES = 128 * 1024 * 1024
MAX_MEMBER_BYTES = 64 * 1024 * 1024
COPY_CHUNK = 1024 * 1024

INTERNAL_METADATA_MEMBERS = (
    "live-source.json",
    "selected-binding.json",
    "capture/freeze-receipt.json",
    "capture/blind-review-template.json",
    "capture/freeze-manifest.json",
)
FORBIDDEN_REVIEWER_MEMBERS = frozenset(
    {
        "capture/predictions.json",
        "capture/candidate-provenance.json",
        "capture/source-evidence.json",
        "capture/freeze-manifest-v2.json",
        "capture/freeze-receipt-v2.json",
        "github-capture-result-v2.json",
    }
)
REQUIRED_ARCHIVE_MEMBERS = frozenset(
    {
        "SHA256SUMS",
        *INTERNAL_METADATA_MEMBERS,
        *FORBIDDEN_REVIEWER_MEMBERS,
    }
)


class BlindArtifactPackError(ValueError):
    pass


def _require_sha(value: str, label: str) -> str:
    text = str(value).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{64}", text):
        raise BlindArtifactPackError(f"{label} must be a SHA256")
    return text


def _require_commit(value: str) -> str:
    text = str(value).strip().lower()
    if not re.fullmatch(r"[0-9a-f]{40}", text):
        raise BlindArtifactPackError("expected commit must be an exact lowercase SHA")
    return text


def _file_sha256(path: Path) -> str:
    digest = sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(COPY_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _member_sha256(archive: zipfile.ZipFile, info: zipfile.ZipInfo) -> str:
    digest = sha256()
    with archive.open(info, "r") as handle:
        for chunk in iter(lambda: handle.read(COPY_CHUNK), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _validate_member_name(name: str) -> PurePosixPath:
    if not name or "\x00" in name or "\\" in name:
        raise BlindArtifactPackError("archive contains an unsafe member name")
    path = PurePosixPath(name)
    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):
        raise BlindArtifactPackError(f"archive contains an unsafe member path: {name}")
    if path.as_posix() != name:
        raise BlindArtifactPackError(f"archive member path is not canonical: {name}")
    return path


def _validate_regular_member(info: zipfile.ZipInfo) -> None:
    _validate_member_name(info.filename)
    if info.is_dir():
        raise BlindArtifactPackError(f"archive directories are not accepted: {info.filename}")
    if info.flag_bits & 0x1:
        raise BlindArtifactPackError(f"encrypted archive member is not accepted: {info.filename}")
    if info.file_size < 0 or info.file_size > MAX_MEMBER_BYTES:
        raise BlindArtifactPackError(f"archive member size is unsafe: {info.filename}")
    if info.create_system != 3:
        raise BlindArtifactPackError(
            f"archive member lacks auditable Unix file type: {info.filename}"
        )
    mode = (info.external_attr >> 16) & 0xFFFF
    if not stat.S_ISREG(mode):
        raise BlindArtifactPackError(f"archive member is not a regular file: {info.filename}")


def _parse_checksum_manifest(payload: bytes) -> dict[str, str]:
    try:
        text = payload.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise BlindArtifactPackError("SHA256SUMS is not valid UTF-8") from exc
    result: dict[str, str] = {}
    for line in text.splitlines():
        if not line:
            continue
        match = re.fullmatch(r"([0-9a-f]{64})  (.+)", line)
        if not match:
            raise BlindArtifactPackError("SHA256SUMS contains an invalid row")
        digest, name = match.groups()
        _validate_member_name(name)
        if name in result:
            raise BlindArtifactPackError(f"SHA256SUMS contains a duplicate path: {name}")
        result[name] = digest
    if not result:
        raise BlindArtifactPackError("SHA256SUMS is empty")
    return result


def _validate_archive(
    artifact_zip: Path,
    *,
    expected_artifact_sha256: str,
    expected_pdf_sha256: str,
    expected_commit: str,
    expected_campaign: str,
    expected_v2_freeze_manifest_sha256: str,
) -> tuple[str, str]:
    if artifact_zip.is_symlink() or not artifact_zip.is_file():
        raise BlindArtifactPackError("artifact ZIP must be a regular non-symlink file")
    expected_artifact_sha256 = _require_sha(
        expected_artifact_sha256, "expected artifact ZIP"
    )
    expected_pdf_sha256 = _require_sha(expected_pdf_sha256, "expected frozen PDF")
    actual_zip_sha = _file_sha256(artifact_zip)
    if actual_zip_sha != expected_artifact_sha256:
        raise BlindArtifactPackError("artifact ZIP SHA256 mismatch")

    try:
        archive = zipfile.ZipFile(artifact_zip, "r")
    except (OSError, zipfile.BadZipFile) as exc:
        raise BlindArtifactPackError("artifact is not a readable ZIP") from exc

    with archive:
        infos = archive.infolist()
        if not infos or len(infos) > MAX_ARCHIVE_MEMBERS:
            raise BlindArtifactPackError("artifact member count is outside the safe bound")

        by_name: dict[str, zipfile.ZipInfo] = {}
        total_size = 0
        for info in infos:
            _validate_regular_member(info)
            if info.filename in by_name:
                raise BlindArtifactPackError(
                    f"artifact contains a duplicate member: {info.filename}"
                )
            by_name[info.filename] = info
            total_size += info.file_size
            if total_size > MAX_ARCHIVE_UNCOMPRESSED_BYTES:
                raise BlindArtifactPackError("artifact uncompressed size exceeds the safe bound")

        missing = sorted(REQUIRED_ARCHIVE_MEMBERS - set(by_name))
        if missing:
            raise BlindArtifactPackError(
                f"artifact is missing required frozen members: {', '.join(missing)}"
            )

        if archive.testzip() is not None:
            raise BlindArtifactPackError("artifact failed ZIP CRC validation")

        sums_info = by_name["SHA256SUMS"]
        if sums_info.file_size > 1024 * 1024:
            raise BlindArtifactPackError("SHA256SUMS is unexpectedly large")
        sums_payload = archive.read(sums_info)
        expected_members = _parse_checksum_manifest(sums_payload)
        if set(expected_members) != set(by_name) - {"SHA256SUMS"}:
            raise BlindArtifactPackError(
                "SHA256SUMS membership does not exactly bind the artifact"
            )
        for name, expected_sha in expected_members.items():
            if _member_sha256(archive, by_name[name]) != expected_sha:
                raise BlindArtifactPackError(f"artifact member SHA256 mismatch: {name}")

        result_info = by_name["github-capture-result-v2.json"]
        if result_info.file_size > 64 * 1024:
            raise BlindArtifactPackError("v2 capture result is unexpectedly large")
        try:
            result_v2 = json.loads(archive.read(result_info).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise BlindArtifactPackError("v2 capture result is not valid UTF-8 JSON") from exc
        if not isinstance(result_v2, dict):
            raise BlindArtifactPackError("v2 capture result must contain an object")
        if (
            result_v2.get("result") != "PASS"
            or result_v2.get("registered_commit") != expected_commit
            or result_v2.get("campaign_key") != expected_campaign
            or result_v2.get("v2_freeze_manifest_sha256")
            != expected_v2_freeze_manifest_sha256
        ):
            raise BlindArtifactPackError("v2 capture result identity mismatch")
        if (
            result_v2.get("candidate_decisions_frozen_before_truth") is not True
            or result_v2.get("truth_available_at_freeze") is not False
            or result_v2.get("review_only") is not True
            or result_v2.get("promotion_ready") is not False
            or result_v2.get("database_write_performed") is not False
            or result_v2.get("review_write_performed") is not False
            or result_v2.get("deployment_performed") is not False
            or result_v2.get("scheduler_change_performed") is not False
        ):
            raise BlindArtifactPackError("v2 capture result safety state mismatch")

        pdf_names = [
            name
            for name in by_name
            if PurePosixPath(name).parent == PurePosixPath("source/netto")
            and name.lower().endswith(".pdf")
        ]
        matching_pdfs = [
            name for name in pdf_names if expected_members.get(name) == expected_pdf_sha256
        ]
        if len(pdf_names) != 1 or len(matching_pdfs) != 1:
            raise BlindArtifactPackError(
                "artifact must contain exactly one frozen Netto PDF with the expected SHA256"
            )
        return matching_pdfs[0], sha256(sums_payload).hexdigest()


def _copy_member(
    archive: zipfile.ZipFile,
    info: zipfile.ZipInfo,
    destination: Path,
) -> None:
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists() or destination.is_symlink():
        raise BlindArtifactPackError(f"staging member already exists: {destination}")
    with archive.open(info, "r") as source, destination.open("xb") as target:
        shutil.copyfileobj(source, target, length=COPY_CHUNK)


def _write_json_create_only(path: Path, payload: dict[str, Any]) -> tuple[str, int]:
    data = (
        json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n"
    ).encode("utf-8")
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        with path.open("xb") as handle:
            handle.write(data)
    except FileExistsError as exc:
        raise BlindArtifactPackError(f"output member already exists: {path}") from exc
    return sha256(data).hexdigest(), len(data)


def generate_from_artifact(
    artifact_zip: Path,
    output: Path,
    *,
    artifact_id: int,
    workflow_run_id: int,
    expected_artifact_sha256: str,
    expected_commit: str,
    expected_campaign: str,
    expected_valid_from: str,
    expected_valid_until: str,
    expected_source_sha256: str,
    expected_pdf_sha256: str,
    expected_freeze_manifest_sha256: str,
    expected_v2_freeze_manifest_sha256: str,
    expected_page_count: int,
) -> dict[str, Any]:
    if artifact_id <= 0 or workflow_run_id <= 0:
        raise BlindArtifactPackError("artifact/run IDs must be positive")
    if output.exists() or output.is_symlink():
        raise BlindArtifactPackError("output directory must be create-only")
    expected_commit = _require_commit(expected_commit)
    expected_artifact_sha256 = _require_sha(
        expected_artifact_sha256, "expected artifact ZIP"
    )
    expected_source_sha256 = _require_sha(
        expected_source_sha256, "expected selected source identity"
    )
    expected_pdf_sha256 = _require_sha(expected_pdf_sha256, "expected frozen PDF")
    expected_freeze_manifest_sha256 = _require_sha(
        expected_freeze_manifest_sha256, "expected v1 freeze manifest"
    )
    expected_v2_freeze_manifest_sha256 = _require_sha(
        expected_v2_freeze_manifest_sha256, "expected v2 freeze manifest"
    )
    if expected_page_count <= 0:
        raise BlindArtifactPackError("expected page count must be positive")

    pdf_name, upstream_sums_sha = _validate_archive(
        artifact_zip,
        expected_artifact_sha256=expected_artifact_sha256,
        expected_pdf_sha256=expected_pdf_sha256,
        expected_commit=expected_commit,
        expected_campaign=expected_campaign,
        expected_v2_freeze_manifest_sha256=expected_v2_freeze_manifest_sha256,
    )

    with tempfile.TemporaryDirectory(prefix="netto-blind-artifact-") as tmp:
        staging = Path(tmp) / "capture-root"
        staging.mkdir(mode=0o700)
        with zipfile.ZipFile(artifact_zip, "r") as archive:
            for name in INTERNAL_METADATA_MEMBERS:
                _copy_member(archive, archive.getinfo(name), staging / name)
            _copy_member(archive, archive.getinfo(pdf_name), staging / pdf_name)

        # The v2 result contains frozen candidate provenance. Do not expose or copy
        # it into reviewer staging. The exact artifact SHA and SHA256SUMS bind the
        # upstream file; only safe identity/state fields were validated above.
        _write_json_create_only(
            staging / "github-capture-result.json",
            {
                "result": "PASS",
                "registered_commit": expected_commit,
                "campaign_key": expected_campaign,
                "truth_available_at_freeze": False,
                "review_only": True,
                "promotion_ready": False,
            },
        )

        try:
            review = generate_pack(
                staging,
                output,
                expected_commit=expected_commit,
                expected_campaign=expected_campaign,
                expected_valid_from=expected_valid_from,
                expected_valid_until=expected_valid_until,
                expected_source_sha256=expected_source_sha256,
                expected_pdf_sha256=expected_pdf_sha256,
                expected_freeze_manifest_sha256=expected_freeze_manifest_sha256,
                expected_page_count=expected_page_count,
            )
        except HeldoutBlindReviewPackError as exc:
            raise BlindArtifactPackError(str(exc)) from exc

    receipt = {
        "schema_version": 1,
        "strategy": STRATEGY,
        "artifact_id": artifact_id,
        "workflow_run_id": workflow_run_id,
        "artifact_zip_sha256": expected_artifact_sha256,
        "artifact_sha256s_sha256": upstream_sums_sha,
        "registered_commit": expected_commit,
        "campaign_key": expected_campaign,
        "campaign_window": {
            "start": expected_valid_from,
            "end": expected_valid_until,
        },
        "store_external_id": STORE_ID,
        "scope": SCOPE,
        "source_sha256": expected_source_sha256,
        "source_pdf_sha256": expected_pdf_sha256,
        "freeze_manifest_sha256": expected_freeze_manifest_sha256,
        "v2_freeze_manifest_sha256": expected_v2_freeze_manifest_sha256,
        "page_count": expected_page_count,
        "review_pack_manifest_sha256": review["manifest_sha256"],
        "blank_review_ledger_sha256": review["blank_review_ledger_sha256"],
        "forbidden_archive_members_extracted": False,
        "prediction_payload_parsed": False,
        "candidate_provenance_payload_parsed": False,
        "parser_predictions_included": False,
        "candidate_provenance_included": False,
        "expected_truth_included": False,
        "live_source_refetch_performed": False,
        "database_write_performed": False,
        "review_write_performed": False,
        "publication_write_performed": False,
        "deployment_performed": False,
    }
    receipt_sha, _ = _write_json_create_only(
        output / "artifact-source-receipt.json", receipt
    )
    pack_sums_sha = _file_sha256(output / "SHA256SUMS")
    provenance_lines = (
        f"{pack_sums_sha}  SHA256SUMS\n"
        f"{receipt_sha}  artifact-source-receipt.json\n"
    ).encode("utf-8")
    provenance_path = output / "ARTIFACT-SHA256SUMS"
    try:
        with provenance_path.open("xb") as handle:
            handle.write(provenance_lines)
    except FileExistsError as exc:
        raise BlindArtifactPackError(
            f"output member already exists: {provenance_path}"
        ) from exc
    return {**receipt, "artifact_source_receipt_sha256": receipt_sha}


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a deterministic blind source-only Netto review pack from an "
            "exact frozen GitHub Actions artifact ZIP."
        )
    )
    parser.add_argument("--artifact-zip", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--artifact-id", type=int, required=True)
    parser.add_argument("--workflow-run-id", type=int, required=True)
    parser.add_argument("--expected-artifact-sha256", required=True)
    parser.add_argument("--expected-commit", required=True)
    parser.add_argument("--expected-campaign", required=True)
    parser.add_argument("--expected-valid-from", required=True)
    parser.add_argument("--expected-valid-until", required=True)
    parser.add_argument("--expected-source-sha256", required=True)
    parser.add_argument("--expected-pdf-sha256", required=True)
    parser.add_argument("--expected-freeze-manifest-sha256", required=True)
    parser.add_argument("--expected-v2-freeze-manifest-sha256", required=True)
    parser.add_argument("--expected-page-count", type=int, required=True)
    args = parser.parse_args()

    payload = generate_from_artifact(
        args.artifact_zip,
        args.output,
        artifact_id=args.artifact_id,
        workflow_run_id=args.workflow_run_id,
        expected_artifact_sha256=args.expected_artifact_sha256,
        expected_commit=args.expected_commit,
        expected_campaign=args.expected_campaign,
        expected_valid_from=args.expected_valid_from,
        expected_valid_until=args.expected_valid_until,
        expected_source_sha256=args.expected_source_sha256,
        expected_pdf_sha256=args.expected_pdf_sha256,
        expected_freeze_manifest_sha256=args.expected_freeze_manifest_sha256,
        expected_v2_freeze_manifest_sha256=args.expected_v2_freeze_manifest_sha256,
        expected_page_count=args.expected_page_count,
    )
    print(
        json.dumps(
            {
                "strategy": payload["strategy"],
                "artifact_id": payload["artifact_id"],
                "workflow_run_id": payload["workflow_run_id"],
                "campaign_key": payload["campaign_key"],
                "page_count": payload["page_count"],
                "review_pack_manifest_sha256": payload[
                    "review_pack_manifest_sha256"
                ],
                "artifact_source_receipt_sha256": payload[
                    "artifact_source_receipt_sha256"
                ],
                "parser_predictions_included": False,
                "candidate_provenance_included": False,
                "expected_truth_included": False,
                "live_source_refetch_performed": False,
                "database_write_performed": False,
                "review_write_performed": False,
                "publication_write_performed": False,
                "deployment_performed": False,
            },
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
