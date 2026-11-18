"""Local checks only - no network. Catches mistakes before anything is sent to Meta."""
from __future__ import annotations

import re
import struct
from urllib.parse import urlparse

from .common import (AD_KEY_RE, BID_STRATEGIES, BILLING_EVENTS, CTAS, DESTINATIONS, FORBIDDEN_EXTRA, GOALS, KEY_RE, OBJECTIVES, PLACEMENTS, ROOT, STATUSES, LauncherError, Registry, Settings, account_cfg, adsets_cfg,
                     audiences_cfg, batch_files, campaigns_cfg, image_path, jload, sha256)

MAX_BYTES = 30 * 1024 * 1024
RATIOS = {"1:1": 1.0, "4:5": 0.8, "9:16": 0.5625, "1.91:1": 1.91}


def image_size(p):
    """(width, height) of a PNG or JPEG without any imaging library."""
    with open(p, "rb") as f:
        head = f.read(24)
        if head[:8] == b"\x89PNG\r\n\x1a\n":
            return struct.unpack(">II", head[16:24])
        if head[:2] == b"\xff\xd8":
            f.seek(2)
            while True:
                b = f.read(1)
                while b and b != b"\xff":
                    b = f.read(1)
                while b == b"\xff":
                    b = f.read(1)
                if not b:
                    return None
                n = b[0]
                if 0xC0 <= n <= 0xCF and n not in (0xC4, 0xC8, 0xCC):
                    f.read(3)
                    h, w = struct.unpack(">HH", f.read(4))
                    return w, h
                (ln,) = struct.unpack(">H", f.read(2))
                f.seek(ln - 2, 1)
    return None


