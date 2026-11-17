"""'doctor' (read-only health check) and 'status'. Neither creates or changes anything on Meta."""
from __future__ import annotations

from datetime import datetime, timezone

import requests

from .common import LauncherError, Registry, Settings, account_cfg, audiences_cfg, batch_files, jload
from .meta_api import Meta, MetaError

NEED_SCOPES = ("ads_management", "ads_read")


def doctor(s: Settings) -> bool:
    ok = True

    def line(good, label, detail=""):
        nonlocal ok
        ok &= bool(good)
        print(f"  {'OK  ' if good else 'FAIL'}  {label}" + (f"  - {detail}" if detail else ""))

    print(f"environment: {s.env.upper()}   api: {s.version}")
    miss = s.missing()
    line(not miss, "credentials present in .env", ", ".join(miss) if miss else f"account {s.account}, page {s.page_id}")
    if miss:
        return False
    meta = Meta(s)
    try:
        me = meta.get("me", fields="id,name")
        line(True, "token accepted by Meta (appsecret_proof ok)", me.get("name", "?"))
    except MetaError as e:
        line(False, "token accepted by Meta", str(e))
        return False
    if s.app_id:
        try:
            r = requests.get(f"{meta.base}debug_token", params={"input_token": s.token, "access_token": f"{s.app_id}|{s.app_secret}"}, timeout=30).json().get("data", {})
            exp = r.get("expires_at") or r.get("data_access_expires_at")
            when = "never (System User token)" if not r.get("expires_at") else datetime.fromtimestamp(r["expires_at"], timezone.utc).strftime("%Y-%m-%d")
            line(r.get("is_valid"), "token is valid", f"expires {when}")
            have = set(r.get("scopes", []))
            line("ads_management" in have, "token has ads_management (needed to create)", f"granted: {', '.join(sorted(have)) or 'none listed'}")
            if "ads_read" not in have:
                print("  note  ads_read is not listed; the next check proves whether reading works anyway")
        except Exception as e:  # noqa: BLE001
            line(False, "token inspection (needs META_*_APP_ID)", s.redact(e))
    else:
        print("  skip  token expiry/scopes check (set APP_ID to enable)")
    try:
        a = meta.get(s.account, fields="name,account_status,currency,timezone_name")
        acc = account_cfg()
        cur_ok = not acc.get("currency") or acc["currency"] == a.get("currency")
        line(True, "ad account reachable", f"{a.get('name')} | {a.get('currency')} | {a.get('timezone_name')} | status {a.get('account_status')}")
        line(cur_ok, "currency matches config/account.json", f"config says {acc.get('currency')}, account is {a.get('currency')}" if not cur_ok else "")
    except MetaError as e:
        line(False, "ad account reachable", str(e))
    try:
        n = len(meta.get(f"{s.account}/campaigns", fields="id", limit=1).get("data", []))
        line(True, "can read campaigns on the ad account", f"{n} found" if n else "none yet")
    except MetaError as e:
        line(False, "can read campaigns on the ad account", str(e))
    try:
        p = meta.get(s.page_id, fields="name")
        line(True, "Facebook Page reachable", p.get("name", ""))
    except MetaError as e:
        line(False, "Facebook Page reachable (creatives need it)", str(e))
    line(bool(audiences_cfg()) and bool(batch_files()), "config + at least one batch present")
    print("\ndoctor: " + ("all good" if ok else "fix the FAIL lines above"))
    return ok


def images(s: Settings) -> None:
    """List images already in the ad account with their hashes (read-only), so a hash can be pasted into a batch."""
    rows = Meta(s).pages(f"{s.account}/adimages", fields="hash,name,width,height,created_time", limit=100)
    print(f"{len(rows)} image(s) in {s.account}")
    for r in rows:
        print(f"  {r['hash']}  {r.get('width')}x{r.get('height')}  {r.get('name', '')}  {r.get('created_time', '')[:10]}")


def live(s: Settings) -> None:
    """Everything that exists in the ad account right now, read straight from Meta (campaign > ad set > ad)."""
    meta = Meta(s)
    acc = s.account
    camps = meta.pages(f"{acc}/campaigns", fields="id,name,objective,effective_status,daily_budget,created_time", limit=100)
    sets = meta.pages(f"{acc}/adsets", fields="id,name,campaign_id,effective_status,optimization_goal,daily_budget", limit=200)
    ads = meta.pages(f"{acc}/ads", fields="id,name,adset_id,effective_status,creative{id}", limit=200)
    imgs = meta.pages(f"{acc}/adimages", fields="hash,name", limit=100)
    print(f"LIVE on Meta - {s.env.upper()} {acc}: {len(camps)} campaign(s), {len(sets)} ad set(s), {len(ads)} ad(s), {len(imgs)} image(s)\n")
    money = lambda v: f"INR {int(v) / 100:,.0f}/day" if v else "-"
    for c in camps:
        print(f"CAMPAIGN  {c['name']}  [{c.get('effective_status')}]  {c.get('objective')}  {money(c.get('daily_budget'))}  id {c['id']}")
        for a in [x for x in sets if x.get("campaign_id") == c["id"]]:
            print(f"  AD SET  {a['name']}  [{a.get('effective_status')}]  {a.get('optimization_goal')}  {money(a.get('daily_budget'))}  id {a['id']}")
            for d in [x for x in ads if x.get("adset_id") == a["id"]]:
                print(f"    AD    {d['name']}  [{d.get('effective_status')}]  creative {(d.get('creative') or {}).get('id', '-')}  id {d['id']}")
    for i in imgs:
        print(f"IMAGE  {i['hash']}  {i.get('name', '')}")


def status(s: Settings, live: bool = False) -> None:
    ent, ads = Registry(s, "entity_registry.json"), Registry(s, "ad_registry.json")
    print(f"environment: {s.env.upper()}")
    for k, v in ent.d.items():
        print(f"  {k:36s} {v.get('id')}  {v.get('status', '')}")
    print(f"\nads: {len(ads.d)}")
    for k, v in ads.d.items():
        print(f"  {k:16s} batch {v.get('batch')}  ad {v.get('meta_ad_id')}  {v.get('status')}")
    if live and ads.d:
        meta = Meta(s)
        print("\nlive state on Meta:")
        for k, v in ads.d.items():
            try:
                r = meta.get(v["meta_ad_id"], fields="effective_status,configured_status")
                print(f"  {k:16s} {r.get('effective_status')} (configured {r.get('configured_status')})")
            except MetaError as e:
                print(f"  {k:16s} {e}")
