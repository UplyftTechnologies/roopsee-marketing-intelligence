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
from src.common import (BID_STRATEGIES, BILLING_EVENTS, CTAS, DESTINATIONS, GOALS as GOALS_ALL, ROOT, LauncherError, Registry, Settings, account_cfg, adsets_cfg,
                        audiences_cfg, campaigns_cfg, clean_extra, deep_merge, jload, jsave)
from src.common import batch_files, jload
from src.meta_api import Meta, MetaError
from src import create_adsets, create_campaigns, create_creatives, media
from src.pipeline import execute
from ui.jobs import explain, start_job
from ui.formats import KINDS as FORMAT_KINDS, compile_ad

router = APIRouter()

GOALS = {
    "traffic": {"label": "Get visitors to the website", "short": "Traffic", "objective": "OUTCOME_TRAFFIC", "optimization": "LINK_CLICKS", "event": None,
                "help": "People click the ad and land on your site. No tracking setup needed."},
    "sales": {"label": "Get sales", "short": "Sales", "objective": "OUTCOME_SALES", "optimization": "OFFSITE_CONVERSIONS", "event": "PURCHASE",
              "help": "Meta looks for people likely to buy. Needs your pixel (dataset) connected."},
    "leads": {"label": "Get leads / sign-ups on the website", "short": "Leads", "objective": "OUTCOME_LEADS", "optimization": "OFFSITE_CONVERSIONS", "event": "LEAD",
              "help": "Meta looks for people likely to complete a sign-up or quiz. Needs your pixel and the event you track."},
    "engagement": {"label": "Get likes, comments and shares", "short": "Engagement", "objective": "OUTCOME_ENGAGEMENT", "optimization": "POST_ENGAGEMENT", "event": None,
                   "help": "Get more people interacting with your posts."},
    "awareness": {"label": "Get known (reach more people)", "short": "Awareness", "objective": "OUTCOME_AWARENESS", "optimization": "REACH", "event": None,
                  "help": "Show your ads to as many different people as possible. No tracking setup needed."},
}
# plain names for Meta's result / bid / billing choices (shown under "More options")
RESULT_LABELS = {"": "Use the campaign's default", "LINK_CLICKS": "Link clicks", "LANDING_PAGE_VIEWS": "Landing page views", "OFFSITE_CONVERSIONS": "Conversions on the website",
                 "VALUE": "Highest purchase value", "REACH": "Reach (different people)", "IMPRESSIONS": "Impressions (times shown)", "AD_RECALL_LIFT": "Ad recall",
                 "POST_ENGAGEMENT": "Post engagement", "PAGE_LIKES": "Page likes", "VIDEO_VIEWS": "Video views", "THRUPLAY": "ThruPlay (15s+ video views)",
                 "LEAD_GENERATION": "Leads (instant form)", "QUALITY_LEAD": "Quality leads", "CONVERSATIONS": "Messages", "APP_INSTALLS": "App installs",
                 "PROFILE_VISIT": "Instagram profile visits", "QUALITY_CALL": "Calls", "REPLIES": "Replies"}
BID_LABELS = {"": "Lowest cost (Meta decides)", "LOWEST_COST_WITHOUT_CAP": "Lowest cost (Meta decides)", "LOWEST_COST_WITH_BID_CAP": "Bid cap (never bid above my amount)",
              "COST_CAP": "Cost cap (aim for my average cost)", "LOWEST_COST_WITH_MIN_ROAS": "Minimum return on ad spend"}
BILLING_LABELS = {"": "Default", "IMPRESSIONS": "Pay per 1,000 impressions", "LINK_CLICKS": "Pay per link click", "THRUPLAY": "Pay per ThruPlay", "POST_ENGAGEMENT": "Pay per engagement"}
DEST_LABELS = {"": "Website", "WEBSITE": "Website", "APP": "App", "MESSENGER": "Messenger", "WHATSAPP": "WhatsApp", "INSTAGRAM_PROFILE": "Instagram profile", "PHONE_CALL": "Phone call",
               "ON_AD": "On the ad (instant form)", "ON_POST": "On the post", "ON_VIDEO": "On the video", "FACEBOOK": "Facebook page", "SHOP_AUTOMATIC": "Shop"}
