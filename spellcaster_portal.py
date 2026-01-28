#!/usr/bin/env python3
"""
Spellcaster Web Portal — Cohen Edition (with login)

Features:
- Indexes your ~/sentinel/library (PDF, TXT, MD) into SQLite + FTS
- Search with FTS + optional substring fallback
- Facets (Spells / Remedies / Potions / Cures / Protection) with poems & live counts
- Per-document notes, personal poem, and song/chorus
- Auto-Caster ritual logger (target, spell, repetitions, delay, presets)
- Simple Audio Reading Mode (no word highlighting)
- Soothing Mode ("Void Drift") with optional ambient hum
- Login / password wall to protect the whole portal
"""

from __future__ import annotations
import os, re, sqlite3, unicodedata
from datetime import datetime
from pathlib import Path
from typing import List, Dict, Optional

from functools import wraps
from flask import (
    Flask,
    request,
    jsonify,
    send_from_directory,
    Response,
    abort,
    session,
    redirect,
    url_for,
    render_template,
)


import openai

# OpenAI client for Sentinel-style reflections (legacy library style)
openai.api_key = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-4.1-mini")  # or e.g. 'gpt-4o-mini'

# ---- Config ---------------------------------------------------------------
APP_NAME = "Spellcaster Portal"

# Login credentials (local only)
USERNAME = os.getenv("PORTAL_USER", "cohen")
PASSWORD = os.getenv("PORTAL_PASS", "fast5man!@")  # set PORTAL_PASS on Render

# This file lives in ~/sentinel/sentinel-suite
# We want BASE_DIR to be ~/sentinel (one level up).
BASE_DIR = Path(__file__).resolve().parent.parent

LIB_DIR = BASE_DIR / "library"
DB_PATH = BASE_DIR / "spellcaster.db"
LIB_DIR.mkdir(parents=True, exist_ok=True)

DEFAULT_USE_CLEANER = True
DEFAULT_LIKE_FALLBACK = True

# Optional PDF support
try:
    import PyPDF2  # type: ignore
    HAS_PDF = True
except Exception:
    HAS_PDF = False

# Optional cleaner PDF extraction
try:
    import pdfminer_high_level as pdfminer_high  # type: ignore
    HAS_PDFMINER = True
except Exception:
    HAS_PDFMINER = False

# Optional Markdown
try:
    import markdown2  # type: ignore
except Exception:
    markdown2 = None

# ---- Database / Search ----------------------------------------------------
SCHEMA_SQL = r"""
PRAGMA journal_mode=WAL;
PRAGMA synchronous=NORMAL;

CREATE TABLE IF NOT EXISTS documents (
    id INTEGER PRIMARY KEY,
    title TEXT NOT NULL,
    path TEXT NOT NULL UNIQUE,
    content TEXT NOT NULL,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE VIRTUAL TABLE IF NOT EXISTS docs_fts USING fts5(
    title, content,
    content='documents', content_rowid='id'
);

CREATE TRIGGER IF NOT EXISTS documents_ai AFTER INSERT ON documents BEGIN
  INSERT INTO docs_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;
CREATE TRIGGER IF NOT EXISTS documents_ad AFTER DELETE ON documents BEGIN
  INSERT INTO docs_fts(docs_fts, rowid, title, content) VALUES ('delete', old.id, old.title, old.content);
END;
CREATE TRIGGER IF NOT EXISTS documents_au AFTER UPDATE ON documents BEGIN
  INSERT INTO docs_fts(docs_fts, rowid, title, content) VALUES ('delete', old.id, old.title, old.content);
  INSERT INTO docs_fts(rowid, title, content) VALUES (new.id, new.title, new.content);
END;
"""

def get_conn() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    conn.execute("PRAGMA synchronous=NORMAL;")
    conn.execute("PRAGMA temp_store=MEMORY;")
    conn.execute("PRAGMA cache_size = -20000;")
    conn.create_function("now_iso", 0, lambda: datetime.utcnow().isoformat())
    return conn

# ---- Facets & Ritual Metadata ---------------------------------------------

FACET_DEFS: Dict[str, List[str]] = {
    "Spells": ["spell", "incantation", "invocation", "conjure"],
    "Remedies": ["remedy", "salve", "ointment", "treatment", "herb"],
    "Potions": ["potion", "elixir", "tincture", "brew"],
    "Cures": ["cure", "healing", "heal", "antidote"],
    "Protection": ["protection", "ward", "shield", "banish", "circle", "sigil"],
}

FACET_POEMS: Dict[str, str] = {
    "Spells":     "Whispered threads of ink and air, your words decide which worlds will flare.",
    "Remedies":   "Leaf and root and quiet care, the body learns it isn’t bare.",
    "Potions":    "In glass and swirl, a sleeping star, you drink the roads to who you are.",
    "Cures":      "Soft undoing of the harm, untying knots with patient charm.",
    "Protection": "Circles drawn and sigils bright, your name stays burning in the night.",
}

FACET_SONGS: Dict[str, str] = {
    "Spells":     "🎵 ‘Speak low, speak clear, let the spell draw near.’",
    "Remedies":   "🎵 ‘Herb by herb, we hum repair, weaving health from open air.’",
    "Potions":    "🎵 ‘Stir once for truth, twice for sight, three times for dream-lit night.’",
    "Cures":      "🎵 ‘Let the wound remember less, beat by beat in gentleness.’",
    "Protection": "🎵 ‘Circle bright, circle strong, keep my story safe and long.’",
}

