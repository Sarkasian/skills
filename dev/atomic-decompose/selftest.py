#!/usr/bin/env python3
"""Runnable check: `python3 selftest.py` exits 0 when every assertion holds.

Standard library only, plus `git`. Runs `skills/atomic-decompose/scripts/decompose.py` in-process against
temporary git repositories with HOME pointed into a temporary folder, and `report.py` beside this file on
sample evaluation runs and weekly records.
"""
from __future__ import annotations

import contextlib
import hashlib
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
for k, v in {"GIT_AUTHOR_NAME": "t", "GIT_AUTHOR_EMAIL": "t@t", "GIT_COMMITTER_NAME": "t",
             "GIT_COMMITTER_EMAIL": "t@t", "GIT_CONFIG_NOSYSTEM": "1"}.items():
    os.environ[k] = v
TEST = "python3 -m unittest -q"


def check(cond, msg):
    if not cond:
        print(f"FAIL {msg}", file=sys.stderr)
        sys.exit(1)


def run(*args, code=0):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = dc.main([str(a) for a in args])
    check(rc == code, f"{' '.join(map(str, args))} exited {rc}, expected {code}\n{err.getvalue()}")
    text = out.getvalue().strip()
    return (json.loads(text) if text else None), err.getvalue()


def refused(code, exit_code, *args):
    _, err = run(*args, code=exit_code)
    m = re.match(r"ERROR \[(\w+)\] ", err)
    check(m and m.group(1) == code, f"{args[0]} expected {code}, got: {err}")
    return err


def sh(cwd, *cmd):
    return subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, check=True).stdout


_n = [0]


def repo(files=None):
    """A git repo with a passing unittest suite in mod.py / test_mod.py."""
    _n[0] += 1
    root = os.path.join(TMP, f"repo{_n[0]}")
    os.makedirs(root)
    files = files or {"mod.py": "def base():\n    return 1\n",
                      "test_mod.py": "import unittest\nimport mod\n\n\nclass Base(unittest.TestCase):\n"
                                     "    def test_base(self):\n        self.assertEqual(mod.base(), 1)\n",
                      "other.py": "X = 1\n", "README.md": "# r\n"}
    for name, text in files.items():
        os.makedirs(os.path.dirname(os.path.join(root, name)) or root, exist_ok=True)
        with open(os.path.join(root, name), "w") as f:
            f.write(text)
    sh(root, "git", "init", "-q")
    sh(root, "git", "add", ".")
    sh(root, "git", "commit", "-qm", "base")
    return root


def item(title, files, covers="R1", **kw):
    return {"title": title, "goal": f"do {title}", "covers": [covers], "files": files,
            "check_cmd": [TEST] if files else [], **kw}


def plan_file(items, requirements=("r1",), questions=(), check_cmd=(TEST,), name=None):
    _n[0] += 1
    path = os.path.join(TMP, name or f"plan{_n[0]}.json")
    with open(path, "w") as f:
        json.dump({"question": "Is it done?", "requirements": list(requirements), "questions": list(questions),
                   "check_cmd": list(check_cmd), "items": items}, f)
    return path


def start(root, items, *extra, **kw):
    out, _ = run("start", "--root", root, "--statement", "do it", "--plan", plan_file(items, **kw), *extra)
    return out["task_dir"], out


def state(t):
    with open(os.path.join(t, "state.json")) as f:
        return json.load(f)


def it(t, i):
    return next(x for x in state(t)["items"] if x["id"] == i)


def events(t):
    with open(os.path.join(t, "record.jsonl")) as f:
        return [json.loads(line) for line in f]


def append(path, text):
    with open(path, "a") as f:
        f.write(text)


def add_test(root, name, body="self.assertTrue(True)"):
    append(os.path.join(root, "test_mod.py"), f"\n\nclass {name}(unittest.TestCase):\n    def test_it(self):\n"
                                              f"        {body}\n")


def log_subjects(root):
    return sh(root, "git", "log", "--format=%s").split("\n")[:-1]


# ---------------------------------------------------------------- plan

def test_plan_problems_all_at_once():
    root = repo()
    err = refused("plan_invalid", 2, "start", "--root", root, "--statement", "s", "--plan", plan_file(
        [{"title": "A", "files": ["mod.py"]}, {"title": "A", "goal": "g", "check": []},
         {"title": "C", "goal": "g", "files": ["/abs"], "check_cmd": "x", "covers": "R9", "depends": ["7"]}],
        requirements=("r1", "r2")))
    for text in ("needs a `goal`", "needs `check_cmd`", "title also used", "needs `check`", "must be a path",
                 "covers R9", "depends on 7", "R1 (r1): no item", "R2 (r2): no item"):
        check(text in err, f"[W2] start lists every plan problem at once: {text}\n{err}")
    check(not os.path.exists(os.path.join(root, dc.TASK_DIR)) or not os.listdir(os.path.join(root, dc.TASK_DIR)),
          "[W12] a refused start leaves no task folder")


def test_plan_lenient_forms():
    root = repo()
    path = os.path.join(TMP, "dict-plan.json")
    with open(path, "w") as f:
        json.dump({"question": "q", "requirements": "one", "items": {"a": {
            "title": "A", "goal": "g", "covers": "R1", "files": "mod.py", "check_cmd": TEST, "returns": "x"}}}, f)
    out, _ = run("start", "--root", root, "--statement", "s", "--plan", path)
    check(out["action"] == "do_yourself" and it(out["task_dir"], "1")["files"] == ["mod.py"],
          "[W2] items as an object, strings for lists and unknown keys are accepted")


