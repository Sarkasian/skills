"""Constants, the Fail error and small helpers that every module uses."""
from __future__ import annotations

import argparse
import datetime as _dt
import os
import shlex

SCHEMA = 2
VERSION = "0.3.0"
TRIES = 3
MAX_PARALLEL = 4
MAX_PARALLEL_LIMIT = 64
ENV_MAX_PARALLEL = "AD_MAX_PARALLEL"
PROJECT_CONFIG = ".atomic-decompose.json"
CHECK_TIMEOUT_S = 600
AUTO_FIXES = 2
TAIL_LINES = 30
TASK_DIR = ".atomic-decompose"
SCRIPT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "decompose.py")  # the entry script
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
