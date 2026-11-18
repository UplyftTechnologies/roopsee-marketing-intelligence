"""Ad set JSON in -> ad set form values out. Reads the launcher's own friendly format AND Meta's raw ad set JSON, and says exactly
what it understood, converted, kept as extra, ignored, and what looks wrong. The file is only ever read as data."""
from __future__ import annotations

import json
import time
from typing import Any

from fastapi import APIRouter, HTTPException, Request

from src.common import BID_STRATEGIES, BILLING_EVENTS, DESTINATIONS, FORBIDDEN_EXTRA, GOALS, Settings, account_cfg, audiences_cfg
from src.meta_api import Meta, MetaError
from src.special import adset_findings

router = APIRouter()
MAX_BYTES = 200 * 1024
MAX_ADSETS = 10

RESULT_ALIASES = {  # friendly words -> Meta's optimisation goal
    "clicks": "LINK_CLICKS", "link_clicks": "LINK_CLICKS", "landing_page_views": "LANDING_PAGE_VIEWS", "page_views": "LANDING_PAGE_VIEWS",
    "purchases": "OFFSITE_CONVERSIONS", "sales": "OFFSITE_CONVERSIONS", "conversions": "OFFSITE_CONVERSIONS", "value": "VALUE",
    "reach": "REACH", "impressions": "IMPRESSIONS", "video_views": "VIDEO_VIEWS", "thruplay": "THRUPLAY", "engagement": "POST_ENGAGEMENT",
    "leads": "LEAD_GENERATION", "messages": "CONVERSATIONS", "conversations": "CONVERSATIONS", "installs": "APP_INSTALLS", "recall": "AD_RECALL_LIFT",
    "page_likes": "PAGE_LIKES", "profile_visits": "PROFILE_VISIT", "calls": "QUALITY_CALL",
}
PRESET_PLACES = {frozenset(["instagram"]): "instagram", frozenset(["facebook", "instagram"]): "facebook_instagram"}
PLACE_WORDS = {"instagram": "instagram", "facebook_instagram": "facebook_instagram", "automatic": "automatic", "auto": "automatic", "custom": "custom"}
POSITION_KEYS = ("facebook_positions", "instagram_positions", "messenger_positions", "audience_network_positions", "device_platforms", "user_os", "user_device")
META_KEYS = {"optimization_goal", "targeting", "promoted_object", "bid_strategy", "bid_amount", "destination_type", "campaign_id", "attribution_spec", "pacing_type"}  # words only Meta's own JSON uses
IGNORED_META = {"id", "account_id", "campaign_id", "adset_id", "status", "effective_status", "configured_status", "created_time", "updated_time", "name",
                "issues_info", "recommendations", "bid_info", "learning_stage_info", "campaign", "adlabels", "source_adset_id",
                "targeting_optimization_types", "ads", "insights"}


def _num(v):
    try:
        f = float(v)
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return None


def _gender(g) -> str:
    g = [x for x in (g or []) if x in (1, 2)]
    return "men" if g == [1] else "women" if g == [2] else "all"


def _blank() -> dict:
    return {"audience": "custom", "custom": {"countries": "IN", "age_min": 18, "age_max": 45, "gender": "all"}, "placements": "automatic",
            "daily_budget": "", "lifetime_budget": "", "goal": "", "event": "", "bid_strategy": "", "bid_amount": "", "billing_event": "", "destination_type": "",
            "start_date": "", "end_date": "", "targeting_extra": {}, "extra": {}, "label": ""}


def _extras(d, where, rep) -> dict:
    if d in (None, {}):
        return {}
    if not isinstance(d, dict):
        rep["warnings"].append(f"{where} must be an object; it was ignored.")
        return {}
    bad = sorted(k for k in d if k in FORBIDDEN_EXTRA)
    if bad:
        rep["ignored"] += [f"{where}.{k}" for k in bad]
    return {k: v for k, v in d.items() if k not in FORBIDDEN_EXTRA}


