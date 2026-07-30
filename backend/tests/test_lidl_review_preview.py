from __future__ import annotations

from pathlib import Path
from tempfile import TemporaryDirectory
import unittest

from app.lidl_review_preview import (
    ReviewPreviewUnavailable,
    build_review_preview_spec,
    resolve_review_preview,
)


PDF_SHA = "c20598d30ff56ce4580c16473b9fc3fdae33649ba32925355d07d8b49c367eb5"
PNG = b"\x89PNG\r\n\x1a\nfixture"


def page_alert() -> dict[str, object]:
    return {
        "source_chain": "lidl",
        "page_number": 19,
        "review_kind": "page_alert",
        "original_payload": {
            "review_kind": "page_alert",
            "hints": [
                {"product_name_hint": "Cola", "title_bbox": [40, 390, 190, 440]},
                {"product_name_hint": "L'ARRIVÉE", "title_bbox": [240, 390, 430, 440]},
            ],
        },
        "provenance": {"source_pdf_sha256": PDF_SHA},
    }


def cola_product() -> dict[str, object]:
    return {
        "source_chain": "lidl",
        "page_number": 19,
        "review_kind": "product",
        "original_payload": {"review_kind": "product"},
        "provenance": {
            "source_pdf_sha256": PDF_SHA,
            "title_bbox": [40, 390, 190, 440],
        },
    }


class LidlReviewPreviewTest(unittest.TestCase):
    def test_page_is_shared_and_hint_product_band_paths_match(self) -> None:
        alert_page = build_review_preview_spec(page_alert(), mode="page")
        product_page = build_review_preview_spec(cola_product(), mode="page")
        hint_band = build_review_preview_spec(page_alert(), mode="band", hint_index=0)
        product_band = build_review_preview_spec(cola_product(), mode="band")

        self.assertEqual(alert_page.relative_path, product_page.relative_path)
        self.assertEqual(hint_band.relative_path, product_band.relative_path)
        self.assertNotEqual(alert_page.relative_path, hint_band.relative_path)

    def test_resolves_only_sha_bound_png_below_root(self) -> None:
        with TemporaryDirectory() as tmp:
            root = Path(tmp)
            spec = build_review_preview_spec(page_alert(), mode="band", hint_index=0)
            path = spec.path_under(root)
            path.parent.mkdir(parents=True)
            path.write_bytes(PNG)

            resolved, digest = resolve_review_preview(
                page_alert(),
                mode="band",
                hint_index=0,
                root=root,
            )
            self.assertEqual(resolved, path.resolve())
            self.assertEqual(digest, PDF_SHA)

            path.write_text("not png", encoding="utf-8")
            with self.assertRaises(ReviewPreviewUnavailable):
                resolve_review_preview(
                    page_alert(),
                    mode="band",
                    hint_index=0,
                    root=root,
                )

    def test_rejects_invalid_source_and_missing_geometry_or_asset(self) -> None:
        invalid = page_alert()
        invalid["provenance"] = {"source_pdf_sha256": "not-a-sha"}
        with self.assertRaises(ReviewPreviewUnavailable):
            build_review_preview_spec(invalid, mode="page")

        with self.assertRaises(ReviewPreviewUnavailable):
            build_review_preview_spec(page_alert(), mode="band", hint_index=99)

        with TemporaryDirectory() as tmp:
            with self.assertRaises(ReviewPreviewUnavailable):
                resolve_review_preview(page_alert(), mode="page", root=Path(tmp))


if __name__ == "__main__":
    unittest.main()
