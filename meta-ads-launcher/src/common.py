"""Shared helpers: paths, settings (.env), JSON registries, logging, config/batch loading."""
from __future__ import annotations

import hashlib
import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
KEY_RE = re.compile(r"^RS_[A-Z0-9]+_\d{3}$")  # an image / base ad ID, e.g. RS_ACNE_001
AD_KEY_RE = re.compile(r"^RS_[A-Z0-9]+_\d{3}(_S\d{1,2})?$")  # an ad ID; _S2, _S3 ... mark the copy of the same ad in another ad set


def base_key(k: str) -> str:
    """RS_ACNE_001_S2 -> RS_ACNE_001 (the image file name)."""
    return re.sub(r"_S\d{1,2}$", "", k or "")

OBJECTIVES = {"OUTCOME_TRAFFIC", "OUTCOME_SALES", "OUTCOME_LEADS", "OUTCOME_AWARENESS", "OUTCOME_ENGAGEMENT", "OUTCOME_APP_PROMOTION"}
CTAS = {"LEARN_MORE", "SHOP_NOW", "SIGN_UP", "GET_OFFER", "ORDER_NOW", "CONTACT_US", "SUBSCRIBE"}
GOALS = {"LINK_CLICKS", "LANDING_PAGE_VIEWS", "OFFSITE_CONVERSIONS", "REACH", "IMPRESSIONS", "VALUE", "POST_ENGAGEMENT", "PAGE_LIKES", "VIDEO_VIEWS", "THRUPLAY",
         "AD_RECALL_LIFT", "LEAD_GENERATION", "QUALITY_LEAD", "CONVERSATIONS", "APP_INSTALLS", "PROFILE_VISIT", "QUALITY_CALL", "REPLIES",
         "TWO_SECOND_CONTINUOUS_VIDEO_VIEWS", "ENGAGED_USERS", "VISIT_INSTAGRAM_PROFILE", "MESSAGING_PURCHASE_CONVERSION", "ONSITE_CONVERSIONS"}  # Meta rejects invalid combinations; the check-only run tells you
BID_STRATEGIES = {"LOWEST_COST_WITHOUT_CAP", "LOWEST_COST_WITH_BID_CAP", "COST_CAP", "LOWEST_COST_WITH_MIN_ROAS"}
BILLING_EVENTS = {"IMPRESSIONS", "LINK_CLICKS", "THRUPLAY", "POST_ENGAGEMENT", "PAGE_LIKES"}
DESTINATIONS = {"WEBSITE", "APP", "MESSENGER", "WHATSAPP", "INSTAGRAM_PROFILE", "PHONE_CALL", "ON_AD", "ON_POST", "ON_VIDEO", "FACEBOOK", "SHOP_AUTOMATIC"}
# things a file can never set: ids, state, credentials. Status is always PAUSED here, by design.
FORBIDDEN_EXTRA = {"id", "account_id", "campaign_id", "adset_id", "ad_id", "status", "effective_status", "configured_status", "created_time", "updated_time",
                   "access_token", "appsecret_proof", "execution_options", "name", "issues_info", "recommendations", "bid_info", "learning_stage_info"}


def clean_extra(d) -> tuple[dict, list[str]]:
    """Make a pass-through dict safe: keep only allowed top-level keys. Returns (clean, dropped key names)."""
    if not isinstance(d, dict):
        return {}, []
    clean = {k: v for k, v in d.items() if k not in FORBIDDEN_EXTRA}
    return clean, sorted(k for k in d if k in FORBIDDEN_EXTRA)


def deep_merge(base: dict, over: dict) -> dict:
    """Return base with `over` laid on top (dicts merge, everything else is replaced)."""
    out = dict(base)
    for k, v in (over or {}).items():
        out[k] = deep_merge(out[k], v) if isinstance(v, dict) and isinstance(out.get(k), dict) else v
    return out
PLACEMENTS = {"instagram", "facebook", "automatic"}
STATUSES = {"DRAFT", "READY"}  # DRAFT = validated only; READY = will be uploaded / prepared


class LauncherError(Exception):
    pass


def load_env() -> dict:
    env: dict = {}
    f = ROOT / ".env"
    if f.exists():
        for line in f.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    for k, v in os.environ.items():  # real environment variables win over the file
        if k.startswith("META_"):
            env[k] = v
    return env


