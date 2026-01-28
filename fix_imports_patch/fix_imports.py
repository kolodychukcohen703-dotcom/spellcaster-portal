#!/usr/bin/env python3

"""
Fix a broken import block in spellcaster_portal.py where
`from werkzeug.exceptions import RequestEntityTooLarge`
may have been inserted inside a parenthesized `from flask import (...)` block,
causing SyntaxError.

Usage:
  python3 fix_imports.py /path/to/spellcaster_portal.py
(or run inside repo root: python3 fix_imports.py spellcaster_portal.py)
"""
import sys
from pathlib import Path

TARGET = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("spellcaster_portal.py")
if not TARGET.exists():
    print(f"[fix_imports] File not found: {TARGET}")
    sys.exit(1)

lines = TARGET.read_text(encoding="utf-8", errors="ignore").splitlines(True)

# Remove all existing occurrences (even if already correct, we'll reinsert cleanly)
lines = [ln for ln in lines if "from werkzeug.exceptions import RequestEntityTooLarge" not in ln]

insert_idx = None

# Find the first "from flask import" statement and insert after it (after closing paren if multiline)
for i, ln in enumerate(lines):
    if ln.lstrip().startswith("from flask import"):
        if "(" in ln and ")" not in ln:
            # multiline import block; find closing ')'
            depth = 0
            for j in range(i, min(i+200, len(lines))):
                depth += lines[j].count("(")
                depth -= lines[j].count(")")
                if depth <= 0 and j != i:
                    insert_idx = j + 1
                    break
            if insert_idx is None:
                insert_idx = i + 1
        else:
            insert_idx = i + 1
        break

if insert_idx is None:
    # fallback: insert after shebang/encoding/comments at top
    insert_idx = 0
    for i, ln in enumerate(lines[:80]):
        if ln.startswith("#!") or ln.lstrip().startswith("#") or ln.strip() == "":
            insert_idx = i + 1
            continue
        break

lines.insert(insert_idx, "from werkzeug.exceptions import RequestEntityTooLarge\n")

TARGET.write_text("".join(lines), encoding="utf-8")
print(f"[fix_imports] Patched: {TARGET} (inserted werkzeug import at line {insert_idx+1})")
