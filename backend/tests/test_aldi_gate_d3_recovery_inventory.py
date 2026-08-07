from __future__ import annotations

from hashlib import sha256
import importlib.util
import json
from pathlib import Path
import tarfile

ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "aldi_gate_d3_recovery_inventory.py"
SPEC = importlib.util.spec_from_file_location("aldi_gate_d3_recovery_inventory", TOOL)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


def image_bytes(page: int) -> bytes:
    return b"\xff\xd8" + bytes([page % 251]) * 10050


def make_family(root: Path, prefix: str = "moved/run") -> Path:
    page_images = root / prefix / "raw" / "page-images"
    for label, count in (("current", 49), ("preview", 41)):
        directory = page_images / label
        directory.mkdir(parents=True, exist_ok=True)
        for page in range(1, count + 1):
            (directory / f"page-{page:03d}.img").write_bytes(image_bytes(page))
    return page_images


def test_directory_family_is_recovered_without_original_a30_path(tmp_path: Path):
    make_family(tmp_path)
    payload = MODULE.build_inventory(tmp_path)
    assert payload["decision"] == "RECOVERY_CANDIDATE_FOUND"
    assert payload["directory_candidate_count"] == 1
    assert payload["complete_recovery_source_count"] == 1
    assert payload["distinct_complete_identity_count"] == 1
    assert payload["complete_recovery_sources"][0]["source"] == "moved/run/raw/page-images"
    assert payload["raw_evidence_exported"] is False
    assert payload["safety"]["manifest_regeneration_authorized"] is False


def test_partial_directory_is_not_promoted(tmp_path: Path):
    page_images = make_family(tmp_path)
    (page_images / "preview" / "page-041.img").unlink()
    payload = MODULE.build_inventory(tmp_path)
    assert payload["decision"] == "NO_RECOVERY_CANDIDATE"
    assert payload["directory_candidate_count"] == 1
    assert payload["directory_candidates"][0]["preview_count"] == 40


def test_manifest_outside_original_path_is_inventory_only(tmp_path: Path):
    path = tmp_path / "elsewhere" / "reports" / "page-image-manifest.json"
    path.parent.mkdir(parents=True)
    path.write_text(json.dumps({"rows": [{"label": "current"}, {"label": "preview"}]}) + "\n")
    payload = MODULE.build_inventory(tmp_path)
    assert payload["manifest_count"] == 1
    assert payload["manifests"][0]["path"] == "elsewhere/reports/page-image-manifest.json"
    assert payload["decision"] == "NO_RECOVERY_CANDIDATE"


def test_safe_tar_family_is_detected_without_extraction(tmp_path: Path):
    source = tmp_path / "source"
    page_images = make_family(source, "legacy")
    archive = tmp_path / "retained-a30.tar.gz"
    with tarfile.open(archive, "w:gz") as tar:
        tar.add(page_images.parent.parent, arcname="backup/legacy")
    payload = MODULE.build_inventory(tmp_path)
    archive_rows = [item for item in payload["archives"] if item["path"] == "retained-a30.tar.gz"]
    assert len(archive_rows) == 1
    assert archive_rows[0]["safe"] is True
    assert archive_rows[0]["complete_49_plus_41_count"] == 1
    assert payload["decision"] == "RECOVERY_CANDIDATE_FOUND"


def test_unsafe_tar_symlink_is_rejected(tmp_path: Path):
    archive = tmp_path / "unsafe.tgz"
    with tarfile.open(archive, "w:gz") as tar:
        info = tarfile.TarInfo("x/link")
        info.type = tarfile.SYMTYPE
        info.linkname = "/etc/passwd"
        tar.addfile(info)
    payload = MODULE.build_inventory(tmp_path)
    row = next(item for item in payload["archives"] if item["path"] == "unsafe.tgz")
    assert row["safe"] is False
    assert row["unsafe_reason"] == "unsafe_member_type"


def test_exact_a21_archive_is_never_a_recovery_candidate(tmp_path: Path, monkeypatch):
    archive = tmp_path / "hermes-deals-aldi-a21-20260801T100533Z.tar.gz"
    archive.write_bytes(b"a21")
    monkeypatch.setattr(MODULE, "A21_ARCHIVE_SHA256", sha256(b"a21").hexdigest())
    payload = MODULE.build_inventory(tmp_path)
    row = payload["archives"][0]
    assert row["is_a21_archive"] is True
    assert payload["complete_recovery_source_count"] == 0
    assert payload["decision"] == "NO_RECOVERY_CANDIDATE"