def test_cycle_and_dirty_files():
    root = repo()
    err = refused("plan_invalid", 2, "start", "--root", root, "--statement", "s", "--plan", plan_file(
        [item("A", ["mod.py"], depends=["2"]), item("B", ["other.py"], depends=["1"])]))
    check("cycle" in err, "[W2] a depends cycle is a plan problem")
    err = refused("plan_invalid", 2, "start", "--root", root, "--statement", "s", "--plan", plan_file(
        [{"title": "A", "goal": "g", "files": ["mod.py"], "check_cmd": ["python3", "-m", "unittest"]}]))
    check("whole in one string" in err, "[W2] a check command split into words is a plan problem")
    append(os.path.join(root, "mod.py"), "# wip\n")
    err = refused("dirty_files", 1, "start", "--root", root, "--statement", "s",
                  "--plan", plan_file([item("A", ["mod.py"])]))
    check("mod.py" in err, "[W14] start refuses planned files with uncommitted changes")
    refused("files_not_found", 1, "start", "--root", TMP, "--statement", "s", "--plan", plan_file([item("A", ["mod.py"])]))
    name = os.path.basename(root)
    err = refused("nested_repo", 1, "start", "--root", os.path.dirname(repo()), "--statement", "s",
                  "--plan", plan_file([item("A", [f"{name}/other.py"])]))
    check(f"--root {root}" in err, "[W2] start refuses a root above the repository and names the right one")
    out, _ = run("start", "--root", repo(), "--statement", "s", "--new-files", "--plan", plan_file([item("A", ["new.py"])]))
    check(out["action"] == "do_yourself", "[W2] --new-files allows a plan whose files are all new")


# ---------------------------------------------------------------- one run

def test_single_run_in_place():
    root = repo()
    append(os.path.join(root, "notes.txt"), "user wip\n")  # unplanned dirty file: never counted as the task's
    t, out = start(root, [item("Add a", ["mod.py", "test_mod.py"]), item("Add b", ["mod.py", "test_mod.py"])])
    check(out["action"] == "do_yourself" and out["items"] == ["1", "2"],
          "[W15] items sharing files form one run, done in the main session")
    brief = open(out["brief"]).read()
    check(len(brief) < 2500 and "RESULT" not in brief and "CHECK" not in brief and "done 1" in brief,
          f"[W7] the brief is short, has no reply protocol and names each done command ({len(brief)} chars)")
    check(not os.path.exists(os.path.join(t, "wt")), "[W15] one run needs no worktree")
    add_test(root, "A")
    err = refused("out_of_order", 1, "done", "2", "--task", t)
    check("item 1 comes before item 2" in err, "[W15] a brief's items are finished in order, by one executor")
    out, _ = run("done", "1", "--task", t)
    check(out["status"] == "done" and out["next"].startswith("next item: 2"), "[W6] done passes and names the next")
    check(log_subjects(root)[0] == "Add a", "[W14] done commits the item, titled after it")
    check("notes.txt" not in sh(root, "git", "show", "--name-only", "--format=", "HEAD"),
          "[W14] the commit holds only the item's files")
    refused("no_changes", 1, "done", "2", "--task", t)
    append(os.path.join(root, "other.py"), "Y = 2\n")
    add_test(root, "B")
    err = refused("outside_files", 1, "done", "2", "--task", t)
    check("other.py" in err, "[W5] done refuses a change outside the item's files")
    sh(root, "git", "checkout", "other.py")
    out, _ = run("done", "2", "--task", t)
    check(out["next"].startswith("every item"), "[W6] the last done says the brief is finished")
    out, _ = run("next", "--task", t)
    check(out["action"] == "report" and state(t)["status"] == "complete" and out["cost"]["done"] == 2,
          "[W15] next finishes the task when nothing is left")
    check("item 1 never changed mod.py" in out["unchanged"] and "item 2" in out["unchanged"],
          "[W6] next names the planned files an item never changed")
    check(open(os.path.join(root, "notes.txt")).read() == "user wip\n", "[W14] the user's own changes are kept")
    check({"engaged", "item_started", "item_done", "stopped"} <= {e["event"] for e in events(t)},
          "[W11] the run record has the report's events")


def test_check_failures_and_retry_limit():
    root = repo()
    t, _ = start(root, [item("Break", ["mod.py"]), item("Next", ["other.py"], depends=["1"]),
                        item("Free", ["mod.py"], check_cmd=["true"])])
    check([r["items"] for r in state(t)["runs"]] == [["1", "2", "3"]],
          "[W15] a dependant joins its dependency's run")
    append(os.path.join(root, "mod.py"), "def base():\n    return 2\n")
    for n in (1, 2):
        err = refused("check_failed", 1, "done", "1", "--task", t)
        check(f"try {n} of 3" in err and "AssertionError" in err, "[W6] a failed check shows the log tail and the try")
    err = refused("item_failed", 1, "done", "1", "--task", t)
    check("return 1" in open(os.path.join(root, "mod.py")).read(), "[W14] the third failure restores the files")
    check("return 2" in open(os.path.join(t, "patches", "1.patch")).read(), "[W14] the failed diff is kept")
    check(it(t, "2")["status"] == "failed" and "depends on item 1" in it(t, "2")["failure"],
          "[W6] work that needs a failed item fails with the reason")
    refused("not_running", 1, "done", "2", "--task", t)
    append(os.path.join(root, "mod.py"), "# free\n")
    run("done", "3", "--task", t)
    out, _ = run("next", "--task", t)
    check(out["action"] == "report" and [f["id"] for f in out["failed"]] == ["1", "2"],
          "[W9] the report lists failed items; the rest carried on")


def test_broken_check_is_not_a_try():
    root = repo()
    t, _ = start(root, [item("A", ["mod.py"], check_cmd=["no-such-tool --x"])])
    append(os.path.join(root, "mod.py"), "#\n")
    refused("check_broken", 1, "done", "1", "--task", t)
    check(it(t, "1")["tries"] == 0, "[W6] a check that cannot run does not use a try")


