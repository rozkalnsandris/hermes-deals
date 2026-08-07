from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/netto-ownership-separator-rpi5-audit.yml"
INSTALLER = ROOT / "tools/runner/install-netto-ownership-separator-rpi5-audit.sh"


def test_workflow_is_owner_only_merged_sha_and_no_checkout_on_self_hosted() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "pull_request_target:" in text
    assert "audit:netto-ownership-separator-v1" in text
    assert "EXPECTED_OWNER_LOGIN: rozkalnsandris" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert "ownership audits are accepted only on merged pull requests" in text
    assert "exact merged SHA has no successful main-push Hermes Deals CI checks run" in text
    assert "runs-on:\n      - self-hosted\n      - Linux\n      - ARM64\n      - hermes-deals-audit" in text
    self_hosted = text.split("  rpi5-audit:\n", 1)[1].split("\n  report:\n", 1)[0]
    assert "permissions: {}" in self_hosted
    assert "actions/checkout" not in self_hosted
    assert "/usr/local/sbin/hermes-deals-netto-ownership-separator-audit-dispatch" in self_hosted
    assert "Production deployment: **not authorized**" in self_hosted
    assert "Database/Review write: **not authorized**" in self_hosted
    assert "Promotion ready: **false by contract**" in self_hosted
    report = text.split("  report:\n", 1)[1]
    assert "github.event.label.name == 'audit:netto-ownership-separator-v1'" in report
    assert "PR_NUMBER: ${{ github.event.pull_request.number }}" in report


def test_installer_pins_exact_runtime_and_immutable_evidence() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert "EXPECTED_SOURCE_REPO='/home/andris/hermes-deals-worktrees/netto-ownership-separator-audit-v1'" in text
    assert "GIT_OPTIONAL_LOCKS=0" in text
    assert "runuser -u andris" in text
    assert "/usr/bin/python3" in text
    assert 'version != "1.28.0"' in text
    assert "tools/netto_ownership_separator_audit.py" in text
    assert "tools/netto_visual_geometry_corpus_replay.py" in text
    assert "tools/netto_visual_geometry_shadow.py" in text
    assert "backend/tests/fixtures/netto/n2_independent_ownership_summary_v1.json" in text
    assert "/home/andris/hermes-deals-audits/netto-n9-visual-cell-validation-pack-v1-20260802T202304Z/generated/fixture-manifest.json" in text
    assert "2b180d67af4c5d1e586704088e3d685cff21ae2e12f3052254daf4553dd4e147" in text
    assert "/home/andris/hermes-deals-netto-corpus/flyers" in text
    assert "ownership-separator-audit.json" in text
    assert '"promotion_ready": False' in text
    assert '"database_write_performed": False' in text
    assert '"review_write_performed": False' in text
    assert '"deployment_performed": False' in text


def test_installer_sudo_boundary_is_single_dedicated_dispatcher() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert "github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-netto-ownership-separator-audit-dispatch" in text
    assert "github-runner must not belong to the Docker group" in text
    assert "docker compose" not in text
    assert "docker run" not in text
    assert "systemctl restart" not in text
    assert "systemctl enable" not in text
    assert "ufw " not in text
    assert "cloudflared" not in text
    assert "psql " not in text
    assert "alembic " not in text


def test_dispatcher_is_exact_sha_create_only_and_sanitized() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    assert '[[ $# -eq 2 ]] || fail "usage: hermes-deals-netto-ownership-separator-audit-dispatch <registered-commit-sha> <artifact-dir>"' in text
    assert '[[ "${commit_sha:-}" == "$EXPECTED_SHA" ]] || fail "requested commit is not the registered audit commit"' in text
    assert "--n9-manifest \"$n9_manifest\"" in text
    assert "--corpus-root \"$corpus_root\"" in text
    assert "--ownership-truth \"$ownership_truth_path\"" in text
    assert "--output \"$STAGING_DIR/ownership-separator-audit.json\"" in text
    assert '[[ ! -e "$STAGING_DIR" ]]' in text
    assert "allowed = {" in text
    for name in (
        "ownership-separator-audit.json",
        "audit-execution.log",
        "audit-exit-code.txt",
        "runtime-identity.json",
    ):
        assert name in text
    assert "sensitive content rejected" in text
    assert "sanitization_passed" in text
