from __future__ import annotations

import stat
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def _normalize(app: Path, alembic: Path, alembic_ini: Path) -> None:
    subprocess.run(
        [
            "find",
            str(app),
            str(alembic),
            "-type",
            "d",
            "-exec",
            "chmod",
            "0755",
            "{}",
            "+",
        ],
        check=True,
    )
    subprocess.run(
        [
            "find",
            str(app),
            str(alembic),
            "-type",
            "f",
            "-exec",
            "chmod",
            "0644",
            "{}",
            "+",
        ],
        check=True,
    )
    subprocess.run(["chmod", "0644", str(alembic_ini)], check=True)


def _fixture(tmp_path: Path) -> tuple[Path, Path, Path, Path, Path, Path]:
    app = tmp_path / "app"
    alembic = tmp_path / "alembic"
    app.mkdir()
    alembic.mkdir()

    app_init = app / "__init__.py"
    collector = app / "collector_cli.py"
    migration = alembic / "env.py"
    alembic_ini = tmp_path / "alembic.ini"
    for path in (app_init, collector, migration, alembic_ini):
        path.write_text("# fixture\n", encoding="utf-8")
    return app, alembic, app_init, collector, migration, alembic_ini


def test_dockerfile_normalizes_runtime_permissions_after_ui_bundle() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")

    copy_app = "COPY app ./app"
    bundle = "RUN python -m app.ui_bundle --ui-dir /app/app/ui"
    normalize = (
        "RUN find /app/app /app/alembic -type d -exec chmod 0755 {} + \\\n"
        "    && find /app/app /app/alembic -type f -exec chmod 0644 {} + \\\n"
        "    && chmod 0644 /app/alembic.ini"
    )
    expose = "EXPOSE 8000"

    assert copy_app in text
    assert bundle in text
    assert normalize in text
    assert expose in text
    assert (
        text.index(copy_app)
        < text.index(bundle)
        < text.index(normalize)
        < text.index(expose)
    )


def test_runtime_permission_command_repairs_private_release_context(tmp_path: Path) -> None:
    app, alembic, app_init, collector, migration, alembic_ini = _fixture(tmp_path)
    app.chmod(0o700)
    alembic.chmod(0o700)
    for path in (app_init, collector, migration, alembic_ini):
        path.chmod(0o600)

    _normalize(app, alembic, alembic_ini)

    assert _mode(app) == 0o755
    assert _mode(alembic) == 0o755
    assert _mode(app_init) == 0o644
    assert _mode(collector) == 0o644
    assert _mode(migration) == 0o644
    assert _mode(alembic_ini) == 0o644


def test_runtime_permission_command_removes_unsafe_context_bits(tmp_path: Path) -> None:
    app, alembic, app_init, collector, migration, alembic_ini = _fixture(tmp_path)
    app.chmod(0o777)
    alembic.chmod(0o777)
    app_init.chmod(0o777)
    collector.chmod(0o666)
    migration.chmod(0o755)
    alembic_ini.chmod(0o666)

    _normalize(app, alembic, alembic_ini)

    assert _mode(app) == 0o755
    assert _mode(alembic) == 0o755
    assert _mode(app_init) == 0o644
    assert _mode(collector) == 0o644
    assert _mode(migration) == 0o644
    assert _mode(alembic_ini) == 0o644
