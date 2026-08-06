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


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_workflow_queues_every_successful_main_ci_on_one_rpi5_runner() -> None:
    text = read(WORKFLOW)
    data = yaml.safe_load(text)
    trigger = data.get("on") or data.get(True)

    assert set(trigger) == {"workflow_run", "workflow_dispatch"}
    assert trigger["workflow_run"]["workflows"] == ["Hermes Deals CI"]
    assert trigger["workflow_run"]["types"] == ["completed"]
    assert trigger["workflow_run"]["branches"] == ["main"]
    assert "github.event.workflow_run.conclusion == 'success'" in text
    assert 'run.get("event") != "push"' in text
    assert 'run.get("head_branch") != "main"' in text
    assert "queued SHA is no longer an ancestor of main" in text
    assert "hermes-deals-release" in text
    assert "/usr/local/sbin/hermes-deals-deploy-main" in text
    assert "https://deals.rozkalns.net/api/health" in text
    assert "https://deals.rozkalns.net/ui" in text
    assert "https://deals.rozkalns.net/ui/review" in text
    assert "public-health.headers" in text
    assert "public-health.json" in text
    assert "public-ui.headers" in text
    assert "public-ui.html" in text
    assert "public-review.headers" in text
    assert "public-review.html" in text
    assert "public-ui-check.json" in text
    assert 'hermes-production-bundle" content="inline-v1' in text
    assert 'data-hermes-production-bundle="styles.css"' in text
    assert 'data-hermes-production-bundle="app.js"' in text
    assert 'href="/ui/styles.css"' in text
    assert 'src="/ui/app.js"' in text
    assert "PUBLIC_UI_BUNDLE=PASS" in text
    assert "actions/upload-artifact@v6" in text
    assert "actions/upload-artifact@v4" not in text
    assert "concurrency:" not in text
    for forbidden in ("pr_number", "issue", "plan", "APPLY api-ui", "release registry"):
        assert forbidden not in text


def test_public_contract_retries_bounded_edge_propagation_without_weakening() -> None:
    text = read(WORKFLOW)

    for marker in (
        'PUBLIC_VERIFY_MAX_ATTEMPTS: "6"',
        'PUBLIC_VERIFY_DELAY_SECONDS: "5"',
        '"Cache-Control": "no-cache"',
        '"Pragma": "no-cache"',
        '"deploy_sha": target_sha',
        'f"public-attempt-{attempt:02d}"',
        '"validation.json"',
        '"validation.err"',
        '"public-verification-attempt.txt"',
        "PUBLIC_VERIFY_ATTEMPT=",
        "time.sleep(delay_seconds)",
        "public API/UI contract failed after",
    ):
        assert marker in text

    assert "if not 1 <= max_attempts <= 10" in text
    assert "if not 0 <= delay_seconds <= 30" in text
    assert "public UI body is unexpectedly small" in text
    assert "public Review body is unexpectedly small" in text
    assert "public UI is missing required markers" in text
    assert "public UI still depends on external assets" in text
    assert 'href="/ui/styles.css"' in text
    assert 'src="/ui/app.js"' in text
    assert "external_ui_assets_required" in text
    assert 'shutil.copy2(result_path, evidence_dir / "public-ui-check.json")' in text


def test_public_contract_uses_cloudflare_access_service_secrets_safely() -> None:
    text = read(WORKFLOW)

    for marker in (
        "CF_ACCESS_CLIENT_ID: ${{ secrets.CF_ACCESS_CLIENT_ID }}",
        "CF_ACCESS_CLIENT_SECRET: ${{ secrets.CF_ACCESS_CLIENT_SECRET }}",
        'os.environ.get("CF_ACCESS_CLIENT_ID", "")',
        'os.environ.get("CF_ACCESS_CLIENT_SECRET", "")',
        '"CF-Access-Client-Id": access_client_id',
        '"CF-Access-Client-Secret": access_client_secret',
        "Cloudflare Access service credentials are missing",
        "Cloudflare Access client ID is invalid",
        "Cloudflare Access client secret is invalid",
        '"cloudflare_access_service_auth": True',
        "PUBLIC_CLOUDFLARE_ACCESS=PASS",
    ):
        assert marker in text

    assert "access_client_id =" in text
    assert "access_client_secret =" in text
    assert "if not access_client_id or not access_client_secret" in text
    assert "request_headers" in text
    assert "write_headers" in text
    assert 'print(access_client_id)' not in text
    assert 'print(access_client_secret)' not in text
    assert 'write_text(access_client_id' not in text
    assert 'write_text(access_client_secret' not in text
    assert 'json.dumps(access_client_id' not in text
    assert 'json.dumps(access_client_secret' not in text


def test_embedded_workflow_python_blocks_compile() -> None:
    text = read(WORKFLOW)
    blocks = re.findall(r"<<'PY'\n(.*?)\n\s+PY", text, flags=re.DOTALL)

    assert len(blocks) == 2
    for index, block in enumerate(blocks, start=1):
        compile(textwrap.dedent(block), f"deploy-main-block-{index}.py", "exec")


def test_main_push_ci_runs_are_not_cancelled_by_newer_merges() -> None:
    text = read(CI)
    assert "hermes-deals-ci-${{ github.event_name }}-${{ github.event.pull_request.number || github.sha }}" in text
    assert "cancel-in-progress: ${{ github.event_name == 'pull_request' }}" in text
    assert "group: hermes-deals-ci-${{ github.ref }}" not in text


def test_root_helper_accepts_queued_ancestors_and_never_downgrades() -> None:
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

    assert 'any(r.path ==' not in text
    assert "flock -n 9" not in text
    assert "requested SHA is not exact current origin/main" not in text
    assert "alembic upgrade" not in text
    assert "docker compose down" not in text
    assert "workflow_dispatch" not in text
    assert "github issue" not in text.lower()


def test_installer_grants_only_new_helper_to_existing_runner() -> None:
    text = read(INSTALLER)
    subprocess.run(["bash", "-n", str(INSTALLER)], check=True)

    assert "actions.runner.rozkalnsandris-hermes-deals.rpi5-hermes-deals-release.service" in text
    assert "github-release-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-deploy-main *" in text
    assert "RUNNER_HAS_DOCKER_GROUP=false" in text
    assert "PRODUCTION_CHANGED=false" in text
