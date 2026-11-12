#!/usr/bin/env python3
"""Task state script for the atomic-decompose skill (standard library only, plus git for commits).

Run `python3 decompose.py <command> --help` for each command's flags. Every command except
`start` takes `--task <task-dir>`. JSON on stdout; errors on stderr as

    ERROR [<code>] <message>
    resolves: auto_retry | needs_fix | needs_user
    next: <exact next step>

Exit codes: 0 ok, 1 a check failed or work is refused, 2 bad input, 3 saved-state fault.

The coordinator plans and asks; this script groups the work. Items that share a file, or depend on
each other, form one run: one executor does them in order, calling `done` after each. Runs that share
no file work at once, each in its own git worktree. One run works in place.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import hashlib
import json
import os
import re
import secrets
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import time

SCHEMA = 2
VERSION = "0.2.0"
TRIES = 3
MAX_PARALLEL = 4
CHECK_TIMEOUT_S = 600
AUTO_FIXES = 2
LOCK_WAIT_S = 60
TAIL_LINES = 30
TASK_DIR = ".atomic-decompose"
SCRIPT = os.path.abspath(__file__)
LOG_EVENTS = ("compaction", "asked_again", "wrong_engagement", "tokens")
QUESTION_TYPES = ("scope", "user_only", "confirm")
SOURCES = ("user", "default_accepted", "default_unconfirmed")


class Fail(Exception):
    def __init__(self, code, message, exit_code=2, resolves="needs_fix", nxt=""):
        super().__init__(message)
        self.code, self.message, self.exit_code, self.resolves, self.nxt = code, message, exit_code, resolves, nxt


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Fail("bad_input", message, 2, "needs_fix", f"{self.prog} --help")


def _now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _ts(text):
    return _dt.datetime.strptime(text, "%Y-%m-%dT%H:%M:%S.%fZ").replace(tzinfo=_dt.timezone.utc)


def _csv(value):
    return [v.strip() for v in value.split(",") if v.strip()] if value else []


def cmd_line(task, *args):
    return " ".join([f"python3 {shlex.quote(SCRIPT)}", *args, "--task", shlex.quote(task.dir)])


# ---------------------------------------------------------------- saved state

class Task:
    def __init__(self, task_dir):
        self.dir = os.path.abspath(task_dir)
        self.state_path = os.path.join(self.dir, "state.json")
        self.record_path = os.path.join(self.dir, "record.jsonl")
        self.lock_path = os.path.join(self.dir, ".lock")
        self.plan_path = os.path.join(self.dir, "plan.json")

    def load(self):
        try:
            with open(self.state_path, encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError) as e:
            raise Fail("state_unreadable", f"cannot read {self.state_path}: {e}", 3, "needs_user",
                       "restore state.json from a backup, or start a new task; do not overwrite it")
        if st.get("schema_version") != SCHEMA:
            raise Fail("state_unreadable", f"{self.state_path} has schema_version {st.get('schema_version')!r}; "
                       f"this script ({VERSION}) reads {SCHEMA}", 3, "needs_user",
                       "finish the task with the script version that started it")
        return st

    def save(self, st):
        st["updated_at"] = _now()
        tmp = os.path.join(self.dir, f".state.{secrets.token_hex(4)}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.state_path)
        except OSError as e:
            with _quiet():
                os.remove(tmp)
            raise Fail("state_write_failed", f"cannot write {self.state_path}: {e}; the saved state is unchanged",
                       3, "auto_retry", "fix the cause (disk, permissions), then rerun the same command")

    def event(self, event, ref=None, data=None):
        """Append one run-record line, cutting a torn last line (a crash mid-write) first."""
        line = json.dumps({"ts": _now(), "event": event, "ref": ref, "data": data or {}}, ensure_ascii=False)
        try:
            if os.path.exists(self.record_path):
                with open(self.record_path, "rb+") as f:
                    raw = f.read()
                    if raw and not raw.endswith(b"\n"):
                        f.seek(raw.rfind(b"\n") + 1)
                        f.truncate()
            with open(self.record_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            raise Fail("record_write_failed", f"cannot append to {self.record_path}: {e}; state.json holds the "
                       "change", 3, "auto_retry", "fix the cause; the run record misses this one line")

    def record(self):
        if not os.path.exists(self.record_path):
            return []
        out = []
        with open(self.record_path, encoding="utf-8") as f:
            for line in f:
                with _quiet(ValueError):
                    out.append(json.loads(line))
        return out

    def lock(self):
        """Wait for the lock; take it over when the process that holds it is gone."""
        end = time.monotonic() + LOCK_WAIT_S
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return
            except FileExistsError:
                if not _holder_alive(self.lock_path):
                    with _quiet():
                        os.remove(self.lock_path)
                    continue
                if time.monotonic() > end:
                    raise Fail("task_locked", f"{self.lock_path} is held by a live process for over {LOCK_WAIT_S}s",
                               3, "needs_user", "wait for the other command to end, then rerun this one")
                time.sleep(0.1)

    def unlock(self):
        with _quiet(OSError, ValueError):
            with open(self.lock_path, encoding="utf-8") as f:
                mine = int(f.read().strip()) == os.getpid()
            if mine:
                os.remove(self.lock_path)


class _quiet:
    def __init__(self, *errors):
        self.errors = errors or (OSError,)

    def __enter__(self):
        return self

    def __exit__(self, kind, value, tb):
        return kind is not None and issubclass(kind, self.errors)


def _holder_alive(path):
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
        pid = int(text) if text else None
    except (OSError, ValueError):
        return True
    if pid is None:  # created, pid not written yet; empty for seconds means its writer died
        with _quiet():
            return time.time() - os.path.getmtime(path) < 5
        return False
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def locked(task, fn):
    task.lock()
    try:
        st = task.load()
        return fn(st)
    finally:
        task.unlock()


# ---------------------------------------------------------------- plan

def _list(value):
    if value is None:
        return []
    return [value] if isinstance(value, str) else list(value)


def _norm_path(p):
    p = str(p).replace("\\", "/").strip()
    while p.startswith("./"):
        p = p[2:]
    return p


def read_plan_file(path):
    try:
        text = sys.stdin.read() if path == "-" else open(path, encoding="utf-8").read()
        plan = json.loads(text)
    except OSError as e:
        raise Fail("plan_unreadable", f"cannot read {path}: {e}", 2)
    except ValueError as e:
        raise Fail("plan_invalid", f"{path} is not JSON: {e}", 2, "needs_fix", "fix the JSON and rerun")
    if not isinstance(plan, dict):
        raise Fail("plan_invalid", "the plan must be one JSON object", 2)
    return plan


def plan_items(plan):
    items = plan.get("items") or []
    if isinstance(items, dict):  # accept {"1": {...}} as well as a list
        items = [dict(v, id=v.get("id", k)) if isinstance(v, dict) else v for k, v in items.items()]
    return items


def normalise_item(raw):
    if not isinstance(raw, dict):
        return None
    return {"id": str(raw["id"]) if raw.get("id") is not None else None,
            "title": str(raw.get("title") or "").strip(), "goal": str(raw.get("goal") or "").strip(),
            "covers": [str(c) for c in _list(raw.get("covers"))],
            "files": [_norm_path(f) for f in _list(raw.get("files"))],
            "check_cmd": [str(c) for c in _list(raw.get("check_cmd"))],
            "check": [str(c) for c in _list(raw.get("check"))],
            "needs": [str(q) for q in _list(raw.get("needs"))],
            "depends": [str(d) for d in _list(raw.get("depends"))],
            "skill": raw.get("skill") or None}


def plan_problems(st):
    """Every problem in the plan at once, so one fix round clears them all."""
    probs = []
    if not st["question"]:
        probs.append("`question`: one sentence the result must answer")
    if not st["requirements"]:
        probs.append("`requirements`: list each part of the request")
    qids = {q["id"] for q in st["questions"]}
    for q in st["questions"]:
        if q["type"] not in QUESTION_TYPES:
            probs.append(f"{q['id']}: `type` must be one of {', '.join(QUESTION_TYPES)}")
        if not q["text"] or (not q["default"] and q.get("origin") != "block"):
            probs.append(f"{q['id']}: needs `text` and a `default`")
    live = [it for it in st["items"] if it["status"] != "dropped"]
    if not live:
        probs.append("`items`: the plan has no items")
    ids, titles = {it["id"] for it in st["items"]}, {}
    reqs = {f"R{i + 1}" for i in range(len(st["requirements"]))}
    covered = set()
    for it in live:
        name = f"item {it['id']} ({it['title'] or 'no title'})"
        if not it["title"]:
            probs.append(f"{name}: needs a `title`")
        elif it["title"] in titles:
            probs.append(f"{name}: title also used by item {titles[it['title']]}")
        titles.setdefault(it["title"], it["id"])
        if not it["goal"]:
            probs.append(f"{name}: needs a `goal`")
        if it["files"] and not it["check_cmd"]:
            probs.append(f"{name}: an item with `files` needs `check_cmd` (the repository's own test command)")
        if not it["files"] and not (it["check"] or it["check_cmd"]):
            probs.append(f"{name}: a read-only item needs `check` (points to judge its result by)")
        for f in it["files"]:
            if not f or os.path.isabs(f) or f == ".." or f.startswith("../") or "/../" in f \
                    or f.split("/")[0] in (TASK_DIR, ".git"):
                probs.append(f"{name}: file {f!r} must be a path inside the root, not under .git/ or {TASK_DIR}/")
        for c in it["covers"]:
            if c not in reqs:
                probs.append(f"{name}: covers {c}, but requirements are {', '.join(sorted(reqs)) or 'none'}")
        covered.update(it["covers"])
        for q in it["needs"]:
            if q not in qids:
                probs.append(f"{name}: needs {q}, which is not a question")
        for d in it["depends"]:
            if d not in ids or d == it["id"]:
                probs.append(f"{name}: depends on {d}, which is not another item")
    for r in sorted(reqs - covered, key=lambda r: int(r[1:])):
        probs.append(f"{r} ({st['requirements'][int(r[1:]) - 1]}): no item `covers` it")
    if _cycle(st):
        probs.append(f"`depends` has a cycle: {' -> '.join(_cycle(st))}")
    # ponytail: sees a split command only by its flag, so ["npm", "test"] passes; upgrade: `command -v` first words.
    if any(c.lstrip().startswith("-") for x in [st] + live for c in x["check_cmd"]):
        probs.append('`check_cmd`: write each command whole in one string ("python3 -m unittest -q"), not as words')
    return probs


def _cycle(st):
    deps = {it["id"]: it["depends"] for it in st["items"] if it["status"] != "dropped"}
    seen, stack = set(), []

    def visit(i):
        if i in stack:
            return stack[stack.index(i):] + [i]
        if i in seen or i not in deps:
            return None
        seen.add(i)
        stack.append(i)
        for d in deps[i]:
            c = visit(d)
            if c:
                return c
        stack.pop()
        return None

    for i in deps:
        c = visit(i)
        if c:
            return c
    return None


def apply_plan(st, plan, task):
    """Merge a plan file into the state: new items are added; items not started are edited, or dropped by
    `"status": "dropped"`. Items the file leaves out are kept as they are."""
    out = {"added": [], "edited": [], "dropped": [], "kept": []}
    if "question" in plan:
        st["question"] = str(plan["question"] or "").strip()
    if "requirements" in plan:
        st["requirements"] = [str(r) for r in _list(plan["requirements"])]
    if "check_cmd" in plan:
        st["check_cmd"] = [str(c) for c in _list(plan["check_cmd"])]
    by_q = {q["id"]: q for q in st["questions"]}
    for raw in _list(plan.get("questions")):
        if not isinstance(raw, dict):
            continue
        q = by_q.get(str(raw.get("id"))) if raw.get("id") else None
        if q is None:
            q = {"id": f"Q{len(st['questions']) + 1}", "asked": False, "answer": None, "answer_source": None,
                 "changed_at": None, "affected": [], "origin": "plan"}
            st["questions"].append(q)
        if q["answer"] is None:
            q.update(type=str(raw.get("type") or "scope"), text=str(raw.get("text") or ""),
                     default=str(raw.get("default") or ""), because=raw.get("because"))
    by_id = {it["id"]: it for it in st["items"]}
    alias, touched = {}, []
    open_states = ("pending", "failed", "blocked")
    for raw in plan_items(plan):
        new = normalise_item(raw)
        if new is None:
            continue
        old = by_id.get(new["id"]) if new["id"] else None
        if raw.get("status") == "dropped":
            if old is not None and old["status"] in open_states:
                old["status"] = "dropped"
                out["dropped"].append(old["id"])
            continue
        if old is None:
            given, new["id"] = new["id"], str(max([int(i["id"]) for i in st["items"]] + [0]) + 1)
            if given:
                alias[given] = new["id"]
            new.update(status="pending", tries=0, notes=[], commit=None, result=None, block=None, run=None,
                       failure=None, origin="plan")
            st["items"].append(new)
            by_id[new["id"]] = new
            out["added"].append(new["id"])
        elif old["status"] in open_states:
            fields = {k: new[k] for k in ("title", "goal", "covers", "files", "check_cmd", "check", "needs",
                                          "depends", "skill")}
            if any(old[k] != v for k, v in fields.items()) or (old["status"] != "pending"
                                                                and raw.get("status") == "pending"):
                old.update(fields, status="pending", block=None, failure=None, tries=0)
                out["edited"].append(old["id"])
        else:
            out["kept"].append(old["id"])
        touched.append(by_id[new["id"]])
    for it in touched:  # `depends` may name the plan file's own ids for new items
        it["depends"] = [alias.get(d, d) for d in it["depends"]]
    probs = plan_problems(st)
    if probs:
        raise Fail("plan_invalid", f"{len(probs)} problem(s) in the plan:\n- " + "\n- ".join(probs), 2,
                   "needs_fix", "fix every listed problem in the plan file, then rerun the same command")
    write_plan_file(task, st)
    return out


def write_plan_file(task, st):
    """The task's own plan.json, with ids, is the file to edit for `plan`."""
    plan = {"question": st["question"], "requirements": st["requirements"], "check_cmd": st["check_cmd"],
            "questions": [{k: q[k] for k in ("id", "type", "text", "default", "because")} for q in st["questions"]],
            "items": [{**{k: it[k] for k in ("id", "title", "goal", "covers", "files", "check_cmd", "check",
                                              "needs", "depends", "skill")}, "status": it["status"]}
                      for it in st["items"] if it["status"] != "dropped"]}
    with open(task.plan_path, "w", encoding="utf-8") as f:
        json.dump(plan, f, ensure_ascii=False, indent=1)


