"""Step 6a - campaigns. Always created PAUSED."""
from __future__ import annotations

from .common import Registry, Settings, account_cfg, campaigns_cfg, clean_extra, deep_merge, minor
from .ensure import ensure
from .meta_api import Meta


def payload(c: dict, acc: dict) -> dict:
    p = {"name": c["key"], "objective": c["objective"], "status": "PAUSED", "special_ad_categories": c.get("special_ad_categories", [])}
    if c["budget_strategy"] == "CBO":
        p["daily_budget"] = minor(c["daily_budget"], acc)
        p["bid_strategy"] = c.get("bid_strategy", "LOWEST_COST_WITHOUT_CAP")
    else:
        p["is_adset_budget_sharing_enabled"] = False  # budgets live on the ad sets
    if c.get("spend_cap"):
        p["spend_cap"] = minor(c["spend_cap"], acc)
    extra, _ = clean_extra(c.get("extra"))
    return deep_merge(p, extra)  # anything not covered above (Meta setting names), already made safe


def run(s: Settings, meta: Meta, keys: list[str], validate_only=False) -> None:
    acc, camps, reg = account_cfg(), campaigns_cfg(), Registry(s, "entity_registry.json")
    for k in keys:
        ensure(s, meta, reg, f"campaign:{k}", "campaigns", k, payload(camps[k], acc), validate_only)
