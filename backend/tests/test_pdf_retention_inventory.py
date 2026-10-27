from __future__ import annotations

import errno
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from hashlib import sha256
from types import SimpleNamespace
from uuid import uuid4
from importlib.util import module_from_spec, spec_from_file_location
import json
from io import BytesIO
import zipfile
import os
from pathlib import Path
import subprocess
import sys

import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models import PdfAcquisition
from app.pdf_retention import register_pdf_acquisition

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

def test_zip_containing_uncompressed_pdf_is_not_a_pdf(tmp_path):
    archive = BytesIO()
    with zipfile.ZipFile(archive, "w", compression=zipfile.ZIP_STORED) as handle:
        handle.writestr("source.pdf", PDF)
    assert b"%PDF-" in archive.getvalue()[:1024]
    (tmp_path / "source.bin").write_bytes(archive.getvalue())
    report = inventory.inventory([tmp_path])
    assert report["assets"][0]["kind"] == "archive_uninspected"
    assert report["archive_contents_inspected"] is False


def test_budget_counts_full_hash_and_stops_before_next_candidate(tmp_path):
    (tmp_path / "a.bin").write_bytes(PDF + b"x" * 5000)
    (tmp_path / "b.bin").write_bytes(PDF)
    report = inventory.inventory([tmp_path], max_total_bytes=len(PDF) + 5000)
    assert report["read_bytes"] == len(PDF) + 5000
    assert len(report["assets"]) == 1
    assert report["status"] == "inventory_partial"


NOW = datetime(2026, 10, 27, 12, tzinfo=timezone.utc)


@pytest.fixture
def registry_case(tmp_path):
    from app.db import engine as configured_engine

    if configured_engine.dialect.name == "postgresql":
        engine = configured_engine
    else:
        engine = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / 'registry.db'}")
        PdfAcquisition.__table__.create(engine)
    root = tmp_path / "raw"
    root.mkdir()
    data = PDF + uuid4().hex.encode()
    (root / "first.pdf").write_bytes(data)
    (root / "second.bin").write_bytes(data)
    report = inventory.inventory([root])
    ctx = SimpleNamespace(engine=engine, root=root, report=report,
                          sha=sha256(data).hexdigest(), shas=set())
    yield ctx
    with engine.begin() as connection:
        if ctx.shas:
            connection.execute(sa.delete(PdfAcquisition).where(PdfAcquisition.pdf_sha256.in_(ctx.shas)))
    if engine is not configured_engine:
        engine.dispose()


def acquire(ctx, acquired_at, *, ref="synthetic-acquisition", digest=None):
    digest = digest or ctx.sha
    ctx.shas.add(digest)
    with Session(ctx.engine) as db:
        register_pdf_acquisition(
            db, pdf_sha256=digest, evidence_ref=ref, acquired_at=acquired_at,
            recorded_at=max(NOW + timedelta(days=40), acquired_at or NOW),
        )
        db.commit()


def annotated(ctx, *, as_of=NOW, report=None):
    with Session(ctx.engine) as db:
        return inventory.retention_report(ctx.report if report is None else report, db, as_of=as_of)


@pytest.mark.parametrize("age,state", [
    (timedelta(days=-1), "not_yet_acquired"),
    (timedelta(days=29), "within_retention"),
    (timedelta(days=30, microseconds=-1), "within_retention"),
    (timedelta(days=30), "raw_expired"),
    (timedelta(days=31), "raw_expired"),
])
def test_registry_report_shared_deadline_for_every_copy(registry_case, age, state):
    ctx = registry_case
    acquire(ctx, NOW - age)
    before = deepcopy(ctx.report)
    result = annotated(ctx)
    asset = result["assets"][0]
    assert result["schema_version"] == 2
    assert result["registry_checked_at"] == NOW.isoformat()
    assert asset["acquisition_status"] == state
    assert asset["first_acquired_at"] == (NOW - age).isoformat()
    assert asset["expires_at"] == (NOW - age + timedelta(days=30)).isoformat()
    assert len(asset["copies"]) == 2
    assert ctx.report == before  # The original filesystem-only observation survives.
    assert result["retention_compliance"] == "unknown"
    assert result["deletion_authorized"] is False
    assert result["all_storage_locations_verified"] is False
    with Session(ctx.engine) as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(PdfAcquisition).where(
            PdfAcquisition.pdf_sha256 == ctx.sha)) == 1


