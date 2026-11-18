"""Copy or import at every level: a whole campaign (with its ad sets and ads), one campaign, one ad, plus a small library of saved templates.
Everything read from Meta or from a file is treated as data only: ids, status and tracking are dropped, anything ACTIVE becomes PAUSED."""
from __future__ import annotations

import json
import re
import time
import uuid
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from src.common import BID_STRATEGIES, FORBIDDEN_EXTRA, ROOT, Registry, Settings, account_cfg, batch_files, jload, jsave
from src.meta_api import Meta, MetaError
from src.spec_clean import clean_creative, describe
from src.special import creative_findings
from ui.importer import MAX_ADSETS, MAX_BYTES, convert
from ui.wizard import GOALS as WIZ_GOALS
from ui.formats import KINDS as FORMAT_KINDS

router = APIRouter()
MAX_ADS = 40
OBJ_GOAL = {g["objective"]: k for k, g in WIZ_GOALS.items()}
CAMP_FIELDS = "name,objective,status,effective_status,daily_budget,lifetime_budget,spend_cap,bid_strategy,special_ad_categories,special_ad_category_country,buying_type"
ADSET_FIELDS = ("name,campaign_id,optimization_goal,billing_event,bid_strategy,bid_amount,daily_budget,lifetime_budget,start_time,end_time,targeting,promoted_object,"
                "destination_type,attribution_spec,pacing_type,is_dynamic_creative,adset_schedule,frequency_control_specs,bid_constraints,status,effective_status")
CREATIVE_FIELDS = "id,object_story_spec,asset_feed_spec,object_story_id,effective_object_story_id,url_tags,degrees_of_freedom_spec,platform_customizations,product_set_id"
AD_FIELDS = f"name,adset_id,campaign_id,status,effective_status,creative{{{CREATIVE_FIELDS}}}"


def _uniq(items: list) -> list:
    seen, out = set(), []
    for x in items:
        k = (x["where"], x["what"], x["status"])
        if k not in seen:
            seen.add(k)
            out.append(x)
    return out


def _rep() -> dict:
    return {"format": None, "count": 0, "filled": [], "converted": [], "kept_as_extra": [], "ignored": [], "warnings": [], "errors": [], "special": []}


def _num(v):
    try:
        f = float(v)
        return int(f) if f == int(f) else f
    except (TypeError, ValueError):
        return None


def _used_keys() -> set:
    used = {p.stem for p in (ROOT / "creatives").rglob("*") if p.is_file()}
    for f in batch_files():
        used |= {a.get("ad_key") for a in (jload(f, {}) or {}).get("ads", [])}
    for env in ("sandbox", "production"):
        used |= set(Registry(Settings(env), "ad_registry.json").d)
    return used


def _next_keys(theme: str, used: set):
    tag = re.sub(r"[^A-Z0-9]", "", theme.upper()) or "COPY"
    nums = [int(k.rsplit("_", 1)[1]) for k in used if k and k.startswith(f"RS_{tag}_") and k.rsplit("_", 1)[1].isdigit()]
    n = max(nums, default=0)

    def nxt():
        nonlocal n
        n += 1
        k = f"RS_{tag}_{n:03d}"
        used.add(k)
        return k
    return nxt