# ---- Meta's raw ad set JSON -------------------------------------------------------------------------------------------------
def from_meta(raw: dict, offset: int, rep: dict) -> dict:
    f = _blank()
    if raw.get("name"):
        f["label"] = str(raw["name"])
        rep["filled"].append("name (kept as a label; the launcher makes its own names)")
    t = dict(raw.get("targeting") or {})
    geo = dict(t.pop("geo_locations", {}) or {})
    countries = geo.pop("countries", None)
    if countries:
        f["custom"]["countries"] = ", ".join(countries)
        rep["filled"].append("countries")
    elif geo:  # regions, cities, zips ... without a whole country: adding India on top would make Meta reject it as conflicting
        f["custom"]["countries"] = ""
        rep["converted"].append("no whole country is targeted, only the places listed under extra targeting")
    if geo:  # cities, regions, radius, location types ...
        f["targeting_extra"]["geo_locations"] = geo
        rep["kept_as_extra"].append("targeting.geo_locations (" + ", ".join(sorted(geo)) + ")")
    if "age_min" in t:
        f["custom"]["age_min"] = t.pop("age_min")
        rep["filled"].append("youngest age")
    if "age_max" in t:
        f["custom"]["age_max"] = t.pop("age_max")
        rep["filled"].append("oldest age")
    if "genders" in t:
        f["custom"]["gender"] = _gender(t.pop("genders"))
        rep["filled"].append("gender")
    plats = t.pop("publisher_platforms", None)
    has_pos = any(k in t for k in POSITION_KEYS)
    if plats:
        preset = PRESET_PLACES.get(frozenset(plats))
        if preset:
            f["placements"] = preset
        else:
            f["placements"] = "custom"
            f["targeting_extra"]["publisher_platforms"] = plats
            rep["kept_as_extra"].append("targeting.publisher_platforms (" + ", ".join(plats) + ")")
        rep["filled"].append("placements")
    elif has_pos:
        f["placements"] = "custom"
    for k in POSITION_KEYS:
        if k in t:
            f["targeting_extra"][k] = t.pop(k)
            rep["kept_as_extra"].append(f"targeting.{k}")
    if t:  # interests, behaviours, custom audiences, exclusions, languages, advantage settings ...
        f["targeting_extra"].update(t)
        rep["kept_as_extra"] += [f"targeting.{k}" for k in sorted(t)]
    if raw.get("optimization_goal"):
        f["goal"] = raw["optimization_goal"]
        rep["filled"].append("goal (" + raw["optimization_goal"] + ")")
        if raw["optimization_goal"] not in GOALS:
            rep["warnings"].append(f"goal {raw['optimization_goal']} is not one I know; Meta's check will tell you whether it is valid here.")
    po = dict(raw.get("promoted_object") or {})
    if po.get("custom_event_type"):
        f["event"] = po.pop("custom_event_type")
        rep["filled"].append("conversion event")
    if po:  # pixel_id, product_set_id, application_id, page_id ...
        f["extra"]["promoted_object"] = po
        rep["kept_as_extra"].append("promoted_object (" + ", ".join(sorted(po)) + ")")
    for key, label in (("bid_strategy", "bid strategy"), ("billing_event", "billing event"), ("destination_type", "destination")):
        if raw.get(key) and raw[key] != "UNDEFINED":  # UNDEFINED means "Meta's default"
            f[key] = raw[key]
            rep["filled"].append(label)
    if raw.get("bid_amount") is not None and _num(raw["bid_amount"]) is not None:
        f["bid_amount"] = round(_num(raw["bid_amount"]) / offset, 2)
        rep["converted"].append(f"bid amount {raw['bid_amount']} -> {f['bid_amount']} (rupees)")
    for key in ("daily_budget", "lifetime_budget"):
        if raw.get(key) is not None and _num(raw[key]):
            f[key] = round(_num(raw[key]) / offset, 2)
            rep["converted"].append(f"{key.replace('_', ' ')} {raw[key]} -> {f[key]} (rupees)")
    for key in ("start_time", "end_time"):
        if raw.get(key):
            f["start_date" if key == "start_time" else "end_date"] = str(raw[key])[:10]
            rep["filled"].append(key.replace("_time", " date"))
            if "T" in str(raw[key]) and not str(raw[key]).split("T")[1].startswith(("00:00", "23:59")):
                rep["converted"].append(f"{key} keeps only the date ({str(raw[key])[:10]})")
    for k in ("attribution_spec", "pacing_type", "adset_schedule", "frequency_control_specs", "dsa_beneficiary", "dsa_payor", "is_dynamic_creative", "min_budget_spend_percentage",
              "daily_min_spend_target", "daily_spend_cap", "lifetime_min_spend_target", "lifetime_spend_cap", "multi_optimization_goal_weight", "optimization_sub_event", "bid_constraints", "regional_regulated_categories"):
        if k in raw and raw[k] not in (None, [], {}):
            f["extra"][k] = raw[k]
            rep["kept_as_extra"].append(k)
    if str(raw.get("status", "PAUSED")).upper() == "ACTIVE":
        rep["warnings"].append("This ad set was ACTIVE in the file. It will be created PAUSED; you turn it on yourself later.")
    ignored = [k for k in raw if k in IGNORED_META]
    rep["ignored"] += [k for k in ignored if k not in ("name", "status")]
    known = set(META_KEYS) | IGNORED_META | {"billing_event", "daily_budget", "lifetime_budget", "start_time", "end_time", "targeting", "attribution_spec", "pacing_type", "adset_schedule",
                                             "frequency_control_specs", "dsa_beneficiary", "dsa_payor", "min_budget_spend_percentage", "daily_min_spend_target", "daily_spend_cap",
                                             "lifetime_min_spend_target", "lifetime_spend_cap", "multi_optimization_goal_weight", "optimization_sub_event", "bid_constraints",
                                             "regional_regulated_categories"}
    for k, v in raw.items():
        if k not in known and v not in (None, [], {}):
            f["extra"][k] = v
            rep["kept_as_extra"].append(k)
    return f


