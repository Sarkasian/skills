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
import io
import json
import os
import re
import sys
import tokenize
from pathlib import Path

SPEC_KEYS = {"name", "description", "license", "compatibility", "metadata", "allowed-tools"}
KNOWN_HOST_KEYS = {"disable-model-invocation", "user-invocable", "paths", "when_to_use", "context",
                   "agent", "model", "effort", "hooks", "argument-hint", "disallowed-tools"}
MAX_CHARS = 1_000_000  # read at most this much of any file; a skill file is far smaller
MAX_LINE = 5000  # a .py file with a longer line is not tokenized: the tokenizer of some Python versions is slow on one
# Folders under scripts/ that hold code the skill's author did not write, or files that are wrong on purpose.
SKIP_DIRS = {"node_modules", "venv", "vendor", "third_party", "__pycache__", "fixtures", "dist", "build"}
SIDE_EFFECT = re.compile(r"\b((deploy|publish|push|send|delete|drop|merge|email)(e?s|ing)?|post(s|ing)? to)\b", re.I)
BOUNDARY = re.compile(r"\bnot for\b|\bdo not use\b|\bnot when\b", re.I)
HARNESS_TOOLS = re.compile(r"\b(StrReplace|Bash\(|the (Read|Write|Grep|Glob|Edit) tool|activate_skill)\b")
# How a script is read. A .py file goes through the standard tokenizer (read_python below): its comments and
# docstrings are left out, and a string literal is told apart from code. A .sh, .js or .ts file, and a .py file that
# does not tokenize, is read with the patterns marked "line rules": whole-line comments are dropped and everything
# else counts as code, so there a comment after code or a string can still match.
# The patterns below are written so that this file does not match them. Each one is bounded: a gap or a run of
# white space between two parts has a fixed maximum length, and no open-ended repeat sits inside another.
S = r"\s{0,80}"  # white space between two arguments, newlines included
Q = "[\"']"
D = "[\"'`]"
# Calls that change files on this machine or in the local repository. A waiver comment can cover these.
# "merge" must end the word: git merge-base and its like only read.
LOCAL_CHANGE = re.compile(
    r"os\.(remove|unlink|rmdir|removedirs|replace)\(|shutil\.(rmtree|move)\(|\.unlink\(|\brm\s+-[a-z]*[rf]"
    r"|^[ \t]*rm\s+[\"$\w./~-]|[\"']rm[\"'],|\bgit\s+(merge|clean|reset\s+--hard)(?![\w-])"
    r"|\bgit\s+worktree\s+remove\b|\bgit\s+branch\s+-D\b|\bgit\s+checkout\s[^\n;|&)]{0,200}?(?<=\s)--(?=[\s\"']|$)", re.M)
# Calls that change something outside this machine or the repository. A waiver does not cover these.
REMOTE_CHANGE = re.compile(
    r"\bgit\s+push\b|requests\.(post|put|patch|delete)\("
    r"|method=[\"'](POST|PUT|PATCH|DELETE)[\"']|\bsmtplib\b|\bcurl\b[^\n]{0,400}-X\s{0,10}(POST|PUT|PATCH|DELETE)"
    r"|\b(kubectl|terraform)\s+(apply|delete|destroy)|\bDROP\s+TABLE|\bDELETE\s+FROM|\bTRUNCATE\s+\w"
    r"|\b(npm|cargo)\s+publish|\btwine\s+upload|\bgh\s+pr\s+merge|\bdocker\s+push|\baws\s+s3\s+rm")
# A git command given as arguments. It is read from a list or tuple that holds the string "git", or from a call to
# a git helper: a function named git, with nothing but the words below around it (run_git, _git_out, gitCmd; not
# git_log, github_events). The subcommand is the first string after "git" (in a helper: the first string) that is
# not an option; the argument after -C, -c, --git-dir, --work-tree or --namespace is that option's value.
HELPER = (r"_{0,2}(?:(?:run|call|exec|do|sh|check|try)_?){0,2}git"
          r"(?:_?(?:run|output|out|command|cmd|call|exec|check|lines|text|quiet|stdout|capture|ok)){0,2}_{0,2}")
