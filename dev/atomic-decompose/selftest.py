#!/usr/bin/env python3
"""Runnable check (TDD §8): `python3 selftest.py` exits 0 when every assertion holds.

Standard library only, plus `git` for the writes-item checkpoints, worktrees and patches. Runs C-4 (the installed
`skills/atomic-decompose/scripts/decompose.py`) in-process against a temporary folder with HOME
pointed into it. Each assertion message starts with the IDs it verifies.
"""
from __future__ import annotations

import contextlib
import io
import json
import os
import re
import subprocess
import sys
import tempfile
from unittest import mock

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "..", "skills", "atomic-decompose", "scripts"))
import decompose as dc  # noqa: E402

TMP = tempfile.mkdtemp(prefix="ad-selftest-")
os.environ["HOME"] = TMP
WS = os.path.join(TMP, "ws")
os.makedirs(WS)


def check(cond, msg):
    if not cond:
        print(f"FAIL {msg}", file=sys.stderr)
        sys.exit(1)


def run(*args, code=0):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = dc.main([str(a) for a in args])
    check(rc == code, f"[API-1] {' '.join(map(str, args))} exited {rc}, expected {code}\n{err.getvalue()}")
    text = out.getvalue().strip()
    try:
        return json.loads(text) if text else None, err.getvalue()
    except ValueError:
        return text, err.getvalue()


def err_code(err):
    m = re.match(r"ERROR \[(\w+)\] ", err)
    return m.group(1) if m else None


def refused(code, exit_code, *args):
    _, err = run(*args, code=exit_code)
    check(err_code(err) == code, f"[API-1] {args[0]} expected {code}, got: {err}")
    return err


def new_task(q="Which option is best?", root=WS, *extra):
    out, _ = run("init", "--root", root, "--statement", "s", "--question", q, *extra)
    return out["task_dir"]


def state(t):
    with open(os.path.join(t, "state.json"), encoding="utf-8") as f:
        return json.load(f)


def record(t):
    with open(os.path.join(t, "record.jsonl"), encoding="utf-8") as f:
        return [json.loads(line) for line in f.read().splitlines()]


def item(t, i):
    return next(x for x in state(t)["items"] if x["id"] == i)


def leaf(t, parent, title, *extra):
    out, _ = run("add", "--task", t, "--parent", parent, "--title", title, "--kind", "leaf",
                 "--goal", "g", "--check", "c", "--returns", "r", *extra)
    return out["id"]


def group(t, parent, title, *extra):
    out, _ = run("add", "--task", t, "--parent", parent, "--title", title, "--kind", "group", *extra)
    return out["id"]


def result(t, i, text="done"):
    p = os.path.join(t, "results", f"{i}.md")
    with open(p, "w", encoding="utf-8") as f:
        f.write(text)
    return p


def rpath(t, i):
    return os.path.join(t, "results", f"{i}.md")


def do(t, ids):
    """Brief and pass every id in a batch."""
    run("brief", ",".join(ids), "--task", t)
    for i in ids:
        run("complete", i, "--task", t, "--attempt", item(t, i)["briefs"], "--verdict", "pass",
            "--result", result(t, i), "--summary", f"summary {i}")


def git(repo, *args, ok=True):
    p = subprocess.run(["git", "-C", repo, *args], capture_output=True, text=True)
    if ok:
        check(p.returncode == 0, f"[selftest] git {' '.join(args)} failed: {p.stderr}")
    return p


# ---------------------------------------------------------------- C-4

def test_init_and_rounds():
    t = new_task("Which is the best football team of my lifetime?")
    tid = os.path.basename(t)
    check(re.fullmatch(r"\d{8}-[a-z0-9-]{1,40}", tid), f"[API-2] task_id format: {tid}")
    t2 = new_task("Which is the best football team of my lifetime?")
    check(os.path.basename(t2) == tid + "-2", f"[API-2] second task_id gets -2: {t2}")
    check(os.path.isdir(os.path.join(t, "results")), "[API-2] init creates results/")
    for q in ("a", "b", "c"):
        run("ask", "--task", t, "--type", "scope", "--text", q, "--default", "d")
    out, _ = run("asked", "--task", t, "--ids", "Q1,Q2")
    check(out["round"] == 1, "[US-2] [API-4] first asked is round 1")
    out, _ = run("asked", "--task", t, "--ids", "Q3")
    check(out["round"] == 2, "[US-2] [API-4] next asked is the next round")
    # start-early: the opening round stays round 1 even when an item that needs no answer started first
    run("answer", "--task", t2, "--id", "Q1", "--text", "x", "--source", "user", code=2)
    leaf(t2, "root", "only")
    run("brief", "1", "--task", t2)
    run("ask", "--task", t2, "--type", "scope", "--text", "mid", "--default", "d")
    leaf(t2, "root", "needs it", "--needs", "Q1")
    check(run("next", "--task", t2)[0]["blocked"] == [{"id": "2", "by": ["Q1"]}],
          "[DM-2] [API-5] an unanswered scope question blocks the leaf that needs it")
    out, _ = run("asked", "--task", t2, "--ids", "Q1")
    check(out["round"] == 1, "[US-2] [API-4] the opening round is round 1 even after an item started")
    refused("empty_default", 2, "ask", "--task", t, "--type", "scope", "--text", "x", "--default", " ")
    out, _ = run("answer", "--task", t, "--id", "Q1", "--text", "d", "--source", "default_accepted")
    check(state(t)["questions"][0]["answer_source"] == "default_accepted", "[US-2] answer --source default_accepted")


