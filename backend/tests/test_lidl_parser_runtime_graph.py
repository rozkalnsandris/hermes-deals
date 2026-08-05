from __future__ import annotations

import importlib.util
from pathlib import Path
import unittest


REPO_ROOT = Path(__file__).resolve().parents[2]
VERIFIER_PATH = (
    REPO_ROOT
    / "tools"
    / "lidl_parser_provenance"
    / "verify_parser_runtime_graph.py"
)


def _load_verifier():
    spec = importlib.util.spec_from_file_location(
        "hermes_lidl_parser_runtime_graph_verifier",
        VERIFIER_PATH,
    )
    if spec is None or spec.loader is None:
        raise RuntimeError("cannot load Lidl parser runtime graph verifier")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LidlParserRuntimeGraphTests(unittest.TestCase):
    def test_committed_graph_is_complete_and_content_addressed(self) -> None:
        verifier = _load_verifier()
        result = verifier.verify_graph(REPO_ROOT)

        self.assertEqual(result["result"], "PASS")
        self.assertEqual(result["canonical_runtime_node"], "v631-runtime-loader")
        self.assertEqual(
            result["canonical_parser_version"],
            "lidl-pdf-v08c-r61-shadow-v631",
        )
        self.assertGreaterEqual(result["node_count"], 13)
        self.assertGreaterEqual(result["edge_count"], 9)
        self.assertGreaterEqual(result["corpus_binding_count"], 2)
        self.assertFalse(result["production_deploy_authorized"])
        self.assertFalse(result["database_write_authorized"])
        self.assertFalse(result["parser_behavior_changed"])

    def test_historical_parser_paths_remain_absent(self) -> None:
        verifier = _load_verifier()
        graph = verifier.load_graph(REPO_ROOT)
        historical_paths = {
            relative
            for identity in graph["historical_identities"]
            for relative in identity.get("paths", [])
        }
        self.assertTrue(historical_paths)
        for relative in historical_paths:
            self.assertFalse((REPO_ROOT / relative).exists(), relative)


if __name__ == "__main__":
    unittest.main()
