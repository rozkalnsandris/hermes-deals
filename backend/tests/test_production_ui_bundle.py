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
    WEEKLY_BRIDGE_TAG,
    UiBundleError,
    build_production_ui_bundle,
)


BACKEND_ROOT = Path(__file__).resolve().parents[1]
SOURCE_UI = BACKEND_ROOT / "app" / "ui"
DOCKERFILE = BACKEND_ROOT / "Dockerfile"
W3_BUNDLE_FIXTURE = """const identity = "HERMES_UI_SCRIPT_OPEN:";
const bootstrap = "w3-behavior-preserving-bootstrap-v1";
const weekly = "normalized_unique_deals_by_id_v1";
const current = "/api/v1/deals/current";
const daily = "/api/v1/deals/daily-specials";
const dailyContract = "explicit_immutable_retailer_evidence_only";
const catalog = "/api/v1/catalog";
void [identity, bootstrap, weekly, current, daily, dailyContract, catalog];
"""


def _copy_ui(tmp_path: Path, name: str = "ui", *, stage_w3: bool = True) -> Path:
    target = tmp_path / name
    shutil.copytree(SOURCE_UI, target)
    if stage_w3:
        (target / "app.js").write_text(W3_BUNDLE_FIXTURE, encoding="utf-8")
    return target


def test_release_image_runs_the_fail_closed_ui_bundler_after_w3_build() -> None:
    dockerfile = DOCKERFILE.read_text(encoding="utf-8")

    assert "AS ui-build" in dockerfile
    assert "RUN npm test" in dockerfile
    assert "npm run build:check" in dockerfile
    assert "COPY app ./app" in dockerfile
    assert "COPY --from=ui-build /ui/dist/app.js /app/app/ui/app.js" in dockerfile
    assert "RUN python -m app.ui_bundle --ui-dir /app/app/ui" in dockerfile
    assert dockerfile.index("COPY app ./app") < dockerfile.index(
        "COPY --from=ui-build /ui/dist/app.js /app/app/ui/app.js"
    )
    assert dockerfile.index(
        "COPY --from=ui-build /ui/dist/app.js /app/app/ui/app.js"
    ) < dockerfile.index("RUN python -m app.ui_bundle --ui-dir /app/app/ui")
    assert dockerfile.index(
        "RUN python -m app.ui_bundle --ui-dir /app/app/ui"
    ) < dockerfile.index("CMD [")


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
    assert WEEKLY_BRIDGE_TAG not in text
    assert SCRIPT_TAG not in text
    assert PRODUCTION_META in text
    assert STYLE_MARKER in text
    assert SCRIPT_MARKER in text
    assert "--accent:#246b45" in text
    assert "/api/v1/deals/current" in text
    assert "/api/v1/deals/daily-specials" in text
    assert "explicit_immutable_retailer_evidence_only" in text
    assert "w3-behavior-preserving-bootstrap-v1" in text
    assert "normalized_unique_deals_by_id_v1" in text
    assert 'class="ui2-shell reference-app"' in text
    assert "hermes-ui-fix" not in text
    assert (first / "styles.css").read_bytes() == source_css
    assert (first / "app.js").read_bytes() == source_js


def test_production_bundle_rejects_legacy_app_when_w3_builder_was_skipped(
    tmp_path: Path,
) -> None:
    ui_dir = _copy_ui(tmp_path, stage_w3=False)

    with pytest.raises(UiBundleError, match="w3-behavior-preserving-bootstrap-v1"):
        build_production_ui_bundle(ui_dir)


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


def test_production_bundle_rejects_historical_fix_metadata(tmp_path: Path) -> None:
    ui_dir = _copy_ui(tmp_path)
    index_path = ui_dir / "index.html"
    index_path.write_text(
        index_path.read_text(encoding="utf-8").replace(
            "</head>",
            '<meta name="hermes-ui-fix" content="should-not-return">\n</head>',
            1,
        ),
        encoding="utf-8",
    )

    with pytest.raises(UiBundleError, match="historical hermes-ui-fix metadata"):
        build_production_ui_bundle(ui_dir)


def test_production_bundle_cannot_be_applied_twice(tmp_path: Path) -> None:
    ui_dir = _copy_ui(tmp_path)
    build_production_ui_bundle(ui_dir)

    with pytest.raises(UiBundleError, match="stylesheet reference must occur exactly once"):
        build_production_ui_bundle(ui_dir)
