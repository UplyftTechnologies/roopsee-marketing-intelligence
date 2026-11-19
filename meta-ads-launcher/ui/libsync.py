"""Sync your Meta ad account into the local library (a handful of calls), and serve the Library page. Reading only: nothing here changes Meta."""
from __future__ import annotations

import threading
import time
from urllib.parse import urlparse

import requests
from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from src import library_store as store
from src.common import Registry, Settings
from src.meta_api import STATS, Meta, MetaError, usage_snapshot
from src.spec_clean import describe
from ui.library import AD_FIELDS, ADSET_FIELDS, CAMP_FIELDS

router = APIRouter()

DEAD = ("DELETED", "ARCHIVED")
NESTED = f"id,{CAMP_FIELDS},adsets.limit(50){{id,{ADSET_FIELDS},ads.limit(50){{id,{AD_FIELDS}}}}}"
IMG_FIELDS = "hash,name,width,height,created_time,url,url_128"
VID_FIELDS = "id,title,length,picture,created_time"
CDN_HOSTS = (".fbcdn.net", ".facebook.com", ".fbsbx.com", ".cdninstagram.com")
MAX_FILE = 30 * 1024 * 1024

SYNC: dict = {"running": False, "phase": "", "done": 0, "total": 0, "error": "", "started": 0.0, "finished": 0.0, "calls_used": 0, "note": ""}
_LOCK = threading.Lock()


def _live(rows: list) -> list:
    return [r for r in rows if r.get("effective_status") not in DEAD]


def _split(c: dict) -> tuple[dict, list, list]:
    """A campaign with nested ad sets and ads -> (campaign, ad sets, ads)."""
    adsets_raw = (c.pop("adsets", None) or {}).get("data", [])
    adsets, ads = [], []
    for a in _live(adsets_raw):
        ads += _live((a.pop("ads", None) or {}).get("data", []))
        adsets.append(a)
    return c, adsets, ads


def _fetch_campaign(meta: Meta, cid: str) -> tuple[dict, list, list]:
    """One campaign the plain way: 3 calls."""
    camp = meta.get(cid, fields=f"id,{CAMP_FIELDS}")
    adsets = _live(meta.pages(f"{cid}/adsets", fields=f"id,{ADSET_FIELDS}", limit=50))
    ads = _live(meta.pages(f"{cid}/ads", fields=f"id,{AD_FIELDS}", limit=50))
    return camp, adsets, ads


def _download(url: str, dest) -> bool:
    """Fetch an image from Meta's file servers (no token is sent). Only Meta's own hosts are allowed."""
    try:
        u = urlparse(url)
        if u.scheme != "https" or not (u.hostname or "").endswith(CDN_HOSTS):
            return False
        r = requests.get(url, timeout=30, stream=True)
        if not r.ok or int(r.headers.get("content-length") or 0) > MAX_FILE:
            return False
        data = r.raw.read(MAX_FILE + 1, decode_content=True)
        if len(data) > MAX_FILE:
            return False
        dest.write_bytes(data)
        return True
    except (requests.RequestException, OSError, ValueError):
        return False


def _ext(url: str) -> str:
    p = urlparse(url).path.lower()
    return ".png" if p.endswith(".png") else ".gif" if p.endswith(".gif") else ".jpg"


def _sync_campaigns(s: Settings, meta: Meta) -> int:
    SYNC.update(phase="Reading campaigns, ad sets and ads", done=0, total=0)
    keep: set = set()
    n_sets = n_ads = 0
    try:
        rows = meta.pages(f"{s.account}/campaigns", fields=NESTED, limit=10)  # campaign + ad sets + ads in one call per 10 campaigns
        SYNC["total"] = len(rows)
        for c in _live(rows):
            c, adsets, ads = _split(c)
            store.save_campaign(s, c, adsets, ads)
            keep.add(str(c["id"]))
            n_sets += len(adsets)
            n_ads += len(ads)
            SYNC["done"] += 1
        SYNC["note"] = "read in bulk"
    except MetaError as e:
        if getattr(e, "code", None) in (17, 4, 32, 613, 80004) or "limiting calls" in str(e):
            raise
        SYNC["note"] = "bulk read was refused, so each campaign was read on its own"  # Meta can say 'too much data'; fall back to 3 calls per campaign
        rows = _live(meta.pages(f"{s.account}/campaigns", fields=f"id,{CAMP_FIELDS}", limit=100))
        SYNC.update(total=len(rows), done=0)
        keep, n_sets, n_ads = set(), 0, 0
        for c in rows:
            camp, adsets, ads = _fetch_campaign(meta, c["id"])
            store.save_campaign(s, camp, adsets, ads)
            keep.add(str(camp["id"]))
            n_sets += len(adsets)
            n_ads += len(ads)
            SYNC["done"] += 1
    store.mark_synced(s, keep_campaign_ids=keep, counts={"campaigns": len(keep), "adsets": n_sets, "ads": n_ads})
    return len(keep)


