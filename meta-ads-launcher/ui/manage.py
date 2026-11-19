"""Manage campaigns that already exist: edit an ad set, add new creatives to ad sets, change the creative of an ad, pause or turn on.

Rules this module keeps:
 - every change starts from a FRESH read of the object, and is refused if it changed on Meta since you opened it (nobody's edit is overwritten)
 - you see each change as before and after, in plain words, and can have Meta test it first
 - on production a change needs the tick box; anything that can spend money (turning on, raising a budget) also needs the typed word
 - every change is written to a log with the values it replaced, so the last change can be undone
 - new ads are created PAUSED unless you turn them on"""
from __future__ import annotations

import json
import re
import time
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException, Request

from src import create_adsets, create_creatives, library_store as store, media
from src.common import ROOT, Registry, Settings, account_cfg, audiences_cfg, clean_extra, image_path, minor, sha256
from src.ensure import ensure
from src.meta_api import Meta, MetaError, usage_snapshot
from src.special import scrub_targeting
from src.spec_clean import describe
from ui.importer import convert
from ui.jobs import start_job
from ui.library import ADSET_FIELDS
from ui.libsync import _fetch_campaign
from ui.wizard import GENDERS, PLACEMENTS, _audience, _build_ads, guardrail_check, pair_warnings, post_link_state

router = APIRouter()
TYPED = "TURN ON"
FORM_KEYS = ("audience", "custom", "placements", "daily_budget", "lifetime_budget", "goal", "event", "bid_strategy", "bid_amount", "billing_event", "destination_type", "start_date", "end_date", "targeting_extra", "extra")
LEARNING_KEYS = {"bid_constraints", "adset_schedule", "pacing_type", "attribution_spec", "promoted_object", "frequency_control_specs"}
ADSET_READ = f"id,{ADSET_FIELDS},campaign{{id,name,objective,bid_strategy,daily_budget,lifetime_budget,effective_status}}"
AD_READ = "id,name,adset_id,campaign_id,status,effective_status,creative{id,name,object_story_spec,asset_feed_spec,object_story_id,effective_object_story_id,url_tags,degrees_of_freedom_spec,product_set_id}"


# ---- small helpers --------------------------------------------------------------------------------------------------------------
def _settings() -> Settings:
    s = Settings()
    if s.missing():
        raise HTTPException(400, "Missing in .env: " + ", ".join(s.missing()))
    return s


def _fail(s: Settings, e: Exception) -> HTTPException:
    text = s.redact(e)
    if "limiting calls" in text or "code 17" in text or "too many calls" in text.lower():
        return HTTPException(429, "Meta is limiting calls for this ad account. Wait a few minutes and try again.")
    return HTTPException(502, f"Meta said: {text[:400]}")


def _n(v):
    """A number from a form value (or None for empty)."""
    try:
        return None if v in (None, "") else float(v)
    except (TypeError, ValueError):
        return None


def norm(form: dict) -> dict:
    """The parts of an ad set form that Meta knows about (the rest is only how the page shows it), in a form that compares equal when nothing changed."""
    f = {k: form.get(k) for k in FORM_KEYS}
    for k in ("daily_budget", "lifetime_budget", "bid_amount"):
        f[k] = _n(f[k])
    c = dict(f.get("custom") or {})
    for k in ("age_min", "age_max"):
        c[k] = _n(c.get(k))
    c["countries"] = ",".join(sorted(x.strip().upper() for x in str(c.get("countries") or "").split(",") if x.strip()))
    f["custom"] = c
    return json.loads(json.dumps(f, sort_keys=True, default=str))


def _rupees(minor_value, offset: int):
    n = _n(minor_value)
    return None if n is None else n / offset


def _money(v) -> str:
    return f"₹{float(v):,.0f}"


def _same(a, b) -> bool:
    return json.dumps(a, sort_keys=True, default=str) == json.dumps(b, sort_keys=True, default=str)


def _names(group: list | None) -> set:
    return {str(x.get("name") or x.get("id")) for x in (group or []) if isinstance(x, dict)}


