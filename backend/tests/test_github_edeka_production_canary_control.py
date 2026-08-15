from __future__ import annotations

import base64
import importlib.util
import json
from pathlib import Path
import sys
from urllib.parse import parse_qs, urlparse

import pytest

ROOT = Path(__file__).resolve().parents[2]
SCRIPT = ROOT / "tools" / "github_edeka_production_canary_control.py"
WORKFLOW = ROOT / ".github" / "workflows" / "hermes-edeka-production-canary-control.yml"
PLAN_PATH = ROOT / "config" / "edeka-production-canary-v01.json"
MAIN_SHA = "b" * 40
CI_RUN_ID = 31888882978


def load_module():
    spec = importlib.util.spec_from_file_location(
        "github_edeka_production_canary_control", SCRIPT
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules["github_edeka_production_canary_control"] = module
    spec.loader.exec_module(module)
    return module


def event(body: str) -> dict:
    return {
        "sender": {"login": "rozkalnsandris", "id": 277435981},
        "issue": {"number": 26, "pull_request": None},
        "comment": {
            "id": 123456789,
            "author_association": "OWNER",
            "body": body,
        },
    }


def encoded_plan(payload: dict | None = None) -> str:
    if payload is None:
        raw = PLAN_PATH.read_bytes()
    else:
        raw = (json.dumps(payload, sort_keys=True) + "\n").encode()
    encoded = base64.b64encode(raw).decode()
    return "\n".join(encoded[i : i + 76] for i in range(0, len(encoded), 76))


def fake_get_factory(*, main_sha: str = MAIN_SHA, ci_success: bool = True, plan: dict | None = None):
    def fake_get(url: str, _token: str):
        parsed = urlparse(url)
        if parsed.path.endswith("/branches/main"):
            return {"commit": {"sha": main_sha}}
        if "/contents/" in parsed.path:
            repo_path = parsed.path.split("/contents/", 1)[1]
            assert parse_qs(parsed.query)["ref"] == [MAIN_SHA]
            if repo_path == "config/edeka-production-canary-v01.json":
                return {
                    "type": "file",
                    "sha": "c" * 40,
                    "encoding": "base64",
                    "content": encoded_plan(plan),
                }
            return {"type": "file", "sha": "d" * 40}
        if parsed.path.endswith("/actions/runs"):
            query = parse_qs(parsed.query)
            assert query["head_sha"] == [MAIN_SHA]
            assert query["event"] == ["push"]
            return {
                "workflow_runs": [
                    {
                        "id": CI_RUN_ID,
                        "name": "Hermes Deals CI checks",
                        "path": ".github/workflows/ci.yml",
                        "head_sha": MAIN_SHA,
                        "event": "push",
                        "status": "completed" if ci_success else "in_progress",
                        "conclusion": "success" if ci_success else None,
                    }
                ]
            }
        raise AssertionError(url)

    return fake_get


@pytest.mark.parametrize("operation", ["verify", "apply", "replay", "rollback"])
def test_exact_owner_command_authorizes_current_main_with_green_ci(operation: str):
    module = load_module()
    values = module.authorize_event(
        event(f"/hermes-edeka canary {operation} sha={MAIN_SHA}"),
        repository=module.EXPECTED_REPOSITORY,
        token="token",
        get_json=fake_get_factory(),
    )
    assert values == {
        "operation": operation,
        "sha": MAIN_SHA,
        "issue_number": "26",
        "comment_id": "123456789",
        "trigger_actor": "rozkalnsandris",
        "ci_run_id": str(CI_RUN_ID),
    }


@pytest.mark.parametrize(
    "body",
    [
        f"/hermes-edeka canary Apply sha={MAIN_SHA}",
        f"/hermes-edeka canary apply sha={'B' * 40}",
        f"/hermes-edeka canary apply sha={'b' * 39}",
        f"/hermes-edeka canary apply sha={MAIN_SHA} extra",
        "/hermes-edeka canary apply sha=$(id)",
        f"/hermes-edeka canary deploy sha={MAIN_SHA}",
    ],
)
def test_command_parser_fails_closed(body: str):
    module = load_module()
    with pytest.raises(module.BridgeAuthorizationError):
        module.parse_comment(body)


def test_authorizer_rejects_wrong_owner_issue_association_or_pull_request():
    module = load_module()
    body = f"/hermes-edeka canary verify sha={MAIN_SHA}"

    bad = event(body)
    bad["sender"]["id"] = 1
    with pytest.raises(module.BridgeAuthorizationError, match="allowlisted owner"):
        module.authorize_event(
            bad,
            repository=module.EXPECTED_REPOSITORY,
            token="x",
            get_json=fake_get_factory(),
        )

    bad = event(body)
    bad["issue"]["number"] = 27
    with pytest.raises(module.BridgeAuthorizationError, match="issue #26"):
        module.authorize_event(
            bad,
            repository=module.EXPECTED_REPOSITORY,
            token="x",
            get_json=fake_get_factory(),
        )

    bad = event(body)
    bad["comment"]["author_association"] = "MEMBER"
    with pytest.raises(module.BridgeAuthorizationError, match="OWNER"):
        module.authorize_event(
            bad,
            repository=module.EXPECTED_REPOSITORY,
            token="x",
            get_json=fake_get_factory(),
        )

    bad = event(body)
    bad["issue"]["pull_request"] = {"url": "https://example.invalid"}
    with pytest.raises(module.BridgeAuthorizationError, match="only on issues"):
        module.authorize_event(
            bad,
            repository=module.EXPECTED_REPOSITORY,
            token="x",
            get_json=fake_get_factory(),
        )


def test_authorizer_requires_exact_current_main_and_green_push_ci():
    module = load_module()
    body = f"/hermes-edeka canary apply sha={MAIN_SHA}"

    with pytest.raises(module.BridgeAuthorizationError, match="current main"):
        module.authorize_event(
            event(body),
            repository=module.EXPECTED_REPOSITORY,
            token="x",
            get_json=fake_get_factory(main_sha="a" * 40),
        )

    with pytest.raises(module.BridgeAuthorizationError, match="CI"):
        module.authorize_event(
            event(body),
            repository=module.EXPECTED_REPOSITORY,
            token="x",
            get_json=fake_get_factory(ci_success=False),
        )


def test_authorizer_revalidates_exact_preparation_only_plan_contract():
    module = load_module()
    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    plan["production_apply_authorized"] = True
    with pytest.raises(module.BridgeAuthorizationError, match="must not self-authorize"):
        module.authorize_event(
            event(f"/hermes-edeka canary apply sha={MAIN_SHA}"),
            repository=module.EXPECTED_REPOSITORY,
            token="x",
            get_json=fake_get_factory(plan=plan),
        )

    plan = json.loads(PLAN_PATH.read_text(encoding="utf-8"))
    plan["expected_first_apply_delta"]["offer_candidates"] = 4
    with pytest.raises(module.BridgeAuthorizationError, match="first-apply contract drift"):
        module.authorize_event(
            event(f"/hermes-edeka canary apply sha={MAIN_SHA}"),
            repository=module.EXPECTED_REPOSITORY,
            token="x",
            get_json=fake_get_factory(plan=plan),
        )


def test_github_output_rejects_newline_injection(tmp_path: Path):
    module = load_module()
    values = module.authorize_event(
        event(f"/hermes-edeka canary verify sha={MAIN_SHA}"),
        repository=module.EXPECTED_REPOSITORY,
        token="x",
        get_json=fake_get_factory(),
    )
    values["trigger_actor"] = "owner\ninjected=true"
    with pytest.raises(module.BridgeAuthorizationError, match="newline"):
        module.write_github_outputs(tmp_path / "out", values)


def test_workflow_keeps_untrusted_issue_input_off_self_hosted_runner():
    source = WORKFLOW.read_text(encoding="utf-8")
    assert "issue_comment:" in source
    assert "github.event.issue.number == 26" in source
    assert "github.event.sender.id == 277435981" in source
    assert "github.event.comment.author_association == 'OWNER'" in source
    assert "startsWith(github.event.comment.body, '/hermes-edeka canary ')" in source
    assert "permissions: {}" in source
    assert "actions/checkout@11bd71901bbe5b1630ceea73d27597364c9af683 # v4.2.2" in source
    assert "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f # v6.0.0" in source
    assert "persist-credentials: false" in source

    self_hosted = source.split("  control:\n", 1)[1].split("  report:\n", 1)[0]
    assert "hermes-deals-audit" in self_hosted
    assert "permissions: {}" in self_hosted
    assert "actions/checkout" not in self_hosted
    assert "github.event.comment.body" not in self_hosted
    assert "GH_TOKEN" not in self_hosted
    assert "DATABASE_URL" not in self_hosted
    assert "/bin/bash -c" not in self_hosted
    assert "systemctl" not in self_hosted
    assert (
        "sudo --non-interactive /usr/local/sbin/hermes-deals-edeka-production-canary-control"
        in self_hosted
    )
    assert '"$OPERATION" "$TARGET_SHA" "$export_dir"' in self_hosted


def test_bridge_exposes_no_direct_host_or_database_mutation_code():
    helper = SCRIPT.read_text(encoding="utf-8")
    assert "subprocess" not in helper
    assert "psycopg" not in helper
    assert "sqlalchemy" not in helper
    assert "DATABASE_URL" not in helper
    assert "sudo" not in helper


def test_is_command_for_workflow_is_narrow():
    module = load_module()
    good = event(f"/hermes-edeka canary verify sha={MAIN_SHA}")
    assert module.is_command_for_workflow(good) is True
    bad = event(f"/hermes-edeka canary verify sha={MAIN_SHA}")
    bad["sender"]["login"] = "someone-else"
    assert module.is_command_for_workflow(bad) is False
