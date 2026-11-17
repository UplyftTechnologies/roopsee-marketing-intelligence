"""Step 9 - the ONLY place that turns anything ACTIVE. Campaign, ad set and ad must all be active for an ad to run."""
from __future__ import annotations

from .common import LauncherError, Registry, Settings, ask, ready_ads
from .meta_api import Meta


def run(s: Settings, meta: Meta, batch: str, assume_yes: bool = False, confirmed: bool = False) -> None:
    _, ads = ready_ads(batch)
    reg = Registry(s, "ad_registry.json")
    todo = [a for a in ads if reg.get(a["ad_key"], {}).get("meta_ad_id") and reg.get(a["ad_key"])["status"] != "ACTIVE"]
    if not todo:
        print("publish: nothing to publish (create the paused ads with 'prepare' first, or they are already active)")
        return
    print(f"About to ACTIVATE {len(todo)} ad(s) in {s.env.upper()} ({s.account}):")
    for a in todo:
        r = reg.get(a["ad_key"])
        print(f"  {a['ad_key']:16s} adset {a['adset_key']}  -> {a['destination']}")
    if not meta.dry and not confirmed:
        if s.env == "production" or not assume_yes:
            if not ask("This can start spending money." if s.env == "production" else "Activate these ads?", "PUBLISH"):
                raise LauncherError("not confirmed - nothing was published")
    ent = Registry(s, "entity_registry.json")
    for a in todo:
        r = reg.get(a["ad_key"])
        for kind, obj_id in (("campaign", r["campaign_id"]), ("adset", r["adset_id"]), ("ad", r["meta_ad_id"])):
            meta.post(obj_id, {"status": "ACTIVE"})
        if not meta.dry:
            reg.update(a["ad_key"], status="ACTIVE")
            ent.update(f"adset:{r['adset_key']}", status="ACTIVE")
        print(f"  {a['ad_key']}: ACTIVE (Meta will review it before it delivers)")