# ---- one campaign ---------------------------------------------------------------------------------------------------------------
def campaign_form(raw: dict, offset: int, rep: dict) -> dict:
    """Meta campaign JSON (or the launcher's) -> the builder's campaign answers."""
    out: dict = {"campaign": {"spend_cap": "", "bid_strategy": "", "special_ad_categories": [], "extra": {}}}
    obj = raw.get("objective")
    goal = raw.get("goal") if raw.get("goal") in WIZ_GOALS else OBJ_GOAL.get(obj)
    if goal:
        out["goal"] = goal
        rep["filled"].append(f"goal ({WIZ_GOALS[goal]['short']})")
    elif obj:
        rep["warnings"].append(f"The objective {obj} is not one of the builder's goals yet, so pick the closest goal yourself and use the extra settings for the rest.")
    daily, life = raw.get("daily_budget"), raw.get("lifetime_budget")
    if _num(daily):
        out["budget_mode"], out["daily_budget"] = "campaign", round(_num(daily) / offset, 2)
        rep["converted"].append(f"campaign daily budget {daily} -> {out['daily_budget']} (rupees)")
    elif raw.get("budget_mode") in ("campaign", "adset"):
        out["budget_mode"] = raw["budget_mode"]
        if _num(raw.get("daily_budget")):
            out["daily_budget"] = _num(raw["daily_budget"])
    else:
        out["budget_mode"] = "adset"
        rep["filled"].append("budgets are on the ad sets")
    if _num(life):
        rep["warnings"].append("This campaign has a lifetime budget. The builder sets daily budgets, so give the ad sets or the campaign a daily budget.")
    if _num(raw.get("spend_cap")):
        out["campaign"]["spend_cap"] = round(_num(raw["spend_cap"]) / offset, 2)
        rep["converted"].append(f"spending limit {raw['spend_cap']} -> {out['campaign']['spend_cap']} (rupees)")
    bs = raw.get("bid_strategy")
    if bs and out["budget_mode"] == "campaign":
        out["campaign"]["bid_strategy"] = bs
        rep["filled"].append("bid strategy")
        if bs not in BID_STRATEGIES:
            rep["warnings"].append(f"Bid strategy {bs} is not one I know.")
    cats = [c for c in (raw.get("special_ad_categories") or []) if c and c != "NONE"]
    if cats:
        out["campaign"]["special_ad_categories"] = cats
        rep["filled"].append("special ad categories")
    for k in ("special_ad_category_country", "buying_type"):
        v = raw.get(k)
        if v and not (k == "buying_type" and v == "AUCTION"):
            out["campaign"]["extra"][k] = v
            rep["kept_as_extra"].append(k)
    if raw.get("name"):
        out["label"] = str(raw["name"])
        rep["filled"].append("name (kept as a label; the launcher makes its own names)")
    if str(raw.get("status", "PAUSED")).upper() == "ACTIVE":
        rep["warnings"].append("The campaign was ACTIVE. It will be created PAUSED; you turn it on yourself later.")
    for k, v in (raw.get("extra") or {}).items():
        if k not in FORBIDDEN_EXTRA:
            out["campaign"]["extra"][k] = v
    return out


def campaign_from_launcher(raw: dict, rep: dict) -> dict:
    """The launcher's own campaign JSON: amounts are already in rupees."""
    out: dict = {"campaign": {"spend_cap": "", "bid_strategy": "", "special_ad_categories": [], "extra": {}}}
    if raw.get("goal") in WIZ_GOALS:
        out["goal"] = raw["goal"]
        rep["filled"].append(f"goal ({WIZ_GOALS[raw['goal']]['short']})")
    elif raw.get("goal"):
        rep["warnings"].append(f"I do not know the goal '{raw['goal']}'. Known: {', '.join(WIZ_GOALS)}.")
    if raw.get("budget_mode") in ("campaign", "adset"):
        out["budget_mode"] = raw["budget_mode"]
        rep["filled"].append("budget mode")
    if _num(raw.get("daily_budget")):
        out["daily_budget"] = _num(raw["daily_budget"])
        rep["filled"].append("daily budget")
    for k in ("start_date", "end_date"):
        if raw.get(k):
            out[k] = str(raw[k])[:10]
            rep["filled"].append(k.replace("_", " "))
    if _num(raw.get("spend_cap")):
        out["campaign"]["spend_cap"] = _num(raw["spend_cap"])
        rep["filled"].append("spending limit")
    if raw.get("bid_strategy"):
        out["campaign"]["bid_strategy"] = str(raw["bid_strategy"]).upper()
        rep["filled"].append("bid strategy")
        if out["campaign"]["bid_strategy"] not in BID_STRATEGIES:
            rep["warnings"].append(f"Bid strategy {out['campaign']['bid_strategy']} is not one I know.")
    if raw.get("special_ad_categories"):
        out["campaign"]["special_ad_categories"] = [str(x).upper() for x in raw["special_ad_categories"]]
        rep["filled"].append("special ad categories")
    if isinstance(raw.get("extra"), dict):
        out["campaign"]["extra"] = {k: v for k, v in raw["extra"].items() if k not in FORBIDDEN_EXTRA}
        if out["campaign"]["extra"]:
            rep["kept_as_extra"].append("campaign extra settings")
    return out


