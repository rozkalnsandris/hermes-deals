from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/netto-missing-normal-price-rpi5-audit.yml"
INSTALLER = ROOT / "tools/runner/install-netto-missing-normal-price-rpi5-audit.sh"


def test_workflow_is_owner_gated_exact_sha_read_only() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in text
    assert "audit:netto-missing-normal-price-v1" in text
    assert "EXPECTED_OWNER_LOGIN: rozkalnsandris" in text
    assert "EXPECTED_OWNER_ID: '277435981'" in text
    assert "audit requires same-repository PR head" in text
    assert "merged SHA is not reachable from current main" in text
    assert "merge_push_ci" in text
    assert "tree_equivalent_pr_head_ci" in text
    assert "neither merge SHA nor exact PR head has successful CI" in text
    assert "tested PR head tree differs from squash merge tree" in text
    assert "/git/commits/{sha}" in text
    assert "/git/commits/{head_sha}" in text
    assert "runs-on: [self-hosted, Linux, ARM64, hermes-deals-audit]" in text
    assert "hermes-deals-netto-missing-normal-price-audit-dispatch" in text
    assert "Database/Review writes: **not authorized**" in text
    assert "Production deploy: **not authorized**" in text
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in text


def test_historical_ci_fallback_never_changes_approved_sha() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "head_sha = str((pr.get('head') or {}).get('sha') or '')" in text
    assert "sha = str(pr.get('merge_commit_sha') or '')" in text
    assert "head_tree = str((head_commit.get('tree') or {}).get('sha') or '')" in text
    assert "merge_tree = str((merge_commit.get('tree') or {}).get('sha') or '')" in text
    assert "merge_tree != head_tree" in text
    assert "out.write(f'should_run=true\\nsha={sha}\\npr_number={pr_number}\\nci_mode={ci_mode}\\n')" in text
    assert "sha={head_sha}" not in text


def test_report_always_clears_one_shot_label_and_reports_run_id() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "PR_NUMBER: ${{ github.event.pull_request.number }}" in text
    assert "RUN_ID: ${{ github.run_id }}" in text
    assert "AUTH_RESULT: ${{ needs.authorize.result }}" in text
    assert "AUTHORIZATION_FAIL" in text
    assert "Workflow run: \\`${RUN_ID}\\`" in text
    assert 'gh api --method DELETE "repos/${REPOSITORY}/issues/${PR_NUMBER}/labels/' in text


def test_installer_pins_exact_corpus_and_runtime_identity() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert "EXPECTED_SOURCE_REPO='/home/andris/hermes-deals-worktrees/netto-missing-normal-price-audit-v1'" in text
    assert "EXPECTED_N9_SHA='2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147'" in text
    assert "EXPECTED_N10_SHA='bf35bff323d76a2b29a7248df067641e5b9f2a7d29329cf53bf9fc0ae832734a'" in text
    assert "CORPUS_ROOT='/home/andris/hermes-deals-netto-corpus/flyers'" in text
    assert "PyMuPDF 1.28.0 required" in text
    assert "runuser -u andris" in text
    assert "GIT_OPTIONAL_LOCKS=0" in text
    assert "github-runner must not belong to the Docker group" in text
    assert "netto_missing_normal_price_audit.py" in text
    assert "netto_visual_geometry_corpus_replay.py" in text
    assert "netto_visual_geometry_shadow.py" in text


def test_dispatcher_exports_only_sanitized_read_only_evidence() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert "missing-normal-price-audit.json" in text
    assert "audit-summary.json" in text
    assert "audit-artifact-manifest.json" in text
    assert "p['review_only_default'] is True and p['promotion_ready'] is False" in text
    assert "p['database_write_performed'] is False and p['deployment_performed'] is False" in text
    assert "automatic_approval_enabled" in text
    assert "automatic_publish_enabled" in text
    assert "sudoers" in text.lower()


def test_control_plane_does_not_contain_high_risk_actions() -> None:
    combined = WORKFLOW.read_text(encoding="utf-8") + INSTALLER.read_text(encoding="utf-8")
    forbidden = (
        "docker compose up",
        "docker compose down",
        "alembic upgrade",
        "cloudflared",
        "systemctl restart",
        "systemctl stop",
        "DROP TABLE",
        "DELETE FROM",
    )
    for token in forbidden:
        assert token not in combined