def _wanted_full_hashes(s: Settings) -> set:
    """Images worth keeping at full size: the ones your ads use, and the ones this launcher uploaded."""
    want: set = set()
    for c in store.list_campaigns(s):
        snap = store.get_campaign(s, c["id"]) or {}
        for a in snap.get("ads", []):
            want |= store.collect_hashes(a.get("creative") or {})
    want |= {v.get("meta_image_hash") for v in Registry(s, "upload_registry.json").d.values() if v.get("meta_image_hash")}
    return {h for h in want if h}


def _sync_images(s: Settings, meta: Meta) -> None:
    SYNC.update(phase="Saving images", done=0, total=0)
    rows = meta.pages(f"{s.account}/adimages", fields=IMG_FIELDS, limit=100)
    old = store.images(s)
    want_full = _wanted_full_hashes(s)
    SYNC["total"] = len(rows)
    thumbs, full = store.media_dir(s, "thumb"), store.media_dir(s, "img")
    out: dict = {}
    for r in rows:
        h = r.get("hash")
        if not h:
            continue
        info = {**old.get(h, {}), "name": r.get("name"), "width": r.get("width"), "height": r.get("height"), "created": (r.get("created_time") or "")[:10]}
        if not (info.get("thumb_file") and (thumbs / info["thumb_file"]).is_file()):
            url = r.get("url_128") or r.get("url")
            if url and _download(url, thumbs / f"{h}.jpg"):
                info["thumb_file"] = f"{h}.jpg"
        if h in want_full and not (info.get("file") and (full / info["file"]).is_file()):
            url = r.get("url")
            if url:
                name = f"{h}{_ext(url)}"
                if _download(url, full / name):
                    info["file"] = name
        out[h] = info
        SYNC["done"] += 1
    store.save_images(s, out)


def _sync_videos(s: Settings, meta: Meta) -> None:
    SYNC.update(phase="Saving video details", done=0, total=0)
    rows = meta.pages(f"{s.account}/advideos", fields=VID_FIELDS, limit=100)
    old = store.videos(s)
    SYNC["total"] = len(rows)
    vt = store.media_dir(s, "vthumb")
    out: dict = {}
    for r in rows:
        vid = str(r.get("id") or "")
        if not vid:
            continue
        info = {**old.get(vid, {}), "title": r.get("title"), "length": r.get("length"), "created": (r.get("created_time") or "")[:10]}
        if not (info.get("thumb_file") and (vt / info["thumb_file"]).is_file()) and r.get("picture") and _download(r["picture"], vt / f"{vid}.jpg"):
            info["thumb_file"] = f"{vid}.jpg"
        out[vid] = info
        SYNC["done"] += 1
    store.save_videos(s, out)


def _run(s: Settings) -> None:
    meta = Meta(s)
    before = STATS["calls"]
    try:
        _sync_campaigns(s, meta)
        _sync_images(s, meta)
        _sync_videos(s, meta)
        SYNC["phase"] = "Done"
    except MetaError as e:
        SYNC["error"] = s.redact(e)[:300]
    except Exception as e:  # noqa: BLE001  (a sync must never crash the server; the message is shown)
        SYNC["error"] = s.redact(f"{type(e).__name__}: {e}")[:300]
    finally:
        SYNC.update(running=False, finished=time.time(), calls_used=STATS["calls"] - before)


# ---- endpoints ----------------------------------------------------------------------------------------------------------------------
def _settings() -> Settings:
    s = Settings()
    if s.missing():
        raise HTTPException(400, "Missing in .env: " + ", ".join(s.missing()))
    return s


@router.get("/api/library/status")
def status():
    s = Settings()
    ix = store.load_index(s)
    age = store.age_hours(s)
    return {"env": s.env, "account": s.account, "synced": bool(ix.get("synced_at")), "synced_at": ix.get("synced_at"), "age_hours": age,
            "stale": bool(age is not None and age * 3600 > store.STALE_AFTER),
            "counts": {"campaigns": len(ix.get("campaigns", {})), "adsets": len(ix.get("adsets", {})), "ads": len(ix.get("ads", {}))},  # what is stored now (a refresh or a removal changes it)
            "images": len(store.images(s)), "images_full": sum(1 for v in store.images(s).values() if v.get("file")), "videos": len(store.videos(s)),
            "megabytes": round(store.size_bytes(s) / 1e6, 1), "sync": dict(SYNC), "usage": usage_snapshot()}


@router.post("/api/library/sync")
def start_sync():
    s = _settings()
    with _LOCK:
        if SYNC["running"]:
            return {"started": False, "message": "A sync is already running."}
        left = usage_snapshot()["blocked_seconds"]
        if left:
            raise HTTPException(429, f"Meta is limiting calls for this ad account. Try again in about {left // 60 + 1} min.")
        SYNC.update(running=True, phase="Starting", done=0, total=0, error="", started=time.time(), finished=0.0, calls_used=0, note="")
    threading.Thread(target=_run, args=(s,), daemon=True).start()
    return {"started": True}


