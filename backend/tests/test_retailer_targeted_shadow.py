from __future__ import annotations

from datetime import date
import unittest

from app.retailer_targeted_shadow import (
    extract_german_date_ranges,
    lidl_linked_product_ids,
    lidl_product_signature,
    lidl_root_products,
    lidl_store_region_evidence,
    publitas_asset_url,
    publitas_page_image_url,
    publitas_product_ids,
    publitas_product_url,
    select_current_lidl_variants,
)


class RetailerTargetedShadowTest(unittest.TestCase):
    def test_publitas_product_ids_reads_and_deduplicates(self) -> None:
        payload={"spreads":[
            {"hotspots":[{"type":"product","products":[{"id":7},{"id":8}]}]},
            {"hotspots":[{"type":"product","products":[{"id":7}]}]},
        ]}
        self.assertEqual(publitas_product_ids(payload),[7,8])

    def test_publitas_product_url(self) -> None:
        self.assertEqual(
            publitas_product_url("regionale-hz","hz30",7),
            "https://api.publitas.com/v1/groups/regionale-hz/publications/hz30/products/7.json",
        )

    def test_publitas_page_image_url(self) -> None:
        self.assertEqual(
            publitas_page_image_url("/100/200/pages/abc"),
            "https://view.publitas.com/100/200/pages/abc-at1600.jpg",
        )

    def test_publitas_pdf_asset_url(self) -> None:
        self.assertEqual(
            publitas_asset_url("/100/200/pdfs/abc.pdf"),
            "https://view.publitas.com/100/200/pdfs/abc.pdf",
        )

    def test_date_range_short_start_long_end(self) -> None:
        self.assertEqual(
            extract_german_date_ranges("20.07. - 25.07.2026",2026),
            [(date(2026,7,20),date(2026,7,25))],
        )

    def test_date_range_two_full_dates(self) -> None:
        self.assertEqual(
            extract_german_date_ranges("20.07.26 – 25.07.26",2026),
            [(date(2026,7,20),date(2026,7,25))],
        )

    def test_lidl_root_products_object_shape_and_prices(self) -> None:
        detail={"flyer":{"products":{
            "a":{"id":1,"name":"Milch","price":1.11,"brand":"X"},
            "b":{"productId":"2","title":"Brot","price":"0,99"},
        }}}
        rows=lidl_root_products(detail)
        self.assertEqual(len(rows),2)
        self.assertEqual([x["price"] for x in rows],[1.11,0.99])

    def test_lidl_root_products_array_shape(self) -> None:
        detail={"flyer":{"products":[
            {"id":1,"name":"Milch","price":{"value":1.49}},
            {"id":2,"name":"Brot","price":None},
        ]}}
        rows=lidl_root_products(detail)
        self.assertEqual(rows[0]["price"],1.49)
        self.assertIsNone(rows[1]["price"])

    def test_lidl_linked_product_ids(self) -> None:
        detail={"flyer":{"pages":[{"links":[
            {"productDetails":{"productId":1}},
            {"productDetails":{"id":"2"}},
            {"title":"not-product"},
        ]}]}}
        self.assertEqual(lidl_linked_product_ids(detail),{"1","2"})

    def test_lidl_signature_is_order_independent(self) -> None:
        a=[{"id":"1","title":"Milch","price":1.11},{"id":"2","title":"Brot","price":0.99}]
        b=list(reversed(a))
        self.assertEqual(lidl_product_signature(a),lidl_product_signature(b))

    def test_select_current_lidl_variants(self) -> None:
        flyers=[
            {"name":"Aktionsprospekt","offerStartDate":"2026-07-20","offerEndDate":"2026-07-25","flyerJson":"x"},
            {"name":"Aktionsprospekt","offerStartDate":"2026-07-27","offerEndDate":"2026-08-01","flyerJson":"y"},
            {"name":"Other","offerStartDate":"2026-07-20","offerEndDate":"2026-07-25","flyerJson":"z"},
        ]
        self.assertEqual(
            [x["flyerJson"] for x in select_current_lidl_variants(flyers,date(2026,7,25))],
            ["x"],
        )

    def test_nuxt_store_region_evidence_is_conservative(self) -> None:
        payload=[
            {"objectNumber":1,"marketingData":2},
            "DE06664",
            {"offerRegion":3,"other":4},
            "31",
            "ignore",
        ]
        result=lidl_store_region_evidence(payload,"DE06664",{"31","19"})
        self.assertTrue(result["store_object_found"])
        self.assertEqual(result["candidate_offer_regions"],["31"])


if __name__=="__main__":
    unittest.main()
