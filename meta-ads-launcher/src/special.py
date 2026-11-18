"""The 'extra mechanisms' that Meta's own JSON can carry (WhatsApp audiences, chat buttons, enhancements, text variations, exclusions ...).
Used when something is imported or copied, to tell the person plainly what came along, what was left out and why, and what to check.
A finding is {"where", "what", "status": kept | dropped | review, "why"}."""
from __future__ import annotations

from typing import Any

NEEDS_MESSAGING = "needs messaging permission that the app does not have, so Meta rejects it with '(#3) Application does not have the capability'"


def _f(where: str, what: str, status: str, why: str) -> dict:
    return {"where": where, "what": what, "status": status, "why": why}


# ---- ad sets ------------------------------------------------------------------------------------------------------------------------
TARGETING_KEPT = {
    "flexible_spec": ("Interests, behaviours and demographics", "sent to Meta exactly as written"),
    "exclusions": ("Exclusions (people who are left out)", "sent to Meta exactly as written"),
    "targeting_automation": ("Advantage audience setting", "sent to Meta exactly as written"),
    "targeting_relaxation_types": ("Audience expansion (lookalike / custom audience)", "sent to Meta exactly as written"),
    "locales": ("Languages", "sent to Meta exactly as written"),
    "excluded_geo_locations": ("Places that are excluded", "sent to Meta exactly as written"),
    "user_device": ("Device targeting", "sent to Meta exactly as written"),
    "user_os": ("Operating system targeting", "sent to Meta exactly as written"),
    "wireless_carrier": ("Mobile carrier targeting", "sent to Meta exactly as written"),
    "life_events": ("Life events", "sent to Meta exactly as written"),
    "education_statuses": ("Education targeting", "sent to Meta exactly as written"),
}
TARGETING_REVIEW = {
    "custom_audiences": ("Custom audiences you include", "they must exist in the ad account you create in; copies from the same account are fine"),
    "excluded_custom_audiences": ("Custom audiences you exclude", "they must exist in the ad account you create in; copies from the same account are fine"),
}
EXTRA_KEPT = {
    "attribution_spec": ("Attribution window", "how long after a click or view a result is counted"),
    "bid_constraints": ("Bid constraints (for example minimum return)", "sent to Meta exactly as written"),
    "is_dynamic_creative": ("Dynamic creative", "Meta mixes your images and texts"),
    "daily_min_spend_target": ("Minimum daily spend", "sent to Meta exactly as written"),
    "daily_spend_cap": ("Daily spend cap", "sent to Meta exactly as written"),
    "pacing_type": ("Pacing", "sent to Meta exactly as written"),
    "dsa_beneficiary": ("EU 'who benefits' name", "sent to Meta exactly as written"),
    "dsa_payor": ("EU 'who pays' name", "sent to Meta exactly as written"),
}


def adset_findings(targeting_extra: dict, extra: dict, where: str) -> tuple[dict, dict, list]:
    """Returns (targeting_extra without what must go, extra, findings)."""
    te = dict(targeting_extra or {})
    ex = dict(extra or {})
    out: list = []
    if "subscriber_universe" in te:
        te.pop("subscriber_universe")
        out.append(_f(where, "WhatsApp customer audience", "dropped", NEEDS_MESSAGING))
    for k, (what, why) in TARGETING_KEPT.items():
        if te.get(k):
            out.append(_f(where, what, "kept", why))
    for k, (what, why) in TARGETING_REVIEW.items():
        if te.get(k):
            n = len(te[k]) if isinstance(te[k], list) else 1
            out.append(_f(where, f"{what} ({n})", "review", why))
    for k, (what, why) in EXTRA_KEPT.items():
        if ex.get(k):
            out.append(_f(where, what, "kept", why))
    known = set(EXTRA_KEPT) | {"promoted_object"}
    other = sorted(k for k in ex if k not in known)
    if other:
        out.append(_f(where, "Other ad set settings: " + ", ".join(other), "kept", "no field for these in the builder; sent to Meta as written (Meta checks them)"))
    return te, ex, out


# ---- creatives ----------------------------------------------------------------------------------------------------------------------
def creative_findings(spec: Any, where: str) -> list:
    out: list = []
    if not isinstance(spec, dict):
        return out
    afs = spec.get("asset_feed_spec") if isinstance(spec.get("asset_feed_spec"), dict) else {}
    oss = spec.get("object_story_spec") if isinstance(spec.get("object_story_spec"), dict) else {}
    if afs.get("message_extensions"):
        out.append(_f(where, "Chat button (message extensions: Messenger / WhatsApp)", "dropped", NEEDS_MESSAGING))
    dof = spec.get("degrees_of_freedom_spec") if isinstance(spec.get("degrees_of_freedom_spec"), dict) else {}
    feats = dof.get("creative_features_spec") if isinstance(dof.get("creative_features_spec"), dict) else {}
    if "standard_enhancements" in feats:
        out.append(_f(where, "Old 'standard enhancements' switch", "dropped", "Meta removed it; only the individual enhancements are accepted now"))
    live = [k for k in feats if k != "standard_enhancements"]
    if live:
        out.append(_f(where, f"Meta's automatic enhancements ({len(live)})", "kept", "for example adapt to placement, text overlay; sent as written"))
    nb, nt = len(afs.get("bodies") or []), len(afs.get("titles") or [])
    if nb > 1 or nt > 1:
        out.append(_f(where, f"Text variations ({nb} texts, {nt} headlines)", "kept", "Meta tests them against each other"))
    if afs.get("ad_formats"):
        out.append(_f(where, "Format options: " + ", ".join(map(str, afs["ad_formats"])), "kept", "sent as written"))
    if spec.get("product_set_id") or afs.get("product_set_id"):
        out.append(_f(where, "Catalog product set", "review", "the app must be allowed to use that catalog; ads using a catalog it cannot reach fail the check"))
    if spec.get("object_story_id") and not oss:
        out.append(_f(where, "Existing post used as the ad", "kept", "its text and image cannot be changed here"))
    for k in ("platform_customizations", "contextual_multi_ads", "creative_sourcing_spec", "interactive_components_spec", "branded_content", "template_url_spec"):
        if spec.get(k):
            out.append(_f(where, f"Advanced creative setting: {k}", "kept", "no field for this in the builder; sent as written (Meta checks it)"))
    return out