SIMPLE_AD_KEYS = ("ad_key", "image_hash", "image", "primary_text", "headline", "description", "cta", "destination", "extra", "link_extra")


# ---- one ad ---------------------------------------------------------------------------------------------------------------------
def ad_form(raw: dict, s: Settings, rep: dict, key: str = "") -> dict | None:
    """An ad copied from Meta (has .creative), a bare creative, or the launcher's {creative_spec} -> an ad card."""
    if raw.get("kind") in FORMAT_KINDS:  # an ad built in the launcher (video, carousel, ...): keep it as the card it was
        out = {k: v for k, v in raw.items() if k not in ("sets", "format", "version")}
        out["ad_key"] = key or str(raw.get("ad_key") or "")
        out["sets"] = []
        rep["filled"].append(f"{raw['kind']} ad")
        return out
    if raw.get("format") == "roopsee-ad" or "creative_spec" in raw:
        spec_in = raw.get("creative_spec")
    elif isinstance(raw.get("creative"), dict):
        spec_in = raw["creative"]
    elif any(k in raw for k in ("object_story_spec", "asset_feed_spec", "object_story_id", "effective_object_story_id")):
        spec_in = raw
    else:
        rep["errors"].append("This does not look like an ad or a creative (no object_story_spec, asset_feed_spec or object_story_id).")
        return None
    if not isinstance(spec_in, dict):
        rep["errors"].append("creative_spec must be an object.")
        return None
    rep.setdefault("special", []).extend(creative_findings(spec_in, str(raw.get("name") or key or "Ad")))
    spec, notes = clean_creative(spec_in, s.page_id, s.instagram_id)
    if not (spec.get("object_story_spec") or spec.get("asset_feed_spec") or spec.get("object_story_id")):
        rep["errors"].append("The creative has nothing to build the ad from (no story, no asset feed, no existing post).")
        return None
    rep["filled"].append("creative")
    if (spec.get("object_story_spec") or {}).get("template_data") and not spec.get("product_set_id") and not (spec.get("asset_feed_spec") or {}).get("product_set_id"):
        rep["warnings"].append("This is a catalog (product) ad but the file does not say which product set it shows. Copy it from your Meta account (that includes it) or add product_set_id to the creative.")
    rep["converted"] += [n for n in notes if n.startswith("this ad uses")]
    rep["ignored"] += [n for n in notes if not n.startswith("this ad uses")]
    if str(raw.get("status", "PAUSED")).upper() == "ACTIVE":
        rep["warnings"].append("The ad was ACTIVE. It will be created PAUSED.")
    if (spec.get("object_story_spec") or {}).get("page_id") and s.page_id:
        rep["converted"].append(f"the Page and Instagram account were set to this environment's ({s.env})")
    return {"ad_key": key, "creative_spec": spec, "label": str(raw.get("name") or ""), "summary": describe(spec), "sets": []}


def _json_in(body: dict):
    text = body.get("text")
    if isinstance(text, str):
        if len(text.encode("utf-8")) > MAX_BYTES:
            raise HTTPException(413, "That file is too large (200 KB limit).")
        try:
            return json.loads(text)
        except json.JSONDecodeError as e:
            raise HTTPException(400, f"This is not valid JSON: {e.msg} (line {e.lineno}, column {e.colno}).")
    return body.get("json")


def _meta() -> tuple[Settings, Meta]:
    s = Settings()
    if s.missing():
        raise HTTPException(400, "Missing in .env: " + ", ".join(s.missing()))
    return s, Meta(s)


def _meta_err(s, e):
    if "code 17" in str(e) or "too many calls" in str(e).lower():
        return HTTPException(429, "Meta is limiting how often this ad account can be asked. Wait a few minutes and try again.")
    return HTTPException(502, f"Meta said: {s.redact(e)[:300]}")