def test_returned_without_done_retries():
    root = repo()
    t, _ = start(root, [item("A", ["mod.py", "test_mod.py"])])
    add_test(root, "Partial")  # partial work, executor gone
    out, _ = run("next", "--task", t)
    check(out["action"] == "do_yourself" and it(t, "1")["tries"] == 1, "[W6] an item with no done is retried")
    check("earlier executor" in open(out["brief"]).read(), "[W7] the retry brief says work may be partly there")
    out, _ = run("done", "1", "--task", t)
    check(out["status"] == "done", "[W6] the earlier partial work counts as the item's change")


def test_rename_block_lock_and_read_only():
    root = repo()
    t, _ = start(root, [item("Move", ["other.py", "moved.py"], check_cmd=["true"]),
                        item("Half", ["README.md"], check_cmd=["true"]), item("Next", ["README.md"], check_cmd=["true"])])
    r1, r2 = (r["dir"] for r in state(t)["runs"])
    sh(r1, "git", "mv", "other.py", "moved.py")
    out, _ = run("done", "1", "--task", t)
    check(out["status"] == "done" and "moved.py" in sh(r1, "git", "ls-files"), "[W14] a git mv item commits")
    append(os.path.join(r2, "README.md"), "half\n")
    run("block", "2", "--question", "Which title?", "--task", t)
    check(open(os.path.join(r2, "README.md")).read() == "# r\n" and "before the block" in it(t, "2")["notes"][0],
          "[W14] block saves the item's partial work and puts its files back")
    open(os.path.join(t, ".lock"), "w").close()  # created by a live command that has not written its pid yet
    with mock.patch.object(dc, "LOCK_WAIT_S", 0.3):
        refused("task_locked", 3, "decide", "--question", "q", "--chosen", "c", "--because", "b", "--task", t)
    os.remove(os.path.join(t, ".lock"))
    root = repo()
    t, _ = start(root, [{"title": "Read", "goal": "g", "covers": ["R1"], "check": ["c"]}])
    append(os.path.join(root, "mod.py"), "#\n")
    append(os.path.join(t, "results", "1.md"), "r\n")
    refused("outside_files", 1, "done", "1", "--task", t)


def test_lost_state_write_after_commit():
    root = repo()
    t, _ = start(root, [item("A", ["mod.py"])])
    append(os.path.join(root, "mod.py"), "#\n")
    with mock.patch.object(dc.os, "replace", side_effect=OSError("disk")):
        refused("state_write_failed", 3, "done", "1", "--task", t)
    check(it(t, "1")["status"] == "running" and log_subjects(root)[0] == "A", "[W12] the state is not overwritten")
    out, _ = run("done", "1", "--task", t)
    check(out["status"] == "done" and out["commit"] == sh(root, "git", "rev-parse", "HEAD").strip(),
          "[W12] rerunning done finds the item's commit")


# ---------------------------------------------------------------- parallel

def test_parallel_runs_land_in_order():
    root = repo()
    t, out = start(root, [item("Mod", ["mod.py"]), item("Other", ["other.py"]),
                          {"title": "Read", "goal": "summarise", "covers": ["R1"], "check": ["names both files"]}])
    check(out["action"] == "dispatch" and len(out["runs"]) == 3, "[W15] runs that share no file go out at once")
    runs = state(t)["runs"]
    check(runs[0]["worktree"] and runs[1]["worktree"] and runs[2]["worktree"] is None,
          "[W15] each writes run gets a worktree; a read-only run needs none")
    for r, name in ((runs[0], "mod.py"), (runs[1], "other.py")):
        append(os.path.join(r["dir"], name), "# change\n")
    run("done", "1", "--task", t)
    run("done", "2", "--task", t)
    refused("no_result", 1, "done", "3", "--task", t)
    os.makedirs(os.path.join(t, "results"), exist_ok=True)
    append(os.path.join(t, "results", "3.md"), "both files\n")
    run("done", "3", "--task", t)
    check(log_subjects(root)[0] == "base", "[W14] worktree commits stay off HEAD until next")
    out, _ = run("next", "--task", t)
    check(log_subjects(root)[:2] == ["Other", "Mod"], "[W14] next lands each run's commits in plan order")
    check(out["action"] == "review" and state(t)["review_state"] == "running",
          "[W6] two landed runs get one review")
    check(not os.path.exists(runs[0]["worktree"]), "[W15] a landed run's worktree is removed")
    check(it(t, "1")["commit"] == sh(root, "git", "rev-parse", "HEAD~1").strip(), "[W14] commits are remapped")
    append(os.path.join(t, "review.md"), "low mod.py:2 comment -> none\n")
    out, _ = run("next", "--task", t)
    check(out["action"] == "finish" and out["review"].endswith("review.md"), "[W6] the review result is handed back")
    out, _ = run("finish", "--task", t)
    check(out["status"] == "complete" and out["review"], "[W9] finish completes and names the review")


def test_delegated_run_is_reviewed():
    root = repo()
    t, out = start(root, [item("Add a", ["mod.py", "test_mod.py"])], "--mode", "delegate")
    check(out["action"] == "dispatch", "[W15] --mode delegate hands a single run to an executor")
    add_test(root, "A")
    run("done", "1", "--task", t)
    out, _ = run("next", "--task", t)
    check(out["action"] == "review" and "has landed" in out["next"],
          "[W6] work an executor did is reviewed, and the user hears it has landed first")
    brief = open(os.path.join(t, "briefs", "r2-review.md")).read()
    check("never changed mod.py" in out["unchanged"] and "item 1 never changed mod.py" in brief,
          "[W6] the unchanged planned file is named to the coordinator and to the reviewer")


