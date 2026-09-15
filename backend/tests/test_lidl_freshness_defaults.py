from __future__ import annotations

import importlib.util
from pathlib import Path
from tempfile import TemporaryDirectory
import unittest


ROOT = Path(__file__).resolve().parents[2]
PLANNER_SCRIPT = ROOT / "tools" / "lidl_weekly_gate_d_activation_plan.py"


def load_script(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec and spec.loader
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class LidlFreshnessDefaultsTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls) -> None:
        cls.planner = load_script(
            PLANNER_SCRIPT,
            "lidl_gate_d_freshness_planner",
        )

    def test_gate_d_activation_defaults_to_next_family(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            args = self.planner.build_parser().parse_args(
                [
                    "--output-dir",
                    str(root / "out"),
                    "--repo-root",
                    "/srv/hermes-deals",
                    "--repo-sha",
                    "a" * 40,
                    "--python",
                    "/usr/bin/python3",
                    "--corpus-root",
                    "/srv/lidl-corpus",
                    "--evidence-root",
                    "/srv/lidl-evidence",
                    "--on-calendar",
                    "Sun *-*-* 00:10:00 Europe/Berlin",
                    "--retry-delay",
                    "30min",
                    "--retry-window",
                    "2h",
                    "--max-attempts",
                    "3",
                    "--timeout-start",
                    "20min",
                ]
            )
            self.assertEqual(args.target, "next")

    def test_default_activation_unit_pins_next_target(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            plan = self.planner.build_activation_plan(
                output_dir=root / "out",
                repo_root=Path("/srv/hermes-deals"),
                repo_sha="a" * 40,
                python_path=Path("/usr/bin/python3"),
                corpus_root=Path("/srv/lidl-corpus"),
                evidence_root=Path("/srv/lidl-evidence"),
                on_calendar="Sun *-*-* 00:10:00 Europe/Berlin",
                retry_delay="30min",
                retry_window="2h",
                max_attempts=3,
                timeout_start="20min",
            )
            self.assertEqual(plan["planner_version"], "lidl-weekly-gate-d-activation-plan-v2")
            self.assertEqual(plan["target"], "next")
            service = (
                root / "out" / self.planner.SERVICE_UNIT
            ).read_text(encoding="utf-8")
            self.assertIn("--target next", service)
            self.assertNotIn("--target current", service)


if __name__ == "__main__":
    unittest.main()
