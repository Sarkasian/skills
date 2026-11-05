#!/usr/bin/env python3
"""Task state script for the atomic-decompose skill (standard library only).

Run `python3 decompose.py <command> --help` for each command's flags.
Every command except `init` takes `--task <task-dir>`. JSON on stdout
(except `brief` and `handoff`, which print text); errors on stderr as

    ERROR [<code>] <message>
    resolves: auto_retry | needs_fix | needs_user
    next: <exact command>

Exit codes: 0 ok, 1 a check failed, 2 bad input, 3 saved-state fault.
"""
from __future__ import annotations

import argparse
import datetime as _dt
import json
import os
import re
import secrets
import shlex
import shutil
import sys

SCHEMA = 1
RETRY_LIMIT = 2  # DD-12: at most RETRY_LIMIT + 1 attempts
DEFAULT_MAX_BATCH = 4
DEFAULT_MAX_PARALLEL = 4
SUMMARY_WORDS = 150
WRITERS = {"init", "stop", "resume", "finish", "mark", "log", "add", "drop",
           "ask", "asked", "answer", "brief", "complete", "decide"}
LOG_EVENTS = ("compaction", "asked_again", "wrong_engagement", "tokens")
SCRIPT = os.path.abspath(__file__)
LEAF_ONLY = ("goal", "checklist", "returns", "discovers", "small")


class Fail(Exception):
    def __init__(self, code, message, exit_code=2, resolves="needs_fix", nxt=""):
        super().__init__(message)
        self.code, self.message, self.exit_code = code, message, exit_code
        self.resolves, self.nxt = resolves, nxt


class Parser(argparse.ArgumentParser):
    def error(self, message):
        raise Fail("bad_input", message, 2, "needs_fix", f"{self.prog} --help")


def _now():
    return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def _append_line(path, text):
    with open(path, "a", encoding="utf-8") as f:
        f.write(text + "\n")


def _key(item_id):
    return tuple(int(p) for p in item_id.split("."))


def _parent(item_id):
    return item_id.rsplit(".", 1)[0] if "." in item_id else "root"


def _csv(value):
    return [v.strip() for v in value.split(",") if v.strip()] if value else []


# ---------------------------------------------------------------- state access

class Task:
    def __init__(self, task_dir):
        self.dir = os.path.abspath(task_dir)
        self.state_path = os.path.join(self.dir, "state.json")
        self.record_path = os.path.join(self.dir, "record.jsonl")
        self.lock_path = os.path.join(self.dir, ".lock")

    def load(self):
        try:
            with open(self.state_path, encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError) as e:
            raise Fail("state_unreadable", f"cannot read {self.state_path}: {e}", 3, "needs_user",
                       "restore state.json or start a new task")
        if st.get("schema_version") != SCHEMA:
            raise Fail("state_unreadable",
                       f"{self.state_path} has schema_version {st.get('schema_version')!r}, this script reads {SCHEMA}",
                       3, "needs_user", "finish the task with the script version that started it")
        return st

    def record_lines(self):
        """Return (parsed lines, torn last line text or None)."""
        if not os.path.exists(self.record_path):
            return [], None
        with open(self.record_path, encoding="utf-8") as f:
            raw = f.read()
        lines = raw.split("\n")
        if lines and lines[-1] == "":
            lines.pop()
        parsed, torn = [], None
        for i, line in enumerate(lines):
            try:
                parsed.append(json.loads(line))
            except ValueError:
                if i == len(lines) - 1:
                    torn = line
                else:
                    raise Fail("state_unreadable", f"{self.record_path} line {i + 1} does not parse", 3,
                               "needs_user", "restore record.jsonl")
        return parsed, torn

    def lock(self):
        try:
            fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
            os.close(fd)
        except FileExistsError:
            raise Fail("task_locked", f"{self.lock_path} exists: another command holds it or a crash left it",
                       3, "needs_user", f"rm {shlex.quote(self.lock_path)}")

    def unlock(self):
        try:
            os.remove(self.lock_path)
        except FileNotFoundError:
            pass


class Writer:
    """Appends one invocation's DM-5 lines (record first), then replaces state.json."""

    def __init__(self, task, st, argv, cmd=None, next_seq=None, first_line_written=False):
        self.task, self.st = task, st
        self.cmd = cmd or secrets.token_hex(8)
        self.argv = argv
        self.first_written = first_line_written
        self.seq = next_seq if next_seq is not None else st.get("applied_seq", 0) + 1
        self.last = None

    def event(self, event, ref=None, data=None):
        line = {"seq": self.seq, "ts": _now(), "cmd": self.cmd,
                "argv": None if self.first_written else self.argv,
                "event": event, "ref": ref, "data": data or {}}
        try:
            _append_line(self.task.record_path, json.dumps(line, ensure_ascii=False))
        except OSError as e:
            raise Fail("record_write_failed", f"cannot append to {self.task.record_path}: {e}; state.json unchanged",
                       3, "auto_retry", f"python3 {SCRIPT} resume --task {shlex.quote(self.task.dir)}")
        self.first_written = True
        self.seq += 1
        self.last = line

    def commit(self):
        if self.last:
            self.st["applied_seq"] = self.last["seq"]
            self.st["updated_at"] = self.last["ts"]
        write_state(self.task, self.st)