@router.post("/api/library/refresh/{cid}")
def refresh_one(cid: str):
    """Re-read one campaign from Meta (3 calls) and update its local copy."""
    if not store.DIGITS.match(cid):
        raise HTTPException(400, "bad campaign id")
    s = _settings()
    try:
        camp, adsets, ads = _fetch_campaign(Meta(s), cid)
    except MetaError as e:
        if "does not exist" in str(e).lower():  # deleted on Meta: the local copy is stale, so drop it
            store.delete_campaign(s, cid)
            return {"removed": True, "note": "This campaign no longer exists on Meta, so its local copy was removed."}
        raise HTTPException(502 if "limiting" not in str(e) else 429, f"Meta said: {s.redact(e)[:300]}")
    if camp.get("effective_status") in DEAD:
        store.delete_campaign(s, cid)
        return {"removed": True, "note": "This campaign was deleted or archived on Meta, so its local copy was removed."}
    store.save_campaign(s, camp, adsets, ads)
    return {"refreshed": cid, "adsets": len(adsets), "ads": len(ads)}


@router.delete("/api/library/campaigns/{cid}")
def delete_local(cid: str):
    store.delete_campaign(Settings(), cid)
    return {"deleted": cid, "note": "Only the local copy was removed. Nothing changed on Meta."}


@router.post("/api/library/clear")
def clear_local():
    store.clear(Settings())
    return {"cleared": True, "note": "Only the local copy was removed. Nothing changed on Meta."}


def _creative_info(ad: dict, s: Settings) -> dict:
    spec = ad.get("creative") or {}
    d = describe(spec)
    hashes = d["image_hashes"] or sorted(store.collect_hashes(spec))
    thumb = next((f"/lib-media/thumb/{h}" for h in hashes if store.image_file(s, h, thumb=True)), None)
    if not thumb:
        thumb = next((f"/lib-media/vthumb/{v}" for v in d["video_ids"] if store.video_thumb(s, v)), None)
    return {"type": d["kind"], "thumb": thumb, "text": (d["texts"] or [""])[0][:120]}


@router.get("/api/library/items")
def items(kind: str = "campaigns", q: str = ""):
    s = Settings()
    q = q.strip().lower()
    hit = lambda *parts: not q or q in " ".join(str(p or "") for p in parts).lower()  # noqa: E731
    if kind == "campaigns":
        rows = [c for c in store.list_campaigns(s) if hit(c["name"], c.get("objective"))]
        return {"items": sorted(rows, key=lambda r: r.get("name") or "")}
    if kind == "adsets":
        rows = [a for a in store.list_adsets(s) if hit(a["name"], a.get("campaign"), a.get("goal"))]
        return {"items": sorted(rows, key=lambda r: (r.get("campaign") or "", r.get("name") or ""))}
    if kind == "ads":
        out = []
        for c in store.list_campaigns(s):
            snap = store.get_campaign(s, c["id"]) or {}
            names = {str(a["id"]): a.get("name") for a in snap.get("adsets", [])}
            for ad in snap.get("ads", []):
                row = {"id": str(ad["id"]), "name": ad.get("name"), "campaign": c["name"], "campaign_id": c["id"], "adset": names.get(str(ad.get("adset_id")), ""),
                       "status": ad.get("effective_status") or ad.get("status"), **_creative_info(ad, s)}
                if hit(row["name"], row["campaign"], row["adset"], row["type"], row["text"]):
                    out.append(row)
        return {"items": sorted(out, key=lambda r: (r["campaign"] or "", r["name"] or ""))}
    if kind == "media":
        imgs = [{"kind": "image", "id": h, "name": v.get("name"), "width": v.get("width"), "height": v.get("height"), "created": v.get("created"),
                 "thumb": f"/lib-media/thumb/{h}" if store.image_file(s, h, thumb=True) else None, "full": bool(store.image_file(s, h))} for h, v in store.images(s).items()]
        vids = [{"kind": "video", "id": i, "name": v.get("title"), "length": v.get("length"), "created": v.get("created"),
                 "thumb": f"/lib-media/vthumb/{i}" if store.video_thumb(s, i) else None} for i, v in store.videos(s).items()]
        rows = [r for r in imgs + vids if hit(r["name"], r["id"])]
        return {"items": sorted(rows, key=lambda r: r.get("created") or "", reverse=True)}
    raise HTTPException(400, "kind must be campaigns, adsets, ads or media")


@router.get("/lib-media/{kind}/{name}")
def lib_media(kind: str, name: str):
    s = Settings()
    p = None
    if kind in ("img", "thumb"):
        p = store.image_file(s, name, thumb=(kind == "thumb")) or (store.image_file(s, name, thumb=True) if kind == "img" else None)
    elif kind == "vthumb":
        p = store.video_thumb(s, name)
    if not p:
        raise HTTPException(404)
    return FileResponse(p)


@router.get("/api/usage")
def usage():
    return usage_snapshot()
