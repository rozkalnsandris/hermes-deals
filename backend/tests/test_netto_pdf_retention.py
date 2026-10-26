"""Netto admission uses real PDF bytes, files and isolated database transactions."""
from dataclasses import replace
from datetime import date, datetime, timedelta, timezone
from hashlib import sha256
from decimal import Decimal
from io import BytesIO
import json
from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

from pypdf import PdfWriter
from pypdf.generic import DecodedStreamObject, DictionaryObject, NameObject
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app import netto_store_prospect as netto
from app.models import OfferCandidateRecord, PdfAcquisition, SourceSnapshot
from app.pdf_retention import PdfRetentionDenied, pdf_retention, register_pdf_acquisition
from app.parsers.netto import NettoParserContext
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
    page = writer.add_blank_page(width=300, height=100)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({
            NameObject("/F1"): DictionaryObject({
                NameObject("/Type"): NameObject("/Font"),
                NameObject("/Subtype"): NameObject("/Type1"),
                NameObject("/BaseFont"): NameObject("/Helvetica"),
            }),
        }),
    })
    stream = DecodedStreamObject()
    stream.set_data(b"BT /F1 12 Tf 10 50 Td (19.10.26 - 24.10.26) Tj ET")
    page[NameObject("/Contents")] = writer._add_object(stream)
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
        OfferCandidateRecord.__table__.create(engine)
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
        snapshot_ids = sa.select(SourceSnapshot.id).where(SourceSnapshot.source_url == source.url)
        connection.execute(sa.delete(OfferCandidateRecord).where(
            OfferCandidateRecord.snapshot_id.in_(snapshot_ids)))
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


@pytest.fixture
def reader(context):
    ctx = context
    bundle = replace(
        ctx.bundle,
        store_html=(Path(__file__).parent / "fixtures/netto_offers.html").read_bytes(),
        prospect_html=b'<meta name="description" content="19.10.26 - 24.10.26">',
    )
    path, _ = write(ctx, bundle=bundle, guarded=False)
    manifest = json.loads(path.read_bytes())
    return SimpleNamespace(
        ctx=ctx, path=path, manifest=manifest,
        parser_context=NettoParserContext(
            uuid4(), ctx.source.url, NOW - timedelta(days=40), "5659", ctx.source.store_name,
        ),
    )


def replay_reader(reader, *, guarded=True):
    return netto.parse_netto_store_prospect_snapshot(
        reader.path, reader.parser_context,
        pdf_registry_engine=reader.ctx.engine if guarded else None,
    )


@pytest.mark.parametrize("strategy,validity", [
    (netto.MANIFEST_STRATEGY_V3, "prospect_html_meta"),
    (netto.MANIFEST_STRATEGY_V3, "prospect_pdf_text"),
    (netto.MANIFEST_STRATEGY_V2, "prospect_pdf_text"),
])
def test_reader_valid_content_is_read_once_and_keeps_offer_provenance(reader, monkeypatch, strategy, validity):
    reader.manifest.update(strategy=strategy, validity_source_type=validity)
    reader.path.write_text(json.dumps(reader.manifest))
    seed(reader.ctx, NOW - timedelta(days=29))
    pdf = Path(reader.manifest["prospect_pdf_path"])
    original = Path.read_bytes
    reads = []

    def observe(path):
        if path == pdf:
            reads.append(path)
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", observe)
    offers = replay_reader(reader)
    assert len(reads) == 1
    assert len(offers) == 5
    assert all(offer.snapshot_id == reader.parser_context.snapshot_id for offer in offers)
    assert all(offer.collected_at == reader.parser_context.collected_at for offer in offers)
    assert all(offer.valid_from == date(2026, 10, 19) and
               offer.valid_until == date(2026, 10, 24) for offer in offers)
    assert all(offer.raw_payload["campaign_validity_source_type"] == validity for offer in offers)
    assert offers == replay_reader(reader, guarded=False)


@pytest.mark.parametrize("state,age", [
    ("unregistered", "unregistered"),
    ("acquisition_unknown", None),
    ("raw_expired", timedelta(days=30)),
    ("raw_expired", timedelta(days=31)),
    ("not_yet_acquired", timedelta(days=-1)),
])
@pytest.mark.parametrize("missing", [False, True])
def test_reader_denial_precedes_pdf_access_and_does_not_change_evidence(reader, monkeypatch, state, age, missing):
    ctx = reader.ctx
    if age != "unregistered":
        acquired = None if age is None else NOW - age
        with Session(ctx.engine) as db:
            register_pdf_acquisition(
                db, pdf_sha256=ctx.sha, evidence_ref="reader-prior-evidence",
                acquired_at=acquired, recorded_at=NOW + timedelta(days=1),
            )
            db.commit()
    pdf = Path(reader.manifest["prospect_pdf_path"])
    if missing:
        pdf.unlink()  # Synthetic test fixture only.
    original = Path.read_bytes
    before = {p: original(p) for p in ctx.root.rglob("*") if p.is_file()}

    def forbid_pdf(path):
        if path == pdf:
            raise AssertionError("denied content must not be opened")
        return original(path)

    monkeypatch.setattr(Path, "read_bytes", forbid_pdf)
    with Session(ctx.engine) as db:
        count_before = db.scalar(sa.select(sa.func.count()).select_from(PdfAcquisition).where(
            PdfAcquisition.pdf_sha256 == ctx.sha))
    with pytest.raises(PdfRetentionDenied) as failure:
        replay_reader(reader)
    assert failure.value.retention.state == state
    assert failure.value.retention.pdf_sha256 == ctx.sha
    assert {p: original(p) for p in before} == before
    with Session(ctx.engine) as db:
        assert db.scalar(sa.select(sa.func.count()).select_from(PdfAcquisition).where(
            PdfAcquisition.pdf_sha256 == ctx.sha)) == count_before


