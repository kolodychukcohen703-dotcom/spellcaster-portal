SPELLCASTER PORTAL — FIXED BUILD (v2)

This build restores the full portal AND adds a stable library ingest pipeline.

What’s new:
- Upload completion no longer fails if indexing errors (index happens in background).
- New endpoints:
  POST /api/library/ingest        { "source_dir": "/tmp/spellcaster_upload_staging" }
  GET  /api/library/ingest_status

Render (recommended):
- Add a Persistent Disk mounted at /data
- Set env var: LIB_DIR=/data/library

How to use ingest:
1) Put files/folders into /tmp/spellcaster_upload_staging (via upload queue or Drive sync output)
2) Call /api/library/ingest
3) Poll /api/library/ingest_status
