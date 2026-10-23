"""B15M2 V08: source-bound isolated PostgreSQL shadow; LIVE execution only."""
from __future__ import annotations

import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import tempfile
import time

REPO = Path("/home/andris/hermes-deals")
OUTPUT_ROOT = Path("/home/andris/hermes-deals-runner-evidence")
DB = "b15m2_v08_shadow"
MIGRATOR = "b15m2_v08_migrator"
APP = "b15m2_v08_app"
READER = "b15m2_v08_reader"
TABLES = (
    "source_snapshots", "offer_candidates", "offer_normalizations",
    "canonical_products", "product_match_candidates", "offer_product_links",
    "offer_review_items", "offer_review_revisions", "offer_pricing_normalizations",
    "comparison_families", "comparison_family_members", "household_states",
)
SOURCE_FILES = (
    "tools/run-hermes-deals-b15m2-least-privilege-shadow-migration-api-regression-v08.sh",
    "tools/b15m2_v08_shadow.py",
    "tools/b15m2-v08-ci.Dockerfile",
    "backend/alembic/versions/0008_household_state.py",
)
ORIGINS = (
    "https://github.com/rozkalnsandris/hermes-deals",
    "https://github.com/rozkalnsandris/hermes-deals.git",
    "git@github.com:rozkalnsandris/hermes-deals.git",
)


def fail(message: str) -> None:
    raise RuntimeError("B15M2_V08_FAIL: " + message)


def run(*args: str, cwd: Path | None = None) -> str:
    result = subprocess.run(
        args, cwd=str(cwd) if cwd else None, capture_output=True, text=True,
        check=False, env={**os.environ, "GIT_OPTIONAL_LOCKS": "0"},
    )
    if result.returncode != 0:
        # Do not publish stderr/stdout: tools may include credentials.
        fail("command failed: " + Path(args[0]).name + " rc=" + str(result.returncode))
    return result.stdout.strip()


def git(*args: str) -> str:
    return run("git", "-C", str(REPO), *args)


def docker(*args: str) -> str:
    return run("docker", *args)


def query(pg: str, role: str, db: str, statement: str) -> str:
    return docker(
        "exec", pg, "psql", "-v", "ON_ERROR_STOP=1",
        "-A", "-t", "-U", role, "-d", db, "-c", statement,
    )


def preflight() -> tuple[str, Path, str, str]:
    if os.getuid() == 0 or os.environ.get("USER") != "andris":
        fail("non-root andris identity required")
    if os.environ.get("HERMES_AUDIT_TRIGGER") != "github-actions":
        fail("registered GitHub Actions dispatcher required")
    if os.environ.get("HERMES_AUDIT_EXPECTED_BRANCH") != "main":
        fail("registered main required")
    sha = os.environ.get("HERMES_AUDIT_EXPECTED_HEAD", "")
    if not re.fullmatch("[0-9a-f]{40}", sha):
        fail("exact registered SHA is missing")
    raw_out = os.environ.get("HERMES_AUDIT_EXPORT_DIR", "")
    out = Path(raw_out)
    if (not raw_out.startswith(str(OUTPUT_ROOT) + "/hermes-deals-audit-")
            or not out.is_dir() or out.is_symlink() or out.owner() != "andris"):
        fail("unsafe evidence directory")
    if not (REPO / ".git").is_dir() or (REPO / ".git").is_symlink():
        fail("unsafe primary checkout")
    if git("branch", "--show-current") != "main":
        fail("primary branch mismatch")
    if git("rev-parse", "HEAD") != sha or git("status", "--porcelain"):
        fail("primary head mismatch or dirty source")
    if git("remote", "get-url", "origin") not in ORIGINS:
        fail("untrusted origin")
    for path in SOURCE_FILES:
        git("ls-files", "--error-unmatch", path)
        git("cat-file", "-e", sha + ":" + path)
    migration = (REPO / SOURCE_FILES[-1]).read_text(encoding="utf-8")
    if 'revision = "0008_household_state"' not in migration:
        fail("migration head mismatch")
    known = {
        "0001_phase1_foundation.py", "0002_offer_persistence_hardening.py",
        "0003_product_identity.py", "0004_offer_app_validity.py",
        "0005_offer_review_queue.py", "0006_unit_basis_pricing.py",
        "0007_comparison_family_pricing.py", "0008_household_state.py",
    }
    actual = {p.name for p in (REPO / "backend/alembic/versions").glob("*.py")}
    if actual != known:
        fail("unknown migration source; review required")
    return sha, out, git("rev-parse", sha + ":" + SOURCE_FILES[0]), git(
        "rev-parse", sha + ":" + SOURCE_FILES[-1])