def init_facets_and_notes(conn: sqlite3.Connection) -> None:
    # Facet meta
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS facet_meta (
            name TEXT PRIMARY KEY,
            poem TEXT,
            song TEXT,
            doc_count INTEGER NOT NULL DEFAULT 0
        );
        """
    )
    for name in FACET_DEFS.keys():
        row = conn.execute(
            "SELECT name, poem, song FROM facet_meta WHERE name = ?",
            (name,),
        ).fetchone()
        if not row:
            poem = FACET_POEMS.get(name, "")
            song = FACET_SONGS.get(name, "")
            conn.execute(
                "INSERT INTO facet_meta (name, poem, song, doc_count) VALUES (?,?,?,0)",
                (name, poem, song),
            )
        else:
            poem = FACET_POEMS.get(name, "") or row["poem"]
            song = FACET_SONGS.get(name, "") or row["song"]
            if poem != row["poem"] or song != row["song"]:
                conn.execute(
                    "UPDATE facet_meta SET poem=?, song=? WHERE name=?",
                    (poem, song, name),
                )

    # Per-document notes / poems
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS document_notes (
            doc_id INTEGER PRIMARY KEY,
            notes TEXT,
            poem TEXT,
            song TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY (doc_id) REFERENCES documents(id) ON DELETE CASCADE
        );
        """
    )

    # Auto-caster ritual log
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS ritual_runs (
            id INTEGER PRIMARY KEY,
            target TEXT,
            spell TEXT,
            repetitions INTEGER,
            delay_seconds INTEGER,
            preset_name TEXT,
            created_at TEXT NOT NULL
        );
        """
    )

def init_db():
    conn = get_conn()
    with conn:
        conn.executescript(SCHEMA_SQL)
        init_facets_and_notes(conn)
    conn.close()

# ---- Ingestion & Cleaning -------------------------------------------------

def read_text_file(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8", errors="ignore")
    except Exception:
        return path.read_text(encoding="latin-1", errors="ignore")

def read_pdf_file(path: Path) -> str:
    if HAS_PDFMINER:
        try:
            return pdfminer_high.extract_text(str(path)) or ""
        except Exception:
            pass
    if not HAS_PDF:
        return ""
    parts: List[str] = []
    try:
        with path.open("rb") as f:
            reader = PyPDF2.PdfReader(f)
            for page in reader.pages:
                try:
                    t = page.extract_text() or ""
                except Exception:
                    t = ""
                if t:
                    parts.append(t)
    except Exception:
        return ""
    return "\n".join(parts)

def clean_text(raw: str) -> str:
    if not raw:
        return ""
    t = unicodedata.normalize("NFC", raw)
    t = t.replace("\r\n", "\n").replace("\r", "\n")
    t = t.replace("\u00ad", "").replace("\u200b", "").replace("\u2060", "")
    t = re.sub(r"-\n(?=\w)", "", t)
    t = re.sub(r"[ \t]*\n[ \t]*", " ", t)
    t = re.sub(r"(?<=[a-z])(?=[A-Z])", " ", t)
    t = re.sub(r"([.,;:!?])(?=[A-Za-z])", r"\1 ", t)
    t = re.sub(r"[ \t]{2,}", " ", t)
    return t.strip()

def extract_text(path: Path, use_cleaner: bool = DEFAULT_USE_CLEANER) -> str:
    ext = path.suffix.lower()
    if ext in {".txt", ".md"}:
        raw = read_text_file(path)
    elif ext == ".pdf":
        raw = read_pdf_file(path)
    else:
        raw = ""
    return clean_text(raw) if use_cleaner else raw

def title_from_path(path: Path) -> str:
    name = path.stem
    name = re.sub(r"[_-]+", " ", name).strip()
    return name.title() if name else str(path.name)

def recompute_facet_counts(conn: Optional[sqlite3.Connection] = None) -> None:
    """
    Keeps facet_meta.doc_count roughly in sync, but UI now
    uses live counts, so this is mostly informational.
    """
    close_after = False
    if conn is None:
        conn = get_conn()
        close_after = True

    for facet, kws in FACET_DEFS.items():
        count = 0
        try:
            q = " OR ".join(
                [f"{kw}*" for kw in kws if len(kw) > 2] +
                [kw for kw in kws if len(kw) <= 2]
            )
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM docs_fts WHERE docs_fts MATCH ?",
                (q,),
            ).fetchone()
            count = int(row["c"] or 0)
        except sqlite3.OperationalError:
            like_clause = " OR ".join([f"content LIKE ?" for _ in kws])
            params = [f"%{kw}%" for kw in kws]
            row = conn.execute(
                f"SELECT COUNT(*) AS c FROM documents WHERE {like_clause}",
                params,
            ).fetchone()
            count = int(row["c"] or 0)

        conn.execute(
            "UPDATE facet_meta SET doc_count=? WHERE name=?",
            (count, facet),
        )

    if close_after:
        conn.close()

def index_library(use_cleaner: bool = DEFAULT_USE_CLEANER) -> Dict[str, int]:
    init_db()
    conn = get_conn()

    print(f"[Reindex] BASE_DIR = {BASE_DIR}")
    print(f"[Reindex] LIB_DIR  = {LIB_DIR}")

    inserted = updated = removed = 0
    file_count = 0

    existing = {row["path"]: row["id"] for row in conn.execute("SELECT id, path FROM documents")}

    for path in sorted(LIB_DIR.rglob("*")):
        if not path.is_file():
            continue
        if path.suffix.lower() not in ({".txt", ".md", ".pdf"} if HAS_PDF else {".txt", ".md"}):
            continue

        file_count += 1
        text = extract_text(path, use_cleaner=use_cleaner)
        if not text.strip():
            continue
        title = title_from_path(path)
        now = datetime.utcnow().isoformat()
        try:
            rel = str(path.relative_to(BASE_DIR))
        except ValueError:
            rel = str(path)
        if rel in existing:
            row = conn.execute("SELECT content FROM documents WHERE path = ?", (rel,)).fetchone()
            if row and row["content"] != text:
                with conn:
                    conn.execute(
                        "UPDATE documents SET title=?, content=?, updated_at=? WHERE path=?",
                        (title, text, now, rel),
                    )
                updated += 1
            existing.pop(rel, None)
        else:
            with conn:
                conn.execute(
                    "INSERT INTO documents(title, path, content, created_at, updated_at) VALUES (?,?,?,?,?)",
                    (title, rel, text, now, now),
                )
            inserted += 1

    for stale_path, doc_id in existing.items():
        with conn:
            conn.execute("DELETE FROM documents WHERE id=?", (doc_id,))
        removed += 1

    recompute_facet_counts(conn)
    total_docs = conn.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"]
    conn.close()

    print(f"[Reindex] Files scanned: {file_count}")
    print(f"[Reindex] Inserted: {inserted}, Updated: {updated}, Removed: {removed}")
    print(f"[Reindex] Total docs in DB: {total_docs}")

    return {
        "inserted": inserted,
        "updated": updated,
        "removed": removed,
        "total_docs": total_docs,
        "files_scanned": file_count,
    }

# ---- Helpers --------------------------------------------------------------

def index_single_pdf(pdf_path: Path) -> dict:
    """Index or update a single PDF in the SQLite library DB.

    Returns a small status dict: {status: 'indexed'|'skipped'|'error', relpath: str, reason?: str}
    """
    try:
        if not pdf_path.exists() or not pdf_path.is_file():
            return {"status": "error", "relpath": str(pdf_path), "reason": "file_not_found"}
        if pdf_path.suffix.lower() != ".pdf":
            return {"status": "skipped", "relpath": str(pdf_path), "reason": "not_pdf"}

        relpath = str(pdf_path.relative_to(LIB_DIR)).replace("\\", "/")

        data = pdf_path.read_bytes()
        file_hash = hashlib.md5(data).hexdigest()

        title = pdf_path.stem
        kind = "pdf"
        content = ""  # we don't extract text here (fast + safe). Use /api/reindex for full rebuild if you add extractors.

        now = datetime.utcnow().isoformat(timespec="seconds") + "Z"

        conn = get_conn()
        cur = conn.cursor()

        cur.execute("SELECT id, hash FROM documents WHERE relpath = ? AND kind = 'pdf'", (relpath,))
        row = cur.fetchone()

        if row and row[1] == file_hash:
            return {"status": "skipped", "relpath": relpath, "reason": "unchanged"}

        if row:
            doc_id = row[0]
            cur.execute(
                "UPDATE documents SET title = ?, content = ?, hash = ?, updated_at = ? WHERE id = ?",
                (title, content, file_hash, now, doc_id),
            )
        else:
            cur.execute(
                "INSERT INTO documents (title, relpath, kind, content, hash, added_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?)",
                (title, relpath, kind, content, file_hash, now, now),
            )

        conn.commit()
        return {"status": "indexed", "relpath": relpath}
    except Exception as e:
        try:
            conn.rollback()
        except Exception:
            pass
        return {"status": "error", "relpath": str(pdf_path), "reason": str(e)}
    finally:
        try:
            conn.close()
        except Exception:
            pass


def rel_to_abs(rel_path: str) -> Path:
    p = Path(rel_path)
    if p.is_absolute():
        return p
    return (BASE_DIR / p).resolve()

# ---- Web App --------------------------------------------------------------
app = Flask(__name__)
# Session config
app.secret_key = os.getenv("SECRET_KEY", "change-this-secret-if-you-like-123")
# Upload limit (bytes)
app.config["MAX_CONTENT_LENGTH"] = int(os.getenv("MAX_UPLOAD_MB", "75")) * 1024 * 1024
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)

# ---- Auth helpers ---------------------------------------------------------

def login_required(f):
    @wraps(f)
    def wrapper(*args, **kwargs):
        if not session.get("logged_in"):
            # remember where user wanted to go
            return redirect(url_for("login", next=request.path))
        return f(*args, **kwargs)
    return wrapper

@app.route("/login", methods=["GET", "POST"])
def login():
    # Already logged in? Go console journal.
    if session.get("logged_in"):
        return redirect(url_for("home_hub"))

    error = None
    next_url = (
        request.args.get("next")
        or request.form.get("next")
        or url_for("console_journal")
    )

    if request.method == "POST":
        u = (request.form.get("username") or "").strip()
        p = request.form.get("password") or ""
        if u == USERNAME and p == PASSWORD:
            session["logged_in"] = True
            session["user"] = u
            return redirect(url_for("home_hub"))
        else:
            error = "Invalid credentials."

    # Simple, self-contained login page
    return Response(f"""
    <!doctype html>
    <html>
    <head>
      <meta charset="utf-8"/>
      <meta name="viewport" content="width=device-width, initial-scale=1"/>
      <title>Spellcaster Login</title>
      <style>
        body {{
          margin:0;
          font-family: system-ui, -apple-system, Segoe UI, sans-serif;
          background: radial-gradient(1000px 700px at 10% -10%, #1f2937, #020617);
          color:#e5e7eb;
          display:flex;
          align-items:center;
          justify-content:center;
          min-height:100vh;
        }}
        .card {{
          width: min(360px, 92vw);
          background: rgba(15,23,42,.95);
          border-radius: 18px;
          padding: 1.4rem 1.5rem 1.6rem;
          box-shadow: 0 18px 45px rgba(0,0,0,.75);
          border:1px solid rgba(148,163,184,.25);
        }}
        h1 {{
          margin:0 0 .6rem 0;
          font-size:1.25rem;
        }}
        .muted {{ color:#9ca3af; font-size:.9rem; }}
        label {{
          display:block;
          margin-top:.8rem;
          font-size:.85rem;
          color:#9ca3af;
        }}
        input[type="text"], input[type="password"] {{
          width:100%;
          margin-top:.25rem;
          padding:.55rem .7rem;
          border-radius:10px;
          border:1px solid rgba(148,163,184,.4);
          background:#020617;
          color:#e5e7eb;
          outline:none;
          font-size:.9rem;
        }}
        input[type="text"]:focus, input[type="password"]:focus {{
          border-color:#a855f7;
          box-shadow:0 0 0 2px rgba(168,85,247,.3);
        }}
        button {{
          margin-top:1rem;
          width:100%;
          padding:.6rem .8rem;
          border-radius:999px;
          border:1px solid rgba(168,85,247,.6);
          background:linear-gradient(180deg, rgba(168,85,247,.9), rgba(129,140,248,.9));
          color:white;
          font-size:.95rem;
          cursor:pointer;
        }}
        .err {{ color:#fca5a5; font-size:.85rem; margin-top:.4rem; }}
        .sigil {{
          width:28px; height:28px; border-radius:50%;
          background: conic-gradient(from 210deg, #a855f7, #22d3ee, #a78bfa, #a855f7);
          box-shadow:0 0 0 3px rgba(129,140,248,.35), inset 0 0 20px rgba(255,255,255,.3);
          margin-bottom:.5rem;
        }}
      </style>
    </head>
    <body>
      <div class="card">
        <div class="sigil"></div>
        <h1>Spellcaster Portal</h1>
        <div class="muted">Private gate. Enter your key to step inside.</div>
        <form method="post">
          <input type="hidden" name="next" value="{next_url}"/>
          <label>Username
            <input type="text" name="username" autocomplete="username" required/>
          </label>
          <label>Password
            <input type="password" name="password" autocomplete="current-password" required/>
          </label>
          <button type="submit">Enter</button>
        </form>
        {"<div class='err'>" + error + "</div>" if error else ""}
      </div>
    </body>
    </html>
    """, mimetype="text/html")

@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))

@app.route("/console_journal", methods=["GET", "POST"])
@login_required
def console_journal():
    """Virtual console journal after login.

    - Reflection mode: gentle journaling reflections
    - Dream mode: dream symbols & insights
    """
    journal_text = ""
    mode = "reflection"  # or "dream"
    ai_output: Optional[str] = None
    error: Optional[str] = None

    if request.method == "POST":
        journal_text = (request.form.get("journal_text") or "").strip()
        mode = (request.form.get("mode") or "reflection").strip() or "reflection"

        if not journal_text:
            error = "Please write something in your journal first."
        else:
            try:
                if mode == "dream":
                    system_msg = (
                        "You are Sentinel, a calm, supportive dream and journal companion. "
                        "Given the user's entry, first offer a short emotional reflection, "
                        "then list key dream symbols or metaphors with gentle interpretations. "
                        "Use headings 'Reflection' and 'Dream Symbols & Insights'. "
                        "Be kind, grounded, and avoid clinical or diagnostic language."
                    )
                else:
                    system_msg = (
                        "You are Sentinel, a calm, supportive journaling companion. "
                        "Given the user's entry, provide a brief reflection and 3–5 gentle "
                        "insights or questions. Use headings 'Reflection' and "
                        "'Insights & Questions'. Be validating and non-judgmental."
                    )

                completion = openai.ChatCompletion.create(
                    model=OPENAI_MODEL,
                    messages=[
                        {"role": "system", "content": system_msg},
                        {"role": "user", "content": journal_text},
                    ],
                    temperature=0.7,
                )
                ai_output = completion["choices"][0]["message"]["content"]
            except Exception as e:
                # Friendly error, no full traceback
                error = f"Something went wrong talking to Sentinel: {e}"

    return render_template(
        "console_journal.html",
        journal_text=journal_text,
        mode=mode,
        ai_output=ai_output,
        error=error,
    )

# ---- Routes (protected) ---------------------------------------------------

@app.route("/")
@login_required
def home() -> Response:
    return Response(INDEX_HTML, mimetype="text/html")

@app.route("/api/health")
@login_required
def api_health():
    init_db()
    conn = get_conn()
    try:
        total_docs = conn.execute("SELECT COUNT(*) AS c FROM documents").fetchone()["c"]
        total_fts  = conn.execute("SELECT COUNT(*) AS c FROM docs_fts").fetchone()["c"]
        one_doc = conn.execute("SELECT id, path FROM documents ORDER BY id DESC LIMIT 1").fetchone()
        sample = dict(one_doc) if one_doc else None
        return jsonify({"ok": True, "docs": total_docs, "fts": total_fts, "sample": sample})
    finally:
        conn.close()

@app.route("/api/books")
@login_required
def api_books():
    conn = get_conn()
    rows = conn.execute(
        "SELECT id, title, path, created_at, updated_at FROM documents ORDER BY title COLLATE NOCASE"
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/spell/<int:doc_id>")
@login_required
def api_spell(doc_id: int):
    conn = get_conn()
    row = conn.execute(
        "SELECT id, title, content, path, updated_at FROM documents WHERE id=?", (doc_id,)
    ).fetchone()
    conn.close()
    if not row:
        return jsonify({"error": "not_found"}), 404

    content = row["content"]
    if markdown2 and ("\n#" in content or content.strip().startswith(("#", "##"))):
        html = markdown2.markdown(content)
    else:
        html = (
            content.replace("&", "&amp;")
                   .replace("<", "&lt;")
                   .replace(">", "&gt;")
                   .replace("\n\n", "</p><p>")
                   .replace("\n", "<br>")
        )
        html = f"<p>{html}</p>"
    return jsonify({
        "id": row["id"],
        "title": row["title"],
        "path": row["path"],
        "updated_at": row["updated_at"],
        "html": html,
        "text": content,  # plain text for simple audio reading
    })

@app.route("/file/<int:doc_id>")
@login_required
def file_by_id(doc_id: int):
    conn = get_conn()
    row = conn.execute("SELECT path FROM documents WHERE id=?", (doc_id,)).fetchone()
    conn.close()
    if not row:
        abort(404)
    rel = row["path"]
    abspath = rel_to_abs(rel)
    if not abspath.exists():
        abort(404)
    try:
        abspath.relative_to(BASE_DIR)
    except Exception:
        abort(403)
    return send_from_directory(directory=str(abspath.parent), path=abspath.name)

# ---- Notes / Poems per Document -------------------------------------------

@app.route("/api/notes/<int:doc_id>", methods=["GET", "POST"])
@login_required
def api_notes(doc_id: int):
    conn = get_conn()
    if request.method == "GET":
        row = conn.execute(
            "SELECT notes, poem, song, updated_at FROM document_notes WHERE doc_id=?",
            (doc_id,),
        ).fetchone()
        conn.close()
        if not row:
            return jsonify({"notes": "", "poem": "", "song": "", "updated_at": None})
        return jsonify({
            "notes": row["notes"] or "",
            "poem": row["poem"] or "",
            "song": row["song"] or "",
            "updated_at": row["updated_at"],
        })

    # POST: upsert
    try:
        payload = request.get_json(force=True)
    except Exception:
        conn.close()
        return jsonify({"error": "invalid_json"}), 400

    notes = (payload.get("notes") or "").strip()
    poem = (payload.get("poem") or "").strip()
    song = (payload.get("song") or "").strip()
    now = datetime.utcnow().isoformat()

    with conn:
        row = conn.execute("SELECT 1 FROM document_notes WHERE doc_id=?", (doc_id,)).fetchone()
        if row:
            conn.execute(
                "UPDATE document_notes SET notes=?, poem=?, song=?, updated_at=? WHERE doc_id=?",
                (notes, poem, song, now, doc_id),
            )
        else:
            conn.execute(
                "INSERT INTO document_notes(doc_id, notes, poem, song, updated_at) VALUES (?,?,?,?,?)",
                (doc_id, notes, poem, song, now),
            )
    conn.close()
    return jsonify({"status": "ok", "updated_at": now})

# ---- Auto-Caster Ritual Logger --------------------------------------------

@app.route("/api/autocast", methods=["POST"])
@login_required
def api_autocast():
    conn = get_conn()
    try:
        payload = request.get_json(force=True)
    except Exception:
        conn.close()
        return jsonify({"error": "invalid_json"}), 400

    target = (payload.get("target") or "").strip()
    spell = (payload.get("spell") or "").strip()
    reps = int(payload.get("repetitions") or 1)
    delay = int(payload.get("delay_seconds") or 0)
    preset = (payload.get("preset_name") or "").strip() or None
    if reps < 1:
        reps = 1
    if reps > 999:
        reps = 999
    if delay < 0:
        delay = 0

    now = datetime.utcnow().isoformat()
    with conn:
        cur = conn.execute(
            "INSERT INTO ritual_runs(target, spell, repetitions, delay_seconds, preset_name, created_at) VALUES (?,?,?,?,?,?)",
            (target, spell, reps, delay, preset, now),
        )
        rid = cur.lastrowid
    conn.close()

    schedule_preview = [i * delay for i in range(reps)]
    return jsonify({
        "status": "ok",
        "id": rid,
        "created_at": now,
        "target": target,
        "repetitions": reps,
        "delay_seconds": delay,
        "preset_name": preset,
        "schedule_preview": schedule_preview,
        "note": "Ritual recorded locally. This is a symbolic scheduler, not an external action.",
    })

# --------- Search -----------------------------------------------------------

def _ftsify(q_raw: str) -> str:
    """
    If the user didn't use quotes or boolean operators, AND the tokens with prefix wildcards:
      'silver mirror' -> 'silver* AND mirror*'
    If the user *does* use OR/AND/NOT, we leave it alone.
    """
    s = q_raw.strip()
    if not s:
        return s
    if re.search(r"\b(OR|AND|NOT)\b", s, flags=re.IGNORECASE):
        return s
    if '"' in s:
        return s
    toks = [t for t in re.split(r"\s+", s) if t]
    parts = []
    for t in toks:
        if len(t) <= 2:
            parts.append(t)
        else:
            parts.append(f"{t}*")
    return " AND ".join(parts) if parts else s

@app.route("/api/search")
@login_required
def api_search():
    q_raw = (request.args.get("q") or "").strip()
    like_toggle = request.args.get("like", "1" if DEFAULT_LIKE_FALLBACK else "0")
    include_like = like_toggle == "1"

    if not q_raw:
        return jsonify([])

    conn = get_conn()
    q_fts = _ftsify(q_raw)

    sql = (
        "SELECT d.id, d.title, "
        "snippet(docs_fts, 1, '<mark>', '</mark>', '…', 12) AS snippet, "
        "bm25(docs_fts) AS rank, d.path "
        "FROM docs_fts JOIN documents d ON d.id = docs_fts.rowid "
        "WHERE docs_fts MATCH ? ORDER BY rank LIMIT 100"
    )
    try:
        rows = conn.execute(sql, (q_fts,)).fetchall()
    except sqlite3.OperationalError as e:
        print(f"[Search] FTS error for q='{q_raw}' (MATCH='{q_fts}'): {e}")
        sql_fallback = sql.replace("bm25(docs_fts) AS rank, ", "0 AS rank, ")
        try:
            rows = conn.execute(sql_fallback, (q_fts,)).fetchall()
        except sqlite3.OperationalError as e2:
            print(f"[Search] FTS fallback also failed: {e2}")
            rows = []

    if rows or not include_like:
        conn.close()
        return jsonify([dict(r) for r in rows])

    like_q = f"%{q_raw}%"
    like_sql = (
        "SELECT id, title, path, content FROM documents "
        "WHERE lower(content) LIKE lower(?) LIMIT 100"
    )
    like_rows = conn.execute(like_sql, (like_q,)).fetchall()
    out = []
    for r in like_rows:
        content = r["content"]
        pos = content.lower().find(q_raw.lower())
        if pos == -1:
            continue
        start = max(0, pos - 90)
        end = min(len(content), pos + len(q_raw) + 90)
        snippet = content[start:end]
        snippet = (snippet
                   .replace("&", "&amp;")
                   .replace("<", "&lt;")
                   .replace(">", "&gt;"))
        low = snippet.lower()
        p = low.find(q_raw.lower())
        if p != -1:
            snippet = f"{snippet[:p]}<mark>{snippet[p:p+len(q_raw)]}</mark>{snippet[p+len(q_raw):]}"

        out.append({
            "id": r["id"],
            "title": r["title"],
            "path": r["path"],
            "snippet": f"…{snippet}…",
            "rank": 0
        })

    conn.close()
    return jsonify(out)

# ---- Facets ---------------------------------------------------------------

def _facet_counts() -> Dict[str, int]:
    """
    Always compute facet counts live from the text,
    instead of trusting facet_meta.doc_count (which might be stale).
    """
    conn = get_conn()
    counts: Dict[str, int] = {k: 0 for k in FACET_DEFS.keys()}
    for facet, kws in FACET_DEFS.items():
        try:
            # Fast path: FTS
            q = " OR ".join(
                [f"{kw}*" for kw in kws if len(kw) > 2] +
                [kw for kw in kws if len(kw) <= 2]
            )
            row = conn.execute(
                "SELECT COUNT(*) AS c FROM docs_fts WHERE docs_fts MATCH ?",
                (q,),
            ).fetchone()
            counts[facet] = int(row["c"] or 0)
        except sqlite3.OperationalError:
            # Fallback: LIKE
            like_clause = " OR ".join([f"content LIKE ?" for _ in kws])
            params = [f"%{kw}%" for kw in kws]
            row = conn.execute(
                f"SELECT COUNT(*) AS c FROM documents WHERE {like_clause}",
                params,
            ).fetchone()
            counts[facet] = int(row["c"] or 0)
    conn.close()
    return counts

@app.route("/api/facets")
@login_required
def api_facets():
    """
    Return live facet counts plus stored poems/songs.
    """
    conn = get_conn()
    meta: Dict[str, Dict[str, str]] = {}
    try:
        rows = conn.execute(
            "SELECT name, poem, song FROM facet_meta"
        ).fetchall()
        for r in rows:
            meta[r["name"]] = {
                "poem": r["poem"] or "",
                "song": r["song"] or "",
            }
    except sqlite3.OperationalError:
        meta = {}
    finally:
        conn.close()

    facets = _facet_counts()
    return jsonify({"facets": facets, "defs": FACET_DEFS, "meta": meta})

# ---- Reflection (local) ---------------------------------------------------

def reflect_on_query(q: str) -> Dict[str, object]:
    ql = q.lower().strip()
    mood = []
    if any(k in ql for k in ["protect", "ward", "banish", "shield"]):
        mood.append("protection")
    if any(k in ql for k in ["heal", "cure", "remedy"]):
        mood.append("healing")
    if any(k in ql for k in ["potion", "elixir", "brew", "tincture"]):
        mood.append("alchemical")
    if any(k in ql for k in ["mirror", "silver", "moon"]):
        mood.append("lunar-reflection")
    if not mood:
        mood.append("seeking")

    suggests = []
    if "protection" in mood:
        suggests += ["Try combining a warding circle with a binding sigil.",
                     "Look for phrases like \"silver mirror\" or \"iron nail\" in older grimoires.",
                     "Search: protection OR ward, and add quotes for exact lines."]
    if "healing" in mood:
        suggests += ["Consider herbs: rosemary, plantain, calendula; look for salve or poultice forms.",
                     "Search for 'remedy* AND (fever* OR infection OR wound)'."]
    if "alchemical" in mood:
        suggests += ["Check tincture ratios (1:5 or 1:10) and steep times.",
                     "Search: potion* AND (protection OR clarity OR sleep)"]

    expansions = []
    toks = [t for t in re.split(r"\s+", q) if t]
    for t in toks:
        if len(t) <= 2:
            continue
        expansions.append(f"{t}*")
    if expansions:
        expansions = [" AND ".join(expansions)]
    else:
        expansions = ["Use quotes for exact lines or add a second term."]

    return {
        "mood": mood,
        "expansions": expansions,
        "suggestions": suggests[:4],
        "note": "This reflection is computed locally — no external API keys used."
    }

@app.route("/api/reflect")
@login_required
def api_reflect():
    q = (request.args.get("q") or "").strip()
    if not q:
        return jsonify({"mood": ["seeking"], "expansions": [], "suggestions": [], "note": "Empty query."})
    return jsonify(reflect_on_query(q))

# ---- Reindex --------------------------------------------------------------
@app.route("/api/reindex", methods=["POST"])
@login_required
def api_reindex():
    use_cleaner = DEFAULT_USE_CLEANER
    try:
        payload = request.get_json(force=False, silent=True) or {}
        if "use_cleaner" in payload:
            use_cleaner = bool(payload["use_cleaner"])
    except Exception:
        pass
    summary = index_library(use_cleaner=use_cleaner)
    return jsonify({"status": "ok", "use_cleaner": use_cleaner, **summary})

# ---- Assets ---------------------------------------------------------------

# -----------------------------
# Resumable (chunked) uploads
# -----------------------------

UPLOADS_DIR = BASE_DIR / "uploads"
UPLOADS_DIR.mkdir(parents=True, exist_ok=True)

def _upload_state_path(upload_id: str) -> Path:
    return UPLOADS_DIR / f"{upload_id}.json"

def _upload_part_path(upload_id: str) -> Path:
    return UPLOADS_DIR / f"{upload_id}.part"

def _safe_relpath(relpath: str) -> str:
    # Prevent path traversal; keep relative to library folder.
    relpath = (relpath or "").replace("\\", "/").lstrip("/")
    relpath = "/".join([p for p in relpath.split("/") if p not in ("", ".", "..")])
    return relpath

@app.post("/api/upload/init")
def api_upload_init():
    """Start a resumable upload session.

    JSON body:
      - filename: original filename (required)
      - size: total size in bytes (required)
      - relpath: relative path under library/ (optional; defaults to filename)
    """
    data = request.get_json(silent=True) or {}
    filename = (data.get("filename") or "").strip()
    total_size = int(data.get("size") or 0)
    relpath = _safe_relpath(data.get("relpath") or filename)

    if not filename or total_size <= 0:
        return jsonify({"ok": False, "error": "filename_and_size_required"}), 400

    upload_id = uuid.uuid4().hex
    chunk_size = int(os.getenv("UPLOAD_CHUNK_SIZE", str(5 * 1024 * 1024)))  # 5MB default (Render-friendly)

    state = {
        "upload_id": upload_id,
        "filename": filename,
        "relpath": relpath,
        "total_size": total_size,
        "chunk_size": chunk_size,
        "received": [],  # list[int] chunk indexes
        "created_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
        "updated_at": datetime.utcnow().isoformat(timespec="seconds") + "Z",
    }
    _upload_state_path(upload_id).write_text(json.dumps(state), encoding="utf-8")
    # Create empty part file
    with open(_upload_part_path(upload_id), "ab"):
        pass

    return jsonify({"ok": True, "upload_id": upload_id, "chunk_size": chunk_size, "received": []})

@app.get("/api/upload/status/<upload_id>")
def api_upload_status(upload_id: str):
    sp = _upload_state_path(upload_id)
    if not sp.exists():
        return jsonify({"ok": False, "error": "not_found"}), 404
    state = json.loads(sp.read_text(encoding="utf-8"))
    part = _upload_part_path(upload_id)
    state["part_size"] = part.stat().st_size if part.exists() else 0
    return jsonify({"ok": True, **state})

@app.post("/api/upload/chunk/<upload_id>")
def api_upload_chunk(upload_id: str):
    """Upload one chunk.

    Form-data:
      - chunk: file (required)
      - index: int (required)
    """
    sp = _upload_state_path(upload_id)
    if not sp.exists():
        return jsonify({"ok": False, "error": "not_found"}), 404

    state = json.loads(sp.read_text(encoding="utf-8"))
    chunk_file = request.files.get("chunk")
    if chunk_file is None:
        return jsonify({"ok": False, "error": "chunk_required"}), 400

    try:
        idx = int(request.form.get("index", "-1"))
    except Exception:
        idx = -1

    if idx < 0:
        return jsonify({"ok": False, "error": "index_required"}), 400

    chunk_size = int(state["chunk_size"])
    offset = idx * chunk_size

    part_path = _upload_part_path(upload_id)
    os.makedirs(part_path.parent, exist_ok=True)

    # Write at offset (supports resume/out-of-order)
    with open(part_path, "r+b" if part_path.exists() else "w+b") as f:
        f.seek(offset)
        f.write(chunk_file.read())

    if idx not in state["received"]:
        state["received"].append(idx)
        state["received"].sort()
        state["updated_at"] = datetime.utcnow().isoformat(timespec="seconds") + "Z"
        sp.write_text(json.dumps(state), encoding="utf-8")

    return jsonify({"ok": True, "upload_id": upload_id, "received_count": len(state["received"])})

@app.post("/api/upload/complete/<upload_id>")
def api_upload_complete(upload_id: str):
    """Finalize a resumable upload: verify size, move into library/, index just that PDF."""
    sp = _upload_state_path(upload_id)
    part_path = _upload_part_path(upload_id)
    if not sp.exists() or not part_path.exists():
        return jsonify({"ok": False, "error": "not_found"}), 404

    state = json.loads(sp.read_text(encoding="utf-8"))
    total_size = int(state["total_size"])
    relpath = _safe_relpath(state["relpath"])

    # Verify size
    if part_path.stat().st_size != total_size:
        return jsonify({
            "ok": False,
            "error": "size_mismatch",
            "expected": total_size,
            "got": part_path.stat().st_size,
        }), 400

    dest = (LIB_DIR / relpath)
    dest.parent.mkdir(parents=True, exist_ok=True)

    # Atomic-ish move
    tmp_dest = dest.with_suffix(dest.suffix + ".tmp")
    shutil.move(str(part_path), str(tmp_dest))
    tmp_dest.replace(dest)

    # Cleanup state
    try:
        sp.unlink(missing_ok=True)
    except Exception:
        pass

    # Index incrementally (fast)
    idx_result = index_single_pdf(dest)

    return jsonify({"ok": True, "saved_to": str(dest), "index": idx_result})


@app.route("/assets/<path:filename>")
def serve_asset(filename: str):
    # Note: this serves files from BASE_DIR, so putting soothing_hum.mp3
    # in ~/sentinel will make it reachable at /assets/soothing_hum.mp3
    return send_from_directory(str(BASE_DIR), filename)

# ---- Frontend (HTML/JS) ---------------------------------------------------
INDEX_HTML = r"""
<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1"/>
  <title>Spellcaster Portal</title>
  <style>
    :root {
      --bg:#0b0c10;
      --panel:#11131a;
      --ink:#f1f5f9;
      --muted:#94a3b8;
      --accent:#7c3aed;
      --ring:#a78bfa;
      --card:#0f172a;
      --shadow:rgba(0,0,0,.35);
    }
    * { box-sizing: border-box; }
    body{
      margin:0;
      font-family: system-ui, -apple-system, Segoe UI, Roboto, Ubuntu, Cantarell, Noto Sans, sans-serif;
      background: radial-gradient(1200px 900px at 10% -10%, #111827, #0b0c10);
      color: var(--ink);
      transition: background 0.5s ease, color 0.5s ease;
    }
    header{
      position: sticky;
      top:0;
      z-index:10;
      backdrop-filter: blur(8px);
      background: linear-gradient(180deg, rgba(15,23,42,.85), rgba(15,23,42,.35));
      border-bottom: 1px solid rgba(148,163,184,.15);
      transition: background 0.5s ease, border-color 0.5s ease;
    }
    .wrap{ max-width:1100px; margin:0 auto; padding:1rem; }
    .brand{ display:flex; align-items:center; gap:.75rem; font-weight:700; letter-spacing:.5px; }
    .brand .sigil{
      width:28px; height:28px; border-radius:50%;
      background: conic-gradient(from 210deg, var(--accent), #22d3ee, var(--ring), var(--accent));
      box-shadow: 0 0 0 3px rgba(124,58,237,.25), inset 0 0 25px rgba(255,255,255,.12);
    }
    .grid{ display:grid; grid-template-columns:290px 1fr; gap:1rem; padding:1rem; position:relative; z-index:1; }
    @media (max-width:880px){ .grid{ grid-template-columns:1fr; } }
    .card{
      background: linear-gradient(180deg, rgba(17,19,26,.9), rgba(17,19,26,.75));
      border:1px solid rgba(148,163,184,.12);
      border-radius:16px;
      box-shadow:0 10px 30px var(--shadow);
      transition: background 0.5s ease, border-color 0.5s ease, box-shadow 0.5s ease;
    }
    .panel{ padding:1rem; }
    .search{ display:flex; gap:.5rem; align-items:center; flex-wrap:wrap; }
    input[type="text"]{
      flex:1 1 220px;
      padding:.8rem 1rem;
      border-radius:12px;
      border:1px solid rgba(148,163,184,.25);
      background:#0b1220;
      color:var(--ink);
      outline:none;
      box-shadow: inset 0 1px 0 rgba(255,255,255,.04);
      transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.3s ease, color 0.3s ease;
    }
    input[type="text"]:focus{
      border-color:var(--ring);
      box-shadow:0 0 0 3px rgba(167,139,250,.25);
    }
    button{
      padding:.6rem .9rem;
      border-radius:12px;
      border:1px solid rgba(124,58,237,.35);
      background: linear-gradient(180deg, rgba(124,58,237,.25), rgba(124,58,237,.15));
      color: var(--ink);
      cursor: pointer;
      font-size:.9rem;
      transition: transform 0.15s ease, box-shadow 0.15s ease, border-color 0.3s ease, background 0.3s ease;
    }
    button:hover{
      transform: translateY(-1px);
      box-shadow:0 6px 18px rgba(0,0,0,.5);
    }
    .muted{ color:var(--muted); font-size:.9rem; transition: color 0.5s ease; }
    .list{
      list-style:none;
      padding:0;
      margin:.5rem 0 0 0;
      max-height:60vh;
      overflow:auto;
    }
    .list li{
      padding:.6rem .6rem;
      border-radius:10px;
      margin:.15rem 0;
      border:1px solid rgba(148,163,184,.12);
      cursor:pointer;
      transition: background 0.2s ease, border-color 0.2s ease;
    }
    .list li:hover{
      background: rgba(124,58,237,.08);
      border-color: rgba(124,58,237,.25);
    }
    .result{
      display:flex;
      flex-direction:column;
      gap:.5rem;
      padding:.8rem;
      border-radius:12px;
      border:1px solid rgba(148,163,184,.12);
      transition: background 0.2s ease, border-color 0.2s ease;
    }
    .result h4{ margin:.1rem 0; }
    mark{
      background: rgba(99,102,241,.35);
      padding:.05rem .2rem;
      border-radius:.2rem;
    }
    .viewer{ padding:1rem 1.2rem; line-height:1.6; }
    .viewer h1,h2,h3{ margin:.6rem 0; }
    .viewer p{ margin:.6rem 0; }
    .footer{
      text-align:center;
      padding:1rem;
      color:var(--muted);
      font-size:.85rem;
      position:relative;
      z-index:1;
    }
    .toggle{ display:flex; align-items:center; gap:.4rem; white-space:nowrap; }
    .toggles{ display:flex; gap:.5rem; align-items:center; flex-wrap:wrap; justify-content:flex-end; }
    .facet{
      display:flex;
      align-items:flex-start;
      justify-content:space-between;
      padding:.45rem .6rem;
      border:1px solid rgba(148,163,184,.12);
      border-radius:10px;
      margin:.2rem 0;
      gap:.5rem;
      transition: background 0.2s ease, border-color 0.2s ease;
    }
    .facet-main{ display:flex; flex-direction:column; }
    .facet-poem{ font-size:.8rem; color:var(--muted); margin-top:.15rem; }
    .facet-right{ display:flex; align-items:center; gap:.4rem; }
    .facet button{ padding:.3rem .55rem; font-size:.8rem; }
    dialog.pdf, dialog.auto {
      width:min(1000px, 96vw); border:none; border-radius:14px; padding:0;
      background: #0b1220; color: var(--ink); box-shadow:0 15px 60px rgba(0,0,0,.55);
    }
    dialog.pdf{ height:min(85vh, 800px); }
    dialog.auto{ max-height:80vh; }
    dialog::backdrop { background: rgba(0,0,0,.55); }
    .pdfbar, .autobar{
      display:flex; justify-content:space-between; align-items:center;
      padding:.6rem .8rem; border-bottom:1px solid rgba(148,163,184,.15);
    }
    .pdfwrap{ width:100%; height:calc(100% - 50px); }
    .pdfwrap iframe{ width:100%; height:100%; border:0; background:#0b1220; }
    .reflection{
      border:1px dashed rgba(148,163,184,.25);
      padding:.8rem; border-radius:12px; margin-top:.6rem;
    }
    .auto-body{
      padding:.8rem .9rem 1rem;
      display:flex; flex-direction:column; gap:.6rem;
    }
    .field{ display:flex; flex-direction:column; gap:.2rem; }
    .field label{ font-size:.85rem; color:var(--muted); }
    .field input[type="text"], .field input[type="number"], .field textarea{
      padding:.55rem .7rem;
      border-radius:10px;
      border:1px solid rgba(148,163,184,.3);
      background:#020617;
      color:var(--ink);
      outline:none;
      font-size:.9rem;
      transition: border-color 0.2s ease, box-shadow 0.2s ease, background 0.3s ease;
    }
    .field input[type="text"]:focus, .field input[type="number"]:focus, .field textarea:focus{
      border-color:var(--ring);
      box-shadow:0 0 0 2px rgba(167,139,250,.25);
    }
    .field textarea{ min-height:70px; resize:vertical; }
    .preset-row{ display:flex; flex-wrap:wrap; gap:.4rem; }
    .preset-row button{ font-size:.8rem; padding:.4rem .6rem; }
    #notesPanel{
      margin-top:1rem;
      padding:1rem;
      border-radius:12px;
      border:1px solid rgba(148,163,184,.25);
      background:#020617;
    }
    #notesPanel h3{ margin-top:0; margin-bottom:.4rem; font-size:1rem; }
    #notesPanel .field textarea{ min-height:80px; }
    #notesStatus{ margin-left:.4rem; }

    /* Simple audio controls */
    .audioControls{
      margin-top:.6rem;
      display:flex;
      flex-wrap:wrap;
      gap:.4rem;
      align-items:center;
    }

    /* Soothing mode: Void Drift */
    body.soothing-mode{
      background: radial-gradient(1200px 900px at 50% -20%, #020617, #020617);
      color:#e5e7eb;
    }
    body.soothing-mode header{
      background: linear-gradient(180deg, rgba(15,23,42,.7), rgba(15,23,42,.2));
      border-bottom-color: rgba(148,163,184,.15);
    }
    body.soothing-mode .card{
      background: linear-gradient(180deg, rgba(10,12,20,.92), rgba(10,12,20,.88));
      border-color: rgba(30,64,175,.5);
      box-shadow:0 14px 40px rgba(0,0,0,.7);
    }
    body.soothing-mode .muted{
      color:#64748b;
    }
    body.soothing-mode input[type="text"]{
      background:#020617;
      color:#e5e7eb;
    }
    body.soothing-mode .result:hover,
    body.soothing-mode .list li:hover{
      background: rgba(37,99,235,.18);
      border-color: rgba(59,130,246,.45);
    }

    /* Starfield overlay for soothing mode */
    #soothingSky{
      position:fixed;
      inset:0;
      pointer-events:none;
      opacity:0;
      transition: opacity 0.8s ease;
      z-index:0;
      overflow:hidden;
    }
    body.soothing-mode #soothingSky{
      opacity:0.35;
    }
    .soothing-star{
      position:absolute;
      width:2px;
      height:2px;
      border-radius:999px;
      background:rgba(148,163,184,.8);
      box-shadow:0 0 6px rgba(148,163,184,.9);
      opacity:0.8;
      animation: drift 36s linear infinite;
    }
    @keyframes drift{
      from { transform: translate3d(var(--sx), var(--sy),0); opacity: 0; }
      10% { opacity: 1; }
      90% { opacity: 1; }
      to { transform: translate3d(calc(var(--sx) + var(--dx)), calc(var(--sy) + var(--dy)),0); opacity:0; }
    }

    /* Hide hum toggle label when not in soothing mode to keep main view clean */
    body:not(.soothing-mode) #humLabel{
      opacity:0.2;
    }
    body:not(.soothing-mode) #humLabel input{
      opacity:0.5;
    }
  
    /* Enchanted world rim around the library */
    header, main {
      position: relative;
      z-index: 2;
    }

    .world-rim {
      position: fixed;
      inset: 0;
      pointer-events: none;
      z-index: 1;
      font-family: system-ui, -apple-system, Segoe UI, sans-serif;
    }

    .world-top-strip {
      position: absolute;
      top: 0;
      left: 0;
      right: 0;
      height: 34px;
      display: flex;
      align-items: center;
      justify-content: center;
      padding: 0 .9rem;
      font-size: .78rem;
      color: #e5e7eb;
      background: linear-gradient(to bottom, rgba(15,23,42,.96), rgba(15,23,42,0));
      backdrop-filter: blur(14px);
      letter-spacing: .03em;
      gap: .75rem;
    }

    .world-top-strip .mini {
      opacity: .9;
      text-shadow: 0 0 10px rgba(15,23,42,.9);
      display: flex;
      gap: .25rem;
      align-items: center;
    }

    .world-top-strip .ticker {
      white-space: nowrap;
      overflow: hidden;
      max-width: 720px;
      mask-image: linear-gradient(to right, transparent, #000 12%, #000 88%, transparent);
      -webkit-mask-image: linear-gradient(to right, transparent, #000 12%, #000 88%, transparent);
    }

    .world-top-strip .ticker span {
      display: inline-block;
      padding-left: 100%;
      animation: rimTicker 45s linear infinite;
    }

    @keyframes rimTicker {
      0%   { transform: translateX(0); }
      100% { transform: translateX(-100%); }
    }

    .world-side {
      position: absolute;
      bottom: 20px;
      font-size: 1.35rem;
      display: flex;
      flex-direction: column;
      gap: .25rem;
      color: #e5e7eb;
      text-shadow: 0 0 10px #000;
    }

    .world-side.left {
      left: 18px;
      align-items: flex-start;
    }

    .world-side.right {
      right: 18px;
      align-items: flex-end;
    }

    .world-creature {
      filter: drop-shadow(0 3px 8px rgba(0,0,0,.9));
      animation: creatureDrift 18s ease-in-out infinite;
    }

    .world-creature.frog {
      animation-duration: 22s;
    }

    .world-creature.snake {
      animation-duration: 26s;
    }

    @keyframes creatureDrift {
      0%   { transform: translate(0,0); }
      25%  { transform: translate(4px,-2px); }
      50%  { transform: translate(-3px,2px); }
      75%  { transform: translate(2px,0); }
      100% { transform: translate(0,0); }
    }

    .world-side .bubble {
      position: relative;
      max-width: 220px;
      font-size: .72rem;
      border-radius: 999px;
      padding: .25rem .6rem;
      background: radial-gradient(circle at 0 0, rgba(148,163,184,.3), rgba(15,23,42,.96));
      border: 1px solid rgba(148,163,184,.55);
      box-shadow: 0 4px 12px rgba(0,0,0,.85);
      backdrop-filter: blur(10px);
    }

    .world-side.left .bubble::before,
    .world-side.right .bubble::before {
      content: "";
      position: absolute;
      width: 10px;
      height: 10px;
      background: inherit;
      border-radius: 999px;
      border: inherit;
      top: -4px;
    }

    .world-side.left .bubble::before {
      left: 9px;
    }

    .world-side.right .bubble::before {
      right: 9px;
    }

    .world-altar {
      position: absolute;
      left: 50%;
      bottom: 8px;
      transform: translateX(-50%);
      display: flex;
      flex-direction: column;
      align-items: center;
      gap: .25rem;
      font-size: .8rem;
      color: #e5e7eb;
      text-shadow: 0 0 10px #000;
    }

    .world-altar-icons {
      font-size: 1rem;
      filter: drop-shadow(0 3px 8px rgba(0,0,0,.9));
    }

    .world-altar-message {
      position: relative;
      min-width: 260px;
      max-width: 360px;
      text-align: center;
      padding: .3rem .9rem;
      border-radius: 999px;
      background: radial-gradient(circle at 50% 0, rgba(248,250,252,.25), rgba(15,23,42,.98));
      border: 1px solid rgba(148,163,184,.6);
      box-shadow: 0 3px 16px rgba(0,0,0,.9);
      backdrop-filter: blur(14px);
      font-size: .76rem;
      overflow: hidden;
    }

    .world-altar-message span {
      position: absolute;
      inset: .3rem .9rem;
      display: block;
      opacity: 0;
    }

    .world-altar-message span:nth-child(1) {
      animation: altarLine 24s infinite;
      animation-delay: 0s;
    }

    .world-altar-message span:nth-child(2) {
      animation: altarLine 24s infinite;
      animation-delay: 8s;
    }

    .world-altar-message span:nth-child(3) {
      animation: altarLine 24s infinite;
      animation-delay: 16s;
    }

    @keyframes altarLine {
      0%,15%   { opacity: 0; }
      20%,55%  { opacity: 1; }
      60%,100% { opacity: 0; }
    }
</style>
</head>
<body>

  <!-- Little enchanted world around the edges -->
  <div class="world-rim">
    <div class="world-top-strip">
      <div class="mini">🌲🕳️🦉</div>
      <div class="ticker">
        <span>
          🦉 “I hoot whenever a new cure is found.” · 
          🐍 “I coil around the secrets so they don’t slip away.” · 
          🐸 “The frog only jumps when it is sure.” · 
          💎 “Every search etches another cut of light into the archive.” · 
          📜 “Cobwebs, coils, frogs & spiders quietly count each page turned.”
        </span>
      </div>
      <div class="mini">💎🐍🐸📜</div>
    </div>

    <div class="world-side left">
      <div class="world-creature owl">🦉</div>
      <div class="bubble">
        “I’m listening to which remedies you chase tonight.”
      </div>
    </div>

    <div class="world-side right">
      <div class="world-creature snake">🐍</div>
      <div class="bubble">
        “Each time you seek protection, I tighten the ward a little more.”
      </div>
    </div>

    <div class="world-altar">
      <div class="world-altar-icons world-creature frog">⛲💧🐸</div>
      <div class="world-altar-message">
        <span>May each book opened tonight return something gentle to your body.</span>
        <span>Every query and cure stays local in this grimoire, held tight by cobwebs and stone.</span>
        <span>Whatever was heavy when you arrived may leave lighter than when it came.</span>
      </div>
    </div>
  </div>

  <!-- Main grimoire layout -->
  <header>
    <div class="wrap" style="display:flex; justify-content:space-between; align-items:center; gap:1rem;">
      <div class="brand"><div class="sigil"></div><div>Spellcaster Portal</div></div>
      <div class="badges">
        <div class="toggles">
          <label class="toggle"><input type="checkbox" id="likeToggle" checked> Substring fallback</label>
          <label class="toggle"><input type="checkbox" id="cleanerToggle" checked> Clean text on reindex</label>
          <button id="autoCaster">Auto-Caster</button>
          <button id="reindex">Reindex</button>
          <button id="soothingToggle">🕊️ Soothing Mode</button>
          <label class="toggle" id="humLabel" style="font-size:.8rem;">
            <input type="checkbox" id="humToggle"> Hum
          </label>
          <a href="/logout" class="toggle" style="text-decoration:none;"><span class="muted" style="font-size:.8rem;">Logout</span></a>
        </div>
      </div>
    </div>
  </header>

  <main class="wrap">
    <div class="grid">
      <aside class="card panel">
        <div class="muted" style="margin-bottom:.4rem;">Your Library</div>
        <ul id="books" class="list"></ul>
        <hr style="opacity:.2; margin:.8rem 0;">
        <div class="muted" style="margin-bottom:.4rem;">Facets</div>
        <div id="facets"></div>
      </aside>

      <section class="card panel">
        <div class="search">
          <input id="q" type="text" placeholder='Search spells, symbols, themes… (e.g., protection OR shield, "silver mirror")'/>
          <button id="go">Search</button>
          <span class="muted">Tip: quotes for exact lines, no quotes for prefix search.</span>
        </div>
        <div id="reflect" class="reflection" style="display:none;"></div>
        <div id="results" style="margin-top:1rem; display:grid; gap:.6rem;"></div>
        <div id="viewer" class="viewer" style="display:none;"></div>
      </section>
    </div>

    <div class="footer">Local, private, and elegant — your grimoire, upgraded.</div>
  </main>


<!-- Starfield overlay and optional hum audio -->
  <div id="soothingSky"></div>
  <audio id="soothingAudio" loop></audio>

  <dialog id="pdfDlg" class="pdf">
    <div class="pdfbar"><div id="pdfTitle" class="muted">PDF Viewer</div> <button id="pdfClose">Close</button></div>
    <div class="pdfwrap"><iframe id="pdfFrame" src=""></iframe></div>
  </dialog>

  <dialog id="autoDlg" class="auto">
    <div class="autobar"><div class="muted">Auto-Caster Ritual</div> <button id="autoClose">Close</button></div>
    <div class="auto-body">
      <div class="field">
        <label for="acTarget">Target name / intent focus</label>
        <input id="acTarget" type="text" placeholder="e.g., Self, Home, Witness at the Crack">
      </div>
      <div class="field">
        <label for="acSpell">Spell text / affirmation</label>
        <textarea id="acSpell" placeholder="Write the core line or stanza…"></textarea>
      </div>
      <div class="field">
        <label>Repetitions & delay</label>
        <div style="display:flex; gap:.4rem;">
          <input id="acReps" type="number" min="1" max="999" value="3" style="max-width:90px;" />
          <input id="acDelay" type="number" min="0" value="60" style="max-width:120px;" />
        </div>
        <div class="muted" style="font-size:.8rem;">Delay is in seconds between passes (0 = no pause).</div>
      </div>
      <div class="field">
        <label>Presets</label>
        <div class="preset-row">
          <button data-preset="Protection Ward">Protection Ward</button>
          <button data-preset="Healing Wash">Healing Wash</button>
          <button data-preset="Clarity Lantern">Clarity Lantern</button>
        </div>
      </div>
      <div style="display:flex; justify-content:flex-end; gap:.5rem; align-items:center;">
        <span id="autoStatus" class="muted" style="font-size:.8rem;"></span>
        <button id="autoRun">Record Ritual</button>
      </div>
    </div>
  </dialog>

  <script>
    const el = (sel) => document.querySelector(sel);
    const results = el('#results');
    const books = el('#books');
    const viewer = el('#viewer');
    const likeToggle = el('#likeToggle');
    const cleanerToggle = el('#cleanerToggle');
    const reflectBox = el('#reflect');

    likeToggle.checked = true;
    cleanerToggle.checked = true;

    // Simple TTS state
    let ttsUtterance = null;

    async function fetchJSON(url, opts={}){
      const r = await fetch(url, opts);
      if(!r.ok) throw new Error('Request failed');
      return await r.json();
    }

    function escapeHtml(s){
      return String(s).replaceAll('&','&amp;').replaceAll('<','&lt;').replaceAll('>','&gt;');
    }

    function resetTts(){
      try{
        if('speechSynthesis' in window){
          window.speechSynthesis.cancel();
        }
      }catch(e){}
      ttsUtterance = null;
    }

    function setupTtsControls(doc){
      const play = el('#ttsPlay');
      const pause = el('#ttsPause');
      const stop = el('#ttsStop');
      const speed = el('#ttsSpeed');
      const supportMsg = el('#ttsSupport');

      if(!play || !pause || !stop || !speed) return;

      // If browser has no speech synthesis, disable controls
      if(!('speechSynthesis' in window)){
        play.disabled = true;
        pause.disabled = true;
        stop.disabled = true;
        if(supportMsg){
          supportMsg.textContent = 'Audio reading is not supported in this browser.';
        }
        return;
      } else if(supportMsg){
        supportMsg.textContent = '';
      }

      resetTts();

      play.onclick = () => {
        if(!('speechSynthesis' in window)) return;

        // If paused, resume
        if(window.speechSynthesis.paused){
          window.speechSynthesis.resume();
          return;
        }

        // If already speaking, restart from beginning
        if(window.speechSynthesis.speaking){
          resetTts();
        }

        const raw = (doc.text || '').replace(/\s+/g, ' ').trim();
        if(!raw){
          if(supportMsg){
            supportMsg.textContent = 'No text available to read.';
          }
          return;
        }

        const u = new SpeechSynthesisUtterance(raw);
        u.rate = parseFloat(speed.value || '1');
        u.onend = () => { ttsUtterance = null; };
        ttsUtterance = u;
        window.speechSynthesis.speak(u);
      };

      pause.onclick = () => {
        try{
          if('speechSynthesis' in window){
            window.speechSynthesis.pause();
          }
        }catch(e){}
      };

      stop.onclick = () => {
        resetTts();
      };

      speed.oninput = () => {
        if(ttsUtterance){
          ttsUtterance.rate = parseFloat(speed.value || '1');
        }
      };
    }

    function showViewer(doc){
      const isPdf = String(doc.path).toLowerCase().endsWith('.pdf');
      const openBtn = isPdf ? `<button id="openPdf" data-id="${doc.id}">Open PDF</button>` : '';
      const meta = `<div class="muted">${escapeHtml(doc.path)} · Updated ${escapeHtml(doc.updated_at)} ${openBtn}</div>`;
      const audioControls = `
        <div id="audioControls" class="audioControls">
          <button id="ttsPlay">▶ Listen</button>
          <button id="ttsPause">Pause</button>
          <button id="ttsStop">Stop</button>
          <label class="muted" style="font-size:.8rem; display:inline-flex; align-items:center; gap:.3rem;">
            Speed
            <input id="ttsSpeed" type="range" min="0.7" max="1.3" step="0.1" value="1"/>
          </label>
          <span id="ttsSupport" class="muted" style="font-size:.8rem;"></span>
        </div>`;

      const notesBlock = `
        <div id="notesPanel">
          <h3>Your Notes & Spell Lines</h3>
          <div class="field">
            <label for="notesText">Notes / reflections</label>
            <textarea id="notesText" placeholder="Thoughts, cross-references, reality-check cues…"></textarea>
          </div>
          <div class="field">
            <label for="poemText">Personal poem / incantation</label>
            <textarea id="poemText" placeholder="Let the spell re-write itself in your words…"></textarea>
          </div>
          <div class="field">
            <label for="songText">Song / chorus line</label>
            <textarea id="songText" placeholder="A line you could hum to remember this work…"></textarea>
          </div>
          <div style="display:flex; align-items:center; gap:.5rem; justify-content:flex-end;">
            <span id="notesStatus" class="muted" style="font-size:.8rem;"></span>
            <button id="saveNotes">Save Notes</button>
          </div>
        </div>`;

      viewer.innerHTML = `<h2>${escapeHtml(doc.title)}</h2>${meta}${audioControls}<hr style="border-color:rgba(148,163,184,.15); margin: .8rem 0;"/>${doc.html}${notesBlock}`;
      viewer.style.display = 'block';
      results.style.display = 'none';

      const btn = document.getElementById('openPdf');
      if(btn){
        btn.addEventListener('click', () => openPdf(btn.dataset.id, doc.title));
      }
      setupNotes(doc.id);
      setupTtsControls(doc);
    }

    async function setupNotes(docId){
      const notesEl = el('#notesText');
      const poemEl  = el('#poemText');
      const songEl  = el('#songText');
      const statusEl = el('#notesStatus');
      const saveBtn = el('#saveNotes');
      if(!notesEl || !saveBtn) return;

      statusEl.textContent = 'Loading notes…';
      try{
        const data = await fetchJSON(`/api/notes/${docId}`);
        notesEl.value = data.notes || '';
        poemEl.value  = data.poem || '';
        songEl.value  = data.song || '';
        if(data.updated_at){
          statusEl.textContent = `Last saved: ${data.updated_at}`;
        } else {
          statusEl.textContent = 'No notes yet.';
        }
      }catch(e){
        statusEl.textContent = 'Could not load notes.';
      }

      saveBtn.onclick = async () => {
        statusEl.textContent = 'Saving…';
        try{
          const body = {
            notes: notesEl.value,
            poem:  poemEl.value,
            song:  songEl.value,
          };
          const res = await fetchJSON(`/api/notes/${docId}`, {
            method:'POST',
            headers:{'Content-Type':'application/json'},
            body: JSON.stringify(body),
          });
          statusEl.textContent = 'Saved at ' + res.updated_at;
        }catch(e){
          statusEl.textContent = 'Save failed.';
        }
      };
    }

    function showResults(items){
      viewer.style.display = 'none';
      results.style.display = 'grid';
      results.innerHTML = '';
      if(items.length === 0){
        results.innerHTML = '<div class="muted">No matching passages. Try different terms or quotes for exact phrases.</div>';
        return;
      }
      for(const r of items){
        const node = document.createElement('div');
        node.className = 'result';
        const isPdf = String(r.path).toLowerCase().endsWith('.pdf');
        const openBtn = isPdf ? `<button data-id="${r.id}" class="open">Open PDF</button>` : '';
        node.innerHTML = `<h4>${escapeHtml(r.title)}</h4><div class="muted">${escapeHtml(r.path)}</div><div>${r.snippet}</div><div><button data-id="${r.id}" class="cast">Cast</button> ${openBtn}</div>`;
        results.appendChild(node);
      }
      results.querySelectorAll('button.cast').forEach(btn => {
        btn.addEventListener('click', async () => {
          const doc = await fetchJSON(`/api/spell/${btn.dataset.id}`);
          showViewer(doc);
          window.scrollTo({top:0, behavior:'smooth'});
        })
      });
      results.querySelectorAll('button.open').forEach(btn => {
        btn.addEventListener('click', () => openPdf(btn.dataset.id));
      });
    }

    async function loadBooks(){
      const data = await fetchJSON('/api/books');
      books.innerHTML = '';
      for(const b of data){
        const li = document.createElement('li');
        li.textContent = b.title;
        li.title = b.path;
        li.addEventListener('click', async () => {
          const doc = await fetchJSON(`/api/spell/${b.id}`);
          showViewer(doc);
        })
        books.appendChild(li);
      }
    }

    async function loadFacets(){
      try {
        const f = await fetchJSON('/api/facets');
        const box = el('#facets');
        const meta = f.meta || {};
        box.innerHTML = '';
        for(const [name,count] of Object.entries(f.facets)){
          const row = document.createElement('div');
          row.className = 'facet';
          const poem = meta[name]?.poem || '';
          const poemHtml = poem ? `<div class="facet-poem">${escapeHtml(poem)}</div>` : '';
          row.innerHTML = `
            <div class="facet-main">
              <div>${escapeHtml(name)}</div>
              ${poemHtml}
            </div>
            <div class="facet-right">
              <span class="muted">${count}</span>
              <button data-name="${escapeHtml(name)}">Open</button>
            </div>`;
          box.appendChild(row);
        }
        box.querySelectorAll('button').forEach(btn => {
          btn.addEventListener('click', async () => {
            const defs = (await fetchJSON('/api/facets')).defs;
            const name = btn.dataset.name;
            const kws = defs[name] || [];
            const q = kws.join(' OR ');
            el('#q').value = q;
            doSearch();
          });
        });
      } catch(e) {
        console.warn('Facet load error', e);
      }
    }

    async function doSearch(){
      const q = el('#q').value.trim();
      if(!q){ results.innerHTML = '<div class="muted">Enter a query above.</div>'; return; }
      const like = likeToggle.checked ? '1' : '0';
      const [refl, data] = await Promise.all([
        fetchJSON(`/api/reflect?q=${encodeURIComponent(q)}`),
        fetchJSON(`/api/search?q=${encodeURIComponent(q)}&like=${like}`)
      ]);
      if(refl){
        reflectBox.style.display = 'block';
        const tips = (refl.suggestions || []).map(s => `<li>${escapeHtml(s)}</li>`).join('');
        const exp  = (refl.expansions || []).map(s => `<code>${escapeHtml(s)}</code>`).join(' · ');
        reflectBox.innerHTML = `<b>Reflection</b> — mood: ${refl.mood.join(', ')}<br>
          <div style="margin:.4rem 0;">Try: ${exp || 'add another term or use quotes'}</div>
          <ul style="margin:.4rem 0 .2rem 1rem;">${tips}</ul>
          <div class="muted" style="font-size:.85rem;">${escapeHtml(refl.note)}</div>`;
      } else {
        reflectBox.style.display = 'none';
      }
      showResults(data);
    }

    function openPdf(id, title='PDF'){
      const dlg = el('#pdfDlg');
      el('#pdfTitle').textContent = title;
      el('#pdfFrame').src = `/file/${id}`;
      dlg.showModal();
    }
    el('#pdfClose').addEventListener('click', () => el('#pdfDlg').close());

    el('#go').addEventListener('click', doSearch);
    el('#q').addEventListener('keydown', (e) => { if(e.key==='Enter') doSearch(); });

    // Auto-Caster UI
    const autoDlg = el('#autoDlg');
    const autoBtn = el('#autoCaster');
    const autoClose = el('#autoClose');
    const autoRun = el('#autoRun');
    const autoStatus = el('#autoStatus');
    const acTarget = el('#acTarget');
    const acSpell  = el('#acSpell');
    const acReps   = el('#acReps');
    const acDelay  = el('#acDelay');

    autoBtn.addEventListener('click', () => {
      autoStatus.textContent = '';
      autoDlg.showModal();
    });
    autoClose.addEventListener('click', () => autoDlg.close());

    document.querySelectorAll('.preset-row button').forEach(btn => {
      btn.addEventListener('click', () => {
        const preset = btn.dataset.preset;
        if(preset === 'Protection Ward'){
          acSpell.value = "May this boundary hold firm; no harm, no malice, no ill intent may pass.";
          acReps.value = 3;
          acDelay.value = 60;
        } else if(preset === 'Healing Wash'){
          acSpell.value = "Let pain soften and flow away; let each breath call the body back to balance.";
          acReps.value = 7;
          acDelay.value = 30;
        } else if(preset === 'Clarity Lantern'){
          acSpell.value = "Illuminate what is true; let confusion fall away like fog from the shore.";
          acReps.value = 5;
          acDelay.value = 45;
        }
        autoStatus.textContent = `Preset loaded: ${preset}`;
      });
    });

    autoRun.addEventListener('click', async () => {
      autoStatus.textContent = 'Recording ritual…';
      try{
        const body = {
          target: acTarget.value,
          spell:  acSpell.value,
          repetitions: Number(acReps.value || 1),
          delay_seconds: Number(acDelay.value || 0),
          preset_name: document.activeElement?.dataset?.preset || null
        };
        const res = await fetchJSON('/api/autocast', {
          method:'POST',
          headers:{'Content-Type':'application/json'},
          body: JSON.stringify(body),
        });
        autoStatus.textContent = `Saved (#${res.id}) — ${res.repetitions} passes, every ${res.delay_seconds}s for ${res.target || 'unspecified target'}.`;
      }catch(e){
        autoStatus.textContent = 'Failed to record ritual.';
      }
    });

    // Soothing mode: starfield + optional hum
    const sky = el('#soothingSky');
    const soothingBtn = el('#soothingToggle');
    const humToggle = el('#humToggle');
    const soothingAudio = el('#soothingAudio');

    function createStarfield(count=45){
      if(!sky) return;
      sky.innerHTML = '';
      const vw = window.innerWidth;
      const vh = window.innerHeight;
      for(let i=0;i<count;i++){
        const star = document.createElement('div');
        star.className = 'soothing-star';
        const sx = Math.random() * vw;
        const sy = Math.random() * vh;
        const dx = (Math.random() - 0.5) * vw * 0.4;
        const dy = (Math.random() - 0.5) * vh * 0.4;
        star.style.setProperty('--sx', sx + 'px');
        star.style.setProperty('--sy', sy + 'px');
        star.style.setProperty('--dx', dx + 'px');
        star.style.setProperty('--dy', dy + 'px');
        const dur = 28 + Math.random()*18;
        star.style.animationDuration = dur + 's';
        star.style.opacity = 0.4 + Math.random()*0.6;
        sky.appendChild(star);
      }
    }

    function enableHum(on){
      if(!soothingAudio) return;
      if(on){
        if(!soothingAudio.src){
          // expects soothing_hum.mp3 to be in ~/sentinel (BASE_DIR)
          soothingAudio.src = '/assets/soothing_hum.mp3';
        }
        soothingAudio.volume = 0.25;
        soothingAudio.play().catch(()=>{});
      } else {
        soothingAudio.pause();
        soothingAudio.currentTime = 0;
      }
    }

    function setSoothing(on){
      document.body.classList.toggle('soothing-mode', on);
      if(on){
        createStarfield();
        if(humToggle && humToggle.checked){
          enableHum(true);
        }
      } else {
        enableHum(false);
      }
    }

    soothingBtn.addEventListener('click', () => {
      const on = !document.body.classList.contains('soothing-mode');
      setSoothing(on);
    });

    if(humToggle){
      humToggle.addEventListener('change', () => {
        if(document.body.classList.contains('soothing-mode') && humToggle.checked){
          enableHum(true);
        } else {
          enableHum(false);
        }
      });
    }

    window.addEventListener('resize', () => {
      if(document.body.classList.contains('soothing-mode')){
        createStarfield();
      }
    });

    el('#reindex').addEventListener('click', async () => {
      try{
        el('#reindex').disabled = true;
        const use_cleaner = cleanerToggle.checked;
        const r = await fetch('/api/reindex', {method:'POST', headers:{'Content-Type':'application/json'},
                    body: JSON.stringify({use_cleaner})});
        const j = await r.json();
        alert(`Reindex done. Files: ${j.files_scanned}, Inserted ${j.inserted}, Updated ${j.updated}, Removed ${j.removed}. Total docs: ${j.total_docs}.`);
        await loadBooks(); await loadFacets();
      } catch(e){
        alert('Reindex failed: '+ e);
      } finally {
        el('#reindex').disabled = false;
      }
    });

    (async function init(){
      try{
        const h = await fetchJSON('/api/health');
        if(!(h && h.ok)){ console.warn('Health check failed', h); }
      }catch(e){ console.warn('Health check error', e); }
      await loadBooks();
      await loadFacets();
    })();
  </script>
</body>
</html>
"""

def run():
    init_db()
    port = int(os.environ.get("PORT", "5000"))
    print(f"[{APP_NAME}] BASE_DIR = {BASE_DIR}")
    print(f"[{APP_NAME}] LIB_DIR  = {LIB_DIR}")
    print(f"[{APP_NAME}] Running on http://0.0.0.0:{port} (reachable from LAN)")
    print(f"[{APP_NAME}] On another device in your network, use: http://<this_machine_LAN_IP>:{port}")
    app.run(host="0.0.0.0", port=port, debug=False)

# --- Web Journal + GPT reflections / dream insights ------------------------
from pathlib import Path

JOURNAL_LOG_PATH = Path(__file__).resolve().parent.parent / "journal_web.log"

# Try to reuse existing OpenAI client if present, otherwise create one
try:
    client
except NameError:
    try:
        from openai import OpenAI
        client = OpenAI()
    except Exception:
        client = None  # API will fail gracefully if not configured


@app.route("/journal_web")
@login_required
def journal_web():
    """
    Simple web journal page: lets you write entries and get GPT reflections
    or dream insights, similar spirit to the console view.
    """
    # Load the last ~50 lines from the log so you can see recent entries.
    entries_tail = []
    try:
        if JOURNAL_LOG_PATH.exists():
            with JOURNAL_LOG_PATH.open("r", encoding="utf-8", errors="ignore") as f:
                lines = f.readlines()
            entries_tail = lines[-80:]
    except Exception:
        entries_tail = []
    return render_template("journal_web.html", entries=entries_tail)


@app.route("/api/journal_reflect", methods=["POST"])
@login_required
def api_journal_reflect():
    """
    Accepts JSON:
      { "entry": "...", "mode": "journal" or "dream" }

    - Appends the entry to journal_web.log
    - Calls OpenAI to generate a reflection / dream insight
    - Returns JSON with the text
    """
    data = request.get_json(force=True, silent=True) or {}
    entry = (data.get("entry") or "").strip()
    mode = (data.get("mode") or "journal").strip().lower()

    if not entry:
        return jsonify({"error": "empty_entry"}), 400

    if mode not in ("journal", "dream"):
        mode = "journal"

    ts = datetime.utcnow().isoformat()
    mode_label = "DREAM" if mode == "dream" else "JOURNAL"

    # Append to local log
    try:
        with JOURNAL_LOG_PATH.open("a", encoding="utf-8") as f:
            f.write(f"\n--- {ts} [{mode_label}] ---\n{entry}\n")
    except Exception as e:
        # Still continue but let the UI know
        log_error = str(e)
    else:
        log_error = None

    # If no OpenAI client, bail cleanly
    if client is None:
        return jsonify({
            "status": "no_client",
            "timestamp": ts,
            "log_error": log_error,
            "reflection": "API client is not configured in this environment."
        }), 500

    # Build prompts
    if mode == "dream":
        system_msg = (
            "You are a gentle dream interpreter and symbolic analyst. "
            "You speak concisely, in 3-6 short bullet points. "
            "You do NOT tell the user what will happen; you describe possible meanings, "
            "patterns, and feelings, and offer calming, grounded suggestions."
        )
        user_msg = (
            "Here is a dream entry from my journal. "
            "1) Identify 3–5 key symbols and what they might mean. "
            "2) Suggest a few gentle ways I can work with this dream in waking life.\n\n"
            f"Dream entry:\n{entry}"
        )
    else:
        system_msg = (
            "You are a reflective journaling companion. "
            "You respond in 3-6 short bullet points. "
            "You help the user notice patterns, feelings, and small, grounded next steps. "
            "You stay supportive and do not give medical or legal advice."
        )
        user_msg = (
            "Here is a journal entry from my day. "
            "1) Reflect briefly on what you notice. "
            "2) Name a few feelings that might be present. "
            "3) Suggest 1–3 tiny next steps or questions I could carry forward.\n\n"
            f"Journal entry:\n{entry}"
        )

    try:
        completion = client.responses.create(
            model="gpt-4.1-mini",
            input=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            max_output_tokens=600,
        )
        # New-style OpenAI Responses API
        ai_text = completion.output[0].content[0].text
    except Exception as e:
        return jsonify({
            "error": "api_error",
            "detail": str(e),
            "timestamp": ts,
            "log_error": log_error,
        }), 500

    return jsonify({
        "status": "ok",
        "mode": mode,
        "timestamp": ts,
        "log_error": log_error,
        "reflection": ai_text,
    })

@app.route("/home_hub")
@login_required
def home_hub():
    return render_template("home_hub.html")



if __name__ == "__main__":
    run()



@app.route("/upload", methods=["GET", "POST"])
@login_required
def upload():
    """Upload PDFs/TXT/MD into the library folder (stored under DATA_DIR)."""
    message = None
    if request.method == "POST":
        f = request.files.get("file")
        if not f or not f.filename:
            message = "No file selected."
        else:
            name = os.path.basename(f.filename)
            # basic extension allow-list
            ext = Path(name).suffix.lower()
            allowed = {".pdf", ".txt", ".md"}
            if ext not in allowed:
                message = "Unsupported file type. Allowed: PDF, TXT, MD."
            else:
                # sanitize filename
                safe = re.sub(r"[^a-zA-Z0-9._ -]+", "_", name).strip().replace("..", ".")
                if not safe:
                    safe = f"upload_{datetime.utcnow().strftime('%Y%m%d_%H%M%S')}{ext}"
                dest = LIB_DIR / safe
                # avoid overwrite by adding suffix
                if dest.exists():
                    stem = dest.stem
                    for i in range(1, 1000):
                        candidate = LIB_DIR / f"{stem}_{i}{ext}"
                        if not candidate.exists():
                            dest = candidate
                            break
                dest.parent.mkdir(parents=True, exist_ok=True)
                f.save(dest)
                # Reindex after upload
                summary = index_library(use_cleaner=DEFAULT_USE_CLEANER)
                message = f"Uploaded to {dest.name}. Reindex complete: +{summary['inserted']} new, {summary['updated']} updated."
    return render_template("upload.html", message=message)

