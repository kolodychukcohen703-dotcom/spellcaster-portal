FIX: Render keeps failing with:
  SyntaxError: from __future__ imports must occur at the beginning of the file

This patch normalizes the very top of spellcaster_portal.py so the future import is legal.

Steps:
  cd ~/sentinel/sentinel_spellcaster_worldchatbot_merged
  unzip -o /path/to/normalize_header_patch.zip
  python3 normalize_header.py spellcaster_portal.py
  python3 -m py_compile spellcaster_portal.py   # should be silent if OK
  git add spellcaster_portal.py
  git commit -m "Normalize header so future import is first"
  git push