GIT_HELPER = re.compile(HELPER, re.I)
GIT_VALUE_OPTIONS = {"-C", "-c", "--git-dir", "--work-tree", "--namespace"}
# Line rules for the same: after "git" (and the [ of a list that follows it, as in execFile("git", [...])), or after
# the helper's bracket, up to six arguments that are bare names or options, then the subcommand. A string that is not an option ends the search, so "git", "log", "push" is no push.
GIT_ARGS = (r"(?:" + Q + "git" + Q + S + "," + S + r"(?:\[" + S + r")?|(?i:(?<![\w$])" + HELPER + r")\(" + S + r"\[?" + S + ")"
            r"(?:(?:[\w.$]{1,80}|" + Q + r"-[^\"'\n]{0,80}" + Q + ")" + S + "," + S + "){0,6}")
REMOTE_ARGS = re.compile(GIT_ARGS + Q + "push" + Q)
LOCAL_ARGS = re.compile(
    GIT_ARGS + "(?:" + Q + "(?:merge|clean)" + Q + "|" + Q + "reset" + Q + S + "," + S + Q + "--hard" + Q
    + "|" + Q + "worktree" + Q + S + "," + S + Q + "remove" + Q + "|" + Q + "branch" + Q + S + "," + S + Q + "-D" + Q
    + "|" + Q + "checkout" + Q + "(?:" + S + "," + S + r"(?:[\w.$]{1,80}|" + Q + r"[^\"'\n]{0,80}" + Q + ")){0,6}?"
    + S + "," + S + Q + "--" + Q + ")")
# Where --dry-run counts as a flag the script has. In a .py file (read_python) it is a string literal that holds
# the flag and nothing but flags ("--dry-run", "-n, --dry-run", "--dry-run/--no-dry-run") and stands in one of these places:
#   1. a positional argument of add_argument(...), add_option(...), option(...) or Option(...);
#   2. next to == or !=, or before "in" or "not in" ("--dry-run" in args);
#   3. an item of a list, tuple or set that follows a membership "in" (arg in ("-n", "--dry-run"); not a for loop);
#   4. the argument of .count(...), .index(...), .remove(...) or .startswith(...);
#   5. a pattern of a case line (case "--dry-run":).
# A parameter "dry_run:" also counts in a file that names typer, which makes the flag from the parameter name.
# Nowhere else: not in a comment, a docstring, a help text, an f-string, an assignment or another tool's arguments.
OPTION_CALLS = {"add_argument", "add_option", "option", "Option"}
ARGV_METHODS = {"count", "index", "remove", "startswith"}
FLAG = "--dry-run"
# Line rules for the flag: the first string of an option call (after up to three short flags), with or without
# the two dashes (yargs); a shell case label; a comparison with == or !=; a shell test with a single =;
# includes/indexOf/has with the flag alone; a JavaScript case label; a "dry-run" key of an options object
# (Node parseArgs, yargs options).
DRY_RUN_LINE = re.compile(
    r"(?:\badd_argument|\badd_option|\.option|\.requiredOption|\.addOption|\.boolean|\bOption)\(" + S
    + "(?:" + D + r"-\w" + D + S + "," + S + "){0,3}" + D + r"(?:-\w,?[ \t]{0,4})?(?:--)?dry-run(?![\w-])"
    r"|(?:^|;;|\bcase\b[^\n]{1,80}?\bin\b)[ \t]*\(?(?:[^\s|()]{1,40}[ \t]*\|[ \t]*){0,8}[\"']?--dry-run(?:=\*)?[\"']?"
    r"[ \t]*(?:\|[ \t]*[^\s|()]{1,40}[ \t]*){0,8}\)"
    r"|[=!]==?\s{0,20}" + D + r"?--dry-run(?![\w-])|" + D + "--dry-run" + D + r"\s{0,20}[=!]==?"
    r"|(?<=[ \t])=[ \t]{1,20}[\"']?--dry-run[\"']?(?=[ \t]*(?:\]|;[ \t]*then\b|&&|\|\|))"
    r"|\[[ \t]{1,20}[\"']?--dry-run[\"']?[ \t]{1,20}=[ \t]"
    r"|\.(?:includes|indexOf|has)\(\s{0,20}" + D + "--dry-run" + D + r"\s{0,20}\)"
    r"|\bcase\s{1,20}" + D + "--dry-run" + D + r"\s{0,20}:|" + D + "dry-run" + D + r"\s{0,20}:\s{0,20}\{", re.M)
