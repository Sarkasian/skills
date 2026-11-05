#!/usr/bin/env python3
"""Runnable check (TDD §8): `python3 selftest.py` exits 0 when every assertion holds.

Standard library only, plus `git` for the coordinator plays. Runs C-4 (the installed
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
    # a first round after an item started is round 2 at least
    run("answer", "--task", t2, "--id", "Q1", "--text", "x", "--source", "user", code=2)
    leaf(t2, "root", "only")
    run("brief", "1", "--task", t2)
    run("ask", "--task", t2, "--type", "user_only", "--text", "mid", "--default", "d")
    out, _ = run("asked", "--task", t2, "--ids", "Q1")
    check(out["round"] == 2, "[US-4] [API-4] a question asked after work started is round 2")
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
                 "Results you build on:", "Skill: none", "Completion checklist:", "- [ ] c", "Return format: r",
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


def _diff_items(t, repo):
    a, b = leaf(t, "root", "Edit A"), leaf(t, "root", "Edit B")
    with open(os.path.join(repo, "f.txt"), "w") as f:
        f.write("one\ntwo\nthree\n")
    git(repo, "add", ".")
    git(repo, "-c", "user.email=t@t", "-c", "user.name=t", "commit", "-qm", "base")
    return a, b


def _patch(repo, before, after):
    """Unified diff from `before` to `after`; leaves the file and index at the committed base."""
    path = os.path.join(repo, "f.txt")
    for text in (before, after):
        with open(path, "w") as f:
            f.write(text)
        if text is before:
            git(repo, "add", "f.txt")
    d = git(repo, "diff").stdout
    git(repo, "reset", "-q", "--hard")
    return d


def test_coordinator_diffs():
    for name in ("clash", "reverse"):
        repo = os.path.join(TMP, name)
        os.makedirs(repo)
        git(repo, "init", "-q")
        t = new_task(f"diff {name}", repo)
        a, b = _diff_items(t, repo)
        base = "one\ntwo\nthree\n"
        da = _patch(repo, base, "one\nTWO\nthree\n")
        if name == "clash":
            db = _patch(repo, base, "one\n2\nthree\n")
            run("brief", f"{a}", "--task", t)
            run("brief", f"{b}", "--task", t)
            for i, d in ((a, da), (b, db)):
                with open(rpath(t, i), "w") as f:
                    f.write(d)
            git(repo, "apply", rpath(t, a))
            run("complete", a, "--task", t, "--attempt", 1, "--verdict", "pass", "--result", rpath(t, a),
                "--summary", "a")
            p = git(repo, "apply", "--check", rpath(t, b), ok=False)
            check(p.returncode != 0, "[DD-15] second clashing diff fails git apply --check")
            run("complete", b, "--task", t, "--attempt", 1, "--verdict", "fail",
                "--reason", f"clash with {a}: {p.stderr.strip()}")
            check(item(t, b)["summary"].startswith(f"clash with {a}"), "[DD-15] clash reason recorded")
        else:
            db = _patch(repo, "one\nTWO\nthree\n", "one\nTWO!\nthree\n")
            for i, d, text in ((a, da, "one\nTWO\nthree\n"), (b, db, "one\nTWO!\nthree\n")):
                run("brief", i, "--task", t)
                with open(rpath(t, i), "w") as f:
                    f.write(d)
                git(repo, "apply", rpath(t, i))
                run("complete", i, "--task", t, "--attempt", 1, "--verdict", "pass", "--result", rpath(t, i),
                    "--summary", i)
            order = [x["ref"] for x in record(t) if x["event"] == "item_done"]
            check(order == [a, b], "[DD-15] item_done lines give the apply order")
            p = git(repo, "apply", "-R", "--check", rpath(t, order[0]), ok=False)
            check(p.returncode != 0, "[DD-15] reversing earliest first fails")
            for i in reversed(order):
                git(repo, "apply", "-R", rpath(t, i))
            check(open(os.path.join(repo, "f.txt")).read() == base, "[DD-15] latest first reverses both")


def main():
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("selftest: all assertions hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
