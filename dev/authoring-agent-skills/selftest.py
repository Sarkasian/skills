#!/usr/bin/env python3
"""Self-check for the authoring-agent-skills scripts. Usage: python3 dev/authoring-agent-skills/selftest.py  (exit 0 = all pass)."""
from __future__ import annotations

import hashlib
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
    odd = 'Reads C:\\temp and "quotes". Use when X. Not for Y.'
    code, out = run("scaffold.py", "--name", "odd-skill", "--dest", tmp, "--description", odd, "--plugin")
    assert code == 0 and json.loads((t / "odd-skill" / "plugin.json").read_text())["description"] == odd, "description must survive JSON"
    code, out = run("lint_skill.py", out["skill_dir"])
    assert out["stats"]["description_chars"] == len(odd), "description must survive YAML, and the lint must unescape it"
    (t / "sym-skill").mkdir()
    (t / "sym-skill" / "SKILL.md").symlink_to(t / "outside.md")  # dangling: exists() is False for it
    assert run("scaffold.py", "--name", "sym-skill", "--dest", tmp, "--description", "x")[0] == 2 and not (t / "outside.md").exists()
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
                              for i in range(20) for _ in range(3)))
    code, out = run("score_trigger_evals.py", str(runs))
    assert code == 0 and [f["query"] for f in out["failures"]] == ["q1"], out
    in_test = sum(int(hashlib.sha256(f"q{i}".encode()).hexdigest(), 16) % 10 >= 6 for i in range(20))
    assert 0 < in_test < 20 and (out["train"]["queries"], out["test"]["queries"]) == (20 - in_test, in_test), out
    assert sum(out[s]["false_positives"] for s in ("train", "test")) == 1 and sum(out[s]["false_negatives"] for s in ("train", "test")) == 0, out
    runs.write_text('{"query": "tie", "should_trigger": true, "triggered": true}\n{"query": "tie", "should_trigger": true, "triggered": false}\n')
    code, out = run("score_trigger_evals.py", str(runs))
    assert code == 0 and out["failures"][0]["trigger_rate"] == 0.5, "a query triggered in half its runs has not triggered"
    for bad_runs in ("{oops\n", "[1, 2]\n", "", '{"query": 1, "should_trigger": true, "triggered": true}\n',
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

    # the eval 6 fixture has to sit exactly at its own cap, or the case does not test the size rule
    nk = t / "notes-keeper"
    shutil.copytree(DEV / "evals" / "files" / "fixture-skills" / "notes-keeper", nk)
    (nk / "SKILL.fixture.md").rename(nk / "SKILL.md")
    check = [sys.executable, str(nk / "scripts" / "check_size.py")]
    assert subprocess.run(check, capture_output=True).returncode == 0 and lint(str(nk))[1] == ""
    with (nk / "SKILL.md").open("a") as f:
        f.write("one more line\n")
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
