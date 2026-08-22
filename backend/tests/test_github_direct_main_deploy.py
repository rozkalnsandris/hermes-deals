from __future__ import annotations

import json
from pathlib import Path
import sys
import unittest


ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools.github_direct_main_deploy import (  # noqa: E402
    AuthorizedDeploy,
    DirectDeployAuthorizationError,
    EXPECTED_WORKFLOW_REF,
    authorize_event,
    dispatch_deploy,
    parse_comment,
)


SHA = "a" * 40


def _event(*, sha: str = SHA, login: str = "rozkalnsandris", owner_id: int = 277435981, issue: int = 553):
    return {
        "sender": {"login": login, "id": owner_id},
        "issue": {"number": issue, "pull_request": None},
        "comment": {
            "id": 12345,
            "body": f"/hermes-deploy current-main sha={sha}",
        },
    }


def _get_json(url: str, token: str):
    assert token == "token"
    if url.endswith("/branches/main"):
        return {"commit": {"sha": SHA}}
    if "/actions/workflows/ci.yml/runs?" in url:
        return {
            "workflow_runs": [
                {
                    "id": 99,
                    "event": "push",
                    "head_branch": "main",
                    "head_sha": SHA,
                    "status": "completed",
                    "conclusion": "success",
                }
            ]
        }
    raise AssertionError(url)


class _Response:
    def __init__(self, status: int, body: bytes = b"") -> None:
        self.status = status
        self._body = body

    def read(self) -> bytes:
        return self._body

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False