def _describe_targeting(base: dict, new: dict) -> list:
    out = []
    bc, nc = base.get("custom") or {}, new.get("custom") or {}
    if _n(bc.get("age_min")) != _n(nc.get("age_min")) or _n(bc.get("age_max")) != _n(nc.get("age_max")):
        i = lambda v: int(v) if _n(v) is not None and float(v) == int(float(v)) else v
        out.append(f"Age: {i(bc.get('age_min'))}–{i(bc.get('age_max'))} → {i(nc.get('age_min'))}–{i(nc.get('age_max'))}")
    if (bc.get("gender") or "all") != (nc.get("gender") or "all"):
        out.append(f"Gender: {bc.get('gender') or 'all'} → {nc.get('gender') or 'all'}")
    if str(bc.get("countries") or "").upper().replace(" ", "") != str(nc.get("countries") or "").upper().replace(" ", ""):
        out.append(f"Countries: {bc.get('countries') or 'none'} → {nc.get('countries') or 'none'}")
    if (base.get("placements") or "") != (new.get("placements") or ""):
        out.append(f"Where the ads appear: {base.get('placements')} → {new.get('placements')}")
    bt, nt = base.get("targeting_extra") or {}, new.get("targeting_extra") or {}
    for k in sorted(set(bt) | set(nt)):
        if _same(bt.get(k), nt.get(k)):
            continue
        if k == "flexible_spec":
            for cls in sorted({c for g in (bt.get(k) or []) + (nt.get(k) or []) for c in g}):
                old = _names([i for g in (bt.get(k) or []) for i in g.get(cls, [])])
                cur = _names([i for g in (nt.get(k) or []) for i in g.get(cls, [])])
                if cur - old:
                    out.append(f"Added to {cls.replace('_', ' ')}: " + ", ".join(sorted(cur - old)))
                if old - cur:
                    out.append(f"Removed from {cls.replace('_', ' ')}: " + ", ".join(sorted(old - cur)))
        elif k not in bt:
            out.append(f"Added targeting: {k.replace('_', ' ')}")
        elif k not in nt:
            out.append(f"Removed targeting: {k.replace('_', ' ')}")
        else:
            out.append(f"Changed targeting: {k.replace('_', ' ')}")
    return out or ["Targeting changed"]


