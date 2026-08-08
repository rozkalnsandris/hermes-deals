from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
OPERATOR = ROOT / "tools" / "runner" / "w4b" / "hermes-deals-w4b-operator"
RENDERER = ROOT / "tools" / "runner" / "w4b" / "render-hermes-deals-w4b-operator.py"
BASE_COMPOSE = ROOT / "docker-compose.yml"
PRODUCTION_COMPOSE = ROOT / "docker-compose.production.yml"
NGINX = ROOT / "infra" / "nginx.conf"
MODE_LINE = "      HERMES_UI_ASSET_MODE: ${HERMES_UI_ASSET_MODE:-inline-w3}"


def render_operator(tmp_path: Path, template: Path = OPERATOR) -> str:
    output = tmp_path / "rendered-operator"
    subprocess.run(
        ["python3", str(RENDERER), str(template), str(output)],
        check=True,
        text=True,
        capture_output=True,
    )
    subprocess.run(["bash", "-n", str(output)], check=True)
    return output.read_text(encoding="utf-8")


def source_contract_program(tmp_path: Path) -> str:
    source = render_operator(tmp_path)
    section = source.split("assert_target_source_contract() {\n", 1)[1].split(
        "\nPY\n}\n\nvalidate_compose_model()", 1
    )[0]
    return section.split("\n", 1)[1]


def run_source_contract(tmp_path: Path, primary_text: str) -> subprocess.CompletedProcess[str]:
    program = source_contract_program(tmp_path)
    primary_base = tmp_path / "primary-compose.yml"
    target_base = tmp_path / "target-compose.yml"
    target_prod = tmp_path / "target-production.yml"
    primary_prod = tmp_path / "primary-production.yml"
    nginx = tmp_path / "nginx.conf"

    primary_base.write_text(primary_text, encoding="utf-8")
    target_base.write_text(BASE_COMPOSE.read_text(encoding="utf-8"), encoding="utf-8")
    prod_bytes = PRODUCTION_COMPOSE.read_bytes()
    target_prod.write_bytes(prod_bytes)
    primary_prod.write_bytes(prod_bytes)
    nginx.write_bytes(NGINX.read_bytes())

    return subprocess.run(
        [
            "python3",
            "-c",
            program,
            str(primary_base),
            str(target_base),
            str(target_prod),
            str(primary_prod),
            str(nginx),
        ],
        text=True,
        capture_output=True,
        check=False,
    )


def current_compose() -> str:
    text = BASE_COMPOSE.read_text(encoding="utf-8")
    assert text.splitlines().count(MODE_LINE) == 1
    return text


def test_legacy_w3_production_compose_without_mode_line_passes(tmp_path: Path) -> None:
    primary = current_compose().replace(MODE_LINE + "\n", "", 1)
    result = run_source_contract(tmp_path, primary)
    assert result.returncode == 0, result.stdout + result.stderr


def test_clean_post_w4b_production_compose_with_reviewed_inline_default_passes(
    tmp_path: Path,
) -> None:
    result = run_source_contract(tmp_path, current_compose())
    assert result.returncode == 0, result.stdout + result.stderr


def test_production_compose_with_non_inline_default_is_blocked(tmp_path: Path) -> None:
    primary = current_compose().replace(
        MODE_LINE,
        "      HERMES_UI_ASSET_MODE: ${HERMES_UI_ASSET_MODE:-hashed-w4}",
        1,
    )
    result = run_source_contract(tmp_path, primary)
    assert result.returncode != 0
    assert "unexpected production W4B Compose mode line" in (result.stdout + result.stderr)


def test_production_compose_with_duplicate_mode_lines_is_blocked(tmp_path: Path) -> None:
    primary = current_compose().replace(MODE_LINE, MODE_LINE + "\n" + MODE_LINE, 1)
    result = run_source_contract(tmp_path, primary)
    assert result.returncode != 0
    assert "unexpected production W4B Compose mode line" in (result.stdout + result.stderr)


def test_unrelated_production_compose_drift_remains_blocked(tmp_path: Path) -> None:
    primary = current_compose() + "\n# unrelated production drift\n"
    result = run_source_contract(tmp_path, primary)
    assert result.returncode != 0
    assert "target base Compose differs from production baseline beyond W4B mode" in (
        result.stdout + result.stderr
    )


def test_renderer_fails_closed_if_source_contract_template_drifts(tmp_path: Path) -> None:
    drifted = tmp_path / "drifted-operator"
    drifted.write_text(
        OPERATOR.read_text(encoding="utf-8").replace(
            "mode_lines = [line for line in target if \"HERMES_UI_ASSET_MODE:\" in line]",
            "mode_lines = tuple(line for line in target if \"HERMES_UI_ASSET_MODE:\" in line)",
            1,
        ),
        encoding="utf-8",
    )
    output = tmp_path / "rendered-drifted"
    result = subprocess.run(
        ["python3", str(RENDERER), str(drifted), str(output)],
        text=True,
        capture_output=True,
        check=False,
    )
    assert result.returncode != 0
    assert "production Compose baseline replacement expected exactly once" in (
        result.stdout + result.stderr
    )
    assert not output.exists()
