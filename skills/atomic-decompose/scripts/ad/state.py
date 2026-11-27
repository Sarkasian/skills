"""Saved state: the task folder, its lock and record, and the max_parallel settings."""
from __future__ import annotations

import json
import os
import secrets
import time

from ad.common import ENV_MAX_PARALLEL, Fail, MAX_PARALLEL, MAX_PARALLEL_LIMIT, _now, PROJECT_CONFIG, SCHEMA, VERSION

LOCK_WAIT_S = 60  # how long a command waits for another command's lock before it gives up


def usable_max_parallel(v):
    return isinstance(v, int) and not isinstance(v, bool) and 1 <= v <= MAX_PARALLEL_LIMIT


def user_config_path():
    base = os.environ.get("APPDATA" if os.name == "nt" else "XDG_CONFIG_HOME")
    return os.path.join(base or os.path.expanduser("~" if os.name == "nt" else "~/.config"),
                        "atomic-decompose", "config.json")


def read_config_file(path):
    """(the file's max_parallel, problem). The value is None when there is no file, or the file sets none."""
    if not os.path.isfile(path):
        return None, None
    try:
        with open(path, encoding="utf-8") as f:
            data = json.load(f)
    except OSError as e:
        return None, f"{path} cannot be read: {e.strerror}"
    except ValueError:  # bad JSON and bad UTF-8 are both ValueErrors
        return None, f"{path} is not JSON"
    if not isinstance(data, dict):
        return None, f"{path} is not a JSON object"
    value = data.get("max_parallel")
    if value is not None and not usable_max_parallel(value):
        return None, f"{path} has no usable 'max_parallel' (want 1 to {MAX_PARALLEL_LIMIT})"
    return value, None


def resolve_max_parallel(flag, plan, root, top):
    """(value, layer, problems) from the first layer that is set: flag, plan, env, user config file, project
    config file, default. A layer that is set but cannot be used is a problem. When it is the first one set,
    the value is None: start refuses and doctor says why. Problems below the layer that wins are only listed."""
    env = (os.environ.get(ENV_MAX_PARALLEL) or "").strip() or None  # set but empty counts as not set
    if env:
        with _quiet(ValueError):  # text that is not a whole number stays text: an unusable value
            env = int(env)
    layers = [(ly, v, None if v is None or usable_max_parallel(v) else
               f"{ly} sets max_parallel {v!r}, not an integer from 1 to {MAX_PARALLEL_LIMIT}")
              for ly, v in (("flag", flag), ("plan", plan.get("max_parallel")), ("env", env))]
    for ly, path in (("user_config", user_config_path()),
                     ("project_config", os.path.join(top or root, PROJECT_CONFIG))):
        v, problem = read_config_file(path)
        layers.append((ly, v, problem and f"{ly}: {problem}"))
    layers.append(("default", MAX_PARALLEL, None))
    layer, value, problem = next(x for x in layers if x[1] is not None or x[2])
    return (None if problem else value), layer, [p for _, _, p in layers if p]