def diff_adset(base: dict, new: dict, raw: dict, acc: dict) -> dict:
    """What an edited ad set form changes compared with how it was opened. Returns the update to send to Meta and a plain list of what it does."""
    errs, warns, risks, changes, payload = [], [], [], [], {}
    off = int(acc.get("currency_offset", 100))
    spend_up = False
    for k, label in (("goal", "the result Meta aims for"), ("billing_event", "what you pay for"), ("destination_type", "where people go")):
        if (new.get(k) or "") != (base.get(k) or ""):
            errs.append(f"You can't change {label} on an ad set that already exists. Duplicate the ad set with the new setting instead.")
    nm = (new.get("name") or "").strip()
    if nm and nm != raw.get("name"):
        payload["name"] = nm
        changes.append({"what": "Name", "before": raw.get("name"), "after": nm})
    for key, label in (("daily_budget", "Daily budget"), ("lifetime_budget", "Lifetime budget")):
        b0, b1 = _n(base.get(key)), _n(new.get(key))
        if b0 == b1:
            continue
        if b0 is None:
            errs.append("The budget type (daily or lifetime) can't be switched on an existing ad set.")
        elif b1 is None or b1 <= 0:
            errs.append(f"{label} can't be cleared. Pause the ad set instead if you want it to stop.")
        else:
            payload[key] = minor(b1, {"currency_offset": off})
            changes.append({"what": label, "before": _money(b0), "after": _money(b1)})
            spend_up = spend_up or b1 > b0
            if b0 and abs(b1 - b0) / b0 > 0.2:
                risks.append(f"The {label.lower()} changes by more than 20%, which can restart Meta's learning phase.")
    a0, a1 = _n(base.get("bid_amount")), _n(new.get("bid_amount"))
    if a0 != a1 and a1:
        payload["bid_amount"] = minor(a1, {"currency_offset": off})
        changes.append({"what": "Bid amount", "before": _money(a0) if a0 else "none", "after": _money(a1)})
        risks.append("A new bid can restart Meta's learning phase.")
    if (base.get("bid_strategy") or "") != (new.get("bid_strategy") or "") and new.get("bid_strategy"):
        payload["bid_strategy"] = new["bid_strategy"]
        changes.append({"what": "Bid strategy", "before": base.get("bid_strategy") or "default", "after": new["bid_strategy"]})
        risks.append("A new bid strategy can restart Meta's learning phase.")
    for key, meta_key, label in (("start_date", "start_time", "Starts"), ("end_date", "end_time", "Ends")):
        if (base.get(key) or "") != (new.get(key) or "") and (new.get(key) or ""):
            payload[meta_key] = f"{new[key]}T{'00:00:00' if key == 'start_date' else '23:59:00'}+0530"
            changes.append({"what": label, "before": base.get(key) or "not set", "after": new[key]})
    # targeting: rebuilt from the form the same way a new ad set is built, keeping anything Meta reported that the editor does not know about
    if any(not _same(base.get(k), new.get(k)) for k in ("audience", "custom", "placements", "targeting_extra")):
        saved = audiences_cfg()

        def build(f):
            aud, e2 = _audience({"audience": f.get("audience") or "custom", "custom": f.get("custom"), "targeting_extra": f.get("targeting_extra")}, saved)
            plc = PLACEMENTS.get(f.get("placements") or "automatic") or PLACEMENTS["automatic"]
            t = create_adsets.targeting({"placements": plc["list"], "targeting_extra": f.get("targeting_extra") or {}},
                                        {"countries": aud["countries"], "age_min": aud["age_min"], "age_max": aud["age_max"], "genders": GENDERS.get(aud["gender"], [])})
            return scrub_targeting(t)[0], e2
        built, e2 = build(new)
        errs += e2
        base_built, _ = build(base)
        live_t = scrub_targeting(raw.get("targeting") or {})[0]  # (settings Meta has removed are never sent back)
        kept = {k: v for k, v in live_t.items() if k not in base_built and k not in built}
        if kept:
            warns.append("Targeting details the editor can't show (" + ", ".join(sorted(kept)) + ") were kept as they are.")
        payload["targeting"] = {**built, **kept}
        for line in _describe_targeting(base, new):
            changes.append({"what": "Audience", "before": "", "after": line})
        risks.append("Changing the audience can restart Meta's learning phase.")
    be, ne = base.get("extra") or {}, new.get("extra") or {}
    clean, dropped = clean_extra(ne)
    for k, v in clean.items():
        if not _same(be.get(k), v):
            payload[k] = v
            changes.append({"what": k.replace("_", " ").capitalize(), "before": "", "after": "changed"})
            if k in LEARNING_KEYS:
                risks.append(f"Changing '{k}' can restart Meta's learning phase.")
    for k in be:
        if k not in ne and k in clean_extra(be)[0]:
            warns.append(f"Removing '{k}' can't be done here, so it was kept as it is. Change it in Ads Manager.")
    if payload.get("daily_budget"):
        guardrail_check(acc, payload["daily_budget"] / off, errs, warns)
    return {"payload": payload, "changes": changes, "errors": errs, "warnings": warns, "risks": sorted(set(risks)), "spend_up": spend_up}


# ---- the change log ------------------------------------------------------------------------------------------------------------
def _log(s: Settings, kind: str, object_id: str, name: str, before: dict, after: dict, note: str = "", extra: dict | None = None) -> str:
    reg = Registry(s, "change_log.json")
    lid = f"c{int(time.time() * 1000)}"
    reg.update(lid, id=lid, ts=datetime.now(timezone.utc).isoformat(timespec="seconds"), kind=kind, object_id=str(object_id), name=name, before=before, after=after, note=note, undone=False, **(extra or {}))
    return lid


@router.get("/api/manage/log")
def change_log():
    s = Settings()
    rows = sorted(Registry(s, "change_log.json").d.values(), key=lambda r: r.get("ts") or "", reverse=True)
    return {"changes": rows[:60], "env": s.env}


def _need_confirm(s: Settings, body: dict, spends: bool) -> None:
    if s.env == "production":
        if not body.get("confirm_production"):
            raise HTTPException(400, {"errors": ["You are on production. Tick the confirmation box to change the real ad account."]})
        if spends and (body.get("typed") or "").strip().upper() != TYPED:
            raise HTTPException(400, {"errors": [f"This can spend money. Type {TYPED} to confirm."]})