class Settings:
    """Credentials for ONE environment (sandbox or production). The two never mix."""

    def __init__(self, env_name: str | None = None):
        e = load_env()
        self.e = e
        self.env = (env_name or e.get("META_ENV") or "sandbox").lower()
        if self.env not in ("sandbox", "production"):
            raise LauncherError("META_ENV must be 'sandbox' or 'production'")
        self.version = e.get("META_API_VERSION", "v25.0")
        self.data = ROOT / "data" / self.env
        self.data.mkdir(parents=True, exist_ok=True)

    SHARED = ("ACCESS_TOKEN", "APP_ID", "APP_SECRET", "PAGE_ID", "INSTAGRAM_ID")  # may be one value for both environments

    def get(self, name: str) -> str:
        v = self.e.get(f"META_{self.env.upper()}_{name}", "").strip()
        if not v and name in self.SHARED:  # one token / app / Page for both: set META_<NAME> once
            v = self.e.get(f"META_{name}", "").strip()
        return v  # the ad account id and pixel are never shared, so sandbox can never act on the real account by fallback

    @property
    def token(self): return self.get("ACCESS_TOKEN")
    @property
    def app_id(self): return self.get("APP_ID")
    @property
    def app_secret(self): return self.get("APP_SECRET")
    @property
    def page_id(self): return self.get("PAGE_ID")
    @property
    def instagram_id(self): return self.get("INSTAGRAM_ID")
    @property
    def pixel_id(self): return self.get("PIXEL_ID")

    @property
    def account(self) -> str:
        a = self.get("AD_ACCOUNT_ID")
        return a if (not a or a.startswith("act_")) else f"act_{a}"

    def missing(self, need=("ACCESS_TOKEN", "APP_SECRET", "AD_ACCOUNT_ID", "PAGE_ID")) -> list[str]:
        return [f"META_{self.env.upper()}_{n}" for n in need if not self.get(n)]

    def secrets(self) -> list[str]:
        return [x for x in (self.token, self.app_secret) if x]

    def redact(self, text) -> str:
        text = str(text)
        for s in self.secrets():
            text = text.replace(s, "***")
        return text


def log(msg: str, settings: Settings | None = None) -> None:
    (ROOT / "logs").mkdir(exist_ok=True)
    if settings:
        msg = settings.redact(msg)
    with open(ROOT / "logs" / "launcher.log", "a", encoding="utf-8") as f:
        f.write(f"{datetime.now().isoformat(timespec='seconds')}  {msg}\n")


def jload(path: Path, default=None):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as e:
        raise LauncherError(f"{path.relative_to(ROOT)} is not valid JSON: {e}")


def jsave(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(obj, indent=2, ensure_ascii=False), encoding="utf-8")
    tmp.replace(path)  # atomic: a crash never leaves a half-written registry


class Registry:
    """A JSON file in data/<env>/ that is saved after every change, so a crash loses nothing."""

    def __init__(self, s: Settings, name: str):
        self.path = s.data / name
        self.d: dict = jload(self.path, {}) or {}

    def get(self, k, default=None): return self.d.get(k, default)
    def __contains__(self, k): return k in self.d

    def update(self, k, **fields):
        self.d.setdefault(k, {}).update(fields)
        jsave(self.path, self.d)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


# ---- config + batches -------------------------------------------------------
def account_cfg() -> dict: return jload(ROOT / "config" / "account.json", {}) or {}
def campaigns_cfg() -> dict: return {c["key"]: c for c in (jload(ROOT / "config" / "campaigns.json", {}) or {}).get("campaigns", []) if "key" in c}
def adsets_cfg() -> dict: return {a["key"]: a for a in (jload(ROOT / "config" / "adsets.json", {}) or {}).get("adsets", []) if "key" in a}
def audiences_cfg() -> dict: return (jload(ROOT / "config" / "audiences.json", {}) or {}).get("audiences", {})


def batch_files() -> list[Path]:
    return sorted((ROOT / "ads").glob("batch_*.json"))


def batch_path(name: str) -> Path:
    p = ROOT / "ads" / (name if name.endswith(".json") else f"{name}.json")
    if not p.exists():
        raise LauncherError(f"batch not found: {p.relative_to(ROOT)}  (available: {', '.join(b.stem for b in batch_files()) or 'none'})")
    return p


def ready_ads(name: str) -> tuple[dict, list[dict]]:
    batch = jload(batch_path(name), {})
    return batch, [a for a in batch.get("ads", []) if a.get("status") == "READY"]


def minor(amount: float, acc: dict) -> int:
    """500 (INR) -> 50000 minor units. Meta budgets are integers in the currency's smallest unit."""
    return int(round(float(amount) * int(acc.get("currency_offset", 100))))


def url_tags(ad: dict, batch_id: str, acc: dict) -> str:
    tpl = acc.get("url_tags", "utm_source=facebook&utm_medium=paid_social&utm_campaign={{campaign.id}}"
                              "&utm_content={{ad.id}}&utm_term={{adset.id}}&rs_creative={ad_key}&rs_batch={batch_id}")
    return tpl.replace("{ad_key}", ad["ad_key"]).replace("{batch_id}", batch_id)


def image_path(ad: dict) -> Path:
    return ROOT / ad.get("image", "")


def need_ready(s: Settings, extra=()) -> None:
    miss = s.missing(("ACCESS_TOKEN", "APP_SECRET", "AD_ACCOUNT_ID", "PAGE_ID") + tuple(extra))
    if miss:
        raise LauncherError("missing in .env: " + ", ".join(miss) + "\n  (copy .env.example to .env and fill it in)")


def guard_write(s: Settings, confirm_production: bool) -> None:
    """Production is never touched by accident."""
    if s.env == "production" and not confirm_production:
        raise LauncherError("META_ENV=production: writes are blocked. Re-run with --confirm-production once you really mean it "
                            "(or use --dry-run to preview).")


def ask(prompt: str, expected: str) -> bool:
    if not sys.stdin.isatty():
        return False
    return input(f"{prompt} Type {expected} to continue: ").strip() == expected