def test_validate_and_add():
    t = new_task("validate case")
    g1 = group(t, "root", "G1")
    l11 = leaf(t, g1, "L11", "--depends", g1)
    group(t, "root", "Empty")
    out, _ = run("validate", "--task", t, code=1)
    codes = {p["code"] for p in out["problems"]}
    check({"cycle", "childless_group"} <= codes, f"[FR-9] validate finds cycle and childless_group: {codes}")
    run("drop", l11, "--task", t)
    run("drop", "2", "--task", t)

    # duplicate_title is refused by add (dropped titles count) and caught by validate on edited state
    refused("duplicate_title", 2, "add", "--task", t, "--parent", "root", "--title", "L11", "--kind", "group")
    st = state(t)
    st["items"].append(dict(st["items"][0], id="9", status="pending"))
    with open(os.path.join(t, "state.json"), "w", encoding="utf-8") as f:
        json.dump(st, f)
    out, _ = run("validate", "--task", t, code=1)
    check("duplicate_title" in {p["code"] for p in out["problems"]}, "[US-5] [FR-9] validate duplicate_title")

    t = new_task("validate case 2")
    a = leaf(t, "root", "A")
    b = leaf(t, "root", "B", "--depends", a)
    d = group(t, "root", "Deferred")
    disc = leaf(t, "root", "Discover", "--discovers", d)
    run("drop", a, "--task", t)
    out, _ = run("validate", "--task", t, code=1)
    probs = {(p["code"], p["ref"]) for p in out["problems"]}
    check(("dangling_dependency", b) in probs, f"[FR-8] dangling_dependency for pending item on dropped: {probs}")
    check(("childless_group", d) not in probs, "[API-3] no childless_group while discovery leaf is live")
    refused("dangling_dependency", 2, "add", "--task", t, "--parent", "root", "--title", "X", "--kind", "leaf",
            "--goal", "g", "--check", "c", "--returns", "r", "--depends", a)
    # not_deferrable: a leaf, a group with children, an already-discovered group
    g2 = group(t, "root", "Full")
    leaf(t, g2, "child")
    for target in (b, g2, d):
        refused("not_deferrable", 2, "add", "--task", t, "--parent", "root", "--title", f"D{target}",
                "--kind", "leaf", "--goal", "g", "--check", "c", "--returns", "r", "--discovers", target)
    refused("parent_is_discovery", 2, "add", "--task", t, "--parent", disc, "--title", "under", "--kind", "group")
    d2 = group(t, "root", "Deferred two")
    refused("not_deferrable", 2, "add", "--task", t, "--parent", d2, "--title", "inside", "--kind", "leaf",
            "--goal", "g", "--check", "c", "--returns", "r", "--discovers", d2)
    # a drop of a discovery leaf writes the leaf as the deferred group's cause
    run("drop", disc, "--task", t)
    line = [x for x in record(t) if x["event"] == "item_dropped" and x["ref"] == d]
    check(line and line[0]["data"]["cause"] == disc, "[API-3] dropped discovery leaf is the group's cause")

    # add under a pending leaf converts it, keeping briefs
    t = new_task("convert case")
    p = leaf(t, "root", "P", "--small")
    run("brief", p, "--task", t)
    run("complete", p, "--task", t, "--attempt", 1, "--verdict", "fail", "--reason", "weak",
        "--result", result(t, p))
    leaf(t, p, "child")
    it = item(t, p)
    check(it["kind"] == "group" and not any(k in it for k in dc.LEAF_ONLY), "[DM-2] converted leaf loses leaf-only")
    check(it["attempts"] == 0 and it["summary"] is None and it["result"] is None and it["briefs"] == 1,
          f"[DM-2] conversion resets attempts, summary, result and keeps briefs: {it}")


def test_skill_and_drop():
    t = new_task("skill case")
    sk = os.path.join(TMP, "elsewhere", "x")
    os.makedirs(sk)
    with open(os.path.join(sk, "SKILL.md"), "w") as f:
        f.write("---\nname: x\n---\n")
    leaf(t, "root", "S", "--skill", os.path.join(sk, "SKILL.md"))
    refused("skill_missing", 2, "add", "--task", t, "--parent", "root", "--title", "M", "--kind", "leaf",
            "--goal", "g", "--check", "c", "--returns", "r", "--skill", os.path.join(TMP, "none", "SKILL.md"))
    refused("skill_path_not_absolute", 2, "add", "--task", t, "--parent", "root", "--title", "N", "--kind", "leaf",
            "--goal", "g", "--check", "c", "--returns", "r", "--skill", "$0/x/SKILL.md")
    g = group(t, "root", "G")
    a, b = leaf(t, g, "A"), leaf(t, g, "B")
    do(t, [a])
    run("brief", "1", "--task", t)
    refused("not_droppable", 2, "drop", "1", "--task", t)
    out, _ = run("drop", g, "--task", t, "--cause", a)
    check(out["dropped"] == [b] and item(t, g)["status"] == "pending",
          f"[API-3] group drop with a done child drops only pending descendants: {out}")
    line = [x for x in record(t) if x["event"] == "item_dropped" and x["ref"] == b][0]
    check(line["data"]["cause"] == a, "[API-3] drop --cause recorded")


def test_next_and_brief():
    t = new_task("next case")
    one = leaf(t, "root", "One")
    deferred = group(t, "root", "Deferred")
    disc = leaf(t, "root", "Disc", "--discovers", deferred)
    leaf(t, "root", "Needs one", "--depends", one)
    five = leaf(t, "root", "Five")
    g = group(t, "root", "Smalls")
    smalls = [leaf(t, g, f"s{i}", "--small") for i in range(1, 11)]
    out, _ = run("next", "--task", t)
    expect = [[disc], [one], [five], smalls[0:4], smalls[4:8], smalls[8:10]]
    check(out["ready"] == expect, f"[FR-10] [DD-14] next batching and priority: {out['ready']}")
    check(smalls[9] == "6.10" and out["ready"][-1] == ["6.9", "6.10"], "[DD-14] 1.10 sorts after 1.9")
    # two batches served before any complete
    brief1, _ = run("brief", disc, "--task", t)
    run("brief", ",".join(smalls[0:4]), "--task", t)
    out, _ = run("next", "--task", t)
    check([disc] not in out["ready"] and smalls[0:4] not in out["ready"], "[API-6] two batches in flight")
    for head in ("BRIEF ", "Mode: delegate", f"ITEM {disc} (attempt 1): Disc", "Goal: g", "Place in plan:",
                 "- next case", "Settled answers you need:", "Settled decisions you must follow:",
                 "Results you build on:", "Skill: none", "Completion checklist (give a CHECK pointer for each):", "- [ ] 1. c", "Return format: r",
                 "Write the full result to: ", "Reply rules:"):
        check(head in brief1, f"[FR-3] [API-7] brief has {head!r}")
    main, _ = run("brief", five, "--task", t, "--mode", "main_session")
    check("Mode: main_session" in main, "[FR-5] brief --mode main_session")
    # expand: childless deferred group with a done discovery leaf
    run("complete", disc, "--task", t, "--attempt", 1, "--verdict", "pass", "--result", result(t, disc),
        "--summary", "found")
    out, _ = run("next", "--task", t)
    check(out["expand"] == [deferred] and item(t, deferred)["status"] == "pending", "[API-5] expand listing")
    refused("open_items", 1, "finish", "--task", t)


