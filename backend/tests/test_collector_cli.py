from __future__ import annotations

import unittest

from app.collector_cli import _required_report_int


class CollectorCliReportParsingTest(unittest.TestCase):
    def test_required_report_int_accepts_numeric_zero(self) -> None:
        self.assertEqual(_required_report_int({"rows_written_second_pass": 0}, "rows_written_second_pass"), 0)

    def test_required_report_int_rejects_missing_or_boolean(self) -> None:
        with self.assertRaises(ValueError):
            _required_report_int({}, "rows_written_second_pass")
        with self.assertRaises(ValueError):
            _required_report_int({"rows_written_second_pass": False}, "rows_written_second_pass")

    def test_required_report_int_accepts_numeric_string(self) -> None:
        self.assertEqual(_required_report_int({"approved_candidate_total": "4"}, "approved_candidate_total"), 4)


class CollectorCliAldiRoutingTest(unittest.TestCase):
    def test_collect_aldi_nord_routes_to_aldi_collector(self) -> None:
        import sys
        from unittest.mock import patch

        import app.collector_cli as collector_cli

        argv = [
            "hermes-deals-collector",
            "collect",
            "--source",
            "aldi_nord",
            "--min-offers",
            "250",
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(
                collector_cli,
                "_collect_aldi_nord",
                return_value=0,
            ) as collect_aldi,
        ):
            self.assertEqual(collector_cli.main(), 0)

        collect_aldi.assert_called_once_with(250)


class CollectorCliEdekaRoutingTest(unittest.TestCase):
    def test_collect_edeka_routes_to_edeka_collector(self) -> None:
        import sys
        from unittest.mock import patch

        import app.collector_cli as collector_cli

        argv = [
            "hermes-deals-collector",
            "collect",
            "--source",
            "edeka",
            "--min-offers",
            "150",
        ]
        with (
            patch.object(sys, "argv", argv),
            patch.object(
                collector_cli,
                "_collect_edeka",
                return_value=0,
            ) as collect_edeka,
        ):
            self.assertEqual(collector_cli.main(), 0)

        collect_edeka.assert_called_once_with(150)

    def test_missing_internal_id_stops_before_session_and_probe(self) -> None:
        from unittest.mock import Mock, patch

        import app.collector_cli as collector_cli
        from app.source_config import SourceConfig

        incomplete = SourceConfig(
            chain="edeka",
            enabled=True,
            priority=2,
            url="https://www.edeka.de/maerkte/071897/angebote/",
            scope="family_primary_edeka",
            notes="",
            keywords=("Angebote",),
            store_external_id="071897",
            store_internal_id=None,
            store_name="EDEKA Patzer",
        )

        with (
            patch.object(
                collector_cli,
                "_source_by_name",
                return_value=incomplete,
            ),
            patch.object(
                collector_cli,
                "SessionLocal",
                Mock(),
            ) as session_local,
            patch.object(
                collector_cli,
                "probe_source",
            ) as probe_source,
        ):
            with self.assertRaisesRegex(
                ValueError,
                "requires store_internal_id",
            ):
                collector_cli._collect_edeka(150)

        session_local.assert_not_called()
        probe_source.assert_not_called()


if __name__ == "__main__":
    unittest.main()
