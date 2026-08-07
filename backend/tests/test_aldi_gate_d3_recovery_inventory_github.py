from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "aldi-gate-d3-recovery-inventory-rpi5.yml"
INSTALLER = ROOT / "tools" / "runner" / "install-aldi-gate-d3-recovery-inventory.py"
DISPATCHER = ROOT / "tools" / "runner" / "aldi_gate_d3_recovery_inventory_dispatch.py"
INVENTORY = ROOT / "tools" / "aldi_gate_d3_recovery_inventory.py"
UPLOAD_ARTIFACT_SHA = "b7c566a772e6b6bfb58ed0dc250532a479d7789f"


def test_gate_d3_workflow_is_manual_owner_only_and_sanitized():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert 'os.environ["ACTOR"] != "rozkalnsandris"' in text
    assert 'os.environ["ACTOR_ID"] != "277435981"' in text
    assert "runs-on: [self-hosted, Linux, ARM64, hermes-deals-audit]" in text
    assert "actions/checkout" not in text
    assert "hermes-deals-aldi-gate-d3-recovery-inventory" in text
    assert "Raw page images exported: **false**" in text
    assert "Raw stderr/exception exported: **false**" in text
    assert "Archive extraction: **false / not authorized**" in text
    assert "Production DB/deploy: **false / not authorized**" in text


def test_gate_d3_workflow_uses_job_level_least_privilege_and_pinned_action():
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "permissions: {}" in text
    assert "contents: write" not in text
    assert "pull-requests: read" in text
    assert "pull-requests: write" in text
    assert "issues: write" not in text
    assert text.count("pull-requests: write") == 1
    assert f"uses: actions/upload-artifact@{UPLOAD_ARTIFACT_SHA}" in text
    assert "actions/upload-artifact@v6" not in text
    assert text.count('"X-GitHub-Api-Version": "2022-11-28"') == 2


def test_gate_d3_installer_preserves_exact_sha_audit_boundary():
    text = INSTALLER.read_text(encoding="utf-8")
    assert 'require(audit_git("branch", "--show-current").decode().strip() == "main"' in text
    assert 'require(audit_git("rev-parse", "HEAD").decode().strip() == commit_sha' in text
    assert '"status", "--porcelain=v1", "-z", "--untracked-files=all"' in text
    assert 'require("docker" not in groups' in text
    assert '"archive_extraction_authorized": False' in text
    assert '"production_apply_authorized": False' in text


def test_gate_d3_installer_normalizes_traversal_and_probes_cli_as_audit_user():
    text = INSTALLER.read_text(encoding="utf-8")
    assert 'AUDITS_ROOT = Path("/usr/local/libexec/hermes-deals-audits")' in text
    assert "normalize_root_dir(AUDITS_ROOT)" in text
    assert "normalize_root_dir(INSTALL_ROOT)" in text
    assert "os.chmod(path, 0o755)" in text
    assert '"/usr/bin/test", "-r", str(inventory)' in text
    assert '"/usr/bin/python3", str(inventory), "--help"' in text
    assert "validate_inventory_as_audit_user(inventory)" in text
    assert 'print("INSTALL_ROOT_TRAVERSABLE_BY_AUDIT_USER=true")' in text
    assert 'print("INVENTORY_CLI_PREFLIGHT_PASS=true")' in text


def test_gate_d3_dispatcher_exports_only_sanitized_inventory():
    text = DISPATCHER.read_text(encoding="utf-8")
    assert 'STATE_ROOT = Path("/home/andris/.local/state/hermes-deals/aldi-perfect-shadow")' in text
    assert '"raw_evidence_exported": False' in text
    assert '"raw_exception_exported": False' in text
    assert '"archive_extraction_authorized": False' in text
    assert "shutil.copyfile(result, export / \"diagnostic-result.json\"" in text
    assert "extractall" not in text
    assert "tarfile" not in text


def test_gate_d3_dispatcher_has_bounded_sanitized_failure_classification():
    text = DISPATCHER.read_text(encoding="utf-8")
    assert "ALLOWED_FAILURE_STAGES" in text
    assert 'failure_stage = "inventory_cli_preflight"' in text
    assert 'failure_stage = "inventory_execution"' in text
    assert '"failure_stage": failure_stage' in text
    assert '"reason_code": failure_reason' in text
    assert '"raw_stderr_exported": False' in text
    assert "completed.stderr.decode" not in text
    assert "cli.stderr.decode" not in text


def test_gate_d3_inventory_is_resource_bounded_and_streaming():
    text = INVENTORY.read_text(encoding="utf-8")
    assert "MAX_ARCHIVE_MEMBER_COUNT" in text
    assert "MAX_ARCHIVE_TOTAL_REGULAR_BYTES" in text
    assert "MAX_PAGE_IMAGE_BYTES" in text
    assert "MAX_PAGE_HASH_BYTES_PER_ARCHIVE" in text
    assert "stream_image_handle" in text
    assert "extracted.read()" not in text
    assert "path.read_bytes()" not in text
    assert "extractall" not in text