# A comment (whole line, or after code) "lint: no-dry-run: <reason of three words or more>". Group 1 is the code before it.
WAIVER = re.compile(r"(?m)^(.*?)(?:#|//)[ \t]*lint: no-dry-run:[ \t]*\S+[ \t]+\S+[ \t]+\S")
COMMENT_LINE = re.compile(r"(?m)^[ \t]*(#|//).*$")
# A prompt that waits for a person. The shell form allows up to ten flags, each with or without a value (-t 5),
# before the one that holds p.
INTERACTIVE = {".py": re.compile(r"(?<![\w.])input\(|getpass\.getpass\("),
               ".sh": re.compile(r"\bread[ \t]+(?:-\w{1,20}[ \t]+(?:[^-\s]\S{0,40}[ \t]+)?){0,10}-\w{0,20}p")}
# A Markdown link target (its #fragment and "title" are left out), or a references/, scripts/ or assets/ path
# anywhere in the text (so inside a command too), also behind a ${...SKILL...}/ variable.
# A leading ./ is the skill root too. Group 1 is the link target, group 3 the bare path. The target, its fragment
# and the variable name are capped in length, and target and fragment are each matched inside a lookahead, which
# is never re-tried shorter. A longer target is no path a file system holds.
LINK = re.compile(r"\]\((?=([^)#\s]{1,500}))\1(?:#(?=([^)\s]{0,500}))\2)?(?:\s+\"[^\"]*\")?\)"
                  r"|(?:\$\{?\w{0,40}SKILL\w{0,40}\}?/|(?<![\w./<>\\-])(?:\./)?)"
                  r"((?:references|scripts|assets)[/\\][^`\s)\"',;#]*[^`\s)\"',;#.:?!*\]}|>])")


def read(p: Path, errors: str = "strict") -> str:
    try:
        with p.open(encoding="utf-8", errors=errors) as f:
            return f.read(MAX_CHARS)
    except UnicodeDecodeError as e:
        raise OSError(f"{p}: not UTF-8 ({e.reason} at byte {e.start})") from None


def git_change(helper: bool, strings: list[tuple[int, str]]) -> tuple[str, str]:
    """("outside" | "things" | "", the git words) for one bracket group; strings holds (argument number, text)."""
    if not helper:
        at = [n for n, (_, text) in enumerate(strings) if text == "git"]
        if not at:
            return "", ""
        strings = strings[at[0] + 1:]
    words: list[str] = []
    value_at = -1
    for n, text in strings:
        if words:
            words.append(text)
        elif text in GIT_VALUE_OPTIONS:
            value_at = n + 1
        elif n != value_at and not text.startswith("-"):
            words.append(text)
    if not words:
        return "", ""
    sub, rest = words[0], words[1:]
    said = "git " + " ".join(words[:2])
    if sub == "push":
        return "outside", said
    if sub in ("merge", "clean") or (sub == "reset" and "--hard" in rest) or (sub == "worktree" and rest[:1] == ["remove"]) \
            or (sub == "branch" and "-D" in rest) or (sub == "checkout" and "--" in rest):
        return "things", said
    return "", ""


