#!/usr/bin/env python3
"""Size check for this skill. Usage: python3 scripts/check_size.py  (exit 0 = SKILL.md is within the cap)."""
import sys
from pathlib import Path

MAX_LINES = 20  # SKILL.md is loaded on every run. Raising this needs the owner's agreement, and the reason goes here.
lines = len((Path(__file__).resolve().parent.parent / "SKILL.md").read_text(encoding="utf-8").splitlines())
print(f"SKILL.md: {lines} lines (cap {MAX_LINES})")
sys.exit(0 if lines <= MAX_LINES else 1)
