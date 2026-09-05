from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import stat
import sys
import zipfile

import pymupdf
import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))
TOOL = TOOLS / "netto_heldout_blind_artifact_pack.py"
SPEC = importlib.util.spec_from_file_location("netto_heldout_blind_artifact_pack", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)

COMMIT = "a" * 40
CAMPAIGN = "hz34_fixture"
VALID_FROM = "2026-08-17"
VALID_UNTIL = "2026-08-22"
SOURCE_SHA = "b" * 64
FREEZE_SHA = "c" * 64
V2_FREEZE_SHA = "d" * 64
ARTIFACT_ID = 9362894718
RUN_ID = 32246715725


def _json(payload: object) -> bytes:
    return (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode("utf-8")


def _pdf_bytes(tmp_path: Path) -> bytes:
    path = tmp_path / "source.pdf"
    document = pymupdf.open()
    for page_number in (1, 2):
        page = document.new_page(width=300, height=400)
        page.insert_text((36, 72), f"FROZEN SOURCE PAGE {page_number} 1.99 €", fontsize=12)
    document.save(path)
    document.close()
    return path.read_bytes()


def _regular_info(name: str) -> zipfile.ZipInfo:
    info = zipfile.ZipInfo(name)
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | 0o600) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def _build_artifact(
    tmp_path: Path,
    *,
    extra_members: list[tuple[zipfile.ZipInfo, bytes]] | None = None,
    corrupt_checksum_for: str | None = None,
    checksum_prefix: str = "",
) -> dict[str, object]:
    pdf = _pdf_bytes(tmp_path)
    pdf_sha = sha256(pdf).hexdigest()
    members: dict[str, bytes] = {
        "capture/blind-review-template.json": _json(
            {
                "campaign_key": CAMPAIGN,
                "source_sha256": SOURCE_SHA,
                "freeze_manifest_sha256": FREEZE_SHA,
                "page_count": 2,
                "parser_predictions_included": False,
                "expected_truth_included": False,
                "pages": [
                    {"page_number": 1, "source_cards": []},
                    {"page_number": 2, "source_cards": []},
                ],
            }
        ),
        "capture/freeze-manifest.json": b'{"SENSITIVE_THRESHOLD_SENTINEL":true}\n',
        "capture/freeze-receipt.json": _json(
            {
                "source_sha256": SOURCE_SHA,
                "freeze_manifest_sha256": FREEZE_SHA,
                "truth_available_at_freeze": False,
                "review_only": True,
                "promotion_ready": False,
                "sensitive_prediction_digest": "DO_NOT_EXPOSE",
            }
        ),
        "capture/predictions.json": b'{"FORBIDDEN_PREDICTION_SENTINEL":"do-not-expose"}\n',
        "capture/candidate-provenance.json": b'{"FORBIDDEN_CANDIDATE_SENTINEL":"do-not-expose"}\n',
        "capture/source-evidence.json": b'{"FORBIDDEN_PRESEGMENT_SENTINEL":"do-not-expose"}\n',
        "capture/freeze-manifest-v2.json": b'{"FORBIDDEN_V2_MANIFEST_SENTINEL":"do-not-expose"}\n',
        "capture/freeze-receipt-v2.json": b'{"FORBIDDEN_V2_RECEIPT_SENTINEL":"do-not-expose"}\n',
        "github-capture-result-v2.json": _json(
            {
                "result": "PASS",
                "registered_commit": COMMIT,
                "campaign_key": CAMPAIGN,
                "v2_freeze_manifest_sha256": V2_FREEZE_SHA,
                "candidate_decisions_frozen_before_truth": True,
                "candidate_secret": "FORBIDDEN_RESULT_SENTINEL",
                "truth_available_at_freeze": False,
                "review_only": True,
                "promotion_ready": False,
                "database_write_performed": False,
                "review_write_performed": False,
                "deployment_performed": False,
                "scheduler_change_performed": False,
            }
        ),
        "live-source.json": _json(
            {
                "store_external_id": "5659",
                "scope": "family_primary_netto",
                "campaign_key": CAMPAIGN,
                "campaign_window": {"start": VALID_FROM, "end": VALID_UNTIL},
            }
        ),
        "selected-binding.json": _json(
            {
                "evidence_identity_sha256": SOURCE_SHA,
                "binding": {"parser_identity": "INTERNAL_ONLY_SENTINEL"},
            }
        ),
        f"source/netto/5659-{CAMPAIGN}-{pdf_sha}.pdf": pdf,
    }
    members["capture/SHA256SUMS"] = b"fixture-v1-sums\n"
    members["capture/SHA256SUMS.v2"] = b"fixture-v2-sums\n"

    checksum_rows = []
    for name, payload in sorted(members.items()):
        digest = sha256(payload).hexdigest()
        if name == corrupt_checksum_for:
            digest = "0" * 64
        checksum_rows.append(f"{digest}  {checksum_prefix}{name}")
    members["SHA256SUMS"] = ("\n".join(checksum_rows) + "\n").encode("utf-8")

    artifact = tmp_path / "artifact.zip"
    with zipfile.ZipFile(artifact, "w") as archive:
        for name, payload in members.items():
            archive.writestr(_regular_info(name), payload)
        for info, payload in extra_members or []:
            archive.writestr(info, payload)
    return {
        "path": artifact,
        "sha": sha256(artifact.read_bytes()).hexdigest(),
        "pdf_sha": pdf_sha,
    }


