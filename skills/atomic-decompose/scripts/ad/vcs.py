"""Git: commits, changed files, patches and restores."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile

from ad.common import Fail, TASK_DIR
from ad.state import _quiet


def git(cwd, *args, check=True, env=None):
    try:
        p = subprocess.run(["git", "-C", cwd, *args], capture_output=True, text=True, env=env)
    except FileNotFoundError:
        raise Fail("git_missing", "git is not installed", 3, "needs_user", "install git, or run without it")
    if check and p.returncode != 0:
        raise Fail("git_failed", f"git {' '.join(args)} failed in {cwd}: {(p.stderr or p.stdout).strip()[-800:]}",
                   3, "needs_user", "fix the git problem it names, then rerun the same command")
    return p


def git_top(path):
    with _quiet(Fail):
        p = git(path, "rev-parse", "--show-toplevel", check=False)
        if p.returncode == 0:
            return os.path.realpath(p.stdout.strip())
    return None


def head(cwd):
    return git(cwd, "rev-parse", "HEAD").stdout.strip()


def _sha_file(path):
    try:
        with open(path, "rb") as f:
            return hashlib.sha1(f.read()).hexdigest()
    except OSError:
        return "<missing>"


def dirty_files(top, root):
    """{path relative to root: content hash, "?"-prefixed when untracked} for every changed or untracked file
    under root, the task folder aside."""
    p = git(top, "status", "--porcelain", "-z", "--untracked-files=all")
    parts, out, i = p.stdout.split("\0"), {}, 0
    rel_root = os.path.relpath(root, top).replace("\\", "/")
    while i < len(parts):
        entry = parts[i]
        i += 1
        if len(entry) < 4:
            continue
        paths = [entry[3:]]
        if entry[0] in "RC":
            paths.append(parts[i])
            i += 1
        for path in paths:
            rel = path if rel_root == "." else (path[len(rel_root) + 1:] if path.startswith(rel_root + "/") else None)
            if rel is None or rel.split("/")[0] == TASK_DIR:
                continue
            out[rel] = ("?" if entry.startswith("??") else "") + _sha_file(os.path.join(root, rel))
    return out


def untracked(value):
    return value.startswith("?")


def covered(path, files):
    return any(path == f or (f.endswith("/") and path.startswith(f)) or path.startswith(f.rstrip("/") + "/")
               for f in files)


def changed_since(run_dir, top_of_run, snapshot):
    """{path: hash} of the files that changed since `snapshot`."""
    now = dirty_files(top_of_run, run_dir)
    return {p: h for p, h in sorted(now.items()) if snapshot.get(p) != h}


def add_paths(run_dir, paths, env=None):
    """`git add -A` the paths, skipping those already gone from disk and index (a `git rm` or `git mv` source)."""
    indexed = set(git(run_dir, "ls-files", "-z", "--", *paths, env=env).stdout.split("\0"))
    keep = [p for p in paths if os.path.lexists(os.path.join(run_dir, p)) or p in indexed]
    if keep:
        git(run_dir, "add", "-A", "--", *keep, env=env)


def save_patch(run_dir, paths, out_path):
    """Write the diff of `paths` (new files included) to `out_path` without touching the real index."""
    idx = git(run_dir, "rev-parse", "--git-path", "index").stdout.strip()
    idx = idx if os.path.isabs(idx) else os.path.join(run_dir, idx)
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(tmp, "index"))
        if os.path.exists(idx):
            shutil.copy(idx, env["GIT_INDEX_FILE"])
        add_paths(run_dir, paths, env)
        diff = git(run_dir, "diff", "--cached", "--binary", "HEAD", "--", *paths, env=env).stdout
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(diff)


# lint: no-dry-run: the caller, shelve, saves the files as a patch first and leaves them alone if that fails
def restore_paths(run_dir, paths):
    tracked = set(git(run_dir, "ls-tree", "-r", "--name-only", "HEAD", "--", *paths).stdout.split("\n")) - {""}
    prefix = git(run_dir, "rev-parse", "--show-prefix").stdout.strip()
    keep = [p for p in paths if prefix + p in tracked]
    if keep:
        git(run_dir, "checkout", "HEAD", "--", *keep)
    gone = [p for p in paths if prefix + p not in tracked]
    if gone:
        git(run_dir, "rm", "-q", "--cached", "--ignore-unmatch", "--", *gone, check=False)
    for p in gone:
        with _quiet():
            os.remove(os.path.join(run_dir, p))
