"""Backend for the guided 'New campaign' flow, drafts, history and the live overview."""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests
from fastapi import APIRouter, HTTPException, Request

from src import doctor, validate as validate_mod
from src.common import (CTAS, ROOT, LauncherError, Registry, Settings, adsets_cfg, audiences_cfg, campaigns_cfg, jload, jsave)
from src.meta_api import Meta, MetaError
from src.pipeline import execute
from ui.jobs import start_job

router = APIRouter()

GOALS = {
    "traffic": {"label": "Get visitors to the website", "short": "Traffic", "objective": "OUTCOME_TRAFFIC", "optimization": "LINK_CLICKS", "event": None,
                "help": "People click the ad and land on your site. No tracking setup needed."},
    "sales": {"label": "Get sales", "short": "Sales", "objective": "OUTCOME_SALES", "optimization": "OFFSITE_CONVERSIONS", "event": "PURCHASE",
              "help": "Meta looks for people likely to buy. Needs your pixel (dataset) connected."},
}
AUDIENCES = {
    "all": {"label": "Everyone in India, 18 to 45", "short": "India 18-45", "countries": ["IN"], "age_min": 18, "age_max": 45, "gender": "all"},
    "women": {"label": "Women in India, 18 to 45", "short": "Women India 18-45", "countries": ["IN"], "age_min": 18, "age_max": 45, "gender": "women"},
}
PLACEMENTS = {
    "instagram": {"label": "Instagram only", "short": "Instagram", "list": ["instagram"]},
    "facebook_instagram": {"label": "Facebook and Instagram", "short": "FB+IG", "list": ["facebook", "instagram"]},
    "automatic": {"label": "Automatic (let Meta decide)", "short": "Auto", "list": ["automatic"]},
}
CTA_LABELS = {"LEARN_MORE": "Learn more", "SHOP_NOW": "Shop now", "SIGN_UP": "Sign up", "GET_OFFER": "Get offer", "ORDER_NOW": "Order now",
              "CONTACT_US": "Contact us", "SUBSCRIBE": "Subscribe"}
GENDERS = {"all": [], "women": [2], "men": [1]}
BATCH_OK = re.compile(r"^[A-Za-z0-9_]+$")


def _dests() -> list[dict]:
    d = jload(ROOT / "config" / "destinations.json", None)
    return (d or {}).get("destinations") or [{"label": "Home page", "url": "https://roopsee.com/"}]


@router.get("/api/wizard/options")
def options():
    s = Settings()
    cats = sorted({p.parent.name for p in (ROOT / "creatives").rglob("*") if p.suffix.lower() in (".jpg", ".jpeg", ".png")})
    return {"env": s.env, "account": s.account, "pixel": bool(s.pixel_id), "missing": s.missing(),
            "goals": [{"id": k, **{x: v[x] for x in ("label", "help")}} for k, v in GOALS.items()],
            "audiences": [{"id": k, "label": v["label"]} for k, v in AUDIENCES.items()],
            "placements": [{"id": k, "label": v["label"]} for k, v in PLACEMENTS.items()],
            "saved_audiences": [{"id": k, "label": k} for k in audiences_cfg() if not k.startswith("WIZ_")],
            "ctas": [{"value": c, "label": CTA_LABELS.get(c, c)} for c in sorted(CTAS)], "destinations": _dests(), "categories": cats}


