from __future__ import annotations

from datetime import date, datetime, timezone
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
import tempfile

from app import _NETTO_ISSUE19_RELEASE_CONTRACT
from app.netto_daily_special_api import _latest_snapshot


POLICY_FIXTURE = (
    Path(__file__).resolve().parent
    / "fixtures"
    / "netto"
    / "n25_title_package_review_policy_v1.json"
)


class _ScalarRows:
    def __init__(self, rows):
        self._rows = list(rows)

    def all(self):
        return list(self._rows)


class _FakeDb:
    def __init__(self, snapshots):
        self._snapshots = list(snapshots)

    def scalars(self, statement):
        return _ScalarRows(self._snapshots)


def _snapshot(
    root: Path,
    *,
    name: str,
    valid_from: date,
    valid_until: date,
    collected_at: datetime,
):
    manifest = {
        "schema_version": 3,
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "prospect_slug": name,
        "valid_from": valid_from.isoformat(),
        "valid_until": valid_until.isoformat(),
    }
    path = root / f"{name}.json"
    path.write_text(json.dumps(manifest), encoding="utf-8")
    return SimpleNamespace(
        snapshot_path=str(path),
        sha256=sha256(path.read_bytes()).hexdigest(),
        collected_at=collected_at,
    )


def test_issue19_runtime_release_contract_is_exact() -> None:
    assert (
        _NETTO_ISSUE19_RELEASE_CONTRACT
        == "requested-date-window+review-only-v1"
    )


def test_issue19_requested_date_keeps_matching_older_campaign() -> None:
    with tempfile.TemporaryDirectory() as tmp:
        root = Path(tmp)
        newer = _snapshot(
            root,
            name="next-week",
            valid_from=date(2026, 8, 10),
            valid_until=date(2026, 8, 15),
            collected_at=datetime(2026, 8, 10, tzinfo=timezone.utc),
        )
        requested = _snapshot(
            root,
            name="requested-week",
            valid_from=date(2026, 8, 3),
            valid_until=date(2026, 8, 8),
            collected_at=datetime(2026, 8, 3, tzinfo=timezone.utc),
        )

        selected = _latest_snapshot(
            _FakeDb([newer, requested]),
            date(2026, 8, 4),
        )

    assert selected is requested


def test_issue19_title_package_policy_remains_review_only() -> None:
    policy = json.loads(POLICY_FIXTURE.read_text(encoding="utf-8"))

    assert policy["title_policy"]["automatic_selection_enabled"] is False
    assert policy["title_policy"]["route"] == "review_required"
    assert policy["package_policy"]["automatic_selection_enabled"] is False
    assert policy["package_policy"]["route"] == "review_required"
    assert policy["promotion_policy"]["automatic_approval_enabled"] is False
    assert policy["promotion_policy"]["automatic_publish_enabled"] is False
    assert policy["promotion_policy"]["production_integration_allowed"] is False
    assert policy["production_write_performed"] is False
