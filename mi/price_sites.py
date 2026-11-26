"""Competitor sites for the Price intelligence tab: how to read a public product page, where the product lists (sitemaps) are, and how to match a product.

Only PUBLIC pages are read: product pages and the sitemaps each site publishes in its robots.txt. No search pages (Tira's robots.txt forbids them),
no logins, no internal APIs. Pages are fetched with Scrapling's Fetcher (a browser-like connection), one at a time per site with a pause in between.

Where each site keeps its numbers (checked in the Nov 2026 feasibility test; if a site changes its pages, its reader below is the place to fix):
  nykaa    window.__PRELOADED_STATE__ .productPage.product: offerPrice (regular price), mrp, inStock, quantity, packSize;
           cohortSaleTemplate.price is an offer for some customers only (shown as a note, never compared). nykaaman.com blocks automated
           reads, but its products are the same ids on nykaa.com, so those links are read there.
  tira     window.APP_DATA .reduxData.catalog.product_meta: price.effective (price) / price.marked (MRP), sellable, sizes[].is_available /
           quantity, discount ("10% OFF"); product_details: name, attributes["pack-size"]. The page also carries placeholder template
           products (e.g. "Hess Inc", ₹1,199): never read prices from anywhere else.
  purplle  JSON-LD Product: offers.price / availability, sku "PPLB<barcode>"; MRP from the page script (mrp:"599",ourPrice:467), which also keeps
           the price of a sold-out product.
"""
from __future__ import annotations

import json
import logging
import random
import re
import time
import unicodedata

SITES = ("nykaa", "tira", "purplle")
LABEL = {"nykaa": "Nykaa", "tira": "Tira", "purplle": "Purplle"}
HOSTS = {"nykaa": ("www.nykaa.com", "nykaa.com"), "tira": ("www.tirabeauty.com", "tirabeauty.com"), "purplle": ("www.purplle.com", "purplle.com")}
SITEMAPS = {  # where each site lists its product pages (from its robots.txt)
    "nykaa": "https://www.nykaa.com/sitemap-v2/sitemap-products-index.xml",
    "tira": "https://www.tirabeauty.com/sitemap.xml",
    "purplle": "https://www.purplle.com/sitemap/products/product-reviews.xml",
}
PAUSE = (3.0, 4.5)  # seconds between two pages of the same site (random in this range)


class Blocked(Exception):
    """The site refused us (403 / 429): back off; several in a row stop that site for this run."""


class PageGone(Exception):
    """404 / 410: the product page no longer exists."""


# ---------------------------------------------------------------- robots.txt
_ROBOTS: dict = {}  # host -> its rules, read once per server run


