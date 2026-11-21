#!/usr/bin/env python3
"""Create a new skill (optionally wrapped in a plugin) from assets/ templates.

Usage:
  python3 scripts/scaffold.py --name pdf-forms --dest .agents/skills --description "Fills PDF forms ... Use when ..."
  python3 scripts/scaffold.py --name pdf-forms --dest plugins --description "..." --plugin   # plugins/pdf-forms/{manifests,skills/pdf-forms}
Flags: --dry-run (list files, write nothing), --force (overwrite existing files).
Prints JSON {"created" | "would_create": [...], "skill_dir": "..."}. Errors go to stderr. Exit codes: 0 ok, 1 files exist (no --force), 2 bad input.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def render(src: Path, values: dict[str, str]) -> str:
    text = src.read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--name", required=True)
    ap.add_argument("--dest", required=True, type=Path)
    ap.add_argument("--description", required=True)
    ap.add_argument("--plugin", action="store_true")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--force", action="store_true")
    args = ap.parse_args()
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", args.name) or len(args.name) > 64:
        print("--name must be 1-64 chars of lowercase letters/digits/single hyphens", file=sys.stderr)
        return 2
    if not 0 < len(args.description) <= 1024:
        print("--description must be 1-1024 chars", file=sys.stderr)
        return 2

    values = {"name": args.name, "title": args.name.replace("-", " ").title(),
              "description": args.description.replace('"', '\\"')}
    root = args.dest / args.name
    skill_dir = root / "skills" / args.name if args.plugin else root
    # Templates end in .tmpl so harnesses never discover assets/skill/SKILL.md as a nested skill.
    plan = [(p, skill_dir / p.relative_to(ASSETS / "skill").with_suffix("") if p.suffix == ".tmpl"
             else skill_dir / p.relative_to(ASSETS / "skill"))
            for p in (ASSETS / "skill").rglob("*") if p.is_file()]
    if args.plugin:
        plan += [(p, root / p.relative_to(ASSETS / "plugin")) for p in (ASSETS / "plugin").rglob("*") if p.is_file()]

    existing = [str(d) for _, d in plan if d.exists()]
    if existing and not args.force:
        print(json.dumps({"error": "files exist; re-run with --force to overwrite", "existing": existing}), file=sys.stderr)
        return 1
    if not args.dry_run:
        for src, dst in plan:
            dst.parent.mkdir(parents=True, exist_ok=True)
            dst.write_text(render(src, values), encoding="utf-8")
        for d in ("references", "scripts", "learnings/proposed"):
            (skill_dir / d).mkdir(parents=True, exist_ok=True)
    print(json.dumps({"created" if not args.dry_run else "would_create": [str(d) for _, d in plan],
                      "skill_dir": str(skill_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