RECIPES = [
    {"id": "traffic", "title": "Get website visits", "text": "Send people to your website or quiz. The simplest place to start.", "goal": "traffic", "placements": "instagram"},
    {"id": "sales", "title": "Sell on my website", "text": "Meta looks for people likely to buy. Needs your pixel.", "goal": "sales", "placements": "automatic", "needs_pixel": True},
    {"id": "leads", "title": "Get leads or sign-ups", "text": "People fill in a form or sign up on your website. Needs your pixel.", "goal": "leads", "placements": "automatic", "needs_pixel": True},
    {"id": "engagement", "title": "Get likes and comments", "text": "More people interacting with your posts.", "goal": "engagement", "placements": "automatic"},
    {"id": "awareness", "title": "Get known", "text": "Reach as many different people as possible.", "goal": "awareness", "placements": "automatic"},
]
AUDIENCES = {
    "all": {"label": "Everyone in India, 18 to 45", "short": "India 18-45", "countries": ["IN"], "age_min": 18, "age_max": 45, "gender": "all"},
    "women": {"label": "Women in India, 18 to 45", "short": "Women India 18-45", "countries": ["IN"], "age_min": 18, "age_max": 45, "gender": "women"},
}
PLACEMENTS = {
    "instagram": {"label": "Instagram only", "short": "Instagram", "list": ["instagram"]},
    "facebook_instagram": {"label": "Facebook and Instagram", "short": "FB+IG", "list": ["facebook", "instagram"]},
    "automatic": {"label": "Automatic (let Meta decide)", "short": "Auto", "list": ["automatic"]},
    "custom": {"label": "Custom (from your JSON or extra settings)", "short": "Custom", "list": ["custom"]},
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
            "recipes": RECIPES, "results": [{"value": k, "label": v} for k, v in RESULT_LABELS.items()], "bids": [{"value": k, "label": v} for k, v in BID_LABELS.items() if k],
            "billings": [{"value": k, "label": v} for k, v in BILLING_LABELS.items()], "destination_types": [{"value": k, "label": v} for k, v in DEST_LABELS.items()],
            "ctas": [{"value": c, "label": CTA_LABELS.get(c, c)} for c in sorted(CTAS)], "destinations": _dests(), "categories": cats}


# the ad account's own pixel, used when .env does not name one
_PIXELS: dict = {}