# ---- bundles: a campaign with its ad sets and ads --------------------------------------------------------------------------------
def bundle_from_meta(camp: dict, adsets: list, ads: list, s: Settings, offset: int) -> dict:
    rep = _rep()
    rep["format"] = "meta (copied from your ad account)"
    answers = campaign_form(camp, offset, rep)
    live = [a for a in adsets if a.get("effective_status") not in ("DELETED", "ARCHIVED")]
    if len(live) > MAX_ADSETS:
        rep["warnings"].append(f"The campaign has {len(live)} ad sets; only the first {MAX_ADSETS} were copied.")
        live = live[:MAX_ADSETS]
    conv = convert({"data": live}, offset)
    for k in ("filled", "converted", "kept_as_extra", "ignored", "warnings", "errors", "special"):
        rep[k] += conv["report"][k]
    forms = conv["adsets"]
    for f, raw in zip(forms, live):
        f["source_id"] = raw.get("id", "")
    idx = {raw["id"]: i for i, raw in enumerate(live) if raw.get("id")}
    if forms and any(f["daily_budget"] for f in forms) and answers.get("budget_mode") != "campaign":
        answers["budget_mode"] = "adset"
    # ads: the same creative used in several ad sets becomes one ad shown in all of them
    used = _used_keys()
    nxt = _next_keys("COPY", used)
    by_sig: dict = {}
    skipped = 0
    for raw in ads:
        if raw.get("effective_status") in ("DELETED", "ARCHIVED") or raw.get("adset_id") not in idx:
            continue
        sub = _rep()
        f = ad_form(raw, s, sub)
        if not f:
            skipped += 1
            continue
        sig = json.dumps(f["creative_spec"], sort_keys=True)
        if sig not in by_sig:
            if len(by_sig) >= MAX_ADS:
                skipped += 1
                continue
            f["ad_key"] = nxt()
            f["set_idx"] = []
            by_sig[sig] = f
        if idx[raw["adset_id"]] not in by_sig[sig]["set_idx"]:
            by_sig[sig]["set_idx"].append(idx[raw["adset_id"]])
        rep["ignored"] += sub["ignored"]
        rep["special"] += sub["special"]
    if skipped:
        rep["warnings"].append(f"{skipped} ad(s) could not be copied (over the {MAX_ADS}-ad limit or unreadable).")
    rep["converted"] = list(dict.fromkeys(rep["converted"]))
    rep["ignored"] = list(dict.fromkeys(rep["ignored"]))
    rep["special"] = _uniq(rep["special"])
    rep["count"] = len(forms)
    answers["adsets"], answers["ads"] = forms, list(by_sig.values())
    rep["warnings"].append("Ad IDs (RS_COPY_001 ...) were given to the copied ads. Rename them if you like; the launcher never reuses an ID.")
    return {"answers": answers, "report": rep}


@router.get("/api/campaigns/from-meta")
def list_campaigns(refresh: bool = False):
    s, m = _meta()
    try:
        rows = m.pages(f"{s.account}/campaigns", fields="id,name,objective,effective_status,daily_budget", limit=100)
    except MetaError as e:
        raise _meta_err(s, e)
    rows = [r for r in rows if r.get("effective_status") not in ("DELETED", "ARCHIVED")]
    return {"campaigns": [{"id": r["id"], "name": r["name"], "objective": r.get("objective"), "status": r.get("effective_status"), "budget": r.get("daily_budget")} for r in rows],
            "account": s.account, "env": s.env}


@router.get("/api/campaigns/from-meta/{cid}")
def copy_campaign(cid: str):
    if not cid.isdigit():
        raise HTTPException(400, "bad campaign id")
    s, m = _meta()
    try:
        camp = m.get(cid, fields=CAMP_FIELDS)
        adsets = m.pages(f"{cid}/adsets", fields=ADSET_FIELDS, limit=50)
        ads = m.pages(f"{cid}/ads", fields=AD_FIELDS, limit=50)
    except MetaError as e:
        raise _meta_err(s, e)
    return bundle_from_meta(camp, adsets, ads, s, int(account_cfg().get("currency_offset", 100)))


