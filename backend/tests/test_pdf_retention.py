from datetime import datetime, timedelta, timezone
from importlib.util import module_from_spec, spec_from_file_location
import io
from pathlib import Path

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa
from sqlalchemy.orm import Session

from app.models import PdfAcquisition
from app.pdf_retention import pdf_retention, register_pdf_acquisition

SHA = "a" * 64
START = datetime(2026, 10, 1, 12, tzinfo=timezone.utc)
ROOT = Path(__file__).resolve().parents[2]


@pytest.fixture
def db():
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    PdfAcquisition.__table__.create(engine)
    with Session(engine) as session:
        yield session
    engine.dispose()


def record(db, *, sha=SHA, ref="manifest:one#pdf", acquired=START, recorded=None):
    return register_pdf_acquisition(db, pdf_sha256=sha, evidence_ref=ref,
                                    acquired_at=acquired, recorded_at=recorded or START + timedelta(days=40))


@pytest.mark.parametrize("offset,state", [
    (timedelta(days=-1), "not_yet_acquired"),
    (timedelta(0), "within_retention"),
    (timedelta(days=29), "within_retention"),
    (timedelta(days=30, microseconds=-1), "within_retention"),
    (timedelta(days=30), "raw_expired"),
    (timedelta(days=31), "raw_expired"),
])
def test_exact_elapsed_time_boundary(db, offset, state):
    record(db)
    result = pdf_retention(db, SHA, as_of=START + offset)
    assert result.state == state
    assert result.first_acquired_at == START
    assert result.expires_at == START + timedelta(days=30)


def test_redownload_and_exact_replay_do_not_extend_deadline(db):
    assert record(db)
    assert record(db, recorded=START + timedelta(days=60)) is False
    assert record(db, ref="manifest:later#pdf", acquired=START + timedelta(days=29))
    db.commit()
    assert db.scalar(sa.select(sa.func.count()).select_from(PdfAcquisition)) == 2
    result = pdf_retention(db, SHA, as_of=START + timedelta(days=30))
    assert result.state == "raw_expired"
    assert result.expires_at == START + timedelta(days=30)


def test_earlier_evidence_shortens_deadline_without_rewriting_observation(db):
    record(db, acquired=START + timedelta(days=10))
    record(db, ref="verified-earlier-manifest#pdf")
    rows = db.execute(sa.select(PdfAcquisition.evidence_ref, PdfAcquisition.acquired_at)).all()
    assert len(rows) == 2
    assert {row[1] for row in rows} == {START.replace(tzinfo=None), (START + timedelta(days=10)).replace(tzinfo=None)}
    assert pdf_retention(db, SHA, as_of=START + timedelta(days=30)).state == "raw_expired"


@pytest.mark.parametrize("original,replacement", [
    (START, START + timedelta(days=1)), (None, START), (START, None),
])
def test_conflicting_reference_is_not_rewritten(db, original, replacement):
    record(db, acquired=original)
    with pytest.raises(ValueError, match="conflicts"):
        record(db, acquired=replacement)
    assert db.scalar(sa.select(sa.func.count()).select_from(PdfAcquisition)) == 1
    actual = db.scalar(sa.select(PdfAcquisition.acquired_at))
    assert actual == (original.replace(tzinfo=None) if original else None)


def test_unknown_legacy_age_cannot_be_reset_by_new_download(db):
    assert pdf_retention(db, SHA, as_of=START).state == "unregistered"
    record(db, acquired=None)
    unknown = pdf_retention(db, SHA, as_of=START)
    assert unknown.state == "acquisition_unknown"
    assert unknown.first_acquired_at is None and unknown.expires_at is None
    record(db, ref="new-download#pdf", acquired=START)
    blocked = pdf_retention(db, SHA, as_of=START + timedelta(days=1))
    assert blocked.state == "acquisition_unknown"
    assert blocked.first_acquired_at is None
    # Even the known upper bound has now expired; unknown age cannot undo that.
    assert pdf_retention(db, SHA, as_of=START + timedelta(days=30)).state == "raw_expired"


def test_different_content_has_separate_deadline(db):
    record(db)
    record(db, sha="b" * 64, acquired=START + timedelta(days=20))
    assert pdf_retention(db, SHA, as_of=START + timedelta(days=30)).state == "raw_expired"
    assert pdf_retention(db, "b" * 64, as_of=START + timedelta(days=30)).state == "within_retention"