# ---- reading --------------------------------------------------------------------------------------------------------------------
@router.get("/api/manage/campaign/{cid}")
def read_campaign(cid: str):
    """A campaign, its ad sets and its ads, read live from Meta (3 calls). The local library copy is refreshed with it."""
    if not store.DIGITS.match(cid):
        raise HTTPException(400, "bad campaign id")
    s = _settings()
    off = int(account_cfg().get("currency_offset", 100))
    try:
        camp, adsets, ads = _fetch_campaign(Meta(s), cid)
    except MetaError as e:
        raise _fail(s, e)
    store.save_campaign(s, camp, adsets, ads)
    by_set: dict = {}
    for ad in ads:
        d = describe(ad.get("creative") or {})
        hashes = d["image_hashes"] or sorted(store.collect_hashes(ad.get("creative") or {}))
        by_set.setdefault(str(ad.get("adset_id")), []).append({
            "id": str(ad["id"]), "name": ad.get("name"), "status": ad.get("effective_status") or ad.get("status"), "type": d["kind"], "creative_id": (ad.get("creative") or {}).get("id"),
            "thumb": next((f"/lib-media/thumb/{h}" for h in hashes if store.image_file(s, h, thumb=True)), None), "text": (d["texts"] or [""])[0][:100]})
    return {"env": s.env, "campaign": {"id": str(camp["id"]), "name": camp.get("name"), "objective": camp.get("objective"), "status": camp.get("effective_status") or camp.get("status"),
                                       "daily_budget": _rupees(camp.get("daily_budget"), off), "lifetime_budget": _rupees(camp.get("lifetime_budget"), off), "bid_strategy": camp.get("bid_strategy")},
            "adsets": [{"id": str(a["id"]), "name": a.get("name"), "status": a.get("effective_status") or a.get("status"), "goal": a.get("optimization_goal"),
                        "daily_budget": _rupees(a.get("daily_budget"), off), "lifetime_budget": _rupees(a.get("lifetime_budget"), off), "destination_type": a.get("destination_type"),
                        "ads": by_set.get(str(a["id"]), [])} for a in adsets]}


def _read_adset(s: Settings, m: Meta, adset_id: str) -> dict:
    try:
        return m.get(adset_id, fields=ADSET_READ)
    except MetaError as e:
        raise _fail(s, e)


@router.get("/api/manage/adset/{adset_id}")
def read_adset(adset_id: str):
    """One ad set, read live, as the same form the builder uses. The page keeps the form it was opened with, to detect a change made meanwhile."""
    if not store.DIGITS.match(adset_id):
        raise HTTPException(400, "bad ad set id")
    s = _settings()
    acc = account_cfg()
    raw = _read_adset(s, Meta(s), adset_id)
    conv = convert(raw, int(acc.get("currency_offset", 100)))
    form = conv["adsets"][0]
    form["name"] = raw.get("name")
    camp = raw.get("campaign") or {}
    shared = bool(camp.get("daily_budget") or camp.get("lifetime_budget"))
    return {"form": form, "report": conv["report"], "status": raw.get("effective_status") or raw.get("status"), "env": s.env,
            "campaign": {"id": camp.get("id"), "name": camp.get("name"), "objective": camp.get("objective"), "shared_budget": shared, "bid_strategy": camp.get("bid_strategy")},
            "locked": ["goal", "billing_event", "destination_type"]}


# ---- editing an ad set ----------------------------------------------------------------------------------------------------------
def _prepare_edit(s: Settings, adset_id: str, body: dict) -> dict:
    m = Meta(s)
    acc = account_cfg()
    raw = _read_adset(s, m, adset_id)
    fresh = convert(raw, int(acc.get("currency_offset", 100)))["adsets"][0]
    base, new = body.get("base") or {}, body.get("form") or {}
    base = {**base, "name": base.get("name") or raw.get("name")}
    if not _same(norm(base), norm(fresh)):
        raise HTTPException(409, {"errors": ["This ad set changed on Meta after you opened it (someone edited it, or it was edited in Ads Manager). Reload it so your change does not overwrite theirs."]})
    d = diff_adset(norm(base) | {"name": raw.get("name")}, norm(new) | {"name": (new.get("name") or "").strip()}, raw, acc)
    d["raw"], d["m"] = raw, m
    return d


@router.post("/api/manage/adset/{adset_id}/preview")
async def preview_adset(adset_id: str, req: Request):
    s = _settings()
    d = _prepare_edit(s, adset_id, await req.json())
    return {"changes": d["changes"], "errors": d["errors"], "warnings": d["warnings"], "risks": d["risks"], "spend_up": d["spend_up"], "nothing": not d["payload"], "env": s.env}