def _auto_pixel(s: Settings):
    key = (s.env, s.account)
    if key not in _PIXELS:
        _PIXELS[key] = None
        try:
            rows = Meta(s).get(f"{s.account}/adspixels", fields="id,name", limit=5).get("data", [])
            _PIXELS[key] = rows[0] if rows else None
        except MetaError:
            pass
    return _PIXELS[key]


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
    geo_extra = bool(((spec.get("targeting_extra") or {}).get("geo_locations")) or {})
    if not countries and geo_extra:  # the places (regions, cities, zips ...) come from the extra targeting instead of a whole country
        gl = {"all": "Everyone", "women": "Women", "men": "Men"}.get(c.get("gender", "all"), "Everyone")
        return {"label": f"{gl}, chosen places, {amin} to {amax}", "short": f"{gl} places {amin}-{amax}", "countries": [], "age_min": amin, "age_max": amax,
                "gender": c.get("gender", "all"), "key": None}, errs
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
    own = ((a.get("campaign") or {}).get("name") or "").strip()
    if own:  # the user chose the campaign name
        name = own
        if name in existing:
            errs.append(f"A campaign called '{name}' was already created with this launcher. Choose a different campaign name.")
    else:
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
        own_set = (sp.get("name") or "").strip()
        if own_set:  # the user chose this ad set's name
            nm = own_set
            if nm in taken:
                errs.append(f"{label}: the name '{nm}' is already used by another ad set. Choose a different name.")
        else:
            while nm in taken:
                m += 1
                nm = f"{nm0} | {m}"
        taken.add(nm)
        akey = aud["key"] or f"WIZ_{'_'.join(aud['countries'])}_{aud['gender']}_{aud['age_min']}_{aud['age_max']}".upper()
        if not aud["key"]:
            audiences[akey] = {"countries": aud["countries"], "age_min": aud["age_min"], "age_max": aud["age_max"], "genders": GENDERS.get(aud["gender"], [])}
            if not aud["countries"]:
                audiences[akey]["geo_in_adset"] = True
        eff_goal = (sp.get("goal") or "").strip() or goal["optimization"]
        if eff_goal not in GOALS_ALL:
            errs.append(f"{label}: I do not know the result '{eff_goal}'.")
        adset = {"key": nm, "campaign_key": name, "audience": akey, "placements": plc["list"], "optimization_goal": eff_goal}
        ev = (sp.get("event") or "").strip().upper() or (goal["event"] or "")
        if eff_goal in ("OFFSITE_CONVERSIONS", "VALUE"):
            adset["optimization_event"] = ev or "PURCHASE"
            if not s.pixel_id and not (sp.get("extra") or {}).get("promoted_object", {}).get("pixel_id"):
                px = _auto_pixel(s) if not s.missing() else None
                if px:
                    sp.setdefault("extra", {})
                    sp["extra"] = {**(sp["extra"] or {}), "promoted_object": {**((sp["extra"] or {}).get("promoted_object") or {}), "pixel_id": px["id"]}}
                    note = f"Using your pixel '{px.get('name')}' ({px['id']}), found in the ad account."
                    if note not in warns:
                        warns.append(note)
                else:
                    errs.append(f"{label}: a conversion goal needs your pixel (dataset) ID. Add META_{s.env.upper()}_PIXEL_ID to .env (python run.py discover finds it).")
        for k_in, k_out, allowed, nice in (("bid_strategy", "bid_strategy", BID_STRATEGIES, "bid strategy"), ("billing_event", "billing_event", BILLING_EVENTS, "billing"),
                                           ("destination_type", "destination_type", DESTINATIONS, "destination")):
            v = (sp.get(k_in) or "").strip().upper()
            if v and v not in allowed:
                errs.append(f"{label}: I do not know the {nice} '{v}'.")
            elif v:
                adset[k_out] = v
        if sp.get("bid_amount") not in (None, ""):
            try:
                if float(sp["bid_amount"]) <= 0:
                    raise ValueError
                adset["bid_amount"] = float(sp["bid_amount"])
            except (TypeError, ValueError):
                errs.append(f"{label}: the bid amount must be a number of rupees.")
        if adset.get("bid_strategy") in ("LOWEST_COST_WITH_BID_CAP", "COST_CAP") and not adset.get("bid_amount"):
            errs.append(f"{label}: this bid strategy needs a bid amount.")
        s_start, s_end = (sp.get("start_date") or start or None), (sp.get("end_date") or end or None)
        if s_start and s_end and s_end < s_start:
            errs.append(f"{label}: the end date is before the start date.")
        if per_set:
            life = sp.get("lifetime_budget") not in (None, "", 0, "0")
            try:
                bud = float(sp.get("lifetime_budget") if life else sp.get("daily_budget"))
                if bud <= 0:
                    raise ValueError
                adset["lifetime_budget" if life else "daily_budget"] = bud
            except (TypeError, ValueError):
                errs.append(f"{label}: enter a daily budget in rupees.")
            if life and not s_end:
                errs.append(f"{label}: a lifetime budget needs an end date.")
        if s_start:
            adset["start_time"] = f"{s_start}T00:00:00+0530"
        if s_end:
            adset["end_time"] = f"{s_end}T23:59:00+0530"
        for key in ("targeting_extra", "extra"):
            val = sp.get(key)
            if val in (None, "", {}):
                continue
            if not isinstance(val, dict):
                errs.append(f"{label}: the extra settings ({key}) must be a JSON object.")
                continue
            clean, dropped = clean_extra(val)
            if dropped:
                warns.append(f"{label}: these extra settings are not allowed and were dropped: {', '.join(dropped)}.")
            adset[key] = clean
        sets_out.append(adset)
        uid_index[sp.get("uid", f"s{i + 1}")] = i
        sp["_aud"], sp["_plc"] = aud, plc
    if not sets_out:
        errs.append("Add at least one ad set.")

    # an ad shown in several ad sets becomes one ad per ad set (the first keeps the plain ID, the others get _S2, _S3 ...)
    ads, used = [], set()
    per_set_count = [0] * len(sets_out)
    # Ad IDs are internal: any ad without a valid, unique one gets the next free one (a local image keeps its file name, which is its ID)
    raw_ads = [dict(x) for x in (a.get("ads") or [])]
    local = lambda x: bool((x.get("image") or "").strip()) and x.get("creative_spec") is None and not x.get("kind")
    claimed: set = set()
    for ad in raw_ads:
        k = Path(ad["image"].strip()).stem if local(ad) else (ad.get("ad_key") or "").strip()
        if local(ad):
            claimed.add(k)
        elif re.fullmatch(r"RS_[A-Z0-9]+_\d{3}", k) and k not in claimed:
            claimed.add(k)
            ad["ad_key"] = k
        else:
            ad["ad_key"] = ""
    for ad in raw_ads:
        if not local(ad) and not ad["ad_key"]:
            ad["ad_key"] = next_ad_key(ad.get("kind") or ("COPY" if ad.get("creative_spec") is not None else "IMAGE"), claimed)
            claimed.add(ad["ad_key"])
    for i, ad in enumerate(raw_ads, 1):
        tag = f"Ad {i}"
        ad_patch: dict = {}
        if ad.get("kind") in FORMAT_KINDS:  # built here from scratch: video, carousel, existing post, Advantage+, catalog
            ad = {**ad, "_tag": tag}
            cspec, ad_patch, e1, w1 = compile_ad(ad)
            warns += w1
            if not re.fullmatch(r"RS_[A-Z0-9]+_\d{3}", (ad.get("ad_key") or "").strip()):
                e1.append(f"{tag}: this ad needs an Ad ID like RS_SKINCARE_001 (letters and digits, then a 3-digit number).")
            if e1:
                errs += e1
                continue
            ad = {**ad, "creative_spec": cspec}
        if ad.get("creative_spec") is not None:  # a whole creative (carousel, video, catalog, dynamic, existing post...) copied from Meta or imported
            skey = (ad.get("ad_key") or "").strip()
            cs = ad["creative_spec"]
            if not re.fullmatch(r"RS_[A-Z0-9]+_\d{3}", skey):
                errs.append(f"{tag}: this ad needs an Ad ID like RS_SKINCARE_001 (letters and digits, then a 3-digit number).")
            if not isinstance(cs, dict) or not (cs.get("object_story_spec") or cs.get("asset_feed_spec") or cs.get("object_story_id")):
                errs.append(f"{tag}: the creative needs object_story_spec, asset_feed_spec or object_story_id.")
                cs = {}
            else:
                from src.spec_clean import clean_creative
                cs, notes = clean_creative(cs, s.page_id, s.instagram_id)
                warns += [f"{tag}: {n}" for n in notes if n.startswith("this ad uses")]
            targets = sorted({uid_index[u] for u in (ad.get("sets") or list(uid_index)) if u in uid_index})
            if not targets:
                errs.append(f"{tag}: choose at least one ad set for it to appear in.")
            for pos, si in enumerate(targets):
                k = skey if pos == 0 else f"{skey}_S{si + 1}"
                if k in used:
                    errs.append(f"{tag}: the same ad ID is used twice.")
                used.add(k)
                entry = {"ad_key": k, "adset_key": sets_out[si]["key"], "creative_spec": cs, "status": "READY"}
                if (ad.get("name") or "").strip():
                    entry["name"] = ad["name"].strip() if pos == 0 else f"{ad['name'].strip()} - ad set {si + 1}"
                if isinstance(ad.get("extra"), dict) and ad["extra"]:
                    entry["extra"] = clean_extra(ad["extra"])[0]
                ads.append(entry)
                per_set_count[si] += 1
                if ad_patch:
                    sets_out[si]["extra"] = deep_merge(sets_out[si].get("extra") or {}, ad_patch)
            continue
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
            if (ad.get("name") or "").strip():
                entry["name"] = ad["name"].strip() if pos == 0 else f"{ad['name'].strip()} - ad set {si + 1}"
            if ad.get("description"):
                entry["description"] = ad["description"].strip()
            for xk in ("extra", "link_extra"):
                if isinstance(ad.get(xk), dict) and ad[xk]:
                    cl, dr = clean_extra(ad[xk])
                    if dr:
                        warns.append(f"{tag}: these extra settings are not allowed and were dropped: {', '.join(dr)}.")
                    entry[xk] = cl
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
    co = a.get("campaign") or {}
    if not per_set:  # shared budget: Meta keeps the bid strategy on the campaign, so lift it off the ad sets
        wanted = [x["bid_strategy"] for x in sets_out if x.get("bid_strategy")]
        if wanted and not co.get("bid_strategy"):
            co = {**co, "bid_strategy": wanted[0]}
            warns.append("With one budget for the whole campaign, the bid strategy is set on the campaign, so '" + BID_LABELS.get(wanted[0], wanted[0]) + "' now applies to every ad set.")
        for x in sets_out:
            x.pop("bid_strategy", None)
        if any(x.get("bid_amount") for x in sets_out) and (co.get("bid_strategy") or "LOWEST_COST_WITHOUT_CAP") not in ("LOWEST_COST_WITH_BID_CAP", "COST_CAP"):
            errs.append("A bid amount only works with a bid cap or cost cap. Pick one of those under the campaign's More options, or remove the bid amount.")
    if co.get("spend_cap") not in (None, ""):
        try:
            camp["spend_cap"] = float(co["spend_cap"])
            if camp["spend_cap"] <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errs.append("The campaign spending limit must be a number of rupees.")
    if co.get("bid_strategy") and not per_set:
        if str(co["bid_strategy"]).upper() in BID_STRATEGIES:
            camp["bid_strategy"] = str(co["bid_strategy"]).upper()
        else:
            errs.append(f"I do not know the campaign bid strategy '{co['bid_strategy']}'.")
    # minimum return on ad spend: the target lives on each ad set (bid_constraints), in Meta's units (x10000)
    eff = None if per_set else (camp.get("bid_strategy") or "LOWEST_COST_WITHOUT_CAP")
    for j, (x, sp) in enumerate(zip(sets_out, set_specs)):
        if (x.get("bid_strategy") or eff) != "LOWEST_COST_WITH_MIN_ROAS":
            continue
        r = sp.get("roas") or co.get("roas")
        try:
            r = float(r)
            if r <= 0:
                raise ValueError
        except (TypeError, ValueError):
            errs.append(f"Ad set {j + 1}: a minimum return on ad spend needs the target, for example 2.5 (every 1 rupee spent should bring back 2.5).")
            continue
        x["extra"] = deep_merge(x.get("extra") or {}, {"bid_constraints": {"roas_average_floor": int(round(r * 10000))}})
        if x.get("optimization_goal") != "VALUE":  # Meta only allows a minimum return when optimising for conversion value
            x["optimization_goal"] = "VALUE"
            x.setdefault("optimization_event", "PURCHASE")
            note = "A minimum return on ad spend needs the result 'Highest purchase value', so that was chosen for you (it needs your pixel and purchase values)."
            if note not in warns:
                warns.append(note)
    if co.get("special_ad_categories"):
        cats = [str(x).upper() for x in co["special_ad_categories"] if x and str(x).upper() != "NONE"]
        if "CREDIT" in cats:
            errs.append("Meta replaced the Credit category with 'Financial products and services'. Pick that one instead.")
        camp["special_ad_categories"] = cats
        if cats:
            country = [c.strip().upper() for c in str(co.get("special_ad_category_country") or "IN").split(",") if c.strip()]
            if not country or not all(len(c) == 2 and c.isalpha() for c in country):
                errs.append("The special ad category needs a country code such as IN.")
            else:
                camp.setdefault("extra", {})["special_ad_category_country"] = country
            warns.append("Special ad categories (" + ", ".join(cats) + ") limit targeting: Meta ignores age, gender, postcodes and lookalike audiences for these ads, and may reject ad sets that ask for them.")
    if isinstance(co.get("extra"), dict) and co["extra"]:
        clean, dropped = clean_extra(co["extra"])
        if dropped:
            warns.append("Campaign: these extra settings are not allowed and were dropped: " + ", ".join(dropped) + ".")
        camp["extra"] = {**camp.get("extra", {}), **clean}
    batch = f"batch_wiz_{now.strftime('%Y%m%d_%H%M')}"
    total = sum(x.get("daily_budget", 0) for x in sets_out) if per_set else daily
    return {"errors": errs, "warnings": warns, "campaign": camp, "adsets": sets_out, "audiences": audiences, "ads": ads, "batch": batch,
            "batch_id": f"ROOPSEE_WIZ_{now.strftime('%Y%m%d_%H%M')}", "names": {"campaign": name, "adsets": [x["key"] for x in sets_out]},
            "summary": {"goal": goal["label"], "budget_mode": "adset" if per_set else "campaign", "daily_budget": daily, "total_budget": total, "ads": len(ads), "start": start, "end": end, "campaign_name": name,
                        "ad_list": [{"name": x.get("name") or x["ad_key"], "id": x["ad_key"], "adset": x["adset_key"]} for x in ads],
                        "adsets": [{"name": x["key"], "audience": sp["_aud"]["label"], "placements": sp["_plc"]["label"], "budget": x.get("daily_budget") or x.get("lifetime_budget"),
                                    "goal": RESULT_LABELS.get(x["optimization_goal"], x["optimization_goal"]), "bid": BID_LABELS.get(x.get("bid_strategy", ""), x.get("bid_strategy", "")),
                                    "extras": sorted(k for k in ("targeting_extra", "extra") if x.get(k)), "ads": per_set_count[j]}
                                   for j, (x, sp) in enumerate(zip(sets_out, set_specs))]}}


