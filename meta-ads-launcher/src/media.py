"""Images and videos used inside a creative (carousel cards, video ads, Advantage+ assets). A creative can name a local file as a text value:
    "image_hash": "file:media/ab12cd34_card1.jpg"      -> replaced by the image hash Meta returns
    "video_id":   "file:media/ab12cd34_promo.mp4"      -> replaced by the video id Meta returns (after Meta has processed the video)
    "image_url":  "thumb:media/ab12cd34_promo.mp4"     -> replaced by that video's thumbnail
Upload happens once per file and is remembered in data/<env>/upload_registry.json, so nothing is ever uploaded twice."""
from __future__ import annotations

import copy
import time
from pathlib import Path

from .common import LauncherError, ROOT, Registry, Settings, sha256
from .meta_api import Meta

IMG_EXT = (".jpg", ".jpeg", ".png")
VID_EXT = (".mp4", ".mov")
MAX_VIDEO = 300 * 1024 * 1024
MAX_IMAGE = 30 * 1024 * 1024
WAIT_VIDEO = 900  # seconds Meta may take to process a video


def _walk(o, fn, parent=None, key=None):
    if isinstance(o, dict):
        for k, v in list(o.items()):
            if isinstance(v, str) and (v.startswith("file:") or v.startswith("thumb:")):
                fn(o, k, v)
            else:
                _walk(v, fn)
    elif isinstance(o, list):
        for x in o:
            _walk(x, fn)


def files_in(spec) -> list[str]:
    """Every local file a creative refers to (unique, in order)."""
    out: list[str] = []

    def add(d, k, v):
        p = v.split(":", 1)[1]
        if p not in out:
            out.append(p)
    _walk(spec, add)
    return out


def _local(rel: str) -> Path:
    p = (ROOT / rel).resolve()
    if not str(p).startswith(str((ROOT / "media").resolve())) or not p.is_file():
        raise LauncherError(f"media file not found: {rel} (upload it again)")
    return p


def kind_of(rel: str) -> str:
    ext = Path(rel).suffix.lower()
    return "image" if ext in IMG_EXT else "video" if ext in VID_EXT else ""


def upload_files(s: Settings, meta: Meta, spec) -> None:
    reg = Registry(s, "upload_registry.json")
    for rel in files_in(spec):
        p = _local(rel)
        digest = sha256(p)
        key = f"media:{digest[:24]}"
        got = reg.get(key, {})
        kind = kind_of(rel)
        if not kind:
            raise LauncherError(f"{rel}: only JPG, PNG, MP4 and MOV files can be used")
        if got.get("uploaded"):
            print(f"  {p.name}: already on Meta")
            continue
        if kind == "image":
            if p.stat().st_size > MAX_IMAGE:
                raise LauncherError(f"{p.name}: image is over 30 MB")
            res = meta.post(f"{s.account}/adimages", {}, files={p.name: (p.name, p.read_bytes())})
            h = next(iter(res["images"].values()))["hash"]
            if not meta.dry:
                reg.update(key, folder="media", filename=p.name, sha256=digest, meta_image_hash=h, uploaded=True, kind="image")
            print(f"  {p.name}: image uploaded ({h})")
            continue
        if p.stat().st_size > MAX_VIDEO:
            raise LauncherError(f"{p.name}: video is over 300 MB (larger videos need Meta's chunked upload, which the launcher does not do yet)")
        res = meta.post(f"{s.account}/advideos", {"title": p.stem[9:] or p.stem}, files={"source": (p.name, p.read_bytes())})
        vid = str(res.get("id") or "")
        if meta.dry:
            print(f"  {p.name}: [dry-run] video would be uploaded")
            continue
        if not vid:
            raise LauncherError(f"{p.name}: Meta did not return a video id")
        print(f"  {p.name}: video uploaded ({vid}); waiting for Meta to process it ...")
        thumb = _wait_ready(meta, vid, p.name)
        reg.update(key, folder="media", filename=p.name, video_id=vid, thumb=thumb, uploaded=True, kind="video", sha="video")


def _wait_ready(meta: Meta, vid: str, name: str) -> str:
    t0 = time.time()
    while time.time() - t0 < WAIT_VIDEO:
        st = (meta.get(vid, fields="status").get("status") or {})
        v = st.get("video_status")
        if v == "ready":
            break
        if v == "error":
            raise LauncherError(f"{name}: Meta could not process this video ({st.get('processing_progress', '')}). Try re-exporting it as MP4 (H.264).")
        time.sleep(5)
    else:
        raise LauncherError(f"{name}: Meta is still processing the video after {WAIT_VIDEO // 60} minutes. Run the step again later; it will not upload twice.")
    rows = meta.get(f"{vid}/thumbnails").get("data", [])
    pref = next((r for r in rows if r.get("is_preferred")), rows[0] if rows else {})
    return pref.get("uri", "")


def resolve(spec: dict, s: Settings, lenient: bool = False, stand_in: dict | None = None) -> dict:
    """Replace file references with Meta's hashes / ids. lenient: use placeholders for files not uploaded yet (dry-run and check-only).
    stand_in: {"image_hash": ..., "video_id": ..., "thumb": ...} used instead of real uploads (check-only)."""
    reg = Registry(s, "upload_registry.json")
    out = copy.deepcopy(spec)

    def sub(d, k, v):
        rel = v.split(":", 1)[1]
        mode = v.split(":", 1)[0]
        if stand_in is not None:
            if kind_of(rel) == "image":
                d[k] = stand_in.get("image_hash", "")
            elif mode == "thumb":
                d[k] = stand_in.get("thumb", "")
            else:
                d[k] = stand_in.get("video_id", "")
            return
        got = reg.get(f"media:{sha256(_local(rel))[:24]}", {})
        if not got.get("uploaded"):
            if not lenient:
                raise LauncherError(f"{rel}: not uploaded yet - run the upload step first")
            d[k] = "DRYHASH" if kind_of(rel) == "image" else "DRYVIDEO" if mode == "file" else "https://example.invalid/thumb.jpg"
            return
        d[k] = got.get("meta_image_hash") if kind_of(rel) == "image" else (got.get("thumb") if mode == "thumb" else got.get("video_id"))
    _walk(out, sub)
    return out
