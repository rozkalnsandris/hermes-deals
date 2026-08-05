from __future__ import annotations

from datetime import date, datetime, timezone
from pathlib import Path
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch
from uuid import uuid4

from app.edeka_store_offers import EdekaCollectionResult
from app.source_config import SourceConfig


SOURCE_URL = "https://www.edeka.de/maerkte/071897/angebote/"
COLLECTED_AT = datetime(2026, 8, 5, 9, 0, tzinfo=timezone.utc)


def _source() -> SourceConfig:
    return SourceConfig(
        chain="edeka",
        enabled=True,
        priority=2,
        url=SOURCE_URL,
        scope="family_primary_edeka",
        notes="",
        keywords=("Angebote",),
        store_external_id="071897",
        store_internal_id="587881",
        store_name="EDEKA Patzer",
    )


class _SessionContext:
    def __init__(self) -> None:
        self.db = object()

    def __enter__(self):
        return self.db

    def __exit__(self, exc_type, exc, traceback) -> None:
        return None


class EdekaManifestCollectorCliTest(unittest.TestCase):
    def test_unchanged_source_returns_before_parse_and_offer_write(self) -> None:
        import app.edeka_collector_cli as cli

        snapshot = SimpleNamespace(
            id=uuid4(),
            success=True,
            snapshot_path="/immutable/edeka-manifest.json",
            sha256="a" * 64,
            error=None,
            http_status=200,
        )
        session = _SessionContext()
        parse_snapshot = Mock()
        save_offers = Mock()
        with (
            patch.object(cli, "_edeka_source", return_value=_source()),
            patch.object(cli, "SessionLocal", return_value=session),
            patch.object(
                cli,
                "collect_edeka_store_offers",
                return_value=EdekaCollectionResult(
                    snapshot=snapshot,
                    unchanged=True,
                ),
            ),
            patch.object(
                cli,
                "parse_edeka_store_offers_snapshot",
                parse_snapshot,
            ),
            patch.object(cli, "save_offer_candidates", save_offers),
        ):
            result = cli.collect_edeka(150)

        self.assertEqual(result, 0)
        parse_snapshot.assert_not_called()
        save_offers.assert_not_called()

    def test_new_manifest_parses_then_persists_after_minimum_gate(self) -> None:
        import app.edeka_collector_cli as cli

        snapshot_id = uuid4()
        snapshot = SimpleNamespace(
            id=snapshot_id,
            success=True,
            snapshot_path="/immutable/edeka-manifest.json",
            sha256="b" * 64,
            source_url=SOURCE_URL,
            final_url=SOURCE_URL,
            collected_at=COLLECTED_AT,
            error=None,
            http_status=200,
        )
        offers = [
            SimpleNamespace(
                parser_version="edeka-v1",
                valid_from=date(2026, 8, 3),
                valid_until=date(2026, 8, 8),
            )
        ]
        session = _SessionContext()
        with (
            patch.object(cli, "_edeka_source", return_value=_source()),
            patch.object(cli, "SessionLocal", return_value=session),
            patch.object(
                cli,
                "collect_edeka_store_offers",
                return_value=EdekaCollectionResult(
                    snapshot=snapshot,
                    unchanged=False,
                ),
            ),
            patch.object(
                cli,
                "parse_edeka_store_offers_snapshot",
                return_value=offers,
            ) as parse_snapshot,
            patch.object(
                cli,
                "save_offer_candidates",
                return_value=1,
            ) as save_offers,
        ):
            result = cli.collect_edeka(1)

        self.assertEqual(result, 0)
        parse_snapshot.assert_called_once()
        context = parse_snapshot.call_args.args[2]
        self.assertEqual(context.snapshot_id, snapshot_id)
        self.assertEqual(context.public_market_id, "071897")
        self.assertEqual(context.internal_market_id, "587881")
        save_offers.assert_called_once_with(session.db, offers)

    def test_minimum_gate_prevents_offer_write(self) -> None:
        import app.edeka_collector_cli as cli

        snapshot = SimpleNamespace(
            id=uuid4(),
            success=True,
            snapshot_path="/immutable/edeka-manifest.json",
            sha256="c" * 64,
            source_url=SOURCE_URL,
            final_url=SOURCE_URL,
            collected_at=COLLECTED_AT,
            error=None,
            http_status=200,
        )
        session = _SessionContext()
        with (
            patch.object(cli, "_edeka_source", return_value=_source()),
            patch.object(cli, "SessionLocal", return_value=session),
            patch.object(
                cli,
                "collect_edeka_store_offers",
                return_value=EdekaCollectionResult(
                    snapshot=snapshot,
                    unchanged=False,
                ),
            ),
            patch.object(
                cli,
                "parse_edeka_store_offers_snapshot",
                return_value=[],
            ),
            patch.object(cli, "save_offer_candidates") as save_offers,
        ):
            result = cli.collect_edeka(150)

        self.assertEqual(result, 3)
        save_offers.assert_not_called()

    def test_systemd_service_uses_manifest_entrypoint(self) -> None:
        root = Path(__file__).resolve().parents[2]
        service = (
            root
            / "infra"
            / "systemd"
            / "hermes-deals-edeka-collector.service"
        ).read_text(encoding="utf-8")

        self.assertIn(
            "python -m app.edeka_collector_cli --min-offers 150",
            service,
        )
        self.assertNotIn("collect --source edeka", service)


if __name__ == "__main__":
    unittest.main()
