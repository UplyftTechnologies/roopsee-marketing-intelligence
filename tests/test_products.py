"""Offline checks for the Products catalogue and its stacked offer estimates."""
import unittest
from unittest.mock import patch

import duckdb

from mi import core, extract
from mi.db import init_raw
from mi.products import TEST_PRODUCT_ID, offer_prices, products_catalogue


class OfferPrices(unittest.TestCase):
    def test_stacked_prices_round_each_discount_half_up(self):
        prices = offer_prices(625, 500)
        self.assertEqual(prices["off_mrp"], 0.2)
        self.assertIs(prices["new15_eligible"], True)
        self.assertEqual(prices["new15_price"], 425)
        self.assertEqual(prices["pay_online_price"], 404)
        self.assertEqual(prices["app_price"], 363)
        self.assertEqual(prices["coupon_discounts"], {"NEW15": 75, "GLO10": 50, "APP10": 43})

    def test_new15_minimum_is_inclusive(self):
        below = offer_prices(400, 298.99)
        self.assertIs(below["new15_eligible"], False)
        self.assertIsNone(below["new15_price"])
        self.assertEqual(below["pay_online_price"], 283.99)
        self.assertEqual(below["app_price"], 255.99)
        self.assertEqual(below["coupon_discounts"], {"APP10": 30})

        at = offer_prices(400, 299)
        self.assertIs(at["new15_eligible"], True)
        self.assertEqual(at["new15_price"], 254)
        self.assertEqual(at["pay_online_price"], 241)
        self.assertEqual(at["app_price"], 218)
        self.assertEqual(at["coupon_discounts"], {"NEW15": 45, "APP10": 25})

    def test_returning_coupon_boundaries_and_overlap(self):
        returning_codes = {"GLO10", "GLO15", "FLAT300", "FLAT500"}
        for price, expected in [
            (499.99, {}),
            (500, {"GLO10": 50}),
            (998.99, {"GLO10": 100}),
            (999, {"GLO10": 100, "FLAT300": 300}),
            (999.99, {"GLO10": 100, "FLAT300": 300}),
            (1000, {"GLO15": 150, "FLAT300": 300}),
            (1498.99, {"GLO15": 225, "FLAT300": 300}),
            (1499, {"GLO15": 225, "FLAT300": 300, "FLAT500": 500}),
            (1499.99, {"GLO15": 225, "FLAT300": 300, "FLAT500": 500}),
            (1500, {"GLO15": 225, "FLAT500": 500}),
        ]:
            with self.subTest(price=price):
                discounts = offer_prices(2000, price)["coupon_discounts"]
                self.assertEqual({code: discounts[code] for code in returning_codes & discounts.keys()}, expected)

    def test_brand_coupons_require_the_qualifying_brand_and_subtotal(self):
        brands = {
            "HARU10": "Haruharu", "TFS10": "THE FACE-SHOP", "MEDICUBE10": "Medicube",
            "COSRX10": "cosrx", "AXISY10": "Axis Y",
        }
        for code, brand in brands.items():
            with self.subTest(brand=brand):
                below = offer_prices(2400, 1998.99, brand)["coupon_discounts"]
                at = offer_prices(2400, 1999, brand)["coupon_discounts"]
                self.assertFalse(brands.keys() & below.keys())
                self.assertEqual(brands.keys() & at.keys(), {code})
                self.assertEqual(at[code], 200)
        self.assertFalse(brands.keys() & offer_prices(2400, 2200, "Other")["coupon_discounts"].keys())

    def test_missing_price_does_not_count_as_ineligible(self):
        prices = offer_prices(500, None)
        self.assertEqual(prices, {
            "mrp": 500, "selling_price": None, "off_mrp": None,
            "new15_eligible": None, "new15_price": None, "pay_online_price": None, "app_price": None,
            "coupon_discounts": {},
        })
        self.assertIsNone(offer_prices(None, 500)["off_mrp"])


class ProductsCatalogue(unittest.TestCase):
    def test_reads_refreshed_catalogue_and_hides_only_the_known_test_sku(self):
        source = [
            {"product_id": TEST_PRODUCT_ID, "product_name": "Checkout test", "mrp": 1, "selling_price": 1},
            {"product_id": "trial", "product_name": "Sample", "mrp": 1, "selling_price": 1},
            {"product_id": "cream-50", "product_name": "Cream", "brand": "Roopsee", "category_l1": "Skincare",
             "category_l2": "Moisturizer", "sku_size": "50 ml", "mrp": 625, "selling_price": 500,
             "images": "https://example.com/cream.jpg|https://example.com/detail.jpg"},
            {"product_id": "cream-100", "product_name": "Cream", "sku_size": "100 ml", "mrp": 999, "selling_price": 850},
        ]
        with duckdb.connect() as con:
            init_raw(con)
            with patch.object(core, "CON", con), patch.object(extract, "ReadOnlySupabase") as supabase:
                self.assertEqual(products_catalogue()["rows"], [])
                supabase.return_value.select.return_value = source
                extract.extract_small(con, only={"raw_catalog_master"})
                data = products_catalogue()

        rows = {row["product_id"]: row for row in data["rows"]}
        self.assertEqual(set(rows), {"trial", "cream-50", "cream-100"})
        self.assertEqual((rows["cream-50"]["size"], rows["cream-100"]["size"]), ("50 ml", "100 ml"))
        self.assertEqual(rows["cream-50"]["image"], "https://example.com/cream.jpg")
        self.assertEqual(rows["cream-50"]["app_price"], 363)
        self.assertEqual(rows["cream-50"]["coupon_discounts"]["NEW15"], 75)
        self.assertEqual({coupon["code"] for coupon in data["rules"]["coupons"]}, {
            "NEW15", "GLO10", "GLO15", "FLAT300", "FLAT500", "APP10",
            "HARU10", "TFS10", "MEDICUBE10", "COSRX10", "AXISY10",
        })