def validate(s: Settings, only: str | None = None) -> tuple[list[str], list[str]]:
    errors: list[str] = []
    warns: list[str] = []
    acc, camps, sets, auds = account_cfg(), campaigns_cfg(), adsets_cfg(), audiences_cfg()

    def err(m): errors.append(m)
    def warn(m): warns.append(m)

    # ---- config ----
    for f in ("account", "campaigns", "adsets", "audiences"):
        try:
            jload(ROOT / "config" / f"{f}.json", None) or err(f"config/{f}.json is missing or empty")
        except LauncherError as e:
            err(str(e))
    for k, c in camps.items():
        if c.get("objective") not in OBJECTIVES:
            err(f"campaign {k}: objective must be one of {sorted(OBJECTIVES)}")
        if c.get("budget_strategy") not in ("CBO", "ABO"):
            err(f"campaign {k}: budget_strategy must be CBO or ABO")
        if c.get("budget_strategy") == "CBO" and not (isinstance(c.get("daily_budget"), (int, float)) and c["daily_budget"] > 0):
            err(f"campaign {k}: CBO needs a positive daily_budget")
        if c.get("status", "PAUSED") != "PAUSED":
            err(f"campaign {k}: status must be PAUSED (publishing is a separate, approved step)")
    for k, a in sets.items():
        if a.get("campaign_key") not in camps:
            err(f"ad set {k}: unknown campaign_key '{a.get('campaign_key')}'")
        if a.get("audience") not in auds:
            err(f"ad set {k}: unknown audience '{a.get('audience')}' (defined: {', '.join(auds) or 'none'})")
        bad = [p for p in a.get("placements", []) if p not in PLACEMENTS]
        if bad:
            err(f"ad set {k}: unknown placements {bad} (allowed: {sorted(PLACEMENTS)})")
        goal = a.get("optimization_goal") or ("OFFSITE_CONVERSIONS" if a.get("optimization_event") else "LINK_CLICKS")
        if goal not in GOALS:
            err(f"ad set {k}: optimization_goal must be one of {sorted(GOALS)}")
        if goal == "OFFSITE_CONVERSIONS" and not a.get("optimization_event"):
            err(f"ad set {k}: OFFSITE_CONVERSIONS needs optimization_event (e.g. PURCHASE)")
        if camps.get(a.get("campaign_key"), {}).get("budget_strategy") == "ABO" and not a.get("daily_budget"):
            err(f"ad set {k}: campaign is ABO, so the ad set needs its own daily_budget")
        camp = camps.get(a.get("campaign_key"), {})
        if camp.get("objective") == "OUTCOME_SALES" and goal != "OFFSITE_CONVERSIONS":
            warn(f"ad set {k}: Sales campaigns normally optimise for conversions (needs a pixel/dataset)")
    def shape(where, obj, keys):
        for k in keys:
            if obj.get(k) is not None and not isinstance(obj[k], dict):
                err(f"{where}: {k} must be an object (curly brackets)")
            bad = sorted(set((obj.get(k) or {}).keys()) & FORBIDDEN_EXTRA) if isinstance(obj.get(k), dict) else []
            if bad:
                warn(f"{where}: {k} contains {bad}; these are ignored (ids, names and status are managed by the launcher)")

    for k, c in camps.items():
        shape(f"campaign {k}", c, ("extra",))
    for k, a in sets.items():
        shape(f"ad set {k}", a, ("extra", "targeting_extra"))
        if a.get("bid_strategy") and a["bid_strategy"] not in BID_STRATEGIES:
            err(f"ad set {k}: bid_strategy must be one of {sorted(BID_STRATEGIES)}")
        if a.get("billing_event") and a["billing_event"] not in BILLING_EVENTS:
            err(f"ad set {k}: billing_event must be one of {sorted(BILLING_EVENTS)}")
        if a.get("destination_type") and a["destination_type"] not in DESTINATIONS:
            warn(f"ad set {k}: destination_type '{a['destination_type']}' is not one I know; Meta's check will tell you if it is valid")
        if a.get("bid_strategy") in ("LOWEST_COST_WITH_BID_CAP", "COST_CAP") and not a.get("bid_amount"):
            err(f"ad set {k}: {a['bid_strategy']} needs a bid_amount (in rupees)")
    for k, a in auds.items():
        if not a.get("countries") and not a.get("geo_in_adset"):
            err(f"audience {k}: countries is required, e.g. [\"IN\"]")

    # ---- batches ----
    files = batch_files()
    if not files:
        err("no ads/batch_*.json found")
    seen: dict[str, str] = {}
    ad_reg = Registry(s, "ad_registry.json")
    hashes = Registry(s, "batch_hashes.json")
    for bf in files:
        name = bf.stem
        try:
            batch = jload(bf, {})
        except LauncherError as e:
            err(str(e))
            continue
        scope = only is None or name == only
        if not batch.get("batch_id"):
            err(f"{name}: batch_id is required")
        frozen = hashes.get(name, {}).get("sha256")
        if frozen and frozen != sha256(bf):
            err(f"{name}: this batch was already submitted and has since been edited. Restore it, or put changes in a new batch with new ad keys.")
        for ad in batch.get("ads", []):
            key = ad.get("ad_key", "")
            where = f"{name}/{key or '?'}"
            if key in seen:
                err(f"{where}: ad_key also used in {seen[key]} (keys are never reused)")
            seen[key] = name
            if not scope:
                continue
            if not AD_KEY_RE.match(key):
                err(f"{where}: ad_key must look like RS_ACNE_001 (or RS_ACNE_001_S2 for the copy in a second ad set)")
            if key in ad_reg and ad_reg.get(key, {}).get("batch") not in (None, name):
                err(f"{where}: key already used by batch {ad_reg.get(key)['batch']}")
            status = ad.get("status")
            if status not in STATUSES:
                err(f"{where}: status must be DRAFT or READY")
            ready = status == "READY"
            if ad.get("creative_spec"):
                cs = ad["creative_spec"]
                if not isinstance(cs, dict) or not (cs.get("object_story_spec") or cs.get("asset_feed_spec") or cs.get("object_story_id")):
                    err(f"{where}: creative_spec needs object_story_spec, asset_feed_spec or object_story_id")
                if not ad.get("adset_key"):
                    err(f"{where}: missing adset_key")
                elif ad["adset_key"] not in sets:
                    err(f"{where}: unknown adset_key '{ad['adset_key']}'")
                continue
            miss = [f for f in ("adset_key", "primary_text", "headline", "cta", "destination") if not ad.get(f)]
            if not ad.get("image") and not ad.get("image_hash"):
                miss.append("image (or image_hash)")
            if ad.get("image_hash") and not re.fullmatch(r"[0-9a-f]{32}", str(ad["image_hash"])):
                err(f"{where}: image_hash must be the 32-character hash Meta returned (run: python run.py images)")
            if ad.get("image_hash") and ad.get("image"):
                warn(f"{where}: both image and image_hash given; the hash is used and the file is ignored")
            if miss:
                err(f"{where}: missing {', '.join(miss)}")
            if ad.get("adset_key") and ad["adset_key"] not in sets:
                err(f"{where}: unknown adset_key '{ad['adset_key']}'")
            if ad.get("cta") and ad["cta"] not in CTAS:
                err(f"{where}: cta must be one of {sorted(CTAS)}")
            u = urlparse(ad.get("destination", ""))
            if ad.get("destination") and (u.scheme != "https" or not u.netloc):
                err(f"{where}: destination must be a full https:// URL")
            if "utm_" in ad.get("destination", ""):
                warn(f"{where}: destination already has UTM tags; the launcher adds its own via url_tags - remove them from the URL")
            if len(ad.get("headline", "")) > 40:
                warn(f"{where}: headline is {len(ad['headline'])} chars; over ~40 may be cut off")
            if len(ad.get("primary_text", "")) > 125:
                warn(f"{where}: primary text is {len(ad['primary_text'])} chars; Meta shows ~125 before 'See more'")
            if ad.get("image") and not ad.get("image_hash"):
                p = image_path(ad)
                prob = err if ready else warn  # a DRAFT may still be waiting for its image
                if not p.exists():
                    prob(f"{where}: image not found: {ad['image']}")
                else:
                    if p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
                        err(f"{where}: image must be JPG or PNG")
                    if p.stat().st_size > MAX_BYTES:
                        err(f"{where}: image is over 30 MB")
                    size = image_size(p)
                    if not size:
                        err(f"{where}: cannot read image dimensions (corrupt file?)")
                    else:
                        w, h = size
                        if w < 600:
                            err(f"{where}: image is {w}px wide; use at least 1080")
                        elif w < 1080:
                            warn(f"{where}: image is {w}px wide; 1080+ looks sharper")
                        if min(abs(w / h - r) / r for r in RATIOS.values()) > 0.03:
                            warn(f"{where}: aspect ratio {w}:{h} is not 1:1, 4:5, 9:16 or 1.91:1; Meta may crop it")
    return errors, warns


def report(s: Settings, only=None) -> bool:
    errors, warns = validate(s, only)
    for w in warns:
        print(f"  WARN  {w}")
    for e in errors:
        print(f"  ERROR {e}")
    print(f"validate: {len(errors)} error(s), {len(warns)} warning(s)")
    return not errors
