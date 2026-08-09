from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
OPERATOR = ROOT / "tools" / "runner" / "w4c" / "hermes_deals_w4c_operator.py"
DISPATCHER = ROOT / "tools" / "runner" / "w4c" / "hermes-deals-w4c-dispatch"
FINALIZER = ROOT / "tools" / "runner" / "w4c" / "run-hermes-deals-w4c-owner-finalizer.sh"
OVERRIDE = ROOT / "tools" / "runner" / "w4c" / "docker-compose.w4c.yml"
WORKFLOW = ROOT / ".github" / "workflows" / "w4c-production-cache-rollout.yml"

TARGET = "42238d93045e60430a42cd13b85b598e78c7d528"
W4B = "128325461f249791af8a5653163772e955dd2b89"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_w4c_operator_is_exact_target_pinned_and_keeps_w4b_as_rollback() -> None:
    operator = read(OPERATOR)

    assert f'TARGET_SHA = "{TARGET}"' in operator
    assert f'W4B_TARGET_SHA = "{W4B}"' in operator
    assert 'W4B_IMAGE = f"hermes-deals-api:w4b-{W4B_TARGET_SHORT}"' in operator
    assert 'TARGET_IMAGE = f"hermes-deals-api:{TARGET_TAG}"' in operator
    assert 'EXPECTED_ALEMBIC = "0007_comparison_family_pricing"' in operator
    assert 'Path("/run/lock/hermes-deals-production-deploy.lock")' in operator
    assert 'Path("/run/lock/hermes-deals-w4b.lock")' in operator
    assert 'Path("/run/lock/hermes-deals-w4c.lock")' in operator
    assert '"DEALS_BIND_IP": "127.0.0.1"' in operator
    assert '"DEALS_HTTP_PORT": "9128"' in operator
    assert '"HERMES_UI_ASSET_MODE": ui_mode' in operator
    assert '"W4C_NGINX_CONFIG": str(nginx_config)' in operator


def test_w4c_operator_preserves_database_git_env_and_cloudflared_boundaries() -> None:
    operator = read(OPERATOR)

    assert "SELECT version_num FROM alembic_version;" in operator
    assert "alembic upgrade" not in operator
    assert "alembic downgrade" not in operator
    assert 'primary_git("status", "--porcelain=v1", "--untracked-files=all")' in operator
    assert 'sha_file(PRIMARY / ".env")' in operator
    assert '"systemctl", "show", "-p", "MainPID", "--value", "cloudflared.service"' in operator
    assert "systemctl restart" not in operator
    assert "systemctl stop" not in operator
    assert "systemctl start" not in operator
    assert "cloudflare" not in operator.casefold().replace("cloudflared", "")
    assert "PY_ENV_WRITE" not in operator
    assert ".write_text(" not in operator.split("def write_rollback_state", 1)[0]


def test_w4c_cutover_and_rollback_are_api_first_then_forced_web_recreate() -> None:
    operator = read(OPERATOR)

    cutover = operator.split("def cutover()", 1)[1].split("def verify()", 1)[0]
    api_apply = cutover.index('"--wait",\n            "api"')
    web_recreate = cutover.index('"--force-recreate"')
    assert api_apply < web_recreate
    assert 'service_container("db") == before.db_id' in cutover
    assert 'except Exception as exc:' in cutover
    assert 'GateError("cutover_unexpected_failure")' in cutover
    assert "rollback_from_state()" in cutover

    rollback = operator.split("def rollback_from_state()", 1)[1].split("def output(", 1)[0]
    rollback_api = rollback.index('"--wait",\n        "api"')
    rollback_web = rollback.index('"--force-recreate"')
    assert rollback_api < rollback_web
    assert 'assert_hashed_ui(restored.web_base, "w4b")' in rollback


