from __future__ import annotations

from pathlib import Path
import re
import subprocess
import textwrap

import yaml


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "deploy-main.yml"
CI = ROOT / ".github" / "workflows" / "ci.yml"
HELPER = ROOT / "tools" / "runner" / "release" / "hermes-deals-deploy-main"
INSTALLER = ROOT / "tools" / "runner" / "install-github-main-deploy.sh"
UPLOAD_ARTIFACT_SHA = "b7c566a772e6b6bfb58ed0dc250532a479d7789f"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def workflow_trigger() -> dict:
    data = yaml.safe_load(read(WORKFLOW))
    return data.get("on") or data.get(True) or {}


def test_workflow_requires_explicit_owner_exact_sha_dispatch() -> None:
    text = read(WORKFLOW)
    trigger = workflow_trigger()

    assert set(trigger) == {"workflow_dispatch"}
    assert "workflow_run" not in text
    inputs = trigger["workflow_dispatch"]["inputs"]
    assert inputs["target_sha"]["required"] is True
    assert inputs["target_sha"]["type"] == "string"
    assert inputs["confirmation"]["required"] is True
    assert inputs["confirmation"]["type"] == "string"

    for marker in (
        "ORIGINAL_ACTOR: ${{ github.actor }}",
        "TRIGGERING_ACTOR: ${{ github.triggering_actor }}",
        "EVENT_REF: ${{ github.ref }}",
        "WORKFLOW_REF: ${{ github.workflow_ref }}",
        'owner != "rozkalnsandris"',
        'os.environ["EVENT_NAME"] != "workflow_dispatch"',
        'os.environ["EVENT_REF"] != "refs/heads/main"',
        "deploy-main.yml@refs/heads/main",
        "actor != owner",
        "triggering_actor != owner",
        're.fullmatch(r"[0-9a-f]{40}", target_sha)',
        'confirmation != f"DEPLOY {target_sha}"',
        "target SHA is not an ancestor of current main",
        "actions/workflows/ci.yml/runs",
        'row.get("event") == "push"',
        'row.get("head_branch") == "main"',
        'row.get("head_sha") == target_sha',
        'row.get("conclusion") == "success"',
        "/usr/local/sbin/hermes-deals-deploy-main",
        "hermes-deals-release",
        "group: hermes-deals-production-release",
        "cancel-in-progress: false",
        f"actions/upload-artifact@{UPLOAD_ARTIFACT_SHA}",
        "Database writes and migrations are not authorized by this workflow",
    ):
        assert marker in text

    assert "actions/upload-artifact@v6" not in text


def test_deploy_prewarms_current_week_without_write_path() -> None:
    text = read(WORKFLOW)
    start = text.index("      - name: Prewarm and verify current weekly overview")
    end = text.index("      - name: Verify public API and UI through Cloudflare Access", start)
    block = text[start:end]

    for marker in (
        'ZoneInfo("Europe/Berlin")',
        '"/api/v1/deals/weekly-specials?"',
        '"week_start": week_start.isoformat()',
        '"X-Hermes-Weekly-Cache"',
        '!= "HIT"',
        "warm_ms >= 1000.0",
        '"database_write": False',
        'print("WEEKLY_PREWARM=PASS")',
        'line.startswith("LOCAL_HEALTH_URL=")',
        'parsed.path != "/api/health"',
        "address.is_loopback or address.is_private or address.is_link_local",
    ):
        assert marker in block

    assert "docker" not in block.lower()
    assert "sudo" not in block.lower()
    assert "DATABASE_URL" not in block
    assert "INSERT " not in block
    assert "UPDATE " not in block
    assert "DELETE " not in block


def test_public_contract_stays_strict_and_cloudflare_authenticated() -> None:
    text = read(WORKFLOW)

    for marker in (
        'PUBLIC_VERIFY_MAX_ATTEMPTS: "6"',
        'PUBLIC_VERIFY_DELAY_SECONDS: "5"',
        "CF_ACCESS_CLIENT_ID: ${{ secrets.CF_ACCESS_CLIENT_ID }}",
        "CF_ACCESS_CLIENT_SECRET: ${{ secrets.CF_ACCESS_CLIENT_SECRET }}",
        '"CF-Access-Client-Id": access_client_id',
        '"CF-Access-Client-Secret": access_client_secret',
        "https://deals.rozkalns.net/api/health?",
        "https://deals.rozkalns.net/ui?",
        "https://deals.rozkalns.net/ui/review?",
        "public contract HTTP status mismatch",
        "public health payload is invalid",
        "public UI is missing required markers",
        "public UI still depends on external assets",
        'href="/ui/styles.css"',
        'src="/ui/app.js"',
        "PUBLIC_API_HEALTH=PASS",
        "PUBLIC_UI_BUNDLE=PASS",
        "PUBLIC_REVIEW=PASS",
        "PUBLIC_CLOUDFLARE_ACCESS=PASS",
        "public API/UI contract failed after",
    ):
        assert marker in text

    assert "print(access_client_id)" not in text
    assert "print(access_client_secret)" not in text
    assert "write_text(access_client_id" not in text
    assert "write_text(access_client_secret" not in text


def test_embedded_workflow_python_blocks_compile() -> None:
    text = read(WORKFLOW)
    blocks = re.findall(r"<<'PY'\n(.*?)\n\s+PY", text, flags=re.DOTALL)

    assert len(blocks) == 3
    for index, block in enumerate(blocks, start=1):
        compile(textwrap.dedent(block), f"deploy-main-block-{index}.py", "exec")


def test_main_ci_keeps_unique_push_runs_and_new_safe_name() -> None:
    text = read(CI)
    assert text.startswith("name: Hermes Deals CI checks\n")
    assert "hermes-deals-ci-${{ github.event_name }}-${{ github.event.pull_request.number || github.sha }}" in text
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in text
    assert "group: hermes-deals-ci-${{ github.ref }}" not in text


def test_root_helper_accepts_authorized_ancestors_and_never_downgrades() -> None:
    text = read(HELPER)
    subprocess.run(["bash", "-n", str(HELPER)], check=True)

    for marker in (
        "queued SHA is not an ancestor of current origin/main",
        "flock 9",
        "DEPLOY_RESULT=NO_OP_ALREADY_CURRENT",
        "DEPLOY_RESULT=NO_OP_STALE",
        "current production SHA is not an ancestor of queued target SHA",
        "release-control worktree must remain detached",
        "docker build",
        "org.opencontainers.image.revision=$TARGET_SHA",
        'yield from walk(getattr(route, "routes", ()))',
        'getattr(route, "path", None)',
        "up -d --no-deps --no-build --wait api",
        "production database container changed",
        "production web container changed",
        "DEPLOY_RESULT=FAIL_ROLLBACK_PASS",
        "DEPLOY_RESULT=PASS",
        "DATABASE_WRITES_AUTHORIZED=false",
        "MIGRATION_COMMANDS_EXECUTED=false",
        "ROLLBACK_PERFORMED=false",
    ):
        assert marker in text

    assert "flock -n 9" not in text
    assert "requested SHA is not exact current origin/main" not in text
    assert "alembic upgrade" not in text
    assert "docker compose down" not in text
    assert "workflow_dispatch" not in text
    assert "github issue" not in text.lower()


def test_installer_grants_only_deploy_helper_to_release_runner() -> None:
    text = read(INSTALLER)
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)

    assert "actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-release.service" in text
    assert "github-release-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-deploy-main *" in text
    assert "RUNNER_HAS_DOCKER_GROUP=false" in text
    assert "PRODUCTION_CHANGED=false" in text
