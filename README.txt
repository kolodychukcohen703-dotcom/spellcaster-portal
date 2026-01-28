Sentinel Spellcaster Upload + Reindex Compatibility Fix (v4)

What's fixed:
- Adds /reindex and /reindex_library routes (GET + POST) so older buttons/links don't 404.
- GET route auto-calls POST /api/reindex and displays the result.

Install:
1) Unzip into your repo folder (sentinel_spellcaster_worldchatbot_merged).
2) It will overwrite spellcaster_portal.py and include upload_client.py.

Notes:
- On Render, redeploy after git push.
