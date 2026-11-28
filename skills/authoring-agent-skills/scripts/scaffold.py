#!/usr/bin/env python3
"""Create a new skill (optionally wrapped in a plugin) from assets/ templates.

Usage:
  python3 scripts/scaffold.py --name pdf-forms --dest .agents/skills --description "Fills PDF forms ... Use when ..."
  python3 scripts/scaffold.py --name pdf-forms --dest plugins --description "..." --plugin   # plugins/pdf-forms/{manifests,skills/pdf-forms}
Flags: --dry-run (list files, write nothing), --force (overwrite existing files).
Prints JSON {"created" | "would_create": [...], "skill_dir": "..."}. Errors go to stderr. Exit codes: 0 ok, 1 files exist (no --force), 2 bad input or a target that cannot be written.
The run checks every file and folder it is to write before it writes the first one, so on exit 1 or 2 nothing was
written, and --dry-run exits with the same code and message as the run without it would. (A target that changes
between the check and the write can still stop a run part way; that is exit 2 too.)
Nothing is written through a symlink inside the new folder: if <dest>/<name>, or a folder or file to be written in it, is a
symlink, the run is refused, also with --force. --dest itself may be a symlink or lie under one (a linked skills folder).
"""
from __future__ import annotations

import argparse
import json
import os
import re
import stat
import sys
from pathlib import Path

ASSETS = Path(__file__).resolve().parent.parent / "assets"


def render(src: Path, values: dict[str, str]) -> str:
    text = src.read_text(encoding="utf-8")
    for k, v in values.items():
        text = text.replace("{{" + k + "}}", v)
    return text


def kind(p: Path) -> str:
    """"link", "dir" or "file" (anything else that is there); "" for a path that is not there. Does not follow a symlink."""
    try:
        mode = os.lstat(p).st_mode
    except (FileNotFoundError, NotADirectoryError):
        return ""
    return "link" if stat.S_ISLNK(mode) else "dir" if stat.S_ISDIR(mode) else "file"


def blocked(p: Path) -> str:
    """Why p, which is not there, cannot be created; "" when it can. Looks at the nearest folder above it that exists."""
    p = p.parent
    while not kind(p):
        p = p.parent
    if not stat.S_ISDIR(os.stat(p).st_mode):
        return f"{p} is not a folder"
    return "" if os.access(p, os.W_OK | os.X_OK) else f"no permission to write in {p}"


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
    if not 0 < len(args.description) <= 1024 or any(ord(c) < 32 or ord(c) == 127 for c in args.description):
        print("--description must be 1-1024 chars on one line, with no control characters", file=sys.stderr)
        return 2
    # NEL, LINE SEPARATOR and PARAGRAPH SEPARATOR are line breaks to some YAML readers; a surrogate is how Python
    # carries a byte of the argument that is not valid UTF-8, and it cannot be written to a file
    if any(ord(c) in (0x85, 0x2028, 0x2029) or 0xD800 <= ord(c) <= 0xDFFF for c in args.description):
        print("--description must be valid UTF-8 with no line-separator character (U+0085, U+2028, U+2029)", file=sys.stderr)
        return 2

    values = {"name": args.name, "title": args.name.replace("-", " ").title(),
              # escaped once for both targets: a JSON string and a double-quoted YAML scalar take the same escapes
              "description": json.dumps(args.description, ensure_ascii=False)[1:-1]}
    root = args.dest / args.name
    skill_dir = root / "skills" / args.name if args.plugin else root
    # Templates end in .tmpl so harnesses never discover assets/skill/SKILL.md as a nested skill.
    plan = [(p, skill_dir / p.relative_to(ASSETS / "skill").with_suffix("") if p.suffix == ".tmpl"
             else skill_dir / p.relative_to(ASSETS / "skill"))
            for p in (ASSETS / "skill").rglob("*") if p.is_file()]
    if args.plugin:
        plan += [(p, root / p.relative_to(ASSETS / "plugin")) for p in (ASSETS / "plugin").rglob("*") if p.is_file()]

    # Everything that can stop the run is looked up before the first write, and in a --dry-run too, so a run that
    # cannot write every file writes none, and --dry-run reports the same refusal as the real run.
    folders = [skill_dir / d for d in ("references", "scripts", "learnings/proposed")]
    try:
        links = sorted({str(p) for _, d in plan for p in (d, *d.parents) if (p == root or root in p.parents) and kind(p) == "link"})
        if links:
            print(json.dumps({"error": "refusing to write through a symlink", "symlinks": links}), file=sys.stderr)
            return 2
        problems = set()
        for _, d in plan:
            k = kind(d)
            problems.add(f"{d} is a folder; a file is to be written there" if k == "dir"
                         else f"no permission to overwrite {d}" if k and args.force and not os.access(d, os.W_OK)
                         else "" if k else blocked(d))
        for d in folders:
            k = kind(d)
            problems.add(f"{d} is a file; a folder is needed there" if k == "file" else "" if k else blocked(d))
        if problems - {""}:
            print(json.dumps({"error": "cannot write", "problems": sorted(problems - {""})}), file=sys.stderr)
            return 2
        existing = [str(d) for _, d in plan if kind(d)]
        if existing and not args.force:
            print(json.dumps({"error": "files exist; re-run with --force to overwrite", "existing": existing}), file=sys.stderr)
            return 1
        texts = [(dst, render(src, values)) for src, dst in plan]  # every template is read before any file is written
        if not args.dry_run:
            for dst, text in texts:
                dst.parent.mkdir(parents=True, exist_ok=True)
                dst.write_text(text, encoding="utf-8")
            for d in folders:
                d.mkdir(parents=True, exist_ok=True)
    except OSError as e:  # also a name the file system refuses, or a folder that may not be looked into
        print(f"cannot write: {e}", file=sys.stderr)
        return 2
    print(json.dumps({"created" if not args.dry_run else "would_create": [str(d) for _, d in plan],
                      "skill_dir": str(skill_dir)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
