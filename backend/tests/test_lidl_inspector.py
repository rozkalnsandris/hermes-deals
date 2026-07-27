from __future__ import annotations

import unittest
from pathlib import Path

from app.lidl_inspector import extract_candidate_tokens, extract_leaflet_refs, extract_script_srcs

FIXTURE = Path(__file__).parent / "fixtures" / "lidl_landing.html"


class LidlInspectorTest(unittest.TestCase):
    def test_extracts_leaflet_links_and_pages(self):
        html = FIXTURE.read_bytes()
        refs = extract_leaflet_refs(html, "https://www.lidl.de/c/online-prospekte/s10005610")
        self.assertEqual(len(refs), 3)
        self.assertEqual(sorted(ref.page for ref in refs if ref.page is not None), [3, 54, 64])
        self.assertEqual({ref.leaflet_key for ref in refs}, {"latest-leaflet-demo"})

    def test_extracts_interesting_candidates(self):
        scripts = extract_script_srcs(FIXTURE.read_bytes(), "https://www.lidl.de/")
        self.assertTrue(any("catalog-app.js" in token for token in scripts))
        tokens = extract_candidate_tokens(FIXTURE.read_bytes(), "https://www.lidl.de/")
        self.assertTrue(any("catalog-app.js" in token for token in tokens))
        self.assertTrue(any("/api/leaflet/catalog.json" in token for token in tokens))


if __name__ == "__main__":
    unittest.main()
