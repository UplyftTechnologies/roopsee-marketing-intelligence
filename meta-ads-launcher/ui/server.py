"""Local web UI backend. Listens on 127.0.0.1 only; the token never leaves this process."""
from __future__ import annotations

import os
import re
import threading
import webbrowser
from pathlib import Path

from fastapi import FastAPI, File, Form, HTTPException, Request, UploadFile
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from src import validate as validate_mod
from src.common import CTAS, GOALS, KEY_RE, OBJECTIVES, PLACEMENTS, ROOT, LauncherError, Registry, Settings, batch_files, jload, jsave, sha256
from src.pipeline import COMMANDS, execute
from ui.jobs import JOBS, RUN_LOCK, start_job
from ui.importer import router as importer_router
from ui.library import router as library_router
from ui.targeting import router as targeting_router
from ui.formats import router as formats_router
from ui.libsync import router as libsync_router
from ui.manage import router as manage_router
from ui.wizard import router as wizard_router

DIST = Path(__file__).parent / "dist"
PORT = int(os.environ.get("META_UI_PORT", "8765"))
CONFIG_FILES = ("campaigns", "adsets", "audiences", "account", "destinations")
BATCH_RE = re.compile(r"^batch_[A-Za-z0-9_]{1,30}$")
CATEGORY_RE = re.compile(r"^[a-z0-9_]{2,30}$")

app = FastAPI(title="Roopsee Meta Ads Launcher", docs_url=None, redoc_url=None, openapi_url=None)
app.include_router(wizard_router)
app.include_router(importer_router)
app.include_router(library_router)
app.include_router(targeting_router)
app.include_router(formats_router)
app.include_router(libsync_router)
app.include_router(manage_router)


# ---- protection: local only, and no cross-site writes ---------------------------------------------------------------------
@app.middleware("http")
async def guard(request: Request, call_next):
    host = (request.headers.get("host") or "").split(":")[0]
    if host not in ("127.0.0.1", "localhost"):  # blocks DNS-rebinding
        return JSONResponse({"detail": "forbidden host"}, status_code=403)
    if request.method not in ("GET", "HEAD") and request.headers.get("x-launcher") != "1":  # another site's page cannot set this header
        return JSONResponse({"detail": "missing X-Launcher header"}, status_code=403)
    return await call_next(request)


# ---- running commands -----------------------------------------------------------------------------------------------------
@app.post("/api/run")
async def run(req: Request):
    b = await req.json()
    cmd, batch, mode = b.get("command"), b.get("batch"), b.get("mode", "dry")
    if cmd not in COMMANDS:
        raise HTTPException(400, "unknown command")
    if batch and not BATCH_RE.match(batch):
        raise HTTPException(400, "bad batch name")
    if mode not in ("dry", "check", "real"):
        raise HTTPException(400, "mode must be dry, check or real")
    confirmed = False
    if cmd == "publish" and mode == "check":
        raise HTTPException(400, "publish has no 'check' mode; use dry run or real")
    if cmd == "publish" and mode == "real":
        if b.get("confirm_text") != "PUBLISH":
            raise HTTPException(400, "type PUBLISH exactly to confirm")
        confirmed = True
    cp, live = bool(b.get("confirm_production")), bool(b.get("live"))
    job = start_job(f"{cmd} {batch or ''} [{mode}]".strip(), [(f"{cmd}", lambda: execute(
        cmd, batch, dry_run=(mode == "dry"), validate_only=(mode == "check"), confirm_production=cp, confirmed=confirmed, live=live))])
    return {"job": job["id"]}


@app.get("/api/jobs/{jid}")
def job(jid: str):
    j = JOBS.get(jid)
    if not j:
        raise HTTPException(404, "unknown job")
    return j


# ---- state ----------------------------------------------------------------------------------------------------------------
def _frozen() -> dict:
    return Registry(Settings(), "batch_hashes.json").d