def test_reader_accepts_instant_before_deadline(reader):
    seed(reader.ctx, NOW - timedelta(days=30) + timedelta(microseconds=1))
    assert replay_reader(reader)


@pytest.mark.parametrize("failure", ["missing", "corrupt"])
def test_reader_does_not_mislabel_live_missing_or_corrupt_pdf_as_expired(reader, failure):
    seed(reader.ctx, NOW)
    pdf = Path(reader.manifest["prospect_pdf_path"])
    if failure == "missing":
        pdf.unlink()
        with pytest.raises(FileNotFoundError):
            replay_reader(reader)
    else:
        pdf.write_bytes(b"corrupt")
        with pytest.raises(ValueError, match="PDF SHA mismatch") as error:
            replay_reader(reader)
        assert not isinstance(error.value, PdfRetentionDenied)


@pytest.mark.parametrize("strategy", [netto.MANIFEST_STRATEGY_V1, netto.MANIFEST_STRATEGY_V2])
def test_legacy_html_only_reader_needs_neither_pdf_nor_registry(reader, monkeypatch, strategy):
    reader.manifest["strategy"] = strategy
    Path(reader.manifest.pop("prospect_pdf_path")).unlink()
    reader.manifest.pop("prospect_pdf_sha256")
    reader.path.write_text(json.dumps(reader.manifest))

    def unexpected_query(*args, **kwargs):
        raise AssertionError("HTML-only replay must not query the PDF registry")

    monkeypatch.setattr(netto, "pdf_retention", unexpected_query)
    assert len(replay_reader(reader)) == 5


def test_reader_registry_error_never_falls_back_to_pdf(reader, monkeypatch):
    pdf = Path(reader.manifest["prospect_pdf_path"])
    original = Path.read_bytes

    def forbid_pdf(path):
        if path == pdf:
            raise AssertionError("failed registry must not fall back to PDF")
        return original(path)

    def registry_error(*args, **kwargs):
        raise RuntimeError("registry unavailable")

    monkeypatch.setattr(Path, "read_bytes", forbid_pdf)
    monkeypatch.setattr(netto, "pdf_retention", registry_error)
    with pytest.raises(RuntimeError, match="registry unavailable"):
        replay_reader(reader)


def test_reader_without_registry_argument_keeps_legacy_behavior(reader, monkeypatch):
    def unexpected_query(*args, **kwargs):
        raise AssertionError("legacy replay must not query the registry")

    monkeypatch.setattr(netto, "pdf_retention", unexpected_query)
    assert len(replay_reader(reader, guarded=False)) == 5


@pytest.mark.parametrize("failure", ["store", "pdf_sha", "validity"])
def test_guarded_reader_preserves_identity_and_validity_checks(reader, failure):
    seed(reader.ctx, NOW)
    if failure == "store":
        reader.manifest["store_external_id"] = "other"
        message = "store mismatch"
    elif failure == "pdf_sha":
        reader.manifest["prospect_pdf_sha256"] = "invalid"
        message = "SHA256"
    else:
        reader.manifest["valid_until"] = "2026-10-31"
        message = "validity no longer matches"
    reader.path.write_text(json.dumps(reader.manifest))
    with pytest.raises(ValueError, match=message):
        replay_reader(reader)


def test_expired_missing_pdf_keeps_persisted_price_and_source_provenance(reader):
    ctx = reader.ctx
    offer = replay_reader(reader, guarded=False)[0]
    manifest_sha = sha256(reader.path.read_bytes()).hexdigest()
    with Session(ctx.engine) as db:
        db.add(SourceSnapshot(
            id=offer.snapshot_id, source_chain="netto", source_url=ctx.source.url,
            collected_at=offer.collected_at, sha256=manifest_sha,
            snapshot_path=str(reader.path), success=True,
            strategy_hint=netto.MANIFEST_STRATEGY_V3,
        ))
        db.flush()
        row = OfferCandidateRecord(
            source_chain="netto", source_offer_id=offer.source_offer_id,
            product_name_raw=offer.product_name_raw, price_eur=offer.price_eur,
            source_url=str(offer.source_url), snapshot_id=offer.snapshot_id,
            collected_at=offer.collected_at, parser_version=offer.parser_version,
            raw_payload=offer.raw_payload,
        )
        db.add(row)
        db.commit()
        row_id = row.id
    seed(ctx, NOW - timedelta(days=30))
    Path(reader.manifest["prospect_pdf_path"]).unlink()
    with pytest.raises(PdfRetentionDenied) as error:
        replay_reader(reader)
    assert error.value.retention.state == "raw_expired"
    with Session(ctx.engine) as db:
        row = db.get(OfferCandidateRecord, row_id)
        assert row.price_eur == offer.price_eur == Decimal("2.79")
        assert row.raw_payload == offer.raw_payload
        assert row.snapshot_id == offer.snapshot_id
        snapshot = db.get(SourceSnapshot, offer.snapshot_id)
        assert snapshot.success and snapshot.sha256 == manifest_sha
        assert snapshot.snapshot_path == str(reader.path)
    assert reader.path.exists()