def next_ad_key(theme: str, taken=()) -> str:
    """The next unused internal ad ID for a theme, e.g. skincare -> RS_SKINCARE_001 (IDs are never reused). `taken` = IDs already claimed in the plan being built."""
    tag = re.sub(r"[^A-Z0-9]", "", str(theme).upper())
    if not tag:
        raise ValueError("a theme is needed")
    used = {p.stem for p in (ROOT / "creatives").rglob("*") if p.is_file()} | set(taken)
    for f in batch_files():
        used |= {x.get("ad_key") for x in jload(f, {}).get("ads", [])}
    for env in ("sandbox", "production"):
        used |= set(Registry(Settings(env), "ad_registry.json").d)
    nums = [int(k.rsplit("_", 1)[1]) for k in used if k and k.startswith(f"RS_{tag}_") and k.rsplit("_", 1)[1].isdigit()]
    return f"RS_{tag}_{max(nums, default=0) + 1:03d}"


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


# ---- "Check with Meta": would Meta accept this? Uses Meta's validate-only mode, so NOTHING is created ----------------------------
def _one(kind: str, name: str, fn, s: Settings) -> dict:
    try:
        fn()
        return {"object": kind, "name": name, "ok": True, "message": "Meta accepts this."}
    except (MetaError, LauncherError) as e:
        msg = s.redact(e)
        plain = msg.split(" -> ", 1)[-1]
        plain = plain.split(" (code ", 1)[0].replace(" | ", ": ")
        return {"object": kind, "name": name, "ok": False, "message": msg[:420], "plain": plain[:300], "hint": (explain(msg) or [None])[0]}