def test_w4c_cache_contract_is_application_owned_and_exact() -> None:
    operator = read(OPERATOR)
    override = read(OVERRIDE)

    assert '"cache-w4b" if cache_contract == "w4b" else "cache-html-w4c"' in operator
    assert '"cache-asset-w4c"' in operator
    assert 'status_code(base, "/ui/assets/not-in-package.js") == "404"' in operator
    assert 'status_code(base, "/ui/assets/w4-shadow-package.json") == "404"' in operator
    assert "proxy_pass" not in override
    assert "cache-control" not in override.casefold()
    assert "immutable" not in override.casefold()
    assert "max-age" not in override.casefold()


def test_w4c_runner_cannot_invoke_root_only_rollback() -> None:
    dispatcher = read(DISPATCHER)
    finalizer = read(FINALIZER)
    workflow = read(WORKFLOW)

    assert '^(preflight|cutover|verify)$' in dispatcher
    assert "rollback" not in dispatcher
    assert "RUNNER_ROLLBACK_AUTHORIZED=false" in finalizer
    assert "$DISPATCHER preflight" in finalizer
    assert "$DISPATCHER cutover" in finalizer
    assert "$DISPATCHER verify" in finalizer
    assert "$DISPATCHER rollback" not in finalizer
    assert '"/hermes-477 preflight": "preflight"' in workflow
    assert '"/hermes-477 cutover": "cutover"' in workflow
    assert '"/hermes-477 verify": "verify"' in workflow
    assert "/hermes-477 rollback" not in workflow


def test_w4c_owner_finalizer_pins_isolated_runtime_delta_and_read_only_preflight() -> None:
    finalizer = read(FINALIZER)

    assert f"TARGET_SHA='{TARGET}'" in finalizer
    assert f"W4B_TARGET_SHA='{W4B}'" in finalizer
    assert "$'M\\tbackend/app/runtime.py'" in finalizer
    for path in (
        "backend/app",
        "backend/frontend",
        "backend/alembic",
        "backend/Dockerfile",
        "backend/requirements.txt",
        "backend/alembic.ini",
        "backend/.dockerignore",
        "docker-compose.yml",
        "docker-compose.production.yml",
        "infra/nginx.conf",
    ):
        assert path in finalizer
    assert "w4c_runtime_delta_not_isolated" in finalizer
    assert 'PREFLIGHT_OUTPUT="$(sudo --non-interactive "$DISPATCHER" preflight 2>&1)"' in finalizer
    assert "PRODUCTION_MUTATED=false" in finalizer
    assert "production_runtime_changed_during_finalizer" in finalizer
    assert "production_env_changed_during_finalizer" in finalizer
    assert "cloudflared_changed_during_finalizer" in finalizer
    assert '"$DISPATCHER" cutover' not in finalizer


def test_w4c_public_bridge_authorizes_before_self_hosted_and_has_no_checkout() -> None:
    workflow = read(WORKFLOW)

    assert "W4C production cache rollout bridge" in workflow
    assert 'if: github.event.issue.pull_request == null' in workflow
    assert 'owner = "rozkalnsandris"' in workflow
    assert 'if os.environ["ISSUE_NUMBER"] != "477":' in workflow
    assert "w4c-production-cache-rollout.yml@refs/heads/main" in workflow
    assert "group: hermes-deals-production-release" in workflow
    assert "permissions: {}" in workflow
    assert "actions/checkout" not in workflow
    assert "/usr/local/sbin/hermes-deals-w4c-dispatch" in workflow
    assert "Run installed W4C dispatcher on RPi5" in workflow
    authorize_pos = workflow.index("Authorize exact owner W4C command")
    self_hosted_pos = workflow.index("Run installed W4C dispatcher on RPi5")
    assert authorize_pos < self_hosted_pos


def test_w4c_control_plane_does_not_modify_existing_w4b_install_root() -> None:
    finalizer = read(FINALIZER)
    operator = read(OPERATOR)

    assert "/usr/local/libexec/hermes-deals-w4c" in finalizer
    assert "/usr/local/libexec/hermes-deals-w4c" in operator
    assert "/usr/local/libexec/hermes-deals-w4b" not in finalizer
    assert "/usr/local/libexec/hermes-deals-w4b" not in operator
    assert "/var/lib/hermes-deals-w4c" in operator
    assert "/var/lib/hermes-deals-w4b" not in operator