def read_python(raw: str) -> tuple[str, bool, bool, str, str]:
    """Read a .py file with the tokenizer: (its text without comments and docstrings, has the --dry-run flag,
    has a waiver comment, a git call that changes something outside, a git call that changes something here).
    Raises ValueError with the reason when the file cannot be read this way; the caller then uses the line rules."""
    if max(map(len, raw.split("\n"))) > MAX_LINE:
        raise ValueError(f"a line of over {MAX_LINE} characters")
    try:  # slim tuples: a TokenInfo also holds its whole source line
        toks = [(t.type, t.string, t.start, t.end) for t in tokenize.generate_tokens(io.StringIO(raw).readline)]
    except (tokenize.TokenError, SyntaxError) as e:  # IndentationError is a SyntaxError
        raise ValueError(str(e.args[0]) if e.args else type(e).__name__) from None
    if any(t[0] == tokenize.ERRORTOKEN for t in toks):
        raise ValueError("a character that is not Python")
    OP, NAME, STRING, ENDS = tokenize.OP, tokenize.NAME, tokenize.STRING, (tokenize.NEWLINE, tokenize.ENDMARKER)
    STARTS = (tokenize.NEWLINE, tokenize.INDENT, tokenize.DEDENT)
    starts = [0]
    for line in raw.split("\n"):
        starts.append(starts[-1] + len(line) + 1)
    cut: list[tuple[int, int]] = []  # comments and docstrings, as offsets into raw

    def drop(t: tuple) -> None:
        a, b = starts[t[2][0] - 1] + t[2][1], starts[t[3][0] - 1] + t[3][1]
        if raw[a:b] != t[1]:  # never cut text at a position that is off
            raise ValueError("token positions that do not match the text")
        cut.append((a, b))

    waived = flag = False
    found = {"outside": "", "things": ""}

    def close(group: list) -> None:
        kind, said = git_change(group[0] == "git", group[1])
        if kind and not found[kind]:
            found[kind] = said

    sig = []  # the tokens that matter: no comments, no line breaks inside brackets
    for t in toks:
        if t[0] == tokenize.COMMENT:
            drop(t)
            waived = waived or bool(WAIVER.match(t[1]))
        elif t[0] != tokenize.NL:
            sig.append(t)
    typer = any(t[0] == NAME and t[1] == "typer" for t in sig)
    stack: list[list] = [["", [], 0]]  # per open bracket: kind ("git", "flag" or ""), its own strings, commas so far
    first, fors, member, i = "", 0, -1, 0  # first word of the statement; open "for"s; index of the last membership "in"
    while i < len(sig):
        tp, s = sig[i][0], sig[i][1]
        before = sig[i - 1] if i else (tokenize.NEWLINE, "")
        if tp in ENDS:
            for group in stack:
                close(group)
            stack, first, fors = [["", [], 0]], "", 0
        elif tp == STRING:
            j = i
            while sig[j][0] == STRING:
                j += 1
            # a statement made of nothing but plain strings is a docstring
            if before[0] in STARTS and sig[j][0] in ENDS and "f" not in "".join(re.match("[A-Za-z]*", t[1]).group(0) for t in sig[i:j]).lower():
                for t in sig[i:j]:
                    drop(t)
                i = j
                continue
            quote = re.match(r"[A-Za-z]*('''|\"\"\"|'|\")", s)
            text = s[quote.end():len(s) - len(quote.group(1))]
            after = sig[i + 1]
            # "own": the string is a whole argument or item of the innermost bracket (outside brackets: also after =)
            own = (before[0] == OP and (before[1] in ("(", "[", "{", ",") or len(stack) == 1 and before[1] == "=")
                   or len(stack) == 1 and before[0] in STARTS) \
                and (after[0] == OP and after[1] in (",", ")", "]", "}") or after[0] in ENDS)
            if own:
                stack[-1][1].append((stack[-1][2], text))
            words = [x for x in re.split(r"[\s,/|=]+", text) if x]
            if FLAG in words and all(x.startswith("-") for x in words) and (
                    own and stack[-1][0] == "flag"
                    or before[0] == OP and before[1] in ("==", "!=") or after[0] == OP and after[1] in ("==", "!=")
                    or after[0] == NAME and (after[1] == "in" or after[1] == "not" and sig[i + 2][1] == "in")
                    or first == "case" and after[0] == OP and after[1] in (":", "|")):
                flag = True
        elif tp == OP and s in ("(", "[", "{"):
            kind = ""
            if before[0] == NAME and s == "(" and GIT_HELPER.fullmatch(before[1]):
                kind = "git"
            elif before[0] == NAME and (s == "(" and (before[1] in OPTION_CALLS or before[1] in ARGV_METHODS and sig[i - 2][1] == ".")
                                        or before[1] == "in" and member == i - 1):
                kind = "flag"
            stack.append([kind, [], 0])
        elif tp == OP and s in (")", "]", "}"):
            if len(stack) > 1:
                close(stack.pop())
        elif tp == OP and s == ",":
            stack[-1][2] += 1
        elif tp == NAME and s == "for":
            fors += 1
        elif tp == NAME and s == "in":
            if fors:
                fors -= 1
            else:
                member = i
        elif tp == NAME and s == "dry_run" and typer and sig[i + 1][0] == OP and sig[i + 1][1] == ":":
            flag = True
        if not first and tp not in STARTS and tp not in ENDS:
            first = s
        i += 1
    parts, at = [], 0
    for a, b in sorted(cut):
        parts.append(raw[at:a])
        at = b
    return "".join(parts) + raw[at:], flag, waived, found["outside"], found["things"]


def on_disk(test) -> bool:
    """`test` is path.exists or path.is_dir. A name the file system refuses as too long is not there (older Pythons raise here)."""
    try:
        return test()
    except OSError:
        return False


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
    return re.sub(r"\s#.*$", "", val).rstrip()  # an unquoted value ends at a YAML comment


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


