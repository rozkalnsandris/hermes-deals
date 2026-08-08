from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
OPERATOR = ROOT / "tools" / "runner" / "w4b" / "hermes-deals-w4b-operator"
RENDERER = ROOT / "tools" / "runner" / "w4b" / "render-hermes-deals-w4b-operator.py"


def render_operator(tmp_path: Path) -> str:
    output = tmp_path / "hermes-deals-w4b-operator"
    subprocess.run(
        ["python3", str(RENDERER), str(OPERATOR), str(output)],
        check=True,
    )
    subprocess.run(["bash", "-n", str(output)], check=True)
    return output.read_text(encoding="utf-8")


def test_w4b_source_contract_accepts_only_two_reviewed_compose_states(
    tmp_path: Path,
) -> None:
    source = render_operator(tmp_path)

    assert (
        'mode_lines != ["      HERMES_UI_ASSET_MODE: '
        '${HERMES_UI_ASSET_MODE:-inline-w3}"]'
    ) in source
    assert (
        "if primary != target and primary != target_without_mode:\n"
        '    raise SystemExit("target base Compose differs from reviewed W4B source states")'
    ) in source
    assert (
        "if target_without_mode != primary:\n"
        '    raise SystemExit("target base Compose differs from production baseline beyond W4B mode")'
    ) not in source
    assert "if target_prod.read_bytes() != primary_prod.read_bytes():" in source
    assert 'raise SystemExit("production Compose overlay drift")' in source


def test_w4b_source_contract_rejects_unrelated_line_drift() -> None:
    target = [
        "services:",
        "  api:",
        "    environment:",
        "      HERMES_UI_ASSET_MODE: ${HERMES_UI_ASSET_MODE:-inline-w3}",
        "      APP_ENV: production",
    ]
    target_without_mode = [
        line for line in target if "HERMES_UI_ASSET_MODE:" not in line
    ]

    exact_target = list(target)
    legacy_reviewed = list(target_without_mode)
    unrelated_drift = [*target_without_mode, "      UNREVIEWED: true"]

    def accepted(primary: list[str]) -> bool:
        return primary == target or primary == target_without_mode

    assert accepted(exact_target)
    assert accepted(legacy_reviewed)
    assert not accepted(unrelated_drift)


def test_w4b_renderer_fails_closed_if_source_contract_template_drifts(
    tmp_path: Path,
) -> None:
    drifted = tmp_path / "drifted-operator"
    drifted.write_text(
        OPERATOR.read_text(encoding="utf-8").replace(
            "if target_without_mode != primary:\n",
            "if primary != target_without_mode:\n",
            1,
        ),
        encoding="utf-8",
    )
    rendered = tmp_path / "rendered"
    result = subprocess.run(
        ["python3", str(RENDERER), str(drifted), str(rendered)],
        text=True,
        capture_output=True,
        check=False,
    )

    assert result.returncode != 0
    assert "reviewed Compose source-state contract replacement expected exactly once" in (
        result.stdout + result.stderr
    )
    assert not rendered.exists()