# ---- the launcher's own friendly format --------------------------------------------------------------------------------------
def from_launcher(raw: dict, saved: dict, rep: dict) -> dict:
    f = _blank()
    if raw.get("name"):
        f["label"] = str(raw["name"])
        rep["filled"].append("name (kept as a label)")
    res = raw.get("result") or raw.get("goal")
    if res:
        r = str(res).strip()
        goal = RESULT_ALIASES.get(r.lower().replace(" ", "_")) or (r.upper() if r.upper() in GOALS else None)
        if goal:
            f["goal"] = goal
            rep["filled"].append(f"result -> {goal}")
        else:
            rep["warnings"].append(f"I do not know the result '{r}'. Known: {', '.join(sorted(set(RESULT_ALIASES)))}.")
    aud = raw.get("audience")
    if isinstance(aud, str):
        if aud in saved:
            f["audience"] = aud
            rep["filled"].append(f"audience (saved: {aud})")
        elif aud.lower() in ("all", "women"):
            f["audience"] = aud.lower()
            rep["filled"].append(f"audience ({aud.lower()})")
        else:
            rep["warnings"].append(f"Audience '{aud}' is not one of your saved audiences, so the default was kept.")
    elif isinstance(aud, dict):
        a = dict(aud)
        c = a.pop("countries", None)
        if c:
            f["custom"]["countries"] = ", ".join(c) if isinstance(c, list) else str(c)
        elif c is not None:  # an empty list: the places come from targeting_extra
            f["custom"]["countries"] = ""
        age = a.pop("age", None)
        if isinstance(age, (list, tuple)) and len(age) == 2:
            f["custom"]["age_min"], f["custom"]["age_max"] = age
        for k in ("age_min", "age_max"):
            if k in a:
                f["custom"][k] = a.pop(k)
        if "gender" in a:
            g = str(a.pop("gender")).lower()
            f["custom"]["gender"] = g if g in ("all", "women", "men") else "all"
        rep["filled"].append("audience (countries, age, gender)")
        for k in ("cities", "regions", "interests", "behaviors", "behaviours"):
            if k in a:
                rep["warnings"].append(f"audience.{k} by name is not converted yet. Put Meta's own targeting in targeting_extra instead (it needs Meta's ids).")
                a.pop(k)
        if a:
            clean = _extras(a, "audience", rep)
            f["targeting_extra"].update(clean)
            rep["kept_as_extra"] += [f"audience.{k}" for k in clean]
    pl = raw.get("placements")
    if pl is not None:
        if isinstance(pl, str):
            p = PLACE_WORDS.get(pl.lower())
        else:
            p = PRESET_PLACES.get(frozenset(x.lower() for x in pl)) or ("custom" if pl else None)
            if p == "custom":
                f["targeting_extra"]["publisher_platforms"] = [x.lower() for x in pl]
        if p:
            f["placements"] = p
            rep["filled"].append(f"placements ({p})")
        else:
            rep["warnings"].append(f"Placements '{pl}' not understood; use instagram, facebook_instagram, automatic, or a list of platforms.")
    b = raw.get("budget") or {}
    if isinstance(b, dict):
        for src, dst in (("daily", "daily_budget"), ("lifetime", "lifetime_budget")):
            if b.get(src) is not None and _num(b[src]):
                f[dst] = _num(b[src])
                rep["filled"].append(dst.replace("_", " "))
    elif _num(b):
        f["daily_budget"] = _num(b)
        rep["filled"].append("daily budget")
    elif b not in ({}, None, ""):
        rep["warnings"].append("The budget was not understood. Use {\"daily\": 500} (in rupees).")
    sch = raw.get("schedule") or {}
    for src, dst in (("start", "start_date"), ("end", "end_date")):
        if sch.get(src):
            f[dst] = str(sch[src])[:10]
            rep["filled"].append(dst.replace("_", " "))
    bid = raw.get("bid") or {}
    if bid.get("strategy"):
        s = str(bid["strategy"]).upper()
        f["bid_strategy"] = s
        rep["filled"].append("bid strategy")
        if s not in BID_STRATEGIES:
            rep["warnings"].append(f"Bid strategy {s} is not one of {sorted(BID_STRATEGIES)}.")
    if bid.get("amount") is not None and _num(bid["amount"]):
        f["bid_amount"] = _num(bid["amount"])
        rep["filled"].append("bid amount")
    ev = (raw.get("conversion") or {}).get("event") if isinstance(raw.get("conversion"), dict) else None
    if ev:
        f["event"] = str(ev).upper()
        rep["filled"].append("conversion event")
    elif f["goal"] == "OFFSITE_CONVERSIONS":
        f["event"] = "PURCHASE"
        rep["converted"].append("conversion event not given, so PURCHASE was used")
    for key, label in (("destination", "destination_type"), ("billing_event", "billing_event")):
        if raw.get(key):
            f[label] = str(raw[key]).upper()
            rep["filled"].append(label.replace("_", " "))
    f["targeting_extra"].update(_extras(raw.get("targeting_extra"), "targeting_extra", rep))
    f["extra"].update(_extras(raw.get("extra"), "extra", rep))
    if f["targeting_extra"]:
        rep["kept_as_extra"].append("targeting_extra")
    if f["extra"]:
        rep["kept_as_extra"].append("extra")
    known = {"format", "version", "name", "result", "goal", "audience", "placements", "budget", "schedule", "bid", "conversion", "destination", "billing_event", "targeting_extra", "extra", "status"}
    unknown = [k for k in raw if k not in known]
    if unknown:
        rep["warnings"].append("Not understood and ignored: " + ", ".join(unknown))
    if str(raw.get("status", "PAUSED")).upper() == "ACTIVE":
        rep["warnings"].append("The file said ACTIVE. It will be created PAUSED; you turn it on yourself later.")
    return f


