"""Source preparation only: no daemon, production DB or protected env reads."""
import importlib.util
import io
import json
import os
from pathlib import Path
import shutil
import subprocess

from alembic.migration import MigrationContext
from alembic.operations import Operations
import pytest
import sqlalchemy as sa

ROOT = Path(__file__).resolve().parents[2]


def household_revision():
    path = ROOT / "backend/alembic/versions/0008_household_state.py"
    spec = importlib.util.spec_from_file_location("household_revision", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.parametrize("settings,expected", [
    ({}, {"HERMES_HOUSEHOLD_ID": "home", "HERMES_PUBLIC_ORIGIN": ""}),
    ({"HERMES_HOUSEHOLD_ID": "test-family", "HERMES_PUBLIC_ORIGIN": "https://household.example.invalid"},
     {"HERMES_HOUSEHOLD_ID": "test-family", "HERMES_PUBLIC_ORIGIN": "https://household.example.invalid"}),
])
def test_compose_passes_household_settings_without_reading_local_env(tmp_path, settings, expected):
    docker = shutil.which("docker")
    if not docker:
        pytest.skip("Docker Compose CLI is unavailable; no daemon is required")
    env_file = tmp_path / "synthetic.env"
    env_file.write_text("POSTGRES_DB=test\nPOSTGRES_USER=test\nPOSTGRES_PASSWORD=ci-placeholder-not-a-secret\nHTTP_USER_AGENT=rollout-test\n")
    result = subprocess.run(
        [docker, "compose", "--profile", "tools", "--env-file", str(env_file), "-f", str(ROOT / "docker-compose.yml"), "config", "--format", "json"],
        env={"PATH": os.environ["PATH"], "HOME": str(tmp_path), **settings},
        check=True, capture_output=True, text=True,
    )
    config = json.loads(result.stdout)
    actual = config["services"]["api"]["environment"]
    assert {key: actual[key] for key in expected} == expected
    assert "HERMES_HOUSEHOLD_ID" not in config["services"]["worker"]["environment"]
    assert "HERMES_PUBLIC_ORIGIN" not in config["services"]["db"]["environment"]
    assert config["volumes"]["hermes_deals_pgdata"]["name"] == "hermes-deals_hermes_deals_pgdata"


def test_household_revision_is_additive_on_isolated_database():
    revision = household_revision()
    assert revision.down_revision == "0007_comparison_family_pricing"
    assert revision.revision == "0008_household_state"
    engine = sa.create_engine("sqlite+pysqlite:///:memory:")
    with engine.begin() as connection:
        connection.exec_driver_sql("CREATE TABLE retained_observation (id INTEGER PRIMARY KEY, payload TEXT NOT NULL)")
        connection.exec_driver_sql("INSERT INTO retained_observation VALUES (1, 'unchanged source evidence')")
        with Operations.context(MigrationContext.configure(connection)):
            revision.upgrade()
        inspector = sa.inspect(connection)
        assert set(inspector.get_table_names()) == {"retained_observation", "household_states"}
        assert connection.exec_driver_sql("SELECT * FROM retained_observation").all() == [(1, "unchanged source evidence")]
        assert connection.exec_driver_sql("SELECT count(*) FROM household_states").scalar_one() == 0
        assert {column["name"] for column in inspector.get_columns("household_states")} == {"id", "version", "state", "updated_at"}
        connection.exec_driver_sql("INSERT INTO household_states VALUES ('test-family', 1, '{}', CURRENT_TIMESTAMP)")
        with pytest.raises(sa.exc.IntegrityError):
            connection.exec_driver_sql("INSERT INTO household_states VALUES ('invalid', 0, '{}', CURRENT_TIMESTAMP)")
    engine.dispose()


def test_household_revision_postgresql_sql_creates_only_household_table():
    output = io.StringIO()
    context = MigrationContext.configure(dialect_name="postgresql", opts={"as_sql": True, "output_buffer": output})
    with Operations.context(context):
        household_revision().upgrade()
    sql = output.getvalue()
    assert sql.count("CREATE TABLE") == 1
    assert "CREATE TABLE household_states" in sql
    assert "ck_household_state_version CHECK (version > 0)" in sql
    assert not any(verb in sql.upper() for verb in ("DROP ", "ALTER ", "INSERT ", "UPDATE ", "DELETE "))