# ---------------------------------------------------------------- git

def git(cwd, *args, check=True, env=None):
    try:
        p = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env=env)
    except FileNotFoundError:
        raise Fail("git_missing", "git is not installed", 3, "needs_user", "install git, or run without it")
    if check and p.returncode != 0:
        raise Fail("git_failed", f"git {' '.join(args)} failed in {cwd}: {(p.stderr or p.stdout).strip()[-800:]}",
                   3, "needs_user", "fix the git problem it names, then rerun the same command")
    return p


def git_top(path):
    with _quiet(Fail):
        p = git(path, "rev-parse", "--show-toplevel", check=False)
        if p.returncode == 0:
            return os.path.realpath(p.stdout.strip())
    return None


def head(cwd):
    return git(cwd, "rev-parse", "HEAD").stdout.strip()


def _sha_file(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return "<missing>"


def dirty_files(top, root):
    """{path relative to root: content hash, "?"-prefixed when untracked} for every changed or untracked file
    under root, the task folder aside."""
    p = git(top, "status", "--porcelain", "-z", "--untracked-files=all")
    parts, out, i = p.stdout.split("\0"), {}, 0
    rel_root = os.path.relpath(root, top).replace("\\", "/")
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        paths = [entry[3:]]
        if entry[0] in "RC":
            paths.append(parts[i])
            i += 1
        for path in paths:
            rel = path if rel_root == "." else (path[len(rel_root) + 1:] if path.startswith(rel_root + "/") else None)
            if rel is None or rel.split("/")[0] == TASK_DIR:
                continue
            out[rel] = ("?" if entry.startswith("??") else "") + _sha_file(os.path.join(root, rel))
    return out


def untracked(value):
    return value.startswith("?")


def covered(path, files):
    return any(path == f or (f.endswith("/") and path.startswith(f)) or path.startswith(f.rstrip("/") + "/")
               for f in files)


def changed_since(run_dir, top_of_run, snapshot):
    """{path: hash} of the files that changed since `snapshot`."""
    now = dirty_files(top_of_run, run_dir)
    return {p: h for p, h in sorted(now.items()) if snapshot.get(p) != h}


def add_paths(run_dir, paths, env=None):
    """`git add -A` the paths, skipping those already gone from disk and index (a `git rm` or `git mv` source)."""
    indexed = set(git(run_dir, "ls-files", "-z", "--", *paths, env=env).stdout.split("\0"))
    keep = [p for p in paths if os.path.lexists(os.path.join(run_dir, p)) or p in indexed]
    if keep:
        git(run_dir, "add", "-A", "--", *keep, env=env)


def save_patch(run_dir, paths, out_path):
    """Write the diff of `paths` (new files included) to `out_path` without touching the real index."""
    idx = git(run_dir, "rev-parse", "--git-path", "index").stdout.strip()
    idx = idx if os.path.isabs(idx) else os.path.join(run_dir, idx)
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(tmp, "index"))
        if os.path.exists(idx):
            shutil.copy(idx, env["GIT_INDEX_FILE"])
        add_paths(run_dir, paths, env)
        diff = git(run_dir, "diff", "--cached", "--binary", "HEAD", "--", *paths, env=env).stdout
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(diff)


