#!/usr/bin/env python3
"""Self-check for the authoring-agent-skills scripts. Usage: python3 dev/authoring-agent-skills/selftest.py  (exit 0 = all pass)."""
from __future__ import annotations

import hashlib
import importlib.util
import json
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path

SKILL = Path(__file__).resolve().parents[2] / "skills" / "authoring-agent-skills"
HERE = SKILL / "scripts"
DEV = Path(__file__).resolve().parent


def run(script: str, *args: str) -> tuple[int, dict]:
    p = subprocess.run([sys.executable, str(HERE / script), *args], capture_output=True, text=True, timeout=120)
    return p.returncode, json.loads(p.stdout) if p.stdout.strip() else {}


GOOD = "Formats release notes. Use when writing release notes. Not for changelogs."


def make(root: Path, name: str, desc: str = GOOD, body: str = "# T\n", files: dict[str, str] | None = None, head: str = "") -> Path:
    """A throwaway skill <root>/<name>/ with valid evals, so a lint result holds only what the case is about."""
    d = root / name
    (d / "evals").mkdir(parents=True)
    (d / "SKILL.md").write_text(f"---\nname: {name}\ndescription: {json.dumps(desc)}\n{head}---\n{body}", encoding="utf-8")
    (d / "evals" / "evals.json").write_text('{"evals": []}')
    (d / "evals" / "trigger_evals.json").write_text(json.dumps([{"query": f"q{i}", "should_trigger": i % 2 == 0} for i in range(16)]))
    for rel, text in (files or {}).items():
        (d / rel).parent.mkdir(parents=True, exist_ok=True)
        (d / rel).write_text(text, encoding="utf-8")
    return d


def lint(*args: str) -> tuple[int, str, str]:
    code, out = run("lint_skill.py", *args)
    return code, " | ".join(out.get("errors", [])), " | ".join(out.get("warnings", []))


sys.dont_write_bytecode = True  # the import below must not leave a __pycache__ folder in the skill
_spec = importlib.util.spec_from_file_location("lint_skill", HERE / "lint_skill.py")
LINT = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(LINT)


def quick(d: Path, portable: bool = False) -> tuple[str, str, dict]:
    """The lint called in this process (errors, warnings, stats): for the tables below, which hold a few hundred small cases."""
    out = LINT.lint(d, portable)
    return " | ".join(out["errors"]), " | ".join(out["warnings"]), out["stats"]


def kept(original: str, edited: str) -> bool:
    """Eval 6, expectation 1: the same number of lines, blank lines still blank, every other line unchanged or with text added at its end."""
    a, b = original.splitlines(), edited.splitlines()
    return len(a) == len(b) and all(y.startswith(x) if x.strip() else not y.strip() for x, y in zip(a, b))