@router.post("/api/manage/adset/{adset_id}/apply")
async def apply_adset(adset_id: str, req: Request):
    body = await req.json()
    s = _settings()
    d = _prepare_edit(s, adset_id, body)
    if d["errors"]:
        raise HTTPException(400, {"errors": d["errors"]})
    if not d["payload"]:
        return {"applied": False, "message": "Nothing changed."}
    _need_confirm(s, body, d["spend_up"])
    m, raw = d["m"], d["raw"]
    try:
        if body.get("check_only"):
            m.post(adset_id, d["payload"], validate_only=True)
            return {"checked": True, "message": "Meta accepts this change. Nothing was applied."}
        m.post(adset_id, d["payload"])
        after = m.get(adset_id, fields=ADSET_READ)
    except MetaError as e:
        raise _fail(s, e)
    before = {k: raw.get(k) for k in d["payload"]}
    lid = _log(s, "adset_update", adset_id, raw.get("name"), before, d["payload"], note="; ".join(f"{c['what']}: {c['before']} → {c['after']}".replace(": →", ":") for c in d["changes"])[:300])
    bad = [k for k, v in d["payload"].items() if k not in ("targeting",) and k in after and not _loose_equal(v, after.get(k))]
    return {"applied": True, "log_id": lid, "verified": not bad, "not_confirmed": bad, "changes": d["changes"]}


def _loose_equal(sent, got) -> bool:
    if isinstance(sent, (int, float)) or (isinstance(sent, str) and sent.isdigit()):
        return str(sent) == str(got)
    if isinstance(sent, str) and re.match(r"\d{4}-\d{2}-\d{2}T", sent):
        return str(got)[:10] == sent[:10]
    return _same(sent, got) or sent == got


# ---- pause / turn on ------------------------------------------------------------------------------------------------------------
@router.post("/api/manage/status")
async def set_status(req: Request):
    body = await req.json()
    kind, oid, want = body.get("kind"), str(body.get("id") or ""), body.get("status")
    if kind not in ("adset", "ad") or not store.DIGITS.match(oid) or want not in ("ACTIVE", "PAUSED"):
        raise HTTPException(400, "kind must be adset or ad, id a number, status ACTIVE or PAUSED")
    s = _settings()
    _need_confirm(s, body, want == "ACTIVE")
    m = Meta(s)
    try:
        cur = m.get(oid, fields="id,name,status,effective_status")
        if (cur.get("status") or "") == want:
            return {"changed": False, "message": f"It is already {want.lower()}."}
        m.post(oid, {"status": want})
    except MetaError as e:
        raise _fail(s, e)
    lid = _log(s, "status", oid, cur.get("name"), {"status": cur.get("status")}, {"status": want}, note=f"{kind}: {cur.get('status')} → {want}", extra={"what": kind})
    return {"changed": True, "log_id": lid, "status": want}


# ---- adding creatives to ad sets that exist -------------------------------------------------------------------------------------
def _stubs(s: Settings, m: Meta, adset_ids: list) -> tuple[list, dict, dict]:
    """Ad sets as the ad builder sees them: (sets, uid -> position, id -> live data). Reads each one (1 call each)."""
    sets, idx, live = [], {}, {}
    for i, aid in enumerate(adset_ids):
        raw = _read_adset(s, m, str(aid))
        live[str(aid)] = raw
        idx[str(aid)] = i
        dest = raw.get("destination_type")
        sets.append({"key": str(aid), "destination_type": "WEBSITE" if dest in (None, "", "UNDEFINED") else dest, "optimization_goal": raw.get("optimization_goal"),
                     "extra": {"is_dynamic_creative": True} if raw.get("is_dynamic_creative") else {}})
    return sets, idx, live


