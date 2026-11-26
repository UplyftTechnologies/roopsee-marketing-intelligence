"""Price intelligence: the page readers and the matching rules, offline (no network, no real database).

Run:  .venv\\Scripts\\python -m unittest tests.test_prices -v
The fixtures are real public product pages saved in Nov 2026 (tests/fixtures/prices). When a site changes its pages and its reader starts
failing on live pages, save a fresh page here, fix the reader in mi/price_sites.py, and update the expected numbers below.
"""
import gzip
import os
import sys
import unittest
from pathlib import Path

os.environ["PRICES_SUPABASE_KEY"] = ""  # these tests never touch the shared price store
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import duckdb  # noqa: E402

from mi import core  # noqa: E402
from mi import price_sites as P  # noqa: E402
from mi import prices as R  # noqa: E402

FIX = ROOT / "tests" / "fixtures" / "prices"


def page(name: str) -> str:
    return gzip.open(FIX / f"{name}.html.gz", "rt", encoding="utf-8").read()


class Readers(unittest.TestCase):
    def test_nykaa_regular_price_mrp_and_offer(self):
        r = P.read("nykaa", page("nykaa_instock"))
        self.assertEqual((r["price"], r["mrp"]), (1490.0, 1490.0))  # the regular price (offerPrice), not the cohort offer
        self.assertEqual(r["offer_price"], 1043.0)                  # an offer for some customers only: kept as a note
        self.assertTrue(r["in_stock"])
        self.assertEqual(r["size"], "30ml")

    def test_tira_price_from_the_product_not_the_template(self):
        r = P.read("tira", page("tira_instock"))
        self.assertEqual((r["price"], r["mrp"]), (1799.0, 1999.0))  # the page also holds a ₹1,199 placeholder product: never that
        self.assertTrue(r["in_stock"])
        self.assertIn("Axis-Y", r["name"])
        self.assertEqual(r["size"], "50 ml")

    def test_tira_unavailable_is_out_of_stock_not_an_error(self):
        r = P.read("tira", page("tira_unavailable"))
        self.assertFalse(r["in_stock"])
        self.assertIsNone(r["price"])

    def test_purplle_price_mrp_and_barcode(self):
        r = P.read("purplle", page("purplle_instock"))
        self.assertEqual((r["price"], r["mrp"]), (467.0, 599.0))
        self.assertTrue(r["in_stock"])
        self.assertTrue(r["ean"] and r["ean"].isdigit())

    def test_purplle_sold_out_still_gives_its_price(self):
        r = P.read("purplle", page("purplle_soldout"))
        self.assertFalse(r["in_stock"])
        self.assertEqual((r["price"], r["mrp"]), (1425.0, None))  # structured data says 0 and so does the script's MRP: only the price is real
        self.assertRegex(r["ean"] or "", r"^\d{13}$")  # the barcode is there even when it is sold out, so the match can still be made

    def test_a_page_without_product_data_is_refused(self):
        for site in P.SITES:
            with self.subTest(site=site), self.assertRaises(ValueError):
                P.read(site, "<html><body>Access denied</body></html>")


class Sizes(unittest.TestCase):
    """A page that sells several sizes (Nykaa) must give the price of OUR size, and a page without our size is never compared."""
    page = {"name": "Cetaphil Gentle Skin Cleanser", "price": 197.0, "mrp": 219.0, "size": None, "in_stock": True, "variants": [
        {"size": "59ml", "price": 197.0, "mrp": 219.0, "offer_price": None, "in_stock": True, "stock_qty": 20002},
        {"size": "236ml", "price": 735.0, "mrp": 799.0, "offer_price": 639.0, "in_stock": True, "stock_qty": 28469}]}

    def test_the_variant_of_our_size_is_used(self):
        got, problem = P.fit_size(self.page, P.sizes_in("236ml"))
        self.assertIsNone(problem)
        self.assertEqual((got["price"], got["mrp"], got["offer_price"]), (735.0, 799.0, 639.0))

    def test_a_page_without_our_size_is_not_compared(self):
        got, problem = P.fit_size(self.page, P.sizes_in("125ml"))
        self.assertIn("59ml", problem)

    def test_a_single_size_page_of_another_size_is_not_compared(self):
        _, problem = P.fit_size({"name": "Serum (30 ml)", "size": "30 ml", "price": 500.0}, P.sizes_in("50ml"))
        self.assertTrue(problem)
        self.assertIsNone(P.fit_size({"name": "Serum", "size": None, "price": 500.0}, P.sizes_in("50ml"))[1])  # unknown size: not refused


