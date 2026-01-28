#!/usr/bin/env python3
"""Normalize spellcaster_portal.py header so `from __future__ import annotations`
is in a legal position (top of file after shebang/encoding/docstring only).

It will:
- keep optional shebang
- keep optional encoding cookie
- keep optional module docstring (triple-quoted)
- remove ALL occurrences of the future import
- insert exactly one future import immediately after docstring (or after initial comments/blanks if no docstring)
"""

import re
import sys
from pathlib import Path

TARGET = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("spellcaster_portal.py")
if not TARGET.exists():
    print(f"[normalize_header] File not found: {TARGET}")
    raise SystemExit(1)

lines = TARGET.read_text(encoding="utf-8", errors="ignore").splitlines(True)

future_re = re.compile(r"^\s*from\s+__future__\s+import\s+annotations\s*$")

# Remove all future-import occurrences anywhere
lines_wo_future = [ln for ln in lines if not future_re.match(ln.strip())]

i = 0
out = []

# Shebang
if i < len(lines_wo_future) and lines_wo_future[i].startswith("#!"):
    out.append(lines_wo_future[i]); i += 1

# Encoding cookie in first two lines (after shebang if present)
enc_re = re.compile(r"^#.*coding[:=]\s*[-\w.]+")
if i < len(lines_wo_future) and enc_re.match(lines_wo_future[i]):
    out.append(lines_wo_future[i]); i += 1
elif i + 1 < len(lines_wo_future) and enc_re.match(lines_wo_future[i + 1]):
    out.append(lines_wo_future[i]); i += 1
    out.append(lines_wo_future[i]); i += 1

# Preserve leading blank/comment lines
while i < len(lines_wo_future) and (lines_wo_future[i].strip() == "" or lines_wo_future[i].lstrip().startswith("#")):
    out.append(lines_wo_future[i]); i += 1

def starts_docstring(s: str) -> bool:
    ss = s.lstrip()
    return ss.startswith('"""') or ss.startswith("'''")
def count_triples(s: str, q: str) -> int:
    return s.count(q)

# Module docstring
if i < len(lines_wo_future) and starts_docstring(lines_wo_future[i]):
    first = lines_wo_future[i]
    q = '"""' if first.lstrip().startswith('"""') else "'''"
    out.append(first); i += 1
    # single-line docstring?
    if count_triples(first, q) >= 2:
        pass
    else:
        while i < len(lines_wo_future):
            out.append(lines_wo_future[i])
            if q in lines_wo_future[i]:
                i += 1
                break
            i += 1

# Insert future import NOW (legal position)
# Ensure a blank line before/after for readability
if len(out) > 0 and not out[-1].endswith("\n"):
    out[-1] = out[-1] + "\n"
out.append("from __future__ import annotations\n")
# keep a blank line after, unless already blank
if i < len(lines_wo_future) and lines_wo_future[i].strip() != "":
    out.append("\n")

# Append the rest unchanged
out.extend(lines_wo_future[i:])

TARGET.write_text("".join(out), encoding="utf-8")
print(f"[normalize_header] Normalized header in {TARGET}")