def test_completion_rules():
    t = new_task("completion case")
    run("ask", "--task", t, "--type", "scope", "--text", "q", "--default", "d")
    run("asked", "--task", t, "--ids", "Q1")
    run("answer", "--task", t, "--id", "Q1", "--text", "first", "--source", "user")
    a = leaf(t, "root", "A", "--needs", "Q1")
    refused("not_running", 2, "complete", a, "--task", t, "--attempt", 1, "--verdict", "fail", "--reason", "x")
    for n in (1, 2):
        run("brief", a, "--task", t)
        run("complete", a, "--task", t, "--attempt", n, "--verdict", "fail", "--reason", f"weak {n}")
        check(item(t, a)["status"] == "pending", f"[DD-12] attempt {n} fail retries")
    text, _ = run("brief", a, "--task", t)
    check("Previous attempt failed or was held because: weak 2" in text, "[FR-4] brief carries the previous reason")
    dep = leaf(t, "root", "Builds on A", "--depends", a)
    out, _ = run("complete", a, "--task", t, "--attempt", 3, "--verdict", "fail", "--reason", "weak 3")
    check(item(t, a)["status"] == "failed", "[FR-4] [DD-12] third failed attempt sets failed")
    check(out["dependants"] == [dep], f"[US-4.4] complete lists the failed item's pending dependants: {out}")
    run("drop", dep, "--task", t, "--cause", a)

    b = leaf(t, "root", "B", "--needs", "Q1")
    run("brief", b, "--task", t)
    run("ask", "--task", t, "--type", "user_only", "--text", "who", "--default", "me")
    run("complete", b, "--task", t, "--attempt", 1, "--verdict", "blocked", "--question", "Q2")
    check(item(t, b)["attempts"] == 0 and item(t, b)["blocked_by"] == ["Q2"], "[US-4] blocked takes back the attempt")
    run("answer", "--task", t, "--id", "Q2", "--text", "you", "--source", "user")
    run("brief", b, "--task", t)
    refused("stale_attempt", 2, "complete", b, "--task", t, "--attempt", 1, "--verdict", "held", "--reason", "x")
    run("complete", b, "--task", t, "--attempt", 2, "--verdict", "held", "--reason", "needs approval")
    check(item(t, b)["attempts"] == 0 and item(t, b)["status"] == "pending", "[US-4] held takes back the attempt")
    do(t, [b])
    out, _ = run("answer", "--task", t, "--id", "Q1", "--text", "second", "--source", "user")
    check(out["changed"] and {"id": b, "was": "done"} in out["affected"] and {"id": a, "was": "failed"} in out["affected"],
          f"[US-3] answer change returns affected with was: {out}")
    check(item(t, b)["status"] == "pending" and item(t, b)["attempts"] == 0, "[US-3] answer change resets items")

    words = " ".join(["w"] * 150)
    run("brief", b, "--task", t)
    refused("summary_too_long", 2, "complete", b, "--task", t, "--attempt", item(t, b)["briefs"], "--verdict",
            "pass", "--result", result(t, b), "--summary", words + " w")
    run("complete", b, "--task", t, "--attempt", item(t, b)["briefs"], "--verdict", "pass", "--result",
        result(t, b), "--summary", words)
    check(item(t, b)["status"] == "done", "[API-6] 150-word summary accepted")
    refused("no_rejected_option", 2, "decide", "--task", t, "--item", b, "--question", "which",
            "--criteria", "Q1", "--chosen", "x")
    refused("not_complete", 2, "mark", "--task", t, "--mark", "accepted")
    run("drop", a, "--task", t)
    run("finish", "--task", t)
    run("mark", "--task", t, "--mark", "accepted")
    check(state(t)["status"] == "complete", "[US-11] finish then mark accepted")
    t2 = new_task("engagement case")
    run("log", "wrong_engagement", "--task", t2)
    check(state(t2)["status"] == "handed_back", "[US-1] [FR-12] log wrong_engagement sets handed_back")


def test_group_dependency():
    t = new_task("group dep case")
    g = leaf(t, "root", "G")
    a, b = leaf(t, g, "A"), leaf(t, g, "B")
    x = leaf(t, "root", "X", "--depends", g)
    ready = lambda: [i for batch in run("next", "--task", t)[0]["ready"] for i in batch]  # noqa: E731
    do(t, [a])
    check(x not in ready(), "[API-3] group dependency waits for every leaf")
    do(t, [b])
    check(x in ready(), "[API-3] group dependency met once every non-dropped leaf is done")
    t = new_task("group dep dropped")
    g = group(t, "root", "G")
    a = leaf(t, g, "A")
    x = leaf(t, "root", "X", "--depends", g)
    run("drop", a, "--task", t)
    check(x not in ready(), "[API-3] never ready while every leaf of the group is dropped")


def test_format_edges():
    t = new_task("format case")
    _, err = run("drop", "7", "--task", t, code=2)
    check(re.fullmatch(r"ERROR \[unknown_ref\] .+\nresolves: (auto_retry|needs_fix|needs_user)\nnext: .+\n", err),
          f"[API-1] error block format: {err!r}")
    run("log", "compaction", "--task", t, "--data", json.dumps({"note": "a\nb"}))
    with open(os.path.join(t, "record.jsonl"), encoding="utf-8") as f:
        raw = f.read()
    check(raw.count("\n") == len(record(t)) and "a\\nb" in raw, "[DM-5] newline in a string written as \\n")


def test_faults():
    t = new_task("fault case")
    run("ask", "--task", t, "--type", "scope", "--text", "q1", "--default", "d")
    run("ask", "--task", t, "--type", "scope", "--text", "q2", "--default", "d")
    st_path = os.path.join(t, "state.json")

    # record_write_failed part-way through asked --ids Q1,Q2
    real = dc._append_line
    calls = []

    def flaky(path, text):
        calls.append(text)
        if len(calls) == 2:
            raise OSError("disk full")
        real(path, text)

    with mock.patch.object(dc, "_append_line", flaky):
        refused("record_write_failed", 3, "asked", "--task", t, "--ids", "Q1,Q2")
    check(not os.path.exists(os.path.join(t, ".lock")), "[DD-16] lock released after a fault")
    refused("record_torn", 3, "ask", "--task", t, "--type", "scope", "--text", "q3", "--default", "d")
    q1_line = [x for x in record(t) if x["event"] == "question_asked"][0]
    out, _ = run("resume", "--task", t)
    asked = [x for x in record(t) if x["event"] == "question_asked"]
    check([x["ref"] for x in asked] == ["Q1", "Q2"] and asked[1]["cmd"] == q1_line["cmd"],
          f"[FR-8] resume appends only the missing Q2 line with Q1's cmd: {asked}")
    check(len(out["applied"]) == 1, "[FR-8] resume lists the invocation in applied")

    # state_write_failed with the clock set back, then resume re-applies by seq
    with mock.patch.object(dc, "_now", lambda: "2000-01-01T00:00:00.000Z"), \
            mock.patch.object(dc.os, "replace", side_effect=OSError("rename")):
        refused("state_write_failed", 3, "ask", "--task", t, "--type", "user_only", "--text", "q3", "--default", "d")
    check(record(t)[-1]["ts"] < state(t)["updated_at"], "[DD-16] unapplied line carries an earlier ts")
    out, _ = run("resume", "--task", t)
    added = [x for x in record(t) if x["event"] == "question_added" and x["ref"] == "Q3"]
    check(len(out["applied"]) == 1 and len(added) == 1 and len(state(t)["questions"]) == 3,
          f"[FR-8] state_write_failed resume re-applies once by seq: {out}")

    # unapplied brief left pending and listed undelivered
    a = leaf(t, "root", "A")
    before = item(t, a)
    with mock.patch.object(dc.os, "replace", side_effect=OSError("rename")):
        run("brief", a, "--task", t, code=3)
    out, _ = run("resume", "--task", t)
    after = item(t, a)
    held = [x for x in record(t) if x["event"] == "item_held" and x["ref"] == a]
    check(out["undelivered"] == [a] and after["status"] == "pending" and len(held) == 1
          and held[0]["data"]["reason"] == "brief not delivered"
          and all(after[k] == before[k] for k in ("briefs", "attempts", "summary")),
          f"[FR-8] unapplied brief stays pending and is undelivered: {out} {after}")

    # record_torn and resume truncating the torn line
    with open(os.path.join(t, "record.jsonl"), "a", encoding="utf-8") as f:
        f.write('{"seq": 99, "ts"')
    refused("record_torn", 3, "log", "tokens", "--task", t)
    out, _ = run("resume", "--task", t)
    check(out.get("torn_line") == '{"seq": 99, "ts"' and record(t)[-1]["event"] == "resumed",
          f"[DD-16] resume truncates the torn line: {out}")

    # task_locked; state_unreadable on another schema_version leaves state.json byte-identical
    open(os.path.join(t, ".lock"), "w").close()
    refused("task_locked", 3, "log", "tokens", "--task", t)
    os.remove(os.path.join(t, ".lock"))
    st = state(t)
    st["schema_version"] = 99
    with open(st_path, "w", encoding="utf-8") as f:
        json.dump(st, f)
    raw = open(st_path, "rb").read()
    refused("state_unreadable", 3, "log", "tokens", "--task", t)
    check(open(st_path, "rb").read() == raw, "[DD-16] state.json byte-identical after state_unreadable")


