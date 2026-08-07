from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github/workflows/aldi-gate-d1-evidence-discovery-rpi5.yml"
INSTALLER = ROOT / "tools/runner/install-aldi-gate-d1-evidence-discovery-dispatcher.py"
DISPATCHER = ROOT / "tools/runner/aldi_gate_d1_evidence_discovery_dispatch.py"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def valid_result() -> dict:
    return {
        "schema_version": 1,
        "mode": "ALDI_GATE_D_RPI5_EVIDENCE_DISCOVERY_V01",
        "decision": "READY_FOR_GATE_D_EXECUTION",
        "state_root": ".",
        "selected": {
            "a21_archive": "a/hermes-deals-aldi-a21-x.tar.gz",
            "a21_projection": "a/reports/a21-adjudicated-projection.jsonl",
            "legacy_manifest": "a/reports/page-image-manifest.json",
            "legacy_page_root": "a/raw/page-images",
            "current_page3": "a/evidence/pages/current/page-003.img",
        },
        "matches": {
            "a21_archives": [{"path": "a/archive.tar.gz"}],
            "a21_projections": [{"path": "a/projection.jsonl"}],
            "legacy_a30_runs": [
                {"manifest_path": "a/reports/page-image-manifest.json", "page_root": "a/raw/page-images"}
            ],
            "authoritative_current_page3": [{"path": "a/evidence/pages/current/page-003.img"}],
        },
        "safety": {
            "discovery_only": True,
            "network_acquisition_authorized": False,
            "parser_execution_authorized": False,
            "source_or_corpus_mutation_authorized": False,
            "candidate_creation_authorized": False,
            "production_database_write_authorized": False,
            "review_write_authorized": False,
            "automatic_approval_authorized": False,
            "automatic_publication_authorized": False,
            "production_deployment_authorized": False,
            "scheduler_or_retry_authorized": False,
            "production_canary_authorized": False,
            "b15m2_v08_action_authorized": False,
            "strict_41_of_41_gate_unchanged": True,
        },
        "review_pack_execution_authorized": False,
        "production_eligible": False,
    }


def test_workflow_is_owner_only_manual_rpi5_execution() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "workflow_dispatch:" in text
    assert 'os.environ["ACTOR"] != "rozkalnsandris"' in text
    assert 'os.environ["ACTOR_ID"] != "277435981"' in text
    assert "runs-on: [self-hosted, Linux, ARM64, hermes-deals-audit]" in text
    assert "hermes-deals-aldi-gate-d1-evidence-discovery-dispatch" in text
    assert "actions/upload-artifact@v6" in text
    assert "Raw evidence exported: **false**" in text
    assert "Gate D review-pack execution: **false / not authorized**" in text


def test_new_execution_files_do_not_enable_strict_shell_mode() -> None:
    for path in (WORKFLOW, INSTALLER, DISPATCHER):
        text = path.read_text(encoding="utf-8")
        assert "set -euo pipefail" not in text
        assert "set -Eeuo pipefail" not in text


def test_installer_freezes_complete_validator_bundle() -> None:
    module = load_module(INSTALLER, "aldi_gate_d1_installer_test")
    required = set(module.BUNDLE_FILES)
    assert "tools/aldi_gate_d_rpi5_evidence_discovery.py" in required
    assert "tools/aldi_weekly_gate_d_visual_review_pack.py" in required
    assert "tools/aldi_weekly_gate_c_shadow_replay_preflight.py" in required
    assert "tools/aldi_weekly_gate_c_shadow_replay_preflight_core.py" in required
    assert "config/aldi-weekly-gate-b-replay-plan-31105044968.json" in required
    assert len([path for path in required if path.endswith(".b64")]) == 8
    assert len(required) == 13


def test_installer_does_not_mutate_audit_git_repository() -> None:
    text = INSTALLER.read_text(encoding="utf-8")
    for command in ("checkout", "switch", "reset", "stash", "clean", "pull", "fetch", "merge", "rebase"):
        assert f'"{command}"' in text
    assert "GIT_OPTIONAL_LOCKS=0" in text
    assert 'audit_git("branch", "--show-current")' in text
    assert 'audit_git("rev-parse", "HEAD")' in text
    assert 'audit_git("status", "--porcelain=v1", "-z", "--untracked-files=all")' in text
    assert "audit repo index changed during installation" in text


def test_dispatcher_accepts_only_safe_discovery_result() -> None:
    module = load_module(DISPATCHER, "aldi_gate_d1_dispatch_test")
    module.validate_discovery_result(valid_result())


def test_dispatcher_rejects_production_or_review_pack_authority() -> None:
    module = load_module(DISPATCHER, "aldi_gate_d1_dispatch_authority_test")
    result = valid_result()
    result["production_eligible"] = True
    try:
        module.validate_discovery_result(result)
    except module.DispatchError:
        pass
    else:
        raise AssertionError("production eligibility must fail closed")

    result = valid_result()
    result["review_pack_execution_authorized"] = True
    try:
        module.validate_discovery_result(result)
    except module.DispatchError:
        pass
    else:
        raise AssertionError("review-pack execution authority must fail closed")


def test_dispatcher_rejects_absolute_or_parent_paths() -> None:
    module = load_module(DISPATCHER, "aldi_gate_d1_dispatch_path_test")
    for unsafe in ("/home/andris/secret", "../escape", "a/../../escape"):
        result = valid_result()
        result["selected"]["a21_archive"] = unsafe
        try:
            module.validate_discovery_result(result)
        except module.DispatchError:
            pass
        else:
            raise AssertionError(f"unsafe path accepted: {unsafe}")


def test_dispatcher_exports_no_raw_evidence_contract() -> None:
    text = DISPATCHER.read_text(encoding="utf-8")
    assert 'for source_name in ("discovery-result.json", "discovery-exit-code.txt")' in text
    assert '"raw_evidence_exported": False' in text
    assert '"production_apply_authorized": False' in text
    assert '"review_pack_execution_authorized": False' in text
    assert "page-003.img" not in text