def check_path(skill: Path, md: Path, body: str, doc: Path, where: str, link: bool, ref: str,
               errors: list[str], warns: list[str]) -> tuple[list[str], str] | None:
    """What to say about one path named in doc, as (the list it goes to, the message); None for a path that is fine."""
    if re.match(r"[a-z]+://|mailto:", ref) or re.search(r"[<*{$\\]", ref):
        return None
    # a Markdown link is relative to the file that holds it, a bare path to the skill root
    target = (doc.parent if link else skill) / ref
    outside = ref.startswith("/") or ".." in Path(ref).parts
    if outside and link and where and not ref.startswith("/"):
        # a link in a reference may climb with ../ to a file of this skill: ../scripts/x.py, ../SKILL.md
        rel = os.path.relpath(target, skill)
        outside = rel == os.pardir or rel.startswith(os.pardir + os.sep)
        target = skill / rel
    if outside:
        return warns, f"path {ref!r} is not relative to the skill root{where}"
    if not on_disk(target.exists):
        if link or on_disk(target.parent.is_dir):
            return errors, f"referenced file does not exist: {ref}{where}"
        # the skill has no such folder, so this may be a path in the user's project
        return warns, (f"{ref}{where} is not in this skill, which has no {target.parent.relative_to(skill).as_posix()}/ folder; "
                       f"add the file, or write a path in the user's project as <project>/{ref}")
    if where and target.suffix == ".md" and target != md and target.relative_to(skill).as_posix() not in body:
        return warns, f"references/{doc.name} names {ref}, which SKILL.md never names; keep references one level deep"
    return None


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
    if any("\\" in (m.group(1) or m.group(3)) for _, text in docs if "\\" in text for m in LINK.finditer(text)):
        errors.append("backslash in a file path; use forward slashes")
    for doc, text in docs:
        where = "" if doc == md else f" (named in references/{doc.name})"
        said: dict[tuple[bool, str], tuple[list[str], str] | None] = {}  # a path named again in this file is not looked up again
        for m in LINK.finditer(text):
            ref = m.group(1) or m.group(3)
            key = (bool(m.group(1)), ref)
            if key not in said:
                said[key] = check_path(skill, md, body, doc, where, key[0], ref, errors, warns)
            if said[key]:
                said[key][0].append(said[key][1])

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
        raw = read(script, "replace").lstrip("\ufeff")  # a byte order mark is not code
        code = COMMENT_LINE.sub("", raw)
        is_test = script.stem.startswith("test_") or script.stem in {"selftest", "self_test"} or "tests" in rel.parts
        if not is_test and script.parent.name == "scripts" and "--help" not in code and "argparse" not in code and "usage" not in code.lower():
            warns.append(f"{name}: no --help/usage found")
        try:
            if script.suffix != ".py":
                raise ValueError("not a .py file")
            src, flag, waived, remote, local = read_python(raw)
        except ValueError as e:  # the line rules
            if script.suffix == ".py":
                warns.append(f"{name}: not read as Python ({e}); checked line by line, so its docstrings, and its comments after code, count as code")
            src, flag = code, "dry-run" in code and bool(DRY_RUN_LINE.search(code))
            waived = any(p.count('"') % 2 == 0 and p.count("'") % 2 == 0 for p in WAIVER.findall(raw))  # not inside a string
            git = "git" in code.lower()  # both patterns need the word, and most scripts do not hold it
            remote, local = git and REMOTE_ARGS.search(code), git and LOCAL_ARGS.search(code)
            remote, local = remote.group(0) if remote else "", local.group(0) if local else ""
        if not is_test and not flag:
            m = REMOTE_CHANGE.search(src)
            remote = m.group(0).strip() if m else remote
            m = LOCAL_CHANGE.search(src)
            local = m.group(0).strip() if m else local
            if remote:
                warns.append(f"{name}: changes something outside this machine ({remote!r}) but has no --dry-run flag; "
                             "add one (a 'lint: no-dry-run:' comment does not cover this)")
            # a comment "lint: no-dry-run: <reason>" in the file says a person judged the local changes safe without one
            elif local and not waived:
                warns.append(f"{name}: changes things ({local!r}) but has no --dry-run flag; add one, or a comment "
                             "'lint: no-dry-run: <reason, three words or more>' if a preview would add no safety")
        if script.suffix in INTERACTIVE and INTERACTIVE[script.suffix].search(src):
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
        if d and not on_disk(d.is_dir):  # a name too long for the file system is no folder either
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
