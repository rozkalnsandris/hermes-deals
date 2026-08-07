from __future__ import annotations

import stat
import subprocess
from pathlib import Path


REPO_ROOT = Path(__file__).resolve().parents[2]
DOCKERFILE = REPO_ROOT / "backend" / "Dockerfile"


def _mode(path: Path) -> int:
    return stat.S_IMODE(path.stat().st_mode)


def test_dockerfile_normalizes_runtime_permissions_after_ui_bundle() -> None:
    text = DOCKERFILE.read_text(encoding="utf-8")

    copy_app = "COPY app ./app"
    bundle = "RUN python -m app.ui_bundle --ui-dir /app/app/ui"
    normalize = (
        "RUN chmod -R a+rX /app/app /app/alembic \\\n"
        "    && chmod a+r /app/alembic.ini"
    )

    assert copy_app in text
    assert bundle in text
    assert normalize in text
    assert text.index(copy_app) < text.index(bundle) < text.index(normalize)


def test_runtime_permission_command_repairs_private_release_context(tmp_path: Path) -> None:
    app = tmp_path / "app"
    alembic = tmp_path / "alembic"
    app.mkdir(mode=0o700)
    alembic.mkdir(mode=0o700)

    app_init = app / "__init__.py"
    collector = app / "collector_cli.py"
    migration = alembic / "env.py"
    alembic_ini = tmp_path / "alembic.ini"

    for path in (app_init, collector, migration, alembic_ini):
        path.write_text("# fixture\n", encoding="utf-8")
        path.chmod(0o600)

    subprocess.run(
        ["chmod", "-R", "a+rX", str(app), str(alembic)],
        check=True,
    )
    subprocess.run(["chmod", "a+r", str(alembic_ini)], check=True)

    assert _mode(app) == 0o755
    assert _mode(alembic) == 0o755
    assert _mode(app_init) == 0o644
    assert _mode(collector) == 0o644
    assert _mode(migration) == 0o644
    assert _mode(alembic_ini) == 0o644
    assert _mode(app_init) & 0o111 == 0
    assert _mode(collector) & 0o111 == 0
