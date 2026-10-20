#!/usr/bin/env python3
"""Source-only GitHub-first / RDC-fallback local policy acceptance."""
import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
UPSTREAM = "4e89b75d7f496dfb43fd9c1eb10a995fad53fdd8"


def select_route(scenario):
    if scenario["error"]:
        return "STOP"
    if scenario["github"]:
        return "GITHUB"
    if scenario["ci"]:
        return "GITHUB_ACTIONS"
    return "RDC_EXCEPTION" if scenario["host"] and scenario["authority"] else "STOP"


class AdoptionPolicyTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.policy = json.loads((ROOT / ".github/github-first-rdc-v1.json").read_text())
        cls.routing = json.loads((ROOT / ".github/start-mode-routing.json").read_text())
        cls.agents = (ROOT / "AGENTS.md").read_text()
        cls.doc = (ROOT / "docs/GITHUB_FIRST_RDC_ADOPTION_V1.md").read_text()

    def test_exact_accepted_shared_revision(self):
        self.assertEqual(self.policy["schema"], "rozkalns.github-first-rdc-fallback.consumer.v1")
        self.assertEqual(self.policy["repository"], "rozkalnsandris/hermes-deals")
        self.assertEqual(self.policy["canonical"]["revision"], UPSTREAM)
        self.assertEqual(len(UPSTREAM), 40)
        self.assertEqual(self.routing["github_first_rdc_fallback"]["shared_revision"], UPSTREAM)

    def test_mandatory_github_priority(self):
        x = self.policy["routing"]
        for key in ("per_step_required", "github_equivalent_required", "github_ci_when_applicable"):
            self.assertIs(x[key], True)
        self.assertIs(x["rdc_convenience_allowed"], False)
        self.assertEqual(x["order"], [
            "GITHUB_CONNECTED_TOOLS", "GITHUB_HOSTED_CI_WHEN_APPLICABLE",
            "MINIMAL_AUTHORIZED_RDC_IF_GITHUB_INCAPABLE", "STOP",
        ])
        local = self.routing["github_first_rdc_fallback"]
        for key in ("mandatory_per_step", "rdc_requires_proven_capability_gap",
                    "github_error_not_an_rdc_fallback", "independent_of_command_mode"):
            self.assertIs(local[key], True)

    def test_minimal_authorized_exception_evidence(self):
        x = self.policy["rdc_exception"]
        for key, value in x.items():
            if key != "evidence_fields":
                self.assertIs(value, True, key)
        self.assertEqual(x["evidence_fields"], [
            "STEP", "REPOSITORY_AND_TARGET", "GITHUB_CAPABILITY_CHECKED",
            "PRECISE_CAPABILITY_GAP", "GITHUB_CI_NOT_EQUIVALENT_REASON",
            "MINIMAL_RDC_OPERATION", "EXISTING_AUTHORIZATION", "GITHUB_RETURN_EVIDENCE",
        ])

    def test_strict_boundaries_and_fail_closed(self):
        for group in ("fail_closed", "hermes_local_stricter"):
            for key, value in self.policy[group].items():
                self.assertIs(value, True, key)
        self.assertEqual(self.routing["default_continuation_mode"], "FAST-LANE v2.2")
        self.assertIn("STRICT", self.agents)
        self.assertIn("Merge never authorizes deployment", self.agents)
        self.assertIn("AUTO-RUN FULL QUEUE", self.agents)
        self.assertIn("No provider LLM API key", self.agents)

    def test_decision_matrix(self):
        cases = self.policy["cases"]
        self.assertEqual(len(cases), 8)
        self.assertEqual(len(set(c["name"] for c in cases)), 8)
        for case in cases:
            with self.subTest(scenario=case["name"]):
                self.assertEqual(select_route(case), case["expected"])

    def test_human_document_and_agents(self):
        for text in (UPSTREAM, "## GitHub-first / RDC fallback v1 (mandatory)",
                     ".github/github-first-rdc-v1.json"):
            self.assertIn(text, self.agents)
        for text in (UPSTREAM, "GitHub -> minimal RDC -> GitHub",
                     "403/429", "AUTO-RUN FULL QUEUE"):
            self.assertIn(text, self.doc)


if __name__ == "__main__":
    unittest.main()
