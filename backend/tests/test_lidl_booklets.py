"""Lidl reader: official source hashes, correct branch and Netto-compatible UI."""
from datetime import date, datetime, timezone
from decimal import Decimal
from hashlib import sha256
import json
from pathlib import Path
from types import SimpleNamespace
from urllib.parse import urljoin
import pytest
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from app import lidl_booklets
from app.models import Base, OfferCandidateRecord, SourceSnapshot

DAY = date(2026, 10, 29)
WHEN = datetime(2026, 10, 26, 8, tzinfo=timezone.utc)
VIEW = "https://www.lidl.de/l/prospekte/test/ar/7"
SELF = "v4/flyer?flyer_identifier=test&region_id=7"
IMAGE = "https://imgproxy.leaflets.schwarz/one/rs:fit:1200:2000:1/image.jpg"
ZOOM = "https://imgproxy.leaflets.schwarz/one/rs:fit:2400:4000:1/zoom.jpg"
SECOND = "https://imgproxy.leaflets.schwarz/two/rs:fit:1200:2000:1/page.jpg"


@pytest.fixture
def env(tmp_path, monkeypatch):
    raw = tmp_path / "raw"
    (raw / "lidl").mkdir(parents=True)
    monkeypatch.setattr(lidl_booklets, "get_settings", lambda: SimpleNamespace(raw_snapshot_dir=raw))
    engine = create_engine("sqlite+pysqlite:///:memory:")
    Base.metadata.create_all(engine)
    with Session(engine) as db:
        source = {
            "dateTime": WHEN.isoformat(), "self": SELF,
            "flyer": {"id": "official-flyer", "offerStartDate": "2026-10-26",
                      "offerEndDate": "2026-10-31", "flyerUrlAbsolute": VIEW,
                      "regions": [{"code": "7"}],
                      "pages": [{"number": 1, "image": IMAGE, "zoom": ZOOM},
                                {"number": 2, "image": SECOND}]},
        }
        def write(value):
            content = json.dumps(value).encode()
            hash_value = sha256(content).hexdigest()
            path = raw / "lidl" / f"flyer-{hash_value}.json"
            path.write_bytes(content)
            return str(path), hash_value, len(content)
        path, digest, count = write(source)
        api = urljoin("https://endpoints.leaflets.schwarz/", SELF)
        snapshot = SourceSnapshot(
            source_chain="lidl", source_url=api, final_url=api,
            scope="physical_store_flyer:r7:2026-10-26:2026-10-31",
            strategy_hint="lidl_public_flyer_json_canonical", success=True,
            collected_at=WHEN, snapshot_path=path, sha256=digest, content_bytes=count,
        )
        db.add(snapshot)
        db.flush()
        payload = {
            "source_snapshot_id": str(snapshot.id), "source_snapshot_sha256": digest,
            "official_flyer_id": "official-flyer", "source_pdf_sha256": "a" * 64,
            "region": "7", "page": 1, "page_image_url": ZOOM,
            "channel": "physical_store", "import_scope_decision": "in_scope",
            "db_write_eligible": True, "production_ready_shadow": True,
        }
        row = OfferCandidateRecord(
            snapshot_id=snapshot.id, source_chain="lidl", source_store_external_id="DE06664",
            source_offer_id="offer1", product_name_raw="Piens", price_eur=Decimal("1.49"),
            valid_from=date(2026, 10, 26), valid_until=date(2026, 10, 31),
            source_url=VIEW, collected_at=WHEN, parser_version="test", raw_payload=payload,
        )
        db.add(row)
        db.commit()
        yield db, source, snapshot, row, write
    engine.dispose()


def test_page_images_zoom_and_navigation(env):
    db, _, snapshot, _, _ = env
    one = lidl_booklets.build_lidl_booklet(db, DAY)
    assert one["state"] == "ready" and one["snapshot_id"] == str(snapshot.id)
    assert one["page_count"] == 2 and one["swipeable"]
    assert one["image_url"] == IMAGE and one["pages"][0]["zoom_image_url"] == ZOOM
    assert one["pages"][1]["zoom_image_url"] is None
    assert one["offers"] == []
    assert "retailer=lidl" in one["next_href"]
    two = lidl_booklets.build_lidl_booklet(db, DAY, 2)
    assert two["image_url"] == SECOND and two["previous_href"] and not two["next_href"]
    assert lidl_booklets.build_lidl_booklet(db, DAY, 3)["state"] == "missing_page"


def test_selected_store_requires_published_anchor(env):
    db, _, _, row, _ = env
    row.source_store_external_id = "another"
    db.commit()
    assert lidl_booklets.build_lidl_booklet(db, DAY)["state"] == "unavailable"


@pytest.mark.parametrize("change", [
    lambda source: source["flyer"].update(flyerUrlAbsolute="https://evil.invalid/ar/7"),
    lambda source: source["flyer"].update(offerEndDate="2026-11-15"),
    lambda source: source["flyer"]["pages"][0].update(zoom="https://evil.invalid/x.jpg"),
    lambda source: source["flyer"]["pages"][1].update(number=1),
    lambda source: source["flyer"].update(regions=[{"code": "8"}]),
    lambda source: source.update(self="v4/flyer?flyer_identifier=test&region_id=8"),
])
def test_reject_invalid_snapshot_metadata(env, change):
    db, source, snapshot, row, write = env
    change(source)
    path, digest, count = write(source)
    snapshot.snapshot_path, snapshot.sha256, snapshot.content_bytes = path, digest, count
    row.raw_payload = {**row.raw_payload, "source_snapshot_sha256": digest}
    db.commit()
    assert lidl_booklets.build_lidl_booklet(db, DAY)["state"] == "unavailable"


@pytest.mark.parametrize("change", [
    lambda row: setattr(row, "source_url", "https://example.invalid/bad"),
    lambda row: setattr(row, "raw_payload", {**row.raw_payload, "source_pdf_sha256": ""}),
    lambda row: setattr(row, "raw_payload", {**row.raw_payload, "page": 3}),
    lambda row: setattr(row, "raw_payload", {**row.raw_payload, "db_write_eligible": False}),
    lambda row: setattr(row, "raw_payload", {**row.raw_payload, "page_image_url": "https://evil.invalid/x"}),
])
def test_reject_unbound_offer_provenance(env, change):
    db, _, _, row, _ = env
    change(row)
    db.commit()
    assert lidl_booklets.build_lidl_booklet(db, DAY)["state"] == "unavailable"


def test_corruption_and_date_bounds(env):
    db, _, snapshot, _, _ = env
    Path(snapshot.snapshot_path).write_bytes(b"corrupted")
    assert lidl_booklets.build_lidl_booklet(db, DAY)["state"] == "unavailable"
    assert lidl_booklets.build_lidl_booklet(db, date(2026, 10, 25))["state"] == "unavailable"
    with pytest.raises(ValueError):
        lidl_booklets.build_lidl_booklet(db, DAY, 0)