# ---- turning answers into a concrete plan ---------------------------------------------------------------------------------
def _audience(spec: dict, saved: dict) -> tuple[dict, list[str]]:
    """One ad set's audience: a built-in preset, one saved in config/audiences.json, or custom."""
    errs = []
    pre = spec.get("audience", "all")
    if pre in AUDIENCES:
        return {**AUDIENCES[pre], "key": None}, errs
    if pre in saved:
        sv = saved[pre]
        g = "women" if sv.get("genders") == [2] else "men" if sv.get("genders") == [1] else "all"
        return {"label": pre, "short": pre[:28], "countries": sv.get("countries", ["IN"]), "age_min": sv.get("age_min", 18), "age_max": sv.get("age_max", 45), "gender": g, "key": pre}, errs
    c = spec.get("custom") or {}
    countries = [x.strip().upper() for x in str(c.get("countries", "IN")).split(",") if x.strip()]
    try:
        amin, amax = int(c.get("age_min") or 18), int(c.get("age_max") or 45)
    except (TypeError, ValueError):
        amin, amax = 18, 45
        errs.append("Ages must be numbers.")
    if not countries or not all(len(x) == 2 and x.isalpha() for x in countries):
        errs.append("Countries must be two-letter codes such as IN, separated by commas.")
    if not (13 <= amin <= amax <= 65):
        errs.append("Ages must be between 13 and 65, and the youngest cannot be above the oldest.")
    g = c.get("gender", "all")
    gl = {"all": "Everyone", "women": "Women", "men": "Men"}.get(g, "Everyone")
    return {"label": f"{gl} in {', '.join(countries)}, {amin} to {amax}", "short": f"{gl} {'/'.join(countries)} {amin}-{amax}", "countries": countries,
            "age_min": amin, "age_max": amax, "gender": g, "key": None}, errs


def _legacy(a: dict) -> list[dict]:
    """Older drafts had a single audience; turn them into a one-item ad set list."""
    return a.get("adsets") or [{"uid": "s1", "audience": a.get("audience", "all"), "custom": a.get("custom"), "placements": a.get("placements", "instagram")}]


