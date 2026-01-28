#!/usr/bin/env python3
"""
Spellcaster Portal – Resumable Library Uploader (chunked)

Uploads PDFs to your running Spellcaster Portal using:
  POST /api/upload/init
  POST /api/upload/chunk/<upload_id>
  POST /api/upload/complete/<upload_id>

Features:
- Walks a folder (your library) and uploads PDFs one by one
- Resume-safe: if interrupted, it can continue by querying /api/upload/status
- Chunked uploads (default 5MB) to survive flaky connections / Render limits

Usage:
  python upload_client.py --base-url http://127.0.0.1:5000 --library ./library

If you're uploading to Render, use your public URL, e.g.:
  python upload_client.py --base-url https://spellcaster-portal.onrender.com --library ./library
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
import requests

def iter_pdfs(root: Path):
    for p in root.rglob("*.pdf"):
        if p.is_file():
            yield p

def safe_relpath(pdf: Path, root: Path) -> str:
    rel = pdf.relative_to(root).as_posix()
    # keep as-is; server will sanitize
    return rel

def init_upload(base_url: str, filename: str, relpath: str, size: int) -> dict:
    r = requests.post(f"{base_url}/api/upload/init", json={"filename": filename, "relpath": relpath, "size": size}, timeout=60)
    r.raise_for_status()
    return r.json()

def status_upload(base_url: str, upload_id: str) -> dict:
    r = requests.get(f"{base_url}/api/upload/status/{upload_id}", timeout=60)
    r.raise_for_status()
    return r.json()

def send_chunk(base_url: str, upload_id: str, idx: int, chunk_bytes: bytes) -> dict:
    files = {"chunk": ("chunk.bin", chunk_bytes, "application/octet-stream")}
    data = {"index": str(idx)}
    r = requests.post(f"{base_url}/api/upload/chunk/{upload_id}", files=files, data=data, timeout=120)
    r.raise_for_status()
    return r.json()

def complete_upload(base_url: str, upload_id: str) -> dict:
    r = requests.post(f"{base_url}/api/upload/complete/{upload_id}", timeout=120)
    r.raise_for_status()
    return r.json()

def upload_one_pdf(base_url: str, pdf: Path, root: Path):
    size = pdf.stat().st_size
    relpath = safe_relpath(pdf, root)
    filename = pdf.name

    init = init_upload(base_url, filename, relpath, size)
    if not init.get("ok"):
        raise RuntimeError(init)

    upload_id = init["upload_id"]
    chunk_size = int(init["chunk_size"])

    # If a previous partial exists, we can resume by asking status
    st = status_upload(base_url, upload_id)
    received = set(st.get("received", []))

    with pdf.open("rb") as f:
        idx = 0
        while True:
            chunk = f.read(chunk_size)
            if not chunk:
                break
            if idx not in received:
                send_chunk(base_url, upload_id, idx, chunk)
            idx += 1

    done = complete_upload(base_url, upload_id)
    return done

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--base-url", required=True, help="e.g. http://127.0.0.1:5000 or your Render URL")
    ap.add_argument("--library", required=True, help="path to your local library folder")
    ap.add_argument("--start-at", default="", help="optional: only upload files whose relpath >= this string (simple resume filter)")
    args = ap.parse_args()

    base_url = args.base_url.rstrip("/")
    root = Path(args.library).expanduser().resolve()
    if not root.exists():
        print(f"Library path not found: {root}", file=sys.stderr)
        sys.exit(2)

    start_at = args.start_at
    total = 0
    ok = 0

    for pdf in iter_pdfs(root):
        rel = safe_relpath(pdf, root)
        if start_at and rel < start_at:
            continue

        total += 1
        print(f"\n[{total}] Uploading: {rel} ({pdf.stat().st_size/1024/1024:.2f} MB)")
        try:
            result = upload_one_pdf(base_url, pdf, root)
            print("  -> complete:", result.get("index"))
            ok += 1
        except Exception as e:
            print("  !! failed:", e, file=sys.stderr)
            print("  Tip: rerun with --start-at", rel, file=sys.stderr)
            break

    print(f"\nDone: {ok}/{total} uploaded this run.")

if __name__ == "__main__":
    main()