class Task:
    def __init__(self, task_dir):
        self.dir = os.path.abspath(task_dir)
        self.state_path = os.path.join(self.dir, "state.json")
        self.record_path = os.path.join(self.dir, "record.jsonl")
        self.lock_path = os.path.join(self.dir, ".lock")
        self.plan_path = os.path.join(self.dir, "plan.json")

    def load(self):
        try:
            with open(self.state_path, encoding="utf-8") as f:
                st = json.load(f)
        except (OSError, ValueError) as e:
            raise Fail("state_unreadable", f"cannot read {self.state_path}: {e}", 3, "needs_user",
                       "restore state.json from a backup, or start a new task; do not overwrite it")
        if st.get("schema_version") != SCHEMA:
            raise Fail("state_unreadable", f"{self.state_path} has schema_version {st.get('schema_version')!r}; "
                       f"this script ({VERSION}) reads {SCHEMA}", 3, "needs_user",
                       "finish the task with the script version that started it")
        return st

    def save(self, st):
        st["updated_at"] = _now()
        tmp = os.path.join(self.dir, f".state.{secrets.token_hex(4)}.tmp")
        try:
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(st, f, ensure_ascii=False, indent=1)
            os.replace(tmp, self.state_path)
        except OSError as e:
            with _quiet():
                # lint: no-dry-run: removes only the temporary copy of state.json this call wrote
                os.remove(tmp)
            raise Fail("state_write_failed", f"cannot write {self.state_path}: {e}; the saved state is unchanged",
                       3, "auto_retry", "fix the cause (disk, permissions), then rerun the same command")

    def event(self, event, ref=None, data=None):
        """Append one run-record line, cutting a torn last line (a crash mid-write) first."""
        line = json.dumps({"ts": _now(), "event": event, "ref": ref, "data": data or {}}, ensure_ascii=False)
        try:
            if os.path.exists(self.record_path):
                with open(self.record_path, "rb+") as f:
                    raw = f.read()
                    if raw and not raw.endswith(b"\n"):
                        f.seek(raw.rfind(b"\n") + 1)
                        f.truncate()
            with open(self.record_path, "a", encoding="utf-8") as f:
                f.write(line + "\n")
        except OSError as e:
            raise Fail("record_write_failed", f"cannot append to {self.record_path}: {e}; state.json holds the "
                       "change", 3, "auto_retry", "fix the cause; the run record misses this one line")

    def record(self):
        if not os.path.exists(self.record_path):
            return []
        out = []
        with open(self.record_path, encoding="utf-8") as f:
            for line in f:
                with _quiet(ValueError):
                    out.append(json.loads(line))
        return out

    def lock(self):
        """Wait for the lock; take it over when the process that holds it is gone."""
        end = time.monotonic() + LOCK_WAIT_S
        while True:
            try:
                fd = os.open(self.lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
                os.write(fd, str(os.getpid()).encode())
                os.close(fd)
                return
            except FileExistsError:
                if not _holder_alive(self.lock_path) and self._remove_dead_lock():
                    continue
                if time.monotonic() > end:
                    raise Fail("task_locked", f"{self.lock_path} is held by a live process for over {LOCK_WAIT_S}s",
                               3, "needs_user", "wait for the other command to end, then rerun this one"
                               + ("; on Windows a lock is never taken over, so if no command is running, "
                                  "delete that file" if os.name == "nt" else ""))
                time.sleep(0.1)

    def _remove_dead_lock(self):
        """Remove a lock whose process is gone. One command at a time does this, behind the takeover file, so
        that two waiters cannot both see the dead lock and the second remove the lock the first then took.
        Returns False when another command is doing it."""
        take = self.lock_path + ".takeover"
        try:
            os.close(os.open(take, os.O_CREAT | os.O_EXCL | os.O_WRONLY))
        except FileExistsError:
            with _quiet():
                if time.time() - os.path.getmtime(take) > 5:  # its command died: a takeover lasts milliseconds
                    # lint: no-dry-run: removes only this task's own takeover marker, left by a dead command
                    os.remove(take)
            return False
        try:
            if not _holder_alive(self.lock_path):  # looked at again, now that no other command can remove it
                with _quiet():
                    # lint: no-dry-run: removes only this task's own lock file, whose process is gone
                    os.remove(self.lock_path)
        finally:
            with _quiet():
                # lint: no-dry-run: removes only the takeover marker this call created
                os.remove(take)
        return True

    def unlock(self):
        with _quiet(OSError, ValueError):
            with open(self.lock_path, encoding="utf-8") as f:
                mine = int(f.read().strip()) == os.getpid()
            if mine:
                # lint: no-dry-run: removes only this task's own lock file, which this process holds
                os.remove(self.lock_path)


class _quiet:
    def __init__(self, *errors):
        self.errors = errors or (OSError,)

    def __enter__(self):
        return self

    def __exit__(self, kind, value, tb):
        return kind is not None and issubclass(kind, self.errors)


def _holder_alive(path):
    try:
        with open(path, encoding="utf-8") as f:
            text = f.read().strip()
        pid = int(text) if text else None
    except (OSError, ValueError):
        return True
    if pid is None:  # created, pid not written yet; empty for seconds means its writer died
        with _quiet():
            return time.time() - os.path.getmtime(path) < 5
        return False
    if pid <= 0:
        return False
    if os.name == "nt":  # there os.kill(pid, 0) ends the process, so a lock is never taken over on Windows
        return True
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except OSError:
        return True
    return True


def locked(task, fn):
    task.lock()
    try:
        st = task.load()
        return fn(st)
    finally:
        task.unlock()
