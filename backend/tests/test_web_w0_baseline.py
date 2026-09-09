from __future__ import annotations

from hashlib import sha256
import importlib.util
from pathlib import Path
import sys
import tempfile
import unittest


ROOT = Path(__file__).resolve().parents[2]
TOOL_PATH = ROOT / "tools" / "web_w0_baseline.py"
SPEC = importlib.util.spec_from_file_location("web_w0_baseline", TOOL_PATH)
assert SPEC and SPEC.loader
MODULE = importlib.util.module_from_spec(SPEC)
sys.modules[SPEC.name] = MODULE
SPEC.loader.exec_module(MODULE)


class WebW0BaselineTest(unittest.TestCase):
    def _make_repo(self, root: Path) -> dict[str, bytes]:
        payloads: dict[str, bytes] = {}
        for index, relative in enumerate(MODULE.SOURCE_PATHS):
            payload = f"fixture-{index}-OFFER_SECRET_PAYLOAD\n".encode()
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(payload)
            payloads[relative] = payload
        return payloads

    def test_deterministic_output_and_content_binding(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payloads = self._make_repo(root)
            git_sha = "1" * 40

            first = MODULE.build_baseline(root, git_sha)
            second = MODULE.build_baseline(root, git_sha)
            first_render = MODULE.render_baseline(first)

            self.assertEqual(first, second)
            self.assertEqual(first_render, MODULE.render_baseline(second))
            self.assertEqual(first["git_sha"], git_sha)
            self.assertTrue(first["source_only"])
            self.assertEqual(
                first["source_totals"]["file_count"],
                len(MODULE.SOURCE_PATHS),
            )

            first_path = MODULE.SOURCE_PATHS[0]
            first_entry = first["source_inventory"][0]
            self.assertEqual(first_entry["path"], first_path)
            self.assertEqual(first_entry["byte_count"], len(payloads[first_path]))
            self.assertEqual(
                first_entry["sha256"],
                sha256(payloads[first_path]).hexdigest(),
            )
            self.assertNotIn("OFFER_SECRET_PAYLOAD", first_render)

    def test_external_observations_remain_explicitly_unobserved(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_repo(root)
            baseline = MODULE.build_baseline(root, "2" * 40)

            self.assertEqual(
                set(baseline["external_evidence"]),
                {
                    "production_ui_html",
                    "response_headers",
                    "browser_load",
                    "startup_waterfall",
                    "chrome_coverage",
                    "keyboard_only",
                },
            )
            for slot in baseline["external_evidence"].values():
                self.assertEqual(slot["state"], "not_observed")

            safety = baseline["safety"]
            self.assertFalse(safety["production_browser_observation_claimed"])
            self.assertFalse(safety["production_header_observation_claimed"])
            self.assertFalse(safety["w0_exit_gate_satisfied_by_this_manifest"])

    def test_invalid_sha_and_missing_source_fail_closed(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_repo(root)

            with self.assertRaises(MODULE.BaselineError):
                MODULE.build_baseline(root, "ABC")
            (root / MODULE.SOURCE_PATHS[-1]).unlink()
            with self.assertRaises(MODULE.BaselineError):
                MODULE.build_baseline(root, "3" * 40)

    def test_symlink_and_path_escape_are_rejected(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self._make_repo(root)

            source = root / MODULE.SOURCE_PATHS[0]
            target = root / "outside-source.txt"
            target.write_text("outside\n", encoding="utf-8")
            source.unlink()
            source.symlink_to(target)

            with self.assertRaises(MODULE.BaselineError):
                MODULE.build_baseline(root, "4" * 40)
            with self.assertRaises(MODULE.BaselineError):
                MODULE._safe_regular_file(root, "../outside-source.txt")

    def test_current_checkout_matches_allowlisted_source_contract(self) -> None:
        baseline = MODULE.build_baseline(ROOT, "0" * 40)
        self.assertEqual(
            [entry["path"] for entry in baseline["source_inventory"]],
            list(MODULE.SOURCE_PATHS),
        )
        self.assertEqual(
            baseline["source_totals"]["file_count"],
            len(MODULE.SOURCE_PATHS),
        )
        self.assertGreater(baseline["source_totals"]["byte_count"], 0)


if __name__ == "__main__":
    unittest.main()