def test_merge_conflict_redoes_the_item():
    root = repo()
    t, out = start(root, [item("Mod", ["mod.py"]), item("Other", ["other.py"])])
    runs = state(t)["runs"]
    for r, (i, name) in zip(runs, (("1", "mod.py"), ("2", "other.py"))):
        append(os.path.join(r["dir"], name), "# change\n")
        run("done", i, "--task", t)
    append(os.path.join(root, "mod.py"), "# user edit\n")  # the user commits on the same lines meanwhile
    sh(root, "git", "commit", "-qam", "user")
    out, _ = run("next", "--task", t)
    check(out["action"] == "do_yourself" and out["items"] == ["1"] and "clashed in mod.py" in open(out["brief"]).read(),
          "[W5] a run that clashes with HEAD goes back to be redone on the current files")
    check(sh(root, "git", "status", "--porcelain", "--untracked-files=no") == "", "[W14] the failed pick is undone")
    check(runs[0]["branch"] in sh(root, "git", "branch"), "[W14] the clashing attempt stays on its branch")


def test_land_blocked_by_staged_change():
    root = repo()
    t, _ = start(root, [item("Mod", ["mod.py"]), item("Other", ["other.py"])])
    for r, (i, name) in zip(state(t)["runs"], (("1", "mod.py"), ("2", "other.py"))):
        append(os.path.join(r["dir"], name), "# change\n")
        run("done", i, "--task", t)
    append(os.path.join(root, "README.md"), "user\n")
    sh(root, "git", "add", "README.md")
    out, _ = run("next", "--task", t)
    check(out["action"] == "stop" and out["condition"] == "land_blocked", "[W5] a staged user change stops landing")
    sh(root, "git", "reset", "-q")
    run("resume", "--task", t)
    out, _ = run("next", "--task", t)
    check(out["action"] == "review" and log_subjects(root)[:2] == ["Other", "Mod"], "[W5] resume clears it")


def test_worktree_leftovers_are_kept():
    root = repo()
    with open(os.path.join(root, ".gitignore"), "w") as f:
        f.write("local.cfg\n")
    append(os.path.join(root, "local.cfg"), "x\n")
    t, _ = start(root, [item("Mod", ["mod.py"], check_cmd=["test -f local.cfg"]), item("Other", ["other.py"])])
    r1, r2 = state(t)["runs"]
    append(os.path.join(r1["dir"], "mod.py"), "# change\n")
    append(os.path.join(r1["dir"], "helper.txt"), "made by 1\n")
    out, _ = run("done", "1", "--task", t)
    check(out["not_committed"] == ["helper.txt"], "[W15] a worktree sees ignored local files; strays are named")
    append(os.path.join(r2["dir"], "other.py"), "# half done\n")
    run("next", "--task", t)
    check(open(os.path.join(root, "helper.txt")).read() == "made by 1\n", "[W14] a worktree's stray file is kept")
    check("half done" in open(os.path.join(t, "patches", f"2-{r2['id']}.patch")).read()
          and "partial work" in " ".join(it(t, "2")["notes"]), "[W14] unfinished worktree work is saved as a patch")
    check(sh(root, "git", "status", "--porcelain", dc.TASK_DIR) == "", "[W14] the task folder is git-ignored")


def test_task_checks_add_a_fix_item():
    root = repo()
    t, _ = start(root, [item("Mod", ["mod.py"], check_cmd=["true"])])
    append(os.path.join(root, "mod.py"), "def base():\n    return 3\n")
    run("done", "1", "--task", t)
    out, _ = run("next", "--task", t)
    fix = state(t)["items"][-1]
    check(out["action"] == "do_yourself" and fix["origin"] == "task_checks" and "mod.py" in fix["files"],
          "[W6] failing task checks after a run add a fix item over its files")


def test_delegate_single_run():
    root = repo()
    t, out = start(root, [item("A", ["mod.py"])], "--mode", "delegate")
    check(out["action"] == "dispatch" and len(out["runs"]) == 1 and state(t)["runs"][0]["worktree"] is None,
          "[W7] delegate mode sends one run to one executor, in place")


def test_fan_in_waits():
    root = repo()
    t, out = start(root, [item("A", ["mod.py"]), item("B", ["other.py"]),
                          item("C", ["README.md"], depends=["1", "2"])])
    check(out["action"] == "dispatch" and [r["items"] for r in out["runs"]] == [["1"], ["2"]],
          "[W15] an item waiting on two runs waits for the next round")


# ---------------------------------------------------------------- questions, stops, decisions

def test_question_round_and_block():
    root = repo()
    q = {"type": "scope", "text": "Which name?", "default": "foo", "because": "README"}
    t, out = start(root, [item("A", ["mod.py"], needs=["Q1"]), item("B", ["other.py"])],
                   questions=[q, {"type": "scope", "text": "Tabs?", "default": "no"}])
    check(out["action"] == "ask" and out["questions"][0]["default"] == "foo" and out["plan"],
          "[W3] start prints the question round with defaults and the plan")
    refused("open_questions", 1, "next", "--task", t)
    run("answer", "--defaults", "--task", t)
    check(state(t)["questions"][0]["answer_source"] == "default_accepted", "[W3] --defaults settles the defaults")
    out, _ = run("next", "--task", t)
    check(out["action"] == "dispatch" and "Q1: Which name? = foo" in open(state(t)["runs"][0]["brief"]).read(),
          "[W4] the brief carries the settled answer")
    check("Q2: Tabs? = no" in open(state(t)["runs"][1]["brief"]).read(),
          "[W4] an answer no item needs goes into every brief")
    run("block", "2", "--approval", "delete other.py", "--task", t)
    append(os.path.join(state(t)["runs"][0]["dir"], "mod.py"), "#\n")
    run("done", "1", "--task", t)
    out, _ = run("next", "--task", t)
    check(out["action"] == "stop" and out["approvals"] == ["2"] and "never approve" in out["next"],
          "[W5] an approval stops the task once the other work is done")
    refused("task_stopped", 1, "plan", "--task", t)
    run("resume", "--deny", "2", "--task", t)
    out, _ = run("next", "--task", t)
    check(out["action"] == "do_yourself" and "The user refused: delete other.py" in open(out["brief"]).read(),
          "[W5] the refusal reaches the retried item")
    run("block", "2", "--question", "Keep X?", "--task", t)
    out, _ = run("next", "--task", t)
    check(out["action"] == "stop" and out["questions"][0]["text"] == "Keep X?", "[W5] a mid-task question stops")
    out, _ = run("answer", "--id", "Q3", "--text", "yes", "--task", t)
    check(it(t, "2")["status"] == "pending" and "resume" in out["next"], "[W5] the answer frees the item")
    out, _ = run("answer", "--id", "Q1", "--text", "bar", "--task", t)
    check(out["answered"][0]["affected"] == ["1"], "[W4] a changed answer names the done items it affects")


