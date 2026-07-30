from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from lidl_v631_runtime import (
    BASE_SHA256,
    PARSER_VERSION,
    SHADOW_SHA256,
    load_lidl_v631,
)


class LidlV631RuntimeTest(unittest.TestCase):
    def test_exact_provenance_bundle_loads(self) -> None:
        runtime = load_lidl_v631()
        self.assertEqual(runtime.base.PARSER_VERSION, "lidl-pdf-v08c-r6")
        self.assertEqual(runtime.shadow.PARSER_VERSION, PARSER_VERSION)
        self.assertEqual(runtime.provenance_dir.name, "v631")

    def test_base_runtime_exposes_weekly_completeness_primitives(self) -> None:
        runtime = load_lidl_v631()
        for name in (
            "extract_pdf_spans",
            "extract_display_price_observations",
            "_title_groups",
            "_is_suspicious_title",
        ):
            self.assertTrue(callable(getattr(runtime.base, name, None)), name)
        self.assertFalse(hasattr(runtime.shadow, "extract_pdf_spans"))

    def test_source_hash_drift_fails_closed(self) -> None:
        with TemporaryDirectory() as raw:
            root = Path(raw)
            (root / "r61_base.py").write_text("BASE_SHA256 = 'changed'\n")
            (root / "r61_shadow.py").write_text("SHADOW_SHA256 = 'changed'\n")
            with self.assertRaisesRegex(RuntimeError, "source SHA drift"):
                load_lidl_v631(root)

    def test_expected_hashes_are_full_sha256_values(self) -> None:
        for digest in (BASE_SHA256, SHADOW_SHA256):
            self.assertEqual(len(digest), 64)
            self.assertTrue(all(char in "0123456789abcdef" for char in digest))


if __name__ == "__main__":
    unittest.main()
