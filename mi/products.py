"""Product catalogue and single-item offer estimates for Marketing Intelligence."""
import re
from decimal import Decimal, ROUND_HALF_UP
from math import isfinite

from .core import app
from .prices import price_catalogue


# Keep in step with the Roopsee checkout rules when offers change.
CART_COUPONS = {
    "NEW15": {"audience": "New customers, once per customer", "minimum": 299, "percent": 15},
    "GLO10": {"audience": "Returning customers, once per customer", "minimum": 500, "maximum": 1000, "percent": 10},
    "GLO15": {"audience": "Returning customers, once per customer", "minimum": 1000, "percent": 15},
    "FLAT300": {"audience": "Returning customers", "minimum": 999, "maximum": 1500, "flat": 300},
    "FLAT500": {"audience": "Returning customers", "minimum": 1499, "flat": 500},
}
APP_COUPON = {"code": "APP10", "audience": "First app order", "percent": 10}
BRAND_COUPON_MINIMUM = 1999
BRAND_COUPON_PERCENT = 10
BRAND_COUPONS = {
    "HARU10": ("Haru Haru Wonder", "Harharu Wonder", "Haruharu"),
    "TFS10": ("The Face Shop", "TFS"),
    "MEDICUBE10": ("Medicube",),
    "COSRX10": ("COSRX",),
    "AXISY10": ("AXIS-Y", "Axis Y"),
}


def _brand_key(brand: str) -> str:
    return re.sub(r"[^a-z0-9]", "", brand.lower())


BRAND_COUPON_BY_NAME = {_brand_key(name): code for code, names in BRAND_COUPONS.items() for name in names}
OFFER_RULES = {
    "effective_date": "2026-11-27",
    "new15_percent": CART_COUPONS["NEW15"]["percent"],
    "new15_min_subtotal": CART_COUPONS["NEW15"]["minimum"],
    "app_percent": APP_COUPON["percent"],
    "online_percent": 5,
    "coupons": [
        *({"code": code, **rule} for code, rule in CART_COUPONS.items()),
        APP_COUPON,
        *({"code": code, "brand": names[0], "minimum": BRAND_COUPON_MINIMUM, "percent": BRAND_COUPON_PERCENT}
          for code, names in BRAND_COUPONS.items()),
    ],
}
TEST_PRODUCT_ID = "RS/T/TE/ROOP/1/01"


def _paise(value: float | None) -> int | None:
    if value is None or not isfinite(value) or value <= 0:
        return None
    return int(Decimal(str(value)).scaleb(2).to_integral_value(rounding=ROUND_HALF_UP)) or None


def _percent_discount(paise: int, percent: int) -> int:
    # Round the discount half-up to a whole rupee.
    return ((paise * percent + 5000) // 10000) * 100


def offer_prices(mrp: float | None, selling_price: float | None, brand: str | None = None) -> dict:
    mrp_paise, selling = _paise(mrp), _paise(selling_price)
    prices = {
        "mrp": mrp_paise / 100 if mrp_paise is not None else None,
        "selling_price": selling / 100 if selling is not None else None,
        "off_mrp": (mrp_paise - selling) / mrp_paise if mrp_paise is not None and selling is not None else None,
        "new15_eligible": None,
        "new15_price": None,
        "pay_online_price": None,
        "app_price": None,
        "coupon_discounts": {},
    }
    if selling is None:
        return prices

    discounts = {}
    for code, rule in CART_COUPONS.items():
        maximum = rule.get("maximum")
        if selling < rule["minimum"] * 100 or (maximum is not None and selling >= maximum * 100):
            continue
        discounts[code] = rule["flat"] * 100 if "flat" in rule else _percent_discount(selling, rule["percent"])

    eligible = "NEW15" in discounts
    after_new15 = selling - discounts.get("NEW15", 0)
    app_discount = _percent_discount(after_new15, APP_COUPON["percent"])
    discounts[APP_COUPON["code"]] = app_discount
    after_app = after_new15 - app_discount

    brand_coupon = BRAND_COUPON_BY_NAME.get(_brand_key(brand or ""))
    if brand_coupon and selling >= BRAND_COUPON_MINIMUM * 100:
        discounts[brand_coupon] = _percent_discount(selling, BRAND_COUPON_PERCENT)

    online_percent = OFFER_RULES["online_percent"]
    prices.update(
        new15_eligible=eligible,
        new15_price=after_new15 / 100 if eligible else None,
        pay_online_price=(after_new15 - _percent_discount(after_new15, online_percent)) / 100,
        app_price=(after_app - _percent_discount(after_app, online_percent)) / 100,
        coupon_discounts={code: discount / 100 for code, discount in discounts.items()},
    )
    return prices


def _image_url(images: str | None) -> str | None:
    urls = re.split(r"\s*\|\s*|[,\s]+(?=https?://)", (images or "").strip())
    return next((url for url in urls if url.startswith(("https://", "http://"))), None)


@app.get("/api/products")
def products_catalogue():
    rows = []
    for product in price_catalogue():
        product_id = product["product_id"].strip()
        if not product_id or product_id == TEST_PRODUCT_ID:
            continue
        rows.append({
            "product_id": product_id,
            "name": product["name"],
            "brand": product["brand"],
            "category": product["category"],
            "type": product["type"],
            "size": product["size"],
            "image": _image_url(product["image"]),
            **offer_prices(product["mrp"], product["price"], product["brand"]),
        })
    return {"rules": OFFER_RULES, "rows": rows}
