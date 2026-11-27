"""Runs: grouping items, briefs, landing worktree commits, the review and the task checks."""
from __future__ import annotations

import os
import shlex
import shutil

from ad.common import cmd_line, Fail, _now, TASK_DIR, TRIES
from ad.state import _quiet
from ad.vcs import covered, dirty_files, git, git_top, head, restore_paths, save_patch, untracked
from ad.checks import run_checks


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
            lines.append(f"Note [from {note['source']}]: {note['text']}" if isinstance(note, dict) else f"Note: {note}")
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


def shelve(task, run, paths, name):
    """Save the diff of `paths` to patches/<name> and put the files back as at HEAD. Returns a phrase for a
    note, or None when there was nothing to save. Files stay as they are when the patch cannot be written."""
    if not paths or not git_top(run["dir"]):
        return None
    patch = os.path.join(task.dir, "patches", name)
    try:
        save_patch(run["dir"], paths, patch)
    except (Fail, OSError, ValueError) as e:  # ValueError: git printed a file name that is not UTF-8
        return f"could not be saved ({e}), so its files are left as they were"
    restore_paths(run["dir"], paths)
    return f"is saved at {patch} (`git apply` it to reuse it)"


def restored(kept):
    """Whether `shelve` put the files back, given what it returned."""
    return bool(kept) and kept.startswith("is saved")


def land_run(task, st, run):
    top = st["git_top"]
    picks = [line[2:] for line in git(top, "cherry", "HEAD", run["branch"], run["base"]).stdout.split("\n")
             if line.startswith("+ ")]
    clash = []
    if picks:
        p = git(top, "cherry-pick", *picks, check=False)
        if p.returncode != 0:
            clash = [p for p in git(top, "diff", "--name-only", "-z", "--diff-filter=U", check=False)
                     .stdout.split("\0") if p]
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
    left = dirty_files(git_top(run["dir"]), run["dir"])
    for p, h in left.items():                       # new files outside every item's files:
        dest = os.path.join(st["root"], p)          # finish lists them in untracked_left
        if untracked(h) and not os.path.lexists(dest):
            os.makedirs(os.path.dirname(dest), exist_ok=True)
            shutil.copy2(os.path.join(run["dir"], p), dest, follow_symlinks=False)
    outside = [p for p, h in left.items() if not untracked(h)]  # tracked edits no item owns go with the worktree
    if outside:
        patch = os.path.join(task.dir, "patches", f"{run['id']}-outside.patch")
        with _quiet(Fail, OSError, ValueError):  # a patch that cannot be saved must not stop the landing
            save_patch(run["dir"], outside, patch)
            run["outside"] = patch
    git(top, "worktree", "remove", "--force", run["worktree"], check=False)
    if clash:
        run["branch_kept"] = True
    else:
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
