"""Source-only click-to-magnify HZ47 pilot guard tests (no local PDF in CI)."""
from pathlib import Path
import sys

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "tools"))
from netto_hz47_click_to_magnify_pilot import (
    SOURCE_SHA256, PAGES, FORMAT, HTML, page_html, build,
)


def test_immutable_five_page_scope_and_no_synthetic_identity():
    assert PAGES == (1, 21, 34, 49, 57)
    assert SOURCE_SHA256 == "c8551dd197ac3050e11a9419a73b174803e5b8684890404b10b77520d3e7436a"
    assert FORMAT == "hermes.netto.hz47.pdf_click_magnify_diagnostic.v1"
    assert "verified product" not in HTML.lower()
    assert "Keine Produktzuordnung" in HTML
    assert "Kein bestätigtes Produkt oder Preis" in HTML
    assert "touch-action:pan-x pan-y" in HTML


def test_all_pilot_pages_use_own_source_image_without_card_boxes():
    for page in PAGES:
        image = f"page{page:02d}.png"
        preview = page_html(page, image)
        assert image in preview
        assert f"Seite {page}" in preview
        assert 'id="page"' in preview
        assert 'id="viewer"' in preview
        assert 'id="zoomed"' in preview
        assert 'aria-label="Schließen"' in preview
        assert "pointercancel" in preview
        assert "Math.hypot" in preview
        assert "showModal()" in preview
        assert "data-product-id" not in preview
        assert "offer_link" not in preview
        assert "document.write" not in preview


def test_untrusted_path_or_page_is_not_inserted_into_html():
    for page, name in (
        (2, "page02.png"),
        (1, "page21.png"),
        (1, "../../evil.png"),
        (1, 'page01.png" onerror="alert(1)'),
    ):
        with pytest.raises(ValueError):
            page_html(page, name)


def test_invalid_pdf_cannot_create_output(tmp_path):
    source = tmp_path / "untrusted.pdf"
    source.write_bytes(b"not a PDF")
    dest = tmp_path / "untrusted-output"
    # PyMuPDF is an optional runtime-only dependency, not required by CI.
    # Invalid file hash is rejected even when PyMuPDF is installed.
    try:
        import fitz  # noqa: F401
    except ImportError:
        pytest.skip("PyMuPDF not installed in CI")
    with pytest.raises(ValueError, match="SHA mismatch"):
        build(source, dest)
    assert not dest.exists()