class Links(unittest.TestCase):
    def test_nykaaman_links_are_read_on_nykaa(self):
        self.assertEqual(P.canonical_url("https://www.nykaaman.com/d-alba-white-truffle-first-spray-serum/p/1991?skuId=3"),
                         "https://www.nykaa.com/d-alba-white-truffle-first-spray-serum/p/1991")
        self.assertEqual(P.site_of("https://www.nykaaman.com/x/p/1"), "nykaa")

    def test_other_shops_are_not_competitor_links(self):
        for u in ("https://www.myntra.com/a/1", "https://elittybeauty.com/products/x", "", None):
            self.assertIsNone(P.canonical_url(u))

    def test_purplle_review_links_become_product_links(self):
        self.assertEqual(P.canonical_url("https://www.purplle.com/product/abc-50-ml/reviews"), "https://www.purplle.com/product/abc-50-ml")


class Matching(unittest.TestCase):
    def test_sizes(self):
        self.assertEqual(P.sizes_in("Serum [30ml]"), {(30.0, "ml")})
        self.assertEqual(P.sizes_in("1 l"), {(1000.0, "ml")})
        self.assertEqual(P.sizes_in("Sunstick 18 gm"), {(18.0, "g")})
        self.assertEqual(P.size_verdict(P.sizes_in("50 ml"), P.sizes_in("50ml")), "same")
        self.assertEqual(P.size_verdict(P.sizes_in("30 ml"), P.sizes_in("150 ml")), "different")
        self.assertEqual(P.size_verdict(P.sizes_in("30 ml"), set()), "unknown")

    def test_same_product_scores_high(self):
        st = P.slug_text("https://www.tirabeauty.com/product/axis-y-panthenol-10-skin-smoothing-shield-cream-50-ml-7612648")
        self.assertGreaterEqual(P.score("Axis-Y Panthenol 10 Skin Smoothing Shield Cream (50 ml)", "Axis-Y", st), 0.95)
        self.assertTrue(P.brand_in("Axis-Y", st))

    def test_a_different_strength_is_not_an_automatic_match(self):
        st = P.slug_text("https://www.tirabeauty.com/product/minimalist-10-glycolic-acid-toner-150ml-111")
        self.assertLess(P.score("Minimalist 8% Glycolic Acid Toner", "Minimalist", st), 0.85)

    def test_percent_written_out_is_the_same_word(self):
        st = P.slug_text("https://www.purplle.com/product/minimalist-8-percentage-glycolic-acid-face-toner-150-ml")
        self.assertGreaterEqual(P.score("Minimalist 8% Glycolic Acid Toner", "Minimalist", st), 0.85)

    def test_their_whole_title_in_our_longer_name_is_the_same_product(self):
        self.assertTrue(P.same_product("Anua Azelaic Acid 10 Hyaluron Redness Soothing Serum For Sensitive Skin", "Anua", "Anua Azelaic Acid 10 Hyaluron Redness Soothing Serum (30 ml)", "same"))
        self.assertTrue(P.same_product("1% Salicylic Acid Oil-Free Moisturizer For Face, Oily & Acne Prone Skin", "The Derma Co", "The Derma Co 1% Salicylic Acid Oil-Free Moisturizer (50g)", "same"))

    def test_no_automatic_match_without_the_same_known_size_or_with_another_strength(self):
        self.assertFalse(P.same_product("Colorbar I-Glide Eye Liner Pencil - 003 Jaded", "Colorbar", "Colorbar I-Glide Eye Pencil", "unknown"))
        self.assertFalse(P.same_product("Minimalist 8% Glycolic Acid Toner", "Minimalist", "Minimalist 10% Glycolic Acid Toner", "same"))
        self.assertFalse(P.same_product("Be Bodywise Advanced Underarm Pigmentation Kit", "Be Bodywise", "Be Bodywise 4% AHA BHA Flora Underarm Roll On & Pigmentation Repair Cream Combo", "same"))

    def test_brand_must_be_in_the_link(self):
        self.assertFalse(P.brand_in("Anua", P.slug_text("https://www.purplle.com/product/cosrx-heartleaf-cream-50-ml")))

    def test_the_tira_id_is_not_a_word(self):
        self.assertNotIn("7612648", P.slug_text("https://www.tirabeauty.com/product/axis-y-cream-50-ml-7612648"))