def _looks_meta(o: dict) -> bool:
    if o.get("format") == "roopsee-adset" or "result" in o or "audience" in o or "placements" in o:  # the launcher's own markers win
        return False
    return bool(META_KEYS & set(o)) or (any(k in o for k in ("daily_budget", "lifetime_budget")) and "budget" not in o)


def convert(data: Any, offset: int = 100) -> dict:
    saved = audiences_cfg()
    rep: dict = {"format": None, "count": 0, "filled": [], "converted": [], "kept_as_extra": [], "ignored": [], "warnings": [], "errors": [], "special": []}
    items: list = []
    fmt = None
    if isinstance(data, dict) and isinstance(data.get("data"), list):  # a Graph API list response
        items, fmt = data["data"], "meta"
    elif isinstance(data, dict) and isinstance(data.get("adsets"), list):
        items = data["adsets"]
        if data.get("format") == "roopsee-adset":
            fmt = "launcher"
    elif isinstance(data, list):
        items = data
    elif isinstance(data, dict):
        items = [data]
    else:
        rep["errors"].append("The file must hold an ad set (an object) or a list of ad sets.")
    items = [x for x in items if isinstance(x, dict)]
    if not items and not rep["errors"]:
        rep["errors"].append("No ad set found in the file.")
    if len(items) > MAX_ADSETS:
        rep["warnings"].append(f"Only the first {MAX_ADSETS} ad sets are used.")
        items = items[:MAX_ADSETS]
    out = []
    for i, raw in enumerate(items, 1):
        sub = {"filled": [], "converted": [], "kept_as_extra": [], "ignored": [], "warnings": [], "errors": []}
        kind = fmt or ("meta" if _looks_meta(raw) else "launcher")
        rep["format"] = rep["format"] or kind
        form = from_meta(raw, offset, sub) if kind == "meta" else from_launcher(raw, saved, sub)
        for k in ("filled", "converted", "kept_as_extra", "ignored", "warnings", "errors"):
            pre = f"Ad set {i}: " if len(items) > 1 and k in ("warnings", "errors") else ""
            rep[k] += [pre + x for x in sub[k]] if pre else sub[k]
        form["targeting_extra"], form["extra"], found = adset_findings(form["targeting_extra"], form["extra"], form.get("label") or f"Ad set {i}")
        rep["special"] += found
        # light sanity so the form never opens with nonsense
        cs = form["custom"]
        try:
            cs["age_min"], cs["age_max"] = int(cs["age_min"]), int(cs["age_max"])
        except (TypeError, ValueError):
            cs["age_min"], cs["age_max"] = 18, 45
            rep["warnings"].append(f"Ad set {i}: ages were not numbers; 18 to 45 was used.")
        if form["goal"] and form["goal"] not in GOALS:
            pass  # warned above
        for k, allowed in (("bid_strategy", BID_STRATEGIES), ("billing_event", BILLING_EVENTS)):
            if form[k] and form[k] not in allowed:
                rep["warnings"].append(f"Ad set {i}: {k.replace('_', ' ')} {form[k]} is not one I know ({', '.join(sorted(allowed))}).")
        if form["destination_type"] and form["destination_type"] not in DESTINATIONS:
            rep["warnings"].append(f"Ad set {i}: destination {form['destination_type']} is not one I know; Meta's check will say if it is valid.")
        out.append(form)
    rep["count"] = len(out)
    for k in ("filled", "converted", "kept_as_extra", "ignored"):
        rep[k] = list(dict.fromkeys(rep[k]))
    return {"adsets": out, "report": rep}


