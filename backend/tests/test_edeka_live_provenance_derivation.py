from __future__ import annotations

from hashlib import sha256
import importlib.util
import io
import json
from pathlib import Path
import shutil
import sys
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import edeka_live_provenance_derivation as derivation  # noqa: E402

BRIDGE_TEST = ROOT / "backend/tests/test_edeka_live_provenance_bridge.py"
WORKFLOW = ROOT / ".github/workflows/edeka-live-provenance-derivation.yml"


def _load_bridge_test_module():
    spec = importlib.util.spec_from_file_location("edeka_bridge_fixture_module", BRIDGE_TEST)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def _sha256_file(path: Path) -> str:
    return sha256(path.read_bytes()).hexdigest()


def _write_sha256s(root: Path, relative_paths: list[str]) -> None:
    lines = []
    for relative in relative_paths:
        path = root / relative
        lines.append(f"{_sha256_file(path)}  {relative}")
    (root / "SHA256SUMS").write_text("\n".join(lines) + "\n", encoding="utf-8")


def _build_artifact(tmp_path: Path) -> tuple[Path, dict[str, object]]:
    fixture = _load_bridge_test_module()
    cycle_source = fixture._make_cycle(tmp_path / "fixture")

    source_commit = "7" * 40
    source_run_id = 123456789
    source_run_attempt = 1
    artifact_id = 987654321
    artifact_name = f"edeka-shadow-cycle-{source_commit}-run-{source_run_id}"
    artifact_digest = "sha256:" + "8" * 64

    inner_root = tmp_path / "inner" / "20260807T000000Z-777777777777"
    inner_root.mkdir(parents=True)
    shutil.copytree(cycle_source, inner_root / "cycle")
    (inner_root / "registered-commit.txt").write_text(source_commit + "\n", encoding="utf-8")
    (inner_root / "capture-exit-code.txt").write_text("0\n", encoding="utf-8")
    (inner_root / "run-request.txt").write_text(
        "runner_version=edeka-shadow-cycle-v01\n"
        f"registered_commit={source_commit}\n"
        "production_database_write=false\n",
        encoding="utf-8",
    )
    (inner_root / "safety-result.txt").write_text(
        "PRIMARY_WORKTREE_MODIFIED=false\n"
        "PRIMARY_GIT_INDEX_UNCHANGED=true\n"
        "AUDIT_GIT_INDEX_UNCHANGED=true\n"
        "PRODUCTION_DATABASE_WRITE=false\n"
        "PRODUCTION_DEPLOYMENT=false\n"
        "SCHEDULER_ACTIVATION=false\n",
        encoding="utf-8",
    )
    (inner_root / "python-packages.txt").write_text("fixture==1\n", encoding="utf-8")

    cycle_files = [
        "cycle-evidence.json",
        "normalization-report.json",
        "shadow.sqlite3",
    ]
    raw_files = sorted(
        path.relative_to(inner_root / "cycle").as_posix()
        for path in (inner_root / "cycle" / "raw").rglob("*")
        if path.is_file()
    )
    _write_sha256s(inner_root / "cycle", cycle_files + raw_files)
    _write_sha256s(
        inner_root,
        [
            "registered-commit.txt",
            "capture-exit-code.txt",
            "run-request.txt",
            "safety-result.txt",
            "python-packages.txt",
            "cycle/cycle-evidence.json",
            "cycle/normalization-report.json",
            "cycle/shadow.sqlite3",
            "cycle/SHA256SUMS",
        ],
    )

    artifact_root = tmp_path / "artifact"
    audit_root = artifact_root / "audit-evidence"
    audit_root.mkdir(parents=True)
    (artifact_root / "runner-request.txt").write_text(
        "audit=edeka-shadow-cycle\n"
        f"commit_sha={source_commit}\n"
        f"run_id={source_run_id}\n"
        f"run_attempt={source_run_attempt}\n",
        encoding="utf-8",
    )
    (artifact_root / "runner-dispatch-exit-code.txt").write_text("0\n", encoding="utf-8")
    (artifact_root / "runner-dispatch.log").write_text(
        "AUDIT=edeka-shadow-cycle\nAUDIT_EXIT_CODE=0\n",
        encoding="utf-8",
    )

    archive_name = "hermes-deals-edeka-shadow-fixture.tar.gz"
    archive_path = audit_root / archive_name
    with tarfile.open(archive_path, "w:gz") as archive:
        archive.add(inner_root, arcname=inner_root.name, recursive=True)
    with tarfile.open(archive_path, "r:gz") as archive:
        member_count = sum(member.isfile() for member in archive.getmembers())
    archive_sha = _sha256_file(archive_path)

    dispatcher = {
        "schema_version": 1,
        "audit": "edeka-shadow-cycle",
        "audit_exit_code": 0,
        "commit_sha": source_commit,
        "production_apply_authorized": False,
        "sanitization_passed": True,
        "archive": {
            "bytes": archive_path.stat().st_size,
            "member_count": member_count,
            "name": archive_name,
            "offer_count": 2,
            "sha256": archive_sha,
        },
    }
    (audit_root / "dispatcher-evidence-manifest.json").write_text(
        json.dumps(dispatcher, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (audit_root / f"{archive_name}.sha256").write_text(
        f"{archive_sha}  /fixture/{archive_name}\n",
        encoding="utf-8",
    )
    (audit_root / "safety-result.txt").write_text(
        "PRIMARY_WORKTREE_MODIFIED=false\n"
        "PRIMARY_GIT_INDEX_UNCHANGED=true\n"
        "AUDIT_GIT_INDEX_UNCHANGED=true\n"
        "PRODUCTION_DATABASE_WRITE=false\n"
        "PRODUCTION_DEPLOYMENT=false\n"
        "SCHEDULER_ACTIVATION=false\n",
        encoding="utf-8",
    )
    (audit_root / "audit-exit-code.txt").write_text("0\n", encoding="utf-8")
    shutil.copy2(inner_root / "cycle" / "cycle-evidence.json", audit_root / "cycle-evidence.json")
    shutil.copy2(
        inner_root / "cycle" / "normalization-report.json",
        audit_root / "normalization-report.json",
    )

    metadata = {
        "source_run_id": source_run_id,
        "source_run_attempt": source_run_attempt,
        "artifact_id": artifact_id,
        "artifact_name": artifact_name,
        "artifact_digest": artifact_digest,
        "source_commit": source_commit,
    }
    return artifact_root, metadata


def test_derivation_builds_sanitized_gate_c_attestation(tmp_path: Path) -> None:
    artifact_root, metadata = _build_artifact(tmp_path)
    output = tmp_path / "output"

    result = derivation.derive_live_provenance_from_artifact(
        artifact_root,
        output,
        source_run_id=metadata["source_run_id"],
        source_run_attempt=metadata["source_run_attempt"],
        artifact_id=metadata["artifact_id"],
        artifact_name=metadata["artifact_name"],
        artifact_digest=metadata["artifact_digest"],
        derivation_commit="9" * 40,
    )

    assert result["result"] == "pass"
    assert result["candidate_count"] == 2
    assert result["automatic_candidate_count"] == 1
    assert result["review_required_count"] == 1
    assert result["production_database_write"] is False
    assert result["production_deployment"] is False

    attestation = json.loads((output / "derivation-attestation.json").read_text())
    assert attestation["source"]["workflow_run_id"] == metadata["source_run_id"]
    assert attestation["source"]["registered_commit"] == metadata["source_commit"]
    assert attestation["derivation"]["candidate_count"] == 2
    assert attestation["derivation"]["all_candidates_provenance_bound"] is True
    assert attestation["derivation"]["promotion_ready"] is False
    assert attestation["safety"]["source_refetch"] is False
    assert attestation["safety"]["production_apply_authorized"] is False

    provenance = json.loads((output / "edeka-live-candidate-provenance.json").read_text())
    assert provenance["live_evidence"]["source_document_kind"] == "html_offer_cards"
    assert len(provenance["candidates"]) == 2
    assert (output / "SHA256SUMS").is_file()


def test_derivation_rejects_artifact_name_run_mismatch(tmp_path: Path) -> None:
    artifact_root, metadata = _build_artifact(tmp_path)

    with pytest.raises(
        derivation.EdekaLiveProvenanceDerivationError,
        match="artifact name/run binding mismatch",
    ):
        derivation.derive_live_provenance_from_artifact(
            artifact_root,
            tmp_path / "output",
            source_run_id=metadata["source_run_id"] + 1,
            source_run_attempt=metadata["source_run_attempt"],
            artifact_id=metadata["artifact_id"],
            artifact_name=metadata["artifact_name"],
            artifact_digest=metadata["artifact_digest"],
            derivation_commit="9" * 40,
        )


def test_safe_extractor_rejects_symlink_member(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        directory = tarfile.TarInfo("root/")
        directory.type = tarfile.DIRTYPE
        archive.addfile(directory)
        link = tarfile.TarInfo("root/link")
        link.type = tarfile.SYMTYPE
        link.linkname = "/etc/passwd"
        archive.addfile(link)

    with pytest.raises(
        derivation.EdekaLiveProvenanceDerivationError,
        match="unsafe inner archive member type",
    ):
        derivation._safe_extract_archive(archive_path, tmp_path / "extract")


def test_safe_extractor_rejects_parent_traversal(tmp_path: Path) -> None:
    archive_path = tmp_path / "unsafe-traversal.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        payload = b"blocked"
        member = tarfile.TarInfo("root/../escape.txt")
        member.size = len(payload)
        archive.addfile(member, io.BytesIO(payload))

    with pytest.raises(
        derivation.EdekaLiveProvenanceDerivationError,
        match="unsafe inner archive path",
    ):
        derivation._safe_extract_archive(archive_path, tmp_path / "extract")


def test_workflow_is_owner_only_main_and_reuses_successful_shadow_artifact() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert 'os.environ["ACTOR"] != "rozkalnsandris"' in text
    assert 'os.environ["ACTOR_ID"] != "277435981"' in text
    assert 'os.environ["REF"] != "refs/heads/main"' in text
    assert 'run.get("name") != "EDEKA shadow cycle RPi5 audit"' in text
    assert 'run.get("conclusion") != "success"' in text
    assert "actions/download-artifact@v6" in text
    assert "github-token: ${{ github.token }}" in text
    assert "run-id: ${{ inputs.source_run_id }}" in text
    assert "71ce804f9b9e2a0e7810fa1f035cb6e27592f45f" in text
    assert "runs-on: [self-hosted" not in text


def test_workflow_uploads_only_sanitized_files_not_extracted_source() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "Upload sanitized provenance only" in text
    assert "edeka-live-candidate-provenance.json" in text
    assert "derivation-attestation.json" in text
    assert "SHA256SUMS" in text
    assert "edeka-live-provenance-result.json" in text
    assert "Raw HTML / SQLite uploaded in derived artifact: **false**" in text
    assert "${{ steps.derive.outputs.output_dir }}/extracted" not in text
    assert "path: ${{ steps.derive.outputs.output_dir }}\n" not in text
