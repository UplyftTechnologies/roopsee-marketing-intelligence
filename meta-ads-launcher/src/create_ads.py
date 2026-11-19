"""Step 8 - ads: attach each creative to its ad set. Always created PAUSED. Freezes the batch file afterwards."""
from __future__ import annotations

from .common import LauncherError, Registry, Settings, adsets_cfg, batch_path, ready_ads, sha256
from . import ensure as ensure_mod
from .ensure import ensure
from .meta_api import Meta


def run(s: Settings, meta: Meta, batch: str, validate_only=False) -> None:
    b, ads = ready_ads(batch)
    sets, ent, reg, hashes = adsets_cfg(), Registry(s, "entity_registry.json"), Registry(s, "ad_registry.json"), Registry(s, "batch_hashes.json")
    done = 0
    for ad in ads:
        k = ad["ad_key"]
        aset = ent.get(f"adset:{ad['adset_key']}", {}).get("id")
        creative = ent.get(f"creative:{k}", {}).get("id")
        if not (aset and creative):
            if validate_only or meta.dry:
                print(f"  ad:{k}: skipped (needs its ad set + creative to exist first)")
                continue
            raise LauncherError(f"{k}: ad set or creative missing - run setup, then prepare")
        # ads are looked up in our registry (ad_registry) first, then by name on Meta
        if reg.get(k, {}).get("meta_ad_id"):
            print(f"  ad:{k}: exists ({reg.get(k)['meta_ad_id']})")
            done += 1
            continue
        shown = ad.get("name") or k  # the name people see in Ads Manager (the Ad ID is the default)
        payload = {"name": shown, "adset_id": aset, "creative": {"creative_id": creative}, "status": "PAUSED"}
        existing = None if (validate_only or ad.get("name") or not ensure_mod.LOOKUPS) else meta.find_by_name("ads", k)
        if existing:
            ad_id = existing
            print(f"  ad:{k}: found on Meta by name, adopted ({ad_id})")
        else:
            res = meta.post(f"{s.account}/ads", payload, validate_only=validate_only)
            if validate_only:
                print(f"  ad:{k}: passed Meta's validation (nothing created)")
                continue
            ad_id = res["id"]
            print(f"  ad:{k}: created PAUSED ({ad_id})")
        if not meta.dry:
            ci = sets[ad["adset_key"]]["campaign_key"]
            reg.update(k, batch=batch.replace(".json", ""), meta_creative_id=creative, meta_ad_id=ad_id, adset_key=ad["adset_key"],
                       adset_id=aset, campaign_id=ent.get(f"campaign:{ci}", {}).get("id"), status="PAUSED")
            done += 1
    # freeze the batch once every READY ad exists on Meta
    if not (meta.dry or validate_only) and ads and done == len(ads):
        hashes.update(batch.replace(".json", ""), sha256=sha256(batch_path(batch)))
        print(f"  batch {batch} is now frozen (further edits are rejected by validate)")