def test_timezone_conversion_and_dst_use_720_hours(db):
    from zoneinfo import ZoneInfo
    start = datetime(2026, 10, 1, 12, tzinfo=ZoneInfo("Europe/Berlin"))
    record(db, acquired=start)
    # DST ends in October; 30 elapsed days end at 11:00 Berlin time.
    end = datetime(2026, 10, 31, 11, tzinfo=ZoneInfo("Europe/Berlin"))
    assert pdf_retention(db, SHA, as_of=end).state == "raw_expired"
    assert pdf_retention(db, SHA, as_of=end - timedelta(microseconds=1)).state == "within_retention"
    assert record(db, acquired=start.astimezone(timezone.utc)) is False


@pytest.mark.parametrize("overrides", [
    {"sha": "Z" * 64}, {"sha": "a" * 63}, {"ref": " "}, {"ref": " ref"}, {"ref": "x" * 256},
    {"acquired": START.replace(tzinfo=None)}, {"recorded": START.replace(tzinfo=None)},
    {"acquired": START + timedelta(days=41)},
])
def test_invalid_observation_never_inserts(db, overrides):
    with pytest.raises(ValueError):
        record(db, **overrides)
    assert db.scalar(sa.select(sa.func.count()).select_from(PdfAcquisition)) == 0


def test_naive_evaluation_is_rejected(db):
    with pytest.raises(ValueError, match="timezone"):
        pdf_retention(db, SHA, as_of=START.replace(tzinfo=None))


def test_caller_owns_transaction(db):
    record(db)
    db.rollback()
    assert pdf_retention(db, SHA, as_of=START).state == "unregistered"


def revision():
    spec = spec_from_file_location("pdf_revision", ROOT / "backend/alembic/versions/0009_pdf_acquisitions.py")
    module = module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_adds_empty_registry_without_touching_retained_data():
    migration = revision()
    assert migration.down_revision == "0008_household_state"
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as conn:
        conn.exec_driver_sql("CREATE TABLE retained_price (id INTEGER PRIMARY KEY, price NUMERIC)")
        conn.exec_driver_sql("INSERT INTO retained_price VALUES (1, 2.99)")
        with Operations.context(MigrationContext.configure(conn)):
            migration.upgrade()
        assert set(sa.inspect(conn).get_table_names()) == {"retained_price", "pdf_acquisitions"}
        assert conn.exec_driver_sql("SELECT * FROM retained_price").all() == [(1, 2.99)]
        assert conn.exec_driver_sql("SELECT count(*) FROM pdf_acquisitions").scalar_one() == 0
        assert {col["name"] for col in sa.inspect(conn).get_columns("pdf_acquisitions")} == {
            col.name for col in PdfAcquisition.__table__.columns}
    engine.dispose()


def test_postgresql_migration_only_creates_registry():
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        revision().upgrade()
    sql = output.getvalue().upper()
    assert sql.count("CREATE TABLE") == 1
    assert "TIMESTAMP WITH TIME ZONE" in sql
    assert not any(verb in sql for verb in ("ALTER ", "INSERT ", "UPDATE ", "DELETE "))


@pytest.mark.parametrize("same_reference", [False, True])
def test_postgresql_concurrent_registration_preserves_earliest_evidence(same_reference):
    from concurrent.futures import ThreadPoolExecutor
    from threading import Barrier
    from uuid import uuid4
    from app.db import engine

    if engine.dialect.name != "postgresql":
        pytest.skip("requires the PostgreSQL 18 CI service")
    sha = uuid4().hex * 2
    barrier = Barrier(2)

    def worker(number):
        with Session(engine) as session:
            barrier.wait(timeout=10)
            inserted = record(session, sha=sha, ref="same" if same_reference else f"source-{number}",
                              acquired=START if same_reference else START + timedelta(days=number))
            session.commit()
            return inserted

    try:
        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(pool.map(worker, [0, 1]))
        with Session(engine) as session:
            result = pdf_retention(session, sha, as_of=START + timedelta(days=30))
            assert result.state == "raw_expired"
            assert result.first_acquired_at == START
            assert result.expires_at == START + timedelta(days=30)
            count = session.scalar(sa.select(sa.func.count()).select_from(PdfAcquisition).where(PdfAcquisition.pdf_sha256 == sha))
            assert count == (1 if same_reference else 2)
        assert sorted(results) == ([False, True] if same_reference else [True, True])
    finally:
        # Only the synthetic rows created by this test in the isolated CI DB.
        with engine.begin() as connection:
            connection.execute(sa.delete(PdfAcquisition).where(PdfAcquisition.pdf_sha256 == sha))