class PriceKey(unittest.TestCase):
    def test_the_key_is_for_the_price_role_only_and_env_keeps_its_other_lines(self):
        sys.path.insert(0, str(ROOT / "tools"))
        import make_price_key as K
        token = K.make_token("a-secret-for-the-test-only-123456", 1_700_000_000)
        self.assertEqual(K.role_of(token), "mi_price_writer")
        out = K.set_lines("# note\nPRODUCT_SUPABASE_URL=https://x\nPRICES_SUPABASE_KEY=old\n", {"PRICES_SUPABASE_KEY": token})
        self.assertEqual(out, f"# note\nPRODUCT_SUPABASE_URL=https://x\nPRICES_SUPABASE_KEY={token}\n")

    def test_without_a_key_nothing_is_marked_to_be_sent(self):
        from mi import price_sync
        self.assertFalse(price_sync.enabled())


class BrandsSizesAndRobots(unittest.TestCase):
    def test_brands_with_signs_are_found_in_links(self):
        for brand, link in (("Rom&nd", "https://www.tirabeauty.com/product/rom-nd-glasting-balm-3-5-g-123456"), ("Dr. Sheth's", "https://www.tirabeauty.com/product/dr-sheth-s-ceramide-cream-50-g-123456"),
                            ("L'Oreal Paris", "https://www.purplle.com/product/l-oreal-paris-serum-30-ml"), ("The Face Shop", "https://www.purplle.com/product/the-face-shop-rice-mask")):
            with self.subTest(brand=brand):
                self.assertTrue(P.brand_in(brand, P.slug_text(link)))
        self.assertFalse(P.brand_in("Rom&nd", P.slug_text("https://www.nykaa.com/roman-dial-watch/p/1")))
        self.assertEqual(P.coverage("Dr. Sheth's Ceramide Cream", "Dr. Sheth's", "dr sheth s ceramide cream 50 g"), (1.0, 1.0))

    def test_a_decimal_size_written_without_its_point_is_the_same_size(self):
        for size, words in (("0.16g", "brow pencil grey brown 016g qskwfy"), ("9.2ml", "hyper curl mascara very black 92ml abc"), ("3.9g", "creamy matte lipstick touch of spice 3 9 gm 3"),
                            ("6.1g", "city mini palette 61g xm")):
            ours = P.sizes_in(size)
            with self.subTest(size=size):
                self.assertEqual(P.size_verdict(ours, P.sizes_in(P.fix_sizes(words, ours))), "same")

    def test_another_size_stays_another_size(self):
        ours = P.sizes_in("9.2ml")
        for words in ("mascara 6 ml", "mascara 19 2 ml", "mascara 192ml"):
            with self.subTest(words=words):
                self.assertEqual(P.size_verdict(ours, P.sizes_in(P.fix_sizes(words, ours))), "different")
        self.assertEqual(P.fix_sizes("serum 50 ml", P.sizes_in("50ml")), "serum 50 ml")  # whole sizes are left alone

    def test_robots_rules(self):
        r = P.robots_rules("User-agent: Googlebot\nAllow: /\n\nUser-agent: *\nAllow: /\nDisallow: /*?q*\nDisallow: /search/\n")
        self.assertFalse(P.robots_allows(r, "https://www.tirabeauty.com/products?q=serum"))
        self.assertFalse(P.robots_allows(r, "https://www.nykaa.com/search/result"))
        self.assertTrue(P.robots_allows(r, "https://www.tirabeauty.com/product/serum-123456"))
        self.assertTrue(P.robots_allows([], "https://x.com/anything"))