def restore_paths(run_dir, paths):
    tracked = set(git(run_dir, "ls-tree", "-r", "--name-only", "HEAD", "--", *paths).stdout.split("\n")) - {""}
    prefix = git(run_dir, "rev-parse", "--show-prefix").stdout.strip()
    keep = [p for p in paths if prefix + p in tracked]
    if keep:
        git(run_dir, "checkout", "HEAD", "--", *keep)
    gone = [p for p in paths if prefix + p not in tracked]
    if gone:
        git(run_dir, "rm", "-q", "--cached", "--ignore-unmatch", "--", *gone, check=False)
    for p in gone:
        with _quiet():
            os.remove(os.path.join(run_dir, p))


# ---------------------------------------------------------------- checks

def run_check(command, cwd, log_path, timeout):
    """Exit code of one shell command, or None when it ran past `timeout` (its process group is killed)."""
    os.makedirs(os.path.dirname(log_path), exist_ok=True)
    with open(log_path, "wb") as log:
        kw = ({"start_new_session": True} if os.name == "posix"
              else {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP})
        p = subprocess.Popen(command, shell=True, cwd=cwd, stdout=log, stderr=subprocess.STDOUT, **kw)
        try:
            return p.wait(timeout=timeout)
        except subprocess.TimeoutExpired:
            if os.name == "posix":
                os.killpg(p.pid, signal.SIGKILL)
            else:
                subprocess.run(["taskkill", "/F", "/T", "/PID", str(p.pid)], capture_output=True)
            p.wait()
            return None


def check_unrunnable(command, exit_code, log_text):
    """Why `command` could not run at all (so its exit code judges the command, not the work), else None."""
    # ponytail: plain text matches on the log; a test that prints `command not found` itself reads as broken.
    # Upgrade path: run the command's first word through `shutil.which` before the check.
    if exit_code in (126, 127):
        return f"the shell could not run it (exit {exit_code})"
    for text in ("command not found", "can't open file"):
        if text in log_text:
            return f"the log says {text!r}"
    m = re.search(r"(?:^|\s)-m\s+([\w.]+)", command)
    if m and re.search(rf"No module named '?{re.escape(m.group(1))}'?(?![\w.])", log_text):
        return f"the module {m.group(1)} is not installed"
    return None


def run_checks(task, commands, cwd, stem, timeout):
    """[(command, exit code or None, log path)] for each command; stops at the first failure."""
    out = []
    for n, command in enumerate(commands, 1):
        log = os.path.join(task.dir, "logs", f"{stem}-{n}.log")
        code = run_check(command, cwd, log, timeout)
        out.append((command, code, log))
        if code != 0:
            break
    return out


def tail(path, n=TAIL_LINES):
    try:
        with open(path, encoding="utf-8", errors="replace") as f:
            return "".join(f.readlines()[-n:]).rstrip()
    except OSError:
        return ""


# ---------------------------------------------------------------- runs

def items_by_id(st):
    return {it["id"]: it for it in st["items"]}


def open_needs(st, it):
    qs = {q["id"]: q for q in st["questions"]}
    return [q for q in it["needs"] if qs[q]["answer"] is None]


def plan_runs(st):
    """Group the items that can start now into runs (lists of item ids, each in dependency order)."""
    by = items_by_id(st)
    pend = [it for it in st["items"] if it["status"] == "pending" and not open_needs(st, it)]
    ready = {it["id"] for it in pend if all(by[d]["status"] == "done" for d in it["depends"])}
    parent = {i: i for i in ready}

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    def join(a, b):
        parent[find(a)] = find(b)

    def link_files(members):
        ids = sorted(members, key=int)
        for x in ids:
            for y in ids:
                if x < y and by[x]["files"] and by[y]["files"] and any(
                        covered(f, by[y]["files"]) or covered(g, by[x]["files"])
                        for f in by[x]["files"] for g in by[y]["files"]):
                    join(x, y)

    link_files(ready)
    # an item waiting only on items in one run joins that run, so a chain runs in one executor
    changed = True
    while changed:
        changed = False
        for it in pend:
            if it["id"] in parent:
                continue
            waiting = [d for d in it["depends"] if by[d]["status"] != "done"]
            if waiting and all(d in parent for d in waiting) and len({find(d) for d in waiting}) == 1:
                parent[it["id"]] = it["id"]
                join(it["id"], waiting[0])
                link_files(parent)
                changed = True
    groups = {}
    for i in parent:
        groups.setdefault(find(i), []).append(i)
    runs = [_dep_order(by, g) for g in groups.values()]
    runs.sort(key=lambda r: int(r[0]))
    if st["mode"] == "main_session" and runs:
        runs = [_dep_order(by, [i for r in runs for i in r])]
    while len(runs) > st["max_parallel"]:  # ponytail: pack the two smallest runs together; a size-aware packer
        runs.sort(key=len)                  # would balance wall time better
        a, b = runs.pop(0), runs.pop(0)
        runs.append(_dep_order(by, a + b))
        runs.sort(key=lambda r: int(r[0]))
    return runs


def _dep_order(by, ids):
    ids, out, done = sorted(ids, key=int), [], set()
    while len(out) < len(ids):
        for i in ids:
            if i not in done and all(d not in ids or d in done for d in by[i]["depends"]):
                out.append(i)
                done.add(i)
                break
    return out


def start_runs(task, st, groups):
    """Create the runs (worktrees when more than one writes run starts at once) and write their briefs."""
    by = items_by_id(st)
    top = st["git_top"]
    writes_runs = [g for g in groups if any(by[i]["files"] for i in g)]
    if len(writes_runs) > 1 and not top:  # no git: no worktrees, so the writers take turns
        groups = [writes_runs[0]] + [g for g in groups if g not in writes_runs]
    use_worktrees = top is not None and len([g for g in groups if any(by[i]["files"] for i in g)]) > 1
    # ponytail: ignored top-level entries (.venv, .env, node_modules) are linked, not copied, so checks run as
    # in place; parallel checks that write into one shared ignored folder can race. Upgrade: copy them.
    ignored = [p.rstrip("/") for p in git(top, "ls-files", "-o", "-i", "--exclude-standard", "--directory", "-z")
               .stdout.split("\0") if p and "/" not in p.rstrip("/") and p.rstrip("/") != TASK_DIR] \
        if use_worktrees else []
    runs = []
    for g in groups:
        rid = f"r{len(st['runs']) + 1}"
        run = {"id": rid, "items": g, "status": "active", "kind": "work", "started_at": _now(),
               "worktree": None, "branch": None, "dir": st["root"], "base": head(top) if top else None,
               "snapshot": {}, "self": len(groups) == 1 and st["mode"] != "delegate"}
        if use_worktrees and any(by[i]["files"] for i in g):
            wt = os.path.join(task.dir, "wt", rid)
            branch = f"ad/{st['task_id']}/{rid}"
            git(top, "worktree", "add", "-q", "-b", branch, wt, run["base"])
            for p in ignored:
                with _quiet():
                    os.symlink(os.path.join(top, p), os.path.join(wt, p))
            run.update(worktree=wt, branch=branch, links=ignored, dir=os.path.normpath(
                os.path.join(wt, os.path.relpath(st["root"], top))))
        elif top:  # a file of this run's items that is dirty already holds an earlier executor's partial work
            files = [f for i in g for f in by[i]["files"]]
            run["snapshot"] = {p: h for p, h in dirty_files(top, st["root"]).items() if not covered(p, files)}
        for i in g:
            by[i].update(status="running", run=rid)
            task.event("item_started", i, {"run": rid, "try": by[i]["tries"] + 1})
        st["runs"].append(run)
        run["brief"] = write_brief(task, st, run)
        runs.append(run)
    return runs


