from __future__ import annotations

from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
OPERATOR = ROOT / "tools" / "runner" / "w4b" / "hermes-deals-w4b-operator"
RENDERER = ROOT / "tools" / "runner" / "w4b" / "render-hermes-deals-w4b-operator.py"
DISPATCHER = ROOT / "tools" / "runner" / "w4b" / "hermes-deals-w4b-dispatch"
FINALIZER = ROOT / "tools" / "runner" / "w4b" / "run-hermes-deals-w4b-owner-finalizer.sh"
OVERRIDE = ROOT / "tools" / "runner" / "w4b" / "docker-compose.w4b.yml"
WORKFLOW = ROOT / ".github" / "workflows" / "w4b-production-cutover.yml"
TARGET_SHA = "128325461f249791af8a5653163772e955dd2b89"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def render_operator(tmp_path: Path) -> str:
    output = tmp_path / "hermes-deals-w4b-operator"
    subprocess.run(
        ["python3", str(RENDERER), str(OPERATOR), str(output)],
        check=True,
    )
    return output.read_text(encoding="utf-8")


def test_w4b_root_scripts_are_syntax_valid(tmp_path: Path) -> None:
    for path in (OPERATOR, DISPATCHER, FINALIZER):
        subprocess.run(["bash", "-n", str(path)], check=True)
    subprocess.run(["python3", "-m", "py_compile", str(RENDERER)], check=True)

    rendered = tmp_path / "rendered-operator"
    subprocess.run(
        ["python3", str(RENDERER), str(OPERATOR), str(rendered)],
        check=True,
    )
    subprocess.run(["bash", "-n", str(rendered)], check=True)


def test_w4b_rendered_operator_is_exact_target_bounded_and_rollback_capable(
    tmp_path: Path,
) -> None:
    source = render_operator(tmp_path)

    assert f"TARGET_SHA='{TARGET_SHA}'" in source
    assert "MODE=\"$1\"" in source
    assert "^(preflight|cutover|verify|rollback)$" in source
    assert "TARGET_IMAGE=\"hermes-deals-api:w4b-$TARGET_SHORT\"" in source
    assert "target base Compose differs from production baseline beyond W4B mode" in source
    assert "target nginx hashed-asset location mismatch" in source
    assert "DEALS_BIND_IP='127.0.0.1'" in source
    assert "DEALS_HTTP_PORT='9128'" in source
    assert "HERMES_UI_ASSET_MODE=\"$ui_mode\"" in source
    assert "W4B_NGINX_CONFIG=\"$nginx_config\"" in source
    assert "up -d --no-deps --no-build --wait api web" in source
    assert "assert_hashed_w4" in source
    assert "assert_inline_w3" in source
    assert "read_live_alembic" in source
    assert "cloudflared_pid" in source
    assert "primary_state" in source
    assert "rollback_internal" in source
    assert "cutover_validation_failed_auto_rollback_passed" in source
    assert "W4B_MODE=rollback" in source

    # Current authoritative production images are main-<12sha>. Preserve a
    # bounded legacy release-* rollback family, reject arbitrary tags, and bind
    # managed-main tags to the exact revision label prefix.
    assert '^hermes-deals-api:main-([0-9a-f]{12})$' in source
    assert "current_api_main_tag_revision_mismatch" in source
    assert '^hermes-deals-api:release-[A-Za-z0-9_.-]+$' in source
    assert 'main_tag = re.fullmatch(r"hermes-deals-api:main-([0-9a-f]{12})", tag)' in source
    assert "values[2].startswith(main_tag.group(1))" in source
    assert 'values[0].startswith("hermes-deals-api:release-")' not in source
    assert '[[ "$API_IMAGE_TAG" == hermes-deals-api:release-* ]]' not in source
    assert "fail 'current_api_tag_not_release_managed'" in source

    # The root-owned operator must not weaken Git's safe.directory protection.
    # Read-only production Git state is collected under the repository owner
    # identity instead, and staged diff helpers are disabled.
    assert "for command in curl docker flock grep install python3 runuser sha256sum stat systemctl; do" in source
    assert 'runuser -u andris -- git -C "$PRIMARY" "$@"' in source
    assert '"$(primary_git rev-parse HEAD)"' in source
    assert '"$(primary_git branch --show-current)"' in source
    assert '"$(primary_git status --porcelain=v1 --untracked-files=all)"' in source
    assert '"$(primary_git diff --cached --binary --no-ext-diff --no-textconv)"' in source
    assert 'git -C "$PRIMARY" rev-parse HEAD' not in source
    assert "safe.directory" not in source

    # Compose JSON must remain on stdin for the model parser. Python source is
    # supplied with -c rather than a heredoc competing for fd 0.
    assert 'compose "$api_tag" "$ui_mode" "$nginx_config" config --format json |' in source
    assert "python3 -c '\nimport json, os, sys" in source
    assert "data = json.load(sys.stdin)" in source
    assert 'python3 - "$api_tag" "$ui_mode" "$nginx_config" <<\'PY\'' not in source

    for forbidden in (
        "alembic upgrade",
        "alembic downgrade",
        "ufw ",
        "cloudflared tunnel",
        "systemctl restart cloudflared",
        "systemctl stop cloudflared",
        "systemctl start cloudflared",
        "git reset",
        "git clean",
        "git checkout",
    ):
        assert forbidden not in source