def setup_roles(pg: str) -> None:
    for sql in (
        "CREATE ROLE b15m2_v08_migrator LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS",
        "CREATE ROLE b15m2_v08_app LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS",
        "CREATE ROLE b15m2_v08_reader LOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOREPLICATION NOBYPASSRLS",
        "CREATE DATABASE b15m2_v08_shadow OWNER b15m2_v08_migrator",
    ):
        query(pg, "postgres", "postgres", sql)
    for sql in (
        "REVOKE CONNECT,TEMPORARY ON DATABASE b15m2_v08_shadow FROM PUBLIC",
        "REVOKE CREATE ON SCHEMA public FROM PUBLIC",
        "GRANT CONNECT ON DATABASE b15m2_v08_shadow TO b15m2_v08_app,b15m2_v08_reader",
    ):
        query(pg, "postgres", DB, sql)


def prove_roles(pg: str) -> None:
    actual = query(pg, "postgres", DB, (
        "SELECT tablename FROM pg_tables WHERE schemaname='public' "
        "AND tablename <> 'alembic_version' ORDER BY tablename")).splitlines()
    if actual != sorted(TABLES):
        fail("12-table schema mismatch")
    owner_ok = query(pg, "postgres", DB, (
        "SELECT COALESCE(bool_and(pg_get_userbyid(c.relowner)="
        "'b15m2_v08_migrator'),false) FROM pg_class c "
        "JOIN pg_namespace n ON n.oid=c.relnamespace "
        "WHERE n.nspname='public' AND c.relkind='r'"))
    if owner_ok != "t":
        fail("table ownership failed")
    qualified = ",".join("public." + t for t in TABLES)
    query(pg, "postgres", DB, "GRANT USAGE ON SCHEMA public TO " + APP + "," + READER)
    query(pg, "postgres", DB, "GRANT SELECT,INSERT,UPDATE,DELETE ON " + qualified + " TO " + APP)
    query(pg, "postgres", DB, "GRANT SELECT ON " + qualified + " TO " + READER)
    for table in TABLES:
        for privilege in ("SELECT", "INSERT", "UPDATE", "DELETE"):
            result = query(pg, "postgres", DB, "SELECT has_table_privilege('" +
                           APP + "','public." + table + "','" + privilege + "')")
            if result != "t":
                fail("application privilege missing: " + table + " " + privilege)
        reader_sql = (
            "SELECT has_table_privilege('" + READER + "','public." + table +
            "','SELECT') AND NOT has_table_privilege('" + READER + "','public." +
            table + "','INSERT') AND NOT has_table_privilege('" + READER +
            "','public." + table + "','UPDATE') AND NOT has_table_privilege('" +
            READER + "','public." + table + "','DELETE')")
        if query(pg, "postgres", DB, reader_sql) != "t":
            fail("reader privilege mismatch: " + table)
        # Zero-row SQL validates each CRUD privilege without fabricating offers.
        query(pg, APP, DB, "BEGIN; SELECT id FROM public." + table +
              " WHERE false; INSERT INTO public." + table +
              " (id) SELECT id FROM public." + table +
              " WHERE false; UPDATE public." + table +
              " SET id=id WHERE false; DELETE FROM public." + table +
              " WHERE false; ROLLBACK")
    forbid = ("SELECT NOT has_table_privilege('" + APP +
              "','public.alembic_version','UPDATE') AND NOT " +
              "has_schema_privilege('" + APP + "','public','CREATE') AND NOT " +
              "has_database_privilege('" + APP + "','" + DB + "','CREATE')")
    if query(pg, "postgres", DB, forbid) != "t":
        fail("application role has migration/admin permission")
    ddl = subprocess.run(
        ("docker", "exec", pg, "psql", "-v", "ON_ERROR_STOP=1",
         "-U", APP, "-d", DB, "-c",
         "CREATE TABLE public.b15m2_v08_forbidden (id integer)"),
        capture_output=True, text=True, check=False)
    if ddl.returncode == 0:
        fail("application role unexpectedly permitted DDL")


