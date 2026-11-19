"""A local copy of your ad account's campaigns, ad sets, ads and media, so copying and duplicating need no calls to Meta.

Layout (one folder per environment and ad account, kept out of git):
  library/<env>/<act_id>/index.json            lists + counts + when it was synced
  library/<env>/<act_id>/campaigns/<id>.json   one campaign with its ad sets and ads exactly as Meta returned them
  library/<env>/<act_id>/media/images.json     image details; files in media/img/<hash>.<ext> and media/thumb/<hash>.jpg
  library/<env>/<act_id>/media/videos.json     video details; cover pictures in media/vthumb/<id>.jpg
Nothing here is ever written back to Meta, and no token or secret is stored."""
from __future__ import annotations

import re
import shutil
import time
from pathlib import Path
from typing import Any

from .common import ROOT, Settings, jload, jsave

LIB = ROOT / "library"
HEX32 = re.compile(r"^[0-9a-f]{32}$")
DIGITS = re.compile(r"^\d{1,25}$")
STALE_AFTER = 7 * 86400  # a copy older than this is shown as possibly out of date


def root(s: Settings) -> Path:
    return LIB / s.env / (s.account or "no_account")


def _index_path(s: Settings) -> Path:
    return root(s) / "index.json"


def load_index(s: Settings) -> dict:
    return jload(_index_path(s), {}) or {}


def have(s: Settings) -> bool:
    return bool(load_index(s).get("synced_at"))


def synced_at(s: Settings) -> float:
    return float(load_index(s).get("synced_at") or 0)


def age_hours(s: Settings) -> float | None:
    t = synced_at(s)
    return (time.time() - t) / 3600 if t else None


# ---- campaigns ----------------------------------------------------------------------------------------------------------------------
def save_campaign(s: Settings, camp: dict, adsets: list, ads: list) -> None:
    """Store one campaign (raw Meta objects) and update the lists in the index."""
    cid = str(camp["id"])
    jsave(root(s) / "campaigns" / f"{cid}.json", {"campaign": camp, "adsets": adsets, "ads": ads, "synced_at": time.time()})
    ix = load_index(s)
    ix.setdefault("campaigns", {})[cid] = {"name": camp.get("name"), "objective": camp.get("objective"), "status": camp.get("effective_status") or camp.get("status"),
                                           "daily_budget": camp.get("daily_budget"), "lifetime_budget": camp.get("lifetime_budget"), "bid_strategy": camp.get("bid_strategy"), "adsets": len(adsets), "ads": len(ads),
                                           "synced_at": time.time()}
    for k in [k for k, v in ix.get("adsets", {}).items() if v.get("campaign_id") == cid]:
        ix["adsets"].pop(k)
    for k in [k for k, v in ix.get("ads", {}).items() if v.get("campaign_id") == cid]:
        ix["ads"].pop(k)
    for a in adsets:
        ix.setdefault("adsets", {})[str(a["id"])] = {"name": a.get("name"), "campaign_id": cid, "campaign": camp.get("name"), "status": a.get("effective_status") or a.get("status"),
                                                     "goal": a.get("optimization_goal")}
    for a in ads:
        ix.setdefault("ads", {})[str(a["id"])] = {"name": a.get("name"), "campaign_id": cid, "campaign": camp.get("name"), "adset_id": str(a.get("adset_id") or ""),
                                                  "status": a.get("effective_status") or a.get("status")}
    jsave(_index_path(s), ix)


def mark_synced(s: Settings, keep_campaign_ids: set | None = None, counts: dict | None = None) -> None:
    """Finish a full sync: drop campaigns that no longer exist on Meta and stamp the time."""
    ix = load_index(s)
    if keep_campaign_ids is not None:
        for cid in [c for c in ix.get("campaigns", {}) if c not in keep_campaign_ids]:
            delete_campaign(s, cid, _ix=ix)
    ix["synced_at"] = time.time()
    ix["account"], ix["env"] = s.account, s.env
    if counts:
        ix["counts"] = counts
    jsave(_index_path(s), ix)


def delete_campaign(s: Settings, cid: str, _ix: dict | None = None) -> None:
    """Remove only the LOCAL copy."""
    if not DIGITS.match(str(cid)):
        return
    ix = _ix if _ix is not None else load_index(s)
    ix.get("campaigns", {}).pop(cid, None)
    for key in ("adsets", "ads"):
        for k in [k for k, v in ix.get(key, {}).items() if v.get("campaign_id") == cid]:
            ix[key].pop(k)
    (root(s) / "campaigns" / f"{cid}.json").unlink(missing_ok=True)
    if _ix is None:
        jsave(_index_path(s), ix)


