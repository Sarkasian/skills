#!/usr/bin/env python3
"""Run a skill's trigger evals and task evals in a headless agent CLI. Standard library only.

Built and checked against the Cursor CLI (`cursor-agent`). Each run gets a fresh temporary workspace outside
this repository. The agent also sees whatever skills and plugins are installed for the user on this machine,
so results depend on the machine as well as the skill.

  trigger  Runs every query in trigger_evals.json N times in read-only mode. A run counts as triggered when the
           agent starts a tool call that names `<name>/SKILL.md`; the run is stopped at that point, or after
           --max-tool-calls tool calls without one (default 8), or at the agent's answer. For the length of
           the command the skill is installed for the user, at ~/.agents/skills/<name>/, and removed at the
           end; the command refuses to start if that folder already exists. The workspace holds a two-file
           stand-in project and no skill. (A skill inside the workspace is read as part of "this repo" by any
           question about the repo, which is not a trigger.) Appends one line per run to --out:
           {"query", "should_trigger", "triggered", "first_skill", "seconds", "model"}.
  task     Runs evals.json cases to completion, once with the skill (copied to `.agents/skills/<name>/` in the
           workspace) and once without, with writes allowed.
           Keeps each workspace and transcript under --out-dir and prints a summary. It does not grade:
           read each workspace against the case's expectations.
           The agent is not confined to the workspace: in the first runs a baseline agent read skills installed
           for the user and wrote a file under ~/.config. Run task evals on a machine or account where that
           is acceptable, and check the transcript for paths outside the workspace before trusting a baseline.

Usage:
  python3 dev/authoring-agent-skills/run_evals.py trigger --skill skills/<name> --out runs.jsonl [--runs 3]
  python3 dev/authoring-agent-skills/run_evals.py task --skill skills/<name> --out-dir DIR [--ids 1,3]
Common flags: --evals-dir DIR (default dev/<name>/evals), --parallel N (default 4), --timeout SECONDS,
  --model NAME, --agent-cmd "..." (default "cursor-agent"), --dry-run (print the planned runs, start nothing).
Runs that fail or time out are written to stderr and to <out>.errors.jsonl, never counted as "not triggered".
Exit codes: 0 all runs finished, 1 some runs failed, 2 bad input.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

# A headless run has nobody to answer questions, so every task prompt gets this suffix, with and without the skill.
NON_INTERACTIVE = ("\n\nThis is a non-interactive run: do not ask me questions. State the assumptions you make "
                   "and carry on to the end.")
SKILL_READ = re.compile(r"/([^/\"\\]+)/SKILL\.md")


def make_workspace(parent: Path, skill: Path | None, files: list[str], evals_dir: Path, stand_in: bool = False) -> Path:
    ws = Path(tempfile.mkdtemp(prefix="ws-", dir=parent))
    subprocess.run(["git", "init", "-q", str(ws)], check=True)
    if skill:
        shutil.copytree(skill, ws / ".agents" / "skills" / skill.name, ignore=shutil.ignore_patterns("__pycache__"))
    if stand_in:
        (ws / "src").mkdir()
        (ws / "src" / "orders.py").write_text('def total(items):\n    return sum(i["price"] * i["qty"] for i in items)\n', encoding="utf-8")
        (ws / "pyproject.toml").write_text('[project]\nname = "orders"\nversion = "0.1.0"\n', encoding="utf-8")
    for f in files:  # paths in evals.json are relative to the folder that holds evals/
        src = evals_dir.parent / f
        if "fixture-skills" in src.parts:  # stored as SKILL.fixture.md so installers do not offer it
            dst = ws / ".agents" / "skills" / src.name
            shutil.copytree(src, dst)
            (dst / "SKILL.fixture.md").rename(dst / "SKILL.md")
        elif src.is_dir():
            shutil.copytree(src, ws, dirs_exist_ok=True)
        else:
            shutil.copy(src, ws)
    return ws


def run_agent(cmd: list[str], prompt: str, ws: Path, timeout: int, transcript: Path | None, stop_on: str | None,
              max_tool_calls: int = 0) -> dict:
    """Run one prompt. Returns {"triggered", "first_skill", "model", "result", "usage", "seconds"} or {"error"}."""
    start = time.monotonic()
    proc = subprocess.Popen([*cmd, prompt], cwd=ws, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                            start_new_session=True)

    def kill() -> None:
        try:
            os.killpg(proc.pid, signal.SIGKILL)
        except ProcessLookupError:
            pass

    timed_out = threading.Event()
    timer = threading.Timer(timeout, lambda: (timed_out.set(), kill()))
    timer.start()
    out: dict = {"triggered": False, "first_skill": None, "model": None, "result": None, "usage": None}
    tool_calls, capped = 0, False
    log = transcript.open("w", encoding="utf-8") if transcript else None
    try:
        for line in proc.stdout:
            if log:
                log.write(line)
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            if e.get("type") == "system":
                out["model"] = e.get("model")
            elif e.get("type") == "tool_call" and e.get("subtype") == "started":
                args = json.dumps(e.get("tool_call"))
                m = SKILL_READ.search(args)
                if m and not out["first_skill"]:
                    out["first_skill"] = m.group(1)
                if stop_on and f"/{stop_on}/SKILL.md" in args:
                    out["triggered"] = True
                    kill()
                    break
                tool_calls += 1
                if max_tool_calls and tool_calls >= max_tool_calls:
                    capped = True
                    kill()
                    break
            elif e.get("type") == "result":
                out["result"], out["usage"] = e.get("result"), e.get("usage")
                if e.get("is_error"):
                    return {"error": f"agent reported an error: {str(e.get('result'))[:300]}"}
        proc.wait()
    finally:
        timer.cancel()
        kill()
        if log:
            log.close()
    out["seconds"] = round(time.monotonic() - start, 1)
    if timed_out.is_set():
        return {"error": f"timed out after {timeout}s"}
    if not out["triggered"] and not capped and out["result"] is None:
        return {"error": f"agent ended without a result (exit {proc.returncode}): {proc.stderr.read()[-300:].strip()}"}
    return out


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("mode", choices=["trigger", "task"])
    ap.add_argument("--skill", required=True, type=Path)
    ap.add_argument("--evals-dir", type=Path)
    ap.add_argument("--out", type=Path, help="trigger: JSONL file to append runs to")
    ap.add_argument("--out-dir", type=Path, help="task: folder for workspaces and transcripts")
    ap.add_argument("--runs", type=int, default=3)
    ap.add_argument("--ids", help="task: comma-separated case ids (default all)")
    ap.add_argument("--parallel", type=int, default=4)
    ap.add_argument("--timeout", type=int)
    ap.add_argument("--max-tool-calls", type=int, default=8)
    ap.add_argument("--model")
    ap.add_argument("--agent-cmd", default="cursor-agent")
    ap.add_argument("--dry-run", action="store_true")
    a = ap.parse_args()

    skill = a.skill.resolve()
    evals_dir = (a.evals_dir or Path(__file__).resolve().parent.parent / skill.name / "evals").resolve()
    if not (skill / "SKILL.md").is_file() or not evals_dir.is_dir():
        print(f"need {skill}/SKILL.md and {evals_dir}/", file=sys.stderr)
        return 2
    if (a.mode == "trigger" and not a.out) or (a.mode == "task" and not a.out_dir):
        print("trigger needs --out, task needs --out-dir", file=sys.stderr)
        return 2
    base = [*shlex.split(a.agent_cmd), "-p", "--trust", "--output-format", "stream-json"]
    if a.model:
        base += ["--model", a.model]

    if a.mode == "trigger":
        queries = json.loads((evals_dir / "trigger_evals.json").read_text(encoding="utf-8"))
        jobs = [(q, n) for q in queries for n in range(a.runs)]
        if a.dry_run:
            print(json.dumps({"would_run": len(jobs), "command": [*base, "--mode", "ask", "<query>"]}))
            return 0
        installed = Path.home() / ".agents" / "skills" / skill.name
        if installed.exists():
            print(f"{installed} exists; remove it first (this command installs the copy under test there for the run)", file=sys.stderr)
            return 2
        tmp = Path(tempfile.mkdtemp(prefix="trigger-evals-"))
        lock = threading.Lock()
        errors = []

        def one(job: tuple[dict, int]) -> None:
            q, _ = job
            ws = make_workspace(tmp, None, [], evals_dir, stand_in=True)
            r = run_agent([*base, "--mode", "ask"], q["query"], ws, a.timeout or 180, None, skill.name, a.max_tool_calls)
            shutil.rmtree(ws, ignore_errors=True)
            row = {"query": q["query"], "should_trigger": q["should_trigger"], **r}
            row.pop("result", None), row.pop("usage", None)
            with lock:
                if "error" in r:
                    errors.append(row)
                    print(json.dumps(row), file=sys.stderr)
                with (a.out.with_name(a.out.name + ".errors.jsonl") if "error" in r else a.out).open("a", encoding="utf-8") as f:
                    f.write(json.dumps(row) + "\n")

        shutil.copytree(skill, installed, ignore=shutil.ignore_patterns("__pycache__"))
        try:
            with ThreadPoolExecutor(a.parallel) as pool:
                list(pool.map(one, jobs))
        finally:
            shutil.rmtree(installed, ignore_errors=True)
            shutil.rmtree(tmp, ignore_errors=True)
        print(json.dumps({"runs": len(jobs), "failed": len(errors), "out": str(a.out)}))
        return 1 if errors else 0

    cases = json.loads((evals_dir / "evals.json").read_text(encoding="utf-8"))["evals"]
    if a.ids:
        want = {int(i) for i in a.ids.split(",")}
        cases = [c for c in cases if c["id"] in want]
    jobs = [(c, arm) for c in cases for arm in ("with", "without")]
    if a.dry_run:
        print(json.dumps({"would_run": [f"{c['id']}-{arm}" for c, arm in jobs], "command": [*base, "--force", "--sandbox", "enabled", "<prompt>"]}))
        return 0
    a.out_dir.mkdir(parents=True, exist_ok=True)
    out_dir = a.out_dir.resolve()

    def one_task(job: tuple[dict, str]) -> dict:
        c, arm = job
        run_dir = out_dir / f"{c['id']}-{arm}"
        run_dir.mkdir(exist_ok=True)
        ws = make_workspace(run_dir, skill if arm == "with" else None, c.get("files", []), evals_dir)
        r = run_agent([*base, "--force", "--sandbox", "enabled"], c["prompt"] + NON_INTERACTIVE, ws, a.timeout or 1200,
                      run_dir / "transcript.jsonl", None)
        (run_dir / "result.md").write_text(r.get("result") or r.get("error", ""), encoding="utf-8")
        r.pop("result", None), r.pop("triggered", None)
        return {"id": c["id"], "arm": arm, "workspace": str(ws), **r}

    with ThreadPoolExecutor(a.parallel) as pool:
        rows = list(pool.map(one_task, jobs))
    (out_dir / "summary.json").write_text(json.dumps(rows, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(rows, indent=2))
    return 1 if any("error" in r for r in rows) else 0


if __name__ == "__main__":
    sys.exit(main())
