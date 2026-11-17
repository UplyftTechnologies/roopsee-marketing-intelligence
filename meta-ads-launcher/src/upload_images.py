"""Step 4 - upload each READY image once; the returned hash is stored so it is never uploaded twice."""
from __future__ import annotations

import json

from .common import LauncherError, Registry, Settings, image_path, ready_ads, sha256
from .meta_api import Meta


def run(s: Settings, meta: Meta, batch: str) -> None:
    _, ads = ready_ads(batch)
    reg = Registry(s, "upload_registry.json")
    by_digest = {v["sha256"]: v["meta_image_hash"] for v in reg.d.values() if v.get("uploaded") and v.get("sha256")}
    if not ads:
        print("upload: no READY ads in this batch")
        return
    for ad in ads:
        key = ad["ad_key"]
        if ad.get("image_hash"):  # an image already on Meta: nothing to upload, just record (and verify) its hash
            h = ad["image_hash"]
            if not meta.dry and reg.get(key, {}).get("meta_image_hash") != h:
                found = meta.get(f"{s.account}/adimages", hashes=json.dumps([h]), fields="hash,name").get("data", [])
                if not found:
                    raise LauncherError(f"{key}: image_hash {h} does not exist in ad account {s.account} (list yours: python run.py images)")
                reg.update(key, folder="(meta)", filename=found[0].get("name", ""), sha256="", meta_image_hash=h, uploaded=True, source="image_hash")
            print(f"  {key}: using existing Meta image hash {h}")
            continue
        p = image_path(ad)
        digest = sha256(p)
        if reg.get(key, {}).get("uploaded") and reg.get(key)["sha256"] == digest:
            print(f"  {key}: already uploaded")
            continue
        if digest in by_digest:  # identical file under another key: reuse the hash
            reg.update(key, folder=p.parent.name, filename=p.name, sha256=digest, meta_image_hash=by_digest[digest], uploaded=True)
            print(f"  {key}: identical image already on Meta, reusing its hash")
            continue
        with open(p, "rb") as f:
            res = meta.post(f"{s.account}/adimages", {}, files={p.name: (p.name, f.read())})
        h = next(iter(res["images"].values()))["hash"]
        if not meta.dry:
            reg.update(key, folder=p.parent.name, filename=p.name, sha256=digest, meta_image_hash=h, uploaded=True)
            by_digest[digest] = h
        print(f"  {key}: uploaded ({h})")
