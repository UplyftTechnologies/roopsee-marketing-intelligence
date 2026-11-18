"""Build ads from scratch in the formats beyond one image: video, carousel, an existing post, Advantage+ (many texts and images) and catalog ads.
`compile_ad` turns the builder's friendly ad card into the creative Meta expects; local files are referenced as "file:media/..." and uploaded at create time."""
from __future__ import annotations

import hashlib
import json
import re
import time
from urllib.parse import urlparse

from fastapi import APIRouter, File, HTTPException, UploadFile
from fastapi.responses import FileResponse

from src import media
from src.common import CTAS, ROOT, Settings, jload
from src.meta_api import Meta, MetaError

router = APIRouter()
KINDS = ("video", "carousel", "post", "dynamic", "catalog")
SAFE = re.compile(r"[^A-Za-z0-9._-]+")
MEDIA_DIR = ROOT / "media"


def _ref(x) -> tuple[str, str]:
    """A picked media item -> (kind, value). {"file": "media/x.jpg"} / {"hash": h} / {"video_id": id}"""
    if not isinstance(x, dict):
        return "", ""
    if x.get("file"):
        return "file", str(x["file"])
    if x.get("hash"):
        return "hash", str(x["hash"])
    if x.get("video_id"):
        return "video", str(x["video_id"])
    return "", ""


def _img(x, where, errs):
    k, v = _ref(x)
    if k == "file" and media.kind_of(v) == "image":
        return f"file:{v}"
    if k == "hash" and re.fullmatch(r"[0-9a-f]{32}", v):
        return v
    errs.append(f"{where}: add an image.")
    return ""


def _vid(x, where, errs):
    """returns (video_id or file ref, thumbnail value or '')"""
    k, v = _ref(x)
    if k == "file" and media.kind_of(v) == "video":
        return f"file:{v}", f"thumb:{v}"
    if k == "video" and v.isdigit():
        return v, (x.get("thumb") or "")
    errs.append(f"{where}: add a video.")
    return "", ""


def _cta(ad, where, errs, key="cta"):
    c = ad.get(key) or "LEARN_MORE"
    if c not in CTAS:
        errs.append(f"{where}: choose a button.")
    return c


def _url(u, where, errs):
    u = (u or "").strip()
    p = urlparse(u)
    if p.scheme != "https" or not p.netloc:
        errs.append(f"{where}: the web page link must start with https://")
    return u