def build_plan(a: dict, s: Settings) -> dict:
    errs, warns = [], []
    goal = GOALS.get(a.get("goal"))
    if not goal:
        errs.append("Choose what you want the campaign to do.")
        goal = GOALS["traffic"]
    if a.get("goal") == "sales" and not s.pixel_id:
        errs.append(f"Sales campaigns need your pixel (dataset) ID. Add META_{s.env.upper()}_PIXEL_ID to .env (run: python run.py discover to find it).")
    per_set = a.get("budget_mode") == "adset"
    saved = audiences_cfg()
    set_specs = _legacy(a)
    if len(set_specs) > 10:
        errs.append("Please use 10 ad sets or fewer in one campaign.")

    daily = 0.0
    if not per_set:
        try:
            daily = float(a.get("daily_budget"))
            if daily <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errs.append("Enter a daily budget in rupees, for example 500.")
        if 0 < daily < 100:
            warns.append("Very small daily budgets can be rejected by Meta. If you see an error about the budget, try a higher amount.")
    start, end = a.get("start_date") or None, a.get("end_date") or None
    if start and end and end < start:
        errs.append("The end date is before the start date.")

    now = datetime.now()
    stamp = now.strftime("%d %b")
    base = f"Roopsee | {goal['short']} | {stamp}"
    existing = campaigns_cfg()
    name, n = base, 1
    while name in existing:
        n += 1
        name = f"{base} | {n}"

    taken = set(adsets_cfg())
    sets_out, audiences, uid_index = [], {}, {}
    for i, sp in enumerate(set_specs):
        label = f"Ad set {i + 1}"
        aud, e2 = _audience(sp, saved)
        errs += [f"{label}: {e}" for e in e2]
        plc = PLACEMENTS.get(sp.get("placements", "instagram"))
        if not plc:
            errs.append(f"{label}: choose where the ads should appear.")
            plc = PLACEMENTS["instagram"]
        nm0 = f"{aud['short']} | {plc['short']} | {stamp}" + (f" | {n}" if n > 1 else "")
        nm, m = nm0, 1
        while nm in taken:
            m += 1
            nm = f"{nm0} | {m}"
        taken.add(nm)
        akey = aud["key"] or f"WIZ_{'_'.join(aud['countries'])}_{aud['gender']}_{aud['age_min']}_{aud['age_max']}".upper()
        if not aud["key"]:
            audiences[akey] = {"countries": aud["countries"], "age_min": aud["age_min"], "age_max": aud["age_max"], "genders": GENDERS.get(aud["gender"], [])}
        adset = {"key": nm, "campaign_key": name, "audience": akey, "placements": plc["list"], "optimization_goal": goal["optimization"]}
        if goal["event"]:
            adset["optimization_event"] = goal["event"]
        if per_set:
            try:
                bud = float(sp.get("daily_budget"))
                if bud <= 0:
                    raise ValueError
                adset["daily_budget"] = bud
            except (TypeError, ValueError):
                errs.append(f"{label}: enter a daily budget in rupees.")
        if start:
            adset["start_time"] = f"{start}T00:00:00+0530"
        if end:
            adset["end_time"] = f"{end}T23:59:00+0530"
        sets_out.append(adset)
        uid_index[sp.get("uid", f"s{i + 1}")] = i
        sp["_aud"], sp["_plc"] = aud, plc
    if not sets_out:
        errs.append("Add at least one ad set.")

    # an ad shown in several ad sets becomes one ad per ad set (the first keeps the plain ID, the others get _S2, _S3 ...)
    ads, used = [], set()
    per_set_count = [0] * len(sets_out)
    for i, ad in enumerate(a.get("ads") or [], 1):
        tag = f"Ad {i}"
        img, h = (ad.get("image") or "").strip(), (ad.get("image_hash") or "").strip()
        key = Path(img).stem if img else (ad.get("ad_key") or "").strip()
        if not img and not h:
            errs.append(f"{tag}: add an image.")
        if img and not (ROOT / img).is_file():
            errs.append(f"{tag}: the image file was not found. Upload it again.")
        if h and not re.fullmatch(r"[0-9a-f]{32}", h):
            errs.append(f"{tag}: that image hash does not look right (it should be 32 letters and digits).")
        if not key or not re.fullmatch(r"RS_[A-Z0-9]+_\d{3}", key):
            errs.append(f"{tag}: this ad needs an Ad ID like RS_SKINCARE_001 (letters and digits, then a 3-digit number). Go back to the Ads step and fill in the Ad ID.")
        if not (ad.get("primary_text") or "").strip():
            errs.append(f"{tag}: write the main text.")
        if not (ad.get("headline") or "").strip():
            errs.append(f"{tag}: write a headline.")
        url = (ad.get("destination") or "").strip()
        if not url.startswith("https://") or "." not in url:
            errs.append(f"{tag}: the web page link must start with https://")
        if ad.get("cta") not in CTAS:
            errs.append(f"{tag}: choose a button.")
        if len(ad.get("primary_text") or "") > 125:
            warns.append(f"{tag}: the main text is long; Meta shows about 125 characters before 'See more'.")
        if len(ad.get("headline") or "") > 40:
            warns.append(f"{tag}: the headline is long and may be cut off.")
        targets = sorted({uid_index[u] for u in (ad.get("sets") or list(uid_index)) if u in uid_index})
        if not targets:
            errs.append(f"{tag}: choose at least one ad set for it to appear in.")
        for pos, si in enumerate(targets):
            k = key if pos == 0 else f"{key}_S{si + 1}"
            if k in used:
                errs.append(f"{tag}: the same ad ID is used twice.")
            used.add(k)
            entry = {"ad_key": k, "adset_key": sets_out[si]["key"], "primary_text": (ad.get("primary_text") or "").strip(), "headline": (ad.get("headline") or "").strip(),
                     "cta": ad.get("cta"), "destination": url, "status": "READY"}
            if ad.get("description"):
                entry["description"] = ad["description"].strip()
            if h:
                entry["image_hash"] = h
            else:
                entry["image"] = img
            ads.append(entry)
            per_set_count[si] += 1
    if not a.get("ads"):
        errs.append("Add at least one ad.")
    for si, c in enumerate(per_set_count):
        if sets_out and c == 0 and a.get("ads"):
            warns.append(f"Ad set {si + 1} has no ads in it. It would be created empty, so either add an ad to it or remove it.")

    camp = {"key": name, "objective": goal["objective"], "budget_strategy": "ABO" if per_set else "CBO", "status": "PAUSED"}
    if not per_set:
        camp["daily_budget"] = daily
    batch = f"batch_wiz_{now.strftime('%Y%m%d_%H%M')}"
    total = sum(x.get("daily_budget", 0) for x in sets_out) if per_set else daily
    return {"errors": errs, "warnings": warns, "campaign": camp, "adsets": sets_out, "audiences": audiences, "ads": ads, "batch": batch,
            "batch_id": f"ROOPSEE_WIZ_{now.strftime('%Y%m%d_%H%M')}", "names": {"campaign": name, "adsets": [x["key"] for x in sets_out]},
            "summary": {"goal": goal["label"], "budget_mode": "adset" if per_set else "campaign", "daily_budget": daily, "total_budget": total, "ads": len(ads), "start": start, "end": end,
                        "adsets": [{"name": x["key"], "audience": sp["_aud"]["label"], "placements": sp["_plc"]["label"], "budget": x.get("daily_budget"), "ads": per_set_count[j]}
                                   for j, (x, sp) in enumerate(zip(sets_out, set_specs))]}}


