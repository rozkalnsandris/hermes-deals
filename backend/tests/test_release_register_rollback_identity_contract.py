from __future__ import annotations

import pathlib
import subprocess


ROOT = pathlib.Path(__file__).resolve().parents[2]
REGISTER = ROOT / "tools/runner/release/hermes-deals-release-register"


def test_release_register_compares_image_identity_not_tag_text() -> None:
    subprocess.run(["bash", "-n", str(REGISTER)], check=True)
    text = REGISTER.read_text(encoding="utf-8")

    # The running production image must be validated by Docker image identity,
    # not by requiring the container tag text to equal the canonical rollback
    # tag. Legacy production tags (e.g. release-<ver>-<suffix>-<date>) are
    # accepted as long as they resolve to the same image ID as the container
    # and the canonical rollback tag resolves to that same image ID.
    for marker in (
        'CURRENT_IMAGE_ID="$(docker inspect "$CURRENT_CONTAINER" --format \'{{.Image}}\')"',
        'CURRENT_IMAGE_TAG="$(docker inspect "$CURRENT_CONTAINER" --format \'{{.Config.Image}}\')"',
        'docker image inspect "$CURRENT_IMAGE_TAG" --format \'{{.Id}}\'',
        "running production tag does not resolve to the container image ID",
        'docker image inspect "$ROLLBACK_TAG" --format \'{{.Id}}\'',
        "running production image ID does not match rollback tag",
    ):
        assert marker in text

    # The strict tag-text equality must no longer gate the registration.
    for forbidden in (
        '[[ "$CURRENT_IMAGE_TAG" == "$ROLLBACK_TAG" ]]',
        "running production tag is not the declared rollback tag",
    ):
        assert forbidden not in text


def test_release_register_preserves_safety_boundaries() -> None:
    text = REGISTER.read_text(encoding="utf-8")

    for marker in (
        "register tool must run as root",
        "another Hermes Deals release process is already active",
        "DATABASE_WRITES_AUTHORIZED=false",
        "PRODUCTION_APPLY_PERFORMED=false",
    ):
        assert marker in text

    for forbidden in (
        "alembic upgrade",
        "alembic downgrade",
        "docker compose up",
        "git reset",
        "git clean",
    ):
        assert forbidden not in text