@router.post("/api/adsets/import")
async def import_json(req: Request):
    body = await req.json()
    text = body.get("text")
    if isinstance(text, str):
        if len(text.encode("utf-8")) > MAX_BYTES:
            raise HTTPException(413, "That file is too large (200 KB limit).")
        try:
            data = json.loads(text)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"This is not valid JSON: {e.msg} (line {e.lineno}, column {e.colno}).")
    else:
        data = body.get("json")
    return convert(data, int(account_cfg().get("currency_offset", 100)))


SAMPLES = {
    "launcher": {"format": "roopsee-adset", "version": 1, "name": "Women 18-35, India",
                 "result": "purchases", "audience": {"countries": ["IN"], "age": [18, 35], "gender": "women"},
                 "placements": "instagram", "budget": {"daily": 500}, "schedule": {"start": "2026-12-01"},
                 "bid": {"strategy": "LOWEST_COST_WITHOUT_CAP"}, "conversion": {"event": "PURCHASE"}},
    "meta": {"name": "Women 18-35, India", "optimization_goal": "OFFSITE_CONVERSIONS", "billing_event": "IMPRESSIONS", "bid_strategy": "LOWEST_COST_WITHOUT_CAP",
             "daily_budget": "50000", "destination_type": "WEBSITE", "start_time": "2026-12-01T00:00:00+0530",
             "promoted_object": {"pixel_id": "1721498525601686", "custom_event_type": "PURCHASE"},
             "targeting": {"geo_locations": {"countries": ["IN"]}, "age_min": 18, "age_max": 35, "genders": [2], "publisher_platforms": ["instagram"]}},
}


