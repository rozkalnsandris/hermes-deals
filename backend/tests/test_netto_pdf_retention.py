"""Netto admission uses real PDF bytes, files and isolated database transactions."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from pypdf import PdfWriter
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app import netto_store_prospect as netto
from app.models import PdfAcquisition, SourceSnapshot
from app.pdf_retention import pdf_retention, register_pdf_acquisition
from app.source_config import SourceConfig

NOW = datetime(2026, 10, 25, 12, tzinfo=timezone.utc)


@pytest.fixture
def context(tmp_path, monkeypatch):
    from app.db import engine as configured_engine

    token = uuid4().hex
    source = SourceConfig(
        chain="netto", enabled=True, priority=1,
        url=f"https://example.invalid/{token}/5659",
        scope="family_primary_netto", notes="fixture", keywords=(),
        store_external_id="5659", store_name="Netto fixture",
    )
    output = BytesIO()
    writer = PdfWriter()
    writer.add_blank_page(width=100, height=100)
    writer.add_metadata({"/Title": token})
    writer.write(output)
    bundle = netto.NettoStoreProspectBundle(
        store_url=source.url, prospect_url="https://example.invalid/hz43",
        prospect_slug="hz43", store_html=b"<html>offers</html>",
        prospect_html=b"<html>viewer</html>",
        valid_from=date(2026, 10, 19), valid_until=date(2026, 10, 24),
        validity_text="19.10.26 - 24.10.26", selected_store_cookie_present=True,
        elapsed_ms=1, publication_json=b'{"config":{}}',
        prospect_pdf_url="https://example.invalid/hz43.pdf",
        prospect_pdf=output.getvalue(),
    )
    if configured_engine.dialect.name == "postgresql":
        engine = configured_engine  # Migrated, isolated PostgreSQL CI service.
    else:
        engine = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / 'registry.db'}")
        PdfAcquisition.__table__.create(engine)
        SourceSnapshot.__table__.create(engine)
    root = tmp_path / "raw"
    monkeypatch.setattr(netto, "get_settings", lambda: SimpleNamespace(raw_snapshot_dir=root))

    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return NOW.astimezone(tz)

    monkeypatch.setattr(netto, "datetime", Clock)
    ctx = SimpleNamespace(
        engine=engine, root=root, source=source, bundle=bundle,
        sha=sha256(bundle.prospect_pdf).hexdigest(),
    )
    yield ctx
    with engine.begin() as connection:
        connection.execute(sa.delete(PdfAcquisition).where(PdfAcquisition.pdf_sha256 == ctx.sha))
        connection.execute(sa.delete(SourceSnapshot).where(SourceSnapshot.source_url == source.url))
    if engine is not configured_engine:
        engine.dispose()


def write(ctx, *, collected_at=NOW, bundle=None, guarded=True):
    return netto._write_bundle(
        bundle or ctx.bundle, source=ctx.source, collected_at=collected_at,
        pdf_registry_engine=ctx.engine if guarded else None,
    )


def seed(ctx, acquired_at):
    with Session(ctx.engine) as db:
        register_pdf_acquisition(
            db, pdf_sha256=ctx.sha, evidence_ref="verified-prior-acquisition",
            acquired_at=acquired_at, recorded_at=NOW,
        )
        db.commit()


def retention(ctx):
    with Session(ctx.engine) as db:
        return pdf_retention(db, ctx.sha, as_of=NOW)


def test_registers_before_first_file_and_keeps_manifest_bytes(context, monkeypatch):
    ctx = context
    original_open = Path.open

    def observed_open(path, *args, **kwargs):
        if args and args[0] == "xb":
            # A separate connection already sees the committed observation.
            assert retention(ctx).state == "within_retention"
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", observed_open)
    path, digest = write(ctx)
    original = path.read_bytes()
    manifest = json.loads(original)
    assert sha256(original).hexdigest() == digest
    assert manifest["schema_version"] == 3
    assert Path(manifest["prospect_pdf_path"]).read_bytes() == ctx.bundle.prospect_pdf
    assert Path(manifest["store_path"]).read_bytes() == ctx.bundle.store_html
    assert write(ctx, guarded=False) == (path, digest)
    assert path.read_bytes() == original
    assert retention(ctx).first_acquired_at == NOW


def test_replay_and_renamed_download_keep_earliest_deadline(context):
    ctx = context
    first = NOW - timedelta(days=10)
    first_path, digest = write(ctx, collected_at=first)
    assert write(ctx, collected_at=first) == (first_path, digest)
    write(ctx, bundle=replace(ctx.bundle, prospect_slug="another-name"))
    result = retention(ctx)
    assert result.first_acquired_at == first
    assert result.expires_at == first + timedelta(days=30)
    with Session(ctx.engine) as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(PdfAcquisition).where(
            PdfAcquisition.pdf_sha256 == ctx.sha)) == 2


@pytest.mark.parametrize("age,allowed", [
    (timedelta(days=29), True),
    (timedelta(days=30, microseconds=-1), True),
    (timedelta(days=30), False),
    (timedelta(days=31), False),
])
def test_existing_sha_deadline_uses_wall_clock_not_new_collection_date(context, age, allowed):
    seed(context, NOW - age)
    if allowed:
        write(context)
        assert list(context.root.rglob("*.pdf"))
    else:
        with pytest.raises(ValueError, match="raw_expired"):
            write(context)
        assert not context.root.exists()
        assert retention(context).state == "raw_expired"


def test_unknown_age_blocks_new_download_without_writing_files(context):
    seed(context, None)
    with pytest.raises(ValueError, match="acquisition_unknown"):
        write(context)
    assert not context.root.exists()
    assert retention(context).state == "acquisition_unknown"


@pytest.mark.parametrize("symlink", [False, True])
def test_existing_unregistered_copy_is_not_assigned_today(context, symlink):
    ctx = context
    root = ctx.root / "netto"
    root.mkdir(parents=True)
    pdf = root / f"5659-hz43-{ctx.sha}.pdf"
    if symlink:
        pdf.symlink_to(root / "missing")
    else:
        pdf.write_bytes(ctx.bundle.prospect_pdf)
    with pytest.raises(ValueError, match="acquisition_unknown"):
        write(ctx)
    assert list(root.iterdir()) == [pdf]
    assert retention(ctx).state == "unregistered"


def test_failed_file_write_preserves_acquisition_across_retry(context, monkeypatch):
    ctx = context
    original_open = Path.open

    def fail_pdf(path, *args, **kwargs):
        if path.suffix == ".pdf" and args and args[0] == "xb":
            raise OSError("injected disk failure")
        return original_open(path, *args, **kwargs)

    monkeypatch.setattr(Path, "open", fail_pdf)
    first = NOW - timedelta(days=5)
    with pytest.raises(OSError, match="injected"):
        write(ctx, collected_at=first)
    assert retention(ctx).first_acquired_at == first
    assert not list(ctx.root.rglob("*.pdf"))
    monkeypatch.setattr(Path, "open", original_open)
    write(ctx)
    assert retention(ctx).first_acquired_at == first


@pytest.mark.parametrize("invalid_date", [
    NOW.replace(tzinfo=None), NOW + timedelta(seconds=1),
])
def test_invalid_acquisition_time_never_writes_files(context, invalid_date):
    with pytest.raises(ValueError):
        write(context, collected_at=invalid_date)
    assert not context.root.exists()
    assert retention(context).state == "unregistered"


def test_registry_commit_failure_never_writes_files(context, monkeypatch):
    def fail_commit(self):
        raise RuntimeError("injected registry commit failure")

    monkeypatch.setattr(Session, "commit", fail_commit)
    with pytest.raises(RuntimeError, match="registry commit"):
        write(context)
    assert not context.root.exists()
    assert retention(context).state == "unregistered"


def test_missing_registry_schema_never_falls_back_to_legacy_write(context, tmp_path):
    missing = sa.create_engine(f"sqlite+pysqlite:///{tmp_path / 'unmigrated.db'}")
    try:
        with pytest.raises(sa.exc.OperationalError):
            netto._write_bundle(
                context.bundle, source=context.source, collected_at=NOW,
                pdf_registry_engine=missing,
            )
        assert not context.root.exists()
    finally:
        missing.dispose()


def test_legacy_mode_does_not_read_registry(context, monkeypatch):
    def unexpected_query(*args, **kwargs):
        raise AssertionError("legacy capture must not need registry schema")

    monkeypatch.setattr(netto, "pdf_retention", unexpected_query)
    path, _ = write(context, guarded=False)
    assert path.exists()
    assert retention(context).state == "unregistered"


@pytest.mark.parametrize("expired", [False, True])
def test_collector_passes_registry_and_records_success_or_denial(context, monkeypatch, expired):
    ctx = context
    if expired:
        seed(ctx, NOW - timedelta(days=30))
    monkeypatch.setattr(netto, "fetch_netto_store_prospect", lambda source: ctx.bundle)
    with Session(ctx.engine) as db:
        snapshot = netto.collect_netto_store_prospect(
            db, ctx.source, pdf_registry_engine=ctx.engine,
        )
        assert snapshot.success is not expired
        if expired:
            assert "raw_expired" in snapshot.error
            assert snapshot.snapshot_path is None
            assert not ctx.root.exists()
        else:
            assert Path(snapshot.snapshot_path).exists()
            assert retention(ctx).state == "within_retention"
