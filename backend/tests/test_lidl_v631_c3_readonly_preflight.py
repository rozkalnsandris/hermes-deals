from __future__ import annotations

from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

import app.lidl_v631_c3_readonly_preflight as c3


def _receipt(*, raw_sha: str, pdf_sha: str) -> dict[str, object]:
    return {
        "family": c3.EXPECTED_FAMILY,
        "source_pdf_sha256": pdf_sha,
        "source_raw_sha256": raw_sha,
        "scan_tree_sha256": "1" * 64,
        "review_profile_sha256": "2" * 64,
        "semantic_tree_sha256": "3" * 64,
        "semantic_manifest_sha256": "4" * 64,
        "semantic_rows_sha256": "5" * 64,
        "valid_from": "2026-08-10",
        "valid_until": "2026-08-15",
    }


def _frozen_family(tmp_path: Path, *, include_timestamp: bool = True) -> tuple[Path, dict[str, object]]:
    family = tmp_path / c3.EXPECTED_FAMILY
    family.mkdir()
    source = {
        "flyer": {"id": "fixture"},
    }
    if include_timestamp:
        source["dateTime"] = "2026-08-11T19:27:44.949539Z"
    source_raw = json.dumps(source, sort_keys=True).encode()
    pdf_raw = b"exact-frozen-pdf-fixture"
    (family / "source.json").write_bytes(source_raw)
    (family / "source.pdf").write_bytes(pdf_raw)
    (family / "discovery-meta.json").write_text(
        json.dumps(
            {
                "raw_sha256": sha256(source_raw).hexdigest(),
                "pdf_sha256": sha256(pdf_raw).hexdigest(),
                "raw_bytes": len(source_raw),
                "pdf_bytes": len(pdf_raw),
                "valid_from": "2026-08-10",
                "valid_until": "2026-08-15",
            }
        ),
        encoding="utf-8",
    )
    return family, _receipt(raw_sha=sha256(source_raw).hexdigest(), pdf_sha=sha256(pdf_raw).hexdigest())


def test_derives_exact_frozen_source_binding(tmp_path: Path) -> None:
    family, receipt = _frozen_family(tmp_path)
    binding = c3.derive_frozen_source_binding(
        family_dir=family,
        receipt=receipt,
        receipt_sha256="a" * 64,
    )
    assert binding["family"] == c3.EXPECTED_FAMILY
    assert binding["source_collected_at"] == "2026-08-11T19:27:44.949539+00:00"
    assert binding["source_content_bytes"] == (family / "source.json").stat().st_size
    assert binding["snapshot_path"] == str((family / "source.json").resolve())
    assert binding["source_url"].endswith(c3.EXPECTED_FAMILY)


def test_frozen_source_binding_fails_closed_without_collection_timestamp(tmp_path: Path) -> None:
    family, receipt = _frozen_family(tmp_path, include_timestamp=False)
    with pytest.raises(c3.LidlC3ReadonlyPreflightError, match="timestamp is unavailable"):
        c3.derive_frozen_source_binding(
            family_dir=family,
            receipt=receipt,
            receipt_sha256="a" * 64,
        )


class _ScalarResult:
    def __init__(self, value: str) -> None:
        self.value = value

    def scalar_one(self) -> str:
        return self.value


class _ReadOnlySession:
    def __init__(self, *, dialect: str = "postgresql", read_only: str = "on", isolation: str = "repeatable read") -> None:
        self.bind = SimpleNamespace(dialect=SimpleNamespace(name=dialect))
        self.read_only = read_only
        self.isolation = isolation
        self.statements: list[str] = []

    def get_bind(self):
        return self.bind

    def execute(self, statement):
        sql = str(statement)
        self.statements.append(sql)
        if sql == "SHOW transaction_read_only":
            return _ScalarResult(self.read_only)
        if sql == "SHOW transaction_isolation":
            return _ScalarResult(self.isolation)
        return _ScalarResult("")


def test_enforces_repeatable_read_read_only_before_inspection() -> None:
    db = _ReadOnlySession()
    state = c3.enforce_postgres_read_only(db)  # type: ignore[arg-type]
    assert db.statements == [
        "SET TRANSACTION ISOLATION LEVEL REPEATABLE READ, READ ONLY",
        "SHOW transaction_read_only",
        "SHOW transaction_isolation",
    ]
    assert state == {"transaction_read_only": "on", "transaction_isolation": "repeatable read"}


@pytest.mark.parametrize(
    ("dialect", "read_only", "isolation", "message"),
    [
        ("sqlite", "on", "repeatable read", "requires PostgreSQL"),
        ("postgresql", "off", "repeatable read", "transaction_read_only is not on"),
        ("postgresql", "on", "read committed", "isolation is not repeatable read"),
    ],
)
def test_read_only_guard_fails_closed(dialect: str, read_only: str, isolation: str, message: str) -> None:
    with pytest.raises(c3.LidlC3ReadonlyPreflightError, match=message):
        c3.enforce_postgres_read_only(  # type: ignore[arg-type]
            _ReadOnlySession(dialect=dialect, read_only=read_only, isolation=isolation)
        )


def _ready_plan() -> dict[str, object]:
    return {
        "result": "READY_TO_CREATE",
        "source_snapshot_action": "CREATE",
        "offer_candidate_action": "CREATE",
        "conflicts": [],
        "expected_deltas": {"first_apply": {"source_snapshots": 1, "offer_candidates": 1}},
        "database_write": False,
        "review_write": False,
        "production_publish": False,
        "production_deploy": False,
        "corpus_write": False,
        "source_replacement": False,
        "systemd_change": False,
        "scheduler_change": False,
    }


def test_baseline_requires_zero_exact_keys_and_stable_counts() -> None:
    c3.validate_readonly_baseline(
        plan=_ready_plan(),
        before={"source_snapshots": 10, "offer_candidates": 20},
        after={"source_snapshots": 10, "offer_candidates": 20},
        exact={"snapshot_id": 0, "snapshot_raw_sha256": 0, "offer_uniqueness_key": 0},
    )
    with pytest.raises(c3.LidlC3ReadonlyPreflightError, match="already exists"):
        c3.validate_readonly_baseline(
            plan=_ready_plan(),
            before={"source_snapshots": 10, "offer_candidates": 20},
            after={"source_snapshots": 10, "offer_candidates": 20},
            exact={"snapshot_id": 1, "snapshot_raw_sha256": 1, "offer_uniqueness_key": 0},
        )
    with pytest.raises(c3.LidlC3ReadonlyPreflightError, match="row counts changed"):
        c3.validate_readonly_baseline(
            plan=_ready_plan(),
            before={"source_snapshots": 10, "offer_candidates": 20},
            after={"source_snapshots": 11, "offer_candidates": 20},
            exact={"snapshot_id": 0, "snapshot_raw_sha256": 0, "offer_uniqueness_key": 0},
        )


def test_c3_module_has_no_apply_or_commit_path() -> None:
    source = Path(c3.__file__).read_text(encoding="utf-8")
    assert "apply_lidl_v631_semantic_persistence_plan" not in source
    assert ".commit(" not in source
