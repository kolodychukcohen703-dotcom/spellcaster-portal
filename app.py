import eventlet
eventlet.monkey_patch()

import time
from flask import jsonify

from spellcaster_portal_patched_v2 import app as app  # noqa

REINDEX_STATE = {
    "running": False,
    "message": "Ready.",
    "started_at": None,
    "finished_at": None,
    "last_error": None,
}

@app.get("/reindex_status")
def reindex_status():
    return jsonify({"ok": True, **REINDEX_STATE})

@app.get("/api/reindex_status")
def reindex_status_alias():
    return jsonify({"ok": True, **REINDEX_STATE})

_orig = app.view_functions.get("api_reindex")
if _orig:
    def api_reindex_wrapper(*args, **kwargs):
        REINDEX_STATE["running"] = True
        REINDEX_STATE["started_at"] = time.time()
        REINDEX_STATE["finished_at"] = None
        REINDEX_STATE["last_error"] = None
        REINDEX_STATE["message"] = "Reindex started..."
        try:
            resp = _orig(*args, **kwargs)
            REINDEX_STATE["message"] = "Reindex finished."
            return resp
        except Exception as e:
            REINDEX_STATE["last_error"] = str(e)
            REINDEX_STATE["message"] = "Reindex failed."
            raise
        finally:
            REINDEX_STATE["running"] = False
            REINDEX_STATE["finished_at"] = time.time()
    app.view_functions["api_reindex"] = api_reindex_wrapper



import os
from pathlib import Path
from flask import request

def _pick_writable_dir(env_key: str, default1: str, default2: str) -> Path:
    candidates = []
    env = os.getenv(env_key)
    if env:
        candidates.append(Path(env))
    candidates.append(Path(default1))
    candidates.append(Path(default2))
    for p in candidates:
        try:
            p.mkdir(parents=True, exist_ok=True)
            t = p / ".write_test"
            t.write_text("ok", encoding="utf-8")
            t.unlink(missing_ok=True)
            return p
        except Exception:
            continue
    p = Path("/tmp/spellcaster_fallback")
    p.mkdir(parents=True, exist_ok=True)
    return p

UPLOADS_DIR = _pick_writable_dir("UPLOADS_DIR", "/data/spellcaster_uploads", "/tmp/spellcaster_uploads")

@app.post("/api/upload")
def api_simple_upload():
    """Simple multi-file upload endpoint for the uploads UI.
    Saves to UPLOADS_DIR preserving relative paths when provided."""
    if "files" not in request.files:
        return {"ok": False, "error": "no_files"}, 400

    saved = 0
    bytes_total = 0
    for f in request.files.getlist("files"):
        name = (f.filename or "").replace("\\", "/").lstrip("/")
        if not name:
            continue
        name = "/".join([p for p in name.split("/") if p not in ("", ".", "..")])
        dest = (UPLOADS_DIR / name)
        dest.parent.mkdir(parents=True, exist_ok=True)
        f.save(dest)
        saved += 1
        try:
            bytes_total += dest.stat().st_size
        except Exception:
            pass

    return {"ok": True, "saved": saved, "bytes": bytes_total, "uploads_dir": str(UPLOADS_DIR)}
