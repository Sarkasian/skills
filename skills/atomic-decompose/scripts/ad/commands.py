"""One function per command."""
from __future__ import annotations

import datetime as _dt
import json
import os
import re
import shlex
import shutil

from ad.common import (AUTO_FIXES, CHECK_TIMEOUT_S, cmd_line, _csv, ENV_MAX_PARALLEL, Fail, MAX_PARALLEL,
                       MAX_PARALLEL_LIMIT, _now, PROJECT_CONFIG, SCHEMA, SCRIPT, TASK_DIR, TRIES, _ts, VERSION)
from ad.state import locked, _quiet, resolve_max_parallel, Task, usable_max_parallel, user_config_path
from ad.plan import apply_plan, _list, _norm_path, plan_items, read_plan_file, write_plan_file
from ad.vcs import add_paths, changed_since, covered, dirty_files, git, git_top, head, untracked
from ad.checks import check_unrunnable, run_checks, tail
from ad.runs import (fail_item, item_commits, items_by_id, plan_runs, prompt_for, result_path, review_due,
                     settle_runs, shelve, start_review, start_runs, task_checks, unchanged_note)


def cmd_start(a):
    root = os.path.realpath(a.root)
    if not os.path.isdir(root):
        raise Fail("bad_input", f"no folder {root}", 2)
    plan = read_plan_file(a.plan)
    top = git_top(root)
    max_parallel, max_layer, config_problems = resolve_max_parallel(a.max_parallel, plan, root, top)
    if max_parallel is None:  # the first layer that is set cannot be used; its problem is the first one listed
        # the flag and the plan are the coordinator's own input; the other layers belong to the user's machine
        mine = {"flag": "pass --max-parallel", "plan": "give the plan's max_parallel"}.get(max_layer)
        raise Fail("plan_invalid" if max_layer == "plan" else "bad_input", config_problems[0], 2,
                   "needs_fix" if mine else "needs_user",
                   f"{mine} an integer from 1 to {MAX_PARALLEL_LIMIT}, or leave it out, then rerun start" if mine
                   else "ask the user to fix or remove that setting, then rerun start; "
                        f"python3 {shlex.quote(SCRIPT)} doctor --root {shlex.quote(root)} lists every layer")
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
          "max_parallel": max_parallel, "max_parallel_layer": max_layer,
          "review": a.review, "review_state": "none", "auto_fixes": 0,
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
    except Fail:  # lint: no-dry-run: removes only the task folder this call just created
        shutil.rmtree(tdir, ignore_errors=True)
        with _quiet():
            os.rmdir(os.path.dirname(tdir))
        raise
    with open(os.path.join(root, TASK_DIR, ".gitignore"), "w", encoding="utf-8") as f:
        f.write("*\n")  # task state, logs and worktrees stay out of the user's commits and stashes
    task.save(st)
    task.event("engaged", None, {"statement": a.statement, "version": VERSION})
    task.event("plan_changed", None, out)
    out = {"task_dir": tdir, "plan": task.plan_path, "max_parallel": max_parallel,
           "max_parallel_layer": max_layer}
    return {**out, **({"config_problems": config_problems} if config_problems else {}),
            **locked(task, lambda s: advance(task, s))}


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
        cap = plan.get("max_parallel")  # read once, at start: a stale plan file must not undo a tune
        if cap is not None and cap != st["max_parallel"]:
            raise Fail("plan_invalid", f"the plan file sets max_parallel {cap!r}; the task has "
                       f"{st['max_parallel']} and `plan` does not change it", 2, "needs_fix",
                       "take max_parallel out of the plan file and rerun; to change the task's value run "
                       + cmd_line(task, "tune", "--max-parallel", "N"))
        out = apply_plan(st, plan, task)
        task.event("plan_changed", None, out)
        task.save(st)
        return {**out, "next": cmd_line(task, "next")}
    return locked(task, go)


def cmd_tune(task, a):
    def go(st):
        if not usable_max_parallel(a.max_parallel):
            raise Fail("bad_input", f"max_parallel must be an integer from 1 to {MAX_PARALLEL_LIMIT}", 2)
        old = st["max_parallel"]
        st["max_parallel"], st["max_parallel_layer"] = a.max_parallel, "tune"
        task.save(st)
        task.event("tune", None, {"max_parallel": a.max_parallel, "previous": old})
        # `next` closes the active runs and charges each unfinished item a try, so it must wait for them
        wait = (" once every executor of the active runs has replied; the new value applies to the round it starts"
                if any(r["status"] == "active" for r in st["runs"]) else "")
        return {"max_parallel": a.max_parallel, "previous": old, "next": cmd_line(task, "next") + wait}
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


def cmd_annotate(task, a):
    def go(st):
        it = items_by_id(st).get(a.item)
        if it is None:
            raise Fail("bad_input", f"no item {a.item}; items are {', '.join(items_by_id(st)) or 'none'}", 2)
        if a.note is None:  # the script's own notes are plain strings
            return {"id": it["id"], "status": it["status"], "next": cmd_line(task, "next"),
                    "notes": [n if isinstance(n, dict) else {"text": n, "source": "script"} for n in it["notes"]]}
        note = " ".join(a.note.split())  # one line, so that a note cannot pass for another line of the brief
        if not 0 < len(note) <= 5000:
            raise Fail("bad_input", "--note must have 1 to 5,000 characters", 2)
        if it["status"] in ("done", "dropped"):
            raise Fail("bad_input", f"item {a.item} is {it['status']}, so no executor would read the note", 2)
        it["notes"].append({"text": note, "source": a.source, "at": _now()})
        task.event("annotated", it["id"], {"note": note, "source": a.source})
        task.save(st)
        return {"id": it["id"], "note_added": True, "next": cmd_line(task, "next"), **(
            {"warning": "the item is running, so only a retry of it reads the note"} if it["status"] == "running" else {})}
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


def cmd_doctor(a):
    root = os.path.realpath(a.root)
    if not os.path.isdir(root):
        raise Fail("bad_input", f"no folder {root}", 2)
    top = git_top(root)
    value, layer, problems = resolve_max_parallel(a.max_parallel, {}, root, top)  # what a start here would get
    return {"max_parallel": value, "layer": layer,
            "layers": {"default": MAX_PARALLEL, "env": os.environ.get(ENV_MAX_PARALLEL),
                       "user_config": user_config_path(),
                       "project_config": os.path.join(top or root, PROJECT_CONFIG)},
            "git": {"root": root, "top": top, "worktrees": top is not None}, "cpus": os.cpu_count(),
            "problems": problems,
            "next": f"start refuses here until the {layer} setting is fixed or removed" if value is None else
                    "start --max-parallel N sets the task value; ad tune --max-parallel N --task <dir> "
                    "changes it for the next round"}


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
            "max_parallel": st["max_parallel"],
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