@app.get("/api/state")
def state():
    s = Settings()
    ent, ads, up = Registry(s, "entity_registry.json").d, Registry(s, "ad_registry.json").d, Registry(s, "upload_registry.json").d
    frozen = _frozen()
    batches = []
    for f in batch_files():
        try:
            data = jload(f, {})
        except LauncherError:
            data = {}
        a = data.get("ads", [])
        batches.append({"name": f.stem, "batch_id": data.get("batch_id"), "ads": len(a), "ready": sum(x.get("status") == "READY" for x in a), "frozen": f.stem in frozen})
    return {"env": s.env, "account": s.account, "page_id": s.page_id, "missing": s.missing(), "version": s.version, "entities": ent, "ads": ads,
            "uploads": up, "batches": batches, "ready": {e: not Settings(e).missing() for e in ("sandbox", "production")}, "enums": {"objectives": sorted(OBJECTIVES), "ctas": sorted(CTAS), "goals": sorted(GOALS), "placements": sorted(PLACEMENTS)}}


@app.get("/api/next-key")
def next_key(theme: str):
    """The next unused ad ID for a theme, e.g. skincare -> RS_SKINCARE_001 (IDs are never reused)."""
    from ui.wizard import next_ad_key
    try:
        return {"key": next_ad_key(theme)}
    except ValueError:
        raise HTTPException(400, "type a theme first (for example skincare)")


@app.post("/api/env")
async def switch_env(req: Request):
    """Switch between sandbox and production for THIS UI session only (restarting returns to the value in .env).
    Neither can be chosen if its credentials are incomplete or a step is running."""
    b = await req.json()
    target = b.get("env")
    if target not in ("sandbox", "production"):
        raise HTTPException(400, "env must be sandbox or production")
    if RUN_LOCK.locked():
        raise HTTPException(409, "a step is still running; wait for it to finish before switching")
    miss = Settings(target).missing()
    if miss:
        raise HTTPException(400, f"{target} is not fully set up in .env. Missing: {', '.join(miss)}")
    os.environ["META_ENV"] = target
    return {"env": target}


@app.get("/api/config")
def get_config():
    return {k: jload(ROOT / "config" / f"{k}.json", {}) for k in CONFIG_FILES}


@app.put("/api/config/{name}")
async def put_config(name: str, req: Request):
    if name not in CONFIG_FILES:
        raise HTTPException(404, "unknown config")
    body = await req.json()
    top = {"campaigns": "campaigns", "adsets": "adsets", "audiences": "audiences", "destinations": "destinations"}.get(name)
    if top and (not isinstance(body, dict) or top not in body):
        raise HTTPException(400, f"expected an object with '{top}'")
    jsave(ROOT / "config" / f"{name}.json", body)
    errors, warns = validate_mod.validate(Settings())
    return {"saved": True, "errors": errors, "warnings": warns}


# ---- batches --------------------------------------------------------------------------------------------------------------
@app.get("/api/batches/{name}")
def get_batch(name: str):
    if not BATCH_RE.match(name):
        raise HTTPException(400, "bad batch name")
    p = ROOT / "ads" / f"{name}.json"
    return {"batch": jload(p, {"batch_id": f"ROOPSEE_{name.upper()}", "ads": []}), "frozen": name in _frozen(), "exists": p.exists()}


@app.put("/api/batches/{name}")
async def put_batch(name: str, req: Request):
    if not BATCH_RE.match(name):
        raise HTTPException(400, "bad batch name (use batch_001 style)")
    if name in _frozen():
        raise HTTPException(409, "this batch was already submitted and is frozen; create a new batch instead")
    body = await req.json()
    if not isinstance(body, dict) or not isinstance(body.get("ads"), list):
        raise HTTPException(400, "expected {batch_id, ads: []}")
    jsave(ROOT / "ads" / f"{name}.json", body)
    errors, warns = validate_mod.validate(Settings(), name)
    return {"saved": True, "errors": errors, "warnings": warns}