@router.post("/api/campaigns/import")
async def import_campaign(req: Request):
    """A campaign JSON: Meta's campaign object, the launcher's {format: roopsee-campaign, campaign, adsets, ads}, or a Meta campaign with adsets/ads lists."""
    data = _json_in(await req.json())
    s, offset = Settings(), int(account_cfg().get("currency_offset", 100))
    rep = _rep()
    if not isinstance(data, dict):
        rep["errors"].append("The file must hold one campaign (an object).")
        return {"answers": {}, "report": rep}
    launcher = data.get("format") == "roopsee-campaign"
    camp = data.get("campaign") if isinstance(data.get("campaign"), dict) else data
    rep["format"] = "launcher" if launcher else "meta"
    answers = campaign_from_launcher(camp, rep) if launcher else campaign_form(camp, offset, rep)
    raw_sets = data.get("adsets") or (data.get("ad_sets") or [])
    if isinstance(raw_sets, dict) and isinstance(raw_sets.get("data"), list):
        raw_sets = raw_sets["data"]
    if raw_sets:
        conv = convert(raw_sets if isinstance(raw_sets, list) else [raw_sets], offset)
        for k in ("filled", "converted", "kept_as_extra", "ignored", "warnings", "errors", "special"):
            rep[k] += conv["report"][k]
        answers["adsets"] = conv["adsets"]
        rep["count"] = len(conv["adsets"])
        if any(f["daily_budget"] for f in conv["adsets"]) and not answers.get("daily_budget"):
            answers["budget_mode"] = "adset"
    set_pos = {x.get("id"): i for i, x in enumerate(raw_sets[:MAX_ADSETS] if isinstance(raw_sets, list) else []) if isinstance(x, dict) and x.get("id")}
    raw_ads = data.get("ads") or []
    if isinstance(raw_ads, dict) and isinstance(raw_ads.get("data"), list):
        raw_ads = raw_ads["data"]
    nxt = _next_keys("COPY", _used_keys())
    out_ads = []
    for raw in raw_ads[:MAX_ADS] if isinstance(raw_ads, list) else []:
        if not isinstance(raw, dict):
            continue
        if launcher and "creative_spec" not in raw and (raw.get("kind") in FORMAT_KINDS or raw.get("image_hash") or raw.get("image")):  # an image ad or a built format: keep as written
            simple = {k: v for k, v in raw.items() if k not in ("sets", "format", "version")} if raw.get("kind") in FORMAT_KINDS else {k: raw[k] for k in SIMPLE_AD_KEYS if k in raw}
            sets_ref = raw.get("sets") if isinstance(raw.get("sets"), list) else []
            simple["set_idx"] = [i for i in sets_ref if isinstance(i, int)] or list(range(len(answers.get("adsets", []))))
            out_ads.append(simple)
            continue
        sub = _rep()
        f = ad_form(raw, s, sub, key=(raw.get("ad_key") or "").strip() or nxt())
        if not f:
            rep["warnings"] += sub["errors"]
            continue
        sets_ref = raw.get("sets") if isinstance(raw.get("sets"), list) else raw.get("set_idx")
        mine = [i for i in (sets_ref or []) if isinstance(i, int)]
        if not mine and raw.get("adset_id") in set_pos:  # a Meta ad says which ad set it belongs to
            mine = [set_pos[raw["adset_id"]]]
        f["set_idx"] = mine or list(range(len(answers.get("adsets", []))))
        out_ads.append(f)
        rep["ignored"] += sub["ignored"]
        rep["special"] += sub["special"]
    if out_ads:
        answers["ads"] = out_ads
    rep["ignored"] = list(dict.fromkeys(rep["ignored"]))
    rep["special"] = _uniq(rep["special"])
    return {"answers": answers, "report": rep}


@router.post("/api/ads/import")
async def import_ad(req: Request):
    data = _json_in(await req.json())
    s = Settings()
    rep = _rep()
    items = data["data"] if isinstance(data, dict) and isinstance(data.get("data"), list) else data["ads"] if isinstance(data, dict) and isinstance(data.get("ads"), list) else data if isinstance(data, list) else [data]
    rep["format"] = "launcher" if isinstance(data, dict) and (data.get("format") == "roopsee-ad" or "creative_spec" in data) else "meta"
    nxt = _next_keys("COPY", _used_keys())
    ads = []
    for raw in items[:MAX_ADS]:
        if not isinstance(raw, dict):
            continue
        f = ad_form(raw, s, rep, key=(raw.get("ad_key") or "").strip() or nxt())
        if f:
            ads.append(f)
    rep["count"] = len(ads)
    for k in ("filled", "converted", "ignored"):
        rep[k] = list(dict.fromkeys(rep[k]))
    rep["special"] = _uniq(rep["special"])
    return {"ads": ads, "report": rep}