def _generate(tmp_path: Path, artifact: dict[str, object], output_name: str = "review-pack"):
    return MODULE.generate_from_artifact(
        Path(artifact["path"]),
        tmp_path / output_name,
        artifact_id=ARTIFACT_ID,
        workflow_run_id=RUN_ID,
        expected_artifact_sha256=str(artifact["sha"]),
        expected_commit=COMMIT,
        expected_campaign=CAMPAIGN,
        expected_valid_from=VALID_FROM,
        expected_valid_until=VALID_UNTIL,
        expected_source_sha256=SOURCE_SHA,
        expected_pdf_sha256=str(artifact["pdf_sha"]),
        expected_freeze_manifest_sha256=FREEZE_SHA,
        expected_v2_freeze_manifest_sha256=V2_FREEZE_SHA,
        expected_page_count=2,
    )


def _tree_hashes(root: Path) -> dict[str, str]:
    return {
        path.relative_to(root).as_posix(): sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_artifact_adapter_emits_only_blind_source_pack(tmp_path: Path) -> None:
    artifact = _build_artifact(tmp_path)
    payload = _generate(tmp_path, artifact)
    output = tmp_path / "review-pack"

    assert payload["artifact_id"] == ARTIFACT_ID
    assert payload["workflow_run_id"] == RUN_ID
    assert payload["artifact_zip_sha256"] == artifact["sha"]
    assert payload["v2_freeze_manifest_sha256"] == V2_FREEZE_SHA
    assert payload["forbidden_archive_members_extracted"] is False
    assert payload["prediction_payload_parsed"] is False
    assert payload["candidate_provenance_payload_parsed"] is False
    assert payload["parser_predictions_included"] is False
    assert payload["candidate_provenance_included"] is False
    assert payload["expected_truth_included"] is False
    assert payload["live_source_refetch_performed"] is False

    forbidden_names = {
        "predictions.json",
        "candidate-provenance.json",
        "source-evidence.json",
        "freeze-manifest-v2.json",
        "freeze-receipt-v2.json",
        "github-capture-result-v2.json",
    }
    assert not any(path.name in forbidden_names for path in output.rglob("*"))

    text = "\n".join(
        path.read_text(encoding="utf-8", errors="ignore")
        for path in output.rglob("*")
        if path.is_file() and path.suffix in {"", ".json"}
    )
    for sentinel in (
        "FORBIDDEN_PREDICTION_SENTINEL",
        "FORBIDDEN_CANDIDATE_SENTINEL",
        "FORBIDDEN_PRESEGMENT_SENTINEL",
        "FORBIDDEN_V2_MANIFEST_SENTINEL",
        "FORBIDDEN_V2_RECEIPT_SENTINEL",
        "FORBIDDEN_RESULT_SENTINEL",
        "SENSITIVE_THRESHOLD_SENTINEL",
        "INTERNAL_ONLY_SENTINEL",
        "DO_NOT_EXPOSE",
    ):
        assert sentinel not in text


def test_checksum_manifest_accepts_single_dot_slash_prefix(tmp_path: Path) -> None:
    artifact = _build_artifact(tmp_path, checksum_prefix="./")
    payload = _generate(tmp_path, artifact)
    assert payload["artifact_zip_sha256"] == artifact["sha"]
    assert (tmp_path / "review-pack" / "artifact-source-receipt.json").is_file()


def test_checksum_manifest_rejects_double_dot_slash_prefix(tmp_path: Path) -> None:
    artifact = _build_artifact(tmp_path, checksum_prefix="././")
    with pytest.raises(MODULE.BlindArtifactPackError, match="not canonical"):
        _generate(tmp_path, artifact)


def test_same_artifact_produces_identical_pack(tmp_path: Path) -> None:
    artifact = _build_artifact(tmp_path)
    _generate(tmp_path, artifact, "pack-a")
    _generate(tmp_path, artifact, "pack-b")
    assert _tree_hashes(tmp_path / "pack-a") == _tree_hashes(tmp_path / "pack-b")


def test_wrong_artifact_sha_fails_before_pack_creation(tmp_path: Path) -> None:
    artifact = _build_artifact(tmp_path)
    with pytest.raises(MODULE.BlindArtifactPackError, match="artifact ZIP SHA256 mismatch"):
        MODULE.generate_from_artifact(
            Path(artifact["path"]),
            tmp_path / "review-pack",
            artifact_id=ARTIFACT_ID,
            workflow_run_id=RUN_ID,
            expected_artifact_sha256="0" * 64,
            expected_commit=COMMIT,
            expected_campaign=CAMPAIGN,
            expected_valid_from=VALID_FROM,
            expected_valid_until=VALID_UNTIL,
            expected_source_sha256=SOURCE_SHA,
            expected_pdf_sha256=str(artifact["pdf_sha"]),
            expected_freeze_manifest_sha256=FREEZE_SHA,
            expected_v2_freeze_manifest_sha256=V2_FREEZE_SHA,
            expected_page_count=2,
        )
    assert not (tmp_path / "review-pack").exists()


def test_checksum_mismatch_fails_closed(tmp_path: Path) -> None:
    artifact = _build_artifact(
        tmp_path, corrupt_checksum_for="capture/predictions.json"
    )
    with pytest.raises(MODULE.BlindArtifactPackError, match="member SHA256 mismatch"):
        _generate(tmp_path, artifact)


def test_traversal_member_fails_closed(tmp_path: Path) -> None:
    artifact = _build_artifact(
        tmp_path,
        extra_members=[(_regular_info("../escape"), b"nope")],
    )
    with pytest.raises(MODULE.BlindArtifactPackError, match="unsafe member path"):
        _generate(tmp_path, artifact)


def test_duplicate_member_fails_closed(tmp_path: Path) -> None:
    with pytest.warns(UserWarning, match="Duplicate name"):
        artifact = _build_artifact(
            tmp_path,
            extra_members=[(_regular_info("live-source.json"), b"duplicate")],
        )
    with pytest.raises(MODULE.BlindArtifactPackError, match="duplicate member"):
        _generate(tmp_path, artifact)


def test_symlink_member_fails_closed(tmp_path: Path) -> None:
    info = zipfile.ZipInfo("source/netto/link.pdf")
    info.create_system = 3
    info.external_attr = (stat.S_IFLNK | 0o777) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    artifact = _build_artifact(tmp_path, extra_members=[(info, b"target")])
    with pytest.raises(MODULE.BlindArtifactPackError, match="not a regular file"):
        _generate(tmp_path, artifact)


def test_v2_result_identity_mismatch_fails_closed(tmp_path: Path) -> None:
    artifact = _build_artifact(tmp_path)
    with pytest.raises(MODULE.BlindArtifactPackError, match="v2 capture result identity mismatch"):
        MODULE.generate_from_artifact(
            Path(artifact["path"]),
            tmp_path / "review-pack",
            artifact_id=ARTIFACT_ID,
            workflow_run_id=RUN_ID,
            expected_artifact_sha256=str(artifact["sha"]),
            expected_commit=COMMIT,
            expected_campaign="hz35_wrong",
            expected_valid_from=VALID_FROM,
            expected_valid_until=VALID_UNTIL,
            expected_source_sha256=SOURCE_SHA,
            expected_pdf_sha256=str(artifact["pdf_sha"]),
            expected_freeze_manifest_sha256=FREEZE_SHA,
            expected_v2_freeze_manifest_sha256=V2_FREEZE_SHA,
            expected_page_count=2,
        )


def test_adapter_source_never_extracts_candidate_payload_files() -> None:
    text = TOOL.read_text(encoding="utf-8")
    assert "FORBIDDEN_REVIEWER_MEMBERS" in text
    assert "for name in INTERNAL_METADATA_MEMBERS" in text
    assert "_copy_member(archive, archive.getinfo(pdf_name)" in text
    assert '_copy_member(archive, archive.getinfo("capture/predictions.json")' not in text
    assert '_copy_member(archive, archive.getinfo("capture/candidate-provenance.json")' not in text
