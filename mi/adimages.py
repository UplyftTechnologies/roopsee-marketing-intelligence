"""Keep a copy of each Meta ad's picture on this computer (data/ad_images/<ad id>.jpg).

Meta's picture links expire after a few days, so the Ads & landing pages tab would lose its ad images. The copy is made right after a Meta sync,
and only for ads that do not have one yet. Nothing is sent to Meta: the pictures are public files on Meta's content servers.
"""
import re

import requests

from .config import DATA_DIR

AD_DIR = DATA_DIR / "ad_images"
MAX_BYTES = 5_000_000


def cache(con) -> dict:
    """Download the picture of every synced ad that has none yet. Returns how many were saved / failed / already there."""
    AD_DIR.mkdir(parents=True, exist_ok=True)
    rows = con.execute("SELECT entity_id, coalesce(thumbnail_url, image_url) FROM raw_meta_entities WHERE entity_type = 'ad' AND coalesce(thumbnail_url, image_url) IS NOT NULL").fetchall()
    out = {"saved": 0, "failed": 0, "already": 0}
    for ad_id, url in rows:
        f, tag_file = AD_DIR / f"{ad_id}.jpg", AD_DIR / f"{ad_id}.size"
        m = re.search(r"p(\d+)x\d+", url)
        size = int(m.group(1)) if m else 0  # Meta names the picture size in the link; a bigger one replaces a smaller copy
        have = int(tag_file.read_text() or 0) if tag_file.exists() else -1
        if f.exists() and f.stat().st_size > 0 and have >= size:
            out["already"] += 1
            continue
        try:
            r = requests.get(url, timeout=30)
            if r.ok and r.content and len(r.content) <= MAX_BYTES and r.headers.get("content-type", "").startswith("image"):
                f.write_bytes(r.content)
                tag_file.write_text(str(size))
                out["saved"] += 1
            else:
                out["failed"] += 1
        except requests.RequestException:
            out["failed"] += 1
    return out
