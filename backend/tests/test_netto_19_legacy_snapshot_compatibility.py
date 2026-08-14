from __future__ import annotations

from pathlib import Path
import unittest


ROOT = Path(__file__).resolve().parents[2]
VERIFIER = ROOT / "tools/runner/netto_19_production_readonly_verify.py"


class Netto19LegacySnapshotCompatibilityContractTest(unittest.TestCase):
    def test_verifier_inventory_excludes_legacy_non_manifest_snapshots(self) -> None:
        text = VERIFIER.read_text(encoding="utf-8")
        self.assertIn(
            "NETTO_MANIFEST_CONTENT_TYPE = "
            "'application/vnd.hermes-deals.netto-store-prospect+json'",
            text,
        )
        self.assertIn(
            "AND content_type='application/vnd.hermes-deals.netto-store-prospect+json'",
            text,
        )


if __name__ == "__main__":
    unittest.main()
