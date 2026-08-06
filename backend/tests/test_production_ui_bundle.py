from __future__ import annotations

from hashlib import sha256
from pathlib import Path
import shutil

import pytest

from app.ui_bundle import (
    PRODUCTION_META,
    SCRIPT_MARKER,
    SCRIPT_TAG,
    STYLE_LINK,
    STYLE_MARKER,
    UiBundleError,
    build_production_ui_bundle,
)


SOURCE_UI = Path(__file__).resolve().parents[1] / "app" / "ui"


def _copy_ui(tmp_path: Path, name: str = "ui") -> Path:
    target = tmp_path / name
    shutil.copytree(SOURCE_UI, target)
    return target


def test_production_bundle_is_self_contained_and_deterministic(
    tmp_path: Path,
) -> None:
    first = _copy_ui(tmp_path, "first")
    second = _copy_ui(tmp_path, "second")
    source_css = (first / "styles.css").read_bytes()
    source_js = (first / "app.js").read_bytes()

    first_index = build_production_ui_bundle(first)
    second_index = build_production_ui_bundle(second)

    first_payload = first_index.read_bytes()
    second_payload = second_index.read_bytes()
    text = first_payload.decode("utf-8")

    assert first_payload == second_payload
    assert sha256(first_payload).hexdigest() == sha256(second_payload).hexdigest()
    assert len(first_payload) > len(source_css) + len(source_js)
    assert STYLE_LINK not in text
    assert SCRIPT_TAG not in text
    assert PRODUCTION_META in text
    assert STYLE_MARKER in text
    assert SCRIPT_MARKER in text
    assert "--accent:#246b45" in text
    assert "/api/v1/deals/current" in text
    assert 'class="ui2-shell reference-app"' in text
    assert (first / "styles.css").read_bytes() == source_css
    assert (first / "app.js").read_bytes() == source_js


def test_production_bundle_fails_when_an_asset_is_missing(tmp_path: Path) -> None:
    ui_dir = _copy_ui(tmp_path)
    (ui_dir / "styles.css").unlink()

    with pytest.raises(UiBundleError, match="stylesheet is missing or unsafe"):
        build_production_ui_bundle(ui_dir)


def test_production_bundle_rejects_duplicate_asset_references(
    tmp_path: Path,
) -> None:
    ui_dir = _copy_ui(tmp_path)
    index_path = ui_dir / "index.html"
    index_path.write_text(
        index_path.read_text(encoding="utf-8").replace(
            STYLE_LINK,
            f"{STYLE_LINK}\n{STYLE_LINK}",
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(UiBundleError, match="stylesheet reference must occur exactly once"):
        build_production_ui_bundle(ui_dir)


def test_production_bundle_rejects_unsafe_inline_closing_sequence(
    tmp_path: Path,
) -> None:
    ui_dir = _copy_ui(tmp_path)
    app_path = ui_dir / "app.js"
    app_path.write_text(
        app_path.read_text(encoding="utf-8") + '\nconst unsafe = "</script>";\n',
        encoding="utf-8",
    )

    with pytest.raises(UiBundleError, match="unsafe </script sequence"):
        build_production_ui_bundle(ui_dir)


def test_production_bundle_cannot_be_applied_twice(tmp_path: Path) -> None:
    ui_dir = _copy_ui(tmp_path)
    build_production_ui_bundle(ui_dir)

    with pytest.raises(UiBundleError, match="stylesheet reference must occur exactly once"):
        build_production_ui_bundle(ui_dir)
