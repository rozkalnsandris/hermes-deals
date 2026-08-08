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


def test_cutover_sequences_target_api_before_forced_web_recreate(tmp_path: Path) -> None:
    source = render_operator(tmp_path)

    combined = (
        'compose "w4b-$TARGET_SHORT" hashed-w4 "$NGINX_TARGET" '
        'up -d --no-deps --no-build --wait api web'
    )
    api_phase = (
        'compose "w4b-$TARGET_SHORT" hashed-w4 "$NGINX_TARGET" '
        'up -d --no-deps --no-build --wait api'
    )
    transition_call = 'if (( APPLY_RC == 0 )) && ! assert_target_api_transition; then'
    web_phase = (
        'compose "w4b-$TARGET_SHORT" hashed-w4 "$NGINX_TARGET" '
        'up -d --no-deps --no-build --wait --force-recreate web'
    )

    assert combined not in source
    assert source.count(api_phase) == 1
    assert source.count(web_phase) == 1
    assert source.count(transition_call) == 1
    assert source.index(api_phase) < source.index(transition_call) < source.index(web_phase)


def test_rollback_sequences_previous_api_before_forced_web_recreate(tmp_path: Path) -> None:
    source = render_operator(tmp_path)

    combined = (
        'compose "${old_tag#hermes-deals-api:}" inline-w3 "$old_nginx" '
        'up -d --no-deps --no-build --wait api web'
    )
    api_phase = (
        'compose "${old_tag#hermes-deals-api:}" inline-w3 "$old_nginx" '
        'up -d --no-deps --no-build --wait api'
    )
    web_phase = (
        'compose "${old_tag#hermes-deals-api:}" inline-w3 "$old_nginx" '
        'up -d --no-deps --no-build --wait --force-recreate web'
    )

    assert combined not in source
    assert source.count(api_phase) == 1
    assert source.count(web_phase) == 1
    assert source.index(api_phase) < source.index(web_phase)


def test_api_transition_guard_binds_exact_target_image_revision_and_mode(tmp_path: Path) -> None:
    source = render_operator(tmp_path)

    assert "assert_target_api_transition()" in source
    assert 'expected_image="$(docker image inspect "$TARGET_IMAGE" --format \'{{.Id}}\')"' in source
    assert 'if [[ "$revision" != "$TARGET_SHA" ]]; then' in source
    assert "grep '^HERMES_UI_ASSET_MODE='" in source
    assert "HERMES_UI_ASSET_MODE=hashed-w4" in source
    assert 'if (( APPLY_RC == 0 )) && ! assert_target_api_transition; then' in source


def test_sequence_fix_does_not_broaden_production_mutation_surface(tmp_path: Path) -> None:
    source = render_operator(tmp_path)

    for forbidden in (
        "alembic upgrade",
        "alembic downgrade",
        "docker compose down",
        "ufw ",
        "systemctl restart cloudflared",
        "systemctl stop cloudflared",
        "systemctl start cloudflared",
        "git reset",
        "git clean",
        "git checkout",
    ):
        assert forbidden not in source

    assert "--no-deps --no-build --wait api" in source
    assert "--force-recreate web" in source