def list_campaigns(s: Settings) -> list[dict]:
    ix = load_index(s)
    return [{"id": k, **v} for k, v in ix.get("campaigns", {}).items()]


def list_adsets(s: Settings) -> list[dict]:
    return [{"id": k, **v} for k, v in load_index(s).get("adsets", {}).items()]


def list_ads(s: Settings) -> list[dict]:
    return [{"id": k, **v} for k, v in load_index(s).get("ads", {}).items()]


def get_campaign(s: Settings, cid: str) -> dict | None:
    if not DIGITS.match(str(cid)):
        return None
    return jload(root(s) / "campaigns" / f"{cid}.json", None)


def find_adset(s: Settings, adset_id: str) -> dict | None:
    meta = load_index(s).get("adsets", {}).get(str(adset_id))
    snap = get_campaign(s, meta["campaign_id"]) if meta else None
    return next((a for a in (snap or {}).get("adsets", []) if str(a.get("id")) == str(adset_id)), None)


def find_ad(s: Settings, ad_id: str) -> dict | None:
    meta = load_index(s).get("ads", {}).get(str(ad_id))
    snap = get_campaign(s, meta["campaign_id"]) if meta else None
    return next((a for a in (snap or {}).get("ads", []) if str(a.get("id")) == str(ad_id)), None)


# ---- media --------------------------------------------------------------------------------------------------------------------------
def collect_hashes(o: Any) -> set:
    """Every image hash a creative refers to (image_hash, and 'hash' inside asset_feed_spec images)."""
    out: set = set()
    if isinstance(o, dict):
        for k, v in o.items():
            if k in ("image_hash", "hash") and isinstance(v, str) and HEX32.match(v):
                out.add(v)
            else:
                out |= collect_hashes(v)
    elif isinstance(o, list):
        for x in o:
            out |= collect_hashes(x)
    return out


def collect_video_ids(o: Any) -> set:
    out: set = set()
    if isinstance(o, dict):
        for k, v in o.items():
            if k == "video_id" and isinstance(v, (str, int)) and DIGITS.match(str(v)):
                out.add(str(v))
            else:
                out |= collect_video_ids(v)
    elif isinstance(o, list):
        for x in o:
            out |= collect_video_ids(x)
    return out


def _media_path(s: Settings) -> Path:
    return root(s) / "media"


def images(s: Settings) -> dict:
    return jload(_media_path(s) / "images.json", {}) or {}


def videos(s: Settings) -> dict:
    return jload(_media_path(s) / "videos.json", {}) or {}


def save_images(s: Settings, data: dict) -> None:
    jsave(_media_path(s) / "images.json", data)


def save_videos(s: Settings, data: dict) -> None:
    jsave(_media_path(s) / "videos.json", data)


def image_file(s: Settings, h: str, thumb: bool = False) -> Path | None:
    """The stored file for an image hash (full size or thumbnail), or None."""
    if not HEX32.match(h or ""):
        return None
    info = images(s).get(h) or {}
    name = info.get("thumb_file" if thumb else "file")
    if not name:
        return None
    p = _media_path(s) / ("thumb" if thumb else "img") / name
    return p if p.is_file() else None


def video_thumb(s: Settings, vid: str) -> Path | None:
    if not DIGITS.match(str(vid)):
        return None
    name = (videos(s).get(str(vid)) or {}).get("thumb_file")
    p = _media_path(s) / "vthumb" / name if name else None
    return p if p and p.is_file() else None


def has_image(s: Settings, h: str) -> bool:
    return h in images(s)


def media_dir(s: Settings, kind: str) -> Path:
    d = _media_path(s) / kind
    d.mkdir(parents=True, exist_ok=True)
    return d


def clear(s: Settings) -> None:
    """Remove the whole local copy of this account (never touches Meta)."""
    r = root(s)
    if r.is_dir() and LIB in r.parents:
        shutil.rmtree(r)


def size_bytes(s: Settings) -> int:
    r = root(s)
    return sum(p.stat().st_size for p in r.rglob("*") if p.is_file()) if r.is_dir() else 0