def test_registry_report_redownload_and_new_mtime_do_not_renew_expiry(registry_case):
    ctx = registry_case
    acquire(ctx, NOW - timedelta(days=31))
    acquire(ctx, NOW, ref="later-download")
    os.utime(ctx.root / "first.pdf", (NOW.timestamp(), NOW.timestamp()))
    before = {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in ctx.root.iterdir()}
    result = annotated(ctx, report=inventory.inventory([ctx.root]))
    assert result["assets"][0]["acquisition_status"] == "raw_expired"
    assert result["assets"][0]["expires_at"] == (NOW - timedelta(days=1)).isoformat()
    assert {p.name: (p.read_bytes(), p.stat().st_mtime_ns) for p in ctx.root.iterdir()} == before


@pytest.mark.parametrize("observations,state,expiry", [
    ([], "unregistered", None),
    ([None], "acquisition_unknown", None),
    ([None, NOW], "acquisition_unknown", NOW + timedelta(days=30)),
    ([None, NOW - timedelta(days=30)], "raw_expired", NOW),
])
def test_registry_report_preserves_unknown_age(registry_case, observations, state, expiry):
    ctx = registry_case
    for index, acquired in enumerate(observations):
        acquire(ctx, acquired, ref=f"evidence-{index}")
    asset = annotated(ctx)["assets"][0]
    assert asset["acquisition_status"] == state
    assert asset["first_acquired_at"] is None
    assert asset["expires_at"] == (expiry.isoformat() if expiry else None)


def test_registry_report_does_not_promote_images_archives_or_invalid_pdf(registry_case):
    ctx = registry_case
    (ctx.root / "page.png").write_bytes(b"\x89PNG\r\n\x1a\nsynthetic")
    (ctx.root / "archive.zip").write_bytes(b"PK\x03\x04synthetic")
    (ctx.root / "invalid.pdf").write_bytes(b"not PDF")
    report = inventory.inventory([ctx.root])
    for row in report["assets"]:
        acquire(ctx, NOW - timedelta(days=31), digest=row["sha256"])
    result = annotated(ctx, report=report)
    assert result["status"] == "inventory_partial"
    for asset in result["assets"]:
        if asset["kind"] == "pdf":
            assert asset["acquisition_status"] == "raw_expired"
        else:
            assert asset["acquisition_status"] == "unknown"
            assert asset["expires_at"] is None
    assert result["archive_contents_inspected"] is False
    assert result["image_parent_bindings_verified"] is False


def test_registry_report_preserves_partial_findings(registry_case):
    ctx = registry_case
    report = inventory.inventory([ctx.root], max_files=1)
    acquire(ctx, NOW - timedelta(days=31))
    result = annotated(ctx, report=report)
    assert result["status"] == "inventory_partial"
    assert result["findings"] == report["findings"]
    assert result["assets"][0]["acquisition_status"] == "raw_expired"


def test_registry_report_does_not_flush_callers_pending_rows(registry_case):
    ctx = registry_case
    with Session(ctx.engine) as db:
        pending = PdfAcquisition(pdf_sha256=ctx.sha, evidence_ref="pending",
                                 acquired_at=NOW, recorded_at=NOW)
        db.add(pending)
        result = inventory.retention_report(ctx.report, db, as_of=NOW)
        assert result["assets"][0]["acquisition_status"] == "unregistered"
        assert pending in db.new
    with Session(ctx.engine) as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(PdfAcquisition).where(
            PdfAcquisition.pdf_sha256 == ctx.sha)) == 0


def test_registry_report_query_failure_preserves_input(registry_case, monkeypatch):
    import app.pdf_retention as registry
    ctx = registry_case
    before = deepcopy(ctx.report)

    def fail(*args, **kwargs):
        raise RuntimeError("injected lookup failure")

    monkeypatch.setattr(registry, "pdf_retention", fail)
    with pytest.raises(RuntimeError, match="lookup failure"):
        annotated(ctx)
    assert ctx.report == before


def test_registry_report_rejects_naive_time_even_without_pdf(registry_case):
    ctx = registry_case
    empty = {**ctx.report, "assets": []}
    with pytest.raises(ValueError, match="timezone"):
        annotated(ctx, report=empty, as_of=NOW.replace(tzinfo=None))