@router.get("/api/adsets/sample")
def sample(format: str = "launcher"):
    return SAMPLES.get(format, SAMPLES["launcher"])


# ---- copy an ad set that already exists on Meta ------------------------------------------------------------------------------
_LIST: dict = {}


@router.get("/api/adsets/from-meta")
def list_meta_adsets(refresh: bool = False):
    s = Settings()
    if s.missing():
        raise HTTPException(400, "Missing in .env: " + ", ".join(s.missing()))
    hit = _LIST.get((s.env, s.account))
    if hit and not refresh and time.time() - hit["t"] < 60:
        return hit["data"]
    try:
        m = Meta(s)
        camps = {c["id"]: c["name"] for c in m.pages(f"{s.account}/campaigns", fields="id,name", limit=100)}
        rows = m.pages(f"{s.account}/adsets", fields="id,name,campaign_id,effective_status,optimization_goal", limit=100)
    except MetaError as e:
        raise HTTPException(502, f"Meta said: {s.redact(e)[:300]}")
    data = {"adsets": [{"id": r["id"], "name": r["name"], "campaign": camps.get(r.get("campaign_id"), ""), "status": r.get("effective_status"), "goal": r.get("optimization_goal")} for r in rows],
            "account": s.account, "env": s.env}
    _LIST[(s.env, s.account)] = {"t": time.time(), "data": data}
    return data


@router.get("/api/adsets/from-meta/{adset_id}")
def copy_meta_adset(adset_id: str):
    if not adset_id.isdigit():
        raise HTTPException(400, "bad ad set id")
    s = Settings()
    fields = ("name,optimization_goal,billing_event,bid_strategy,bid_amount,daily_budget,lifetime_budget,start_time,end_time,targeting,promoted_object,destination_type,"
              "attribution_spec,pacing_type,adset_schedule,frequency_control_specs,bid_constraints,status")
    try:
        raw = Meta(s).get(adset_id, fields=fields)
    except MetaError as e:
        raise HTTPException(502, f"Meta said: {s.redact(e)[:300]}")
    out = convert(raw, int(account_cfg().get("currency_offset", 100)))
    out["report"]["format"] = "meta (copied from your ad account)"
    return out