def write_state(task, st):
    tmp = os.path.join(task.dir, f".state.{secrets.token_hex(4)}.tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(st, f, ensure_ascii=False, indent=1)
    try:
        os.replace(tmp, task.state_path)
    except OSError as e:
        try:
            os.remove(tmp)
        except OSError:
            pass
        raise Fail("state_write_failed",
                   f"cannot replace {task.state_path}: {e}; record.jsonl holds the change",
                   3, "auto_retry", f"python3 {SCRIPT} resume --task {shlex.quote(task.dir)}")


# ---------------------------------------------------------------- plan helpers

def items_by_id(st):
    return {it["id"]: it for it in st["items"]}


def children(st, pid, live_only=True):
    return [it for it in st["items"] if _parent(it["id"]) == pid
            and (not live_only or it["status"] != "dropped")]


def descendants(st, pid):
    return [it for it in st["items"] if it["id"].startswith(pid + ".")]


def discoverer(st, gid):
    for it in st["items"]:
        if it["kind"] == "leaf" and it.get("discovers") == gid:
            return it
    return None


def dep_leaves(st, dep_id):
    """Leaves a depends_on entry stands for: itself, or a group's non-dropped descendant leaves."""
    it = items_by_id(st).get(dep_id)
    if not it:
        return []
    if it["kind"] == "leaf":
        return [it]
    return [d for d in descendants(st, dep_id) if d["kind"] == "leaf" and d["status"] != "dropped"]


def dep_met(st, dep_id):
    it = items_by_id(st).get(dep_id)
    if not it or it["status"] == "dropped":
        return False
    leaves = dep_leaves(st, dep_id)
    return bool(leaves) and all(l["status"] == "done" for l in leaves)


def needs_of(st, dep_id):
    out = []
    for leaf in dep_leaves(st, dep_id):
        for q in leaf["needs"]:
            if q not in out:
                out.append(q)
    it = items_by_id(st).get(dep_id)
    if it:
        for q in it["needs"]:
            if q not in out:
                out.append(q)
    return out


def dep_closure(st, item):
    """Every item the depends_on chain of `item` reaches (group deps include their descendants)."""
    by = items_by_id(st)
    seen, stack = [], list(item["depends_on"])
    while stack:
        d = stack.pop()
        if d in seen or d not in by:
            continue
        seen.append(d)
        stack.extend(by[d]["depends_on"])
        for desc in descendants(st, d):
            if desc["id"] not in seen:
                stack.append(desc["id"])
    return seen


def recompute_blocked(st):
    qs = {q["id"]: q for q in st["questions"]}
    for it in st["items"]:
        it["blocked_by"] = [q for q in it["needs"]
                            if q in qs and qs[q]["type"] == "user_only" and qs[q]["answer"] is None]


def propagate_needs(st):
    """Keep every item's needs a superset of the needs of the items its depends_on names."""
    changed = True
    while changed:
        changed = False
        for it in st["items"]:
            for d in it["depends_on"]:
                for q in needs_of(st, d):
                    if q not in it["needs"]:
                        it["needs"].append(q)
                        changed = True


def deferred_groups_to_expand(st):
    out = []
    for g in st["items"]:
        if g["kind"] == "group" and g["status"] != "dropped" and not children(st, g["id"]):
            d = discoverer(st, g["id"])
            if d and d["status"] == "done":
                out.append(g["id"])
    return out


def compute_next(st):
    ready, blocked = [], []
    for it in st["items"]:
        if it["kind"] != "leaf" or it["status"] != "pending":
            continue
        if it["blocked_by"]:
            blocked.append({"id": it["id"], "by": list(it["blocked_by"])})
            continue
        if all(dep_met(st, d) for d in it["depends_on"]):
            ready.append(it)
    singles, pools = [], {}
    for it in ready:
        if it.get("small") and it["attempts"] == 0 and not it.get("discovers"):
            pools.setdefault((_parent(it["id"]), it.get("skill") or ""), []).append(it)
        else:
            singles.append([it])
    batches = list(singles)
    for pool in pools.values():
        pool.sort(key=lambda x: _key(x["id"]))
        for i in range(0, len(pool), st["max_batch"]):
            batches.append(pool[i:i + st["max_batch"]])
    pending = [it for it in st["items"] if it["status"] == "pending"]

    def dependants(batch):
        ids = {b["id"] for b in batch}
        return sum(1 for p in pending if p["id"] not in ids and ids & set(dep_closure(st, p)))

    batches.sort(key=lambda b: (0 if any(x.get("discovers") for x in b) else 1, -dependants(b),
                                min(_key(x["id"]) for x in b)))
    expand = deferred_groups_to_expand(st)
    remaining = sum(1 for it in st["items"] if it["kind"] == "leaf" and it["status"] in ("pending", "running"))
    return {"mode": st["mode"], "ready": [[x["id"] for x in b] for b in batches], "blocked": blocked,
            "expand": expand, "remaining": remaining + len(expand)}


def require_item(st, item_id):
    it = items_by_id(st).get(item_id)
    if not it:
        raise Fail("unknown_ref", f"no work item {item_id}", 2, "needs_fix", "decompose.py status --task <task>")
    return it


def require_question(st, qid):
    for q in st["questions"]:
        if q["id"] == qid:
            return q
    raise Fail("unknown_ref", f"no question {qid}", 2, "needs_fix",
               "decompose.py ask --task <task> --type user_only --text <question> --default <default>")


def under_task(task, path):
    p = path if os.path.isabs(path) else os.path.join(task.dir, path)
    p = os.path.realpath(p)
    if not (p.startswith(os.path.realpath(task.dir) + os.sep) and os.path.isfile(p)):
        raise Fail("result_missing", f"{path} is not a file under {task.dir}", 2, "needs_fix",
                   "write the result file under the task folder, then run complete again")
    return os.path.relpath(p, os.path.realpath(task.dir))


def check_summary(text):
    if len(text.split()) > SUMMARY_WORDS:
        raise Fail("summary_too_long", f"summary has {len(text.split())} words, the limit is {SUMMARY_WORDS}",
                   2, "needs_fix", "shorten the summary and run complete again")


def check_skill(path):
    if not os.path.isabs(path):
        raise Fail("skill_path_not_absolute", f"--skill {path} is not absolute; expand any listing alias",
                   2, "needs_fix", "pass the absolute SKILL.md path the host lists")
    if not os.path.isfile(path):
        raise Fail("skill_missing", f"no SKILL.md at {path}", 2, "needs_user",
                   "install the skill or re-plan the item without it")


# ---------------------------------------------------------------- config (DM-9)

def config_paths(root):
    return [os.path.join(root, ".atomic-decompose", "config.local.json"),
            os.path.join(root, ".atomic-decompose", "config.json"),
            os.path.join(os.path.expanduser("~"), ".config", "atomic-decompose", "config.json")]


def _positive(path, field, value):
    if value is not None and (not isinstance(value, int) or isinstance(value, bool) or value < 1):
        raise Fail("config_unreadable", f"{path}: {field} must be an integer >= 1", 2, "needs_user",
                   f"fix {field} in {path}")


def read_configs(root):
    out = []
    for p in config_paths(root):
        if not os.path.exists(p):
            continue
        try:
            with open(p, encoding="utf-8") as f:
                c = json.load(f)
        except (OSError, ValueError) as e:
            raise Fail("config_unreadable", f"{p}: not valid JSON ({e})", 2, "needs_user", f"fix {p}")
        if not isinstance(c, dict) or c.get("schema_version") != SCHEMA:
            raise Fail("config_unreadable", f"{p}: schema_version must be {SCHEMA}", 2, "needs_user", f"fix {p}")
        _positive(p, "max_parallel", c.get("max_parallel"))
        for name, prof in (c.get("profiles") or {}).items():
            _positive(p, f"profiles.{name}.max_batch", (prof or {}).get("max_batch"))
            _positive(p, f"profiles.{name}.max_parallel", (prof or {}).get("max_parallel"))
        out.append(c)
    return out


def resolve_config(root, profile_flag):
    configs = read_configs(root)
    profile = profile_flag
    if profile is None:
        profile = next((c["profile"] for c in configs if c.get("profile")), None)
    max_batch, prof = DEFAULT_MAX_BATCH, None
    if profile is not None:
        prof = next(((c.get("profiles") or {})[profile] for c in configs
                     if profile in (c.get("profiles") or {})), None)
        if prof is None:
            raise Fail("unknown_profile", f"no configuration file defines profile {profile!r}", 2, "needs_user",
                       "add the profile to a config file or omit --profile")
        max_batch = prof.get("max_batch") or DEFAULT_MAX_BATCH
    max_parallel = next((c["max_parallel"] for c in configs if c.get("max_parallel")), DEFAULT_MAX_PARALLEL)
    if prof and prof.get("max_parallel"):
        max_parallel = min(max_parallel, prof["max_parallel"])
    return profile, max_batch, max_parallel


# ---------------------------------------------------------------- commands
# Each writing command: fn(task, st, args, w) -> output; it mutates st and emits events on w.

def cmd_stop(task, st, a, w):
    if a.condition == "complete":
        raise Fail("bad_condition", "stop --condition complete is not allowed; run finish", 2, "needs_fix",
                   "decompose.py finish --task <task>")
    st["status"], st["stop"] = "stopped", {"condition": a.condition, "detail": a.detail}
    w.event("stopped", None, {"condition": a.condition})
    return {"status": st["status"], "stop": st["stop"]}


def cmd_finish(task, st, a, w):
    open_leaves = [it["id"] for it in st["items"] if it["kind"] == "leaf" and it["status"] in ("pending", "running")]
    expand = deferred_groups_to_expand(st)
    if open_leaves or expand:
        raise Fail("open_items", f"open leaves {open_leaves}, groups to expand {expand}", 1, "needs_fix",
                   "decompose.py next --task <task>")
    st["status"], st["stop"] = "complete", {"condition": "complete", "detail": "every leaf done or failed"}
    w.event("stopped", None, {"condition": "complete"})
    return {"status": st["status"], "stop": st["stop"]}


def cmd_mark(task, st, a, w):
    if st["status"] != "complete":
        raise Fail("not_complete", "mark needs a complete task; run finish first", 2, "needs_fix",
                   "decompose.py finish --task <task>")
    if a.mark == "reworked":
        st["status"], st["stop"] = "active", None
    w.event("marked", None, {"mark": a.mark, "reason": a.reason})
    return {"status": st["status"], "stop": st["stop"]}


def cmd_log(task, st, a, w):
    data = {}
    if a.data:
        try:
            data = json.loads(a.data)
        except ValueError as e:
            raise Fail("bad_input", f"--data is not JSON: {e}", 2)
    if a.event == "wrong_engagement":
        st["status"] = "handed_back"
    w.event(a.event, a.ref, data)
    return {"event": a.event}


def cmd_add(task, st, a, w):
    by = items_by_id(st)
    if a.parent != "root":
        parent = by.get(a.parent)
        if not parent:
            raise Fail("unknown_parent", f"no item {a.parent}", 2)
        if parent["kind"] == "leaf" and parent.get("discovers"):
            raise Fail("parent_is_discovery", f"{a.parent} is a discovery leaf and cannot have children", 2)
        if parent["status"] != "pending":
            raise Fail("parent_not_pending", f"{a.parent} is {parent['status']}", 2)
    if any(it["title"] == a.title for it in st["items"]):
        raise Fail("duplicate_title", f"an item already has the title {a.title!r}", 2, "needs_fix",
                   "give the item a new title")
    if a.kind == "leaf":
        if not a.goal:
            raise Fail("leaf_without_goal", "a leaf needs --goal", 2)
        if not a.check:
            raise Fail("leaf_without_checklist", "a leaf needs at least one --check", 2)
        if not a.returns:
            raise Fail("leaf_without_returns", "a leaf needs --returns", 2)
    needs, depends = _csv(a.needs), _csv(a.depends)
    qids = {q["id"] for q in st["questions"]}
    for q in needs:
        if q not in qids:
            raise Fail("unknown_ref", f"no question {q}", 2)
    for d in depends:
        if d not in by:
            raise Fail("unknown_ref", f"no item {d}", 2)
        if by[d]["status"] == "dropped":
            raise Fail("dangling_dependency", f"{d} is dropped; depend on the item that replaces it, or on none", 2)
    if a.skill:
        check_skill(a.skill)
    if a.discovers:
        g = by.get(a.discovers)
        if (a.kind != "leaf" or not g or g["kind"] != "group" or children(st, g["id"])
                or discoverer(st, g["id"]) or a.parent == g["id"] or a.parent.startswith(g["id"] + ".")):
            raise Fail("not_deferrable", f"{a.discovers} is not a childless group without a discovery leaf", 2)
    if a.parent != "root":
        parent = by[a.parent]
        if parent["kind"] == "leaf":
            parent["kind"] = "group"
            for f in LEAF_ONLY:
                parent.pop(f, None)
            parent.update(summary=None, result=None, attempts=0)
    sibs = [it for it in st["items"] if _parent(it["id"]) == a.parent]
    n = max((_key(s["id"])[-1] for s in sibs), default=0) + 1
    new_id = str(n) if a.parent == "root" else f"{a.parent}.{n}"
    item = {"id": new_id, "title": a.title, "kind": a.kind, "needs": needs, "depends_on": depends,
            "blocked_by": [], "skill": a.skill, "status": "pending", "attempts": 0, "briefs": 0,
            "result": None, "summary": None}
    if a.kind == "leaf":
        item.update(goal=a.goal, checklist=list(a.check), returns=a.returns, discovers=a.discovers,
                    small=bool(a.small))
    st["items"].append(item)
    propagate_needs(st)
    recompute_blocked(st)
    w.event("item_planned", new_id)
    return {"id": new_id}


def _drop(st, w, ids, cause):
    by = items_by_id(st)
    out = []
    for i in ids:
        if by[i]["status"] != "dropped":
            by[i]["status"] = "dropped"
            w.event("item_dropped", i, {"cause": cause})
            out.append(i)
    return out


def cmd_drop(task, st, a, w):
    it = require_item(st, a.id)
    to_drop = []
    if it["kind"] == "leaf":
        if it["status"] in ("running", "done", "failed"):
            raise Fail("not_droppable", f"{a.id} is {it['status']}", 2)
        to_drop.append(it["id"])
    else:
        desc = sorted(descendants(st, it["id"]), key=lambda x: _key(x["id"]), reverse=True)
        for d in desc:
            if d["kind"] == "leaf" and d["status"] == "pending":
                to_drop.append(d["id"])
        live = [d for d in desc if d["kind"] == "leaf" and d["status"] in ("running", "done", "failed")]
        for d in desc:
            if d["kind"] == "group" and not any(l["id"].startswith(d["id"] + ".") for l in live):
                to_drop.append(d["id"])
        if not live:
            to_drop.append(it["id"])
    dropped = _drop(st, w, to_drop, a.cause)
    extra = []
    for i in dropped:
        leaf = items_by_id(st)[i]
        g = leaf.get("discovers")
        if g and not children(st, g, live_only=False):
            extra += _drop(st, w, [g], i)
    recompute_blocked(st)
    return {"dropped": dropped + extra}


def cmd_ask(task, st, a, w):
    if not a.default.strip():
        raise Fail("empty_default", "every question needs a proposed default", 2)
    qid = f"Q{len(st['questions']) + 1}"
    st["questions"].append({"id": qid, "text": a.text, "type": a.type, "default": a.default, "round": None,
                            "answer": None, "answer_source": None, "changed_at": None})
    recompute_blocked(st)
    w.event("question_added", qid, {"type": a.type})
    return {"id": qid}


def cmd_asked(task, st, a, w):
    ids = _csv(a.ids)
    qs = [require_question(st, q) for q in ids]
    rounds = [q["round"] for q in st["questions"] if q["round"] is not None]
    started = any(it["briefs"] > 0 for it in st["items"])
    rnd = max(rounds) + 1 if rounds else (2 if started else 1)
    if started:
        rnd = max(rnd, 2)
    for q in qs:
        q["round"] = rnd
        w.event("question_asked", q["id"], {"type": q["type"]})
    return {"ids": ids, "round": rnd}


def cmd_answer(task, st, a, w):
    q = require_question(st, a.id)
    changed = q["answer"] is not None
    affected = []
    for it in st["items"]:
        if a.id in it["needs"]:
            affected.append({"id": it["id"], "was": it["status"]})
    q["answer"], q["answer_source"] = a.text, a.source
    if changed:
        q["changed_at"] = _now()
        for it in st["items"]:
            if a.id in it["needs"] and it["kind"] == "leaf" and it["status"] in ("running", "done", "failed"):
                it["status"], it["attempts"] = "pending", 0
        if st["status"] == "complete":
            st["status"], st["stop"] = "active", None
        w.event("answer_changed", a.id, {"source": a.source})
    else:
        w.event("answered", a.id, {"source": a.source})
    recompute_blocked(st)
    return {"id": a.id, "changed": changed, "affected": affected}


def last_item_event(task, ref):
    lines, _ = task.record_lines()
    for line in reversed(lines):
        if line.get("ref") == ref and line["event"] in ("item_done", "item_retried", "item_failed", "item_held",
                                                         "item_blocked"):
            if line["event"] == "item_held" and line["data"].get("reason") == "brief not delivered":
                continue
            return line["event"]
    return None


def render_brief(task, st, items, mode):
    by = items_by_id(st)
    qs = {q["id"]: q for q in st["questions"]}
    out = [f"BRIEF {st['task_id']}", f"Mode: {mode}", ""]
    for it in items:
        out.append(f"ITEM {it['id']} (attempt {it['briefs']}): {it['title']}")
        out.append(f"Goal: {it['goal']}")
        out.append("Place in plan:")
        out.append(f"- {st['governing_question']}")
        parts = it["id"].split(".")
        ancestors = [".".join(parts[:i]) for i in range(1, len(parts))]
        for anc in ancestors:
            out.append(f"- {anc} {by[anc]['title']}")
        out.append("Settled answers you need:")
        for qid in it["needs"]:
            q = qs.get(qid)
            if q and q["answer"] is not None:
                out.append(f"- {qid} ({q['type']}): {q['text']} -> {q['answer']}")
        out.append("Settled decisions you must follow:")
        scope = {it["id"], *ancestors, *dep_closure(st, it)}
        for d in st["decisions"]:
            if d["item"] in scope:
                out.append(f"- {d['id']}: {d['question']} -> {d['chosen']}")
        out.append("Results you build on:")
        for dep in it["depends_on"]:
            for leaf in dep_leaves(st, dep):
                path = os.path.join(task.dir, leaf["result"]) if leaf["result"] else "none"
                out.append(f"- {leaf['id']} {leaf['title']}: {leaf['summary']} (full result: {path})")
        out.append(f"Skill: {it.get('skill') or 'none'}")
        out.append("Completion checklist:")
        out.extend(f"- [ ] {c}" for c in it["checklist"])
        out.append(f"Return format: {it['returns']}")
        if it["summary"] and last_item_event(task, it["id"]) in ("item_retried", "item_failed", "item_held"):
            out.append(f"Previous attempt failed or was held because: {it['summary']}")
        out.append(f"Write the full result to: {os.path.join(task.dir, 'results', it['id'] + '.md')}")
        out.append("")
    out.append("Reply rules: do not ask the user anything; if you need a fact only the user knows, reply "
               "`BLOCKED <id> <attempt> <question>` for that item. Take no step outside your goal, such as "
               "deleting files or contacting a third party; reply `APPROVAL <id> <attempt> <step>` instead. "
               "If the named skill does not load, reply `SKILL_FAILED <id> <attempt> <skill>`. Do not edit "
               "state.json. Do not change files outside the task folder; write each change as a unified diff "
               "in the result file, with `a/<path>` and `b/<path>` headers relative to the workspace root. "
               "For each other item, reply `RESULT <id> <attempt> <path>` and a summary of at most 150 words.")
    return "\n".join(out)


def cmd_brief(task, st, a, w):
    ids = _csv(a.ids)
    ready = {i for batch in compute_next(st)["ready"] for i in batch}
    items = []
    for i in ids:
        it = require_item(st, i)
        if i not in ready:
            raise Fail("not_ready", f"{i} is not in next's ready list", 2, "needs_fix",
                       "decompose.py next --task <task>")
        if it.get("skill"):
            check_skill(it["skill"])
        items.append(it)
    os.makedirs(os.path.join(task.dir, "results"), exist_ok=True)
    for it in items:
        it["status"] = "running"
        it["attempts"] += 1
        it["briefs"] += 1
        w.event("item_started", it["id"])
    return render_brief(task, st, items, a.mode or st["mode"])


def cmd_complete(task, st, a, w):
    it = require_item(st, a.id)
    if it["status"] != "running":
        raise Fail("not_running", f"{a.id} is {it['status']}; discard this reply", 2, "needs_fix",
                   "decompose.py next --task <task>")
    if a.attempt != it["briefs"]:
        raise Fail("stale_attempt", f"attempt {a.attempt} is not the latest brief {it['briefs']}; discard this reply",
                   2, "needs_fix", "decompose.py next --task <task>")
    out = {"id": a.id}
    if a.verdict == "pass":
        if not a.result or a.summary is None:
            raise Fail("bad_input", "pass needs --result and --summary", 2)
        rel = under_task(task, a.result)
        check_summary(a.summary)
        it.update(status="done", result=rel, summary=a.summary)
        w.event("item_done", a.id)
    elif a.verdict == "fail":
        if not a.reason:
            raise Fail("bad_input", "fail needs --reason", 2)
        it["result"] = under_task(task, a.result) if a.result else None
        it["summary"] = a.reason
        if it["attempts"] >= RETRY_LIMIT + 1:
            it["status"] = "failed"
            w.event("item_failed", a.id)
            g = it.get("discovers")
            if g and not children(st, g, live_only=False) and items_by_id(st)[g]["status"] != "dropped":
                out["dropped"] = _drop(st, w, [g], a.id)
            out["dependants"] = [p["id"] for p in st["items"]
                                 if p["status"] == "pending" and a.id in dep_closure(st, p)]
        else:
            it["status"] = "pending"
            w.event("item_retried", a.id)
    elif a.verdict == "blocked":
        if not a.question:
            raise Fail("bad_input", "blocked needs --question", 2)
        require_question(st, a.question)
        if a.question not in it["needs"]:
            it["needs"].append(a.question)
        it["status"] = "pending"
        it["attempts"] -= 1
        propagate_needs(st)
        w.event("item_blocked", a.id, {"question": a.question})
    else:  # held
        if not a.reason:
            raise Fail("bad_input", "held needs --reason", 2)
        it.update(status="pending", summary=a.reason)
        it["attempts"] -= 1
        w.event("item_held", a.id, {"reason": a.reason})
    recompute_blocked(st)
    out.update(status=it["status"], attempts=it["attempts"])
    return out


def cmd_decide(task, st, a, w):
    require_item(st, a.item)
    criteria = _csv(a.criteria)
    if not criteria:
        raise Fail("bad_input", "decide needs at least one --criteria question", 2)
    for c in criteria:
        require_question(st, c)
    if not a.reject:
        raise Fail("no_rejected_option", "a decision needs at least one --reject \"<option>::<reason>\"", 2)
    rejected = []
    for r in a.reject:
        if "::" not in r:
            raise Fail("bad_input", f"--reject {r!r} must be \"<option>::<reason>\"", 2)
        opt, reason = r.split("::", 1)
        rejected.append({"option": opt.strip(), "reason": reason.strip()})
    did = f"D{len(st['decisions']) + 1}"
    st["decisions"].append({"id": did, "item": a.item, "question": a.question, "criteria": criteria,
                            "chosen": a.chosen, "rejected": rejected})
    w.event("decided", did, {"item": a.item})
    return {"id": did}


COMMANDS = {"stop": cmd_stop, "finish": cmd_finish, "mark": cmd_mark, "log": cmd_log, "add": cmd_add,
            "drop": cmd_drop, "ask": cmd_ask, "asked": cmd_asked, "answer": cmd_answer, "brief": cmd_brief,
            "complete": cmd_complete, "decide": cmd_decide}


# ---------------------------------------------------------------- init, resume, views

def slug(text):
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:40].rstrip("-")