class GitHubDirectMainDeployTest(unittest.TestCase):
    def test_exact_command_is_accepted(self) -> None:
        self.assertEqual(parse_comment(f"/hermes-deploy current-main sha={SHA}"), SHA)

    def test_command_is_full_match_and_lowercase_sha_only(self) -> None:
        bad = [
            f"/hermes-deploy current-main sha={SHA} extra",
            f"prefix /hermes-deploy current-main sha={SHA}",
            f"/hermes-deploy current-main sha={SHA.upper()}",
            "/hermes-deploy current-main sha=main",
        ]
        for value in bad:
            with self.subTest(value=value), self.assertRaises(DirectDeployAuthorizationError):
                parse_comment(value)

    def test_authorizes_exact_owner_issue_main_and_successful_push_ci(self) -> None:
        authorized = authorize_event(
            _event(),
            repository="rozkalnsandris/hermes-deals",
            workflow_ref=EXPECTED_WORKFLOW_REF,
            token="token",
            get_json=_get_json,
        )
        self.assertEqual(authorized.sha, SHA)
        self.assertEqual(authorized.issue_number, 553)
        self.assertEqual(authorized.comment_id, 12345)
        self.assertEqual(authorized.ci_run_id, 99)

    def test_rejects_wrong_owner_issue_workflow_or_stale_sha(self) -> None:
        cases = [
            (_event(login="someone-else"), EXPECTED_WORKFLOW_REF),
            (_event(owner_id=1), EXPECTED_WORKFLOW_REF),
            (_event(issue=554), EXPECTED_WORKFLOW_REF),
            (_event(sha="b" * 40), EXPECTED_WORKFLOW_REF),
            (_event(), "rozkalnsandris/hermes-deals/.github/workflows/hermes-direct-main-deploy.yml@refs/pull/1/merge"),
        ]
        for event, workflow_ref in cases:
            with self.subTest(event=event, workflow_ref=workflow_ref), self.assertRaises(DirectDeployAuthorizationError):
                authorize_event(
                    event,
                    repository="rozkalnsandris/hermes-deals",
                    workflow_ref=workflow_ref,
                    token="token",
                    get_json=_get_json,
                )

    def test_rejects_when_exact_main_has_no_successful_push_ci(self) -> None:
        def get_json(url: str, token: str):
            if url.endswith("/branches/main"):
                return {"commit": {"sha": SHA}}
            return {
                "workflow_runs": [
                    {
                        "id": 98,
                        "event": "pull_request",
                        "head_branch": "main",
                        "head_sha": SHA,
                        "status": "completed",
                        "conclusion": "success",
                    },
                    {
                        "id": 97,
                        "event": "push",
                        "head_branch": "main",
                        "head_sha": SHA,
                        "status": "completed",
                        "conclusion": "failure",
                    },
                ]
            }

        with self.assertRaisesRegex(DirectDeployAuthorizationError, "successful completed push CI"):
            authorize_event(
                _event(),
                repository="rozkalnsandris/hermes-deals",
                workflow_ref=EXPECTED_WORKFLOW_REF,
                token="token",
                get_json=get_json,
            )

    def test_legacy_dispatch_helper_remains_fixed_to_manual_main_deploy_workflow(self) -> None:
        captured = {}

        def opener(request, timeout=0):
            captured["url"] = request.full_url
            captured["method"] = request.method
            captured["body"] = json.loads(request.data.decode("utf-8"))
            captured["timeout"] = timeout
            return _Response(
                200,
                json.dumps(
                    {
                        "workflow_run_id": 123456,
                        "html_url": "https://github.com/rozkalnsandris/hermes-deals/actions/runs/123456",
                    }
                ).encode("utf-8"),
            )

        result = dispatch_deploy(
            AuthorizedDeploy(SHA, 553, 12345, 99),
            repository="rozkalnsandris/hermes-deals",
            token="token",
            opener=opener,
        )
        self.assertEqual(
            captured["url"],
            "https://api.github.com/repos/rozkalnsandris/hermes-deals/actions/workflows/deploy-main.yml/dispatches",
        )
        self.assertEqual(captured["method"], "POST")
        self.assertEqual(
            captured["body"],
            {
                "ref": "main",
                "inputs": {
                    "target_sha": SHA,
                    "confirmation": f"DEPLOY {SHA}",
                },
            },
        )
        self.assertEqual(result["workflow_run_id"], 123456)

    def test_workflow_authorizes_on_github_hosted_then_uses_guarded_release_runner(self) -> None:
        workflow = (ROOT / ".github/workflows/hermes-direct-main-deploy.yml").read_text(encoding="utf-8")
        self.assertIn("issue_comment:", workflow)
        self.assertIn("github.event.issue.number == 553", workflow)
        self.assertIn("runs-on: ubuntu-latest", workflow)
        self.assertIn("actions: read", workflow)
        self.assertNotIn("actions: write", workflow)
        self.assertIn("contents: read", workflow)
        self.assertIn(
            "actions/checkout@08c6903cd8c0fde910a37f88322edcfb5dd907a8 # v5.0.0",
            workflow,
        )
        self.assertIn("persist-credentials: false", workflow)
        self.assertIn("ref: main", workflow)
        self.assertIn("from tools.github_direct_main_deploy import authorize_event", workflow)
        self.assertNotIn("python3 tools/github_direct_main_deploy.py", workflow)
        self.assertNotIn("github.event.comment.body }}", workflow)

        deploy = workflow.split("\n  deploy:\n", 1)[1].split("\n  report:\n", 1)[0]
        self.assertIn("- self-hosted", deploy)
        self.assertIn("- hermes-deals-release", deploy)
        self.assertIn(
            "sudo --non-interactive /usr/local/sbin/hermes-deals-deploy-main",
            deploy,
        )
        self.assertNotIn("GH_TOKEN:", deploy)
        self.assertNotIn("github.event.comment", deploy)
        self.assertNotIn("docker ", deploy)
        self.assertIn("weekly-retailer-trust-smoke.json", deploy)
        for state in (
            "offers",
            "no_offers",
            "not_published_yet",
            "source_unavailable",
            "stale_data",
            "not_supported",
        ):
            self.assertIn(f'"{state}"', deploy)
        for retailer in ("lidl", "aldi_nord", "netto", "edeka"):
            self.assertIn(f'"{retailer}"', deploy)
        self.assertIn("https://deals.rozkalns.net/api/health", deploy)
        self.assertIn("https://deals.rozkalns.net/ui", deploy)
        self.assertIn(
            "actions/upload-artifact@b7c566a772e6b6bfb58ed0dc250532a479d7789f # v6.0.0",
            deploy,
        )

        report = workflow.split("\n  report:\n", 1)[1]
        self.assertIn("issues: write", report)
        self.assertIn("database writes/migrations authorized: **false**", report)
        self.assertIn("/issues/553/comments", report)


if __name__ == "__main__":
    unittest.main()