def main() -> None:
    sha, out, script_blob, migration_blob = preflight()
    if shutil.which("docker") is None:
        fail("Docker unavailable; no production fallback")
    pg_image = docker("image", "inspect", "postgres:18.4", "--format", "{{.Id}}")
    if not re.fullmatch("sha256:[0-9a-f]{64}", pg_image):
        fail("pinned local PostgreSQL image identity missing")
    # Detached tracked archive excludes ignored files, .env and host secrets.
    temp = Path(tempfile.mkdtemp(prefix="hermes-b15m2-v08-"))
    source = temp / "source"
    source.mkdir(mode=0o700)
    run("git", "-C", str(REPO), "archive", "--format=tar",
        "--output", str(temp / "source.tar"), sha)
    run("tar", "-xf", str(temp / "source.tar"), "-C", str(source))
    if any(p.is_symlink() for p in source.rglob("*")):
        fail("source archive symlink not allowed")
    socket = temp / "socket"
    socket.mkdir(mode=0o777)
    socket.chmod(0o777)
    run_key = temp.name.replace("-", "").replace("_", "")
    pg = "hermes-" + run_key + "-pg"
    runtime = "hermes-b15m2-v08-runtime:" + sha
    ci = "hermes-b15m2-v08-ci:" + sha
    docker("build", "--pull=false", "--file", str(source / "backend/Dockerfile"),
           "--tag", runtime, str(source / "backend"))
    docker("build", "--pull=false", "--file", str(source / SOURCE_FILES[2]),
           "--build-arg", "BASE_IMAGE=" + runtime, "--tag", ci, str(source))
    runtime_id = docker("image", "inspect", runtime, "--format", "{{.Id}}")
    ci_id = docker("image", "inspect", ci, "--format", "{{.Id}}")
    mount = "type=bind,source=" + str(socket) + ",target=/var/run/postgresql"
    docker("run", "--detach", "--network", "none", "--name", pg,
           "--tmpfs", "/var/lib/postgresql:rw,nosuid,nodev",
           "--mount", mount, "--env", "POSTGRES_HOST_AUTH_METHOD=trust",
           pg_image)
    for _ in range(45):
        ready = subprocess.run(
            ("docker", "exec", pg, "pg_isready", "-U", "postgres", "-d", "postgres"),
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, check=False)
        if ready.returncode == 0:
            break
        time.sleep(1)
    else:
        fail("isolated PostgreSQL not ready")
    setup_roles(pg)
    migration_url = "postgresql+psycopg://" + MIGRATOR + "@/" + DB + "?host=/var/run/postgresql"
    docker("run", "--name", "hermes-" + run_key + "-migration",
           "--network", "none", "--mount", mount,
           "--env", "DATABASE_URL=" + migration_url,
           runtime_id, "python", "-m", "alembic", "upgrade", "head")
    if query(pg, "postgres", DB, "SELECT version_num FROM alembic_version") != "0008_household_state":
        fail("migration did not reach 0008")
    prove_roles(pg)
    docker("run", "--name", "hermes-" + run_key + "-tests",
           "--network", "none", "--read-only", "--tmpfs", "/tmp:rw",
           "--mount", "type=bind,source=" + str(source) + ",target=/src,readonly",
           "--workdir", "/src/backend", "--env", "PYTHONPATH=/src/backend",
           "--env", "DATABASE_URL=sqlite+pysqlite:///:memory:",
           ci_id, "python", "-m", "pytest", "-q", "-p", "no:cacheprovider", "tests")
    app_url = "postgresql+psycopg://" + APP + "@/" + DB + "?host=/var/run/postgresql"
    smoke = ("from fastapi.testclient import TestClient; from app.main import app; "
             "r=TestClient(app).get('/api/health'); assert r.status_code == 200")
    docker("run", "--name", "hermes-" + run_key + "-api",
           "--network", "none", "--read-only", "--tmpfs", "/tmp:rw",
           "--mount", mount, "--env", "DATABASE_URL=" + app_url,
           runtime_id, "python", "-c", smoke)
    # No raw DB data, credentials, connection URLs or host inventory in artifact.
    evidence = {
        "audit": "b15m2-v08", "result": "PASS",
        "source_sha": sha, "wrapper_blob": script_blob,
        "migration_blob": migration_blob, "alembic_head": "0008_household_state",
        "table_count": len(TABLES), "role_matrix": "12 table zero-row CRUD",
        "full_backend_suite": "PASS", "api_smoke": "PASS",
        "postgres_image_id": pg_image, "runtime_image_id": runtime_id,
        "ci_image_id": ci_id, "docker_network": "none",
        "production_database_write": False, "production_deploy": False,
        "automatic_cleanup": False,
    }
    (out / "b15m2-v08-summary.json").write_text(
        json.dumps(evidence, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print("B15M2_V08_RESULT=PASS")


if __name__ == "__main__":
    main()