def compile_ad(ad: dict) -> tuple[dict, dict, list[str], list[str]]:
    """-> (creative_spec, patch for the ad sets that show it, errors, warnings)"""
    kind = ad.get("kind")
    tag = ad.get("_tag", "Ad")
    errs: list[str] = []
    warns: list[str] = []
    patch: dict = {}
    spec: dict = {}
    if kind == "video":
        vid, thumb = _vid(ad.get("video"), tag, errs)
        text, title = (ad.get("primary_text") or "").strip(), (ad.get("headline") or "").strip()
        if not text:
            errs.append(f"{tag}: write the main text.")
        url = _url(ad.get("destination"), tag, errs)
        vd = {"video_id": vid, "message": text, "title": title, "call_to_action": {"type": _cta(ad, tag, errs), "value": {"link": url}}}
        if ad.get("description"):
            vd["link_description"] = ad["description"].strip()
        k, v = _ref(ad.get("thumb_image"))
        if k in ("file", "hash"):
            vd["image_hash"] = _img(ad["thumb_image"], tag, errs)
        elif thumb:
            vd["image_url"] = thumb
        else:
            errs.append(f"{tag}: this video needs a cover picture. Pick one, or choose a video from the library that has one.")
        spec = {"object_story_spec": {"video_data": vd}}
        if len(text) > 125:
            warns.append(f"{tag}: the main text is long; Meta shows about 125 characters before 'See more'.")
    elif kind == "carousel":
        cards = ad.get("cards") or []
        if not 2 <= len(cards) <= 10:
            errs.append(f"{tag}: a carousel needs 2 to 10 cards (it has {len(cards)}).")
        main = _url(ad.get("destination"), tag, errs)
        out = []
        for i, c in enumerate(cards, 1):
            w = f"{tag}, card {i}"
            ch: dict = {"link": _url(c.get("link") or main, w, errs), "name": (c.get("headline") or "").strip()}
            if not ch["name"]:
                errs.append(f"{w}: write a headline.")
            if c.get("description"):
                ch["description"] = c["description"].strip()
            if c.get("video"):
                vid, thumb = _vid(c["video"], w, errs)
                ch["video_id"] = vid
                if thumb:
                    ch["picture"] = thumb
            else:
                ch["image_hash"] = _img(c.get("image"), w, errs)
            if c.get("cta"):
                ch["call_to_action"] = {"type": _cta(c, w, errs, "cta")}
            out.append(ch)
        ld = {"link": main, "message": (ad.get("primary_text") or "").strip(), "child_attachments": out,
              "multi_share_end_card": bool(ad.get("end_card")), "multi_share_optimized": bool(ad.get("optimized", True))}
        if not ld["message"]:
            errs.append(f"{tag}: write the main text.")
        spec = {"object_story_spec": {"link_data": ld}}
    elif kind == "post":
        pid = str(ad.get("post_id") or "").strip()
        if not re.fullmatch(r"\d+_\d+", pid):
            errs.append(f"{tag}: the post id looks like 1175723048967774_122127934839430745 (page id, underscore, post id). Pick a post from the list or paste its id.")
        spec = {"object_story_id": pid}
        warns.append(f"{tag}: an existing post is used as it is. Its text and image cannot be changed here.")
    elif kind == "dynamic":
        imgs = [_img(x, tag, errs) for x in (ad.get("images") or [])]
        vids = [_vid(x, tag, errs) for x in (ad.get("videos") or [])]
        bodies = [t.strip() for t in (ad.get("bodies") or []) if str(t).strip()]
        titles = [t.strip() for t in (ad.get("titles") or []) if str(t).strip()]
        descs = [t.strip() for t in (ad.get("descriptions") or []) if str(t).strip()]
        if not imgs and not vids:
            errs.append(f"{tag}: add at least one image or video.")
        if not bodies:
            errs.append(f"{tag}: add at least one main text.")
        if not titles:
            errs.append(f"{tag}: add at least one headline.")
        if len(bodies) > 5 or len(titles) > 5 or len(descs) > 5:
            errs.append(f"{tag}: Meta allows up to 5 texts, 5 headlines and 5 descriptions.")
        if len(imgs) > 10 or len(vids) > 10:
            errs.append(f"{tag}: Meta allows up to 10 images and 10 videos.")
        url = _url(ad.get("destination"), tag, errs)
        ctas = [c for c in (ad.get("ctas") or ["LEARN_MORE"]) if c in CTAS] or ["LEARN_MORE"]
        afs: dict = {"bodies": [{"text": t} for t in bodies], "titles": [{"text": t} for t in titles], "link_urls": [{"website_url": url}],
                     "call_to_action_types": ctas, "ad_formats": ["AUTOMATIC_FORMAT"] if imgs and vids else ["SINGLE_VIDEO"] if vids else ["SINGLE_IMAGE"]}
        if descs:
            afs["descriptions"] = [{"text": t} for t in descs]
        if imgs:
            afs["images"] = [{"hash": h} for h in imgs]
        if vids:
            afs["videos"] = [{"video_id": v, **({"thumbnail_url": t} if t else {})} for v, t in vids]
        spec = {"object_story_spec": {}, "asset_feed_spec": afs}
        patch = {"is_dynamic_creative": True}
        warns.append(f"{tag}: Meta tries every combination and learns which works best. An ad set for this kind of ad can hold only this one ad.")
    elif kind == "catalog":
        pset = str(ad.get("product_set_id") or "").strip()
        if not pset.isdigit():
            errs.append(f"{tag}: pick the product set to show.")
        url = _url(ad.get("destination"), tag, errs)
        td = {"link": url, "message": (ad.get("primary_text") or "").strip(), "name": ad.get("headline") or "{{product.name}}",
              "description": ad.get("description") or "{{product.price}}", "call_to_action": {"type": _cta(ad, tag, errs)},
              "multi_share_end_card": False, "show_multiple_images": bool(ad.get("multiple_images"))}
        if not td["message"]:
            errs.append(f"{tag}: write the main text.")
        spec = {"object_story_spec": {"template_data": td}, "product_set_id": pset}
        warns.append(f"{tag}: the ad set must use your pixel and a conversion goal that fits catalog ads. Check with Meta tells you if something is off.")
    else:
        errs.append(f"{tag}: unknown ad kind '{kind}'.")
    if ad.get("url_tags"):
        spec["url_tags"] = str(ad["url_tags"]).strip()
    return spec, patch, errs, warns


