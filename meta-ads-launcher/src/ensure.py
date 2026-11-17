"""'Create it only if it does not exist yet' - the reason re-running a batch never makes duplicates."""
from __future__ import annotations

from .common import Registry, Settings
from .meta_api import Meta


def ensure(s: Settings, meta: Meta, reg: Registry, reg_key: str, edge: str, name: str, payload: dict,
           validate_only: bool = False, lookup: bool = True):
    """Returns the Meta id, or None when only validating. Order: our registry -> same name already on Meta -> create."""
    have = reg.get(reg_key, {}).get("id")
    if have:
        print(f"  {reg_key}: exists ({have})")
        return have
    if lookup and not validate_only:
        found = meta.find_by_name(edge, name)
        if found:
            reg.update(reg_key, id=found, name=name, recovered=True)
            print(f"  {reg_key}: found on Meta by name, adopted ({found})")
            return found
    res = meta.post(f"{s.account}/{edge}", payload, validate_only=validate_only)
    if validate_only:
        print(f"  {reg_key}: passed Meta's validation (nothing created)")
        return None
    new = res["id"]
    if not meta.dry:
        reg.update(reg_key, id=new, name=name, status="PAUSED")
    print(f"  {reg_key}: " + ("would be created PAUSED" if meta.dry else f"created PAUSED ({new})"))
    return new