def test_w4b_operator_renderer_fails_closed_on_template_drift(tmp_path: Path) -> None:
    drifted = tmp_path / "drifted-operator"
    drifted.write_text(
        read(OPERATOR).replace(
            "current_api_tag_not_release_managed",
            "unexpected_validator_drift",
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
    assert "managed-image baseline replacement expected exactly once" in (
        result.stdout + result.stderr
    )
    assert not rendered.exists()


def test_w4b_operator_renderer_fails_closed_on_production_git_state_drift(
    tmp_path: Path,
) -> None:
    drifted = tmp_path / "drifted-git-state-operator"
    drifted.write_text(
        read(OPERATOR).replace(
            'git -C "$PRIMARY" rev-parse HEAD',
            'git -C "$PRIMARY" rev-parse --verify HEAD',
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
    assert "production Git state replacement expected exactly once" in (
        result.stdout + result.stderr
    )
    assert not rendered.exists()


def test_w4b_operator_renderer_fails_closed_on_compose_validator_stdin_drift(
    tmp_path: Path,
) -> None:
    drifted = tmp_path / "drifted-compose-stdin-operator"
    drifted.write_text(
        read(OPERATOR).replace(
            'python3 - "$api_tag" "$ui_mode" "$nginx_config" <<\'PY\'',
            'python3 - "$api_tag" "$ui_mode" <<\'PY\'',
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
    assert "Compose validator stdin head replacement expected exactly once" in (
        result.stdout + result.stderr
    )
    assert not rendered.exists()


def test_w4b_dispatcher_does_not_expose_rollback_to_runner() -> None:
    source = read(DISPATCHER)

    assert "^(preflight|cutover|verify)$" in source
    assert "mode_not_runner_authorized" in source
    assert "operator.sha256" in source
    assert "sha256sum \"$OPERATOR\"" in source
    assert 'exec "$OPERATOR" "$MODE"' in source
    assert "rollback)" not in source


def test_w4b_owner_finalizer_refreshes_only_verified_exact_target_control_plane() -> None:
    source = read(FINALIZER)

    assert f"TARGET_SHA='{TARGET_SHA}'" in source
    assert "RUNNER_USER='github-release-runner'" in source
    assert "render-hermes-deals-w4b-operator.py" in source
    assert 'sudo install -o root -g root -m 0755 "$RENDERED_OPERATOR" "$OPERATOR"' in source
    assert "tree_digest()" in source
    assert "SNAPSHOT_DIGEST=" in source
    assert "existing_target_source_mismatch" in source
    assert "existing_target_runtime_symlink_unsafe" in source
    assert "existing_target_source_symlink_unsafe" in source
    assert "CONTROL_PLANE_INSTALL_MODE='fresh'" in source
    assert "CONTROL_PLANE_INSTALL_MODE='refresh'" in source
    assert "CONTROL_PLANE_INSTALL_MODE=%s" in source
    assert "target_runtime_already_installed" not in source

    assert "$DISPATCHER preflight" in source
    assert "$DISPATCHER cutover" in source
    assert "$DISPATCHER verify" in source
    assert "$DISPATCHER rollback" not in source
    assert 'sudo -u "$RUNNER_USER" sudo --non-interactive "$OPERATOR" rollback' in source
    assert "runner_unexpectedly_authorized_for_root_only_rollback" in source
    assert 'sudo -u "$RUNNER_USER" sudo --non-interactive "$DISPATCHER" preflight' in source
    assert "PRODUCTION_GIT_UNCHANGED=true" in source
    assert "PRODUCTION_ENV_UNCHANGED=true" in source
    assert "PRODUCTION_RUNTIME_UNCHANGED=true" in source
    assert "CLOUDFLARED_UNCHANGED=true" in source


def test_w4b_compose_overlay_changes_only_mode_and_nginx_mount() -> None:
    source = read(OVERRIDE)
    assert source == (
        "services:\n"
        "  api:\n"
        "    environment:\n"
        "      HERMES_UI_ASSET_MODE: ${HERMES_UI_ASSET_MODE:?set_HERMES_UI_ASSET_MODE}\n"
        "  web:\n"
        "    volumes:\n"
        "      - ${W4B_NGINX_CONFIG:?set_W4B_NGINX_CONFIG}:/etc/nginx/conf.d/default.conf:ro\n"
    )


def test_w4b_public_repo_workflow_has_hosted_authorizer_and_restricted_runner() -> None:
    source = read(WORKFLOW)

    assert "issue_comment:" in source
    assert '"/hermes-374 preflight": "preflight"' in source
    assert '"/hermes-374 cutover": "cutover"' in source
    assert '"/hermes-374 verify": "verify"' in source
    assert 'if os.environ["ISSUE_NUMBER"] != "374":' in source
    assert 'if os.environ[key] != owner:' in source
    assert "w4b-production-cutover.yml@refs/heads/main" in source
    assert "hermes-deals-release" in source
    assert "permissions: {}" in source
    assert "actions/checkout" not in source
    assert "secrets." not in source
    assert 'sudo --non-interactive /usr/local/sbin/hermes-deals-w4b-dispatch "$MODE"' in source
    assert "dispatcher_failed_without_sanitized_reason" in source
    assert "GitHub runners cannot invoke the root-only rollback mode" in source
