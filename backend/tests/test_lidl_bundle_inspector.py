from __future__ import annotations

import unittest
from pathlib import Path

from app.lidl_bundle_inspector import (
    extract_endpoint_candidates,
    extract_network_snippets,
    extract_source_map_url,
)

FIXTURE = Path(__file__).parent / "fixtures" / "lidl_bundle.js"


class LidlBundleInspectorTest(unittest.TestCase):
    def test_extracts_absolute_and_relative_candidates(self):
        data = FIXTURE.read_bytes()
        values = extract_endpoint_candidates(data, "https://lidl.leaflets.schwarz/assets/index-demo.js")
        self.assertIn("https://leaflet-api.example.test/api/v1", values)
        self.assertIn("https://leaflet-api.example.test/graphql", values)
        self.assertIn("https://lidl.leaflets.schwarz/api/publications/${id}/pages", values)
        self.assertIn("https://lidl.leaflets.schwarz/assets/config/leaflet.json", values)

    def test_extracts_network_context(self):
        snippets = extract_network_snippets(FIXTURE.read_bytes())
        self.assertTrue(any("fetch(" in item for item in snippets))

    def test_extracts_source_map(self):
        url = extract_source_map_url(FIXTURE.read_bytes(), "https://lidl.leaflets.schwarz/assets/index-demo.js")
        self.assertEqual(url, "https://lidl.leaflets.schwarz/assets/index-demo.js.map")


if __name__ == "__main__":
    unittest.main()
