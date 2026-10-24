from __future__ import annotations

import os
from pathlib import Path
import subprocess
import sys
import textwrap
import unittest


class CollectorImportIsolationTest(unittest.TestCase):
    """Cold-process checks: another retailer must not be needed to run a command."""

    def run_isolated(self, body: str, *, selected: str = "") -> None:
        guard = """
            import importlib.abc
            import sys

            selected = SELECTED
            class RetailerImportGuard(importlib.abc.MetaPathFinder):
                def find_spec(self, fullname, path=None, target=None):
                    for retailer in ("aldi", "edeka", "lidl", "netto"):
                        prefixes = ("app." + retailer + "_", "app.parsers." + retailer)
                        if selected not in (retailer, "api") and fullname.startswith(prefixes):
                            raise AssertionError("Unrelated retailer imported: " + fullname)
                    return None

            sys.meta_path.insert(0, RetailerImportGuard())
        """
        script = textwrap.dedent(guard).replace("SELECTED", repr(selected))
        result = subprocess.run(
            [sys.executable, "-c", script + "\n" + textwrap.dedent(body)],
            cwd=Path(__file__).resolve().parents[1],
            env={**os.environ, "DATABASE_URL": "sqlite+pysqlite:///:memory:"},
            capture_output=True,
            text=True,
            timeout=30,
        )
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)

    def test_help_does_not_import_any_retailer(self) -> None:
        for args in (["--help"], ["collect", "--help"]):
            with self.subTest(args=args):
                self.run_isolated(f"""
                    import app.collector_cli as cli
                    sys.argv = ["collector", *{args!r}]
                    try:
                        cli.main()
                    except SystemExit as exc:
                        assert exc.code == 0
                    else:
                        raise AssertionError("Expected argparse help exit")
                """)

    def test_aldi_and_edeka_reach_source_failure_without_other_retailers(self) -> None:
        for retailer, source in (("aldi", "aldi_nord"), ("edeka", "edeka")):
            with self.subTest(source=source):
                self.run_isolated(f"""
                    from types import SimpleNamespace
                    from unittest.mock import MagicMock, patch
                    import app.collector_cli as cli

                    configured = SimpleNamespace(
                        url="https://example.test/fixture",
                        store_external_id="071897",
                        store_internal_id="587881",
                        store_name="Fixture",
                    )
                    failed = SimpleNamespace(
                        success=False, snapshot_path=None,
                        error="fixture source unavailable", http_status=503,
                    )
                    sys.argv = ["collector", "collect", "--source", {source!r}]
                    with (
                        patch.object(cli, "_source_by_name", return_value=configured),
                        patch.object(cli, "SessionLocal", MagicMock()),
                        patch.object(cli, "probe_source", return_value=failed) as probe,
                        patch.object(cli, "save_offer_candidates") as save,
                    ):
                        assert cli.main() == 2
                        probe.assert_called_once()
                        save.assert_not_called()
                """, selected=retailer)

    def test_netto_dispatch_without_other_retailers(self) -> None:
        self.run_isolated("""
            from types import SimpleNamespace
            from unittest.mock import MagicMock, patch
            import app.collector_cli as cli
            import app.netto_html_collector as netto

            result = SimpleNamespace(saved=0, offers=20, cards=20,
                                     rejected=0, snapshot_id="fixture")
            sys.argv = ["collector", "collect", "--source", "netto", "--min-offers", "20"]
            with (
                patch.object(cli, "_source_by_name", return_value=object()),
                patch.object(cli, "SessionLocal", MagicMock()),
                patch.object(netto, "collect_html", return_value=result) as collect,
            ):
                assert cli.main() == 0
                collect.assert_called_once()
                assert collect.call_args.args[3] == 20
        """, selected="netto")


    def test_api_bootstrap_preserves_existing_routes_and_patches(self) -> None:
        self.run_isolated("""
            import app.main as main
            import app.netto_daily_special_api as daily
            import app.weekly_special_api as weekly
            from app.netto_daily_special_runtime_patch import latest_manifest_snapshot
            from app.weekly_special_runtime_patch import isolated_explicit_daily_specials
            from app.current_deals_route_installer import installed_fast_current_deals
            from app.canonical_catalog_route_installer import (
                installed_fast_canonical_catalog,
                installed_fast_canonical_ui_overview,
            )

            assert daily._latest_snapshot is latest_manifest_snapshot
            assert weekly._explicit_daily_specials is isolated_explicit_daily_specials
            expected = {
                "/api/v1/deals/current": installed_fast_current_deals,
                "/api/v1/catalog": installed_fast_canonical_catalog,
                "/api/v1/ui/overview": installed_fast_canonical_ui_overview,
            }
            for path, endpoint in expected.items():
                routes = [r for r in main.app.routes if getattr(r, "path", None) == path]
                assert len(routes) == 1, (path, len(routes))
                assert routes[0].endpoint is endpoint, path
        """, selected="api")


if __name__ == "__main__":
    unittest.main()