@router.post("/api/wizard/preview")
async def preview(req: Request):
    return build_plan(await req.json(), Settings())


@router.post("/api/wizard/create")
async def create(req: Request):
    body = await req.json()
    s = Settings()
    plan = build_plan(body.get("answers") or {}, s)
    if plan["errors"]:
        raise HTTPException(400, {"errors": plan["errors"]})
    cp = bool(body.get("confirm_production"))
    if s.env == "production" and not cp:
        raise HTTPException(400, {"errors": ["You are on production. Tick the confirmation box to create this on the real ad account."]})
    miss = s.missing()
    if miss:
        raise HTTPException(400, {"errors": ["Missing in .env: " + ", ".join(miss)]})
    files = {n: ROOT / "config" / f"{n}.json" for n in ("campaigns", "adsets", "audiences")}
    before = {n: (p.read_text(encoding="utf-8") if p.exists() else None) for n, p in files.items()}
    bpath = ROOT / "ads" / f"{plan['batch']}.json"
    try:
        c = jload(files["campaigns"], {"campaigns": []}) or {"campaigns": []}
        c["campaigns"].append(plan["campaign"])
        jsave(files["campaigns"], c)
        d = jload(files["adsets"], {"adsets": []}) or {"adsets": []}
        d["adsets"].extend(plan["adsets"])
        jsave(files["adsets"], d)
        au = jload(files["audiences"], {"audiences": {}}) or {"audiences": {}}
        au.setdefault("audiences", {}).update(plan["audiences"])
        jsave(files["audiences"], au)
        jsave(bpath, {"batch_id": plan["batch_id"], "ads": plan["ads"]})
        errors, _ = validate_mod.validate(s, plan["batch"])
        if errors:
            raise LauncherError("; ".join(errors))
    except Exception as e:  # undo every file we touched so a failed attempt leaves nothing behind
        for n, txt in before.items():
            if txt is None:
                files[n].unlink(missing_ok=True)
            else:
                files[n].write_text(txt, encoding="utf-8")
        bpath.unlink(missing_ok=True)
        msg = str(e)
        if "never reused" in msg or "already used" in msg:
            msg = "One of these images has already been used in another campaign. Every image can be used only once, so upload a new image (or a new version of it)."
        raise HTTPException(400, {"errors": [f"Could not prepare this campaign. {msg}"]})

    batch = plan["batch"]
    Registry(s, "wizard_history.json").update(batch, answers=body.get("answers"), created=datetime.now(timezone.utc).isoformat(timespec="seconds"),
                                              campaign=plan["names"]["campaign"], goal=plan["summary"]["goal"], budget=plan["summary"]["total_budget"],
                                              ads=len(plan["ads"]), adsets=len(plan["adsets"]))

    def result(ok):
        ent, ads = Registry(s, "entity_registry.json").d, Registry(s, "ad_registry.json").d
        cid = ent.get(f"campaign:{plan['names']['campaign']}", {}).get("id")
        url = None
        if cid and s.env == "production":
            url = f"https://adsmanager.facebook.com/adsmanager/manage/campaigns?act={s.account.replace('act_', '')}&selected_campaign_ids={cid}"
        return {"batch": batch, "env": s.env, "campaign": {"name": plan["names"]["campaign"], "id": cid},
                "adsets": [{"name": n, "id": ent.get(f"adset:{n}", {}).get("id")} for n in plan["names"]["adsets"]],
                "ads": [{"key": x["ad_key"], "adset": x["adset_key"], "id": ads.get(x["ad_key"], {}).get("meta_ad_id"), "status": ads.get(x["ad_key"], {}).get("status")} for x in plan["ads"]],
                "ads_manager_url": url}

    steps = [("Upload the images", lambda: execute("upload", batch, confirm_production=cp)),
             ("Create the campaign and ad sets (paused)", lambda: execute("setup", batch, confirm_production=cp)),
             ("Create the ads (paused)", lambda: execute("prepare", batch, confirm_production=cp))]
    job = start_job(f"new campaign {plan['names']['campaign']}", steps, result)
    return {"job": job["id"], "batch": batch}


