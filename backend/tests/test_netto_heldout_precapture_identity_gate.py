from __future__ import annotations

from datetime import date
from hashlib import sha256
from importlib.util import module_from_spec, spec_from_file_location
import json
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.netto_store_prospect import NettoStoreProspectBundle


ROOT = Path(__file__).resolve().parents[2]
TOOL = ROOT / "tools" / "netto_heldout_live_source.py"
spec = spec_from_file_location("netto_heldout_live_source", TOOL)
assert spec and spec.loader
live = module_from_spec(spec)
spec.loader.exec_module(live)


def bundle(pdf: bytes = b"%PDF-test-bytes") -> NettoStoreProspectBundle:
    publication = {
        "config": {
            "publicationId": 3342621,
            "sourceDocumentId": 4466010,
        }
    }
    return NettoStoreProspectBundle(
        store_url="https://www.netto-online.de/store?stores_id=5659",
        prospect_url="https://wochenprospekt.netto-online.de/test/?storeid=5659",
        prospect_slug="test-campaign",
        store_html=b"store",
        prospect_html=b"viewer",
        valid_from=date(2026, 9, 3),
        valid_until=date(2026, 9, 5),
        validity_text="03.09.26 - 05.09.26",
        selected_store_cookie_present=True,
        elapsed_ms=0,
        publication_api_url="https://api.publitas.com/v1/groups/regionale-hz/publications/test-campaign.json",
        publication_json=json.dumps(publication).encode(),
        prospect_pdf_url=(
            "https://wochenprospekt.netto-online.de/100989/3342621/pdfs/test.pdf"
        ),
        prospect_pdf=pdf,
    )


def expected_for(value: NettoStoreProspectBundle) -> dict[str, object]:
    return {
        "store_external_id": "5659",
        "scope": "family_primary_netto",
        "campaign_key": value.prospect_slug,
        "valid_from": value.valid_from.isoformat(),
        "valid_until": value.valid_until.isoformat(),
        "publication_id": "3342621",
        "group_id": "100989",
        "source_document_id": "4466010",
        "pdf_url": value.prospect_pdf_url,
        "pdf_size_bytes": len(value.prospect_pdf),
        "pdf_sha256": sha256(value.prospect_pdf).hexdigest(),
    }


def test_expected_identity_accepts_exact_transient_bundle() -> None:
    value = bundle()
    live.validate_expected_identity(value, expected_for(value))


@pytest.mark.parametrize(
    ("field", "replacement"),
    [
        ("campaign_key", "other-campaign"),
        ("valid_from", "2026-09-04"),
        ("valid_until", "2026-09-06"),
        ("publication_id", "9999999"),
        ("group_id", "999999"),
        ("source_document_id", "9999999"),
        ("pdf_url", "https://example.invalid/not-the-frozen-pdf.pdf"),
        ("pdf_size_bytes", 999),
        ("pdf_sha256", "0" * 64),
    ],
)
def test_expected_identity_fails_closed_on_any_mismatch(
    field: str, replacement: object
) -> None:
    value = bundle()
    expected = expected_for(value)
    expected[field] = replacement
    with pytest.raises(live.HeldoutLiveSourceError, match="does not match owner-frozen"):
        live.validate_expected_identity(value, expected)


def test_obsolete_html_interstitial_size_is_explicitly_rejected() -> None:
    value = bundle()
    expected = expected_for(value)
    expected["pdf_size_bytes"] = live.OBSOLETE_NON_PDF_SIZE
    with pytest.raises(
        live.HeldoutLiveSourceError,
        match="204344-byte HTML interstitial size is forbidden",
    ):
        live.validate_expected_identity(value, expected)


def test_materialize_identity_failure_precedes_source_materialization(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw_root = tmp_path / "source"
    output = tmp_path / "live-source.json"
    source = SimpleNamespace(
        store_external_id="5659",
        scope="family_primary_netto",
        url="https://www.netto-online.de/store/5659",
    )
    value = bundle()
    write_called = False

    monkeypatch.setattr(live, "load_family_source", lambda repo: source)
    monkeypatch.setattr(
        live,
        "fetch_latest_nonexpired",
        lambda source, as_of: value,
    )

    def reject_identity(value: object) -> None:
        raise live.HeldoutLiveSourceError("frozen identity mismatch")

    def forbidden_write(*args: object, **kwargs: object) -> None:
        nonlocal write_called
        write_called = True
        raise AssertionError("source materialization must not run")

    monkeypatch.setattr(live, "validate_expected_identity", reject_identity)
    monkeypatch.setattr(live, "_write_bundle", forbidden_write)

    with pytest.raises(live.HeldoutLiveSourceError, match="frozen identity mismatch"):
        live.materialize(ROOT, raw_root, date(2026, 9, 3), output)

    assert not raw_root.exists()
    assert not output.exists()
    assert write_called is False


def test_frozen_identity_uses_corrected_pdf_size_and_sha() -> None:
    assert live.EXPECTED_CAPTURE_IDENTITY["campaign_key"] == (
        "hz36_hasb_4_grpd2aa3f85d0d14fac0003"
    )
    assert live.EXPECTED_CAPTURE_IDENTITY["pdf_size_bytes"] == 53_312_927
    assert live.EXPECTED_CAPTURE_IDENTITY["pdf_size_bytes"] != live.OBSOLETE_NON_PDF_SIZE
    assert live.EXPECTED_CAPTURE_IDENTITY["pdf_sha256"] == (
        "13d081858ba94530a3619429cbfc30626b860295445aa444c3f852b8bfe587b3"
    )
