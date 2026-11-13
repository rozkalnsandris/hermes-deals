from __future__ import annotations

from copy import deepcopy
from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import subprocess
import sys

import pytest

TOOL = Path(__file__).resolve().parents[2] / "tools" / "pdf_retention_inventory.py"
spec = spec_from_file_location("pdf_retention_inventory_expiry_plan", TOOL)
assert spec and spec.loader
inventory = module_from_spec(spec)
spec.loader.exec_module(inventory)


def report(*, status="inventory_complete", storage=False, archives=False, images=False):
    return {
        "schema_version": 2,
        "registry_checked_at": "2026-11-13T12:00:00+00:00",
        "status": status,
        "roots": ["/srv/raw", "/srv/corpus"],
        "assets": [
            {
                "kind": "pdf",
                "sha256": "a" * 64,
                "bytes": 100,
                "copies": [
                    {"root": 1, "path": "later.pdf"},
                    {"root": 0, "path": "first.pdf"},
                ],
                "first_acquired_at": "2026-10-01T00:00:00+00:00",
                "expires_at": "2026-10-31T00:00:00+00:00",
                "acquisition_status": "raw_expired",
            },
            {
                "kind": "pdf",
                "sha256": "b" * 64,
                "bytes": 100,
                "copies": [{"root": 0, "path": "keep.pdf"}],
                "first_acquired_at": "2026-11-01T00:00:00+00:00",
                "expires_at": "2026-12-01T00:00:00+00:00",
                "acquisition_status": "within_retention",
            },
        ],
        "findings": [],
        "archive_contents_inspected": archives,
        "image_parent_bindings_verified": images,
        "all_storage_locations_verified": storage,
        "retention_compliance": "unknown",
        "deletion_authorized": False,
    }


def test_expiry_dry_run_lists_only_observed_expired_pdf_copies_and_never_authorizes():
    source = report()
    before = deepcopy(source)
    result = inventory.expired_pdf_dry_run(source)
    plan = result["expiry_dry_run"]

    assert source == before
    assert plan["mode"] == "observed_expired_pdf_copies_only"
    assert plan["candidate_pdf_sha_count"] == 1
    assert plan["candidate_copy_count"] == 2
    assert plan["candidates"] == [
        {
            "root": 0,
            "path": "first.pdf",
            "pdf_sha256": "a" * 64,
            "expires_at": "2026-10-31T00:00:00+00:00",
        },
        {
            "root": 1,
            "path": "later.pdf",
            "pdf_sha256": "a" * 64,
            "expires_at": "2026-10-31T00:00:00+00:00",
        },
    ]
    assert {row["type"] for row in plan["blockers"]} == {
        "storage_locations_unverified",
        "archive_contents_uninspected",
        "image_parent_bindings_unverified",
    }
    assert plan["ready_for_explicit_apply_gate"] is False
    assert plan["apply_supported"] is False
    assert result["deletion_authorized"] is False


@pytest.mark.parametrize("state", ["unregistered", "acquisition_unknown", "not_yet_acquired"])
def test_expiry_dry_run_preserves_unknown_or_unusable_acquisition_state_as_blocker(state):
    source = report(storage=True, archives=True, images=True)
    source["assets"][1]["acquisition_status"] = state
    source["assets"][1]["first_acquired_at"] = None
    source["assets"][1]["expires_at"] = None
    result = inventory.expired_pdf_dry_run(source)
    blocker = [row for row in result["expiry_dry_run"]["blockers"]
               if row["type"] == "pdf_acquisition_state"]
    assert blocker == [{
        "type": "pdf_acquisition_state",
        "pdf_sha256": "b" * 64,
        "state": state,
    }]
    assert result["expiry_dry_run"]["ready_for_explicit_apply_gate"] is False
    assert result["deletion_authorized"] is False


def test_expiry_dry_run_marks_complete_proven_report_ready_but_still_not_authorized():
    result = inventory.expired_pdf_dry_run(
        report(storage=True, archives=True, images=True)
    )
    assert result["expiry_dry_run"]["blockers"] == []
    assert result["expiry_dry_run"]["ready_for_explicit_apply_gate"] is True
    assert result["expiry_dry_run"]["apply_supported"] is False
    assert result["deletion_authorized"] is False


def test_expiry_dry_run_partial_inventory_is_a_blocker():
    result = inventory.expired_pdf_dry_run(
        report(status="inventory_partial", storage=True, archives=True, images=True)
    )
    assert {"type": "inventory_incomplete"} in result["expiry_dry_run"]["blockers"]
    assert result["expiry_dry_run"]["ready_for_explicit_apply_gate"] is False


@pytest.mark.parametrize("mutation", ["schema", "state", "absolute", "parent", "duplicate"])
def test_expiry_dry_run_rejects_unenriched_or_unsafe_input(mutation):
    source = report(storage=True, archives=True, images=True)
    if mutation == "schema":
        source["schema_version"] = 1
    elif mutation == "state":
        source["assets"][0]["acquisition_status"] = "unknown"
    elif mutation == "absolute":
        source["assets"][0]["copies"][0]["path"] = "/outside.pdf"
    elif mutation == "parent":
        source["assets"][0]["copies"][0]["path"] = "../outside.pdf"
    else:
        source["assets"][0]["copies"][1] = dict(source["assets"][0]["copies"][0])
    with pytest.raises(ValueError):
        inventory.expired_pdf_dry_run(source)


def test_cli_plan_expired_requires_registry_before_scanning(tmp_path):
    source = tmp_path / "source.pdf"
    source.write_bytes(b"%PDF-1.7\nfixture\n")
    before = source.read_bytes()
    result = subprocess.run(
        [sys.executable, str(TOOL), str(tmp_path), "--plan-expired"],
        text=True, capture_output=True, timeout=10,
    )
    assert result.returncode == 2
    assert result.stdout == ""
    assert "--plan-expired requires --with-registry" in result.stderr
    assert source.read_bytes() == before
