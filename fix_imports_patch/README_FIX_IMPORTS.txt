FIX: SyntaxError around RequestEntityTooLarge import

This patch provides a safe fixer script that repairs the import section in-place.

Steps (from your repo folder):
  cd ~/sentinel/sentinel_spellcaster_worldchatbot_merged
  unzip -o /path/to/fix_imports_patch.zip
  python3 fix_imports.py spellcaster_portal.py
  python3 -m py_compile spellcaster_portal.py   # should be silent if OK
  git add spellcaster_portal.py
  git commit -m "Fix broken RequestEntityTooLarge import placement"
  git push

Then redeploy on Render.