def test_plan_edit():
    root = repo()
    t, _ = start(root, [item("A", ["mod.py"]), item("B", ["mod.py"], check_cmd=["false"])])
    append(os.path.join(root, "mod.py"), "#\n")
    run("done", "1", "--task", t)
    plan = json.load(open(os.path.join(t, "plan.json")))
    check([i["id"] for i in plan["items"]] == ["1", "2"], "[W2] the task's plan.json carries ids")
    plan["items"][1]["check_cmd"] = ["true"]
    plan["items"].append({"title": "C", "goal": "g", "covers": ["R1"], "files": ["other.py"], "check_cmd": ["true"]})
    with open(os.path.join(t, "plan.json"), "w") as f:
        json.dump(plan, f)
    out, _ = run("plan", "--task", t)
    check(out["kept"] == ["1", "2"] and out["added"] == ["3"], "[W2] plan keeps started items and adds new ones")
    path = plan_file([{"id": "a", "title": "D", "goal": "g", "covers": ["R1"], "files": ["README.md"],
                       "check_cmd": ["true"]},
                      {"id": "b", "title": "E", "goal": "g", "covers": ["R1"], "files": ["README.md"],
                       "check_cmd": ["true"], "depends": ["a"]}])
    out, _ = run("plan", path, "--task", t)
    check(out["added"] == ["4", "5"] and it(t, "5")["depends"] == ["4"] and it(t, "3")["status"] == "pending",
          "[W2] a partial plan adds items, maps its own ids in depends and keeps the items it leaves out")
    out, _ = run("plan", plan_file([{"id": "3", "status": "dropped"}]), "--task", t)
    check(out["dropped"] == ["3"], "[W2] an item is dropped by status dropped")


def test_decide_and_status():
    root = repo()
    t, _ = start(root, [item("A", ["mod.py"])])
    refused("bad_input", 2, "decide", "--question", "Which?", "--chosen", "x", "--reject", "y", "--task", t)
    out, _ = run("decide", "--question", "Which?", "--chosen", "x", "--reject", "y::slower", "--because", "bench",
                 "--task", t)
    run("decide", "--question", "Which?", "--chosen", "z", "--because", "new bench", "--supersedes", out["id"],
        "--task", t)
    st, _ = run("status", "--task", t)
    check(st["decisions"][0]["superseded_by"] == "D2" and "next" in st["next"] and st["active_runs"],
          "[W8] decisions are kept with rejected options; status names the next command")


def test_stop_finish_mark_log():
    root = repo()
    t, _ = start(root, [item("A", ["mod.py"])])
    refused("not_finished", 1, "finish", "--task", t)
    run("stop", "--condition", "user", "--detail", "pause", "--task", t)
    refused("task_stopped", 1, "finish", "--task", t)
    run("resume", "--task", t)
    append(os.path.join(root, "mod.py"), "#\n")
    run("done", "1", "--task", t)
    append(os.path.join(root, "other.py"), "#\n")
    err = refused("uncommitted_changes", 1, "next", "--task", t)
    check("other.py" in err, "[W14] finish refuses changes made during the task that are not committed")
    sh(root, "git", "checkout", "other.py")
    run("finish", "--task", t)
    refused("bad_input", 2, "mark", "--mark", "reworked", "--task", t)
    run("mark", "--mark", "accepted", "--task", t)
    check(state(t)["mark"]["mark"] == "accepted", "[W11] the mark is recorded")
    run("log", "wrong_engagement", "--task", t)
    check(state(t)["status"] == "handed_back", "[W1] a wrong engagement hands the task back")


# ---------------------------------------------------------------- faults

def test_faults():
    root = repo()
    t, _ = start(root, [item("A", ["mod.py"])])
    with open(os.path.join(t, "record.jsonl"), "a") as f:
        f.write('{"torn')
    run("status", "--task", t)
    run("decide", "--question", "q", "--chosen", "c", "--because", "b", "--task", t)
    check(all(isinstance(e, dict) for e in events(t)), "[W12] a torn record line is cut on the next write")
    lock = os.path.join(t, ".lock")
    with open(lock, "w") as f:
        f.write("999999999")
    run("decide", "--question", "q2", "--chosen", "c", "--because", "b", "--task", t)
    check(not os.path.exists(lock), "[W12] a lock left by a dead process is taken over")
    with open(lock, "w") as f:
        f.write(str(os.getpid()))
    with mock.patch.object(dc, "LOCK_WAIT_S", 0.2):
        refused("task_locked", 3, "decide", "--question", "q3", "--chosen", "c", "--because", "b", "--task", t)
    os.remove(lock)
    with open(os.path.join(t, "state.json"), "w") as f:
        f.write("{")
    refused("state_unreadable", 3, "status", "--task", t)
    check(open(os.path.join(t, "state.json")).read() == "{", "[W12] unreadable state is never overwritten")