def _prepare_ads(s: Settings, body: dict) -> dict:
    ids = [str(x) for x in (body.get("adset_ids") or []) if store.DIGITS.match(str(x))]
    if not ids:
        raise HTTPException(400, {"errors": ["Choose at least one ad set to add the ads to."]})
    m = Meta(s)
    sets, idx, live = _stubs(s, m, ids)
    errs, warns, fixes = [], [], []
    ads_in = [{**ad, "sets": ad.get("sets") or None} for ad in (body.get("ads") or [])]
    if not ads_in:
        errs.append("Add at least one ad.")
    ads, _count = _build_ads(ads_in, s, sets, idx, errs, warns, fixes)
    pair = pair_warnings(ads, sets)
    keep = []
    for w in pair:  # look at the post itself: one without a website link is refused in a website ad set, one with a link is fine
        link = post_link_state(s, m, w["post"])
        if link is False:
            errs.append(f"The post {w['post']} has no website link or button, so Meta will refuse it in the website ad set '{w['adset']}'. Choose a post that carries your link, or use an image, video or carousel ad.")
        elif link is None:
            keep.append(w)
    pair = keep
    warns += [w["message"] for w in pair]
    for aid, raw in live.items():
        n_new = sum(1 for a in ads if a["adset_key"] == aid)
        if raw.get("is_dynamic_creative") and n_new:
            errs.append(f"The ad set '{raw.get('name')}' uses dynamic creative, which holds only one ad. Add the new ad to a different ad set, or replace its ad.")
        if (raw.get("effective_status") or "") in ("ARCHIVED", "DELETED"):
            errs.append(f"The ad set '{raw.get('name')}' is archived, so ads can't be added to it.")
    return {"ads": ads, "errors": errs, "warnings": warns, "fixes": fixes, "pair": pair, "live": live, "m": m}


@router.post("/api/manage/ads/preview")
async def preview_ads(req: Request):
    s = _settings()
    d = _prepare_ads(s, await req.json())
    return {"errors": d["errors"], "warnings": d["warnings"], "fixes": d["fixes"], "pair_warnings": d["pair"], "env": s.env,
            "ads": [{"id": a["ad_key"], "name": a.get("name") or a["ad_key"], "adset": d["live"][a["adset_key"]].get("name"), "type": describe(a["creative_spec"])["kind"] if a.get("creative_spec") else "Single image"} for a in d["ads"]]}


def _upload_local(s: Settings, meta: Meta, ent: dict) -> str:
    """A local picture goes to Meta once (the same file is never uploaded twice) and its hash is remembered."""
    reg = Registry(s, "upload_registry.json")
    p = image_path(ent)
    digest = sha256(p)
    have = {v["sha256"]: v["meta_image_hash"] for v in reg.d.values() if v.get("uploaded") and v.get("sha256")}
    if digest in have:
        h = have[digest]
        print(f"  {ent['ad_key']}: identical picture already on Meta")
    else:
        res = meta.post(f"{s.account}/adimages", {}, files={p.name: (p.name, p.read_bytes())})
        h = next(iter(res["images"].values()))["hash"]
        print(f"  {ent['ad_key']}: picture uploaded")
    reg.update(ent["ad_key"], folder=p.parent.name, filename=p.name, sha256=digest, meta_image_hash=h, uploaded=True)
    return h


def _create_ad(s: Settings, meta: Meta, ent: dict, adset_id: str, status: str, label: str) -> dict:
    """One new ad in an existing ad set: upload what is local, create the creative, then the ad. Remembered, so a retry never makes a second one."""
    acc, ents, ads_reg = account_cfg(), Registry(s, "entity_registry.json"), Registry(s, "ad_registry.json")
    k = ent["ad_key"]
    if ads_reg.get(k, {}).get("meta_ad_id"):
        print(f"  {k}: already created ({ads_reg.get(k)['meta_ad_id']})")
        return {"key": k, "id": ads_reg.get(k)["meta_ad_id"], "creative_id": ads_reg.get(k).get("meta_creative_id")}
    batch_id = f"MANAGE_{datetime.now().strftime('%Y%m%d_%H%M')}"
    h = None
    if ent.get("creative_spec"):
        if media.files_in(ent["creative_spec"]):
            print(f"  {k}: uploading its pictures and videos")
            media.upload_files(s, meta, ent["creative_spec"])
    elif ent.get("image"):
        h = _upload_local(s, meta, ent)
    else:
        h = ent.get("image_hash")
    payload = create_creatives.payload(ent, h or "", batch_id, s, acc)
    cid = ensure(s, meta, ents, f"creative:{k}", "adcreatives", ent.get("name") or k, payload, lookup=False)
    ad_payload = {"name": ent.get("name") or k, "adset_id": adset_id, "creative": {"creative_id": cid}, "status": status}
    if ent.get("labels"):
        ad_payload["adlabels"] = [{"name": str(x)} for x in ent["labels"] if str(x).strip()]
    res = meta.post(f"{s.account}/ads", ad_payload)
    ads_reg.update(k, batch=label, meta_creative_id=cid, meta_ad_id=res["id"], adset_key=adset_id, adset_id=adset_id, status=status)
    print(f"  {k}: ad created {status} ({res['id']})")
    return {"key": k, "id": res["id"], "creative_id": cid}


