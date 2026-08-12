from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/lidl-v631-c3-readonly-rpi5.yml"
DISPATCHER = ROOT / "tools/runner/lidl-v631-c3-readonly-dispatcher.sh"
INSTALLER = ROOT / "tools/runner/install-lidl-v631-c3-readonly-dispatcher.sh"


def _text(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def test_c3_rpi5_workflow_is_owner_gated_and_does_not_checkout_pr_code() -> None:
    source = _text(WORKFLOW)
    assert "workflow_dispatch:" in source
    assert "EXPECTED_OWNER_LOGIN: rozkalnsandris" in source
    assert "EXPECTED_OWNER_ID: '277435981'" in source
    assert "runs-on:\n      - self-hosted\n      - Linux\n      - ARM64\n      - hermes-deals-audit" in source
    assert "actions/checkout" not in source
    assert "pull_request:" not in source
    assert "pull_request_target:" not in source
    assert "sudo --non-interactive /usr/local/sbin/hermes-deals-lidl-v631-c3-readonly" in source
    assert "actions/upload-artifact@ea165f8d65b6e75b540449e92b4886f43607fa02" in source
    assert "issues: write" not in source
    assert "pull-requests: write" not in source


def test_c3_authorizer_binds_merged_registration_and_current_main_blobs() -> None:
    source = _text(WORKFLOW)
    for marker in (
        "if not pr.get('merged') or not pr.get('merged_at')",
        "registration merge is not reachable from current main",
        "c31df993e94707ffa35b82c4976f4b79e1154add",
        "65273e99a855e3ea26c65329745c5101d4d2d742",
        "5c183c4459275c99c7d0f9d66a7a5c425384a5be",
        "de26a292d727a89f9ad2b701a543897b6f87224b",
        "a5c1fdc09ba70ca1d009f0e983a5ab16a187c679",
        "current main C3 blob drift",
    ):
        assert marker in source


def test_dispatcher_is_read_only_against_live_runtime_and_fail_closed() -> None:
    source = _text(DISPATCHER)
    assert "docker ps" in source
    assert "docker inspect" in source
    assert "postgres:18.4-bookworm" in source
    assert "DATABASE_URL=\"$DATABASE_URL\"" in source
    assert "PYTHONDONTWRITEBYTECODE=1" in source
    assert "lidl_v631_c3_readonly_preflight.py" in source
    assert "--expected-head \"$CURRENT_SHA\"" in source
    assert "--corpus-root \"$CORPUS_ROOT\"" in source
    assert "merge-base --is-ancestor \"$registered_merge_sha\" \"$CURRENT_SHA\"" in source
    assert "[[ \"$RC\" -eq 0 || \"$RC\" -eq 30 ]]" in source
    assert "production_baseline_before') != report.get('production_baseline_after" in source
    assert "'transaction_read_only':'on'" in source
    assert "'transaction_isolation':'repeatable read'" in source
    assert "'snapshot_id':0" in source
    assert "'source_snapshots':1,'offer_candidates':1" in source
    assert "report.get('transaction_rolled_back') is not True" in source
    assert "CORPUS_AFTER=\"$(corpus_tree)\"" in source
    assert "audit Git index changed" in source

    forbidden = (
        "docker exec",
        "docker run",
        "docker compose up",
        "docker start",
        "docker restart",
        "pip install",
        "python3 -m pip",
        "apt install",
        "apt-get install",
        "apply_lidl_v631_semantic_persistence_plan",
        "git checkout",
        "git reset",
        "git pull",
        "git fetch",
    )
    for token in forbidden:
        assert token not in source


def test_dispatcher_private_material_is_root_owned_and_sanitized_output_is_fixed() -> None:
    source = _text(DISPATCHER)
    assert "PRIVATE_ROOT='/var/lib/hermes-deals/lidl-v631-c3-readonly-private'" in source
    assert "EVIDENCE_ROOT='/var/lib/hermes-deals/lidl-v631-c3-readonly'" in source
    assert "root:root:700" in source
    assert "root:root:755" in source
    assert "db-inspect.json" in source
    assert "root:root:600" in source
    assert "chown root:root \"$SUMMARY\"" in source
    assert "chmod 0644 \"$SUMMARY\"" in source
    assert "POSTGRES_PASSWORD" in source
    assert "summary.update" in source
    summary_block = source[source.index("summary={") : source.index("if [[ \"$RC\" -eq 30 ]]", source.index("summary={"))]
    assert "DATABASE_URL" not in summary_block
    assert "POSTGRES_PASSWORD" not in summary_block
    assert "github-runner:github-runner" not in source
    assert "artifact-dir" not in source


def test_workflow_reads_only_fixed_sanitized_evidence_path() -> None:
    source = _text(WORKFLOW)
    fixed = "/var/lib/hermes-deals/lidl-v631-c3-readonly/${{ github.run_id }}-${{ github.run_attempt }}/summary.json"
    assert fixed in source
    assert "ARTIFACT_DIR" not in source
    assert "RUNNER_TEMP" not in source
    for key in (
        "production_database_write",
        "review_write",
        "production_publish",
        "production_deploy",
        "corpus_write",
        "source_replacement",
        "systemd_change",
        "scheduler_change",
        "docker_exec",
        "container_create",
        "package_install",
    ):
        assert key in source
    assert "transaction_rolled_back" in source
    assert "expected_first_apply_delta" in source
    assert "exact_key_counts" in source


def test_installer_is_registration_only_and_does_not_install_apply_capability() -> None:
    source = _text(INSTALLER)
    assert "[[ ${EUID:-$(id -u)} -eq 0 ]]" in source
    assert "audit clone is not exact clean main at installer SHA" in source
    assert "EXPECTED_C3_BLOB='c31df993e94707ffa35b82c4976f4b79e1154add'" in source
    assert "EXPECTED_CORE_BLOB='65273e99a855e3ea26c65329745c5101d4d2d742'" in source
    assert "EXPECTED_PLANNER_BLOB='5c183c4459275c99c7d0f9d66a7a5c425384a5be'" in source
    assert "EXPECTED_DISPATCHER_BLOB='de26a292d727a89f9ad2b701a543897b6f87224b'" in source
    assert "/usr/local/sbin/hermes-deals-lidl-v631-c3-readonly" in source
    assert "/etc/sudoers.d/hermes-deals-lidl-v631-c3-readonly" in source
    assert "PRIVATE_ROOT='/var/lib/hermes-deals/lidl-v631-c3-readonly-private'" in source
    assert "EVIDENCE_ROOT='/var/lib/hermes-deals/lidl-v631-c3-readonly'" in source
    assert "install -d -o root -g root -m 0700 \"$PRIVATE_ROOT\"" in source
    assert "install -d -o root -g root -m 0755 \"$EVIDENCE_ROOT\"" in source
    assert "RUNNER_HAS_DOCKER_GROUP=false" in source
    assert "systemctl is-active" in source
    assert "systemctl enable" not in source
    assert "systemctl restart" not in source
    assert "apply_lidl_v631" not in source
    assert "production_database_write=true" not in source.casefold()


def test_workflow_never_invokes_installer() -> None:
    source = _text(WORKFLOW)
    assert "install-lidl-v631-c3-readonly-dispatcher.sh" in source  # blob identity only
    assert "sudo --non-interactive tools/runner/install" not in source
    assert "sudo --non-interactive ./tools/runner/install" not in source