@router.post("/api/wizard/retry")
async def retry(req: Request):
    """Run the three steps again for a batch that stopped half way. Finished work is skipped."""
    body = await req.json()
    s = Settings()
    batch = body.get("batch", "")
    if not BATCH_OK.match(batch) or not (ROOT / "ads" / f"{batch}.json").exists():
        raise HTTPException(400, "unknown batch")
    cp = bool(body.get("confirm_production"))
    steps = [("Upload the images", lambda: execute("upload", batch, confirm_production=cp)),
             ("Create the campaign and ad sets (paused)", lambda: execute("setup", batch, confirm_production=cp)),
             ("Create the ads (paused)", lambda: execute("prepare", batch, confirm_production=cp))]
    return {"job": start_job(f"retry {batch}", steps)["id"]}


# ---- drafts + history -----------------------------------------------------------------------------------------------------
DRAFTS = ROOT / "drafts"
DRAFT_ID = re.compile(r"^[a-z0-9]{6,12}$")


@router.get("/api/drafts")
def drafts():
    out = []
    for p in sorted(DRAFTS.glob("*.json"), key=lambda x: x.stat().st_mtime, reverse=True) if DRAFTS.exists() else []:
        d = jload(p, {})
        out.append({"id": p.stem, "title": d.get("title") or "Untitled", "updated": d.get("updated")})
    return out


@router.get("/api/drafts/{did}")
def get_draft(did: str):
    if not DRAFT_ID.match(did) or not (DRAFTS / f"{did}.json").exists():
        raise HTTPException(404, "no such draft")
    return jload(DRAFTS / f"{did}.json", {})


@router.put("/api/drafts/{did}")
async def put_draft(did: str, req: Request):
    if did == "new":
        did = uuid.uuid4().hex[:8]
    if not DRAFT_ID.match(did):
        raise HTTPException(400, "bad id")
    body = await req.json()
    jsave(DRAFTS / f"{did}.json", {"id": did, "title": body.get("title") or "Untitled", "updated": datetime.now().isoformat(timespec="seconds"), "answers": body.get("answers", {})})
    return {"id": did}


@router.delete("/api/drafts/{did}")
def del_draft(did: str):
    if DRAFT_ID.match(did):
        (DRAFTS / f"{did}.json").unlink(missing_ok=True)
    return {"deleted": True}


@router.get("/api/history")
def history():
    s = Settings()
    rows = [{"batch": k, **{x: v.get(x) for x in ("campaign", "goal", "budget", "ads", "adsets", "created")}, "answers": v.get("answers")} for k, v in Registry(s, "wizard_history.json").d.items()]
    return sorted(rows, key=lambda r: r.get("created") or "", reverse=True)


# ---- overview (live from Meta) --------------------------------------------------------------------------------------------
_CACHE: dict = {}


