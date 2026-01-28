Sentinel Spellcaster Upload Bundle (Render-safe)

What this fixes
- Prevents 500s caused by writing to a read-only project directory on Render by defaulting runtime storage to /tmp.
- Lets you optionally point storage to a Render Persistent Disk mount (recommended for big libraries).

Files included
- spellcaster_portal_patched_v2.py  (server: adds env-configurable paths)
- upload_client.py                  (client: resumable, one-file-at-a-time uploader)
- app.py                            (your merged entrypoint example)
- requirements-extra.txt            (optional deps)

Server env vars (Render > Service > Environment)
- UPLOADS_DIR=/tmp/spellcaster_uploads
- LIB_DIR=/tmp/spellcaster_library
- DB_PATH=/tmp/spellcaster.db

IMPORTANT for 12.5GB library:
- /tmp is NOT persistent. If your Render service restarts, uploads/index may be lost.
- For durability you need a Render Persistent Disk (paid) or external object storage (S3/R2).
  If using a Render disk mounted at /var/data, set:
  UPLOADS_DIR=/var/data/spellcaster_uploads
  LIB_DIR=/var/data/spellcaster_library
  DB_PATH=/var/data/spellcaster.db

Client usage
1) install requests in the SAME venv you're running upload_client.py from:
   pip install requests
2) run:
   python3 upload_client.py --base-url https://spellcaster-portal.onrender.com --library ~/sentinel/library

Resume after a failure:
   python3 upload_client.py --base-url https://spellcaster-portal.onrender.com --library ~/sentinel/library --start-at "SomeBook.pdf"