@router.post("/api/manage/ads/apply")
async def apply_ads(req: Request):
    body = await req.json()
    s = _settings()
    d = _prepare_ads(s, body)
    if d["errors"]:
        raise HTTPException(400, {"errors": d["errors"]})
    turn_on = bool(body.get("turn_on"))
    _need_confirm(s, body, turn_on)
    status = "ACTIVE" if turn_on else "PAUSED"
    created: list = []

    def work():
        m = Meta(s)
        for ent in d["ads"]:
            created.append(_create_ad(s, m, ent, ent["adset_key"], status, "manage"))
        if created:
            _log(s, "ads_added", ",".join(c["id"] for c in created), f"{len(created)} ad(s)", {}, {"status": status},
                 note=f"{len(created)} new ad(s) added to {len({e['adset_key'] for e in d['ads']})} ad set(s), {status.lower()}", extra={"ad_ids": [c["id"] for c in created]})

    job = start_job(f"add {len(d['ads'])} ad(s) to existing ad sets", [("Create the creatives and ads", work)], lambda ok: {"created": created, "status": status})
    return {"job": job["id"]}


# ---- changing the creative of one ad -------------------------------------------------------------------------------------------
def _read_ad(s: Settings, m: Meta, ad_id: str) -> dict:
    try:
        return m.get(ad_id, fields=AD_READ)
    except MetaError as e:
        raise _fail(s, e)


@router.post("/api/manage/ad/preview")
async def preview_replace(req: Request):
    body = await req.json()
    s = _settings()
    old = _read_ad(s, Meta(s), str(body.get("ad_id")))
    d = _prepare_ads(s, {"adset_ids": [old["adset_id"]], "ads": [{**(body.get("ad") or {}), "sets": None}]})
    if len(d["ads"]) != 1 and not d["errors"]:
        d["errors"].append("Build exactly one new ad.")
    # a dynamic creative ad set holds one ad: replacing is fine, adding is not
    d["errors"] = [e for e in d["errors"] if "holds only one ad" not in e] if (body.get("mode") == "in_place") else d["errors"]
    return {"errors": d["errors"], "warnings": d["warnings"], "fixes": d["fixes"], "pair_warnings": d["pair"], "old": {"id": str(old["id"]), "name": old.get("name"), "status": old.get("effective_status") or old.get("status"),
            "type": describe(old.get("creative") or {})["kind"]}, "env": s.env}


@router.post("/api/manage/ad/apply")
async def apply_replace(req: Request):
    """mode 'new_ad': add a new ad with the new creative to the same ad set (paused), and with switch_over pause the old one and turn the new one on.
    mode 'in_place': point the existing ad at a new creative (the ad goes back into Meta's review; the old creative is kept so this can be undone)."""
    body = await req.json()
    s = _settings()
    mode = body.get("mode")
    if mode not in ("new_ad", "in_place"):
        raise HTTPException(400, "mode must be new_ad or in_place")
    m = Meta(s)
    old = _read_ad(s, m, str(body.get("ad_id")))
    d = _prepare_ads(s, {"adset_ids": [old["adset_id"]], "ads": [{**(body.get("ad") or {}), "sets": None}]})
    errs = [e for e in d["errors"] if not (mode == "in_place" and "holds only one ad" in e)]
    if errs or len(d["ads"]) != 1:
        raise HTTPException(400, {"errors": errs or ["Build exactly one new ad."]})
    ent = d["ads"][0]
    switch = bool(body.get("switch_over")) and mode == "new_ad"
    _need_confirm(s, body, switch or (mode == "in_place" and (old.get("effective_status") or "") == "ACTIVE"))

    def work():
        mm = Meta(s)
        if mode == "new_ad":
            made = _create_ad(s, mm, ent, str(old["adset_id"]), "ACTIVE" if switch else "PAUSED", "manage")
            if switch and (old.get("status") or "") != "PAUSED":
                mm.post(str(old["id"]), {"status": "PAUSED"})
                print(f"  old ad {old['id']} paused")
            _log(s, "ad_replaced", made["id"], ent.get("name") or ent["ad_key"], {"old_ad": str(old["id"]), "old_status": old.get("status")}, {"new_ad": made["id"], "switched": switch},
                 note=("new ad turned on, old ad paused" if switch else "new ad added paused; the old ad was left as it is"), extra={"old_ad": str(old["id"]), "new_ad": made["id"]})
        else:
            made = _create_ad_creative_only(s, mm, ent)
            mm.post(str(old["id"]), {"creative": {"creative_id": made["creative_id"]}})
            print(f"  ad {old['id']} now uses the new creative {made['creative_id']} (back in Meta's review)")
            _log(s, "ad_creative", str(old["id"]), old.get("name"), {"creative_id": (old.get("creative") or {}).get("id")}, {"creative_id": made["creative_id"]}, note="creative replaced in place")

    job = start_job(f"change the creative of ad {old.get('name')}", [("Create the new creative" + (" and ad" if mode == "new_ad" else "") , work)], lambda ok: {"mode": mode})
    return {"job": job["id"]}


