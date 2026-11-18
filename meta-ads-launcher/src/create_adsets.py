"""Step 6b - ad sets (audience, placements, optimisation). Always created PAUSED."""
from __future__ import annotations

from .common import LauncherError, Registry, Settings, account_cfg, adsets_cfg, audiences_cfg, campaigns_cfg, clean_extra, deep_merge, minor
from .ensure import ensure
from .meta_api import Meta


def targeting(a: dict, aud: dict) -> dict:
    t = {"geo_locations": {"countries": aud["countries"]} if aud.get("countries") else {}, "age_min": aud.get("age_min", 18), "age_max": aud.get("age_max", 65),
         "targeting_automation": {"advantage_audience": 0}}  # 0 = keep to the age/country we set
    if aud.get("genders"):
        t["genders"] = aud["genders"]  # 1 = men, 2 = women
    places = a.get("placements", ["automatic"])
    if "automatic" not in places and "custom" not in places:  # "custom" = the platforms and positions come from targeting_extra
        t["publisher_platforms"] = places
    extra, _ = clean_extra(a.get("targeting_extra"))  # cities, interests, custom audiences, exclusions, positions ... (Meta's own targeting names)
    return deep_merge(t, extra)


def payload(a: dict, campaign_id: str, s: Settings, acc: dict, camp: dict, aud: dict) -> dict:
    goal = a.get("optimization_goal") or ("OFFSITE_CONVERSIONS" if a.get("optimization_event") else "LINK_CLICKS")
    p = {"name": a["key"], "campaign_id": campaign_id, "status": "PAUSED", "billing_event": a.get("billing_event", "IMPRESSIONS"), "optimization_goal": goal,
         "destination_type": a.get("destination_type", "WEBSITE"), "targeting": targeting(a, aud)}
    if camp["budget_strategy"] == "ABO":
        if a.get("lifetime_budget"):
            p["lifetime_budget"] = minor(a["lifetime_budget"], acc)
        else:
            p["daily_budget"] = minor(a["daily_budget"], acc)
        p["bid_strategy"] = a.get("bid_strategy", "LOWEST_COST_WITHOUT_CAP")
    if a.get("bid_amount"):
        p["bid_amount"] = minor(a["bid_amount"], acc)
    if goal in ("OFFSITE_CONVERSIONS", "VALUE"):
        if not s.pixel_id and not (a.get("extra") or {}).get("promoted_object", {}).get("pixel_id"):
            raise LauncherError(f"ad set {a['key']} optimises for conversions: set META_{s.env.upper()}_PIXEL_ID in .env")
        p["promoted_object"] = {"pixel_id": s.pixel_id, "custom_event_type": a.get("optimization_event") or "PURCHASE"} if s.pixel_id else {"custom_event_type": a.get("optimization_event") or "PURCHASE"}
    if a.get("start_time"):
        p["start_time"] = a["start_time"]
    if a.get("end_time"):
        p["end_time"] = a["end_time"]
    extra, _ = clean_extra(a.get("extra"))
    if "promoted_object" in extra and "promoted_object" in p:
        extra["promoted_object"] = deep_merge(p["promoted_object"], extra["promoted_object"])
    return deep_merge(p, extra)


def run(s: Settings, meta: Meta, keys: list[str], validate_only=False) -> None:
    acc, sets, camps, auds, reg = account_cfg(), adsets_cfg(), campaigns_cfg(), audiences_cfg(), Registry(s, "entity_registry.json")
    for k in keys:
        a = sets[k]
        cid = reg.get(f"campaign:{a['campaign_key']}", {}).get("id")
        if not cid and meta.dry:
            cid = "DRY_CAMPAIGN"
        if not cid:
            if validate_only:
                print(f"  adset:{k}: skipped (its campaign does not exist yet, so Meta cannot validate it)")
                continue
            raise LauncherError(f"ad set {k}: campaign {a['campaign_key']} has no Meta id yet - run setup in order")
        ensure(s, meta, reg, f"adset:{k}", "adsets", k, payload(a, cid, s, acc, camps[a["campaign_key"]], auds[a["audience"]]), validate_only)