def test_no_git_workspace():
    root = os.path.join(TMP, "plain")
    os.makedirs(root)
    append(os.path.join(root, "a.txt"), "a\n")
    t, out = start(root, [item("A", ["a.txt"], check_cmd=["true"]), item("B", ["b.txt"], check_cmd=["true"])],
                   check_cmd=())
    check(out["action"] == "do_yourself" and out["items"] == ["1"], "[W13] without git the writers take turns")
    run("done", "1", "--task", t)
    out, _ = run("next", "--task", t)
    check(out["items"] == ["2"], "[W13] the next writer goes after")


def test_docs_name_real_commands():
    skill = open(os.path.join(HERE, "..", "..", "skills", "atomic-decompose", "SKILL.md")).read()
    names = set(dc.COMMANDS) | {"start"}
    used = set(re.findall(r"`ad (\w+)", skill))
    check(used and used <= names, f"[W13] SKILL.md names only real commands: {sorted(used - names)}")
    check(len(skill) <= 8000, f"[W13] SKILL.md is at most 8,000 characters ({len(skill)})")
    check(len(open(dc.SCRIPT).read().split("\n")) <= 1600, "[W13] decompose.py is at most 1,600 lines")


sys.path.insert(0, HERE)
import report  # noqa: E402


def report_run(*args, code=0):
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = report.main([str(a) for a in args])
    check(rc == code, f"[API-12] report {' '.join(map(str, args))} exited {rc}, expected {code}\n{err.getvalue()}")
    return out.getvalue(), err.getvalue()


def write_json(path, obj, lines=False):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        f.write("\n".join(json.dumps(o) for o in obj) + "\n" if lines else json.dumps(obj))


def query_split(held, stem="engage query"):
    return next(q for q in (f"{stem} {n}" for n in range(100))
                if (int(hashlib.sha256(q.encode()).hexdigest(), 16) % 10 >= 6) is held)