def cmd_init(a, argv):
    profile, max_batch, max_parallel = resolve_config(a.root, a.profile)
    base = os.path.join(os.path.abspath(a.root), ".atomic-decompose")
    stem = _dt.datetime.now(_dt.timezone.utc).strftime("%Y%m%d") + "-" + slug(a.question)
    task_id, n = stem, 1
    while os.path.exists(os.path.join(base, task_id)):
        n += 1
        task_id = f"{stem}-{n}"
    task_dir = os.path.join(base, task_id)
    os.makedirs(task_dir)
    task = Task(task_dir)
    try:
        task.lock()
        st = {"schema_version": SCHEMA, "task_id": task_id, "statement": a.statement,
              "governing_question": a.question, "mode": a.mode, "status": "active", "stop": None,
              "items": [], "questions": [], "decisions": [], "profile": profile, "max_batch": max_batch,
              "max_parallel": max_parallel, "applied_seq": 0, "updated_at": None}
        os.makedirs(os.path.join(task_dir, "results"))
        w = Writer(task, st, argv)
        w.event("engaged")
        w.commit()
        task.unlock()
    except BaseException:
        shutil.rmtree(task_dir, ignore_errors=True)
        raise
    return {"task_id": task_id, "task_dir": task_dir}


def cmd_resume(task, argv):
    st = task.load()
    lines, torn = task.record_lines()
    out = {"applied": [], "undelivered": []}
    if torn is not None:
        with open(task.record_path, "rb") as f:
            data = f.read()
        body = data[:-1] if data.endswith(b"\n") else data
        cut = body.rfind(b"\n") + 1
        with open(task.record_path, "wb") as f:
            f.write(data[:cut])
    unapplied = [l for l in lines if l["seq"] > st.get("applied_seq", 0)]
    if torn is not None and not unapplied:
        out["torn_line"] = torn
    groups, order = {}, []
    for l in unapplied:
        if l["cmd"] not in groups:
            groups[l["cmd"]] = []
            order.append(l["cmd"])
        groups[l["cmd"]].append(l)
    next_seq = (lines[-1]["seq"] + 1) if lines else 1
    for cmd in order:
        glines = groups[cmd]
        first = glines[0]
        if first.get("argv") is None:
            out.setdefault("torn_lines_without_argv", []).append(cmd)
            st["applied_seq"], st["updated_at"] = glines[-1]["seq"], glines[-1]["ts"]
            continue
        cargv = first["argv"]
        args = build_parser().parse_args(cargv + ["--task", task.dir])
        if cargv[0] == "brief":
            out["undelivered"] += _csv(args.ids)
            st["applied_seq"], st["updated_at"] = glines[-1]["seq"], glines[-1]["ts"]
            continue
        w = ReplayWriter(task, st, cargv, cmd, next_seq, len(glines))
        COMMANDS[cargv[0]](task, st, args, w)
        next_seq = w.seq
        last = w.last or glines[-1]
        st["applied_seq"], st["updated_at"] = last["seq"], last["ts"]
        out["applied"].append({"cmd": cmd, "argv": cargv})
    w = Writer(task, st, argv, next_seq=next_seq)
    for i in out["undelivered"]:
        w.event("item_held", i, {"reason": "brief not delivered"})
    if st["status"] == "stopped":
        st["status"], st["stop"] = "active", None
    w.event("resumed", None, {"undelivered": out["undelivered"]})
    w.commit()
    res = {"status": st["status"], "stop": st["stop"], "applied": out["applied"], "undelivered": out["undelivered"]}
    if "torn_line" in out:
        res["torn_line"] = out["torn_line"]
    return res