def test_inventory_default_cli_stays_stdlib_only(tmp_path):
    (tmp_path / "source.pdf").write_bytes(PDF)
    # -S disables site-packages, including the optional registry dependencies.
    result = subprocess.run([sys.executable, "-S", str(TOOL), str(tmp_path)],
                            text=True, capture_output=True, timeout=10,
                            env={**os.environ, "DATABASE_URL": "invalid-must-not-be-read"})
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["schema_version"] == 1
    assert "registry_checked_at" not in report


@pytest.mark.parametrize("url", ["", "invalid-secret-marker", "sqlite:///must-not-create.db"])
def test_registry_cli_invalid_config_has_no_json_or_secret(tmp_path, url):
    (tmp_path / "source.pdf").write_bytes(PDF)
    result = subprocess.run([sys.executable, str(TOOL), str(tmp_path), "--with-registry"],
                            text=True, capture_output=True, timeout=15, cwd=tmp_path,
                            env={**os.environ, "DATABASE_URL": url})
    assert result.returncode == 2
    assert result.stdout == ""
    assert "registry lookup failed" in result.stderr
    assert "invalid-secret-marker" not in result.stderr
    assert sorted(p.name for p in tmp_path.iterdir()) == ["source.pdf"]


def test_registry_cli_failure_never_prints_partial_json_or_credentials(tmp_path, monkeypatch, capsys):
    (tmp_path / "source.pdf").write_bytes(PDF)

    def fail(report, database_url):
        report["registry_checked_at"] = "partial"
        raise RuntimeError("postgresql://name:private-secret@private-host/database")

    monkeypatch.setattr(inventory, "registry_report", fail)
    monkeypatch.setattr(sys, "argv", [str(TOOL), str(tmp_path), "--with-registry"])
    with pytest.raises(SystemExit) as error:
        inventory.main()
    assert error.value.code == 2
    output = capsys.readouterr()
    assert output.out == ""
    assert "registry lookup failed" in output.err
    assert "private-" not in output.err


def test_postgresql_registry_connection_is_readonly_and_repeatable(registry_case, monkeypatch):
    ctx = registry_case
    if ctx.engine.dialect.name != "postgresql":
        pytest.skip("requires the PostgreSQL 18 CI service")
    acquire(ctx, NOW - timedelta(days=31))
    original = inventory.retention_report

    def inspect_transaction(report, db, *, as_of):
        assert db.scalar(sa.text("SHOW transaction_read_only")) == "on"
        assert db.scalar(sa.text("SHOW transaction_isolation")) == "repeatable read"
        assert db.scalar(sa.text("SHOW statement_timeout")) == "10s"
        with pytest.raises(sa.exc.DBAPIError):
            with db.begin_nested():
                db.execute(sa.update(PdfAcquisition).where(
                    PdfAcquisition.pdf_sha256 == ctx.sha).values(acquired_at=NOW))
        return original(report, db, as_of=NOW)

    monkeypatch.setattr(inventory, "retention_report", inspect_transaction)
    result = inventory.registry_report(ctx.report, os.environ["DATABASE_URL"])
    assert result["assets"][0]["acquisition_status"] == "raw_expired"
    with Session(ctx.engine) as db:
        assert db.scalar(sa.select(PdfAcquisition.acquired_at).where(
            PdfAcquisition.pdf_sha256 == ctx.sha)) == NOW - timedelta(days=31)


def test_postgresql_registry_cli_success_and_partial_exit(registry_case):
    ctx = registry_case
    if ctx.engine.dialect.name != "postgresql":
        pytest.skip("requires the PostgreSQL 18 CI service")
    acquire(ctx, datetime.now(timezone.utc) - timedelta(days=31))
    for extra, expected_code in [([], 0), (["--max-files", "1"], 2)]:
        result = subprocess.run(
            [sys.executable, str(TOOL), str(ctx.root), "--with-registry", *extra],
            text=True, capture_output=True, timeout=20,
        )
        assert result.returncode == expected_code, result.stderr
        report = json.loads(result.stdout)
        assert report["assets"][0]["acquisition_status"] == "raw_expired"
        assert report["deletion_authorized"] is False
        assert report["status"] == ("inventory_complete" if expected_code == 0 else "inventory_partial")


def test_registry_missing_schema_does_not_create_it(registry_case):
    empty = sa.create_engine("sqlite+pysqlite:///:memory:")
    before = deepcopy(registry_case.report)
    try:
        with Session(empty) as db:
            with pytest.raises(sa.exc.OperationalError):
                inventory.retention_report(before, db, as_of=NOW)
        assert sa.inspect(empty).get_table_names() == []
        assert before == registry_case.report
    finally:
        empty.dispose()
