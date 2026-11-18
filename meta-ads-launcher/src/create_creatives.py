"""Step 7 - ad creatives: uploaded image hash + copy + destination + UTM tags."""
from __future__ import annotations

from .common import LauncherError, Registry, Settings, account_cfg, clean_extra, deep_merge, ready_ads, url_tags
from .ensure import ensure
from .meta_api import Meta


def spec_payload(ad: dict, batch_id: str, s: Settings, acc: dict, lenient: bool = False, stand_in: dict | None = None) -> dict:
    """An ad that carries a whole creative (carousel, video, catalog, dynamic, existing post...) copied from Meta or imported as JSON."""
    from . import media
    from .spec_clean import clean_creative
    spec, _ = clean_creative(ad["creative_spec"], s.page_id, s.instagram_id)
    if media.files_in(spec):
        spec = media.resolve(spec, s, lenient=lenient, stand_in=stand_in)
    out = {"name": ad["ad_key"], **spec}
    out.setdefault("url_tags", url_tags({"ad_key": ad["ad_key"]}, batch_id, acc))
    extra, _ = clean_extra(ad.get("extra"))
    return deep_merge(out, extra)


def payload(ad: dict, image_hash: str, batch_id: str, s: Settings, acc: dict) -> dict:
    if ad.get("creative_spec"):
        return spec_payload(ad, batch_id, s, acc)
    link = {"image_hash": image_hash, "link": ad["destination"], "message": ad["primary_text"], "name": ad["headline"],
            "call_to_action": {"type": ad["cta"], "value": {"link": ad["destination"]}}}
    if ad.get("description"):
        link["description"] = ad["description"]
    story = {"page_id": s.page_id, "link_data": link}
    if s.instagram_id:
        story["instagram_user_id"] = s.instagram_id
    link_extra, _ = clean_extra(ad.get("link_extra"))  # extra fields inside link_data (Meta's names), e.g. caption
    story["link_data"] = deep_merge(story["link_data"], link_extra)
    out = {"name": ad["ad_key"], "object_story_spec": story, "url_tags": url_tags(ad, batch_id, acc)}
    extra, _ = clean_extra(ad.get("extra"))  # extra fields on the creative itself, e.g. degrees_of_freedom_spec
    return deep_merge(out, extra)


def run(s: Settings, meta: Meta, batch: str, validate_only=False) -> None:
    b, ads = ready_ads(batch)
    acc, up, ent = account_cfg(), Registry(s, "upload_registry.json"), Registry(s, "entity_registry.json")
    for ad in ads:
        k = ad["ad_key"]
        h = ad.get("image_hash") or up.get(k, {}).get("meta_image_hash")
        if ad.get("creative_spec"):
            h = "SPEC"
        if not h:
            if not (meta.dry or validate_only):
                raise LauncherError(f"{k}: image not uploaded yet - run upload first")
            h = "DRYHASH"
        # creatives cannot be looked up by name on Meta, so only our own registry prevents duplicates here
        pl = spec_payload(ad, b["batch_id"], s, acc, lenient=bool(meta.dry or validate_only)) if ad.get("creative_spec") else payload(ad, h, b["batch_id"], s, acc)
        ensure(s, meta, ent, f"creative:{k}", "adcreatives", k, pl, validate_only, lookup=False)