@app.get("/api/validate")
def validate_ep(batch: str | None = None):
    errors, warns = validate_mod.validate(Settings(), batch)
    return {"errors": errors, "warnings": warns}


# ---- creative library -----------------------------------------------------------------------------------------------------
@app.get("/api/creatives")
def creatives():
    up = Registry(Settings(), "upload_registry.json").d
    used = {a.get("image") for f in batch_files() for a in (jload(f, {}).get("ads", []))}
    out = []
    for p in sorted((ROOT / "creatives").rglob("*")):
        if p.suffix.lower() in (".jpg", ".jpeg", ".png"):
            size = validate_mod.image_size(p)
            rel = p.relative_to(ROOT).as_posix()
            out.append({"key": p.stem, "category": p.parent.name, "path": rel, "bytes": p.stat().st_size,
                        "width": size[0] if size else None, "height": size[1] if size else None,
                        "hash": up.get(p.stem, {}).get("meta_image_hash"), "used": rel in used})
    return out


@app.get("/creatives/{path:path}")
def creative_file(path: str):
    p = (ROOT / "creatives" / path).resolve()
    if not str(p).startswith(str((ROOT / "creatives").resolve())) or not p.is_file() or p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        raise HTTPException(404)
    return FileResponse(p)


@app.post("/api/creatives")
async def upload_creative(file: UploadFile = File(...), category: str = Form(...), ad_key: str = Form(None)):
    ext = Path(file.filename or "").suffix.lower()
    if ext not in (".jpg", ".jpeg", ".png"):
        raise HTTPException(400, "image must be JPG or PNG")
    if not CATEGORY_RE.match(category):
        raise HTTPException(400, "theme: lowercase letters, digits, underscore (for example acne)")
    existing = [p.stem for p in (ROOT / "creatives").rglob("*") if p.is_file()]
    if not ad_key:  # next free number for this theme
        tag = category.upper()
        nums = [int(x.rsplit("_", 1)[1]) for x in existing if x.startswith(f"RS_{tag}_") and x.rsplit("_", 1)[1].isdigit()]
        ad_key = f"RS_{tag}_{max(nums, default=0) + 1:03d}"
    if not KEY_RE.match(ad_key):
        raise HTTPException(400, "ad ID must look like RS_ACNE_001")
    if ad_key in existing:
        raise HTTPException(409, f"{ad_key} already exists; IDs are never reused")
    data = await file.read()
    if len(data) > 30 * 1024 * 1024:
        raise HTTPException(400, "image is over 30 MB")
    dest = ROOT / "creatives" / category / f"{ad_key}{'.jpg' if ext == '.jpeg' else ext}"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(data)
    size = validate_mod.image_size(dest)
    if not size:
        dest.unlink()
        raise HTTPException(400, "cannot read this image (corrupt file?)")
    return {"saved": dest.relative_to(ROOT).as_posix(), "key": ad_key, "width": size[0], "height": size[1], "sha256": sha256(dest)}


# ---- the app itself (built by `python run.py ui`) -------------------------------------------------------------------------
if (DIST / "index.html").exists():
    app.mount("/", StaticFiles(directory=DIST, html=True), name="app")
else:
    @app.get("/", response_class=HTMLResponse)
    def not_built():
        return "<h3>The UI has not been built yet.</h3><p>Run <code>python run.py ui</code> (needs Node.js once) or <code>npm install &amp;&amp; npm run build</code> in <code>ui-app</code>.</p>"


def serve(open_browser: bool = True) -> None:
    import uvicorn
    url = f"http://127.0.0.1:{PORT}"
    s = Settings()
    print(f"Roopsee Meta Ads Launcher UI  ->  {url}   [{s.env.upper()}]   (Ctrl+C to stop)")
    if open_browser:
        threading.Timer(1.0, lambda: webbrowser.open(url)).start()
    uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="warning")
