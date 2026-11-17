"""Step 7 - ad creatives: uploaded image hash + copy + destination + UTM tags."""
from __future__ import annotations

from .common import LauncherError, Registry, Settings, account_cfg, ready_ads, url_tags
from .ensure import ensure
from .meta_api import Meta


def payload(ad: dict, image_hash: str, batch_id: str, s: Settings, acc: dict) -> dict:
    link = {"image_hash": image_hash, "link": ad["destination"], "message": ad["primary_text"], "name": ad["headline"],
            "call_to_action": {"type": ad["cta"], "value": {"link": ad["destination"]}}}
    if ad.get("description"):
        link["description"] = ad["description"]
    story = {"page_id": s.page_id, "link_data": link}
    if s.instagram_id:
        story["instagram_user_id"] = s.instagram_id
    return {"name": ad["ad_key"], "object_story_spec": story, "url_tags": url_tags(ad, batch_id, acc)}


def run(s: Settings, meta: Meta, batch: str, validate_only=False) -> None:
    b, ads = ready_ads(batch)
    acc, up, ent = account_cfg(), Registry(s, "upload_registry.json"), Registry(s, "entity_registry.json")
    for ad in ads:
        k = ad["ad_key"]
        h = ad.get("image_hash") or up.get(k, {}).get("meta_image_hash")
        if not h:
            if not (meta.dry or validate_only):
                raise LauncherError(f"{k}: image not uploaded yet - run upload first")
            h = "DRYHASH"
        # creatives cannot be looked up by name on Meta, so only our own registry prevents duplicates here
        ensure(s, meta, ent, f"creative:{k}", "adcreatives", k, payload(ad, h, b["batch_id"], s, acc), validate_only, lookup=False)
