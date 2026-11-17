"""One entry point for every command, used by both the CLI (run.py) and the web UI, so they can never disagree."""
from __future__ import annotations

from . import create_adsets, create_ads, create_campaigns, create_creatives, doctor, publish, upload_images, validate
from .common import LauncherError, Settings, adsets_cfg, guard_write, log, need_ready, ready_ads
from .meta_api import Meta

COMMANDS = ["doctor", "validate", "images", "upload", "setup", "prepare", "publish", "status"]


def execute(command: str, batch: str | None = None, dry_run=False, validate_only=False, confirm_production=False,
            yes=False, confirmed=False, live=False) -> bool:
    """Prints progress; raises LauncherError on a refused/failed step; returns False when a check reported problems.
    `confirmed` means a human typed PUBLISH (the UI sets it only after checking that text)."""
    s = Settings()
    if command == "doctor":
        return doctor.doctor(s)
    if command == "validate":
        return validate.report(s, batch)
    if command == "status":
        doctor.status(s, live)
        return True
    if command == "images":
        need_ready(s)
        doctor.images(s)
        return True
    if command not in COMMANDS:
        raise LauncherError(f"unknown command '{command}'")
    if not batch:
        raise LauncherError(f"--batch is required for '{command}'  (example: python run.py {command} --batch batch_001)")
    print(f"[{s.env.upper()}] {command} {batch}" + ("  (dry run)" if dry_run else "  (check with Meta, nothing created)" if validate_only else ""))
    if not validate.report(s, batch):
        raise LauncherError("validation failed - nothing was sent")
    _, ads = ready_ads(batch)
    if not ads:
        raise LauncherError("no ads with status READY in this batch (DRAFT ads are validated but never sent)")
    if not dry_run:
        need_ready(s)
        guard_write(s, confirm_production)
    meta = Meta(s, dry_run=dry_run)
    log(f"{s.env} {command} {batch} dry={dry_run} validate_only={validate_only}", s)
    if command == "upload":
        upload_images.run(s, meta, batch)
    elif command == "setup":
        keys = sorted({x["adset_key"] for x in ads})
        create_campaigns.run(s, meta, sorted({adsets_cfg()[k]["campaign_key"] for k in keys}), validate_only)
        create_adsets.run(s, meta, keys, validate_only)
    elif command == "prepare":
        create_creatives.run(s, meta, batch, validate_only)
        create_ads.run(s, meta, batch, validate_only)
    elif command == "publish":
        publish.run(s, meta, batch, yes, confirmed)
    print("done.")
    return True