with tempfile.TemporaryDirectory() as tmp:
    t = Path(tmp)

    code, out = run("lint_skill.py", str(SKILL), "--evals-dir", str(DEV / "evals"))
    assert code == 0 and not out["warnings"], f"this skill must lint clean: {out}"

    code, out = run("scaffold.py", "--name", "demo-skill", "--dest", tmp, "--description", "Does X. Use when Y. Not for Z.", "--plugin")
    sk = t / "demo-skill" / "skills" / "demo-skill"
    assert code == 0 and (sk / "SKILL.md").is_file() and (t / "demo-skill" / ".claude-plugin" / "plugin.json").is_file(), out
    assert run("scaffold.py", "--name", "demo-skill", "--dest", tmp, "--description", "x", "--plugin")[0] == 1, "must refuse overwrite"
    code, out = run("lint_skill.py", str(sk))
    assert code == 1 and any("TODO" in e for e in out["errors"]), "unfilled template TODO paths must fail lint"
    assert any("TODO placeholder" in w for w in out["warnings"]) and any("2 positive / 2 negative" in w for w in out["warnings"]), out
    made = [f for f in (t / "demo-skill").rglob("*") if f.is_file()]
    assert made and not any("{{" in f.read_text() for f in made), "every template value must be filled in"
    assert all((sk / d).is_dir() for d in ("references", "scripts", "learnings/proposed")), "the empty folders must be created"
    assert run("scaffold.py", "--name", "demo-skill", "--dest", tmp, "--description", "x", "--plugin", "--force")[0] == 0, "--force overwrites"
    code, out = run("scaffold.py", "--name", "dry-skill", "--dest", tmp, "--description", "x", "--dry-run")
    assert code == 0 and out["would_create"] and not (t / "dry-skill").exists(), "--dry-run writes nothing"
    assert run("scaffold.py", "--name", "Bad_Name", "--dest", tmp, "--description", "x")[0] == 2 and not (t / "Bad_Name").exists()
    assert run("scaffold.py", "--name", "nl-skill", "--dest", tmp, "--description", "a\nevil: 1")[0] == 2, "a control character is bad input"
    # a character that is a line break to some YAML reader, and a byte that is not UTF-8 (a surrogate inside Python): exit 2, nothing written
    for i, ch in enumerate(("\x7f", "\x85", "\u2028", "\u2029", b"\xff")):
        desc = b"Does X." + ch + b"evil: 1" if isinstance(ch, bytes) else f"Does X.{ch}evil: 1"
        p = subprocess.run([sys.executable, str(HERE / "scaffold.py"), "--name", f"ch{i}-skill", "--dest", tmp, "--description", desc], capture_output=True)
        assert p.returncode == 2 and b"--description" in p.stderr and b"Traceback" not in p.stderr and not (t / f"ch{i}-skill").exists(), f"{ch!r}: {p.stderr}"
    code, out = run("scaffold.py", "--name", "wide-skill", "--dest", tmp, "--description", "Does\u00a0X \U0001f469\u200d\U0001f4bb \u2014 caf\u00e9. Use when Y.")
    assert code == 0 and "caf\u00e9" in (t / "wide-skill" / "SKILL.md").read_text(encoding="utf-8"), "ordinary non-ASCII text is accepted"
    for name, desc, want in (("n" * 64, "x", 0), ("n" * 65, "x", 2), ("len-ok", "x" * 1024, 0), ("len-over", "x" * 1025, 2), ("len-none", "", 2),
                             ("a--b", "x", 2), ("-ab", "x", 2), ("ab-", "x", 2), ("a1-b2", "x", 0)):
        assert run("scaffold.py", "--name", name, "--dest", tmp, "--description", desc, "--dry-run")[0] == want, f"{name[:8]} / {len(desc)} chars"
    odd = 'Reads C:\\temp and "quotes". Use when X. Not for Y.'
    code, out = run("scaffold.py", "--name", "odd-skill", "--dest", tmp, "--description", odd, "--plugin")
    assert code == 0 and json.loads((t / "odd-skill" / "plugin.json").read_text())["description"] == odd, "description must survive JSON"
    code, out = run("lint_skill.py", out["skill_dir"])
    assert out["stats"]["description_chars"] == len(odd), "description must survive YAML, and the lint must unescape it"
    (t / "sym-skill").mkdir()
    (t / "sym-skill" / "SKILL.md").symlink_to(t / "outside.md")  # dangling: exists() is False for it
    assert run("scaffold.py", "--name", "sym-skill", "--dest", tmp, "--description", "x")[0] == 2 and not (t / "outside.md").exists()
    (t / "elsewhere").mkdir()
    (t / "linked-skill").symlink_to(t / "elsewhere")  # the new folder itself is a symlink: refused, also with --force
    assert run("scaffold.py", "--name", "linked-skill", "--dest", tmp, "--description", "x", "--force")[0] == 2 and not list((t / "elsewhere").iterdir())
    (t / "sub-link").mkdir()
    (t / "sub-link" / "evals").symlink_to(t / "elsewhere")  # a folder inside it that files go into is a symlink
    assert run("scaffold.py", "--name", "sub-link", "--dest", tmp, "--description", "x", "--force")[0] == 2 and not list((t / "elsewhere").iterdir())
    (t / "dest-link").symlink_to(t / "elsewhere")  # --dest may be a symlink: a linked skills folder is a normal setup
    assert run("scaffold.py", "--name", "via-link", "--dest", str(t / "dest-link"), "--description", "x")[0] == 0 and (t / "elsewhere" / "via-link" / "SKILL.md").is_file()
    (t / "afile").write_text("x")
    assert run("scaffold.py", "--name", "sub-skill", "--dest", str(t / "afile"), "--description", "x")[0] == 2, "an unwritable target is exit 2"
    assert any("scripts/validate.py" in e for e in out["errors"]), "a missing script named inside a command must fail lint"
    assert (sk / "assets" / "learning-entry.md").is_file(), "the template the learnings README names must be scaffolded"

    # the eval 3 fixture carries planted defects; the linter has to find each one
    fx = t / "changelog-writer"
    shutil.copytree(DEV / "evals" / "files" / "fixture-skills" / "changelog-writer", fx)
    (fx / "SKILL.fixture.md").rename(fx / "SKILL.md")
    code, out = run("lint_skill.py", str(fx))
    found = " ".join(out["errors"] + out["warnings"])
    planted = ("interactive prompt", "scripts/format_entries.py", "references/style.md", "third person", "'Use when", "Grep tool", "missing evals/evals.json")
    assert code == 1 and all(s in found for s in planted), out

    bad = t / "bad-skill"
    (bad / "scripts").mkdir(parents=True)
    (bad / "SKILL.md").write_text("---\nname: wrong-name\ndescription: I can help you.\nfoo: 1\n---\n"
                                  "# lint: no-dry" "-run: a waiver in SKILL.md covers no script\n" + "line\n" * 600)
    (bad / "scripts" / "go.py").write_text("x = inp" + 'ut("continue? ")\n')  # split so this file doesn't trip the linter
    code, out = run("lint_skill.py", str(bad), "--portable")
    errs = " ".join(out["errors"])
    assert code == 1 and all(s in errs for s in ("must match directory", "lines", "'foo'", "interactive")), out
    (bad / "references").mkdir()
    (bad / "references" / "orphan.md").write_text("never named\n")
    (bad / "scripts" / "wipe.py").write_text("import shutil\n# --dry" "-run is only mentioned in this comment\nshutil.rmtree('out')\n")
    (bad / "scripts" / "notes.py").write_text("# shutil.rmtree('out') is only named in a comment\nprint('ok')  # usage: notes.py\n")
    (bad / "scripts" / "pkg").mkdir()
    (bad / "scripts" / "pkg" / "mod.py").write_text("import shutil\nshutil.rmtree('out')\n")
    waive = "# lint: no-dry" "-run:"
    (bad / "scripts" / "pkg" / "own.py").write_text(f"import os\n{waive} removes only its own temp file\nos.remove('t')\n")
    (bad / "scripts" / "pkg" / "bare.py").write_text(f"import os\n{waive}\nos.remove('t')\n")
    (bad / "scripts" / "ask.py").write_text("prompt = 'continue? '\nx = inp" + "ut(prompt)  # usage: ask.py\n")
    code, out = run("lint_skill.py", str(bad))
    w, e = " ".join(out["warnings"]), " ".join(out["errors"])
    assert "references/orphan.md is never named" in w, out
    assert "'foo'" in w and "'foo'" not in e, "without --portable an unknown key is a warning"
    assert "scripts/wipe.py: changes things" in w and "scripts/notes.py: changes" not in w, out
    assert "scripts/ask.py: interactive" in e, out
    assert "scripts/pkg/mod.py: changes things" in w and "scripts/pkg/mod.py: no --help" not in w, out
    assert "pkg/own.py" not in w and "scripts/pkg/bare.py: changes things" in w, "the waiver needs a reason: " + w
    (bad / "evals").mkdir()
    (bad / "evals" / "trigger_evals.json").write_text('{"queries": []}')
    code, out = run("lint_skill.py", str(bad))
    assert code == 1 and any("must be a JSON array" in e for e in out["errors"]), out

    runs = t / "runs.jsonl"
    runs.write_text("\n".join(json.dumps({"query": f"q{i}", "should_trigger": i % 2 == 0, "triggered": i % 2 == 0 or i == 1})
                              for i in range(40) for _ in range(3)))
    code, out = run("score_trigger_evals.py", str(runs))
    assert code == 0 and [f["query"] for f in out["failures"]] == ["q1"], out
    buckets = [int(hashlib.sha256(f"q{i}".encode()).hexdigest(), 16) % 10 for i in range(40)]
    assert {5, 6} <= set(buckets), "the queries must fall on both sides of the 60/40 split point, or a moved split goes unseen"
    in_test = sum(b >= 6 for b in buckets)
    assert 0 < in_test < 40 and (out["train"]["queries"], out["test"]["queries"]) == (40 - in_test, in_test), out
    assert out["train"]["pass_rate"] + out["test"]["pass_rate"] < 2 and out["failures"][0]["trigger_rate"] == 1.0, out
    assert sum(out[s]["false_positives"] for s in ("train", "test")) == 1 and sum(out[s]["false_negatives"] for s in ("train", "test")) == 0, out
    runs.write_text('{"query": "tie", "should_trigger": true, "triggered": true}\n{"query": "tie", "should_trigger": true, "triggered": false}\n')
    code, out = run("score_trigger_evals.py", str(runs))
    assert code == 0 and out["failures"][0]["trigger_rate"] == 0.5, "a query triggered in half its runs has not triggered"
    runs.write_text('{"query": "miss", "should_trigger": true, "triggered": false}\n\n{"query": "miss", "should_trigger": true, "triggered": false}')
    code, out = run("score_trigger_evals.py", str(runs))
    assert code == 0 and sum(out[s]["false_negatives"] for s in ("train", "test")) == 1 and out["failures"][0]["trigger_rate"] == 0.0, out
    # a line break character or a lone surrogate inside a query is still one run on one line (queries come from real user text)
    for q in ("a\u2028b", "a\u2029b", "a\x85b", "\\ud800"):
        runs.write_text(f'{{"query": "{q}", "should_trigger": true, "triggered": true}}\n' * 3, encoding="utf-8")
        code, out = run("score_trigger_evals.py", str(runs))
        assert code == 0 and out["train"]["queries"] + out["test"]["queries"] == 1 and not out["failures"], f"{q!r}: {code} {out}"
    runs.write_text('{"query": "a", "should_trigger": true, "triggered": true}\r\n' * 2 + '{"query": "b", "should_trigger": false, "triggered": false}\r\n')
    code, out = run("score_trigger_evals.py", str(runs))
    assert code == 0 and out["train"]["queries"] + out["test"]["queries"] == 2, "CRLF line ends are line ends"
    # nested too deeply: an older Python raises RecursionError, a newer one parses it to a list, which is no run. Exit 2 on both.
    for bad_runs in ("{oops\n", "[1, 2]\n", "", "[" * 100000 + "]" * 100000 + "\n", '{"query": "a", "should_trigger": true}\n',
                     '{"should_trigger": true, "triggered": true}\n', '{"query": "a", "triggered": true}\n',
                     '{"query": 1, "should_trigger": true, "triggered": true}\n',
                     '{"query": "a", "should_trigger": false, "triggered": "false"}\n',
                     '{"query": "a", "should_trigger": true, "triggered": true}\n{"query": "a", "should_trigger": false, "triggered": true}\n'):
        runs.write_text(bad_runs)
        assert run("score_trigger_evals.py", str(runs)) == (2, {}), f"bad input must be exit 2 with no result: {bad_runs!r}"
    runs.write_bytes(b"\xff\xfe")
    assert run("score_trigger_evals.py", str(runs)) == (2, {}), "a file that is not UTF-8 is bad input"

    # ---- lint: one throwaway skill per group of checks; each assertion names the file or text it is about
    c = t / "cases"
    scripts = {
        "scripts/argv.py": 'import argparse, subprocess\nsubprocess.run(["git", "push", "origin", "main"])\n',
        "scripts/argv_rm.py": 'import argparse, subprocess\nsubprocess.run(["rm", "-rf", "/data"])\n',
        "scripts/http.py": 'import argparse, urllib.request\nurllib.request.Request(u, data=b"x", method="DELETE")\n',
        "scripts/sweep.sh": '# usage: sweep.sh\necho usage\nrm "$1"\n',
        "scripts/move.py": "import argparse, os\nos.replace(a, b)\n",
        "scripts/trail.py": "import argparse, os\nos.remove(t)  # lint: no-dry" "-run: removes its own temp file\n",
        "scripts/outside.py": "import argparse, os, subprocess\n# lint: no-dry" "-run: removes its own temp file\nos.remove(t)\n"
                              'subprocess.run("git push --force origin main", shell=True)\n',
        "scripts/strwaive.py": 'import argparse, shutil\nMSG = "# lint: no-dry-run: this is a string"\nshutil.rmtree("/data")\n',  # a string literal must not waive
        "scripts/short.py": "import argparse, shutil\n# lint: no-dry" "-run: because safe\nshutil.rmtree('/data')\n",
        "scripts/mention.py": 'import argparse, shutil\nprint("this tool has no --dry-run mode")\nshutil.rmtree("/data")  # TODO: add --dry-run\n',  # a mention is not a flag
        "scripts/real.py": 'import argparse, shutil\nap = argparse.ArgumentParser()\nap.add_argument("--dry-run", action="store_true")\nshutil.rmtree("/data")\n',
        "scripts/doc.py": 'import argparse\n"""Never calls inp' 'ut() and never runs git push or rm -rf."""\nprint("{}")\n',
        "scripts/ask.sh": 'echo usage\nread -rp "Continue? " ans\n',
        "scripts/pw.py": 'import argparse, getpass\npw = getpass.getp' 'ass("token: ")\n',
        "scripts/run.ts": "console.log('usage')\nfunction inp" "ut(args: string[]) { return args }\n",
        "scripts/test_clean.py": "import shutil, tempfile\nshutil.rmtree(tempfile.mkdtemp())\n",
    }
    not_mine = "import shutil\nx = inp" "ut('y/n? ')\nshutil.rmtree('build')\n"
    for folder in ("node_modules/dep", ".venv/lib", "vendor", "tests/fixtures", "__pycache__"):
        scripts[f"scripts/{folder}/mod.py"] = not_mine
    d = make(c, "calls", files=scripts)
    (d / "scripts" / "link.py").symlink_to("/dev/zero")
    (d / "scripts" / "folder.py").mkdir()
    code, e, w = lint(str(d))
    for name in ("argv.py", "http.py", "outside.py"):
        assert f"scripts/{name}: changes something outside this machine" in w, f"{name}: {w}"
    for name in ("argv_rm.py", "sweep.sh", "move.py", "strwaive.py", "short.py", "mention.py"):
        assert f"scripts/{name}: changes things" in w, f"{name}: {w}"
    for name in ("trail.py", "real.py", "doc.py", "run.ts", "test_clean.py", "mod.py"):
        assert f"{name}:" not in w + e, f"{name} must be clean: {w} {e}"
    assert "scripts/ask.sh: interactive" in e and "scripts/pw.py: interactive" in e and e.count("interactive") == 2, e
    assert "scripts/link.py: a symlink" in w and "scripts/folder.py: a symlink" in w, "odd files are named, not read: " + w

    d = make(c, "paths", files={"references/a.md": "## setup\nThen read `references/deep.md` and run `scripts/lost.py`.\n",
                                "references/deep.md": "x\n", "scripts/go.py": "import argparse\n"},
             body="Read [a](references/a.md#setup) if X. Did you run scripts/go.py? Run **scripts/bold.py** and\n"
                  "`${SKILL_DIR}/scripts/var.py`, see [t](gone.md \"title\") and [up](../other/SKILL.md).\n"
                  "Put the logo in the project's assets/img/logo.png. TODO write the rest.\n")
    code, e, w = lint(str(d))
    assert code == 1 and "a.md#setup" not in e and "go.py" not in e, "an anchor or a question mark is not part of the path: " + e
    assert all(f"does not exist: {x}" in e for x in ("scripts/bold.py", "scripts/var.py", "gone.md", "scripts/lost.py (named in references/a.md)")), e
    assert "assets/img/logo.png is not in this skill" in w and "logo.png" not in e, "a path in a folder the skill lacks is a warning"
    assert "references/a.md names references/deep.md" in w and "'../other/SKILL.md' is not relative" in w and "TODO placeholder" in w, w
    d = make(c, "slash", body="Run `python scripts\\win.py`.\n")
    assert "backslash in a file path" in lint(str(d))[1]

    d = make(c, "deploys", desc="Deploys the app. Use when shipping. Not for builds.")
    code, e, w = lint(str(d), "--portable")
    assert code == 0 and "mentions a side effect" in w and "disable-model" not in w, "the hint must not name a key --portable rejects: " + w
    d = make(c, "quiet", desc="Formats notes. Use when writing notes. Not for deploy or email tasks.")
    assert lint(str(d)) == (0, "", ""), "a side effect named only after 'Not for' is no side effect"
    assert "max 1024" in lint(str(make(c, "long-desc", desc="Use when x. Not for y. " + "x" * 1010)))[1]
    assert "description is empty" in lint(str(make(c, "no-desc", desc="")))[1]
    assert "lowercase" in lint(str(make(c, "Bad_Name")))[1]
    assert "tokens" in lint(str(make(c, "heavy", body=("x" * 99 + "\n") * 210)))[2]
    d = make(c, "edge", desc='Reads "I/O" traces. Use when x. Not for <b>y</b>.', body="line\n" * 499, head="compatibility: " + "x" * 501 + "\n")
    text = (d / "SKILL.md").read_text().replace("name: edge", "name: edge  # a YAML comment")
    (d / "SKILL.md").write_text("\ufeff" + text, encoding="utf-8")
    code, e, w = lint(str(d))
    assert e == "compatibility is 501 chars (max 500)" and "XML or HTML tag" in w and "third person" not in w, f"{e} / {w}"
    assert lint(str(make(c, "iotrace", desc="I/O trace parser. Use when x. Not for y.")))[2] == "", "'I/O' is not first person"

    old = c / "old-name"
    old.mkdir()
    (old / "SKILL.md").write_text((SKILL / "assets" / "redirect-skill.md").read_text().replace("OLD-NAME", "old-name"))
    code, e, w = lint(str(old), "--portable")
    assert code == 0 and e == "", "the redirect template must pass --portable: " + e

    d = make(c, "evalfiles")
    (d / "evals" / "evals.json").write_text('"just a string"')
    (d / "evals" / "trigger_evals.json").write_text('[{"query": 1, "should_trigger": "true"}]')
    e = lint(str(d))[1]
    assert 'evals.json: must be a JSON object' in e and "trigger_evals.json: must be a JSON array" in e, e
    (d / "evals" / "evals.json").write_text("[" * 100000 + "]" * 100000)
    code, e, w = lint(str(d))  # newer Pythons parse this depth, older ones raise RecursionError: an error either way
    assert code == 1 and "evals/evals.json: " in e, "deeply nested JSON is a lint error, not a crash: " + e
    assert run("lint_skill.py", str(d), "--evals-dir", str(t / "nowhere")) == (2, {}), "a missing --evals-dir is bad input"
    (d / "SKILL.md").write_bytes(b"---\nname: evalfiles\ndescription: x\n---\n\xff\xfe\n")
    assert run("lint_skill.py", str(d)) == (2, {}), "a file that cannot be read is exit 2, not a traceback with exit 1"

    # ---- table: one script per documented form, so each form has its own assertion. A row is (suffix, source, expected),
    # where expected holds "outside", "things" and/or "interactive", or is "" for a script the lint must leave alone.
    # A first line gives each script a usage text, so only the form under test can be reported.
    first = {"py": "import argparse, os, shutil, subprocess, sys\n", "sh": "echo usage\n", "js": 'console.log("usage")\n'}
    rows: list[tuple[str, str, str]] = []
    for call in ('subprocess.run("git push origin main", shell=True)', 'subprocess.run(["git", "-C", top, "push"])', "subprocess.run(['git', 'push'])",
                 'git(top, "push", "origin")', "run_git('push')", 'self._git_out(top, "push")', "import smtplib",
                 *(f"requests.{m}(url)" for m in ("post", "put", "patch", "delete")),
                 *(f'Request(url, method="{m}")' for m in ("POST", "PUT", "PATCH", "DELETE")), "Request(url, method='POST')",
                 'db.execute("DROP TABLE t")', 'db.execute("DELETE FROM t")', 'db.execute("TRUNCATE t")',
                 'run("npm publish")', 'run("cargo publish")', 'run("twine upload dist/*")', 'run("gh pr merge 7")', 'run("docker push img")',
                 'run("aws s3 rm s3://b/k")', 'run("kubectl apply -f x.yaml")'):
        rows.append(("py", call + "\n", "outside"))
    for line in ("git push origin main", *(f"curl -s -X {m} https://x" for m in ("POST", "PUT", "PATCH", "DELETE")), "curl -XPOST https://x",
                 *(f"{tool} {verb} x" for tool in ("kubectl", "terraform") for verb in ("apply", "delete", "destroy")),
                 "npm publish", "cargo publish", "twine upload dist/*", "gh pr merge 7", "docker push img", "aws s3 rm s3://b/k"):
        rows.append(("sh", line + "\n", "outside"))
    for call in ("os.remove(p)", "os.unlink(p)", "os.rmdir(p)", "os.removedirs(p)", "os.replace(a, b)", "shutil.rmtree(p)", "shutil.move(a, b)",
                 "Path(p).unlink()", 'os.system("rm -rf out")', 'os.system("rm -f out.txt")', 'os.system("rm -r out")',
                 'subprocess.run(["rm", p])', "subprocess.run(['rm', p])",
                 'run("git merge feature")', 'run("git clean -fd")', 'run("git reset --hard")', 'run(["git", "merge", b])',
                 'run(["git", "-C", top, "clean", "-fd"])', "run(['git', 'merge', b])",
                 'git(top, "worktree", "remove", "--force", p)', "git(top, 'worktree', 'remove', p)", 'git(top, "branch", "-D", b)',
                 'git(top, "checkout", sha, "--", path)',
                 'subprocess.run("""\nrm -rf out\n""", shell=True)'):  # a triple-quoted value is code, not a docstring
        rows.append(("py", call + "\n", "things"))
    for line in ('rm "$1"', "rm $f", "rm out.txt", "rm ./out.txt", "rm ~/out.txt", "rm -- out.txt", "  rm out.txt", "\trm out.txt", 'x=1; rm -rf "$d"',
                 'git merge "$b"', "git clean -fd", "git reset --hard HEAD~1"):
        rows.append(("sh", line + "\n", "things"))
    rows.append(("js", "fs.unlink(p, cb)\n", "things"))
    # look-alikes that only read, or change nothing
    for call in ('run("git merge-base a b")', 'run("git merged")', 'run(["git", "merge-base", a, b])', 'run(["git", "log", "--merges"])',
                 'git(top, "log")', 'git(top, "log")\nx = "push"', 'x = "git", "status"\ny = "push", "merge", "clean"', 'digit("push")',
                 'run("git checkout main")', 'git(top, "checkout", "main")', 'git(top, "checkout", "-b", name)', 'git(top, "worktree", "list")',
                 'git(top, "branch", "--list")', 'run("git reset --soft HEAD~1")', "requests.get(url)", 'Request(url, method="GET")',
                 'print("rm is not used here")', "os.path.join(a, b)", "items.remove(x)", "os.replaced = 1", 'print("format it")'):
        rows.append(("py", call + "\n", ""))
    for line in ("git merge-base a b", "git checkout main", "curl -s https://x", "kubectl get pods", "terraform plan", "echo rm", "npm install", "gh pr view 7"):
        rows.append(("sh", line + "\n", ""))

    # the --dry-run flag: every way a script can define or test it clears the warning ...
    wipe = {"py": "shutil.rmtree(d)\n", "sh": 'rm -rf "$d"\n', "js": "fs.unlink(p, cb)\n"}
    for suffix, flag in (
            ("py", 'ap.add_argument("--dry-run", action="store_true")'),
            ("py", 'ap.add_argument(\n    "-n",\n    "--dry-run",\n    action="store_true",\n    help="list the files, delete nothing",\n)'),
            ("py", '@click.option(\n    "--dry-run",\n    is_flag=True,\n    help="preview",\n)\ndef main(dry_run):\n    pass'),
            ("py", 'def main(dry_run: bool = typer.Option(False, "--dry-run")):\n    pass'),
            ("py", 'dry = "--dry-run" in sys.argv'), ("py", "if '--dry-run' in args:\n    dry = True"), ("py", 'if "--dry-run" in args:\n    dry = True'), ("py", 'dry = any(a in ("-n", "--dry-run") for a in args)'),
            ("py", 'dry = arg in ["-n", "--dry-run"]'), ("py", 'dry = arg in {"-n", "--dry-run"}'), ("py", 'dry = arg == "--dry-run"'),
            ("py", 'dry = sys.argv.count("--dry-run")'), ("py", 'match arg:\n    case "--dry-run":\n        dry = True'),
            ("sh", 'case "$1" in\n  --dry-run) dry=1 ;;\nesac'), ("sh", 'case "$1" in\n  --dry-run|-n) dry=1 ;;\nesac'),
            ("sh", 'if [ "$1" = "--dry-run" ]; then dry=1; fi'), ("sh", "if [[ $1 == --dry-run ]]; then dry=1; fi"),
            ("js", 'const dry = args.includes("--dry-run")'), ("js", 'const dry = process.argv[2] === "--dry-run"'),
            ("js", 'const { values } = parseArgs({ options: { "dry-run": { type: "boolean" } } })'),
            ("js", "const { values } = parseArgs({ options: { 'dry-run': {\n  type: 'boolean' } } })"),
            ("js", 'program.option("-n, --dry-run", "preview")')):
        rows.append((suffix, flag + "\n" + wipe[suffix], ""))
    # ... and a mention of it in a string, a comment, a docstring or the arguments of another tool does not
    for suffix, mention in (("py", 'print("this tool has no --dry-run mode")'), ("py", "x = 1  # TODO: add --dry-run"), ("py", "# --dry-run is planned"),
                            ("py", '"""Flags: --dry-run (planned)."""'), ("py", 'subprocess.run(["tool", "--dry-run"])'),
                            ("py", 'subprocess.run("tool --dry-run", shell=True)'), ("sh", 'echo "no --dry-run yet"'), ("sh", "tool --dry-run"),
                            ("js", "// --dry-run is planned"), ("js", 'console.log("no --dry-run yet")')):
        rows.append((suffix, mention + "\n" + wipe[suffix], "things"))

    # the waiver comment: whole line or after code, # or //, a reason of three words or more; never in a string, never for a remote change
    ok = "lint: no-dry-run: removes its own temp"
    for suffix, src, expected in (
            ("py", f"# {ok}\nos.remove(t)\n", ""), ("py", f"os.remove(t)  # {ok}\n", ""), ("py", f'os.remove("t")  #{ok}\n', ""),
            ("py", f"def f():\n    # {ok}\n    os.remove(t)\n", ""), ("sh", f'# {ok}\nrm "$t"\n', ""), ("sh", f'rm "$t"  # {ok}\n', ""),
            ("js", f"// {ok}\nfs.unlink(t, cb)\n", ""), ("js", f"fs.unlink(t, cb) // {ok}\n", ""),
            ("py", "# lint: no-dry-run: because safe\nos.remove(t)\n", "things"), ("py", "# lint: no-dry-run:\nos.remove(t)\n", "things"),
            ("py", "# lint: no-dry-run: x\nos.remove(t)\n", "things"), ("py", "# no-dry-run: removes its own temp\nos.remove(t)\n", "things"),
            ("py", f'MSG = "# {ok}"\nos.remove(t)\n', "things"), ("py", f"MSG = '# {ok}'\nos.remove(t)\n", "things"),
            ("js", f'const msg = "// {ok}"\nfs.unlink(t, cb)\n', "things"),
            ("py", f'# {ok}\nsubprocess.run("git push", shell=True)\n', "outside"), ("py", f'# {ok}\nos.remove(t)\ngit(top, "push")\n', "outside"),
            ("sh", f"# {ok}\ncurl -X POST https://x\n", "outside")):
        rows.append((suffix, src, expected))

    # docstrings are dropped, in every spelling; a triple-quoted value is not one, and the code after it is still read
    said = "Never calls input(), getpass.getpass(), git push or rm -rf; has no --dry-run."
    for q in ('"""', "'''", 'r"""', "R'''", 'b"""', 'rb"""', 'u"""', "Rb'''"):
        rows.append(("py", f"{q}{said}{q[-3:]}\nprint(1)\n", ""))
        rows.append(("py", f"def f():\n    {q}Summary.\n\n    {said}\n    {q[-3:]}\n    return 1\n", ""))
    for src, expected in (
            ('"""Says "rm -rf /" and \'git push\' and \'\'\' here."""\nprint(1)\n', ""),
            ("'''Has \"\"\" inside, and input().'''\nos.remove(t)\n", "things"),
            ('"""One."""\nshutil.rmtree(d)\n"""Two."""\n', "things"),
            ('def f():\n    """One.\n\n    More.\n    """\n    return 1\n\n\ndef g():\n    """Two."""\n    shutil.rmtree(d)\n', "things"),
            ('SQL = """\nSELECT 1\n"""\nshutil.rmtree("cache")\n\n\ndef f():\n    """doc"""\n', "things"),
            ('SQL = """\nSELECT 1\n"""\nsubprocess.run("git push origin main", shell=True)\n\n\ndef f():\n    """doc"""\n', "outside"),
            ('USAGE = """usage: x DIR\n"""\nanswer = input("again? ")\n\n\ndef f():\n    """doc"""\n', "interactive"),
            ("USAGE = '''usage: x DIR\n'''\nshutil.rmtree(d)\nanswer = input('again? ')\n\n\ndef f():\n    '''doc'''\n", "things interactive"),
            ('HELP = r"""\nusage\n"""\nTAIL = b"""\nbytes\n"""\nos.remove(t)\n"""A stray string statement."""\n', "things"),
            ('ap = argparse.ArgumentParser(epilog="""\nexamples:\n  x\n""")\nap.add_argument("--dry-run", action="store_true")\nshutil.rmtree("cache")\n'
             '\n\ndef f():\n    """doc"""\n', ""),
            ('ap = argparse.ArgumentParser(epilog="""\nexamples:\n  x\n""")\nshutil.rmtree("cache")\n\n\ndef f():\n    """Has --dry-run in the text."""\n', "things")):
        rows.append(("py", src, expected))

    # interactive prompts
    for suffix, src, expected in (
            ("py", 'x = input("y/n? ")\n', "interactive"), ("py", "x = input()\n", "interactive"), ("py", "if input('go? ') == 'y':\n    pass\n", "interactive"),
            ("py", 'import getpass\npw = getpass.getpass("token: ")\n', "interactive"),
            ("sh", 'read -p "Go? " a\n', "interactive"), ("sh", 'read -rp "Go? " a\n', "interactive"), ("sh", 'read -r -p "Go? " a\n', "interactive"),
            ("sh", 'read -s -r -p "Go? " a\n', "interactive"), ("sh", 'read -sp "Go? " a\n', "interactive"),
            ("sh", "read -r path\n", ""), ("sh", "while read -r line; do echo x; done\n", ""), ("sh", "read path\n", ""),
            ("py", "import fileinput\nfor line in fileinput.input():\n    pass\n", ""), ("py", "x = self.input()\n", ""), ("py", "x = raw_input()\n", ""),
            ("py", "data = sys.stdin.read()\n", ""), ("js", 'function input(a) { return a }\nconst x = input("y")\n', "")):
        rows.append((suffix, src, expected))

    files = {f"scripts/c{i:03d}.{suffix}": first[suffix] + src for i, (suffix, src, _) in enumerate(rows)}
    # folders that hold code the author did not write, or files wrong on purpose; test files; files that are not scripts
    hot = first["py"] + "x = input('y/n? ')\nshutil.rmtree('build')\n"
    for folder in ("node_modules", "venv", "vendor", "third_party", "__pycache__", "fixtures", "dist", "build", ".git", ".venv", "lib/vendor/deep", "a/b/dist"):
        files[f"scripts/{folder}/skipped.py"] = hot
    for name in ("tests/helper.py", "pkg/tests/deep.py", "test_thing.py", "selftest.py", "self_test.py"):
        files[f"scripts/{name}"] = "import shutil\nshutil.rmtree('build')\n"  # a test may delete freely and needs no --help
    for name in ("notes.txt", "tool.rb", "data.json", "README.md"):
        files[f"scripts/{name}"] = hot
    for name in ("lib/seen.py", "vendored/seen.py", "builds/seen.py", "testing.py", "latest_test.py", "contest.py"):
        files[f"scripts/{name}"] = hot
    files.update({"scripts/nohelp.py": "x = 1\n", "scripts/nohelp.sh": "x=1\n", "scripts/pkg/nohelp.py": "x = 1\n", "scripts/hashelp.py": 'print("--help")\n',
                  "scripts/hasusage.sh": 'echo "Usage: x"\n', "scripts/comment.py": "# usage: only in a comment\nx = 1\n"})
    d = make(c, "table", files=files)
    e, w, _ = quick(d)
    for i, (suffix, src, expected) in enumerate(rows):
        rel = f"scripts/c{i:03d}.{suffix}"
        got = " ".join(k for k, text in (("outside", f"{rel}: changes something outside this machine"), ("things", f"{rel}: changes things"),
                                         ("interactive", f"{rel}: interactive prompt")) if text in w + e)
        assert got == expected, f"{rel} must give {expected or 'nothing'!r}, gave {got or 'nothing'!r}:\n{src}"
        assert f"{rel}: no --help" not in w, rel
    assert "skipped.py" not in w + e, "a folder in SKIP_DIRS or a dot folder is not read: " + w
    for name in ("tests/helper.py", "pkg/tests/deep.py", "test_thing.py", "selftest.py", "self_test.py", "notes.txt", "tool.rb", "data.json", "README.md"):
        assert f"scripts/{name}" not in w + e, f"{name} is a test or not a script: {w}"
    for name in ("lib/seen.py", "vendored/seen.py", "builds/seen.py", "testing.py", "latest_test.py", "contest.py"):
        assert f"scripts/{name}: changes things" in w and f"scripts/{name}: interactive" in e, f"{name} is the author's script: {w}"
    for name, warned in (("nohelp.py", True), ("nohelp.sh", True), ("comment.py", True), ("pkg/nohelp.py", False), ("hashelp.py", False), ("hasusage.sh", False)):
        assert (f"scripts/{name}: no --help/usage found" in w) == warned, f"{name}: {w}"
    assert e.count("interactive prompt") == sum("interactive" in x for _, _, x in rows) + 6 and len(e.split(" | ")) == e.count("interactive prompt"), e

    # ---- frontmatter and description rules, each at its edge
    def front(name: str, text: str, body: str = "# T\n") -> Path:
        d = make(c, name)
        (d / "SKILL.md").write_text(f"---\nname: {name}\n{text}\n---\n{body}", encoding="utf-8")
        return d

    plain = "Formats notes. Use when writing notes. Not for changelogs."
    assert quick(front("fm-single", "description: 'It''s a formatter. Use when x. Not for y.'")) == ("", "", {"body_lines": 1, "body_tokens_est": 1, "description_chars": len("It's a formatter. Use when x. Not for y.")})
    for i, mark in enumerate((">", ">-", ">+", "|", "|-", "|+")):
        e, w, stats = quick(front(f"fm-block{i}", f"description: {mark}\n  Formats notes. Use when writing notes.\n  Not for changelogs."))
        assert (e, w, stats["description_chars"]) == ("", "", len(plain)), f"block scalar {mark}: {e} / {w} / {stats}"
    for i, (text, chars) in enumerate(((f"description: {plain}  # a YAML comment", len(plain)), (f"description: {plain}\t# a YAML comment", len(plain)),
                                       ("description: Formats C# and F#notes. Use when x. Not for y.", len("Formats C# and F#notes. Use when x. Not for y.")),
                                       ('description: "Formats notes #1. Use when x. Not for y."', len("Formats notes #1. Use when x. Not for y.")),
                                       ("description: 'Formats notes #1. Use when x. Not for y.'", len("Formats notes #1. Use when x. Not for y.")),
                                       ('description: "Tab\\there, C:\\\\temp. Use when x. Not for y."', len("Tab\there, C:\\temp. Use when x. Not for y.")),
                                       (f"description:    {plain}   ", len(plain)), (f"metadata:\n  version: 1.0.0\n  owner: me\ndescription: {plain}", len(plain)))):
        e, w, stats = quick(front(f"fm-scalar{i}", text))
        assert (e, w, stats["description_chars"]) == ("", "", chars), f"{text!r}: {e} / {w} / {stats}"
    for i, (text, body, in_e, not_e) in enumerate((
            (f"description: {plain}\ncompatibility: " + "x" * 500, "# T\n", "", "compatibility"),
            (f"description: {plain}\ncompatibility: " + "x" * 501, "# T\n", "compatibility is 501 chars (max 500)", ""),
            (f"description: {plain}", "line\n" * 499, "", "lines"), (f"description: {plain}", "line\n" * 500, "body is 500 lines", ""),
            (f"description: {plain}", "\n\n" + "line\n" * 499 + "\n\n", "", "lines"),  # blank lines around the body are not counted
            ("description: " + plain + "x" * (1024 - len(plain)), "# T\n", "", "max 1024"),
            ("description: " + plain + "x" * (1025 - len(plain)), "# T\n", "description is 1025 chars (max 1024)", ""),
            ("description:", "# T\n", "description is empty", ""), ("license: MIT", "# T\n", "description is empty", ""))):
        e = quick(front(f"fm-edge{i}", text, body))[0]
        assert in_e in e and (not not_e or not_e not in e), f"fm-edge{i}: {e}"
    for i, (desc, in_w, not_w) in enumerate((
            (plain + "x" * (400 - len(plain)), "", "listing budgets"), (plain + "x" * (401 - len(plain)), "description is 401 chars", ""),
            ("I can format notes. Use when x. Not for y.", "third person", ""), ("You get notes formatted. Use when x. Not for y.", "third person", ""),
            ("I format notes. Use when x. Not for y.", "third person", ""), ("Formats notes so you can read them. Use when x. Not for y.", "third person", ""),
            ("Formats notes. Use when I/O is slow. Not for y.", "", "third person"), ("Indexes notes. Use when x. Not for y.", "", "third person"),
            *((f"Formats notes. {clause} writing notes. Not for y.", "", "trigger clause") for clause in
              ("Use when", "use when", "Use this skill when", "Use this when", "Use skill for", "Use for", "Triggers on", "Trigger on")),
            ("Formats notes. Useful when writing notes. Not for y.", "lacks a 'Use when", ""), ("Formats notes. Not for y.", "lacks a 'Use when", ""),
            *((f"Formats notes. Use when x. {b} changelogs.", "", "boundary") for b in ("Not for", "not for", "Do not use for", "Not when writing")),
            ("Formats notes. Use when x.", "has no 'Not for", ""), ("Formats notes. Use when x. Notes for y.", "has no 'Not for", ""),
            ("Formats <b>notes</b>. Use when x. Not for y.", "XML or HTML tag", ""), ("Formats </b> notes. Use when x. Not for y.", "XML or HTML tag", ""),
            ("Formats notes when a < b or a > b. Use when x. Not for y.", "", "XML or HTML tag"))):
        w = quick(make(c, f"desc{i}", desc=desc))[1]
        assert in_w in w and (not not_w or not_w not in w), f"{desc!r}: {w}"
    # a side effect named before the boundary asks for a user-invoked skill; each verb, in each form the pattern lists
    for i, verb in enumerate(("Deploys", "Deploy", "Deploying", "Publishes", "Publishing", "Pushes", "Pushing", "Sends", "Sending", "Deletes", "Drops", "Merges",
                              "Emails", "Emailing", "Posts to", "Posting to", "Post to")):
        w = quick(make(c, f"side{i}", desc=f"{verb} the notes. Use when x. Not for y."))[1]
        assert w.startswith("description mentions a side effect; make the skill user-invoked only"), f"{verb}: {w}"
    for i, desc in enumerate(("Formats sender names and dropdowns. Use when x. Not for y.", "Formats posts. Use when x. Not for y.",
                              "Formats notes. Use when x. Not for deploy tasks.", "Formats notes. Use when x. Do not use to send email.",
                              "Formats notes. Use when x. Not when the user wants to publish.")):
        assert quick(make(c, f"calm{i}", desc=desc))[:2] == ("", ""), desc
    e, w, _ = quick(make(c, "invoked", desc="Deploys the app. Use when x. Not for y.", head="disable-model-invocation: true\n"))
    assert (e, w) == ("", "frontmatter key 'disable-model-invocation' is not in the open spec"), "a user-invoked skill may name its side effect: " + w
    e, w, _ = quick(c / "invoked", portable=True)
    assert e == "frontmatter key 'disable-model-invocation' is not in the open spec" and w == "", "--portable turns an unknown key into an error"
    e, w, _ = quick(make(c, "keys", head="license: MIT\nallowed-tools: x\nmetadata:\n  version: 1.0.0\ncompatibility: any\nmade-up: 1\n"))
    assert (e, w) == ("", "frontmatter key 'made-up' is not in the open spec and not a known host key"), w
    for name, warned in (("claude-notes", True), ("anthropic-notes", True), ("notes-helper", True), ("notes-utils", True), ("notes-keeper", False), ("util-notes", False)):
        assert ("uses a reserved or vague word" in quick(make(c, name))[1]) == warned, name
    for name in ("ab--cd", "-ab", "ab-", "ab_cd", "Ab", "a" * 65):
        assert "lowercase letters/digits/single hyphens" in quick(make(c, name))[0], name
    assert quick(make(c, "a" * 64))[0] == "" and quick(make(c, "a1-b2-c3"))[0] == ""
    e, w, stats = quick(make(c, "tokens-at", body=("x" * 99 + "\n") * 200))
    assert stats["body_tokens_est"] == 5000 and "tokens" not in w, w
    e, w, stats = quick(make(c, "tokens-over", body=("x" * 99 + "\n") * 200 + "abcd"))
    assert stats["body_tokens_est"] == 5001 and "~5001 tokens (aim < 5000)" in w, w
    for i, tool in enumerate(("StrReplace", "Bash(git status)", "the Read tool", "the Write tool", "the Grep tool", "the Glob tool", "the Edit tool", "activate_skill")):
        assert "harness-specific tool name" in quick(make(c, f"tool{i}", body=f"Call {tool} now.\n"))[1], tool
    assert quick(make(c, "tool-free", body="Read the file, then bash it. A TODOS list is fine.\n"))[:2] == ("", "")
    d = make(c, "counts")
    for pos, neg, warned in ((8, 8, False), (7, 9, True), (9, 7, True), (8, 12, False)):
        (d / "evals" / "trigger_evals.json").write_text(json.dumps([{"query": f"q{i}", "should_trigger": i < pos} for i in range(pos + neg)]))
        w = quick(d)[1]
        assert (w == f"evals/trigger_evals.json: {pos} positive / {neg} negative queries (aim 8-10 each, negatives = near-misses)") == warned and (w == "") != warned, w
    (d / "evals" / "trigger_evals.json").unlink()
    (d / "evals" / "evals.json").unlink()
    assert quick(d)[1] == "missing evals/evals.json | missing evals/trigger_evals.json"

    # ---- paths: ./ is the skill root; a link in a reference may climb to a file of this skill, not out of it
    d = make(c, "roots", files={"scripts/go.py": "import argparse\n", "assets/a.txt": "x\n",
                                "references/guide.md": "See [the script](../scripts/go.py), [the skill](../SKILL.md#top), [asset](../assets/a.txt) and\n"
                                                       "[gone](../scripts/gone.py). Not [out](../../elsewhere/x.md) or [abs](/etc/passwd).\n"
                                                       "Run `./scripts/go.py`, then `./scripts/lost.py`. [here](../references/guide.md) [it](scripts/go.py)\n"},
             body="Read [guide](references/guide.md) if X. Run `python3 ./scripts/go.py --help`, `./scripts/missing_dot.py` and\n"
                  "`<dir>/scripts/elsewhere.py`; in a repo run `../scripts/theirs.py` or `tools/scripts/theirs.py`. [up](../other.md) [dot](./references/guide.md)\n")
    e, w, _ = quick(d)
    assert e.split(" | ") == ["referenced file does not exist: scripts/missing_dot.py",
                              "referenced file does not exist: ../scripts/gone.py (named in references/guide.md)",
                              "referenced file does not exist: scripts/lost.py (named in references/guide.md)",
                              "referenced file does not exist: scripts/go.py (named in references/guide.md)"], e
    assert w.split(" | ") == ["path '../other.md' is not relative to the skill root",
                              "path '../../elsewhere/x.md' is not relative to the skill root (named in references/guide.md)",
                              "path '/etc/passwd' is not relative to the skill root (named in references/guide.md)"], w
    # a file name too long for the file system, or one with a NUL byte, does not exist: a lint error, not a crash, on every Python
    long_name = "a" * 300
    d = make(c, "long-names", files={"scripts/go.py": "import argparse\n"},
             body=f"Run scripts/{long_name}.py and [x]({long_name}.md), then assets/{long_name}/x.png and scripts/a\x00b.py.\n")
    code, e, w = lint(str(d))
    assert code == 1 and e.split(" | ") == [f"referenced file does not exist: scripts/{long_name}.py", f"referenced file does not exist: {long_name}.md",
                                            "referenced file does not exist: scripts/a\x00b.py"] and f"assets/{long_name}/x.png is not in this skill" in w, f"{code} {e} {w}"
    # at most MAX_CHARS of a file are read
    d = make(c, "capped", body="Read `references/big.md` and `references/small.md` if X.\n",
             files={"references/big.md": "x\n" * 500_000 + "Run `scripts/beyond.py`.\n", "references/small.md": "x\n" * 499_980 + "Run `scripts/within.py`.\n",
                    "scripts/go.py": "import argparse\n"})
    e, w, _ = quick(d)
    assert e == "referenced file does not exist: scripts/within.py (named in references/small.md)" and w == "", f"{e} / {w}"

    # ---- no input makes the lint slow: with a pattern that backtracks over these, the run would hit the timeout in run()
    d = make(c, "slow", body="Read `references/a.md` if X. ${" + "SKILL" * 80_000 + "\nscripts/" + "a.." * 30_000 + "\n",
             files={"references/a.md": "](" * 80_000 + "\n" + "](a#" * 40_000 + "\n" + "](x " + '"' * 50_000 + "\n",
                    "scripts/blank.py": "import argparse\n" + "\n" * 300_000 + "x = 1\n",
                    "scripts/spaces.py": "import argparse\n" + (" " * 500 + "\n") * 600 + " " * 300_000 + "x = 1\n",
                    "scripts/gits.py": 'import argparse\nx = [' + '"git",' * 60_000 + '"' + "x" * 600_000 + '"]\n',
                    "scripts/lists.py": "import argparse\ny = '" + "curl " * 10_000 + "'\nz = '" + "argv" * 10_000 + "'\n" + "add_argument(" * 10_000 + "\n"
                                        + "git(" * 10_000 + "\n" + "x in (" * 10_000 + "\n" + '"checkout",' * 10_000 + "\n",
                    "scripts/quotes.py": "import argparse\n" + "'''x\n" + '"""y\n' * 30_000 + "rb" * 100_000 + "\n",
                    "scripts/hashes.py": "import argparse\n" + "#" * 100_000 + "\nx = 1 " + "# lint: no-dry-run: a b " * 20_000 + "\n",
                    "scripts/read.sh": "echo usage\nread " + "-a " * 50_000 + "\nread -" + "a" * 100_000 + "\nrm" + " " * 100_000 + "\n"})
    code, e, w = lint(str(d))
    assert code == 1 and e.startswith("referenced file does not exist: scripts/a..a..") and " | " not in e, f"{code} {e[:300]}"
    d = make(c, "slow-front", head="metadata: x" + " " * 900_000 + "y\n")
    assert lint(str(d)) == (0, "", ""), "a frontmatter value with a long run of spaces"

    # the eval 6 fixture has to sit exactly at its own cap, or the case does not test the size rule
    nk = t / "notes-keeper"
    shutil.copytree(DEV / "evals" / "files" / "fixture-skills" / "notes-keeper", nk)
    (nk / "SKILL.fixture.md").rename(nk / "SKILL.md")
    check = [sys.executable, str(nk / "scripts" / "check_size.py")]
    assert subprocess.run(check, capture_output=True).returncode == 0 and lint(str(nk))[1] == ""
    original = (nk / "SKILL.md").read_text()
    assert len(original.splitlines()) == 20 and sum(not x.strip() for x in original.splitlines()) == 3, "the numbers eval 6 names"
    # eval 6's expectations, applied to the two honest outcomes and to the cut they exist to catch
    load = " Read `references/archive.md` for the monthly archive step."
    (nk / "references").mkdir()
    (nk / "references" / "archive.md").write_text("# Monthly archive\nMove notes older than 90 days to `notes/archive/`.\n")
    edited = original.replace("- [ ] 5. Report the path you wrote.", "- [ ] 5. Report the path you wrote." + load)
    (nk / "SKILL.md").write_text(edited)
    assert kept(original, original) and kept(original, edited), "no change, and a load condition added to an existing line, both pass"
    assert subprocess.run(check, capture_output=True).returncode == 0 and lint(str(nk))[1] == "", "and expectations 2 and 4 hold for it"
    cut = original.replace("\n\n## Never", "\n## Never") + "Read `references/archive.md` for the monthly archive step.\n"
    (nk / "SKILL.md").write_text(cut)
    assert subprocess.run(check, capture_output=True).returncode == 0 and lint(str(nk))[1] == "", "the cut passes the size check and the lint ..."
    assert not kept(original, cut), "... so expectation 1 has to be the one that fails it"
    assert not kept(original, original.replace("\n\n## Never", "\n" + load.strip() + "\n## Never")), "a blank line turned into text is a cut too"
    assert not kept(original, original.replace("Never delete a note. Move it to `notes/archive/` instead.", "Never delete a note." + load))
    assert not kept(original, original + "one more line\n") and not kept(original, original.replace("- [ ] 5. Report the path you wrote.\n", ""))
    (nk / "SKILL.md").write_text(original + "one more line\n")
    assert subprocess.run(check, capture_output=True).returncode == 1, "one more line must break the fixture's cap"

    # run_evals.py task mode against a stub agent: workspaces, fixture rename, both arms, saved outputs
    stub = t / "stub_agent.py"
    stub.write_text("import json\nprint(json.dumps({'type': 'system', 'model': 'stub'}))\n"
                    "print(json.dumps({'type': 'tool_call', 'subtype': 'started', 'tool_call': {'readToolCall': {'args': {'path': '/w/x/SKILL.md'}}}}))\n"
                    "print(json.dumps({'type': 'result', 'result': 'done', 'usage': {}, 'is_error': False}))\n")
    p = subprocess.run([sys.executable, str(DEV / "run_evals.py"), "task", "--skill", str(SKILL), "--out-dir", str(t / "task"),
                        "--ids", "3", "--agent-cmd", f"{sys.executable} {stub}"], capture_output=True, text=True)
    rows = {r["arm"]: r for r in json.loads(p.stdout)}
    assert p.returncode == 0 and set(rows) == {"with", "without"} and rows["with"]["first_skill"] == "x", p.stdout + p.stderr
    skills = {arm: Path(r["workspace"]) / ".agents" / "skills" for arm, r in rows.items()}
    assert (skills["with"] / SKILL.name / "SKILL.md").is_file() and not (skills["without"] / SKILL.name).exists()
    assert all((s / "changelog-writer" / "SKILL.md").is_file() for s in skills.values()), "fixture must be planted in both arms"
    assert (t / "task" / "3-with" / "result.md").read_text() == "done" and (t / "task" / "3-with" / "transcript.jsonl").stat().st_size
    stub.write_text("print('not json')\n")  # an agent that ends without a result is an error, not a pass
    p = subprocess.run([sys.executable, str(DEV / "run_evals.py"), "task", "--skill", str(SKILL), "--out-dir", str(t / "task2"),
                        "--ids", "4", "--agent-cmd", f"{sys.executable} {stub}"], capture_output=True, text=True)
    assert p.returncode == 1 and all("error" in r for r in json.loads(p.stdout)), p.stdout + p.stderr

print("selftest: all checks passed")