def write_brief(task, st, run):
    by = items_by_id(st)
    qs = {q["id"]: q for q in st["questions"]}
    items = [by[i] for i in run["items"]]
    used = {q for it in st["items"] for q in it["needs"]}  # an answer no item `needs` applies to every item
    needs = sorted({q for it in items for q in it["needs"]} | {q for q in qs if q not in used and qs[q]["answer"]},
                   key=lambda q: int(q[1:]))
    done = lambda i: cmd_line(task, "done", i)  # noqa: E731
    lines = [f"Task {st['task_id']}, items {', '.join(run['items'])}: you do all of them, alone, in this order. "
             f"Work in {run['dir']} (cd there first; change files only there).",
             f"Request: {st['question']}",
             "One item at a time: do its goal and run its `done` command before you start the next item, "
             "because `done` commits every change in the item's files. `done` runs the checks first; "
             "on a failure it prints why: fix it and run `done` again, at most 3 times, then go on. "
             "Only `done` commits: never run git commit, reset, clean or stash, or change the task folder.",
             f"Need a fact only the user knows: {cmd_line(task, 'block', '<id>', '--question', shlex.quote('<q>'))}"
             ", then go on.",
             f"A step outside the goal (other files, deleting, contacting anyone): {cmd_line(task, 'block', '<id>', '--approval', shlex.quote('<step>'))}, then go on.",
             f"When every item is finished, run {cmd_line(task, 'next')} and do what it prints."
             if run["self"] else "Do not ask the user anything. Reply with one line per item saying what you did."]
    if needs:
        lines.append("Settled: " + "; ".join(f"{q}: {qs[q]['text']} = {qs[q]['answer']}" for q in needs))
    live = [d for d in st["decisions"] if not d.get("superseded_by")]
    if live:
        lines.append("Decided: " + "; ".join(f"{d['id']}: {d['question']} = {d['chosen']}" for d in live))
    for it in items:
        lines += ["", f"ITEM {it['id']}: {it['title']}" + (f"   [Skill: {it['skill']}, load it first]"
                                                           if it["skill"] else "")]
        if it["files"]:
            lines.append(f"Files: {', '.join(it['files'])}")
        else:
            lines.append(f"Result: write it to {result_path(task, it)}; change no workspace file")
        lines.append(f"Goal: {it['goal']}")
        if it["check_cmd"]:
            lines.append("Checks (`done` runs them): " + " && ".join(it["check_cmd"]))
        if it["check"]:
            lines.append("Judged by: " + "; ".join(it["check"]))
        for note in it["notes"]:
            lines.append(f"Note: {note}")
        lines.append(f"Done: {done(it['id'])}")
    path = os.path.join(task.dir, "briefs", f"{run['id']}.md")
    for d in ("briefs", "results"):
        os.makedirs(os.path.join(task.dir, d), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    return path


def result_path(task, it):
    return it["result"] or os.path.join(task.dir, "results", f"{it['id']}.md")


def prompt_for(path):
    return f"Your whole task is the brief at {path}. Read it, then follow it."


def settle_runs(task, st):
    """Close every active run: unfinished items go back to pending, worktree commits land on HEAD in plan order.
    Returns (closed runs, a stop dict or None)."""
    by = items_by_id(st)
    closed = []
    for run in [r for r in st["runs"] if r["status"] == "active"]:
        if run["kind"] == "review":
            run["status"] = "closed"
            closed.append(run)
            continue
        for i in run["items"]:
            it = by[i]
            if it["status"] == "running":
                it["tries"] += 1
                if it["tries"] >= TRIES:
                    fail_item(task, st, it, "its executor returned without `done` three times")
                else:
                    it.update(status="pending", run=None)
                    it["notes"].append("An earlier executor returned without running `done`" + (
                        "." if run["worktree"] else "; its work may be partly there in the files"))
                    task.event("item_retried", i, {"reason": "no done"})
        if run["worktree"]:
            stop = land_run(task, st, run)
            if stop:
                return closed, stop
        run["status"] = "closed"
        closed.append(run)
    return closed, None


def land_run(task, st, run):
    top = st["git_top"]
    picks = [line[2:] for line in git(top, "cherry", "HEAD", run["branch"], run["base"]).stdout.split("\n")
             if line.startswith("+ ")]
    clash = []
    if picks:
        p = git(top, "cherry-pick", *picks, check=False)
        if p.returncode != 0:
            clash = git(top, "diff", "--name-only", "--diff-filter=U", check=False).stdout.split()
            git(top, "cherry-pick", "--abort", check=False)
            if not clash:  # git refused before picking: staged or uncommitted changes in the way
                return {"condition": "land_blocked",
                        "detail": f"git cannot land run {run['id']} on HEAD: {(p.stderr or p.stdout).strip()[-400:]}"
                                  "; commit, unstage or stash what it names"}
        else:
            remap_commits(st, top)
            run["landed"] = len(picks)
    by = items_by_id(st)
    left = dirty_files(git_top(run["dir"]), run["dir"])
    for i in run["items"]:
        it = by[i]
        if it["status"] == "done" and clash:
            it.update(status="pending", commit=None, run=None)
            it["tries"] += 1
            it["notes"].append(f"Its earlier attempt clashed in {', '.join(clash)} with work that landed meanwhile; "
                               f"redo it on the current files (the attempt: `git show {run['branch']}`)")
            task.event("merge_conflict", i, {"files": clash, "branch": run["branch"]})
            if it["tries"] >= TRIES:
                fail_item(task, st, it, f"it clashed with other work on landing; see branch {run['branch']}")
        elif it["status"] != "done" and it["files"]:
            kept = shelve(task, run, [p for p in left if covered(p, it["files"])], f"{i}-{run['id']}.patch")
            if kept:
                it["notes"].append(f"Its partial work from run {run['id']} {kept}")
    for p, h in dirty_files(git_top(run["dir"]), run["dir"]).items():  # new files outside every item's files:
        dest = os.path.join(st["root"], p)                               # finish lists them in untracked_left
        if untracked(h) and not os.path.lexists(dest):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(os.path.join(run["dir"], p), dest, follow_symlinks=False)
    git(top, "worktree", "remove", "--force", run["worktree"], check=False)
    if not clash:
        git(top, "branch", "-D", run["branch"], check=False)
    return None


def item_commits(cwd, st):
    """{item id: sha} for this task's commits since the task began, newest first wins."""
    log = git(cwd, "log", "--format=%H %(trailers:key=AD-Item,valueonly,separator=)", f"{st['base_head']}..HEAD")
    out = {}
    for line in log.stdout.split("\n"):
        sha, _, trailer = line.partition(" ")
        task_id, _, item = trailer.strip().rpartition("/")
        if task_id == st["task_id"]:
            out.setdefault(item, sha)
    return out


def remap_commits(st, top):
    for item, sha in item_commits(top, st).items():
        if item in items_by_id(st):
            items_by_id(st)[item]["commit"] = sha


def fail_item(task, st, it, reason):
    it.update(status="failed", failure=reason)
    task.event("item_failed", it["id"], {"reason": reason})
    for other in st["items"]:  # work that needs a failed item cannot happen; the rest carries on
        if other["status"] in ("pending", "blocked", "running") and it["id"] in other["depends"]:
            fail_item(task, st, other, f"it depends on item {it['id']}, which failed")


def review_due(st):
    """auto: review what executors wrote; the coordinator watched its own work being written."""
    if st["review"] == "never" or st["review_state"] != "none":
        return False
    done = {it["id"] for it in st["items"] if it["status"] == "done" and it["files"]}
    return bool(done) if st["review"] == "always" else any(
        not r.get("self") and done & set(r["items"]) for r in st["runs"])


def unchanged_note(items):
    quiet = [f"item {it['id']} never changed {', '.join(it['untouched'])}" for it in items
             if it["status"] == "done" and it.get("untouched")]
    return "; ".join(quiet) + ". If that work was forgotten, add an item for it." if quiet else None


def start_review(task, st):
    rid = f"r{len(st['runs']) + 1}"
    path = os.path.join(task.dir, "review.md")
    items = [it for it in st["items"] if it["status"] == "done"]
    lines = [f"Review task {st['task_id']}, read-only: change no file except {path}.",
             f"Request: {st['question']}",
             "Requirements: " + "; ".join(f"R{i + 1}: {r}" for i, r in enumerate(st["requirements"])),
             f"The changes: in {st['root']} run `git diff {st['base_head']} HEAD`" if st["git_top"]
             else f"The changes are in {st['root']}.",
             "Items:"]
    lines += [f"- {it['id']} {it['title']}: {it['goal']}" for it in items]
    lines += [f"Planned files left unchanged: {unchanged_note(items)}"] if unchanged_note(items) else []
    lines += ["Check the diff against the requirements and goals: bugs, missing cases, broken or lost tests, "
              "conflicts between items, and anything a goal asked for that is not there.",
              f"Write one line per finding to {path}: `<high|medium|low> <file>:<line> <problem> -> <fix>`, "
              "or `no findings`. Reply with the number of findings."]
    brief = os.path.join(task.dir, "briefs", f"{rid}-review.md")
    os.makedirs(os.path.dirname(brief), exist_ok=True)
    with open(brief, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    st["runs"].append({"id": rid, "items": [], "status": "active", "kind": "review", "brief": brief,
                       "worktree": None, "started_at": _now()})
    st["review_state"] = "running"
    task.event("review_started", rid)
    return brief


def task_checks(task, st, stem):
    """Run the task checks on HEAD once per HEAD. Returns the failure (command, log) or None."""
    if not st["check_cmd"]:
        return None
    now = head(st["git_top"]) if st["git_top"] else None
    if now is not None and st.get("checked_head") == now:
        return None
    for command, code, log in run_checks(task, st["check_cmd"], st["root"], stem, st["check_timeout_s"]):
        if code != 0:
            return command, code, log
    st["checked_head"] = now
    return None


# ---------------------------------------------------------------- commands

def cmd_start(a):
    root = os.path.realpath(a.root)
    if not os.path.isdir(root):
        raise Fail("bad_input", f"no folder {root}", 2)
    plan = read_plan_file(a.plan)
    top = git_top(root)
    stamp = _dt.datetime.now().strftime("%Y%m%d")
    slug = re.sub(r"[^a-z0-9]+", "-", str(plan.get("question") or "task").lower()).strip("-")[:40] or "task"
    base = os.path.join(root, TASK_DIR, f"{stamp}-{slug}")
    tdir, n = base, 1
    while os.path.exists(tdir):
        n += 1
        tdir = f"{base}-{n}"
    st = {"schema_version": SCHEMA, "version": VERSION, "task_id": os.path.basename(tdir), "root": root,
          "git_top": top, "statement": a.statement, "question": "", "requirements": [], "check_cmd": [],
          "check_timeout_s": int(plan.get("check_timeout_s") or CHECK_TIMEOUT_S), "mode": a.mode,
          "max_parallel": a.max_parallel, "review": a.review, "review_state": "none", "auto_fixes": 0,
          "status": "active", "stop": None, "questions": [], "decisions": [], "items": [], "runs": [],
          "base_head": head(top) if top else None, "started_at": _now(), "updated_at": None, "mark": None}
    planned = sorted({f for raw in plan_items(plan) if isinstance(raw, dict)
                      for f in (_norm_path(x) for x in _list(raw.get("files")))})
    found = [f for f in planned if os.path.lexists(os.path.join(root, f))]
    if planned and not found and not a.new_files:
        raise Fail("files_not_found", f"none of the planned files exist under {root}: {', '.join(planned[:6])}", 1,
                   "needs_fix", "give --root the folder the request changes (file paths start there); if every "
                                "file really is new, rerun with --new-files")
    for f in found:  # git sees nothing inside a repository nested below the root's own
        inner = git_top(os.path.dirname(os.path.join(root, f.rstrip("/"))) or root)
        if inner != top:
            raise Fail("nested_repo", f"{f} is in another git repository, {inner}", 1, "needs_fix",
                       f"rerun start with --root {inner} and file paths that start there")
    if top:
        dirty = dirty_files(top, root)
        clash = sorted(p for p in dirty if covered(p, planned))
        if clash:
            raise Fail("dirty_files", f"planned files have uncommitted changes: {', '.join(clash)}", 1, "needs_user",
                       "ask the user to commit or stash them, then rerun start")
        st["start_dirty"] = dirty
    os.makedirs(tdir)
    task = Task(tdir)
    try:
        out = apply_plan(st, plan, task)
    except Fail:
        shutil.rmtree(tdir, ignore_errors=True)
        with _quiet():
            os.rmdir(os.path.dirname(tdir))
        raise
    with open(os.path.join(root, TASK_DIR, ".gitignore"), "w", encoding="utf-8") as f:
        f.write("*\n")  # task state, logs and worktrees stay out of the user's commits and stashes
    task.save(st)
    task.event("engaged", None, {"statement": a.statement, "version": VERSION})
    task.event("plan_changed", None, out)
    return {"task_dir": tdir, "plan": task.plan_path, **locked(task, lambda s: advance(task, s))}


def advance(task, st):
    """The next action for the coordinator; settles returned runs and starts new ones. Caller holds the lock."""
    t = shlex.quote(task.dir)
    nxt = cmd_line(task, "next")
    if st["status"] == "complete":
        return {"action": "report", "next": "write the report; mark after the user replies"}
    if st["status"] == "handed_back":
        return {"action": "none", "next": "the task was handed back; stop using this method"}
    if st["status"] == "stopped":
        return stop_action(task, st)
    unasked = [q for q in st["questions"] if q["answer"] is None and not q["asked"] and q["origin"] == "plan"]
    if unasked:
        for q in unasked:
            q["asked"] = True
            task.event("question_asked", q["id"], {"type": q["type"], "round": 1})
        task.save(st)
        return {"action": "ask", "questions": [qview(q) for q in unasked],
                "plan": [{"id": it["id"], "title": it["title"], "files": it["files"]}
                         for it in st["items"] if it["status"] != "dropped"],
                "next": "ask all of these in one question, each labelled with its type and default, with the plan in "
                        f"the prompt; record each reply with {cmd_line(task, 'answer', '--id', '<Q>', '--text', shlex.quote('<reply>'))} "
                        f"(or `answer --defaults` when the user accepts them), then {nxt}"}
    unanswered = [q["id"] for q in st["questions"] if q["answer"] is None and q["origin"] == "plan"]
    if unanswered:
        raise Fail("open_questions", f"{', '.join(unanswered)} have no answer yet", 1, "needs_user",
                   f"record the user's replies with `answer`, or `answer --defaults`, then {nxt}")
    review_run = next((r for r in st["runs"] if r["status"] == "active" and r["kind"] == "review"), None)
    closed, stop = settle_runs(task, st)
    if stop:
        return do_stop(task, st, stop["condition"], stop["detail"])
    out = {}
    if review_run:
        path = os.path.join(task.dir, "review.md")
        if os.path.isfile(path):
            st["review_state"] = "done"
            task.event("review_done", review_run["id"])
            out["review"] = path
        else:
            st["review_state"] = "none" if st.get("review_tries", 0) < 1 else "missing"
            st["review_tries"] = st.get("review_tries", 0) + 1
    round_items = [items_by_id(st)[i] for r in closed for i in r["items"]]
    if unchanged_note(round_items):
        out["unchanged"] = unchanged_note(round_items)
    landed = [it["id"] for it in round_items if it["status"] == "done"]
    # a round with items going back for another try is checked after that try, so no fix item duplicates them
    if round_items and all(it["status"] in ("done", "failed") for it in round_items) \
            and any(it["status"] == "done" and it["files"] for it in st["items"]):
        failed = task_checks(task, st, f"task-{len(st['runs'])}")
        if failed:
            command, code, log = failed
            if st["auto_fixes"] >= AUTO_FIXES:
                return do_stop(task, st, "task_checks_failed", f"`{command}` still fails after {AUTO_FIXES} fix "
                                                               f"items; log {log}")
            st["auto_fixes"] += 1
            files = sorted({f for i in landed for f in items_by_id(st)[i]["files"]})
            fix = {"id": str(max(int(i["id"]) for i in st["items"]) + 1),
                   "title": f"Fix the task checks ({st['auto_fixes']})",
                   "goal": f"The task check `{command}` exits {code} after items "
                           f"{', '.join(landed)} landed. Make it pass without undoing "
                           f"what those items added. Log tail:\n{tail(log, 15)}",
                   "covers": [], "files": files, "check_cmd": list(st["check_cmd"]), "check": [], "needs": [],
                   "depends": [], "skill": None, "status": "pending", "tries": 0, "notes": [], "commit": None,
                   "result": None, "block": None, "run": None, "failure": None, "origin": "task_checks"}
            st["items"].append(fix)
            task.event("fix_added", fix["id"], {"command": command, "log": log})
            write_plan_file(task, st)
    groups = plan_runs(st)
    if groups:
        runs = start_runs(task, st, groups)
        task.save(st)
        if runs[0]["self"]:
            return {**out, "action": "do_yourself", "items": runs[0]["items"], "brief": runs[0]["brief"],
                    "next": f"read the brief and do its items yourself, then {nxt}"}
        return {**out, "action": "dispatch",
                "runs": [{"run": r["id"], "items": r["items"], "prompt": prompt_for(r["brief"])} for r in runs],
                "next": f"start exactly {len(runs)} executor(s), one per prompt, in the foreground and all at once; "
                        "pass each prompt unchanged (it is one executor's whole job, never shared or split); "
                        f"when every one has replied, {nxt}"}
    blocked = [it for it in st["items"] if it["status"] == "blocked"]
    live_needs = {q for it in st["items"] if it["status"] in ("pending", "blocked") for q in it["needs"]}
    waiting = [q for q in st["questions"] if q["answer"] is None and q["id"] in live_needs]
    if blocked or waiting:
        return do_stop(task, st, "needs_user", "; ".join(
            [f"{q['id']}: {q['text']}" for q in waiting]
            + [f"item {it['id']} asks approval: {it['block']['text']}" for it in blocked
               if it["block"]["kind"] == "approval"]))
    for it in st["items"]:  # nothing can start: what is left waits on failed work
        if it["status"] == "pending":
            fail_item(task, st, it, "it waits on work that cannot finish")
    if review_due(st):
        brief = start_review(task, st)
        task.save(st)
        return {**out, "action": "review", "prompt": prompt_for(brief),
                "next": "tell the user now that the work has landed and its checks pass, with a review still to "
                        f"come; then start one read-only executor with the prompt, in the foreground; when it "
                        f"replies, {nxt}"}
    task.save(st)
    if "review" in out:
        return {**out, "action": "finish",
                "next": f"read the review; for each finding to fix, add an item to {task.plan_path}, run "
                        f"{cmd_line(task, 'plan')}, then {nxt}; keep the rest as named gaps; with nothing to fix, "
                        f"{cmd_line(task, 'finish')}"}
    return {"action": "report", **out, **finish_now(task, st)}


def qview(q):
    return {k: q.get(k) for k in ("id", "type", "text", "default", "because")}


def do_stop(task, st, condition, detail):
    st["status"], st["stop"] = "stopped", {"condition": condition, "detail": detail, "at": _now()}
    for q in st["questions"]:
        if q["answer"] is None and not q["asked"]:
            q["asked"] = True
            task.event("question_asked", q["id"], {"type": q["type"], "round": 2})
    task.event("stopped", None, {"condition": condition, "detail": detail})
    task.save(st)
    return stop_action(task, st)


def stop_action(task, st):
    stop = st["stop"]
    approvals = [it["id"] for it in st["items"] if it["status"] == "blocked" and it["block"]["kind"] == "approval"]
    how = [f"record answers with {cmd_line(task, 'answer', '--id', '<Q>', '--text', shlex.quote('<reply>'))}"]
    if approvals:
        how.append(f"then {cmd_line(task, 'resume', '--approve', '<ids>', '--deny', '<ids>')} as the user said")
    else:
        how.append(f"then {cmd_line(task, 'resume')}")
    return {"action": "stop", "condition": stop["condition"], "detail": stop["detail"],
            "questions": [qview(q) for q in st["questions"] if q["answer"] is None], "approvals": approvals,
            "next": "tell the user what the stop needs, all in one message, and wait for the reply; never approve "
                    "a step yourself. After the reply: " + ", ".join(how)}


def cmd_next(task, a):
    return locked(task, lambda st: advance(task, st))


def cmd_plan(task, a):
    plan = read_plan_file(a.file or task.plan_path)

    def go(st):
        if st["status"] == "complete":
            raise Fail("task_complete", "the task is complete; `mark --mark reworked` reopens it", 1)
        out = apply_plan(st, plan, task)
        task.event("plan_changed", None, out)
        task.save(st)
        return {**out, "next": cmd_line(task, "next")}
    return locked(task, go)


def cmd_answer(task, a):
    def go(st):
        qs = {q["id"]: q for q in st["questions"]}
        if a.defaults:
            todo = [(q, q["default"], "default_accepted") for q in st["questions"]
                    if q["answer"] is None and q["default"]]
        else:
            if a.id not in qs:
                raise Fail("bad_input", f"no question {a.id}; questions are {', '.join(qs) or 'none'}", 2)
            if a.text is None:
                raise Fail("bad_input", "give --text, or --defaults", 2)
            todo = [(qs[a.id], a.text, a.source)]
        out = []
        for q, text, source in todo:
            changed = q["answer"] is not None and q["answer"] != text
            affected = [it["id"] for it in st["items"] if q["id"] in it["needs"] and it["status"] == "done"]
            q.update(answer=text, answer_source=source)
            if changed:
                q["changed_at"] = _now()
                q["affected"] = sorted(set(q["affected"]) | set(affected), key=int)
            for it in st["items"]:
                if it["status"] == "blocked" and it["block"].get("question") == q["id"]:
                    it.update(status="pending", block=None)
            task.event("answered", q["id"], {"source": source, "changed": changed})
            out.append({"id": q["id"], "answer": text, "source": source, **({"affected": affected} if changed else {})})
        task.save(st)
        return {"answered": out, "next": cmd_line(task, "resume") if st["status"] == "stopped"
                else cmd_line(task, "next")}
    return locked(task, go)


def cmd_done(task, a):
    st = task.load()
    it = items_by_id(st).get(a.id)
    if it is None:
        raise Fail("bad_input", f"no item {a.id}", 2)
    if it["status"] == "done":
        return {"id": it["id"], "status": "done", "commit": it["commit"], "next": next_in_run(task, st, it)}
    if it["status"] != "running":
        why = f" ({it['failure']})" if it["failure"] else ""
        raise Fail("not_running", f"item {a.id} is {it['status']}{why}, so it is not yours to finish now", 1,
                   "needs_fix", "skip it: " + next_in_run(task, st, it))
    run = next(r for r in st["runs"] if r["id"] == it["run"])
    first = next(i for i in run["items"] if items_by_id(st)[i]["status"] == "running")
    if first != it["id"]:  # two executors on one brief would commit each other's half-made edits
        raise Fail("out_of_order", f"item {first} comes before item {a.id} in this brief", 1, "needs_fix",
                   f"one executor does a brief's items in order: do item {first} first. If you were told to do "
                   "only part of the brief, change nothing and reply `this brief was given to several executors`")
    top = git_top(run["dir"]) if st["git_top"] else None
    mine, stray = [], []
    if top:
        # ponytail: new untracked files outside the item (build and test output, mostly) are left alone and
        # named, not refused; a source file created outside the plan shows in that list, uncommitted
        changed = changed_since(run["dir"], top, run["snapshot"])
        others = [f for o in st["items"] if o["status"] == "running" and o["run"] != run["id"]
                  and next(r for r in st["runs"] if r["id"] == o["run"])["dir"] == run["dir"] for f in o["files"]]
        outside = [p for p, h in changed.items() if not covered(p, it["files"]) and not untracked(h)
                   and not (not it["files"] and covered(p, others))]
        stray = [p for p, h in changed.items() if not covered(p, it["files"]) and untracked(h)
                 and p not in run.get("links", [])]
        if outside:
            if not it["files"]:
                raise Fail("outside_files", f"item {a.id} is read-only, but these changed: {', '.join(outside)}",
                           1, "needs_fix", "undo those changes; write only the result file")
            raise Fail("outside_files", f"item {a.id} may change only {', '.join(it['files'])}; also changed: "
                       f"{', '.join(outside)}", 1, "needs_fix",
                       "undo those changes (an item later in your run does its own files), or ask with "
                       f"{cmd_line(task, 'block', a.id, '--approval', shlex.quote('change <file>: <why>'))}")
        mine = [p for p in changed if covered(p, it["files"])] if it["files"] else []
        if it["files"] and not mine and not a.no_change:
            sha = landed_commit(run["dir"], st, it)
            if sha:
                return finish_item(task, it["id"], sha, None)
            raise Fail("no_changes", f"item {a.id}'s files are unchanged under {run['dir']}", 1, "needs_fix",
                       f"do the goal; if it truly needs no change, rerun with --no-change \"<why>\"")
    if not it["files"]:
        rp = a.result or result_path(task, it)
        if not os.path.isfile(rp) or not os.path.getsize(rp):
            raise Fail("no_result", f"item {a.id} has no result at {rp}", 1, "needs_fix",
                       f"write the result to {rp}, then run done again")
    attempt = it["tries"] + 1
    results = run_checks(task, it["check_cmd"], run["dir"], f"{it['id']}-{attempt}", st["check_timeout_s"])
    bad = next(((c, code, log) for c, code, log in results if code != 0), None)
    if bad:
        command, code, log = bad
        why = check_unrunnable(command, code, tail(log, 200)) if code is not None else None
        if why:
            raise Fail("check_broken", f"`{command}` could not run: {why}. This does not count as a try.\n"
                       f"{tail(log, 10)}", 1, "needs_fix",
                       f"if the command itself is wrong, {cmd_line(task, 'block', a.id, '--question', shlex.quote('the check `<cmd>` is wrong: <why>'))}")
        return fail_try(task, a.id, command, code, log, run, mine)
    sha = None
    if it["files"] and top and mine:
        sha = commit_item(run["dir"], st, it, mine)
    out = finish_item(task, it["id"], sha, a.result and os.path.abspath(a.result),
                      [f for f in it["files"] if top and not any(covered(p, [f]) for p in mine)])
    if stray:
        out["not_committed"] = stray[:20]
    return out


def fail_try(task, item_id, command, code, log, run, mine):
    def go(st):
        it = items_by_id(st)[item_id]
        it["tries"] += 1
        what = "timed out" if code is None else f"exited {code}"
        if it["tries"] < TRIES:
            task.event("item_retried", item_id, {"reason": f"`{command}` {what}", "log": log})
            task.save(st)
            return None
        kept = shelve(task, run, mine, f"{item_id}.patch")
        fail_item(task, st, it, f"`{command}` {what} on all {TRIES} tries; log {log}"
                  + (f"; its last diff {kept}" if kept else ""))
        task.save(st)
        return it
    failed = locked(task, go)
    st = task.load()
    if failed is None:
        it = items_by_id(st)[item_id]
        raise Fail("check_failed", f"`{command}` {'timed out' if code is None else f'exited {code}'} "
                   f"(try {it['tries']} of {TRIES}). Log {log}, last lines:\n{tail(log)}", 1, "needs_fix",
                   f"fix the work, then {cmd_line(task, 'done', item_id)}")
    raise Fail("item_failed", f"item {item_id} failed {TRIES} tries; its files are back as they were", 1,
               "needs_fix", next_in_run(task, st, failed))


def shelve(task, run, paths, name):
    """Save the diff of `paths` to patches/<name> and put the files back as at HEAD. Returns a phrase for a
    note, or None when there was nothing to save. Files stay as they are when the patch cannot be written."""
    if not paths or not git_top(run["dir"]):
        return None
    patch = os.path.join(task.dir, "patches", name)
    try:
        save_patch(run["dir"], paths, patch)
    except (Fail, OSError) as e:
        return f"could not be saved ({e}), so its files are left as they were"
    restore_paths(run["dir"], paths)
    return f"is saved at {patch} (`git apply` it to reuse it)"


def landed_commit(run_dir, st, it):
    """The commit an earlier `done` made for this item, when the state write after it was lost."""
    return item_commits(run_dir, st).get(it["id"])


def commit_item(run_dir, st, it, paths):
    add_paths(run_dir, paths)
    msg = ["-m", it["title"], "-m", f"{it['goal'][:600]}", "-m", f"AD-Item: {st['task_id']}/{it['id']}"]
    p = git(run_dir, "commit", "-q", *msg, "--", *paths, check=False)
    if p.returncode != 0:
        raise Fail("commit_failed", f"git commit failed (a hook or the git identity): "
                   f"{(p.stderr or p.stdout).strip()[-800:]}", 1, "needs_fix",
                   "fix what the message names (a failing hook is part of the work), then run done again")
    return head(run_dir)


def finish_item(task, item_id, sha, result, untouched=()):
    def go(st):
        it = items_by_id(st)[item_id]
        it.update(status="done", commit=sha, block=None, untouched=list(untouched))
        if result:
            it["result"] = result
        task.event("item_done", item_id, {"commit": sha, "tries": it["tries"] + 1})
        task.save(st)
        return {"id": item_id, "status": "done", "commit": sha, "next": next_in_run(task, st, it)}
    return locked(task, go)


def next_in_run(task, st, it):
    run = next((r for r in st["runs"] if r["id"] == it.get("run")), None)
    if run is None:
        return "go on with your brief"
    by = items_by_id(st)
    left = [i for i in run["items"] if by[i]["status"] == "running"]
    if left:
        return f"next item: {left[0]} {by[left[0]]['title']}"
    if run.get("self"):
        return f"every item in the brief is finished: run {cmd_line(task, 'next')}"
    return "every item in your brief is finished: reply with one line per item"


def cmd_block(task, a):
    if bool(a.question) == bool(a.approval):
        raise Fail("bad_input", "give exactly one of --question or --approval", 2)

    def go(st):
        it = items_by_id(st).get(a.id)
        if it is None or it["status"] != "running":
            raise Fail("not_running", f"item {a.id} is not running", 1)
        block = {"kind": "question" if a.question else "approval", "text": a.question or a.approval}
        if a.question:
            q = {"id": f"Q{len(st['questions']) + 1}", "type": "user_only", "text": a.question,
                 "default": a.default or "", "because": f"asked by item {a.id}", "asked": False, "answer": None,
                 "answer_source": None, "changed_at": None, "affected": [], "origin": "block"}
            st["questions"].append(q)
            it["needs"].append(q["id"])
            block["question"] = q["id"]
        run = next(r for r in st["runs"] if r["id"] == it["run"])
        top = git_top(run["dir"]) if st["git_top"] and it["files"] else None
        mine = [p for p in changed_since(run["dir"], top, run["snapshot"]) if covered(p, it["files"])] if top else []
        kept = shelve(task, run, mine, f"{a.id}-blocked.patch")
        if kept:
            it["notes"].append(f"Work from before the block {kept}")
        it.update(status="blocked", block=block)
        task.event("item_blocked", a.id, block)
        task.save(st)
        return {"id": a.id, "status": "blocked", "next": next_in_run(task, st, it)}
    return locked(task, go)


def cmd_decide(task, a):
    def go(st):
        rejected = []
        for r in a.reject:
            opt, sep, why = r.partition("::")
            if not sep or not opt.strip() or not why.strip():
                raise Fail("bad_input", f"--reject {r!r}: write \"<option>::<why it lost>\"", 2)
            rejected.append({"option": opt.strip(), "why": why.strip()})
        if not (a.criteria or a.because):
            raise Fail("bad_input", "give --criteria <Q-ids> or --because \"<evidence>\"", 2)
        d = {"id": f"D{len(st['decisions']) + 1}", "question": a.question, "chosen": a.chosen, "rejected": rejected,
             "criteria": _csv(a.criteria), "because": a.because, "supersedes": a.supersedes, "superseded_by": None}
        if a.supersedes:
            old = next((x for x in st["decisions"] if x["id"] == a.supersedes), None)
            if old is None:
                raise Fail("bad_input", f"no decision {a.supersedes}", 2)
            old["superseded_by"] = d["id"]
        st["decisions"].append(d)
        task.event("decided", d["id"], {"chosen": a.chosen})
        task.save(st)
        return {"id": d["id"]}
    return locked(task, go)


def cmd_status(task, a):
    st = task.load()
    active = [r for r in st["runs"] if r["status"] == "active"]
    if st["status"] == "stopped":
        nxt = "tell the user what the stop needs; after the reply: answer, then " + cmd_line(task, "resume")
    elif st["status"] == "complete":
        nxt = "report the result; mark after the user replies"
    elif st["status"] == "handed_back":
        nxt = "none: the task was handed back"
    else:
        nxt = cmd_line(task, "next") + (" (once every executor of the active runs has replied; after a new session "
                                        "or compaction run it now: it restarts their unfinished items)"
                                        if active else "")
    return {"question": st["question"], "status": st["status"], "stop": st["stop"],
            "requirements": [f"R{i + 1}: {r}" for i, r in enumerate(st["requirements"])],
            "items": [{k: it.get(k) for k in ("id", "title", "status", "files", "tries", "commit", "result", "block",
                                              "failure", "skill")} for it in st["items"]],
            "answers": [{**qview(q), "answer": q["answer"], "source": q["answer_source"], "affected": q["affected"]}
                        for q in st["questions"]],
            "decisions": st["decisions"], "active_runs": [{"run": r["id"], "items": r["items"], "brief": r["brief"]}
                                                          for r in active],
            "plan": task.plan_path, "next": nxt}


def cmd_resume(task, a):
    def go(st):
        if st["status"] == "handed_back":
            return {"status": "handed_back", "next": "none: stop using this method on this task"}
        by = items_by_id(st)
        for ids, ok in ((_csv(a.approve), True), (_csv(a.deny), False)):
            for i in ids:
                it = by.get(i)
                if it is None or it["status"] != "blocked" or it["block"]["kind"] != "approval":
                    raise Fail("bad_input", f"item {i} is not waiting for an approval", 2)
                text = it["block"]["text"]
                it["notes"].append(f"The user approved: {text}" if ok else
                                   f"The user refused: {text}. Reach the goal without it.")
                it.update(status="pending", block=None)
                task.event("approval", i, {"approved": ok, "step": text})
        was = st["stop"]
        st["status"], st["stop"] = "active", None
        task.event("resumed", None, {"stop": was, "new_session": a.new_session})
        task.save(st)
        return {"status": "active", "was": was, "next": cmd_line(task, "next")}
    return locked(task, go)


def cmd_stop(task, a):
    def go(st):
        do_stop(task, st, a.condition, a.detail)
        return {"status": "stopped", "next": "tell the user why; continue only after their reply, with resume"}
    return locked(task, go)


def cmd_finish(task, a):
    return locked(task, lambda st: finish_now(task, st))


def finish_now(task, st):
    if st["status"] == "stopped":
        raise Fail("task_stopped", f"the task is stopped ({st['stop']['condition']})", 1, "needs_user",
                   stop_action(task, st)["next"])
    if st["status"] == "complete":
        return summary(task, st)
    busy = [it["id"] for it in st["items"] if it["status"] in ("pending", "running", "blocked")]
    if busy or any(r["status"] == "active" for r in st["runs"]):
        raise Fail("not_finished", f"items {', '.join(busy) or 'in active runs'} are not finished", 1,
                   "needs_fix", cmd_line(task, "next"))
    if review_due(st):
        raise Fail("review_needed", "the work needs its review first", 1, "needs_fix", cmd_line(task, "next"))
    if st["git_top"]:
        now, before = dirty_files(st["git_top"], st["root"]), st.get("start_dirty", {})
        left = sorted(p for p, h in now.items() if before.get(p) != h and not untracked(h))
        st["untracked_left"] = sorted(p for p, h in now.items() if before.get(p) != h and untracked(h))[:50]
        if left:
            raise Fail("uncommitted_changes", f"files changed during the task are not committed: "
                       f"{', '.join(left)}", 1, "needs_fix",
                       "a change belongs to an item: add an item for it to the plan (plan, next), or, if it is "
                       "stray, ask the user before undoing it")
    failed = task_checks(task, st, "finish") if any(it["status"] == "done" and it["files"]
                                                    for it in st["items"]) else None
    if failed:
        command, code, log = failed
        raise Fail("checks_failed", f"task check `{command}` exits {code}; log {log}:\n{tail(log, 15)}", 1,
                   "needs_fix", f"add a fix item to {task.plan_path}, run plan, then next")
    if st["git_top"]:
        for r in st["runs"]:
            if r.get("worktree") and os.path.isdir(r["worktree"]):
                git(st["git_top"], "worktree", "remove", "--force", r["worktree"], check=False)
                git(st["git_top"], "branch", "-D", r["branch"], check=False)
    st["status"] = "complete"
    st["finished_at"] = _now()
    task.event("stopped", None, {"condition": "complete"})
    task.save(st)
    return summary(task, st)


def summary(task, st):
    rec = task.record()
    items = [it for it in st["items"] if it["status"] != "dropped"]
    tokens = [l["data"] for l in rec if l["event"] == "tokens"]
    end = st.get("finished_at") or _now()
    return {"question": st["question"], "status": st["status"],
            "items": [{k: it[k] for k in ("id", "title", "status", "commit", "result", "skill")} for it in items],
            "failed": [{"id": it["id"], "title": it["title"], "why": it["failure"]}
                       for it in items if it["status"] == "failed"],
            "decisions": st["decisions"],
            "unconfirmed_defaults": [qview(q) for q in st["questions"] if q["answer_source"] == "default_unconfirmed"],
            "changed_answers": [{"id": q["id"], "affected": q["affected"]} for q in st["questions"] if q["changed_at"]],
            "review": os.path.join(task.dir, "review.md") if st["review_state"] == "done" else None,
            "untracked_left": st.get("untracked_left", []),
            "cost": {"wall_s": round((_ts(end) - _ts(st["started_at"])).total_seconds()),
                     "runs": len([r for r in st["runs"] if r["kind"] == "work"]),
                     "parallel_runs": len([r for r in st["runs"] if r.get("worktree")]),
                     "tries": sum(it["tries"] + (it["status"] == "done") for it in items),
                     "done": sum(it["status"] == "done" for it in items),
                     "failed": sum(it["status"] == "failed" for it in items),
                     "tokens": tokens[-1] if tokens else None},
            "next": "write the report (answer first); mark after the user replies"}


def cmd_mark(task, a):
    def go(st):
        if st["status"] != "complete":
            raise Fail("not_complete", "mark a task after finish", 1, "needs_fix", cmd_line(task, "finish"))
        if a.mark == "reworked" and not a.reason:
            raise Fail("bad_input", "a reworked mark needs --reason", 2)
        st["mark"] = {"mark": a.mark, "reason": a.reason}
        if a.mark == "reworked":
            st["status"], st["review_state"] = "active", "none"
        task.event("marked", None, {"mark": a.mark, "reason": a.reason})
        task.save(st)
        return {"mark": a.mark, "next": (f"edit {task.plan_path} for the rework, run plan, then next"
                                         if a.mark == "reworked" else "nothing more")}
    return locked(task, go)


def cmd_log(task, a):
    def go(st):
        data = json.loads(a.data) if a.data else {}
        if a.event == "wrong_engagement":
            st["status"] = "handed_back"
        task.event(a.event, a.ref, data)
        task.save(st)
        return {"logged": a.event, "next": "carry on as normal work, without this method"
                if a.event == "wrong_engagement" else cmd_line(task, "status")}
    try:
        return locked(task, go)
    except ValueError as e:
        raise Fail("bad_input", f"--data is not JSON: {e}", 2)


# ---------------------------------------------------------------- entry

def build_parser():
    p = Parser(prog="decompose.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = p.add_subparsers(dest="command", required=True, parser_class=Parser)

    def cmd(name, help_text, task=True):
        s = sub.add_parser(name, help=help_text, description=help_text)
        if task:
            s.add_argument("--task", required=True, help="the task folder start printed")
        return s

    s = cmd("start", "Create a task from a plan file; prints the questions to ask, or the first action.", task=False)
    s.add_argument("--plan", required=True, help="plan JSON file, or - for stdin (SKILL.md shows the format)")
    s.add_argument("--statement", required=True, help="the user's request, verbatim")
    s.add_argument("--root", default=".", help="the folder the items change, where their file paths start "
                                               "(default: the current folder)")
    s.add_argument("--new-files", action="store_true", help="every planned file is new")
    s.add_argument("--mode", choices=("auto", "delegate", "main_session"), default="auto",
                   help="auto: one run is done in the main session, more go to executors; delegate: always "
                        "executors; main_session: everything in the main session")
    s.add_argument("--max-parallel", type=int, default=MAX_PARALLEL, help="most runs at once")
    s.add_argument("--review", choices=("auto", "always", "never"), default="auto",
                   help="auto: review the work that executors did, not the coordinator's own")
    s = cmd("plan", "Apply an edited plan file (default: the task's plan.json) to the items not started.")
    s.add_argument("file", nargs="?")
    s = cmd("answer", "Record an answer; --defaults accepts every open question's default.")
    s.add_argument("--id")
    s.add_argument("--text")
    s.add_argument("--source", choices=SOURCES, default="user")
    s.add_argument("--defaults", action="store_true")
    cmd("next", "Land finished runs, run the task checks, and print the next action.")
    s = cmd("done", "Executor: run an item's checks and commit it.")
    s.add_argument("id")
    s.add_argument("--result", help="a read-only item's result file (default: the path its brief names)")
    s.add_argument("--no-change", help="why the item needs no file change")
    s = cmd("block", "Executor: park an item on a question for the user or an approval.")
    s.add_argument("id")
    s.add_argument("--question")
    s.add_argument("--default", help="the answer you would act on")
    s.add_argument("--approval", help="the step outside the goal")
    s = cmd("decide", "Record a choice, its criteria and each rejected option.")
    s.add_argument("--question", required=True)
    s.add_argument("--chosen", required=True)
    s.add_argument("--reject", action="append", default=[], help="\"<option>::<why it lost>\", once per option")
    s.add_argument("--criteria", help="question ids holding the criteria")
    s.add_argument("--because", help="workspace evidence, when no question holds the criteria")
    s.add_argument("--supersedes")
    cmd("status", "Print the plan, answers, decisions, progress and the next command.")
    s = cmd("resume", "Restart a stopped task after the user replied.")
    s.add_argument("--approve", help="item ids whose step the user approved")
    s.add_argument("--deny", help="item ids whose step the user refused")
    s.add_argument("--new-session", action="store_true")
    s = cmd("stop", "Stop the task.")
    s.add_argument("--condition", choices=("user", "fault"), required=True)
    s.add_argument("--detail", required=True)
    cmd("finish", "Check that everything is committed and passes; complete the task and print its summary.")
    s = cmd("mark", "Record the user's mark.")
    s.add_argument("--mark", choices=("accepted", "reworked", "unmarked"), required=True)
    s.add_argument("--reason")
    s = cmd("log", "Record a run-record event.")
    s.add_argument("event", choices=LOG_EVENTS)
    s.add_argument("--ref")
    s.add_argument("--data", help="JSON object")
    return p


COMMANDS = {"next": cmd_next, "plan": cmd_plan, "answer": cmd_answer, "done": cmd_done, "block": cmd_block,
            "decide": cmd_decide, "status": cmd_status, "resume": cmd_resume, "stop": cmd_stop,
            "finish": cmd_finish, "mark": cmd_mark, "log": cmd_log}
ANY_STATUS = {"status", "answer", "resume", "stop", "log", "mark", "finish", "next", "done", "block"}


def run(argv):
    a = build_parser().parse_args(argv)
    if a.command == "start":
        return cmd_start(a)
    task = Task(a.task)
    if not os.path.isfile(task.state_path):
        raise Fail("bad_input", f"no task at {task.dir} (no state.json)", 2)
    if a.command not in ANY_STATUS and task.load()["status"] == "stopped":
        raise Fail("task_stopped", "the task is stopped", 1, "needs_user", stop_action(task, task.load())["next"])
    return COMMANDS[a.command](task, a)


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        out = run(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 0
    except Fail as e:
        print(f"ERROR [{e.code}] {e.message}\nresolves: {e.resolves}\nnext: {e.nxt or 'see --help'}", file=sys.stderr)
        return e.exit_code
    print(json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
