"""Git: commits, changed files, patches and restores."""
from __future__ import annotations

import hashlib
import os
import shutil
import subprocess
import tempfile

from ad.common import Fail, TASK_DIR
from ad.state import _quiet


def git(cwd, *args, check=True, env=None, text=True):
    """Run git in `cwd`. `text=False` gives the output as bytes, for a diff that must be kept byte for byte.
    A file name that is not UTF-8 comes back with its bytes kept (surrogateescape), so it is still that file."""
    how = {"text": True, "errors": "surrogateescape"} if text else {}
    try:
        p = subprocess.run(["git", "-C", cwd, *args], capture_output=True, env=env, **how)
    except FileNotFoundError:
        raise Fail("git_missing", "git is not installed", 3, "needs_user", "install git, or run without it")
    if check and p.returncode != 0:
        said = p.stderr or p.stdout
        said = said if text else said.decode("utf-8", "replace")
        raise Fail("git_failed", f"git {' '.join(args)} failed in {cwd}: {said.strip()[-800:]}",
                   3, "needs_user", "fix the git problem it names, then rerun the same command")
    return p


def lit(paths):
    """The paths as git pathspecs that are taken as written: a file named `a*.py` or `:x` is that file, not a
    pattern. Written on each path, not set as GIT_LITERAL_PATHSPECS, which the user's hooks would inherit."""
    return [":(literal)" + p for p in paths]


def has_commit(top):
    return git(top, "rev-parse", "--verify", "-q", "HEAD", check=False).returncode == 0


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


def ignored_files(root, paths):
    """Those of `paths` (relative to root) that git ignores. A tracked file is never ignored."""
    # `./` in front: check-ignore takes a name as written, except that a leading `:` would start pathspec magic
    return [p for p in paths if p.split("/")[0] != TASK_DIR
            and git(root, "check-ignore", "-q", "--", "./" + p, check=False).returncode == 0]


def dirty_files(top, root, outside=False):
    """{path relative to root: content hash, "?"-prefixed when untracked} for every changed or untracked file
    under root, the task folder aside. With `outside`, the files of the repository that are not under root
    instead; their paths, relative to root too, start with `../`."""
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
            if outside and rel is None:
                rel = os.path.relpath(os.path.join(top, path), root).replace("\\", "/")
            elif outside or rel is None or rel.split("/")[0] == TASK_DIR:
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
    indexed = set(git(run_dir, "ls-files", "-z", "--", *lit(paths), env=env).stdout.split("\0"))
    keep = [p for p in paths if os.path.lexists(os.path.join(run_dir, p)) or p in indexed]
    if keep:
        git(run_dir, "add", "-A", "--", *lit(keep), env=env)


def save_patch(run_dir, paths, out_path):
    """Write the diff of `paths` (new files included) to `out_path` without touching the real index."""
    idx = git(run_dir, "rev-parse", "--git-path", "index").stdout.strip()
    idx = idx if os.path.isabs(idx) else os.path.join(run_dir, idx)
    with tempfile.TemporaryDirectory() as tmp:
        env = dict(os.environ, GIT_INDEX_FILE=os.path.join(tmp, "index"))
        if os.path.exists(idx):
            shutil.copy(idx, env["GIT_INDEX_FILE"])
        add_paths(run_dir, paths, env)
        # bytes, not text: decoding would fail on a file that is not UTF-8 and would turn CRLF into LF
        diff = git(run_dir, "diff", "--cached", "--binary", "HEAD", "--", *lit(paths), env=env, text=False).stdout
    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "wb") as f:
        f.write(diff)


def restore_paths(run_dir, paths):
    """Put `paths` back as at HEAD: a tracked file is checked out, a file HEAD does not have is removed."""
    # -z: names come back unquoted, and relative to run_dir, as `paths` are
    tracked = set(git(run_dir, "ls-tree", "-r", "-z", "--name-only", "HEAD", "--", *lit(paths)).stdout.split("\0")) - {""}
    keep = [p for p in paths if p in tracked]
    if keep:
        # lint: no-dry-run: shelve saved these files' changes in a patch first, and skips this when that fails
        git(run_dir, "checkout", "HEAD", "--", *lit(keep))
    gone = [p for p in paths if p not in tracked]
    if gone:
        git(run_dir, "rm", "-q", "--cached", "--ignore-unmatch", "--", *lit(gone), check=False)
    for p in gone:
        with _quiet():
            # lint: no-dry-run: the caller, shelve, saved this file in a patch first and skips this when that fails
            os.remove(os.path.join(run_dir, p))
