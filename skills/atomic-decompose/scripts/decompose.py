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
max_parallel, the most runs that work at once, is the task's own value: the first setting that
applies at start is --max-parallel, the plan's max_parallel, AD_MAX_PARALLEL, ~/.config/atomic-decompose/
config.json (Windows %APPDATA%), .atomic-decompose.json in the git top, then 4. doctor reports which applies
and from where; tune changes the task value between rounds.
"""
from __future__ import annotations

import argparse
import json
import os
import sys

from ad.common import Fail, LOG_EVENTS, MAX_PARALLEL, MAX_PARALLEL_LIMIT, Parser, PROJECT_CONFIG, SOURCES
from ad.state import Task
from ad.commands import (cmd_annotate, cmd_answer, cmd_block, cmd_decide, cmd_doctor, cmd_done, cmd_finish, cmd_log,
                         cmd_mark, cmd_next, cmd_plan, cmd_resume, cmd_start, cmd_status, cmd_stop, cmd_tune,
                         stop_action)


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
    s.add_argument("--max-parallel", type=int, default=None,
                   help="most runs at once; the task value is the first setting that applies: this flag, "
                        "the plan file's max_parallel, AD_MAX_PARALLEL, the user config file, "
                        f"{PROJECT_CONFIG} in the git top, {MAX_PARALLEL}")
    s.add_argument("--review", choices=("auto", "always", "never"), default="auto",
                   help="auto: review the work that executors did, not the coordinator's own")
    s = cmd("plan", "Apply an edited plan file (default: the task's plan.json) to the items not started.")
    s.add_argument("file", nargs="?")
    s = cmd("answer", "Record an answer; --defaults accepts every open question's default.")
    s.add_argument("--id")
    s.add_argument("--text")
    s.add_argument("--source", choices=SOURCES, default="user")
    s.add_argument("--defaults", action="store_true")
    s = cmd("annotate", "Add a note to an open item, or list its notes; the item's next brief carries its notes.")
    s.add_argument("--item", required=True, help="the item id")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--note", help="the direction for the item's next executor; kept as one line")
    g.add_argument("--list", action="store_true", help="print the item's notes")
    s.add_argument("--source", choices=("user", "system"), default="user", help="who the note comes from")
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
    s = cmd("tune", "Change the task's max_parallel for the next round.")
    s.add_argument("--max-parallel", type=int, required=True,
                   help=f"an integer from 1 to {MAX_PARALLEL_LIMIT}")
    d = cmd("doctor", "Show which max_parallel applies to a folder and from which layer.", task=False)
    d.add_argument("--root", default=".", help="workspace to check (default: the current folder)")
    d.add_argument("--max-parallel", type=int, default=None,
                   help="what a start --max-parallel here would set")
    return p


COMMANDS = {"next": cmd_next, "plan": cmd_plan, "answer": cmd_answer, "done": cmd_done, "block": cmd_block,
            "decide": cmd_decide, "status": cmd_status, "resume": cmd_resume, "stop": cmd_stop,
            "finish": cmd_finish, "mark": cmd_mark, "log": cmd_log, "tune": cmd_tune, "annotate": cmd_annotate}
ANY_STATUS = {"status", "answer", "resume", "stop", "log", "mark", "finish", "next", "done", "block", "annotate"}


def run(argv):
    a = build_parser().parse_args(argv)
    if a.command == "start":
        return cmd_start(a)
    if a.command == "doctor":
        return cmd_doctor(a)
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
