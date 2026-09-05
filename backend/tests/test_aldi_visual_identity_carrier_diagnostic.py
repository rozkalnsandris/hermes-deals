from __future__ import annotations

import importlib
from pathlib import Path
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
TOOLS = ROOT / "tools"
if str(TOOLS) not in sys.path:
    sys.path.insert(0, str(TOOLS))

diagnostic = importlib.import_module("aldi_visual_identity_carrier_diagnostic")


class AldiVisualIdentityCarrierDiagnosticTest(unittest.TestCase):
    def test_decision_requires_dom_carrier_for_every_unbound_offer(self):
        self.assertEqual(
            diagnostic._decision(
                [
                    {"producer_binding_count": 0, "dom_identity_carrier_count": 2},
                    {"producer_binding_count": 2, "dom_identity_carrier_count": 1},
                ]
            ),
            "ALL_UNBOUND_HAVE_DOM_IDENTITY_CARRIERS",
        )
        self.assertEqual(
            diagnostic._decision(
                [
                    {"producer_binding_count": 0, "dom_identity_carrier_count": 1},
                    {"producer_binding_count": 0, "dom_identity_carrier_count": 0},
                ]
            ),
            "PARTIAL_DOM_IDENTITY_CARRIERS",
        )
        self.assertEqual(
            diagnostic._decision(
                [{"producer_binding_count": 0, "dom_identity_carrier_count": 0}]
            ),
            "NO_DOM_IDENTITY_CARRIERS",
        )
        self.assertEqual(
            diagnostic._decision(
                [{"producer_binding_count": 1, "dom_identity_carrier_count": 0}]
            ),
            "NO_UNBOUND_OFFERS",
        )

    def test_sanitization_exports_structure_not_raw_carrier_values(self):
        raw = {
            "location_host": "www.aldi-nord.de",
            "document_width": 1440,
            "document_height": 10000,
            "rows": [
                {
                    "object_id": "1000083",
                    "producer_binding_count": 0,
                    "exact_attribute_count": 0,
                    "embedded_attribute_count": 1,
                    "exact_url_count": 0,
                    "embedded_url_count": 1,
                    "direct_text_count": 0,
                    "script_match_count": 1,
                    "dom_identity_carrier_count": 1,
                    "samples": [
                        {
                            "match_kind": "url_path_segment_embedded",
                            "tag_name": "a",
                            "attribute_name": "href",
                            "visible": True,
                            "container_tag": "article",
                            "container_role": "",
                            "container_testid": "product-card",
                            "value_length": 64,
                            "left_context": "-offer-",
                            "right_context": ".html",
                        }
                    ],
                    "script_samples": [
                        {
                            "script_id": "__NEXT_DATA__",
                            "script_type": "application/json",
                            "text_length": 1000,
                        }
                    ],
                }
            ],
        }
        result = diagnostic._sanitize_inventory(raw)
        sample = result["rows"][0]["samples"][0]
        self.assertEqual(sample["match_kind"], "url_path_segment_embedded")
        self.assertEqual(sample["attribute_name"], "href")
        self.assertEqual(len(sample["carrier_fingerprint_sha256"]), 64)
        self.assertNotIn("href", sample)
        self.assertNotIn("raw_html", sample)
        self.assertNotIn("text", sample)

    def test_inventory_source_is_bounded_and_diagnostic_only(self):
        source = (TOOLS / "aldi_visual_identity_carrier_diagnostic.py").read_text(
            encoding="utf-8"
        )
        self.assertIn("MAX_OFFERS = 256", source)
        self.assertIn("MAX_SAMPLES_PER_KIND = 12", source)
        self.assertIn("url_path_segment_embedded", source)
        self.assertIn("url_query_value_embedded", source)
        self.assertIn("direct_text_embedded", source)
        self.assertIn("script_match_count", source)
        self.assertIn('"producer_matching_contract_modified": False', source)
        self.assertNotIn("page.screenshot(", source)
        self.assertNotIn("request.json", source)

    def test_dispatcher_and_installer_keep_owner_context_and_no_mutation_authority(self):
        dispatcher = (
            TOOLS / "runner" / "aldi-visual-identity-carrier-diagnostic-dispatcher.sh"
        ).read_text(encoding="utf-8")
        installer = (
            TOOLS
            / "runner"
            / "install-aldi-visual-identity-carrier-diagnostic-dispatcher.sh"
        ).read_text(encoding="utf-8")

        for source in (dispatcher, installer):
            self.assertIn("runuser -u andris -- env -i", source)
            self.assertIn("GIT_OPTIONAL_LOCKS=0", source)
            self.assertNotIn("safe.directory", source)

        self.assertIn("NETWORK_SOURCE_READ=true", dispatcher)
        self.assertIn("PRODUCTION_DATABASE_WRITE=false", dispatcher)
        self.assertIn("REQUEST_CREATED=false", dispatcher)
        self.assertIn("REQUEST_ACCEPTED=false", dispatcher)
        self.assertIn("PRODUCTION_CANARY=false", dispatcher)
        self.assertNotIn(
            "/var/lib/hermes-deals/aldi-new-baseline-weekly-shadow-v01/requests",
            dispatcher,
        )

    def test_workflow_is_exact_owner_gated_and_self_hosted_job_has_no_permissions(self):
        workflow = (
            ROOT
            / ".github"
            / "workflows"
            / "hermes-aldi-visual-identity-carrier-diagnostic.yml"
        ).read_text(encoding="utf-8")
        self.assertIn("github.event.issue.number == 682", workflow)
        self.assertIn("github.event.comment.user.login == 'rozkalnsandris'", workflow)
        self.assertIn("github.event.comment.user.id == 277435981", workflow)
        self.assertIn("github.event.comment.author_association == 'OWNER'", workflow)
        self.assertIn(
            "github.event.comment.body == '/hermes-aldi-visual-identity-carrier diagnose'",
            workflow,
        )
        self.assertIn(
            "runs-on: [self-hosted, Linux, ARM64, hermes-deals-audit]", workflow
        )
        self.assertIn("permissions: {}", workflow)
        self.assertIn("persist-credentials: false", workflow)
        self.assertNotIn("schedule:", workflow)
        self.assertNotIn("workflow_dispatch:", workflow)
        self.assertIn("producer matching contract mutation: `false`", workflow)


if __name__ == "__main__":
    unittest.main()