def test_config():
    ws = os.path.join(TMP, "cfg")
    os.makedirs(os.path.join(ws, ".atomic-decompose"))
    home_cfg = os.path.join(TMP, ".config", "atomic-decompose")
    os.makedirs(home_cfg, exist_ok=True)

    def put(path, obj):
        with open(path, "w", encoding="utf-8") as f:
            json.dump(dict(obj, schema_version=1), f)

    put(os.path.join(home_cfg, "config.json"), {"profile": "h", "max_parallel": 6,
                                                "profiles": {"h": {"max_batch": 2}, "p": {"max_batch": 9}}})
    put(os.path.join(ws, ".atomic-decompose", "config.json"),
        {"profiles": {"p": {"max_batch": 3}, "low": {"max_parallel": 2}, "high": {"max_parallel": 10}}})
    put(os.path.join(ws, ".atomic-decompose", "config.local.json"), {"profiles": {"p": {"max_batch": 1}}})
    st = state(new_task("cfg a", ws))
    check((st["profile"], st["max_batch"], st["max_parallel"]) == ("h", 2, 6), f"[DM-9] home profile: {st}")
    st = state(new_task("cfg b", ws, "--profile", "p"))
    check(st["max_batch"] == 1, "[DM-9] --profile then config.local.json wins for max_batch")
    st = state(new_task("cfg c", ws, "--profile", "low"))
    check(st["max_parallel"] == 2, "[US-9] [DM-9] a profile cap below the user's lowers max_parallel")
    st = state(new_task("cfg d", ws, "--profile", "high"))
    check(st["max_parallel"] == 6, "[US-9] [DM-9] a profile cap above the user's keeps the user's value")
    refused("unknown_profile", 2, "init", "--root", ws, "--statement", "s", "--question", "q", "--profile", "zz")


def make_repo(name):
    """A repo with a commit, plus the user's own staged, unstaged and untracked changes."""
    repo = os.path.join(TMP, name)
    os.makedirs(repo)
    git(repo, "init", "-q")
    git(repo, "config", "user.email", "t@t")
    git(repo, "config", "user.name", "t")
    write(repo, "f.txt", "one\ntwo\nthree\n")
    write(repo, "g.txt", "g\n")
    write(repo, ".gitignore", "*.log\n")
    write(repo, "keep.log", "tracked although ignored\n")
    git(repo, "add", "-f", ".")
    git(repo, "commit", "-qm", "base")
    write(repo, "s.txt", "staged\n")
    git(repo, "add", "s.txt")
    write(repo, "g.txt", "g changed by the user\n")
    write(repo, "u.txt", "untracked\n")
    return repo