# ---- files ----------------------------------------------------------------------------------------------------------------------
@router.post("/api/media")
async def upload_media(file: UploadFile = File(...)):
    name = SAFE.sub("_", (file.filename or "file").strip())[-60:] or "file"
    ext = ("." + name.rsplit(".", 1)[-1].lower()) if "." in name else ""
    if ext not in media.IMG_EXT + media.VID_EXT:
        raise HTTPException(400, "Use JPG or PNG images, or MP4 or MOV videos.")
    limit = media.MAX_VIDEO if ext in media.VID_EXT else media.MAX_IMAGE
    data = await file.read()
    if len(data) > limit:
        raise HTTPException(400, f"That file is too large (limit {limit // (1024 * 1024)} MB).")
    digest = hashlib.sha256(data).hexdigest()
    MEDIA_DIR.mkdir(exist_ok=True)
    dest = MEDIA_DIR / f"{digest[:8]}_{name}"
    dest.write_bytes(data)
    out = {"file": dest.relative_to(ROOT).as_posix(), "kind": "image" if ext in media.IMG_EXT else "video", "name": name, "bytes": len(data)}
    if out["kind"] == "image":
        from src import validate as v
        size = v.image_size(dest)
        if not size:
            dest.unlink()
            raise HTTPException(400, "Cannot read this image (corrupt file?).")
        out["width"], out["height"] = size
    return out


@router.get("/media/{name}")
def media_file(name: str):
    p = (MEDIA_DIR / name).resolve()
    if not str(p).startswith(str(MEDIA_DIR.resolve())) or not p.is_file() or p.suffix.lower() not in media.IMG_EXT:
        raise HTTPException(404)
    return FileResponse(p)


# ---- reading what is already on Meta --------------------------------------------------------------------------------------------
_C: dict = {}


def _cached(key, ttl, fn):
    hit = _C.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    v = fn()
    _C[key] = (time.time(), v)
    return v


def _meta():
    s = Settings()
    if s.missing():
        raise HTTPException(400, "Missing in .env: " + ", ".join(s.missing()))
    return s, Meta(s)


def _fail(s, e):
    if "code 17" in str(e) or "too many calls" in str(e).lower():
        return HTTPException(429, "Meta is limiting how often it can be asked. Wait a minute and try again.")
    return HTTPException(502, f"Meta said: {s.redact(e)[:300]}")


@router.get("/api/meta/videos")
def videos(refresh: bool = False):
    s, m = _meta()
    k = (s.env, s.account, "videos")
    if refresh:
        _C.pop(k, None)
    try:
        rows = _cached(k, 120, lambda: m.get(f"{s.account}/advideos", fields="id,title,picture,length,source", limit=40).get("data", []))
    except MetaError as e:
        raise _fail(s, e)
    return {"videos": [{"id": r["id"], "title": r.get("title") or "", "thumb": r.get("picture") or "", "seconds": round(r.get("length") or 0)} for r in rows]}


def _page_get(s, m, path, **params):
    """Page content needs the Page's own access token, which the user token can ask for."""
    import hashlib as _h, hmac as _hm, requests
    tok = m.get(s.page_id, fields="access_token").get("access_token")
    if not tok:
        raise MetaError("Meta did not give a Page access token (the token needs pages_show_list / pages_read_engagement)")
    q = dict(params, access_token=tok)
    if s.app_secret:
        q["appsecret_proof"] = _hm.new(s.app_secret.encode(), tok.encode(), _h.sha256).hexdigest()
    r = requests.get(m.base + path, params=q, timeout=60)
    body = r.json()
    if "error" in body:
        raise MetaError(s.redact(f"GET {path} -> {body['error'].get('message')} (code {body['error'].get('code')})"))
    return body