@router.get("/api/ads/from-meta")
def list_ads(refresh: bool = False):
    s, m = _meta()
    try:
        camps = {c["id"]: c["name"] for c in m.pages(f"{s.account}/campaigns", fields="id,name", limit=100)}
        rows = m.pages(f"{s.account}/ads", fields="id,name,campaign_id,effective_status", limit=100)
    except MetaError as e:
        raise _meta_err(s, e)
    rows = [r for r in rows if r.get("effective_status") not in ("DELETED", "ARCHIVED")]
    return {"ads": [{"id": r["id"], "name": r["name"], "campaign": camps.get(r.get("campaign_id"), ""), "status": r.get("effective_status")} for r in rows], "account": s.account, "env": s.env}


@router.get("/api/ads/from-meta/{aid}")
def copy_ad(aid: str):
    if not aid.isdigit():
        raise HTTPException(400, "bad ad id")
    s, m = _meta()
    try:
        raw = m.get(aid, fields=AD_FIELDS)
    except MetaError as e:
        raise _meta_err(s, e)
    rep = _rep()
    rep["format"] = "meta (copied from your ad account)"
    f = ad_form(raw, s, rep, key=_next_keys("COPY", _used_keys())())
    rep["count"] = 1 if f else 0
    return {"ads": [f] if f else [], "report": rep}


@router.post("/api/ads/describe")
async def describe_spec(req: Request):
    """Re-summarise an edited creative (used by the expert JSON box on an imported ad)."""
    body = await req.json()
    spec = body.get("creative_spec")
    if not isinstance(spec, dict):
        raise HTTPException(400, "creative_spec must be an object")
    s = Settings()
    cleaned, notes = clean_creative(spec, s.page_id, s.instagram_id)
    return {"creative_spec": cleaned, "summary": describe(cleaned), "notes": notes}


# ---- templates: saved pieces you reuse (an ad set, a campaign setup, an ad) -------------------------------------------------------
TPL = ROOT / "templates"
TPL_ID = re.compile(r"^[a-z0-9]{6,12}$")
KINDS = {"adset", "campaign", "ad"}


@router.get("/api/templates")
def templates(kind: str = ""):
    TPL.mkdir(exist_ok=True)
    out = []
    for p in sorted(TPL.glob("*.json"), key=lambda p: p.stat().st_mtime, reverse=True):
        try:
            d = json.loads(p.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if kind and d.get("kind") != kind:
            continue
        out.append({"id": p.stem, "kind": d.get("kind"), "title": d.get("title"), "saved": d.get("saved"), "note": d.get("note", "")})
    return {"templates": out}


@router.get("/api/templates/{tid}")
def get_template(tid: str):
    p = TPL / f"{tid}.json"
    if not TPL_ID.match(tid) or not p.is_file():
        raise HTTPException(404, "template not found")
    return json.loads(p.read_text(encoding="utf-8"))


@router.put("/api/templates/{tid}")
async def put_template(tid: str, req: Request):
    b = await req.json()
    kind, payload = b.get("kind"), b.get("payload")
    if kind not in KINDS or payload is None:
        raise HTTPException(400, "kind must be adset, campaign or ad, and a payload is needed")
    if len(json.dumps(payload).encode()) > MAX_BYTES * 2:
        raise HTTPException(413, "That template is too large.")
    if tid == "new" or not TPL_ID.match(tid):
        tid = uuid.uuid4().hex[:8]
    TPL.mkdir(exist_ok=True)
    jsave(TPL / f"{tid}.json", {"kind": kind, "title": str(b.get("title") or "Untitled")[:80], "note": str(b.get("note") or "")[:300], "payload": payload,
                                "saved": datetime.now(timezone.utc).isoformat(timespec="seconds")})
    return {"id": tid}


@router.delete("/api/templates/{tid}")
def del_template(tid: str):
    p = TPL / f"{tid}.json"
    if TPL_ID.match(tid) and p.is_file():
        p.unlink()
    return {"ok": True}
