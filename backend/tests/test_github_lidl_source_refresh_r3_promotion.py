from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-lidl-source-refresh-r3-promotion.yml"
DISPATCHER = ROOT / "tools" / "runner" / "lidl-r3-promotion-dispatcher.sh"
INSTALLER = ROOT / "tools" / "runner" / "install-lidl-r3-promotion-dispatcher.sh"
FINALIZER = ROOT / "tools" / "runner" / "run-lidl-r3-promotion-owner-finalizer.sh"


def test_r3_promotion_workflow_has_exact_owner_and_authorization_gate() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "github.event.issue.number == 361" in text
    assert "github.actor == 'rozkalnsandris'" in text
    assert 'EXPECTED_OWNER_ID: "277435981"' in text
    assert "sender.get('id')!=int(os.environ['EXPECTED_OWNER_ID'])" in text
    assert "auth_id!=5227260615" in text
    assert "8aaf1f96a119e51c980a45da80031d5abd2db65d4cdc3516bd5368fd0537c7f9" in text
    assert "Authorized scope: create-once promotion" in text
    assert "Not authorized: profile promotion" in text
    assert "pull_request_target" not in text
    assert "repository_dispatch" not in text


def test_r3_promotion_self_hosted_job_never_checks_out_repo_code() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    promote = text.split("  promote:\n", 1)[1].split("\n  report:\n", 1)[0]
    assert "self-hosted" in promote
    assert "hermes-deals-audit" in promote
    assert "actions/checkout" not in promote
    assert "git clone" not in promote
    assert "git checkout" not in promote
    assert "sudo --non-interactive /usr/local/sbin/hermes-deals-lidl-r3-promotion-dispatch" in promote
    assert "actions/upload-artifact@043fb46d1a93c77aae656e7c1c64a875d1fc6a0a" in promote
    assert "actions/upload-artifact@v" not in promote


def test_r3_promotion_workflow_pins_exact_artifacts_and_forbids_other_scopes() -> None:
    text = WORKFLOW.read_text(encoding="utf-8")
    assert "9021545332" in text
    assert "d4f9be1a19592a45739e4cc6a2827833682460e1c41bdd6496e0375077ef33c4" in text
    assert "9024741383" in text
    assert "c1432c05d3975094d2e56ae70fc216c8e8def4199ac312c92b2ff50afc9032dc" in text
    assert "profile_promotion':False" in text
    assert "database_write':False" in text
    assert "review_write':False" in text
    assert "auto_publish':False" in text
    assert "production_deploy':False" in text
    assert "automatic_retry':False" in text


def test_r3_root_dispatcher_has_fresh_semantic_preflight_and_exact_targets() -> None:
    text = DISPATCHER.read_text(encoding="utf-8")
    assert "lidl-source-refresh-audit.py" in text
    assert "3ff8e244b463fb62ef632f8a8cf3be78012a7e72f6b36606a519590b7b634222" in text
    assert "FRESH_SEMANTIC_PREFLIGHT=PASS" in text
    assert "e6ebe5669551a2d455e7b2c036746e08e3bdd20e8e0562fab6972ab97e2a88e8" in text
    assert "12ebbb79bb7bfd46e603e766d357549bf4fb381e6afe4dfdcfeaa1844d6ac6dd" in text
    assert "scan-v631-7191e910f07b" in text
    assert "review-profile must be absent" in text
    assert "CORPUS_OUTSIDE_R3_TARGETS_UNCHANGED=true" in text
    assert "PRODUCTION_DATABASE_WRITE=false" in text
    assert "REVIEW_WRITE=false" in text
    assert "PRODUCTION_PUBLISH=false" in text
    assert "PRODUCTION_DEPLOY=false" in text
    assert "AUTOMATIC_RETRY=false" in text


def test_r3_installer_and_finalizer_only_bootstrap_capability() -> None:
    installer = INSTALLER.read_text(encoding="utf-8")
    finalizer = FINALIZER.read_text(encoding="utf-8")
    assert "PROMOTION_EXECUTED=false" in installer
    assert "CORPUS_WRITE=false" in installer
    assert "github-runner ALL=(root) NOPASSWD: /usr/local/sbin/hermes-deals-lidl-r3-promotion-dispatch *" in installer
    assert "RUNNER_HAS_DOCKER_GROUP=false" in installer
    assert "PROMOTION_EXECUTED=false" in finalizer
    assert "bootstrap executed R3 scan promotion" in finalizer
    assert "bootstrap executed R3 authority promotion" in finalizer
    assert "NEXT_GITHUB_COMMAND=/hermes-lidl-source-refresh-r3-promote" in finalizer
    assert "PRIMARY_INVARIANCE=true" in finalizer
    assert "IMMUTABLE_SOURCE_INVARIANCE=true" in finalizer