class ReplayWriter(Writer):
    """Re-runs an invocation, appending only the lines it would have written beyond the `skip` that survived."""

    def __init__(self, task, st, argv, cmd, next_seq, skip):
        super().__init__(task, st, argv, cmd=cmd, next_seq=next_seq, first_line_written=True)
        self.skip = skip

    def event(self, event, ref=None, data=None):
        if self.skip > 0:
            self.skip -= 1
            return
        super().event(event, ref, data)


def cmd_status(st):
    return {"governing_question": st["governing_question"], "status": st["status"], "stop": st["stop"],
            "items": [{k: it.get(k) for k in ("id", "title", "kind", "status", "attempts", "briefs", "needs",
                                              "depends_on", "skill", "result", "summary")} for it in st["items"]],
            "answers": [{k: q[k] for k in ("id", "type", "text", "round", "answer", "answer_source", "changed_at")}
                        for q in st["questions"]],
            "decisions": [{k: d[k] for k in ("id", "chosen", "rejected")} for d in st["decisions"]]}


def cmd_handoff(task, st):
    t = shlex.quote(task.dir)
    script = f"python3 {shlex.quote(os.path.abspath(__file__))}"
    leaves = [it for it in st["items"] if it["kind"] == "leaf" and it["status"] != "dropped"]
    done = sum(1 for l in leaves if l["status"] == "done")
    lines, torn = task.record_lines()
    out = [f"Governing question: {st['governing_question']}", f"Task status: {st['status']}",
           f"Stop: {st['stop']['condition'] + ' - ' + st['stop']['detail'] if st['stop'] else 'none'}",
           f"Items done: {done} of {len(leaves)}", "Settled answers:"]
    for q in st["questions"]:
        if q["answer"] is not None:
            out.append(f"- {q['id']} ({q['type']}, {q['answer_source']}): {q['text']} -> {q['answer']}")
    out.append("Decisions:")
    for d in st["decisions"]:
        out.append(f"- {d['id']} (item {d['item']}): {d['question']} -> {d['chosen']}")
    failed = [l["id"] for l in leaves if l["status"] == "failed"]
    out.append(f"Failed items: {', '.join(failed) or 'none'}")
    if st["status"] == "handed_back":
        nxt = "none: the task was handed back; work normally"
    elif torn is not None or any(l["seq"] > st.get("applied_seq", 0) for l in lines):
        nxt = f"{script} resume --task {t}"
    elif st["status"] == "stopped":
        nxt = f"{script} resume --task {t}  (after the user answers, approves or asks to continue)"
    else:
        n = compute_next(st)
        running = [l["id"] for l in leaves if l["status"] == "running"]
        if n["expand"]:
            nxt = f"{script} add --task {t} --parent {n['expand'][0]} ...  (or drop it)"
        elif n["ready"]:
            nxt = f"{script} brief {','.join(n['ready'][0])} --task {t}"
        elif running:
            nxt = f"wait for the replies of {', '.join(running)}, then {script} complete ..."
        elif st["status"] == "complete":
            nxt = f"{script} status --task {t}  (show the result; record the user's mark with mark)"
        elif not st["items"]:
            nxt = f"{script} add --task {t} --parent root ..."
        else:
            nxt = f"{script} finish --task {t}"
    out.append(f"Next command: {nxt}")
    return "\n".join(out)