class RunAndScreen(unittest.TestCase):
    """The run's reading step, what each shop column says, and your decisions: an in-memory database, no network."""
    P1 = {"product_id": "P1", "name": "Brand X Glow Serum", "brand": "Brand X", "category": "Face", "type": "Serum", "size": "30ml", "mrp": 1200.0, "price": 1000.0, "link": None, "barcode": None, "image": None}
    URL = "https://www.nykaa.com/brand-x-glow-serum/p/1"

    def setUp(self):
        self.old = (core.CON, R.price_catalogue, P.fetch, P.read, P.pause)
        core.CON = duckdb.connect(":memory:")
        R.price_init(core.CON)
        R.price_catalogue = lambda: [self.P1]
        P.pause = lambda: None
        self.answers = []  # what each page read gives, in order: a price, None for a sold-out page without one, or an exception
        P.fetch = lambda url, timeout=40: "page"
        P.read = self.read
        R._save_match("P1", "nykaa", url=self.URL, status="matched", method="sheet", confidence=1.0, matched_name=None)

    def tearDown(self):
        core.CON, R.price_catalogue, P.fetch, P.read, P.pause = self.old

    def read(self, site, body):
        a = self.answers.pop(0)
        if isinstance(a, Exception):
            raise a
        return {"name": "Brand X Glow Serum", "price": a, "mrp": 1200.0, "offer_price": None, "in_stock": a is not None, "stock_qty": None, "size": "30ml", "discount": None, "ean": None, "variants": []}

    def run_once(self, *answers):
        self.answers = list(answers)
        run = core.CON.execute("INSERT INTO price_runs (started_at, status, sites) VALUES (now(), 'running', 'nykaa') RETURNING run_id").fetchone()[0]
        R.PRICE_JOB.update(stop=False, sites={"nykaa": {"phase": "", "done": 0, "total": 0, "ok": 0, "failed": 0, "error": None}})
        R._run_site("nykaa", run, [self.P1], None)
        core.CON.execute("UPDATE price_runs SET status = 'done' WHERE run_id = ?", [run])
        return run

    def cell(self, site="nykaa"):
        return R._rows()[0]["sites"][site]

    def test_a_price_counts_even_when_out_of_stock(self):
        self.run_once(900.0)
        core.CON.execute("UPDATE price_snapshots SET in_stock = false")
        row = R._rows()[0]
        self.assertEqual((row["sites"]["nykaa"]["state"], row["cheapest_price"], row["gap"]), ("priced", 900.0, round(1000 / 900 - 1, 4)))
        self.assertNotIn("in_stock", row["sites"]["nykaa"])

    def test_the_last_price_stays_with_its_date_when_a_later_read_has_none(self):
        self.run_once(900.0)
        self.run_once(None)
        c = self.cell()
        self.assertEqual((c["state"], c["price"], c["earlier"]), ("priced", 900.0, True))

    def test_never_priced_is_not_available_and_never_looked_at_is_not_checked(self):
        self.assertEqual(self.cell()["state"], "unchecked")
        self.assertEqual(self.cell("tira")["state"], "unchecked")
        self.run_once(None)
        self.assertEqual(self.cell()["state"], "not_available")
        R._save_match("P1", "tira", url=None, status="none", method=None, confidence=0, matched_name=None)
        self.assertEqual(self.cell("tira")["state"], "not_available")

    def test_a_failed_page_is_tried_once_more(self):
        self.run_once(RuntimeError("network"), 950.0)
        self.assertEqual(self.cell()["price"], 950.0)
        self.assertEqual(core.CON.execute("SELECT count(*) FROM price_snapshots").fetchone()[0], 1)

    def test_a_dead_link_is_forgotten_and_searched_again(self):
        self.run_once(P.PageGone("HTTP 404"))
        m = R._matches()[("P1", "nykaa")]
        self.assertEqual((m["status"], m["url"], m["rejected"], m["checked_at"]), ("none", None, [self.URL], None))

    def test_a_stopped_run_is_continued_not_repeated(self):
        run = self.run_once(900.0)
        core.CON.execute("UPDATE price_runs SET status = 'stopped' WHERE run_id = ?", [run])
        self.run_once()  # nothing left to read: reading a page would fail on the empty answer list
        self.assertEqual(core.CON.execute("SELECT count(*) FROM price_snapshots").fetchone()[0], 1)

    def test_not_sold_here_and_rejecting_one_of_several(self):
        cands = [{"url": self.URL, "score": 0.7}, {"url": self.URL + "2", "score": 0.6}]
        R._save_match("P1", "nykaa", url=self.URL, status="review", method="name", confidence=0.7, matched_name=None, candidates=cands)
        R.prices_match(R.MatchIn(product_id="P1", site="nykaa", action="reject", url=self.URL))
        self.assertEqual(self.cell()["state"], "review")          # one suggestion is left
        R.prices_match(R.MatchIn(product_id="P1", site="nykaa", action="notsold"))
        self.assertEqual(self.cell()["state"], "not_available")
        self.assertEqual(len(R._matches()[("P1", "nykaa")]["rejected"]), 2)

    def test_changes_and_history_leave_out_a_rejected_page(self):
        self.run_once(900.0)
        self.run_once(800.0)
        self.assertEqual([(c["before_price"], c["now_price"]) for c in R._changes()], [(900.0, 800.0)])
        self.assertEqual([p["price"] for p in R.prices_history("P1")["points"]], [900.0, 800.0])  # one point per reading
        self.assertEqual(len({p["run"] for p in R.prices_history("P1")["points"]}), 2)
        R.prices_match(R.MatchIn(product_id="P1", site="nykaa", action="reject", url=self.URL))
        self.assertEqual(R._changes(), [])
        self.assertEqual(R.prices_history("P1")["points"], [])


if __name__ == "__main__":
    unittest.main()
