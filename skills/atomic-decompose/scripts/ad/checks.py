"""Running an item's or the task's check commands."""
from __future__ import annotations

import os
import re
import signal
import subprocess

from ad.common import TAIL_LINES


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