def cmd_validate(st):
    problems = []
    by = items_by_id(st)

    def p(code, ref, msg):
        problems.append({"code": code, "ref": ref, "message": msg})

    qids = {q["id"] for q in st["questions"]}
    titles = {}
    for it in st["items"]:
        if it["status"] == "dropped":
            continue
        if it["title"] in titles:
            p("duplicate_title", it["id"], f"same title as {titles[it['title']]}")
        titles.setdefault(it["title"], it["id"])
        for q in it["needs"]:
            if q not in qids:
                p("unknown_ref", it["id"], f"needs unknown question {q}")
        for d in it["depends_on"]:
            if d not in by:
                p("unknown_ref", it["id"], f"depends on unknown item {d}")
            elif by[d]["status"] == "dropped" and it["status"] == "pending":
                p("dangling_dependency", it["id"], f"depends on dropped item {d}")
        if it["kind"] == "leaf":
            for f, code in (("goal", "leaf_without_goal"), ("checklist", "leaf_without_checklist"),
                            ("returns", "leaf_without_returns")):
                if not it.get(f):
                    p(code, it["id"], f"leaf has no {f}")
        elif not children(st, it["id"]):
            d = discoverer(st, it["id"])
            if not (d and d["status"] in ("pending", "running", "done")):
                p("childless_group", it["id"], "group has no live children")
    color = {}

    def visit(i):
        color[i] = 1
        # a group stands for its leaves, so a leaf depending on its own ancestor closes a cycle
        edges = by[i]["depends_on"] + ([c["id"] for c in children(st, i)] if by[i]["kind"] == "group" else [])
        for d in edges:
            if d not in by or by[d]["status"] == "dropped":
                continue
            if color.get(d) == 1:
                p("cycle", i, f"dependency cycle through {d}")
            elif color.get(d) is None:
                visit(d)
        color[i] = 2

    for it in st["items"]:
        if it["status"] != "dropped" and color.get(it["id"]) is None:
            visit(it["id"])
    for q in st["questions"]:
        if q["round"] == 1 and q["answer"] is None:
            p("open_question", q["id"], "round-1 question has no answer")
    return {"ok": not problems, "problems": problems}


