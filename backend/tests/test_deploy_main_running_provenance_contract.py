from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
HELPER = ROOT / "tools" / "runner" / "release" / "hermes-deals-deploy-main"


def _text() -> str:
    return HELPER.read_text(encoding="utf-8")


def test_deploy_main_trusts_running_managed_image_provenance_not_env_equality() -> None:
    text = _text()

    assert "production env tag does not match running API image" not in text
    assert 'if [[ "$OLD_TAG" =~ ^(main|w4b|w4c)-([0-9a-f]{12})$ ]]; then' in text
    assert 'MANAGED_TAG_SHA="${BASH_REMATCH[2]}"' in text
    assert '[[ "$MANAGED_TAG_SHA" == "${OLD_REVISION:0:12}" ]]' in text
    assert "managed current production image tag does not match OCI revision" in text
    assert 'elif [[ "$OLD_TAG" =~ ^release-[A-Za-z0-9_.-]+$ ]]; then' in text
    assert "current production image is not a managed Hermes Deals release image" in text
    assert 'docker image inspect "$OLD_IMAGE_REF" --format' in text
    assert "current image tag and container image ID disagree" in text


def test_deploy_main_tolerates_stale_env_only_after_running_provenance_checks() -> None:
    text = _text()

    provenance = text.index("MANAGED_TAG_SHA=''")
    image_identity = text.index("current image tag and container image ID disagree")
    env_read = text.index("PY_ENV_READ")
    stale_branch = text.index('if [[ "$ENV_TAG" != "$OLD_TAG" ]]; then')
    pre_alembic = text.index('PRE_ALEMBIC="$(read_alembic)"')

    assert provenance < image_identity < env_read < stale_branch < pre_alembic
    assert "running API provenance verified independently" in text
    assert "PRODUCTION_ENV_TAG_STALE=true" in text
    assert "PRODUCTION_ENV_TAG_STALE=false" in text


def test_deploy_main_keeps_env_write_after_successful_apply_and_rollback_gate() -> None:
    text = _text()

    apply = text.index('HERMES_DEALS_API_TAG="$NEW_TAG" "${COMPOSE[@]}" up -d')
    rollback = text.index('if [[ $APPLY_RC -ne 0 ]]; then')
    env_write = text.index('python3 - "$PRIMARY/.env" "$NEW_TAG" <<\'PY_ENV_WRITE\'')
    result_pass = text.index("printf 'DEPLOY_RESULT=PASS\\n'")

    assert apply < rollback < env_write < result_pass
    assert 'HERMES_DEALS_API_TAG="$OLD_TAG" "${COMPOSE[@]}" up -d' in text
    assert "DATABASE_WRITES_AUTHORIZED=false" in text
    assert "MIGRATION_COMMANDS_EXECUTED=false" in text
