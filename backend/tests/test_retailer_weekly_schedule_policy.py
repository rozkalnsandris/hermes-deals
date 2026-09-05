from __future__ import annotations

import importlib.util
import json
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[2]
POLICY = ROOT / "config" / "retailer-weekly-schedule-policy-v1.json"
EDEKA_MIGRATION = ROOT / "tools" / "runner" / "reschedule_edeka_weekly_monitor.py"
LIDL_MIGRATION = ROOT / "tools" / "runner" / "reschedule_lidl_gate_d.py"

CANONICAL = "Sun *-*-* 00:10:00 Europe/Berlin"


def load_module(path: Path, name: str):
    spec = importlib.util.spec_from_file_location(name, path)
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    spec.loader.exec_module(module)
    return module


def test_all_family_retailers_share_sunday_0010_activation_default() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    assert policy["schema_version"] == 1
    assert policy["timezone"] == "Europe/Berlin"
    assert policy["publication_reference"] == "Sun *-*-* 00:00:00 Europe/Berlin"
    assert policy["canonical_on_calendar"] == CANONICAL
    assert policy["publication_buffer_minutes"] == 10
    assert set(policy["retailers"]) == {
        "aldi_nord",
        "edeka_patzer_071897",
        "lidl_physical_store",
        "netto_5659",
    }
    assert {
        row["activation_default"]
        for row in policy["retailers"].values()
    } == {CANONICAL}


def test_policy_does_not_authorize_live_or_production_mutation() -> None:
    policy = json.loads(POLICY.read_text(encoding="utf-8"))
    authority = policy["authority"]
    assert authority == {
        "live_scheduler_change_requires_explicit_owner_authorization": True,
        "merge_changes_live_scheduler": False,
        "production_database_write_authorized": False,
        "production_deploy_authorized": False,
        "publication_write_authorized": False,
        "review_write_authorized": False,
    }


def test_merged_edeka_and_prepared_lidl_migrations_match_canonical_schedule() -> None:
    edeka = load_module(EDEKA_MIGRATION, "edeka_schedule_policy")
    lidl = load_module(LIDL_MIGRATION, "lidl_schedule_policy")
    assert edeka.NEW_SCHEDULE == CANONICAL
    assert lidl.NEW_SCHEDULE == CANONICAL
