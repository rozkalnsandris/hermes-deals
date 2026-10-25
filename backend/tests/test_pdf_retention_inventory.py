from __future__ import annotations

import errno
from importlib.util import module_from_spec, spec_from_file_location
import json
import os
from pathlib import Path
import subprocess
import sys

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "pdf_retention_inventory.py"
spec = spec_from_file_location("pdf_retention_inventory", TOOL)
assert spec and spec.loader
inventory = module_from_spec(spec)
spec.loader.exec_module(inventory)
PDF = b"%PDF-1.7\nsynthetic inventory fixture, not a parsed document\n"


def test_disguised_pdf_and_duplicate_copies_have_no_invented_age(tmp_path):
    first, second = tmp_path / "first", tmp_path / "second"
    first.mkdir()
    second.mkdir()
    (first / "source.bin").write_bytes(PDF)
    (second / "booklet.pdf").write_bytes(PDF)
    os.utime(first / "source.bin", (1, 1))
    os.utime(second / "booklet.pdf", (100000, 100000))
    (first / "metadata.json").write_text('{"dateTime":"2026-10-25T00:00:00Z"}')
    report = inventory.inventory([second, first])
    assert report == inventory.inventory([first, second])
    assert report["status"] == "inventory_complete"
    assert len(report["assets"]) == 1
    asset = report["assets"][0]
    assert asset["kind"] == "pdf"
    assert asset["bytes"] == len(PDF)
    assert asset["copies"] == [{"root": 0, "path": "source.bin"}, {"root": 1, "path": "booklet.pdf"}]
    assert asset["first_acquired_at"] is None
    assert asset["expires_at"] is None
    assert report["retention_compliance"] == "unknown"
    assert report["deletion_authorized"] is False


def test_archive_and_image_are_unresolved_not_proven_pdf_copies(tmp_path):
    (tmp_path / "hidden.bin").write_bytes(b"PK\x03\x04archive not extracted")
    (tmp_path / "page.bin").write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")
    report = inventory.inventory([tmp_path])
    assert {row["kind"] for row in report["assets"]} == {"archive_uninspected", "image_candidate"}
    assert report["archive_contents_inspected"] is False
    assert report["image_parent_bindings_verified"] is False
    assert report["all_storage_locations_verified"] is False


def test_symlinks_and_fifo_are_not_followed_or_opened(tmp_path):
    root, outside = tmp_path / "root", tmp_path / "outside"
    root.mkdir()
    outside.mkdir()
    (outside / "secret.pdf").write_bytes(PDF)
    (root / "file.pdf").symlink_to(outside / "secret.pdf")
    (root / "directory").symlink_to(outside, target_is_directory=True)
    os.mkfifo(root / "pipe")
    report = inventory.inventory([root])
    assert report["assets"] == []
    assert report["status"] == "inventory_partial"
    assert [row["reason"] for row in report["findings"]].count("symlink_skipped") == 2
    assert any(row["reason"] == "nonregular_skipped" for row in report["findings"])


@pytest.mark.parametrize("case", ["relative", "filesystem", "overlap", "symlink", "ancestor"])
def test_unsafe_or_overlapping_roots_rejected(tmp_path, case):
    root = tmp_path / "root"
    root.mkdir()
    child = root / "child"
    child.mkdir()
    link = tmp_path / "alias"
    link.symlink_to(root, target_is_directory=True)
    roots = {
        "relative": [Path("relative")], "filesystem": [Path("/")],
        "overlap": [root, child], "symlink": [link], "ancestor": [link / "child"],
    }[case]
    with pytest.raises(ValueError):
        inventory.inventory(roots)


@pytest.mark.parametrize("limits,reason", [
    ({"max_file_bytes": 1}, "file_size_limit"),
    ({"max_total_bytes": 1}, "total_read_limit"),
    ({"max_files": 1}, "entry_limit"),
])
def test_limits_report_partial_inventory(tmp_path, limits, reason):
    (tmp_path / "a.pdf").write_bytes(PDF)
    (tmp_path / "b.pdf").write_bytes(PDF)
    report = inventory.inventory([tmp_path], **limits)
    assert report["status"] == "inventory_partial"
    assert any(row["reason"] == reason for row in report["findings"])
    assert report["retention_compliance"] == "unknown"


def test_read_failure_does_not_hide_other_files(tmp_path, monkeypatch):
    (tmp_path / "blocked.pdf").write_bytes(PDF)
    (tmp_path / "good.pdf").write_bytes(PDF + b"good")
    original_open = os.open

    def selective_open(path, *args, **kwargs):
        if path == "blocked.pdf":
            raise PermissionError(errno.EACCES, "fixture denial")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(inventory.os, "open", selective_open)
    report = inventory.inventory([tmp_path])
    assert report["status"] == "inventory_partial"
    assert report["findings"][0]["reason"] == f"read_error:{errno.EACCES}"
    assert report["assets"][0]["copies"] == [{"root": 0, "path": "good.pdf"}]


def test_change_during_hash_is_reported(tmp_path, monkeypatch):
    path = tmp_path / "source.pdf"
    path.write_bytes(PDF)
    original_fstat = os.fstat
    inode = path.stat().st_ino
    seen = 0

    def changed_fstat(fd):
        nonlocal seen
        result = original_fstat(fd)
        if result.st_ino == inode:
            seen += 1
            if seen == 1:
                os.utime(path, ns=(result.st_atime_ns, result.st_mtime_ns + 1000000000))
        return result

    monkeypatch.setattr(inventory.os, "fstat", changed_fstat)
    report = inventory.inventory([tmp_path])
    assert report["assets"] == []
    assert report["findings"][0]["reason"] == "file_changed"


def test_invalid_pdf_is_not_silently_ignored(tmp_path):
    (tmp_path / "source.pdf").write_bytes(b"HTML instead of PDF")
    report = inventory.inventory([tmp_path])
    assert report["status"] == "inventory_partial"
    assert report["assets"][0]["kind"] == "invalid_pdf_header"


def test_cli_outputs_json_and_leaves_input_contents_and_mtime_unchanged(tmp_path):
    path = tmp_path / "source.pdf"
    path.write_bytes(PDF)
    before = path.stat()
    result = subprocess.run([sys.executable, str(TOOL), str(tmp_path)], text=True, capture_output=True, timeout=10)
    assert result.returncode == 0, result.stderr
    assert json.loads(result.stdout)["assets"][0]["kind"] == "pdf"
    assert sorted(p.name for p in tmp_path.iterdir()) == ["source.pdf"]
    assert path.read_bytes() == PDF
    assert path.stat().st_mtime_ns == before.st_mtime_ns
    failed = subprocess.run([sys.executable, str(TOOL), str(tmp_path), "--max-total-bytes", "1"],
                            text=True, capture_output=True, timeout=10)
    assert failed.returncode == 2
    assert json.loads(failed.stdout)["status"] == "inventory_partial"