def test_report_release():
    base = os.path.join(TMP, "release", "evals")
    runs = os.path.join(base, "runs")
    case = {"prompt": "p", "expected_output": "o", "files": [], "discoverable_facts": [], "fallback_reply": "r",
            "follow_ups": [], "weak_result": None}
    cases = [dict(case, id=1, expectations=["a", "b"], covers=["choice"],
                  planted_questions=[{"fact": "f1", "type": "scope"}, {"fact": "f2", "type": "user_only"}],
                  scripted_answers=[{"fact": "f1", "answer": "x"}, {"fact": "f2", "answer": "y"}]),
             dict(case, id=2, expectations=["c", "d"], covers=["long_run"], weak_result="files/old.md",
                  planted_questions=[{"fact": "f3", "type": "scope"}], scripted_answers=[{"fact": "f3", "answer": "z"}])]
    q_true, q_tune = query_split(True), query_split(False)
    q_false = query_split(True, "quick ask")
    write_json(os.path.join(base, "evals.json"), {"skill_name": "atomic-decompose", "evals": cases})
    write_json(os.path.join(base, "trigger_evals.json"),
               [{"query": q, "should_trigger": s, "reply": "r", "note": "n"}
                for q, s in ((q_true, True), (q_false, False), (q_tune, True))])
    long_dir = os.path.join(runs, "cursor", "long-task")
    write_json(os.path.join(long_dir, "record.jsonl"),
               [{"seq": 1, "ts": "2026-11-04T10:00:00.000Z", "event": "asked_again", "ref": "Q1", "data": {}}], True)
    write_json(os.path.join(runs, "cursor", "load_tokens.json"), {"tokenizer": "t", "files": [], "tokens": 4100})

    def line(c, arm, met=(True, True), attempt=1, interrupted="none", **kw):
        r = {"harness": "cursor", "model": "m", "case": c, "arm": arm, "attempt": attempt,
             "interrupted": interrupted, "triggered": None, "planted_asked": [], "discoverable_asked": 0,
             "task_dir": None, "sessions": [], "subagent_attribution_verified": True,
             "started_at": "2026-11-04T10:00:00Z", "ended_at": "2026-11-04T11:00:00Z",
             "expectations": [{"text": f"e{i}", "met": m} for i, m in enumerate(met)]}
        r.update(kw)
        return r

    asked1 = [{"fact": "f1", "in_round": True}, {"fact": "f2", "in_round": True}]
    asked2 = [{"fact": "f3", "in_round": True}]
    lines = [
        line("task:1", "with", planted_asked=asked1),
        line("task:2", "with", attempt=1, interrupted="permission_prompt", planted_asked=asked2),
        line("task:2", "with", attempt=2, planted_asked=asked2, task_dir="long-task"),
        line("task:1", "without", met=(True, False)),
        line("task:2", "without", met=(False, False)),
        line("task:1", "main_session", attempt=1, interrupted="denial"),
        line("task:1", "main_session", attempt=2, interrupted="safety_stop"),
        line("task:2", "main_session"),
        line("task:1", "delegate_baseline", met=(False, True)),
        line(f"engage:{q_true}", "with", met=(), interrupted="safety_stop", triggered=True),
        line(f"engage:{q_false}", "with", met=(), triggered=False),
        line(f"engage:{q_tune}", "with", met=(), triggered=False),
    ]
    write_json(os.path.join(runs, "cursor", "runs.jsonl"), lines, True)
    report_run("release", "--runs", runs)
    rep = json.load(open(os.path.join(runs, "report.json")))
    md = open(os.path.join(runs, "report.md")).read()
    t = {x["id"]: x for x in rep["targets"]}
    check(t["NFR-1"]["value"] == 1.0 and t["NFR-1"]["met"],
          "[NFR-1] [US-12.7] [DD-9] pooled with-arm expectations use attempt 2 and leave out delegate_baseline")
    check(t["NFR-2"]["value"] == 0.75 and t["NFR-2"]["met"], "[NFR-2] with minus without on the same cases and model")
    check(t["NFR-3"]["value"] == "not_computable" and not t["NFR-3"]["met"] and rep["pr6"]["escalate"],
          "[NFR-3] [PR-6] Cursor tokens not computed: NFR-3 not_computable and escalated")
    check(t["NFR-11"]["value"] == 0.5 and not t["NFR-11"]["met"],
          "[NFR-11] [US-12.10] a twice-interrupted main-session run scores every expectation unmet")
    check(t["NFR-4"]["value"] == 0.0 and t["NFR-9"]["value"] == 1.0,
          "[NFR-4] [NFR-9] [US-12.10] held-out split per kind; an interrupted engagement run counts as wrong")
    check(t["NFR-5"]["value"] == 1 and not t["NFR-5"]["met"], "[NFR-5] a re-ask in the long-run task record misses")
    check(t["NFR-6"]["value"] == 1.0 and t["NFR-6"]["met"] and t["NFR-10"]["met"] and t["NFR-8"]["value"] == 4100,
          "[NFR-6] [NFR-8] [NFR-10] planted, load and discoverable targets")
    check(rep["gate"] == "fail" and "Release gate failed" in md and "NFR-11 (cursor)" in md,
          "[US-12.4] the report states the gate failed and names the failed targets")
    check(rep["exit_criterion_2"] == "not_met" and rep["exit_criterion_2_missing"] == [],
          "[US-12.14] no without-method pass: exit criterion 2 is not met")
    check(all(x["total"] is None and x["estimate"] is False for x in rep["tokens"]) and len(rep["tokens"]) == 7,
          "[US-12.3] one token entry per task-case run, null until the Cursor export is pinned")
    check(rep["delegate_baseline"] == {"total": None, "expectations_met": 1, "with_total": None,
                                       "with_expectations_met": 2}, "[DD-9] delegate_baseline beside case 1's with run")
    c10 = {(r["arm"], r["case"]) for r in rep["criterion_10_runs"]}
    check(c10 == {("main_session", "task:1"), ("with", f"engage:{q_true}")} and "affects NFR-11" in md,
          "[US-12.12] criterion 10 runs listed with the comparisons they affect")
    check("task:2: attempt 1 permission_prompt" in md, "[US-12.7] an interrupted first attempt is a setup fault")
    check("FAIL: e1" in md and "pass: e0" in md, "[US-12.3] pass or fail per expectation")
    trig = [json.loads(x) for x in open(os.path.join(runs, "cursor", "trigger_runs.jsonl"))]
    check({"query": q_true, "should_trigger": True, "triggered": False} in trig,
          "[US-12.10] trigger_runs.jsonl flips an interrupted engagement run")

    lines[3] = line("task:1", "without")
    lines[0] = line("task:1", "with", planted_asked=asked1, subagent_attribution_verified=False)
    write_json(os.path.join(runs, "cursor", "runs.jsonl"), lines, True)
    report_run("release", "--runs", runs)
    rep = json.load(open(os.path.join(runs, "report.json")))
    check(rep["exit_criterion_2"] == "not_computable" and rep["exit_criterion_2_missing"] ==
          [{"harness": "cursor", "lacks": "tokens"}, {"harness": "cursor", "lacks": "attribution"}]
          and "could not be checked" in open(os.path.join(runs, "report.md")).read(),
          "[US-12.6] exit criterion 2 not computable names each harness and what it lacks")
    lines[0] = line("task:1", "with", met=(False, True))
    lines[2] = line("task:2", "with", attempt=2, met=(True, False))
    write_json(os.path.join(runs, "cursor", "runs.jsonl"), lines, True)
    report_run("release", "--runs", runs)
    check(json.load(open(os.path.join(runs, "report.json")))["exit_criterion_2"] == "met",
          "[US-12.13] [US-12.15] no with-method pass while a without-method run passes: exit criterion 2 met")
    lines[3] = line("task:1", "without", met=(False, False))
    write_json(os.path.join(runs, "cursor", "runs.jsonl"), lines, True)
    report_run("release", "--runs", runs)
    nfr3 = next(x for x in json.load(open(os.path.join(runs, "report.json")))["targets"] if x["id"] == "NFR-3")
    check(nfr3["met"] and nfr3["value"] is None, "[NFR-3] met by definition when the without arm meets nothing")

    with open(os.path.join(runs, "cursor", "runs.jsonl"), "w") as f:
        f.write(json.dumps(lines[0]) + "\nnot json\n")
    _, err = report_run("release", "--runs", runs, code=2)
    check("bad_run_line" in err and "runs.jsonl:2" in err, "[API-12] a DM-8 line that does not parse")
    cases[1]["scripted_answers"] = [{"fact": "other", "answer": "z"}]
    write_json(os.path.join(base, "evals.json"), {"skill_name": "atomic-decompose", "evals": cases})
    _, err = report_run("release", "--runs", runs, code=2)
    check("case_mismatch" in err and "case 2" in err, "[API-13] scripted_answers and planted_questions differ")


