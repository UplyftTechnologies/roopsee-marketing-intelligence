"""Make a creative that was READ from Meta safe to CREATE again: drop what Meta fills in by itself (ids, tracking, expiring image URLs),
point it at this environment's Page / Instagram account, and describe what kind of ad it is in plain words."""
from __future__ import annotations

import copy
from typing import Any

# top-level keys of a creative that Meta computes or that must not be copied
CREATIVE_DROP = {"id", "name", "effective_object_story_id", "call_to_action_type", "status", "account_id", "tracking_specs", "thumbnail_url", "image_url",
                 "object_url", "effective_instagram_story_id", "effective_instagram_media_id", "instagram_permalink_url", "created_time", "updated_time"}
SPEC_KEYS = ("object_story_spec", "asset_feed_spec", "object_story_id", "degrees_of_freedom_spec", "platform_customizations", "interactive_components_spec",
             "product_set_id", "dynamic_ad_voice", "url_tags", "template_url_spec", "branded_content", "contextual_multi_ads", "creative_sourcing_spec", "authorization_category",
             "link_url", "title", "body", "image_hash", "video_id", "carousel_ad_link", "ad_disclaimer_spec")


def _strip_label_ids(o: Any) -> Any:
    """adlabels / *_label objects carry ids that only exist on the source ad; Meta wants just the names when creating."""
    if isinstance(o, dict):
        out = {}
        for k, v in o.items():
            if k == "adlabels" and isinstance(v, list):
                out[k] = [{"name": x.get("name")} for x in v if isinstance(x, dict) and x.get("name")]
            elif k.endswith("_label") and isinstance(v, dict):
                out[k] = {"name": v.get("name")}
            else:
                out[k] = _strip_label_ids(v)
        return out
    if isinstance(o, list):
        return [_strip_label_ids(x) for x in o]
    return o


def _drop_urls(o: Any) -> Any:
    """video_data.image_url / thumbnail_url are temporary links; the image_hash beside them is what lasts."""
    if isinstance(o, dict):
        has_hash = "image_hash" in o
        out = {}
        for k, v in o.items():
            if (k == "thumbnail_url" or (k == "image_url" and has_hash)) and not str(v).startswith(("thumb:", "file:")):
                continue
            out[k] = _drop_urls(v)
        return out
    if isinstance(o, list):
        return [_drop_urls(x) for x in o]
    return o


def clean_creative(raw: dict, page_id: str | None = None, instagram_id: str | None = None) -> tuple[dict, list[str]]:
    """Returns (spec ready to create, notes about what was dropped or switched)."""
    notes: list[str] = []
    spec = {k: copy.deepcopy(v) for k, v in raw.items() if k not in CREATIVE_DROP and v not in (None, "", [], {})}
    for k in list(spec):
        if k not in SPEC_KEYS:
            notes.append(f"dropped creative.{k}")
            spec.pop(k)
    dropped = [k for k in raw if k in CREATIVE_DROP and raw[k] not in (None, "", [], {}) and k not in ("id", "name")]
    if dropped:
        notes.append("left out (Meta fills these in itself): " + ", ".join(sorted(dropped)))
    spec = _drop_urls(_strip_label_ids(spec))
    oss = spec.get("object_story_spec")
    if isinstance(oss, dict):
        if page_id:
            oss["page_id"] = page_id
        if instagram_id:
            oss["instagram_user_id"] = instagram_id
        else:
            oss.pop("instagram_user_id", None)
        # catalog / dynamic ads: Meta stores them as template_data on read but they are created from the same shape; nothing to change.
    elif spec.get("asset_feed_spec") and not spec.get("object_story_id"):  # an Advantage+ creative built here: the story only names the Page
        spec["object_story_spec"] = {k: v for k, v in (("page_id", page_id), ("instagram_user_id", instagram_id)) if v}
    elif raw.get("effective_object_story_id") and not spec.get("asset_feed_spec"):
        spec["object_story_id"] = raw["effective_object_story_id"]  # an ad built on an existing post
        notes.append("this ad uses an existing post, so it is reused as is (its text and image cannot be edited)")
    if "object_story_id" in spec and "object_story_spec" in spec:
        spec.pop("object_story_id")
    return spec, notes


def describe(spec: dict) -> dict:
    """A plain-words summary of a creative: what format it is, the texts, the link, the images."""
    oss = spec.get("object_story_spec") or {}
    afs = spec.get("asset_feed_spec") or {}
    kind, texts, titles, link, hashes, videos, cards = "Ad", [], [], "", [], [], 0
    ld = oss.get("link_data") or {}
    td = oss.get("template_data") or {}
    vd = oss.get("video_data") or {}
    if spec.get("object_story_id") and not oss and not afs:
        kind = "Existing post"
    elif td:
        kind = "Catalog / product ads"
        cards = len(td.get("child_attachments") or [])
        texts = [td.get("message")] if td.get("message") else []
        link = td.get("link", "")
    elif ld.get("child_attachments"):
        kind = "Carousel"
        cards = len(ld["child_attachments"])
        texts = [ld.get("message")] if ld.get("message") else []
        link = ld.get("link", "")
        hashes = [c.get("image_hash") for c in ld["child_attachments"] if c.get("image_hash")]
        titles = [c.get("name") for c in ld["child_attachments"] if c.get("name")]
    elif vd:
        kind = "Video"
        texts = [vd.get("message")] if vd.get("message") else []
        titles = [vd.get("title")] if vd.get("title") else []
        link = ((vd.get("call_to_action") or {}).get("value") or {}).get("link", "")
        videos = [vd.get("video_id")] if vd.get("video_id") else []
        if vd.get("image_hash"):
            hashes = [vd["image_hash"]]
    elif ld:
        kind = "Single image"
        texts = [ld.get("message")] if ld.get("message") else []
        titles = [ld.get("name")] if ld.get("name") else []
        link = ld.get("link", "")
        if ld.get("image_hash"):
            hashes = [ld["image_hash"]]
    if afs:
        opt = afs.get("optimization_type")
        if opt == "DEGREES_OF_FREEDOM" or afs.get("bodies") or afs.get("titles"):
            kind = ("Dynamic creative" if opt == "DEGREES_OF_FREEDOM" else "Advantage+ creative") + (" (" + kind.lower() + ")" if kind not in ("Ad",) else "")
        elif kind == "Ad":
            kind = "Advantage+ creative"
        texts = texts or [x.get("text") for x in afs.get("bodies", []) if x.get("text")]
        titles = titles or [x.get("text") for x in afs.get("titles", []) if x.get("text")]
        hashes = hashes or [x.get("hash") for x in afs.get("images", []) if x.get("hash")]
        videos = videos or [x.get("video_id") for x in afs.get("videos", []) if x.get("video_id")]
        link = link or next((x.get("website_url") for x in afs.get("link_urls", []) if x.get("website_url")), "")
    return {"kind": kind, "texts": texts[:3], "text_count": len(texts), "titles": titles[:3], "title_count": len(titles), "link": link,
            "image_hashes": [h for h in dict.fromkeys(hashes) if h][:10], "video_ids": [v for v in dict.fromkeys(videos) if v][:10], "cards": cards}
