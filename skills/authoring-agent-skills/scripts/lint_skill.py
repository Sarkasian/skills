#!/usr/bin/env python3
"""Lint a skill directory against the best-practice hard rules.

Usage: python3 scripts/lint_skill.py <skill-dir> [--portable] [--evals-dir DIR]
  --portable   unknown frontmatter keys are errors (claude.ai / Skills API reject them).
  --evals-dir  folder holding evals.json and trigger_evals.json (default: <skill-dir>/evals).
Prints JSON {"errors": [...], "warnings": [...], "stats": {...}} on stdout.
Exit codes: 0 clean or warnings only, 1 errors, 2 bad input.
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

SPEC_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
KNOWN_HOST_KEYS = {"disable-model-invocation", "user-invocable", "paths", "when_to_use", "context",
                   "agent", "model", "effort", "hooks", "argument-hint", "disallowed-tools"}
SIDE_EFFECT = re.compile(r"\b(deploy|publish|push|send|delete|drop|merge|post to|email)\b", re.I)
HARNESS_TOOLS = re.compile(r"\b(StrReplace|Bash\(|the (Read|Write|Grep|Glob|Edit) tool|activate_skill)\b")
# A Markdown link target, or a references/, scripts/ or assets/ path anywhere in the text (so inside a command too).
# Calls that change something outside the script. Written so that this file does not match its own patterns.
SIDE_EFFECT_CALL = re.compile(
    r"os\.(remove|unlink|rmdir)\(|shutil\.rmtree\(|\.unlink\(|\brm\s+-[a-z]*[rf]|\bgit\s+(push|merge|reset\s+--hard)"
    r"|requests\.(post|put|patch|delete)\(|\bsmtp(?:lib)\b|\bcurl\b[^\n]*-X\s*(POST|PUT|PATCH|DELETE)"
    r"|\b(kubectl|terraform)\s+(apply|delete|destroy)|\bDROP\s+TABLE|\bDELETE\s+FROM|\b(npm|cargo)\s+publish|\btwine\s+upload")
COMMENT_LINE = re.compile(r"(?m)^\s*(#|//).*$")
LINK = re.compile(r"\]\(([^)#\s]+)\)|(?<![\w./<>-])((?:references|scripts|assets)/[^`\s)\"',;]*[^`\s)\"',;.:])")


def parse_frontmatter(text: str) -> tuple[dict[str, str], str] | None:
    """Minimal YAML subset: top-level scalars, quoted strings, block scalars, nested maps as raw text."""
    if not text.startswith("---\n"):
        return None
    end = text.find("\n---", 4)
    if end == -1:
        return None
    fm: dict[str, str] = {}
    key = None
    for line in text[4:end].splitlines():
        m = re.match(r"^([A-Za-z0-9_-]+):\s*(.*)$", line)
        if m:
            key, val = m.group(1), m.group(2).strip()
            fm[key] = "" if val in (">", ">-", "|", "|-") else val.strip("'\"")
        elif key and line.startswith((" ", "\t")):
            fm[key] = (fm[key] + " " + line.strip()).strip()
    return fm, text[end + 4:].lstrip("\n")


def lint(skill: Path, portable: bool, evals_dir: Path | None = None) -> dict:
    errors: list[str] = []
    warns: list[str] = []
    md = skill / "SKILL.md"
    if not md.is_file():
        return {"errors": [f"missing {md}"], "warnings": [], "stats": {}}
    text = md.read_text(encoding="utf-8")
    parsed = parse_frontmatter(text)
    if parsed is None:
        return {"errors": ["SKILL.md has no '---' frontmatter block"], "warnings": [], "stats": {}}
    fm, body = parsed

    name, desc = fm.get("name", ""), fm.get("description", "")
    if not re.fullmatch(r"[a-z0-9]+(-[a-z0-9]+)*", name) or len(name) > 64:
        errors.append(f"name {name!r}: 1-64 chars, lowercase letters/digits/single hyphens")
    if name != skill.resolve().name:
        errors.append(f"name {name!r} must match directory {skill.resolve().name!r}")
    if re.search(r"claude|anthropic|helper|utils", name):
        warns.append(f"name {name!r} uses a reserved or vague word")
    if not desc:
        errors.append("description is empty")
    elif len(desc) > 1024:
        errors.append(f"description is {len(desc)} chars (max 1024)")
    else:
        if len(desc) > 400:
            warns.append(f"description is {len(desc)} chars; listing budgets truncate, aim for <=400 with triggers first")
        if re.match(r"(I|You)\b", desc) or re.search(r"\b(I can|you can)\b", desc, re.I):
            warns.append("description should be third person ('Processes X...'), not 'I/You can'")
        if not re.search(r"\buse (this )?(skill )?(when|for)\b|\btriggers? on\b", desc, re.I):
            warns.append("description lacks a 'Use when ...' trigger clause")
        if not re.search(r"\bnot for\b|\bdo not use\b|\bnot when\b", desc, re.I):
            warns.append("description has no 'Not for ...' boundary (add one if a near-miss skill exists)")

    for k in fm.keys() - SPEC_KEYS:
        msg = f"frontmatter key {k!r} is not in the open spec" + ("" if k in KNOWN_HOST_KEYS else " and not a known host key")
        (errors if portable else warns).append(msg)

    lines = body.count("\n") + 1
    tokens = len(body) // 4
    if lines >= 500:
        errors.append(f"SKILL.md body is {lines} lines (keep < 500; move detail to references/)")
    if tokens > 5000:
        warns.append(f"SKILL.md body is ~{tokens} tokens (aim < 5000)")
    if "\\" in "".join(m.group(1) or m.group(2) for m in LINK.finditer(body)):
        errors.append("backslash in a file path; use forward slashes")
    for m in HARNESS_TOOLS.finditer(body):
        warns.append(f"harness-specific tool name {m.group(0)!r}; say 'read the file' / 'run <cmd>'")

    for m in LINK.finditer(body):
        ref = (m.group(1) or m.group(2)).split(" ")[0]
        if re.match(r"[a-z]+://|mailto:", ref) or "<" in ref or "*" in ref:
            continue
        target = skill / ref
        if ref.startswith("/") or ".." in Path(ref).parts:
            warns.append(f"path {ref!r} is not relative to the skill root")
        elif not target.exists():
            errors.append(f"referenced file does not exist: {ref}")
        elif target.suffix == ".md" and target.parent != skill:
            nested = [x for x in LINK.findall(target.read_text(encoding="utf-8")) if x[0].endswith(".md") and "://" not in x[0]]
            if nested:
                warns.append(f"{ref} links to further .md files; keep references one level deep")

    for ref in sorted((skill / "references").glob("*.md")) if (skill / "references").is_dir() else []:
        if f"references/{ref.name}" not in body:
            warns.append(f"references/{ref.name} is never named in SKILL.md; give it a load condition ('read X if Y')")

    # rglob, so the modules behind an entry script are checked too; only a top-level script needs its own --help
    for script in sorted((skill / "scripts").rglob("*")) if (skill / "scripts").is_dir() else []:
        if script.suffix in {".py", ".sh", ".js", ".ts"}:
            name = script.relative_to(skill).as_posix()
            raw = script.read_text(encoding="utf-8", errors="replace")
            src = COMMENT_LINE.sub("", raw)
            is_test = script.stem.startswith("test_") or script.stem in {"selftest", "self_test"}
            if not is_test and script.parent.name == "scripts" and "--help" not in src and "argparse" not in src and "usage" not in src.lower():
                warns.append(f"{name}: no --help/usage found")
            m = SIDE_EFFECT_CALL.search(src)
            # a comment "lint: no-dry-run: <reason>" in the file says a person judged the changes safe without one
            if m and "--dry-run" not in src and not re.search(r"lint: no-dry" + r"-run:[ \t]*\w", raw):
                warns.append(f"{name}: changes things ({m.group(0).strip()!r}) but has no --dry" + "-run flag; add one, "
                             "or a comment 'lint: no-dry" + "-run: <reason>' if a preview would add no safety")
            if re.search(r"(?<![\w.])input\(|\bread\s+-p\s", src):
                errors.append(f"{name}: interactive prompt; take flags/env/stdin instead")

    if SIDE_EFFECT.search(desc) and fm.get("disable-model-invocation", "").lower() != "true":
        warns.append("description mentions a side effect; consider disable-model-invocation: true (user-invoked only)")

    for f in ("evals/evals.json", "evals/trigger_evals.json"):
        p = (evals_dir or skill / "evals") / Path(f).name
        if not p.is_file():
            warns.append(f"missing {f}")
            continue
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except json.JSONDecodeError as e:
            errors.append(f"{f}: invalid JSON ({e})")
            continue
        if f.endswith("trigger_evals.json"):
            if not isinstance(data, list) or not all(isinstance(q, dict) for q in data):
                errors.append(f"{f}: must be a JSON array of {{\"query\", \"should_trigger\"}} objects")
                continue
            pos = sum(1 for q in data if q.get("should_trigger") is True)
            neg = sum(1 for q in data if q.get("should_trigger") is False)
            if pos < 8 or neg < 8:
                warns.append(f"{f}: {pos} positive / {neg} negative queries (aim 8-10 each, negatives = near-misses)")

    return {"errors": errors, "warnings": warns, "stats": {"body_lines": lines, "body_tokens_est": tokens, "description_chars": len(desc)}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("skill_dir", type=Path)
    ap.add_argument("--portable", action="store_true")
    ap.add_argument("--evals-dir", type=Path)
    args = ap.parse_args()
    if not args.skill_dir.is_dir():
        print(f"not a directory: {args.skill_dir}", file=sys.stderr)
        return 2
    result = lint(args.skill_dir, args.portable, args.evals_dir)
    print(json.dumps(result, indent=2))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
