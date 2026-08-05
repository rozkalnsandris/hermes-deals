from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
CLOSURE_PATH = (
    REPO_ROOT
    / "tools"
    / "lidl_parser_provenance"
    / "verify_issue_22_closure.py"
)


def _load_closure():
    spec = importlib.util.spec_from_file_location(
        "hermes_lidl_issue_22_closure",
        CLOSURE_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Lidl issue #22 closure verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LidlIssue22ClosureTests(unittest.TestCase):
    def test_current_main_satisfies_complete_closure_contract(self) -> None:
        closure = _load_closure()
        result = closure.verify_issue_22_closure(REPO_ROOT)

        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["issue"], 22)
        self.assertEqual(result["base_graph_result"], "PASS")
        self.assertEqual(result["canonical_runtime_node"], "v631-runtime-loader")
        self.assertEqual(
            result["canonical_parser_version"],
            "lidl-pdf-v08c-r61-shadow-v631",
        )
        self.assertGreaterEqual(result["node_count"], 19)
        self.assertGreaterEqual(result["edge_count"], 15)
        self.assertEqual(result["corpus_binding_count"], 2)
        self.assertEqual(result["r6_parser_status"], "quarantined_by_absence")
        self.assertGreaterEqual(
            result["import_contract"]["required_route_count"],
            6,
        )
        self.assertTrue(result["lidl_python_inventory"]["backend_modules"])
        self.assertTrue(result["lidl_python_inventory"]["tool_entrypoints"])
        self.assertTrue(result["lidl_python_inventory"]["tests"])
        self.assertIn(
            "backend/app/lidl_weekly_review_bridge.py",
            result["import_contract"]["support_importers"][
                "app.lidl_weekly_completeness_contract"
            ],
        )
        self.assertFalse(result["production_deploy_authorized"])
        self.assertFalse(result["database_write_authorized"])
        self.assertFalse(result["review_write_authorized"])
        self.assertFalse(result["parser_behavior_changed"])

    def test_closure_report_is_deterministic(self) -> None:
        closure = _load_closure()
        first = closure.verify_issue_22_closure(REPO_ROOT)
        second = closure.verify_issue_22_closure(REPO_ROOT)
        self.assertEqual(first, second)

    def test_undeclared_non_test_importer_fails_closed(self) -> None:
        closure = _load_closure()
        graph = closure.load_graph(REPO_ROOT)
        importers = closure.collect_direct_importers(REPO_ROOT)
        importers["lidl_parser_provenance.lidl_v631_runtime"] = [
            *importers["lidl_parser_provenance.lidl_v631_runtime"],
            "tools/undeclared_lidl_runtime.py",
        ]

        with self.assertRaisesRegex(
            closure.LidlIssue22ClosureError,
            "non-test Lidl runtime importer is absent from graph",
        ):
            closure.validate_direct_import_contract(graph, importers)

    def test_missing_declared_runtime_route_fails_closed(self) -> None:
        closure = _load_closure()
        graph = closure.load_graph(REPO_ROOT)
        graph["edges"] = [
            edge
            for edge in graph["edges"]
            if not (
                edge.get("from") == "weekly-one-shot"
                and edge.get("to") == "v631-runtime-loader"
            )
        ]
        importers = closure.collect_direct_importers(REPO_ROOT)

        with self.assertRaisesRegex(
            closure.LidlIssue22ClosureError,
            "required Lidl runtime routes are absent from graph",
        ):
            closure.validate_direct_import_contract(graph, importers)


if __name__ == "__main__":
    unittest.main()
