from __future__ import annotations

import io
from pathlib import Path
import sys
import tarfile

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

import edeka_live_provenance_derivation as derivation  # noqa: E402


def _add_file(archive: tarfile.TarFile, name: str, payload: bytes) -> None:
    info = tarfile.TarInfo(name=name)
    info.size = len(payload)
    archive.addfile(info, io.BytesIO(payload))


def test_safe_extract_member_count_tracks_regular_files_not_directories(
    tmp_path: Path,
) -> None:
    archive_path = tmp_path / "evidence.tar.gz"
    with tarfile.open(archive_path, "w:gz") as archive:
        for directory in (
            "run",
            "run/cycle",
            "run/cycle/raw",
            "run/cycle/raw/edeka",
        ):
            info = tarfile.TarInfo(name=directory)
            info.type = tarfile.DIRTYPE
            archive.addfile(info)
        _add_file(archive, "run/registered-commit.txt", b"commit\n")
        _add_file(archive, "run/cycle/cycle-evidence.json", b"{}\n")

    extracted_root, member_count = derivation._safe_extract_archive(
        archive_path,
        tmp_path / "out",
    )

    # The RPi5 dispatcher manifest records regular-file members only. Directory
    # entries are still validated and extracted, but must not inflate this count.
    assert member_count == 2
    assert (extracted_root / "registered-commit.txt").is_file()
    assert (extracted_root / "cycle" / "cycle-evidence.json").is_file()
    assert (extracted_root / "cycle" / "raw" / "edeka").is_dir()