def _token_days(s: Settings):
    if not s.app_id:
        return None
    try:
        r = requests.get(f"https://graph.facebook.com/{s.version}/debug_token", params={"input_token": s.token, "access_token": f"{s.app_id}|{s.app_secret}"}, timeout=20).json().get("data", {})
        if r.get("expires_at"):
            return {"date": datetime.fromtimestamp(r["expires_at"], timezone.utc).strftime("%d %b %Y"), "days": int((r["expires_at"] - time.time()) // 86400)}
    except Exception:  # noqa: BLE001
        return None
    return None


@router.get("/api/overview")
def overview(refresh: bool = False):
    s = Settings()
    base = {"env": s.env, "account": s.account, "page_id": s.page_id}
    miss = s.missing()
    if miss:
        return {**base, "configured": False, "missing": miss}
    hit = _CACHE.get((s.env, s.account))
    if hit and not refresh and time.time() - hit["t"] < 45:
        return hit["data"]
    try:
        live = doctor.fetch_live(s)
        info = Meta(s).get(s.account, fields="name,currency")
    except MetaError as e:
        return {**base, "configured": True, "error": s.redact(e)}
    counts = {"campaigns": live["counts"]["campaigns"], "adsets": live["counts"]["adsets"], "ads": live["counts"]["ads"]}
    ads = [a for c in live["tree"] for st in c["children"] for a in st["children"]]
    counts["active_ads"] = sum(1 for a in ads if a["status"] == "ACTIVE")
    counts["paused_ads"] = sum(1 for a in ads if (a["status"] or "").endswith("PAUSED"))
    att = []
    td = _token_days(s)
    if td and td["days"] <= 60:
        att.append({"tone": "bad" if td["days"] <= 14 else "warn", "title": f"Your access token expires on {td['date']} ({max(td['days'], 0)} days)",
                    "text": "After that, creating and reading ads stops. Create a long-lived System User token in Business Settings and update .env."})
    bad = [a["name"] for a in ads if (a["status"] or "") in ("DISAPPROVED", "WITH_ISSUES")]
    if bad:
        att.append({"tone": "bad", "title": f"{len(bad)} ad(s) have problems", "text": "Meta flagged: " + ", ".join(bad[:4]) + ". Open them in Ads Manager to see the reason."})
    if not s.pixel_id:
        att.append({"tone": "info", "title": "No pixel connected", "text": f"Traffic campaigns work without it. For Sales, add META_{s.env.upper()}_PIXEL_ID to .env (python run.py discover finds it)."})
    mine = [k for k, v in Registry(s, "ad_registry.json").d.items() if v.get("status") == "PAUSED"]
    if mine:
        att.append({"tone": "good", "title": f"{len(mine)} launcher ad(s) are created but paused", "text": "Nothing is spending. When you are ready, turn them on from the Run page."})
    data = {**base, "configured": True, "account_name": info.get("name"), "currency": info.get("currency"), "counts": counts, "tree": live["tree"],
            "images": live["images"], "attention": att, "fetched": datetime.now().strftime("%H:%M:%S")}
    _CACHE[(s.env, s.account)] = {"t": time.time(), "data": data}
    return data


# ---- images already on Meta (with previews) ------------------------------------------------------------------------------
_IMG_CACHE: dict = {}
HEX32 = re.compile(r"^[0-9a-f]{32}$")


def _img(r: dict) -> dict:
    return {"hash": r.get("hash"), "name": r.get("name"), "width": r.get("width"), "height": r.get("height"), "created": (r.get("created_time") or "")[:10],
            "thumb": r.get("url_128") or r.get("url"), "full": r.get("url") or r.get("url_128"), "link": r.get("permalink_url")}


@router.get("/api/meta-images")
def meta_images(hashes: str | None = None, refresh: bool = False):
    """Images in the ad account with a thumbnail and the full-size image link. Meta's image links need no token."""
    s = Settings()
    if s.missing():
        raise HTTPException(400, "Missing in .env: " + ", ".join(s.missing()))
    meta = Meta(s)
    fields = "hash,name,width,height,created_time,url,url_128,permalink_url"
    try:
        if hashes:
            want = [h for h in hashes.split(",") if HEX32.match(h)][:20]
            if not want:
                raise HTTPException(400, "that is not an image hash (32 letters and digits)")
            rows = meta.get(f"{s.account}/adimages", hashes=json.dumps(want), fields=fields).get("data", [])
            return {"images": [_img(r) for r in rows]}
        hit = _IMG_CACHE.get((s.env, s.account))
        if hit and not refresh and time.time() - hit["t"] < 60:
            return hit["data"]
        rows = meta.pages(f"{s.account}/adimages", fields=fields, limit=100)
        data = {"images": sorted((_img(r) for r in rows), key=lambda x: x["created"] or "", reverse=True), "env": s.env, "account": s.account}
        _IMG_CACHE[(s.env, s.account)] = {"t": time.time(), "data": data}
        return data
    except MetaError as e:
        raise HTTPException(502, f"Meta said: {s.redact(e)[:300]}")