def _create_ad_creative_only(s: Settings, meta: Meta, ent: dict) -> dict:
    acc, ents = account_cfg(), Registry(s, "entity_registry.json")
    k = ent["ad_key"]
    h = None
    if ent.get("creative_spec"):
        if media.files_in(ent["creative_spec"]):
            media.upload_files(s, meta, ent["creative_spec"])
    elif ent.get("image"):
        h = _upload_local(s, meta, ent)
    else:
        h = ent.get("image_hash")
    payload = create_creatives.payload(ent, h or "", f"MANAGE_{datetime.now().strftime('%Y%m%d_%H%M')}", s, acc)
    cid = ensure(s, meta, ents, f"creative:{k}", "adcreatives", ent.get("name") or k, payload, lookup=False)
    Registry(s, "ad_registry.json").update(k, batch="manage", meta_creative_id=cid, status="CREATIVE_ONLY")
    return {"key": k, "creative_id": cid}


# ---- undo -----------------------------------------------------------------------------------------------------------------------
@router.post("/api/manage/undo/{log_id}")
async def undo(log_id: str, req: Request):
    body = await req.json()
    s = _settings()
    reg = Registry(s, "change_log.json")
    e = reg.get(log_id)
    if not e or e.get("undone"):
        raise HTTPException(404, "that change is not in the log, or was already undone")
    m = Meta(s)
    kind, oid = e["kind"], e["object_id"]
    spends = kind == "status" and e["before"].get("status") == "ACTIVE"
    _need_confirm(s, body, spends)
    try:
        if kind == "adset_update":
            cur = m.get(oid, fields=ADSET_READ)
            moved = [k for k, v in e["after"].items() if k != "targeting" and not _loose_equal(v, cur.get(k))]
            if moved:
                raise HTTPException(409, {"errors": ["It has changed again since (" + ", ".join(moved) + "), so it was not undone. Edit it by hand."]})
            before = dict(e["before"])
            if isinstance(before.get("targeting"), dict):
                before["targeting"] = scrub_targeting(before["targeting"])[0]
            m.post(oid, before)
        elif kind == "status":
            m.post(oid, {"status": e["before"]["status"]})
        elif kind == "ad_creative":
            m.post(oid, {"creative": {"creative_id": e["before"]["creative_id"]}})
        elif kind == "ad_replaced":
            m.post(e["new_ad"], {"status": "PAUSED"})
            if e["before"].get("old_status") == "ACTIVE":
                m.post(e["old_ad"], {"status": "ACTIVE"})
        elif kind == "ads_added":
            for aid in e.get("ad_ids", []):
                m.post(aid, {"status": "PAUSED"})
        else:
            raise HTTPException(400, "this kind of change cannot be undone here")
    except MetaError as ex:
        raise _fail(s, ex)
    reg.update(log_id, undone=True)
    _log(s, "undo", oid, e.get("name") or "", e.get("after") or {}, e.get("before") or {}, note=f"undid: {e.get('note') or e['kind']}"[:300])
    return {"undone": True, "note": "Ads added were paused (not deleted)." if kind == "ads_added" else ""}