def robots_rules(text: str) -> list[tuple[bool, str]]:
    """(allowed, path pattern) pairs of the `User-agent: *` group."""
    rules, star, in_rules = [], False, False
    for raw in str(text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if ":" not in line:
            continue
        k, v = (x.strip() for x in line.split(":", 1))
        k = k.lower()
        if k == "user-agent":
            if in_rules:
                star, in_rules = False, False
            star = star or v == "*"
        elif k in ("allow", "disallow"):
            in_rules = True
            if star and v:
                rules.append((k == "allow", v))
    return rules


def robots_allows(rules: list, url: str) -> bool:
    """The longest matching rule wins (Allow wins a tie); * matches anything and a final $ means the end of the address."""
    path = re.sub(r"^https?://[^/]+", "", url) or "/"
    best = None
    for allow, rule in rules:
        rx = re.escape(rule).replace(r"\*", ".*")
        if rx.endswith(r"\$"):
            rx = rx[:-2] + "$"
        if re.match(rx, path) and (best is None or len(rule) > best[1] or (len(rule) == best[1] and allow)):
            best = (allow, len(rule))
    return True if best is None else best[0]


def _allowed(url: str, timeout: int) -> bool:
    m = re.match(r"(https?://[^/]+)", url)
    if not m or url.endswith("/robots.txt"):
        return True
    host = m.group(1)
    if host not in _ROBOTS:
        try:
            _ROBOTS[host] = robots_rules(_get(f"{host}/robots.txt", timeout))
        except PageGone:
            _ROBOTS[host] = []  # the site has no robots.txt
        except Exception:
            return True  # could not be read this time: the page request itself will show whether the site is reachable; asked again next time
    return robots_allows(_ROBOTS[host], url)


# ---------------------------------------------------------------- fetching
def fetch(url: str, timeout: int = 40) -> str:
    """The page body, if the site's robots.txt allows it. Raises Blocked / PageGone, or RuntimeError for anything else (network, 5xx)."""
    if not _allowed(url, timeout):
        raise RuntimeError("the site's robots.txt does not allow this page")
    return _get(url, timeout)


def _get(url: str, timeout: int) -> str:
    from scrapling.fetchers import Fetcher  # imported here so the dashboard starts even without Scrapling installed
    logging.getLogger("scrapling").setLevel(logging.WARNING)
    last = None
    for attempt in range(2):
        try:
            p = Fetcher.get(url, impersonate="chrome", stealthy_headers=True, timeout=timeout)
        except Exception as e:  # network trouble: one retry after a short wait
            last = f"{type(e).__name__}: {str(e)[:120]}"
            time.sleep(5)
            continue
        if p.status in (403, 429):
            raise Blocked(f"HTTP {p.status}")
        if p.status in (404, 410):
            raise PageGone(f"HTTP {p.status}")
        if p.status >= 500:
            last = f"HTTP {p.status}"
            time.sleep(5)
            continue
        body = p.body
        return body.decode("utf-8", "ignore") if isinstance(body, (bytes, bytearray)) else str(body)
    raise RuntimeError(last or "fetch failed")


def pause() -> None:
    time.sleep(random.uniform(*PAUSE))


def site_of(url: str) -> str | None:
    m = re.match(r"https?://([^/]+)", str(url or ""))
    host = (m.group(1).lower() if m else "")
    if host in ("www.nykaaman.com", "nykaaman.com"):
        return "nykaa"
    return next((s for s, hs in HOSTS.items() if host in hs), None)


def canonical_url(url: str) -> str | None:
    """A product link as we read it: https, the site's own host, no query string; nykaaman.com links become the same product on nykaa.com."""
    u = str(url or "").strip()
    s = site_of(u)
    if not s:
        return None
    u = re.sub(r"[?#].*$", "", u)
    u = re.sub(r"^https?://(www\.)?nykaaman\.com", "https://www.nykaa.com", u)
    u = re.sub(r"^http://", "https://", u)
    if s == "purplle":
        u = re.sub(r"/reviews/?$", "", u)
    return u


# ---------------------------------------------------------------- reading a product page
def _num(v):
    try:
        f = float(str(v).replace(",", "").strip())
        return f if f > 0 else None
    except (TypeError, ValueError):
        return None


def _assigned_json(body: str, var: str):
    m = re.search(r"window\." + re.escape(var) + r"\s*=\s*", body)
    if not m:
        return None
    try:
        return json.JSONDecoder().raw_decode(body[m.end():])[0]
    except ValueError:
        return None


def _ld_product(body: str) -> dict:
    for blk in re.findall(r"<script[^>]+application/ld\+json[^>]*>(.*?)</script>", body, re.S):
        try:
            d = json.loads(blk)
        except ValueError:
            continue
        for x in (d if isinstance(d, list) else [d]):
            if isinstance(x, dict) and "offers" in x:
                return x
    return {}


def read_nykaa(body: str) -> dict:
    st = _assigned_json(body, "__PRELOADED_STATE__")
    p = ((st or {}).get("productPage") or {}).get("product") or {}
    if not p:
        raise ValueError("Nykaa page layout not recognised (no product data)")
    def one(x):
        price, offer = _num(x.get("offerPrice")), _num((x.get("cohortSaleTemplate") or {}).get("price"))
        return {"price": price, "mrp": _num(x.get("mrp")), "offer_price": offer if offer and price and offer < price else None,
                "in_stock": bool(x.get("inStock")), "stock_qty": x.get("quantity"), "size": x.get("packSize") or x.get("variantName")}
    # a page sells every size of the product: the headline price is the DEFAULT size (often the smallest), so each size is kept and the
    # caller picks the one that matches ours (fit_size)
    variants = [one(v) for v in (p.get("variants") or []) if v.get("packSize") or v.get("variantName")]
    return {"name": p.get("name"), **one(p), "discount": None, "ean": None, "variants": variants}


def read_tira(body: str) -> dict:
    d = _assigned_json(body, "APP_DATA")
    cat = (((d or {}).get("reduxData") or {}).get("catalog")) or {}
    pm, pd = cat.get("product_meta") or {}, cat.get("product_details") or {}
    if not pd:
        raise ValueError("Tira page layout not recognised (no product data)")
    pr = pm.get("price") or {}
    sizes = pm.get("sizes") or []
    in_stock = bool(pm.get("sellable")) and any(s.get("is_available") for s in sizes)
    attrs = pd.get("attributes") or {}
    return {"name": pd.get("name"), "price": _num((pr.get("effective") or {}).get("min")), "mrp": _num((pr.get("marked") or {}).get("min")), "offer_price": None,
            "in_stock": in_stock, "stock_qty": sum(int(s.get("quantity") or 0) for s in sizes) or None, "size": attrs.get("pack-size"),
            "discount": pm.get("discount") or None, "ean": None}


def read_purplle(body: str) -> dict:
    ld = _ld_product(body)
    if not ld:
        raise ValueError("Purplle page layout not recognised (no product data)")
    off = ld.get("offers") or {}
    off = off[0] if isinstance(off, list) and off else off
    in_stock = "instock" in str(off.get("availability") or "").lower()
    m = re.search(r"\bmrp:\s*\"?([\d.]+)\"?\s*,\s*ourPrice:\s*\"?([\d.]+)", body)
    sku = str(ld.get("sku") or "")
    ean = re.match(r"PPLB(\d{8,14})", sku)
    price = (_num(off.get("price")) if in_stock else None) or (_num(m.group(2)) if m else None)  # sold out: structured data says 0, the script keeps it
    return {"name": ld.get("name"), "price": price, "mrp": _num(m.group(1)) if m else None, "offer_price": None,
            "in_stock": in_stock, "stock_qty": None, "size": None, "discount": None, "ean": ean.group(1) if ean else None}


READERS = {"nykaa": read_nykaa, "tira": read_tira, "purplle": read_purplle}


def fit_size(got: dict, ours: set) -> tuple[dict, str | None]:
    """The reading for OUR size: the matching size variant when the page has several (Nykaa); else the page itself.
    Returns (reading, problem): problem says why it must not be compared (the page only sells other sizes), or None."""
    variants = got.get("variants") or []
    if variants and ours:
        same = [v for v in variants if size_verdict(ours, sizes_in(v["size"])) == "same"]
        if same:
            v = same[0]
            return {**got, **v}, None
        if all(size_verdict(ours, sizes_in(v["size"])) == "different" for v in variants):
            return got, "sizes on the page: " + ", ".join(str(v["size"]) for v in variants)
        return got, None
    page = sizes_in(got.get("size")) or sizes_in(got.get("name"))
    if size_verdict(ours, page) == "different":
        return got, f"size on the page: {got.get('size') or next(iter(page))[0]}"
    return got, None


def read(site: str, body: str) -> dict:
    out = READERS[site](body)
    if out["in_stock"] and not out["price"]:
        raise ValueError(f"{LABEL[site]} page shows the product in stock but no price was found")
    return out


# ---------------------------------------------------------------- sitemaps (the list of every product page of a site)
def sitemap_urls(site: str, progress=lambda m: None, stop=lambda: False) -> list[str]:
    """Every product page a site lists in its sitemaps (canonical links)."""
    def locs(x):
        return re.findall(r"<loc>\s*([^<]+?)\s*</loc>", x)
    idx = locs(fetch(SITEMAPS[site], timeout=90))
    if site == "purplle":
        return sorted({canonical_url(u) for u in idx if "/product/" in u} - {None})
    files = [u for u in idx if ("sitemap-products-" in u if site == "nykaa" else "/sitemap/products/" in u)]
    out = set()
    for i, f in enumerate(files, 1):
        if stop():
            break
        progress(f"reading the {LABEL[site]} product list ({i}/{len(files)})")
        pause()
        out.update(u for u in (canonical_url(x) for x in locs(fetch(f, timeout=120))) if u and ("/p/" in u if site == "nykaa" else "/product/" in u))
    return sorted(out)


# ---------------------------------------------------------------- matching
STOP = {"the", "and", "for", "with", "of", "a", "an", "in", "to", "on", "by", "new", "pack", "set", "combo", "free", "off", "buy", "get", "online", "india"}
UNIT = {"ml": "ml", "l": "ml", "ltr": "ml", "litre": "ml", "liter": "ml", "g": "g", "gm": "g", "gms": "g", "gram": "g", "grams": "g", "kg": "g", "mg": "mg",
        "oz": "oz", "pc": "pc", "pcs": "pc", "piece": "pc", "pieces": "pc", "n": "pc", "sheet": "pc", "sheets": "pc", "pad": "pc", "pads": "pc"}
FACTOR = {"l": 1000, "ltr": 1000, "litre": 1000, "liter": 1000, "kg": 1000}
SIZE_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(" + "|".join(sorted(UNIT, key=len, reverse=True)) + r")\b")


def norm(s) -> str:
    s = unicodedata.normalize("NFKD", str(s or "")).encode("ascii", "ignore").decode().lower()
    s = s.replace("&", " and ").replace("'", "").replace("’", "")
    s = re.sub(r"(\d)\s*%", r"\1 pct", s)
    s = re.sub(r"\b(percentage|percent|per cent)\b", "pct", s)  # "8%" (us) = "8 percentage" (Purplle)
    return re.sub(r"\s+", " ", re.sub(r"[^a-z0-9.]+", " ", s)).strip()


def sizes_in(text) -> set:
    """Sizes written in a text, as (value in base unit, unit): '30ml' / '30 ml' -> (30.0, 'ml'); '1.2g' -> (1.2, 'g'); '1 l' -> (1000.0, 'ml')."""
    out = set()
    for v, u in SIZE_RE.findall(norm(text).replace(" .", ".")):
        out.add((round(float(v) * FACTOR.get(u, 1), 2), UNIT[u]))
    return out


def size_verdict(ours: set, theirs: set) -> str:
    """'same', 'different' or 'unknown' (a size missing on either side)."""
    if not ours or not theirs:
        return "unknown"
    for v, u in ours:
        for w, t in theirs:
            if u == t and abs(v - w) <= max(0.02 * v, 0.5 if u in ("ml", "g") else 0):
                return "same"
    return "different" if {u for _, u in ours} & {u for _, u in theirs} else "unknown"


def slug_text(url: str) -> str:
    """The words of a product link: nykaa /<slug>/p/<id>, tira /product/<slug>-<id>, purplle /product/<slug>."""
    path = re.sub(r"^https?://[^/]+", "", url)
    m = re.match(r"/([^/]+)/p/\d+", path) or re.match(r"/product/([^/?#]+)", path)
    slug = m.group(1) if m else path
    if "tirabeauty" in url:
        slug = re.sub(r"-\d{5,}$", "", slug)
    return norm(slug.replace("-", " "))


def tokens(text) -> set:
    return {t for t in norm(text).split() if t not in STOP and not (t.isdigit() and len(t) > 4)}


def _alnum(text) -> str:
    return re.sub(r"[^a-z0-9]", "", str(text))


def brand_keys(brand) -> list[str]:
    """The ways a brand can be spelled inside a link, letters and digits only."""
    base = re.sub(r"(?i)^the\s+", "", str(brand or ""))
    forms = (base, base.replace("&", ""), base.replace("&", " n "))
    return sorted({_alnum(norm(f)) for f in forms} - {""})


def _brand_words(brand) -> set:
    b = str(brand or "")
    forms = (b, re.sub(r"['\u2019&.]", " ", b))
    return {w for f in forms for w in norm(f).replace(".", " ").split()} | set(norm(b).split())


def fix_sizes(words: str, ours: set) -> str:
    """A link drops the decimal point of a size: our 9.2 ml is written 92ml or 9-2-ml. Put the point back (only for OUR sizes),
    so the page is not thrown out as another size. The page itself is still checked when it is opened."""
    for v, u in ours:
        if v == int(v):
            continue
        whole, part = f"{v:g}".split(".")
        units = "|".join(sorted((k for k, x in UNIT.items() if x == u), key=len, reverse=True))
        words = re.sub(rf"(?<![\d.])(?:{whole} {part}|{whole}{part}) ?({units})\b", rf"{v:g} \1", words)
    return words


def coverage(our_name: str, brand: str, their_text: str) -> tuple[float, float]:
    """(share of OUR name's words found in theirs, share of THEIR words found in ours). Brand and sizes are left out (compared separately);
    plain numbers stay, so "8% toner" and "10% toner" differ. Our sheet names often add a description ("... For Oily Skin"), so the second
    share is the telling one: when every word of their title is in our name, it is the same product (given the same brand and size)."""
    b = _brand_words(brand)
    sizeish = re.compile(r"\d+(\.\d+)?(" + "|".join(UNIT) + r")?")

    def keep(t):
        return t not in b and t not in UNIT and not (sizeish.fullmatch(t) and not t.isdigit())
    def words(x):  # sizes go as a whole ("30 ml", "(50g)"), so their number is not left behind as a word
        return {t for t in tokens(SIZE_RE.sub(" ", norm(x))) if keep(t)}
    ours, theirs = words(our_name), words(their_text)
    if not ours or not theirs:
        return 0.0, 0.0

    def same(a, pool):  # equal, or the same word with a different ending (moisturising / moisturizing, serum / serums)
        return a in pool or (len(a) >= 6 and any(len(x) >= 6 and x[:6] == a[:6] for x in pool))
    return round(sum(same(t, theirs) for t in ours) / len(ours), 3), round(sum(same(t, ours) for t in theirs) / len(theirs), 3)


def score(our_name: str, brand: str, their_text: str) -> float:
    """0..1 name similarity: the better of the two coverages, weighted towards the one with the fewest unexplained words."""
    a, b = coverage(our_name, brand, their_text)
    return round(max(0.75 * a + 0.25 * b, 0.4 * a + 0.6 * b), 3)


def same_product(our_name: str, brand: str, their_name: str, size: str) -> bool:
    """Sure enough to match without asking: same brand (checked by the caller), the SAME known size, and either nearly all of our name in theirs,
    or every word of their title in our name (with at least half of ours)."""
    a, b = coverage(our_name, brand, their_name)
    return size == "same" and ((a >= 0.85 and b >= 0.6) or (b >= 0.95 and a >= 0.5))


def brand_in(brand: str, their_text: str) -> bool:
    text = _alnum(their_text)
    return any(k in text for k in brand_keys(brand))