def test_report_weekly():
    root = os.path.join(TMP, "weekly")
    marks = os.path.join(root, "marks")
    os.makedirs(marks)
    week_ts = "2026-11-04T10:00:00.000Z"

    def task(harness, name, events, status="complete", questions=(), ts=week_ts):
        d = os.path.join(root, harness, name)
        write_json(os.path.join(d, "state.json"), {"schema_version": 1, "status": status,
                                                   "questions": list(questions)})
        write_json(os.path.join(d, "record.jsonl"), [{"seq": i, "ts": ts, "event": e, "ref": r, "data": dt}
                                                    for i, (e, r, dt) in enumerate(events, 1)], True)
        return d

    done = [("engaged", None, {}), ("item_done", "I1", {}), ("stopped", None, {"condition": "complete"})]
    t1 = task("cursor", "t1", [("engaged", None, {}), ("question_asked", "Q1", {}),
                               ("answered", "Q1", {"source": "user"}), ("question_asked", "Q1", {}), *done[1:]],
              questions=[{"id": "Q1", "round": 1, "answer_source": "user"}])
    t2 = task("cursor", "t2", [("engaged", None, {}), ("question_asked", "Q1", {}),
                               ("answered", "Q1", {"source": "default_accepted"}), ("item_failed", "I1", {}),
                               ("stopped", None, {"condition": "fault"}), ("marked", None, {"mark": "reworked"})],
              status="stopped", questions=[{"id": "Q1", "round": 1, "answer_source": "default_accepted"}])
    task("codex", "t3", [("engaged", None, {}), ("wrong_engagement", None, {}),
                         ("stopped", None, {"condition": "complete"})], status="handed_back")
    f0 = task("cursor", "f00", [("question_asked", "Q1", {}), *done],
              questions=[{"id": "Q1", "round": 1, "answer_source": None}])
    fillers = [task("codex" if n % 2 else "cursor", f"f{n:02}", done) for n in range(2, 15)]
    task("codex", "f01", [*done[:2], ("stopped", None, {"condition": "user_stop"})], status="stopped")
    task("cursor", "old", done, ts="2026-10-01T10:00:00.000Z")
    torn = task("cursor", "gap-torn", done)
    with open(os.path.join(torn, "record.jsonl"), "a") as f:
        f.write('{"seq": 4, "ts"')
    bad = task("codex", "gap-state", done)
    with open(os.path.join(bad, "state.json"), "w") as f:
        f.write("{")
    marks_file = os.path.join(marks, "2026-W45-marks.json")
    write_json(marks_file, {"schema_version": 1, "week": "2026-W45", "preconditions_held_from": [],
                            "sponsor_shorter_period": [],
                            "sessions": [{"harness": "cursor", "task_dir": t2, "contradictions": 2},
                                         {"harness": "cursor", "task_dir": t1, "contradictions": None}],
                            "questions": [{"task_dir": t1, "ref": "Q1", "discoverable": True},
                                          {"task_dir": t2, "ref": "Q1", "discoverable": False},
                                          {"task_dir": f0, "ref": "Q1", "discoverable": None}]})
    args = ("weekly", "--roots", f"cursor={os.path.join(root, 'cursor')}", f"codex={os.path.join(root, 'codex')}",
            "--week", "2026-W45", "--marks", marks)
    out, _ = report_run(*args)
    res = json.loads(out)
    m = {(x["id"], x["harness"]): x for x in res["metrics"]}
    check(sorted(res["gaps"]) == sorted([torn, bad]) and m[("M-3", None)]["status"] == "measured",
          "[API-12] [M-3] two gaps in 20 tasks are named and leave the week measured")
    check(m[("M-1", None)]["value"] == 3, "[M-1] one re-ask from the record plus 2 review contradictions; null left out")
    check(m[("M-2", None)]["value"] == 0.5, "[M-2] the DM-10 classification of asked questions, null left out")
    check(m[("M-3", None)]["value"] == report.rate(1, 16),
          "[M-3] tasks ending in the week, wrong engagements and user stops left out")
    check(m[("M-4", None)]["value"] == report.rate(1, 17) and m[("M-5", None)]["value"] == report.rate(1, 18),
          "[M-4] [M-5] pooled over both roots")
    check(m[("M-7", None)]["status"] == "incomplete", "[M-7] fewer than 5 marked results is incomplete")
    check(m[("M-8", None)]["value"] == 0.5, "[M-8] rounds with every default accepted, unanswered rounds left out")
    check(m[("M-6", "codex")]["status"] == "unmeasured" and m[("M-9", "codex")]["status"] == "unmeasured"
          and ("M-6", "cursor") not in m, "[M-6] [M-9] one entry per non-Cursor harness, none for Cursor")
    check(json.load(open(os.path.join(marks, "2026-W45.json"))) == res, "[API-12] weekly writes <marks>/<week>.json")

    with open(os.path.join(fillers[-1], "record.jsonl"), "a") as f:
        f.write("{")
    res = json.loads(report_run(*args)[0])
    check(len(res["gaps"]) == 3 and all(x["status"] != "measured" for x in res["metrics"]),
          "[API-12] three gaps in 20 tasks make the week incomplete")
    os.rename(marks_file, marks_file + ".bak")
    res = json.loads(report_run(*args)[0])
    m = {(x["id"], x["harness"]): x for x in res["metrics"]}
    check(m[("M-1", None)]["status"] == m[("M-2", None)]["status"] == "unmeasured",
          "[API-12] no DM-10 file for the week: M-1 and M-2 unmeasured")
    write_json(marks_file, {"schema_version": 2, "week": "2026-W45", "sessions": [], "questions": []})
    _, err = report_run(*args, code=2)
    check("marks_unreadable" in err and "schema_version" in err and "W45-marks.json" in err,
          "[API-12] a DM-10 file with another schema_version names the file and field")
    with open(marks_file, "w") as f:
        f.write("{")
    check("marks_unreadable" in report_run(*args, code=2)[1], "[API-12] a DM-10 file that is not JSON")


def main():
    for name, fn in list(globals().items()):
        if name.startswith("test_") and callable(fn):
            fn()
    print("selftest: all assertions hold")
    return 0


if __name__ == "__main__":
    sys.exit(main())