_CHECK_CACHE: dict = {}


def _cached(key, ttl, fn):
    hit = _CHECK_CACHE.get(key)
    if hit and time.time() - hit[0] < ttl:
        return hit[1]
    val = fn()
    _CHECK_CACHE[key] = (time.time(), val)
    return val


def _parent_campaign(meta: Meta, s: Settings, camp: dict):
    """Meta can only check an ad set against an existing campaign, so borrow one with the same goal and budget type (nothing is changed on it)."""
    rows = _cached((s.env, s.account, "parents"), 300, lambda: meta.get(f"{s.account}/campaigns", fields="id,name,objective,daily_budget,lifetime_budget,effective_status,bid_strategy", limit=100).get("data", []))
    want_cbo = camp["budget_strategy"] == "CBO"
    ok = [r for r in rows if r.get("objective") == camp["objective"] and r.get("effective_status") not in ("DELETED", "ARCHIVED")]
    capped = ("LOWEST_COST_WITH_BID_CAP", "COST_CAP", "LOWEST_COST_WITH_MIN_ROAS")
    want_bs = camp.get("bid_strategy")
    ok.sort(key=lambda r: (bool(r.get("daily_budget") or r.get("lifetime_budget")) != want_cbo, (r.get("bid_strategy") != want_bs) if want_bs in capped else r.get("bid_strategy") in capped, r.get("effective_status") != "PAUSED"))
    if not ok:
        return None
    r = ok[0]
    r["_cbo"] = bool(r.get("daily_budget") or r.get("lifetime_budget"))
    return r