@router.get("/api/meta/posts")
def posts():
    s, m = _meta()
    try:
        rows = _cached((s.env, s.page_id, "posts"), 120, lambda: _page_get(s, m, f"{s.page_id}/published_posts", fields="id,message,created_time,full_picture,permalink_url", limit=25).get("data", []))
    except MetaError as e:
        raise _fail(s, e)
    return {"posts": [{"id": r["id"], "text": (r.get("message") or "")[:140], "date": (r.get("created_time") or "")[:10], "picture": r.get("full_picture") or "", "link": r.get("permalink_url") or ""} for r in rows]}


@router.get("/api/meta/catalogs")
def catalogs():
    s, m = _meta()

    def go():
        out, last = [], None
        biz = None
        try:
            biz = (m.get(s.account, fields="business").get("business") or {}).get("id")
        except MetaError as e:
            last = e
        for path in ([f"{biz}/owned_product_catalogs", f"{biz}/client_product_catalogs"] if biz else []) + [f"{s.page_id}/product_catalogs"]:
            try:
                out += m.get(path, fields="id,name,product_count", limit=25).get("data", [])
            except MetaError as e:
                last = e
        if not out and last:
            raise last
        return list({c["id"]: c for c in out}.values())
    try:
        cats = _cached((s.env, s.account, "catalogs"), 300, go)
    except MetaError as e:
        raise _fail(s, e)
    return {"catalogs": [{"id": c["id"], "name": c.get("name"), "products": c.get("product_count")} for c in cats]}


@router.get("/api/meta/product-sets")
def product_sets(catalog: str):
    if not catalog.isdigit():
        raise HTTPException(400, "bad catalog id")
    s, m = _meta()
    try:
        rows = _cached((s.env, catalog, "sets"), 300, lambda: m.get(f"{catalog}/product_sets", fields="id,name,product_count", limit=50).get("data", []))
    except MetaError as e:
        raise _fail(s, e)
    return {"sets": [{"id": r["id"], "name": r.get("name"), "products": r.get("product_count")} for r in rows]}


# ---- previews -------------------------------------------------------------------------------------------------------------------
PREVIEW_FORMATS = {"MOBILE_FEED_STANDARD": "Facebook feed (phone)", "DESKTOP_FEED_STANDARD": "Facebook feed (computer)", "INSTAGRAM_STANDARD": "Instagram feed",
                   "INSTAGRAM_STORY": "Instagram story", "INSTAGRAM_REELS": "Instagram reels", "FACEBOOK_STORY_MOBILE": "Facebook story", "FACEBOOK_REELS_MOBILE": "Facebook reels"}


@router.post("/api/ads/preview")
async def preview(body: dict):
    """A real Meta preview of one ad in one place. Works for creatives whose images and videos are already on Meta."""
    from src.spec_clean import clean_creative
    s, m = _meta()
    fmt = body.get("format", "MOBILE_FEED_STANDARD")
    if fmt not in PREVIEW_FORMATS:
        raise HTTPException(400, "unknown preview place")
    spec = body.get("creative_spec")
    if body.get("ad") and not spec:
        ad = dict(body["ad"])
        spec, _, errs, _w = compile_ad(ad)
        if errs:
            raise HTTPException(400, errs[0])
    if not isinstance(spec, dict):
        raise HTTPException(400, "nothing to preview")
    spec, _ = clean_creative(spec, s.page_id, s.instagram_id)
    if media.files_in(spec):
        raise HTTPException(400, "This ad uses files that are uploaded when you create it, so Meta cannot preview it yet. Use images and videos already on Meta, or create the ad paused and look at it in Ads Manager.")
    try:
        res = m.get(f"{s.account}/generatepreviews", creative=json.dumps(spec), ad_format=fmt)
    except MetaError as e:
        raise _fail(s, e)
    body_html = (res.get("data") or [{}])[0].get("body", "")
    mt = re.search(r'src="([^"]+)"', body_html)
    url = (mt.group(1) if mt else "").replace("&amp;", "&")
    if not url or urlparse(url).netloc not in ("www.facebook.com", "facebook.com", "business.facebook.com"):
        raise HTTPException(502, "Meta did not return a preview for this ad.")
    return {"url": url, "format": fmt}


@router.get("/api/ads/preview-formats")
def preview_formats():
    return {"formats": [{"id": k, "label": v} for k, v in PREVIEW_FORMATS.items()]}