# ---------------------------------------------------------------- CLI

def build_parser():
    ap = Parser(prog="decompose.py", description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="command", required=True, parser_class=Parser)

    def cmd(name, help_text):
        sp = sub.add_parser(name, help=help_text, description=help_text)
        if name != "init":
            sp.add_argument("--task", required=True, help="task folder <workspace>/.atomic-decompose/<task-id>")
        return sp

    sp = cmd("init", "Create a task folder and state; prints {task_id, task_dir}.")
    sp.add_argument("--root", required=True, help="workspace root")
    sp.add_argument("--statement", required=True)
    sp.add_argument("--question", required=True, help="governing question")
    sp.add_argument("--mode", choices=["delegate", "main_session"], default="delegate")
    sp.add_argument("--profile")
    sp = cmd("stop", "Stop the task with a stop condition.")
    sp.add_argument("--condition", required=True,
                    choices=["blocked_on_user", "needs_approval", "fault", "user_stop", "complete"])
    sp.add_argument("--detail", required=True)
    cmd("resume", "Repair the record, re-apply unapplied invocations and move a stopped task to active.")
    cmd("finish", "Mark the task complete (every leaf done or failed).")
    sp = cmd("mark", "Record the user's mark of the result.")
    sp.add_argument("--mark", required=True, choices=["accepted", "reworked"])
    sp.add_argument("--reason")
    sp = cmd("log", "Append a run-record event.")
    sp.add_argument("event", choices=LOG_EVENTS)
    sp.add_argument("--ref")
    sp.add_argument("--data", help="JSON object")
    sp = cmd("add", "Add a work item; prints {id}.")
    sp.add_argument("--parent", required=True, help="parent item id or root")
    sp.add_argument("--title", required=True)
    sp.add_argument("--kind", required=True, choices=["group", "leaf"])
    sp.add_argument("--goal")
    sp.add_argument("--check", action="append", default=[], help="checklist entry (repeat)")
    sp.add_argument("--returns")
    sp.add_argument("--needs", help="comma-separated question ids")
    sp.add_argument("--depends", help="comma-separated item ids")
    sp.add_argument("--skill", help="absolute path of the skill's SKILL.md")
    sp.add_argument("--small", action="store_true")
    sp.add_argument("--discovers", help="childless group this discovery leaf answers")
    sp = cmd("drop", "Drop a pending item, or a group's pending descendants.")
    sp.add_argument("id")
    sp.add_argument("--cause")
    cmd("validate", "Check the plan; prints {ok, problems}.")
    sp = cmd("ask", "Add a question; prints {id}.")
    sp.add_argument("--type", required=True, choices=["scope", "user_only"])
    sp.add_argument("--text", required=True)
    sp.add_argument("--default", required=True)
    sp = cmd("asked", "Record that questions were put to the user; prints {ids, round}.")
    sp.add_argument("--ids", required=True)
    sp = cmd("answer", "Settle or change an answer.")
    sp.add_argument("--id", required=True)
    sp.add_argument("--text", required=True)
    sp.add_argument("--source", required=True, choices=["user", "default_accepted", "default_unconfirmed"])
    cmd("status", "Print the plan, answers and decisions as JSON.")
    cmd("handoff", "Print the restart summary and the exact next command.")
    cmd("next", "Print ready batches, blocked items and groups to expand.")
    sp = cmd("brief", "Start items and print their brief.")
    sp.add_argument("ids", help="item id or comma-separated batch")
    sp.add_argument("--mode", choices=["main_session"])
    sp = cmd("complete", "Record an executor's reply for one item.")
    sp.add_argument("id")
    sp.add_argument("--attempt", required=True, type=int)
    sp.add_argument("--verdict", required=True, choices=["pass", "fail", "blocked", "held"])
    sp.add_argument("--result")
    sp.add_argument("--summary")
    sp.add_argument("--reason")
    sp.add_argument("--question")
    sp = cmd("decide", "Record a decision with its rejected options.")
    sp.add_argument("--item", required=True)
    sp.add_argument("--question", required=True)
    sp.add_argument("--criteria", required=True)
    sp.add_argument("--chosen", required=True)
    sp.add_argument("--reject", action="append", default=[], help="\"<option>::<reason>\" (repeat)")
    return ap