@router.post("/api/wizard/check")
async def check(req: Request):
    answers = await req.json()
    s = Settings()
    plan = build_plan(answers, s)
    if plan["errors"]:
        return {"ok": False, "plan_errors": plan["errors"], "warnings": plan["warnings"], "checks": []}
    if s.missing():
        raise HTTPException(400, "Missing in .env: " + ", ".join(s.missing()))
    meta, acc, checks = Meta(s), account_cfg(), []
    try:
        cp = create_campaigns.payload(plan["campaign"], acc)
        checks.append(_one("Campaign", plan["names"]["campaign"], lambda: meta.post(f"{s.account}/campaigns", cp, validate_only=True), s))
        parent = _parent_campaign(meta, s, plan["campaign"])
        saved = audiences_cfg()
        for adset in plan["adsets"]:
            if not parent:
                checks.append({"object": "Ad set", "name": adset["key"], "ok": None,
                               "message": "Not pre-checked: your account has no campaign with the same goal and budget type to test against. It will be checked when it is created."})
                continue
            aud = plan["audiences"].get(adset["audience"]) or saved.get(adset["audience"]) or {"countries": ["IN"]}
            try:
                payload = create_adsets.payload(adset, parent["id"], s, acc, plan["campaign"], aud)
            except LauncherError as e:
                checks.append({"object": "Ad set", "name": adset["key"], "ok": False, "message": s.redact(e)})
                continue
            note = ""
            if (plan["campaign"]["budget_strategy"] == "CBO") != parent["_cbo"]:  # the borrowed campaign budgets differently, so test with a matching stand-in budget
                if parent["_cbo"]:
                    for k in ("daily_budget", "lifetime_budget", "bid_strategy", "bid_amount"):
                        payload.pop(k, None)
                else:
                    payload["daily_budget"] = 50000
                note = " (checked with a stand-in budget)"
            r_ = _one("Ad set", adset["key"], lambda p=payload: meta.post(f"{s.account}/adsets", p, validate_only=True), s)
            if r_["ok"]:
                r_["message"] += note
            checks.append(r_)
        # creatives: one check per distinct ad text (borrowing any image from the account when the real one is not uploaded yet)
        stand_in = None
        seen = set()
        for ad in plan["ads"]:
            if ad.get("creative_spec"):
                import json as _json
                sig = _json.dumps(ad["creative_spec"], sort_keys=True)
                if sig in seen or len(seen) >= 4:
                    continue
                seen.add(sig)
                stand = None
                refs = media.files_in(ad["creative_spec"])
                if refs:  # files are uploaded at create time, so test with stand-ins taken from the account
                    stand = {"image_hash": "", "video_id": "", "thumb": ""}
                    if any(media.kind_of(r) == "image" for r in refs):
                        rows = _cached((s.env, s.account, "image"), 300, lambda: meta.get(f"{s.account}/adimages", fields="hash", limit=1).get("data", []))
                        stand["image_hash"] = rows[0]["hash"] if rows else ""
                    if any(media.kind_of(r) == "video" for r in refs):
                        vr = _cached((s.env, s.account, "video"), 300, lambda: meta.get(f"{s.account}/advideos", fields="id,picture", limit=1).get("data", []))
                        stand["video_id"], stand["thumb"] = (vr[0]["id"], vr[0].get("picture", "")) if vr else ("", "")
                    if (not stand["image_hash"] and any(media.kind_of(r) == "image" for r in refs)) or (not stand["video_id"] and any(media.kind_of(r) == "video" for r in refs)):
                        checks.append({"object": "Ad", "name": ad["ad_key"], "ok": None, "message": "Not pre-checked: your ad account has no image or video to test with yet."})
                        continue
                payload = create_creatives.spec_payload(ad, plan["batch_id"], s, acc, stand_in=stand)
                checks.append(_one("Ad", ad["ad_key"], lambda p=payload: meta.post(f"{s.account}/adcreatives", p, validate_only=True), s))
                continue
            sig = (ad["primary_text"], ad["headline"], ad["destination"], ad["cta"], ad.get("image_hash") or ad.get("image"))
            if sig in seen or len(seen) >= 4:
                continue
            seen.add(sig)
            h = ad.get("image_hash")
            if not h:
                if stand_in is None:
                    rows = _cached((s.env, s.account, "image"), 300, lambda: meta.get(f"{s.account}/adimages", fields="hash", limit=1).get("data", []))
                    stand_in = rows[0]["hash"] if rows else ""
                h = stand_in
            if not h:
                checks.append({"object": "Ad", "name": ad["ad_key"], "ok": None, "message": "Not pre-checked: there is no image in your ad account yet to test with."})
                continue
            payload = create_creatives.payload(ad, h, plan["batch_id"], s, acc)
            checks.append(_one("Ad", ad["ad_key"], lambda p=payload: meta.post(f"{s.account}/adcreatives", p, validate_only=True), s))
    except MetaError as e:
        if "code 17" in str(e) or "too many calls" in str(e).lower():
            raise HTTPException(429, "Meta is limiting how often this ad account can be asked. Wait a few minutes and press Check again.")
        raise HTTPException(502, f"Meta said: {s.redact(e)[:300]}")
    bad = [c for c in checks if c["ok"] is False]
    return {"ok": not bad and any(c["ok"] for c in checks), "plan_errors": [], "warnings": plan["warnings"], "checks": checks, "tested_against": parent["name"] if parent else None}
