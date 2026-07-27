from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from app.source_config import load_sources


class SourceConfigTest(unittest.TestCase):
    def test_load_schema_v1(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.json"
            path.write_text(json.dumps({
                "schema_version": 1,
                "sources": [{
                    "chain": "netto", "enabled": True, "priority": 1,
                    "url": "https://example.invalid", "scope": "test",
                    "notes": "", "keywords": ["offer"], "store_external_id": "6071",
                    "store_internal_id": "internal-6071", "store_name": "Netto Test"
                }]
            }), encoding="utf-8")
            items = load_sources(path)
            self.assertEqual(items[0].chain, "netto")
            self.assertEqual(items[0].store_external_id, "6071")
            self.assertEqual(items[0].store_internal_id, "internal-6071")


    def test_load_edeka_dual_store_ids(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sources.json"
            path.write_text(
                json.dumps(
                    {
                        "schema_version": 1,
                        "sources": [
                            {
                                "chain": "edeka",
                                "enabled": True,
                                "priority": 2,
                                "url": "https://www.edeka.de/maerkte/071897/angebote/",
                                "scope": "family_primary_edeka",
                                "notes": "",
                                "keywords": ["Angebote"],
                                "store_external_id": "071897",
                                "store_internal_id": "587881",
                                "store_name": "EDEKA Patzer",
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

            item = load_sources(path)[0]
            self.assertEqual(item.store_external_id, "071897")
            self.assertEqual(item.store_internal_id, "587881")
            self.assertEqual(item.store_name, "EDEKA Patzer")


if __name__ == "__main__":
    unittest.main()
