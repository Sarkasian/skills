#!/usr/bin/env python3
"""Self-check for the authoring-agent-skills scripts. Usage: python3 dev/authoring-agent-skills/selftest.py  (exit 0 = all pass)."""
from __future__ import annotations

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
    p = subprocess.run([sys.executable, str(HERE / script), *args], capture_output=True, text=True)
    return p.returncode, json.loads(p.stdout) if p.stdout.strip() else {}


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
    (bad / "SKILL.md").write_text("---\nname: wrong-name\ndescription: I can help you.\nfoo: 1\n---\n" + "line\n" * 600)
    (bad / "scripts" / "go.py").write_text("x = inp" + 'ut("continue? ")\n')  # split so this file doesn't trip the linter
    code, out = run("lint_skill.py", str(bad), "--portable")
    errs = " ".join(out["errors"])
    assert code == 1 and all(s in errs for s in ("must match directory", "lines", "'foo'", "interactive")), out
    (bad / "references").mkdir()
    (bad / "references" / "orphan.md").write_text("never named\n")
    (bad / "scripts" / "wipe.py").write_text("import shutil\n# --dry" "-run is only mentioned in this comment\nshutil.rmtree('out')\n")
    (bad / "scripts" / "notes.py").write_text("# send and delete are only words in a comment\nprint('ok')  # usage: notes.py\n")
    (bad / "scripts" / "pkg").mkdir()
    (bad / "scripts" / "pkg" / "mod.py").write_text("import shutil\nshutil.rmtree('out')\n")
    waive = "# lint: no-dry" "-run:"
    (bad / "scripts" / "pkg" / "own.py").write_text(f"import os\n{waive} removes only its own temp file\nos.remove('t')\n")
    (bad / "scripts" / "pkg" / "bare.py").write_text(f"import os\n{waive}\nos.remove('t')\n")
    (bad / "scripts" / "ask.py").write_text("prompt = 'continue? '\nx = inp" + "ut(prompt)  # usage: ask.py\n")
    code, out = run("lint_skill.py", str(bad))
    w, e = " ".join(out["warnings"]), " ".join(out["errors"])
    assert "references/orphan.md is never named" in w, out
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
