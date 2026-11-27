#!/usr/bin/env python3
"""Lint a skill directory against the best-practice hard rules.

Usage: python3 scripts/lint_skill.py <skill-dir> [--portable] [--evals-dir DIR]
  --portable   unknown frontmatter keys are errors (claude.ai / Skills API reject them).
  --evals-dir  folder holding evals.json and trigger_evals.json (default: <skill-dir>/evals).
Prints JSON {"errors": [...], "warnings": [...], "stats": {...}} on stdout.
Exit codes: 0 clean or warnings only, 1 lint errors, 2 bad input or a file that could not be read (message on stderr).
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
MAX_CHARS = 1_000_000  # read at most this much of any file; a skill file is far smaller
# Folders under scripts/ that hold code the skill's author did not write, or files that are wrong on purpose.
SKIP_DIRS = {"node_modules", "venv", "vendor", "third_party", "__pycache__", "fixtures", "dist", "build"}
SIDE_EFFECT = re.compile(r"\b((deploy|publish|push|send|delete|drop|merge|email)(e?s|ing)?|post(s|ing)? to)\b", re.I)
BOUNDARY = re.compile(r"\bnot for\b|\bdo not use\b|\bnot when\b", re.I)
HARNESS_TOOLS = re.compile(r"\b(StrReplace|Bash\(|the (Read|Write|Grep|Glob|Edit) tool|activate_skill)\b")
# The two patterns below are written so that this file does not match them.
# Calls that change files on this machine or in the local repository. A waiver comment can cover these.
LOCAL_CHANGE = re.compile(
    r"os\.(remove|unlink|rmdir|removedirs|replace)\(|shutil\.(rmtree|move)\(|\.unlink\(|\brm\s+-[a-z]*[rf]"
    r"|^\s*rm\s+[\"$\w./~-]|[\"']rm[\"'],|\bgit\s+(merge|clean|reset\s+--hard)\b|[\"']git[\"'],[^\n]*[\"'](merge|clean)[\"']", re.M)
# Calls that change something outside this machine or the repository. A waiver does not cover these.
REMOTE_CHANGE = re.compile(
    r"\bgit\s+push\b|[\"']git[\"'],[^\n]*[\"']push[\"']|requests\.(post|put|patch|delete)\("
    r"|method=[\"'](POST|PUT|PATCH|DELETE)[\"']|\bsmtplib\b|\bcurl\b[^\n]*-X\s*(POST|PUT|PATCH|DELETE)"
    r"|\b(kubectl|terraform)\s+(apply|delete|destroy)|\bDROP\s+TABLE|\bDELETE\s+FROM|\bTRUNCATE\s+\w"
    r"|\b(npm|cargo)\s+publish|\btwine\s+upload|\bgh\s+pr\s+merge|\bdocker\s+push|\baws\s+s3\s+rm")
# The flag counts only where the script defines or tests it, not where a string or comment mentions it.
DRY_RUN_FLAG = re.compile(r"(add_argument|option|includes)\([^)\n]*--dry-run|--dry-run[|)]|==?\s*[\"']?--dry-run|argv[^\n]*--dry-run")
# A comment (whole line, or after code) "lint: no-dry-run: <reason of three words or more>". Group 1 is the code before it.
WAIVER = re.compile(r"(?m)^(.*?)(?:#|//)[ \t]*lint: no-dry-run:[ \t]*\S+(?:[ \t]+\S+){2,}")
COMMENT_LINE = re.compile(r"(?m)^\s*(#|//).*$")
DOCSTRING = re.compile(r"(?m)^[ \t]*[rRbBuU]?(\"\"\"|''')[\s\S]*?\1")
# A Markdown link target (its #fragment and "title" are left out), or a references/, scripts/ or assets/ path
# anywhere in the text (so inside a command too), also behind a ${...SKILL...}/ variable.
LINK = re.compile(r"\]\(([^)#\s]+)(?:#[^)\s]*)?(?:\s+\"[^\"]*\")?\)"
                  r"|(?:\$\{?\w*SKILL\w*\}?/|(?<![\w./<>\\-]))((?:references|scripts|assets)[/\\][^`\s)\"',;#]*[^`\s)\"',;#.:?!*\]}|>])")


def read(p: Path, errors: str = "strict") -> str:
    try:
        with p.open(encoding="utf-8", errors=errors) as f:
            return f.read(MAX_CHARS)
    except UnicodeDecodeError as e:
        raise OSError(f"{p}: not UTF-8 ({e.reason} at byte {e.start})") from None


def scalar(val: str) -> str:
    if val in (">", ">-", ">+", "|", "|-", "|+"):
        return ""
    if len(val) > 1 and val[0] == val[-1] == '"':
        try:
            return str(json.loads(val))
        except ValueError:
            return val[1:-1]
    if len(val) > 1 and val[0] == val[-1] == "'":
        return val[1:-1].replace("''", "'")
    return re.sub(r"\s+#.*$", "", val)  # an unquoted value ends at a YAML comment


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
            key = m.group(1)
            fm[key] = scalar(m.group(2).strip())
        elif key and line.startswith((" ", "\t")):
            fm[key] = (fm[key] + " " + line.strip()).strip()
    return fm, text[end + 4:].lstrip("\n")


def lint(skill: Path, portable: bool, evals_dir: Path | None = None) -> dict:
    errors: list[str] = []
    warns: list[str] = []
    md = skill / "SKILL.md"
    if not md.is_file():
        return {"errors": [f"missing {md}"], "warnings": [], "stats": {}}
    parsed = parse_frontmatter(read(md).lstrip("\ufeff"))
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
        if re.match(r"(I|You)\s", desc) or re.search(r"\b(I can|you can)\b", desc, re.I):
            warns.append("description should be third person ('Processes X...'), not 'I/You can'")
        if not re.search(r"\buse (this )?(skill )?(when|for)\b|\btriggers? on\b", desc, re.I):
            warns.append("description lacks a 'Use when ...' trigger clause")
        if not BOUNDARY.search(desc):
            warns.append("description has no 'Not for ...' boundary (add one if a near-miss skill exists)")
        if re.search(r"</?[A-Za-z][^>]*>", desc):
            warns.append("description holds an XML or HTML tag; some hosts reject it")
    if len(fm.get("compatibility", "")) > 500:
        errors.append(f"compatibility is {len(fm['compatibility'])} chars (max 500)")

    for k in fm.keys() - SPEC_KEYS:
        msg = f"frontmatter key {k!r} is not in the open spec" + ("" if k in KNOWN_HOST_KEYS else " and not a known host key")
        (errors if portable else warns).append(msg)

    lines = len(body.rstrip("\n").splitlines())
    tokens = len(body) // 4
    if lines >= 500:
        errors.append(f"SKILL.md body is {lines} lines (keep < 500; move detail to references/)")
    if tokens > 5000:
        warns.append(f"SKILL.md body is ~{tokens} tokens (aim < 5000)")
    for m in HARNESS_TOOLS.finditer(body):
        warns.append(f"harness-specific tool name {m.group(0)!r}; say 'read the file' / 'run <cmd>'")
    if re.search(r"\bTODO\b", body):
        warns.append("SKILL.md still holds a TODO placeholder")

    refs = sorted(p for p in (skill / "references").glob("*.md") if p.is_file()) if (skill / "references").is_dir() else []
    docs = [(md, body)] + [(r, read(r)) for r in refs]
    if any("\\" in (m.group(1) or m.group(2)) for _, text in docs for m in LINK.finditer(text)):
        errors.append("backslash in a file path; use forward slashes")
    for doc, text in docs:
        where = "" if doc == md else f" (named in references/{doc.name})"
        for m in LINK.finditer(text):
            ref = m.group(1) or m.group(2)
            if re.match(r"[a-z]+://|mailto:", ref) or re.search(r"[<*{$\\]", ref):
                continue
            # a Markdown link is relative to the file that holds it, a bare path to the skill root
            target = (doc.parent if m.group(1) else skill) / ref
            if ref.startswith("/") or ".." in Path(ref).parts:
                warns.append(f"path {ref!r} is not relative to the skill root{where}")
            elif not target.exists():
                if m.group(1) or target.parent.is_dir():
                    errors.append(f"referenced file does not exist: {ref}{where}")
                else:  # the skill has no such folder, so this may be a path in the user's project
                    warns.append(f"{ref}{where} is not in this skill, which has no {target.parent.relative_to(skill).as_posix()}/ folder; "
                                 f"add the file, or write a path in the user's project as <project>/{ref}")
            elif where and target.suffix == ".md" and target.relative_to(skill).as_posix() not in body:
                warns.append(f"references/{doc.name} names {ref}, which SKILL.md never names; keep references one level deep")

    for ref in refs:
        if f"references/{ref.name}" not in body:
            warns.append(f"references/{ref.name} is never named in SKILL.md; give it a load condition ('read X if Y')")

    # rglob, so the modules behind an entry script are checked too; only a top-level script needs its own --help
    for script in sorted((skill / "scripts").rglob("*")) if (skill / "scripts").is_dir() else []:
        rel = script.relative_to(skill)
        if script.suffix not in {".py", ".sh", ".js", ".ts"} or any(p in SKIP_DIRS or p.startswith(".") for p in rel.parts[:-1]):
            continue
        name = rel.as_posix()
        if script.is_symlink() or not script.is_file():
            warns.append(f"{name}: a symlink or not a regular file; not checked")
            continue
        raw = read(script, "replace")
        code = COMMENT_LINE.sub("", raw)
        src = DOCSTRING.sub("", code) if script.suffix == ".py" else code
        is_test = script.stem.startswith("test_") or script.stem in {"selftest", "self_test"} or "tests" in rel.parts
        if not is_test and script.parent.name == "scripts" and "--help" not in code and "argparse" not in code and "usage" not in code.lower():
            warns.append(f"{name}: no --help/usage found")
        if not is_test and not DRY_RUN_FLAG.search(src):
            remote, local = REMOTE_CHANGE.search(src), LOCAL_CHANGE.search(src)
            if remote:
                warns.append(f"{name}: changes something outside this machine ({remote.group(0).strip()!r}) but has no --dry-run flag; "
                             "add one (a 'lint: no-dry-run:' comment does not cover this)")
            # a comment "lint: no-dry-run: <reason>" in the file says a person judged the local changes safe without one
            elif local and not any(p.count('"') % 2 == 0 and p.count("'") % 2 == 0 for p in WAIVER.findall(raw)):
                warns.append(f"{name}: changes things ({local.group(0).strip()!r}) but has no --dry-run flag; add one, or a comment "
                             "'lint: no-dry-run: <reason, three words or more>' if a preview would add no safety")
        if (script.suffix == ".py" and re.search(r"(?<![\w.])input\(|getpass\.getpass\(", src)) or \
                (script.suffix == ".sh" and re.search(r"\bread\s+(-\w+\s+)*-\w*p", src)):
            errors.append(f"{name}: interactive prompt; take flags/env/stdin instead")

    if SIDE_EFFECT.search(BOUNDARY.split(desc)[0]) and fm.get("disable-model-invocation", "").lower() != "true":
        warns.append("description mentions a side effect; make the skill user-invoked only on each target host "
                     "(look up each host's switch; it is host-specific, so not a key for a --portable skill)")

    for fname in ("evals.json", "trigger_evals.json"):
        f, p = f"evals/{fname}", (evals_dir or skill / "evals") / fname
        if not p.is_file():
            warns.append(f"missing {f}")
            continue
        try:
            data = json.loads(read(p))
        except (json.JSONDecodeError, RecursionError) as e:
            errors.append(f"{f}: invalid JSON ({e})")
            continue
        if fname == "evals.json":
            if not isinstance(data, dict) or not isinstance(data.get("evals"), list):
                errors.append(f"{f}: must be a JSON object with an \"evals\" array")
        elif not isinstance(data, list) or not all(
                isinstance(q, dict) and isinstance(q.get("query"), str) and isinstance(q.get("should_trigger"), bool) for q in data):
            errors.append(f"{f}: must be a JSON array of {{\"query\": string, \"should_trigger\": true|false}} objects")
        else:
            pos = sum(1 for q in data if q["should_trigger"])
            if pos < 8 or len(data) - pos < 8:
                warns.append(f"{f}: {pos} positive / {len(data) - pos} negative queries (aim 8-10 each, negatives = near-misses)")

    return {"errors": errors, "warnings": warns, "stats": {"body_lines": lines, "body_tokens_est": tokens, "description_chars": len(desc)}}


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("skill_dir", type=Path)
    ap.add_argument("--portable", action="store_true")
    ap.add_argument("--evals-dir", type=Path)
    args = ap.parse_args()
    for d in (args.skill_dir, args.evals_dir):
        if d and not d.is_dir():
            print(f"not a directory: {d}", file=sys.stderr)
            return 2
    try:
        result = lint(args.skill_dir, args.portable, args.evals_dir)
    except OSError as e:
        print(f"could not lint: {e}", file=sys.stderr)
        return 2
    print(json.dumps(result, indent=2))
    return 1 if result["errors"] else 0


if __name__ == "__main__":
    sys.exit(main())
