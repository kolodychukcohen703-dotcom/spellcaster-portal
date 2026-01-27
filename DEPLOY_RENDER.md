# Deploy (Render)

## Service type
- Web Service (Python)

## Build command
pip install -r requirements.txt

## Start command (Socket.IO)
gunicorn app:app --worker-class eventlet -w 1 --bind 0.0.0.0:$PORT

## Environment variables (recommended)
- SECRET_KEY = a long random string
- PORTAL_USER = your username
- PORTAL_PASS = your password
- OPENAI_API_KEY = (optional; only needed for reflection features)
- DATA_DIR = /var/data  (if you add a Render persistent disk mounted at /var/data)
- MAX_UPLOAD_MB = 75   (optional)

## Persistent storage (important)
Render’s filesystem is ephemeral unless you attach a Disk.
Attach a Disk and mount it at **/var/data**, then set:
- DATA_DIR=/var/data

This keeps:
- /var/data/library (uploaded books)
- /var/data/spellcaster.db (search index DB)