def write(repo, rel, text):
    path = os.path.join(repo, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb" if isinstance(text, bytes) else "w") as f:
        f.write(text)


def read(repo, rel):
    with open(os.path.join(repo, rel)) as f:
        return f.read()


def porcelain(repo):
    return git(repo, "status", "--porcelain", "--untracked-files=all").stdout


def index(repo):
    return git(repo, "ls-files", "--stage").stdout


def refs(repo, t):
    return git(repo, "for-each-ref", "--format=%(refname)", f"refs/atomic-decompose/{os.path.basename(t)}/").stdout


def worktrees(repo):
    return [line for line in git(repo, "worktree", "list", "--porcelain").stdout.splitlines()
            if line.startswith("worktree ")]


def ready_ids(t):
    return [i for batch in run("next", "--task", t)[0]["ready"] for i in batch]


def test_in_place_checkpoint():
    repo = make_repo("inplace")
    status0, index0 = porcelain(repo), index(repo)
    t = new_task("in place case", repo)
    check(porcelain(repo) == status0, "[DD-4] the task folder adds nothing to git status")
    a = leaf(t, "root", "Edit", "--writes")
    check(item(t, a)["writes"] is True, "[API-3] add --writes stores writes")
    text, _ = run("brief", a, "--task", t)
    it = item(t, a)
    check(it["worktree"] is None and "Edits: in place" in text and "never write a diff" in text,
          f"[API-7] a lone writes item edits in place, and the brief forbids diffs: {it}")
    ref = it["checkpoint"]
    check(git(repo, "show", f"{ref}:g.txt").stdout == "g changed by the user\n"
          and git(repo, "show", f"{ref}:u.txt").stdout == "untracked\n"
          and git(repo, "show", f"{ref}:s.txt").stdout == "staged\n",
          "[DD-8] checkpoint holds unstaged, untracked and staged changes")
    check(index(repo) == index0 and porcelain(repo) == status0 and not git(repo, "stash", "list").stdout,
          "[DD-8] checkpoint leaves the user's index, status and stash list alone")
    # the executor edits, deletes and creates files in place
    write(repo, "f.txt", "one\nTWO\nthree\n")
    os.remove(os.path.join(repo, "g.txt"))
    write(repo, "new/dir/n.txt", "created\n")
    write(repo, "u.txt", "untracked, edited\n")
    write(repo, "keep.log", "edited\n")
    out, _ = run("changes", a, "--task", t)
    got = {(f["status"], f["path"]) for f in out["files"]}
    check(out["edits"] == "in_place" and got == {("M", "f.txt"), ("D", "g.txt"), ("A", "new/dir/n.txt"),
                                                ("M", "u.txt"), ("M", "keep.log")},
          f"[API-5] changes lists the item's files, a tracked file under an ignore rule included: {out}")
    out, _ = run("complete", a, "--task", t, "--attempt", 1, "--verdict", "fail", "--reason", "weak")
    check(read(repo, "f.txt") == "one\ntwo\nthree\n" and read(repo, "g.txt") == "g changed by the user\n"
          and read(repo, "u.txt") == "untracked\n" and not os.path.exists(os.path.join(repo, "new"))
          and read(repo, "keep.log") == "tracked although ignored\n",
          "[DD-8] fail restores changed and deleted paths and deletes created files")
    check(porcelain(repo) == status0 and index(repo) == index0 and sorted(out["restored"]) ==
          ["f.txt", "g.txt", "keep.log", "new/dir/n.txt", "u.txt"], f"[DD-8] restore leaves the index alone: {out}")

    # pass: the patch is saved, binary-safe, and the edits stay
    run("brief", a, "--task", t)
    check(item(t, a)["checkpoint"].endswith(f"/{a}-2"), "[DM-2] one checkpoint ref per attempt")
    write(repo, "f.txt", "one\nTWO\nthree\n")
    write(repo, "b.bin", bytes([0, 255, 1, 254]))
    out, _ = run("complete", a, "--task", t, "--attempt", 2, "--verdict", "pass", "--result", result(t, a),
                 "--summary", "edited")
    patch = os.path.join(t, item(t, a)["patch"])
    with open(patch, encoding="utf-8") as f:
        ptext = f.read()
    check(item(t, a)["patch"] == f"patches/{a}.patch" and "GIT binary patch" in ptext and "+TWO" in ptext,
          "[DD-8] pass saves a binary-safe git patch")
    check(read(repo, "f.txt") == "one\nTWO\nthree\n" and index(repo) == index0,
          "[DD-8] pass leaves the edits in place and the index alone")
    done = [x for x in record(t) if x["event"] == "item_done"][-1]
    check(done["data"]["patch"] == f"patches/{a}.patch", "[DM-5] item_done records the patch")
    check(not [line for line in porcelain(repo).splitlines() if ".atomic-decompose" in line],
          "[DD-4] task folder with patches still adds nothing to git status")


def test_writes_hold_and_worktrees():
    repo = make_repo("hold")
    t = new_task("hold case", repo)
    x = leaf(t, "root", "Research")
    a = leaf(t, "root", "Writer A", "--writes")
    b = leaf(t, "root", "Writer B", "--writes", "--depends", x)
    run("brief", a, "--task", t)
    check(item(t, a)["worktree"] is None, "[DD-8] the only ready writer runs in place")
    do(t, [x])
    check(b not in ready_ids(t), "[API-5] next holds a writes item while an in-place writer runs")
    refused("not_ready", 2, "brief", b, "--task", t)
    run("complete", a, "--task", t, "--attempt", 1, "--verdict", "pass", "--result", result(t, a),
        "--summary", "a")
    check(b in ready_ids(t), "[API-5] the held writes item is ready once the in-place writer ends")

    repo = make_repo("worktrees")
    status0 = porcelain(repo)
    t = new_task("worktree case", repo)
    a = leaf(t, "root", "Writer A", "--writes")
    b = leaf(t, "root", "Writer B", "--writes")
    text_a, _ = run("brief", a, "--task", t)
    text_b, _ = run("brief", b, "--task", t)
    wa, wb = (os.path.join(t, item(t, i)["worktree"]) for i in (a, b))
    check(os.path.isdir(wa) and os.path.isdir(wb) and f"under {wa}" in text_a and "in your worktree only" in text_b,
          "[DD-8] writes items ready together each get a worktree named in the brief")
    check(read(wa, "g.txt") == "g changed by the user\n" and read(wa, "u.txt") == "untracked\n",
          "[DD-8] the worktree starts from the checkpoint, with the user's uncommitted files")
    check(porcelain(repo) == status0, "[DD-4] worktrees inside the task folder add nothing to git status")
    write(wa, "f.txt", "one\nTWO\nthree\n")
    write(wa, "a.txt", "from a\n")
    write(wb, "f.txt", "one\n2\nthree\n")
    out, _ = run("changes", a, "--task", t)
    check(out["edits"] == "worktree" and {f["path"] for f in out["files"]} == {"f.txt", "a.txt"}
          and read(repo, "f.txt") == "one\ntwo\nthree\n", f"[API-5] worktree edits leave the workspace alone: {out}")
    run("complete", a, "--task", t, "--attempt", 1, "--verdict", "pass", "--result", result(t, a), "--summary", "a")
    check(read(repo, "f.txt") == "one\nTWO\nthree\n" and read(repo, "a.txt") == "from a\n"
          and os.path.exists(os.path.join(t, "patches", f"{a}.patch")),
          "[DD-8] a worktree pass applies its patch to the workspace and saves it")
    check(not os.path.exists(wa) and len(worktrees(repo)) == 2 and item(t, a)["worktree"] is None,
          "[DD-8] a worktree pass removes the worktree")
    before = (read(repo, "f.txt"), porcelain(repo))
    err = refused("patch_conflict", 1, "complete", b, "--task", t, "--attempt", 1, "--verdict", "pass",
                  "--result", result(t, b), "--summary", "b")
    check((read(repo, "f.txt"), porcelain(repo)) == before and item(t, b)["status"] == "running"
          and not os.path.exists(os.path.join(t, "patches", f"{b}.patch")) and "--verdict fail" in err,
          f"[DD-15] a clashing worktree patch changes nothing and names the fail command: {err}")
    out, _ = run("complete", b, "--task", t, "--attempt", 1, "--verdict", "fail", "--reason", "clash with a")
    check(item(t, b)["status"] == "pending" and not os.path.exists(wb) and out["worktree_removed"],
          "[DD-15] the clashing item is retried and its worktree removed")
    # a stale worktree, then mark accepted cleans refs and worktrees but keeps the task files
    run("brief", b, "--task", t)
    check(item(t, b)["worktree"] is None, "[DD-8] the retry runs in place against the current files")
    git(repo, "worktree", "add", "-q", "--detach", os.path.join(t, "wt", "stale"), "HEAD")
    run("complete", b, "--task", t, "--attempt", 2, "--verdict", "pass", "--result", result(t, b), "--summary", "b")
    check(refs(repo, t).count("\n") == 3, f"[DM-2] one ref per writes attempt: {refs(repo, t)}")
    run("finish", "--task", t)
    check(not refs(repo, t) and len(worktrees(repo)) == 1 and not os.path.exists(os.path.join(t, "wt")),
          "[DD-25] finish removes the task's refs and worktrees")
    run("mark", "--task", t, "--mark", "accepted")
    check(all(os.path.exists(os.path.join(t, p)) for p in ("state.json", "record.jsonl", f"results/{a}.md",
                                                           f"patches/{a}.patch", f"patches/{b}.patch")),
          "[DD-8] mark accepted keeps state, record, results and patches")


def test_reverse_patches():
    repo = make_repo("reverse")
    t = new_task("reverse case", repo)
    run("ask", "--task", t, "--type", "scope", "--text", "q", "--default", "d")
    run("answer", "--task", t, "--id", "Q1", "--text", "first", "--source", "user")
    a = leaf(t, "root", "Edit A", "--writes", "--needs", "Q1")
    b = leaf(t, "root", "Edit B", "--writes", "--needs", "Q1", "--depends", a)
    for i, text in ((a, "one\nTWO\nthree\n"), (b, "one\nTWO!\nthree\n")):
        run("brief", i, "--task", t)
        write(repo, "f.txt", text)
        run("complete", i, "--task", t, "--attempt", 1, "--verdict", "pass", "--result", result(t, i),
            "--summary", i)
    out, _ = run("answer", "--task", t, "--id", "Q1", "--text", "second", "--source", "user")
    patches = {e["id"]: e["patch"] for e in out["affected"]}
    order = [x["ref"] for x in record(t) if x["event"] == "item_done"]
    check(order == [a, b] and set(patches) == {a, b}, f"[DD-15] affected names each done item's patch: {out}")
    p = git(repo, "apply", "-R", "--check", patches[order[0]], ok=False)
    check(p.returncode != 0, "[DD-15] reversing earliest first fails")
    for i in reversed(order):
        git(repo, "apply", "-R", patches[i])
    check(read(repo, "f.txt") == "one\ntwo\nthree\n" and read(repo, "g.txt") == "g changed by the user\n",
          "[DD-15] reversing the saved patches latest first restores the files")


def test_writes_needs_git():
    plain = os.path.join(TMP, "plain")
    os.makedirs(plain)
    t = new_task("no repo case", plain)
    a = leaf(t, "root", "Edit", "--writes")
    err = refused("not_a_git_repo", 3, "brief", a, "--task", t)
    check(item(t, a)["status"] == "pending" and item(t, a)["briefs"] == 0 and "next: " in err,
          "[FR-8] a writes item outside a git repository faults before any change")
    real = subprocess.run

    def no_git(cmd, *args, **kw):
        if cmd[0] == "git":
            raise FileNotFoundError("git")
        return real(cmd, *args, **kw)

    with mock.patch.object(dc.subprocess, "run", no_git):
        refused("git_missing", 3, "brief", a, "--task", t)
    check(item(t, a)["status"] == "pending", "[FR-8] git missing faults before any change")
    leaf(t, "root", "Research")
    do(t, ["2"])
    check(item(t, "2")["status"] == "done", "[DD-8] an item without --writes needs no git")


def cmd_leaf(t, parent, title, *extra):
    out, _ = run("add", "--task", t, "--parent", parent, "--title", title, "--kind", "leaf",
                 "--goal", "g", "--returns", "r", *extra)
    return out["id"]


def test_init_fields_and_add_rules():
    st = state(new_task("init fields"))
    check((st["mode"], st["mode_explicit"], st["max_chain"], st["check_timeout_s"]) == ("delegate", False, 5, 600),
          f"[DM-1] [API-2] init defaults: {st}")
    st = state(new_task("init explicit", WS, "--mode", "delegate"))
    check(st["mode_explicit"] is True, "[DM-1] [DD-9] an explicit --mode delegate is recorded")
    t = new_task("add rules")
    g = group(t, "root", "G")
    refused("bad_input", 2, "add", "--task", t, "--parent", "root", "--title", "Gc", "--kind", "group",
            "--check-cmd", "true")
    refused("bad_input", 2, "add", "--task", t, "--parent", "root", "--title", "SW", "--kind", "leaf", "--goal", "g",
            "--check", "c", "--returns", "r", "--small", "--writes")
    refused("leaf_without_checklist", 2, "add", "--task", t, "--parent", g, "--title", "N", "--kind", "leaf",
            "--goal", "g", "--returns", "r")
    i = cmd_leaf(t, g, "Cmd only", "--check-cmd", "true")
    check(item(t, i)["check_commands"] == ["true"] and item(t, i)["checklist"] == [] and run("validate", "--task", t)[0]["ok"],
          "[DM-2] [API-3] a leaf with only a command entry is valid; commands are kept apart from the checklist")


def test_verify_and_checks():
    t = new_task("verify case")
    j = leaf(t, "root", "Judged")
    c = cmd_leaf(t, "root", "Checked", "--check", "judged too", "--check-cmd", "test -f marker", "--check-cmd",
                 "echo run >> runs.txt")
    run("brief", j, "--task", t)
    refused("no_check_commands", 2, "verify", j, "--task", t)
    text, _ = run("brief", c, "--task", t)
    check("Checked by the script after you reply" in text and "- test -f marker" in text and "- [ ] 1. judged too" in text
          and "CHECK <id> <n> <path>:<line>" in text, f"[API-7] [API-8] brief lists command entries apart: {text}")
    err = refused("checks_not_passed", 1, "complete", c, "--task", t, "--attempt", 1, "--verdict", "pass",
                  "--result", result(t, c), "--summary", "s")
    check(f"verify {c}" in err and item(t, c)["status"] == "running", f"[DD-23] pass before verify names verify: {err}")
    out, err = run("verify", c, "--task", t, code=1)
    check(out["passed"] is False and out["checks"][0]["exit_code"] == 1 and out["checks"][1]["exit_code"] == 0
          and err_code(err) == "checks_failed", f"[API-5] verify runs every command even after a failure: {out}")
    check(os.path.exists(os.path.join(t, out["checks"][0]["log"])) and out["checks"][0]["log"] == f"results/{c}-1-check-1.log",
          "[API-5] verify writes each command's log")
    err = refused("checks_not_passed", 1, "complete", c, "--task", t, "--attempt", 1, "--verdict", "pass",
                  "--result", result(t, c), "--summary", "s")
    check("--verdict fail" in err and "check failed: test -f marker" in err, f"[DD-23] a failed check names fail: {err}")
    run("complete", c, "--task", t, "--attempt", 1, "--verdict", "fail", "--reason", "check failed")
    run("brief", c, "--task", t)
    check(item(t, c)["check_runs"] == [], "[DM-2] brief empties check_runs")
    open(os.path.join(WS, "marker"), "w").close()
    # a crash after the checks_run line: resume re-applies the exit codes without rerunning the commands
    with mock.patch.object(dc.os, "replace", side_effect=OSError("rename")):
        refused("state_write_failed", 3, "verify", c, "--task", t)
    runs_before = read(WS, "runs.txt")
    run("resume", "--task", t)
    check(read(WS, "runs.txt") == runs_before and [r["exit_code"] for r in item(t, c)["check_runs"]] == [0, 0],
          "[DM-5] resume re-applies verify from its line and runs no check command")
    run("complete", c, "--task", t, "--attempt", 2, "--verdict", "pass", "--result", result(t, c), "--summary", "s")
    runs = [x for x in record(t) if x["event"] == "checks_run"]
    check(item(t, c)["status"] == "done" and [x["data"]["attempt"] for x in runs] == [1, 2],
          "[DM-5] checks_run lines carry the attempt; pass is accepted after a passing verify")
    os.remove(os.path.join(WS, "marker"))

    # a command past check_timeout_s is stopped with every process it started
    ws = os.path.join(TMP, "timeout")
    os.makedirs(os.path.join(ws, ".atomic-decompose"))
    with open(os.path.join(ws, ".atomic-decompose", "config.json"), "w") as f:
        json.dump({"schema_version": 1, "profile": "quick", "profiles": {"quick": {"check_timeout_s": 1}}}, f)
    t = new_task("timeout case", ws)
    check(state(t)["check_timeout_s"] == 1, "[DM-9] check_timeout_s comes from the profile")
    s = cmd_leaf(t, "root", "Slow", "--check-cmd", "sleep 30 & echo $! > child.pid; wait")
    run("brief", s, "--task", t)
    import time
    t0 = time.time()
    out, _ = run("verify", s, "--task", t, code=1)
    pid = int(read(ws, "child.pid"))
    try:
        os.kill(pid, 0)
        alive = True
    except OSError:
        alive = False
    check(out["checks"][0]["exit_code"] is None and time.time() - t0 < 10 and not alive,
          "[API-5] a command past check_timeout_s counts as failing and its process group is killed")
    with open(os.path.join(ws, ".atomic-decompose", "config.json"), "w") as f:
        json.dump({"schema_version": 1, "profiles": {"bad": {"max_chain": 0}}}, f)
    refused("config_unreadable", 2, "init", "--root", ws, "--statement", "s", "--question", "q2")


def test_git_state_refusal():
    repo = make_repo("busy")
    t = new_task("busy case", repo)
    a = leaf(t, "root", "Edit", "--writes")
    head = git(repo, "rev-parse", "HEAD").stdout.strip()
    write(repo, ".git/MERGE_HEAD", head + "\n")
    err = refused("git_failed", 3, "brief", a, "--task", t)
    check("merge" in err and item(t, a)["status"] == "pending" and not refs(repo, t),
          f"[API-5] a writes brief during a merge refuses before any change: {err}")
    os.remove(os.path.join(repo, ".git", "MERGE_HEAD"))
    bare = os.path.join(TMP, "bare.git")
    git(TMP, "init", "-q", "--bare", bare)
    t = new_task("bare case", bare)
    a = leaf(t, "root", "Edit", "--writes")
    err = refused("git_failed", 3, "brief", a, "--task", t)
    check("bare" in err, f"[API-1] a bare repository refuses a writes brief: {err}")


def test_plan_shown_and_unneeded():
    repo = make_repo("shown")
    t = new_task("shown case", repo)
    a = leaf(t, "root", "Edit", "--writes")
    refused("bad_input", 2, "log", "plan_shown", "--task", t, "--data", '{"writes": []}')
    run("log", "plan_shown", "--task", t, "--data", json.dumps({"writes": [{"id": a, "paths": ["f.txt", "docs/"]}]}))
    run("brief", a, "--task", t)
    write(repo, "f.txt", "x\n")
    write(repo, "docs/a/b.md", "x\n")
    write(repo, "other.txt", "x\n")
    out, _ = run("changes", a, "--task", t)
    check(out["unlisted"] == ["other.txt"], f"[API-5] unlisted holds paths the shown plan does not cover: {out}")
    os.remove(os.path.join(repo, "other.txt"))
    run("complete", a, "--task", t, "--attempt", 1, "--verdict", "pass", "--result", result(t, a), "--summary", "s")
    err = refused("patch_not_reversed", 1, "drop", a, "--task", t, "--unneeded")
    check(item(t, a)["status"] == "done" and "apply -R" in err, f"[API-3] drop --unneeded needs the patch reversed: {err}")
    git(repo, "apply", "-R", os.path.join(t, item(t, a)["patch"]))
    out, _ = run("drop", a, "--task", t, "--unneeded")
    drop = [x for x in record(t) if x["event"] == "item_dropped"][-1]
    check(out["dropped"] == [a] and drop["data"]["cause"] == "unneeded after answer",
          "[DM-5] drop --unneeded logs cause 'unneeded after answer'")
    n = leaf(t, "root", "Pending")
    refused("not_droppable", 2, "drop", n, "--task", t, "--unneeded")


def test_finish_rerun_and_cleanup():
    repo = make_repo("finish")
    t = new_task("finish case", repo)
    a = cmd_leaf(t, "root", "Edit", "--writes", "--check-cmd", "grep -q TWO f.txt")
    run("brief", a, "--task", t)
    write(repo, "f.txt", "one\nTWO\nthree\n")
    run("verify", a, "--task", t)
    run("complete", a, "--task", t, "--attempt", 1, "--verdict", "pass", "--result", result(t, a), "--summary", "s")
    write(repo, "f.txt", "one\ntwo\nthree\n")  # a later change breaks the passed item's check
    n0 = len(record(t))
    err = refused("checks_failed", 1, "finish", "--task", t)
    check(state(t)["status"] == "active" and len(record(t)) == n0 and "--check-cmd 'grep -q TWO f.txt'" in err
          and "--writes" in err, f"[DD-24] a failing rerun changes nothing and names one fix leaf: {err}")
    fix = cmd_leaf(t, "root", "Fix the finish checks", "--writes", "--check-cmd", "grep -q TWO f.txt")
    for attempt in (1, 2, 3):
        run("brief", fix, "--task", t)
        run("complete", fix, "--task", t, "--attempt", attempt, "--verdict", "fail", "--reason", "could not")
    out, _ = run("finish", "--task", t)
    stopped = [x for x in record(t) if x["event"] == "stopped"][-1]
    check(out["status"] == "complete" and out["unresolved"][0]["command"] == "grep -q TWO f.txt"
          and stopped["data"]["cleaned"]["refs"] == 4 and not refs(repo, t) and not os.path.exists(os.path.join(t, "wt")),
          f"[DD-24] [DD-25] a command a failed fix leaf holds is skipped as unresolved; finish removes refs: {out}")


def test_one_entry():
    t = new_task("one entry")
    a = leaf(t, "root", "Only")
    check(run("next", "--task", t)[0]["one_entry"] is True, "[DD-9] a one-leaf plan is one entry")
    run("brief", a, "--task", t)
    run("complete", a, "--task", t, "--attempt", 1, "--verdict", "fail", "--reason", "retry")
    check(run("next", "--task", t)[0]["one_entry"] is True, "[DD-9] a retry inside the first entry keeps it true")
    leaf(t, "root", "Second")
    check(run("next", "--task", t)[0]["one_entry"] is False, "[DD-9] a second entry makes it false for good")
    t = new_task("explicit delegate", WS, "--mode", "delegate")
    leaf(t, "root", "Only")
    check(run("next", "--task", t)[0]["one_entry"] is False, "[DD-9] an explicit --mode delegate keeps it false")
    t = new_task("deferred")
    g = group(t, "root", "Later")
    leaf(t, "root", "Find", "--discovers", g)
    check(run("next", "--task", t)[0]["one_entry"] is False, "[DD-9] a childless deferred group keeps it false")


def test_answer_restores_running_writer():
    repo = make_repo("answer")
    t = new_task("answer case", repo)
    run("ask", "--task", t, "--type", "scope", "--text", "q", "--default", "d")
    run("answer", "--task", t, "--id", "Q1", "--text", "first", "--source", "user")
    a = leaf(t, "root", "Edit", "--writes", "--needs", "Q1")
    run("brief", a, "--task", t)
    write(repo, "f.txt", "changed\n")
    out, _ = run("answer", "--task", t, "--id", "Q1", "--text", "second", "--source", "user")
    line = [x for x in record(t) if x["event"] == "answer_changed"][-1]
    check(out["affected"][0].get("restored") == ["f.txt"] and line["data"]["affected"] == [{"id": a, "restored": ["f.txt"]}]
          and read(repo, "f.txt") == "one\ntwo\nthree\n", f"[API-4] [DM-5] answer records what it restored: {out}")


def test_chains():
    repo = make_repo("chain")
    t = new_task("chain case", repo)
    refused("unknown_ref", 2, "add", "--task", t, "--parent", "root", "--title", "Orphan", "--kind", "leaf",
            "--goal", "g", "--check", "c", "--returns", "r", "--chain-after", "1")
    s1 = leaf(t, "root", "Step 1", "--writes")
    refused("chain_invalid", 2, "add", "--task", t, "--parent", "root", "--title", "No dep", "--kind", "leaf",
            "--goal", "g", "--check", "c", "--returns", "r", "--writes", "--chain-after", s1)
    s2 = leaf(t, "root", "Step 2", "--writes", "--depends", s1, "--chain-after", s1)
    s3 = leaf(t, "root", "Step 3", "--writes", "--depends", s2, "--chain-after", s2)
    check(run("next", "--task", t)[0]["ready"] == [[s1, s2, s3]], "[API-14] next returns a chain as one entry")
    refused("not_ready", 2, "brief", s2, "--task", t)
    text, _ = run("brief", f"{s1},{s2},{s3}", "--task", t)
    check(text.count("Chain checkpoint:") == 3 and item(t, s1)["checkpoint"] and item(t, s2)["checkpoint"] is None
          and all(item(t, i)["worktree"] is None for i in (s1, s2, s3)),
          "[API-14] a lone chain runs in place, one checkpoint, a checkpoint line per step")
    write(repo, "f.txt", "one\nTWO\nthree\n")
    run("checkpoint", s1, "--task", t)
    write(repo, "a.txt", "step 2\n")
    run("checkpoint", s2, "--task", t)
    write(repo, "b.txt", "step 3 half\n")  # step 3 fails without a checkpoint
    refused("step_not_finished", 2, "changes", s3, "--task", t)
    out, _ = run("changes", s2, "--task", t)
    check([f["path"] for f in out["files"]] == ["a.txt"], f"[API-5] a step's changes span its own refs: {out}")
    run("complete", s1, "--task", t, "--attempt", 1, "--verdict", "pass", "--result", result(t, s1), "--summary", "s")
    run("complete", s2, "--task", t, "--attempt", 1, "--verdict", "pass", "--result", result(t, s2), "--summary", "s")
    with open(os.path.join(t, item(t, s2)["patch"])) as f:
        check("a.txt" in f.read(), "[DM-11] a chain step's patch is its own span")
    out, _ = run("complete", s3, "--task", t, "--attempt", 1, "--verdict", "fail", "--reason", "x")
    check(out["restored"] == ["b.txt"] and read(repo, "a.txt") == "step 2\n" and read(repo, "f.txt") == "one\nTWO\nthree\n",
          f"[API-14] the stopping step restores only its own span: {out}")

    # a worktree chain beside another writer; the first step fails, later steps are unrun
    repo = make_repo("chainwt")
    t = new_task("chain worktree", repo)
    s1 = leaf(t, "root", "Step 1", "--writes")
    s2 = leaf(t, "root", "Step 2", "--writes", "--depends", s1, "--chain-after", s1)
    other = leaf(t, "root", "Other", "--writes")
    run("brief", f"{s1},{s2}", "--task", t)
    check(item(t, s1)["worktree"] == item(t, s2)["worktree"] == os.path.join("wt", s1),
          "[API-14] a chain beside a ready writer shares one worktree named after its first step")
    wt = os.path.join(t, item(t, s1)["worktree"])
    write(wt, "f.txt", "chain\n")
    out, _ = run("complete", s1, "--task", t, "--attempt", 1, "--verdict", "fail", "--reason", "x")
    check(out["worktree_removed"] and not os.path.exists(wt), "[API-14] the stopping step removes the shared worktree")
    out, _ = run("complete", s2, "--task", t, "--attempt", 1, "--verdict", "held", "--reason", f"chain stopped at {s1}")
    held = [x for x in record(t) if x["event"] == "item_held"][-1]
    check(item(t, s2)["status"] == "pending" and item(t, s2)["attempts"] == 0 and "restored" not in held["data"]
          and "worktree_removed" not in held["data"], "[API-14] an unrun step is held and restores nothing")
    check(read(repo, "f.txt") == "one\ntwo\nthree\n" and other, "[API-14] the workspace is untouched")

    # a worktree chain that passes: each pass applies its own patch; the shared tree stays until the last step
    repo = make_repo("chainpass")
    t = new_task("chain pass", repo)
    s1 = leaf(t, "root", "Step 1", "--writes")
    s2 = cmd_leaf(t, "root", "Step 2", "--writes", "--depends", s1, "--chain-after", s1,
                  "--check-cmd", "test -f a.txt && test ! -f late.txt")
    leaf(t, "root", "Other", "--writes")
    run("brief", f"{s1},{s2}", "--task", t)
    wt = os.path.join(t, item(t, s1)["worktree"])
    write(wt, "f.txt", "one\nTWO\nthree\n")
    run("checkpoint", s1, "--task", t)
    write(wt, "a.txt", "step 2\n")
    run("checkpoint", s2, "--task", t)
    write(wt, "late.txt", "after the step ended\n")
    out, _ = run("verify", s2, "--task", t)
    check(out["passed"] and not os.path.exists(os.path.join(t, "wt", f"{s2}-check")),
          "[API-5] a chain step is verified in a check worktree of its -end ref, removed after")
    run("complete", s1, "--task", t, "--attempt", 1, "--verdict", "pass", "--result", result(t, s1), "--summary", "s")
    check(read(repo, "f.txt") == "one\nTWO\nthree\n" and not os.path.exists(os.path.join(repo, "a.txt"))
          and os.path.isdir(wt), "[API-14] a step's pass applies only its patch and keeps the shared worktree")
    run("verify", s2, "--task", t)
    run("complete", s2, "--task", t, "--attempt", 1, "--verdict", "pass", "--result", result(t, s2), "--summary", "s")
    check(read(repo, "a.txt") == "step 2\n" and not os.path.exists(os.path.join(repo, "late.txt"))
          and not os.path.exists(wt), "[API-14] the last step's pass removes the shared worktree")

    # chain_invalid: max_chain
    t = new_task("chain cap")
    prev = leaf(t, "root", "S1")
    for n in range(2, 6):
        prev = leaf(t, "root", f"S{n}", "--depends", prev, "--chain-after", prev)
    refused("chain_invalid", 2, "add", "--task", t, "--parent", "root", "--title", "S6", "--kind", "leaf", "--goal",
            "g", "--check", "c", "--returns", "r", "--depends", prev, "--chain-after", prev)


def test_replay_clears_worktree():
    repo = make_repo("replaywt")
    t = new_task("replay worktree", repo)
    a = leaf(t, "root", "A", "--writes")
    leaf(t, "root", "B", "--writes")
    run("brief", a, "--task", t)
    check(item(t, a)["worktree"], "[selftest] a runs in a worktree")
    with mock.patch.object(dc.os, "replace", side_effect=OSError("rename")):
        refused("state_write_failed", 3, "complete", a, "--task", t, "--attempt", 1, "--verdict", "fail",
                "--reason", "x")
    run("resume", "--task", t)
    check(item(t, a)["worktree"] is None and item(t, a)["status"] == "pending",
          "[DM-2] a re-applied fail sets worktree to null without git")


def main():
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("selftest: all assertions hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
