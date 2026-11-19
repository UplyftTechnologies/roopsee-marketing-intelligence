"""Clear the launcher's own record of a campaign it created once that campaign no longer exists on Meta, so its name can be used again.

The launcher remembers each campaign it made (config/campaigns.json, config/adsets.json, the batch file of its ads, and an id registry per environment).
Deleting the campaign on Meta does not change those, so the name stayed 'taken'. Clearing it MOVES everything to backups/ first, so nothing is lost
and it can be put back by hand. Ad IDs stay in the ad registry: an ad ID is never reused."""
from __future__ import annotations

import re
import shutil
import time

from .common import ROOT, LauncherError, Registry, Settings, batch_files, jload, jsave
from .meta_api import Meta, MetaError

ENVS = ("sandbox", "production")


def _safe(name: str) -> str:
    return re.sub(r"[^A-Za-z0-9_.-]+", "_", name)[:60]


def exists_on_meta(s: Settings, obj_id: str) -> bool | None:
    """True / False when Meta says so, None when that cannot be told (no credentials, Meta limiting calls, another error)."""
    if s.missing():
        return None
    try:
        r = Meta(s).get(str(obj_id), fields="id,effective_status")
    except MetaError as e:
        text = str(e).lower()
        if "does not exist" in text or "unsupported get request" in text:
            return False
        return None
    return r.get("effective_status") not in ("DELETED", "ARCHIVED")


def recorded_ids(name: str) -> dict:
    """{env: (Settings, campaign id)} for every environment where the launcher created this campaign."""
    out = {}
    for env in ENVS:
        e = Settings(env)
        cid = Registry(e, "entity_registry.json").get(f"campaign:{name}", {}).get("id")
        if cid:
            out[env] = (e, cid)
    return out


def is_gone(name: str) -> bool:
    """True when the launcher has a record of this campaign but it no longer exists on Meta in any environment (or was never created at all)."""
    ids = recorded_ids(name)
    return all(exists_on_meta(e, cid) is False for e, cid in ids.values())  # no ids at all: nothing was created, only a leftover record


def owner_of_adset(key: str) -> str | None:
    for a in (jload(ROOT / "config" / "adsets.json", {}) or {}).get("adsets", []):
        if a.get("key") == key:
            return a.get("campaign_key")
    return None


def forget_campaign(name: str) -> dict:
    """Move this campaign's launcher records to backups/ and remove them from the live files. Returns what was moved."""
    cfg_c, cfg_a = ROOT / "config" / "campaigns.json", ROOT / "config" / "adsets.json"
    camps = jload(cfg_c, {"campaigns": []}) or {"campaigns": []}
    sets = jload(cfg_a, {"adsets": []}) or {"adsets": []}
    c_entries = [c for c in camps.get("campaigns", []) if c.get("key") == name]
    a_entries = [a for a in sets.get("adsets", []) if a.get("campaign_key") == name]
    if not c_entries and not a_entries:
        return {"campaign": name, "moved": False}
    keys = {a["key"] for a in a_entries}
    batches = []
    for bf in batch_files():
        used = {ad.get("adset_key") for ad in (jload(bf, {}) or {}).get("ads", [])}
        if used & keys:
            if not used <= keys:  # a batch that also belongs to another campaign cannot be moved without breaking that one
                raise LauncherError(f"The batch {bf.stem} also holds ads of another campaign, so '{name}' cannot be cleared automatically.")
            batches.append(bf)
    dest = ROOT / "backups" / f"forgot_{_safe(name)}_{time.strftime('%Y%m%d_%H%M%S')}"
    dest.mkdir(parents=True, exist_ok=True)
    removed_reg: dict = {}
    for env in ENVS:
        ent, hashes = Registry(Settings(env), "entity_registry.json"), Registry(Settings(env), "batch_hashes.json")
        gone = {k: ent.d[k] for k in [f"campaign:{name}", *[f"adset:{k}" for k in keys]] if k in ent.d}
        gone_h = {b.stem: hashes.d[b.stem] for b in batches if b.stem in hashes.d}
        removed_reg[env] = {"entity_registry": gone, "batch_hashes": gone_h}
        for k in gone:
            ent.d.pop(k)
        for k in gone_h:
            hashes.d.pop(k)
        if gone:
            jsave(ent.path, ent.d)
        if gone_h:
            jsave(hashes.path, hashes.d)
    jsave(dest / "removed.json", {"campaign": c_entries, "adsets": a_entries, "registry": removed_reg, "batches": [b.name for b in batches],
                                  "note": "Cleared because the campaign no longer exists on Meta. To put it back, add the entries to config/ and data/<env>/, and move the batch file to ads/."})
    for b in batches:
        shutil.move(str(b), str(dest / b.name))
    camps["campaigns"] = [c for c in camps.get("campaigns", []) if c.get("key") != name]
    sets["adsets"] = [a for a in sets.get("adsets", []) if a.get("campaign_key") != name]
    jsave(cfg_c, camps)
    jsave(cfg_a, sets)
    return {"campaign": name, "moved": True, "adsets": sorted(keys), "batches": [b.stem for b in batches], "backup": str(dest.relative_to(ROOT))}