def _argv_for_record(argv):
    out, skip = [], False
    for i, x in enumerate(argv):
        if skip:
            skip = False
            continue
        if x == "--task":
            skip = True
            continue
        if x.startswith("--task="):
            continue
        out.append(x)
    return out


def run(argv):
    a = build_parser().parse_args(argv)
    rec_argv = _argv_for_record(argv)
    if a.command == "init":
        return cmd_init(a, rec_argv)
    task = Task(a.task)
    if not os.path.isdir(task.dir):
        raise Fail("bad_input", f"no task folder {task.dir}", 2)
    if a.command not in WRITERS:
        st = task.load()
        if a.command == "status":
            return cmd_status(st)
        if a.command == "handoff":
            return cmd_handoff(task, st)
        if a.command == "next":
            return compute_next(st)
        res = cmd_validate(st)
        if not res["ok"]:
            print(json.dumps(res, ensure_ascii=False))
            raise Fail("validate_failed", f"{len(res['problems'])} plan problem(s)", 1, "needs_fix",
                       "fix each problem with add or drop, then validate again")
        return res
    task.lock()
    try:
        if a.command == "resume":
            return cmd_resume(task, rec_argv)
        st = task.load()
        lines, torn = task.record_lines()
        if torn is not None or any(l["seq"] > st.get("applied_seq", 0) for l in lines):
            raise Fail("record_torn", "the run record has lines state.json lacks", 3, "auto_retry",
                       f"python3 {SCRIPT} resume --task {shlex.quote(task.dir)}")
        next_seq = (lines[-1]["seq"] + 1) if lines else 1
        w = Writer(task, st, rec_argv, next_seq=next_seq)
        out = COMMANDS[a.command](task, st, a, w)
        w.commit()
        return out
    finally:
        task.unlock()


def main(argv=None):
    argv = sys.argv[1:] if argv is None else argv
    try:
        out = run(argv)
    except SystemExit as e:
        return e.code if isinstance(e.code, int) else 0
    except Fail as e:
        print(f"ERROR [{e.code}] {e.message}\nresolves: {e.resolves}\nnext: {e.nxt or 'see --help'}",
              file=sys.stderr)
        return e.exit_code
    print(out if isinstance(out, str) else json.dumps(out, ensure_ascii=False))
    return 0


if __name__ == "__main__":
    sys.exit(main())
