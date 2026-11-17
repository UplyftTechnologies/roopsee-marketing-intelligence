"""Background jobs: one at a time, output captured line by line, plain-English hints when something fails."""
from __future__ import annotations

import io
import threading
import uuid
from contextlib import redirect_stderr, redirect_stdout

from fastapi import HTTPException

from src.common import LauncherError, Settings

JOBS: dict[str, dict] = {}
RUN_LOCK = threading.Lock()


class _Out(io.TextIOBase):
    def __init__(self, job): self.job = job
    def write(self, s):
        self.job["log"] += s
        return len(s)


HINTS = [
    (("1341012", "No permission to access this profile"),
     "Meta says this login cannot post as your Facebook Page. In Business Settings > Pages, make sure the user behind the token has full access to the Page, then try again."),
    (("Invalid OAuth access token", "code 190"),
     "The access token is invalid or has expired. Create a new token and put it in .env."),
    (("Requires business_management", "(#200)"),
     "The token is missing a permission or has no access to this object. Check the token's permissions in the app dashboard."),
    (("writes are blocked",),
     "You are on production. Tick the production confirmation box to allow changes."),
    (("PIXEL_ID",),
     "Sales campaigns need your pixel (dataset) ID in .env. Run: python run.py discover  to find it."),
    (("does not exist in ad account",),
     "That image hash is not in this ad account. Open Creatives > 'Already on Meta' to see the hashes you can use."),
    (("validation failed",),
     "Something in the setup needs fixing before anything is sent. The messages above say what."),
    (("another command is still running",),
     "Wait for the current step to finish."),
    (("Tried accessing nonexisting field", "code 100"),
     "Meta rejected one of the values. Read the technical details below for the field name."),
    (("minimum budget", "budget is too low", "1885"),
     "Meta says the daily budget is too low for this goal. Try a higher budget."),
]


def explain(log: str) -> list[str]:
    return [h for keys, h in HINTS if any(k in log for k in keys)]


def start_job(label: str, steps: list, finish=None) -> dict:
    """steps: list of (title, callable). They run in order and stop at the first failure."""
    if not RUN_LOCK.acquire(blocking=False):
        raise HTTPException(409, "another command is still running; wait for it to finish")
    job = {"id": uuid.uuid4().hex[:10], "label": label, "status": "running", "ok": None, "log": "", "hints": [], "result": None,
           "steps": [{"title": t, "status": "waiting"} for t, _ in steps]}
    JOBS[job["id"]] = job
    for old in list(JOBS)[:-30]:
        JOBS.pop(old, None)

    def work():
        s = None
        try:
            s = Settings()
            out = _Out(job)
            ok = True
            with redirect_stdout(out), redirect_stderr(out):
                for i, (title, fn) in enumerate(steps):
                    job["steps"][i]["status"] = "running"
                    try:
                        if fn() is False:
                            raise LauncherError("this step reported problems (see above)")
                        job["steps"][i]["status"] = "done"
                    except LauncherError as e:
                        print(f"\nERROR: {e}")
                        job["steps"][i]["status"] = "failed"
                        ok = False
                        break
                    except Exception as e:  # noqa: BLE001
                        print(f"\nUNEXPECTED ERROR: {s.redact(e)}")
                        job["steps"][i]["status"] = "failed"
                        ok = False
                        break
            job["ok"] = ok
            if finish:
                try:
                    job["result"] = finish(ok)
                except Exception as e:  # noqa: BLE001
                    job["log"] += f"\n(could not read the result: {s.redact(e)})\n"
        except Exception as e:  # noqa: BLE001
            job["log"] += f"\nUNEXPECTED ERROR: {s.redact(e) if s else e}\n"
            job["ok"] = False
        finally:
            job["hints"] = explain(job["log"]) if not job["ok"] else []
            job["status"] = "done"
            RUN_LOCK.release()

    threading.Thread(target=work, daemon=True).start()
    return job
