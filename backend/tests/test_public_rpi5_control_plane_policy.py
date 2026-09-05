from __future__ import annotations

import json
from pathlib import Path
import re


ROOT = Path(__file__).resolve().parents[2]
POLICY_PATH = ROOT / "policy" / "public-rpi5-control-plane-v1.json"
WORKFLOWS_DIR = ROOT / ".github" / "workflows"


def _has_self_hosted_runner(text: str) -> bool:
    lines = text.splitlines()
    for index, line in enumerate(lines):
        if re.search(r"\bruns-on:\s*\[[^\]]*\bself-hosted\b", line):
            return True
        match = re.match(r"^(\s*)runs-on:\s*$", line)
        if not match:
            continue
        indent = len(match.group(1))
        for child in lines[index + 1 :]:
            if not child.strip() or child.lstrip().startswith("#"):
                continue
            child_indent = len(child) - len(child.lstrip())
            if child_indent <= indent:
                break
            if re.fullmatch(r"\s*-\s*self-hosted\s*(?:#.*)?", child):
                return True
    return False


def _load_policy() -> dict[str, object]:
    return json.loads(POLICY_PATH.read_text(encoding="utf-8"))


def test_public_rpi5_inventory_covers_every_self_hosted_workflow() -> None:
    policy = _load_policy()
    workflows = policy["workflows"]
    assert isinstance(workflows, list)

    declared = {str(row["path"]) for row in workflows}
    assert len(declared) == len(workflows) == 52

    all_workflows = sorted((*WORKFLOWS_DIR.glob("*.yml"), *WORKFLOWS_DIR.glob("*.yaml")))
    actual = {
        str(path.relative_to(ROOT))
        for path in all_workflows
        if _has_self_hosted_runner(path.read_text(encoding="utf-8"))
    }

    assert len(all_workflows) == policy["inventory_counts"]["workflow_files"] == 80
    assert len(actual) == policy["inventory_counts"]["self_hosted_workflows"] == 52
    assert actual == declared


def test_public_rpi5_inventory_uses_only_declared_capabilities() -> None:
    policy = _load_policy()
    allowed = set(policy["capability_values"])
    rows = policy["workflows"]
    assert allowed == {
        "production_release",
        "read_only_retailer_audit",
        "diagnostic",
        "owner_finalizer_bootstrap",
        "scheduled_unattended",
    }
    assert {row["capability"] for row in rows} <= allowed
    assert all(str(row["path"]).startswith(".github/workflows/") for row in rows)


def test_origin_path_canary_keeps_narrow_current_runner_contract() -> None:
    policy = _load_policy()
    canary = policy["canary"]
    workflow_path = ROOT / str(canary["workflow"])
    text = workflow_path.read_text(encoding="utf-8")

    assert canary["workflow"] == ".github/workflows/origin-path-rpi5-audit.yml"
    assert canary["runner_label"] == "hermes-deals-audit"
    assert canary["fixed_dispatcher"] == "/usr/local/sbin/hermes-deals-origin-path-audit-dispatch"
    assert canary["replacement_model"] == "rpi5_pull_read_only"
    assert canary["requires_owner_authorized_merged_sha"] is True
    assert canary["rpi5_checkout_allowed"] is False
    assert canary["production_database_write_allowed"] is False
    assert canary["production_deploy_allowed"] is False
    assert canary["restart_or_configuration_mutation_allowed"] is False

    assert "- hermes-deals-audit" in text
    assert "sudo --non-interactive /usr/local/sbin/hermes-deals-origin-path-audit-dispatch" in text
    assert "uses: actions/checkout@" not in text


def test_public_rpi5_migration_invariants_fail_closed() -> None:
    policy = _load_policy()
    invariants = policy["migration_invariants"]

    assert invariants == {
        "direct_pull_request_to_self_hosted_allowed": False,
        "untrusted_head_checkout_on_rpi5_allowed": False,
        "generic_shell_operation_allowed": False,
        "single_universal_privileged_agent_allowed": False,
        "runner_deregistration_requires_proven_replacement": True,
        "host_systemd_sudoers_or_runner_mutation_requires_separate_owner_live_authorization": True,
    }
