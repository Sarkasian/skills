#!/usr/bin/env python3
"""Checks that the parts of deep-research-run agree with each other. Standard library only.

Run: python3 dev/deep-research-run/selftest.py   (exit 0 = all checks hold, 1 = an assertion failed)
"""
import json
import re
from pathlib import Path

DEV = Path(__file__).resolve().parent
SKILL = DEV.parent.parent / "skills" / "deep-research-run"
HEADINGS = ["## Answers", "## Unverified", "## Failures", "## Open threads", "## Passes"]


def main() -> None:
    text = (SKILL / "SKILL.md").read_text(encoding="utf-8")

    # The result template and the checklist must use the same five headings, in the template's order.
    template = re.search(r"```markdown\n(.*?)```", text, re.S).group(1)
    assert re.findall(r"(?m)^## .+$", template) == HEADINGS, "template headings changed"
    checklist = "\n".join(line for line in text.splitlines() if line.startswith("- [ ]"))
    for h in HEADINGS:
        assert f"`{h}`" in checklist, f"checklist does not name {h}"
    assert set(re.findall(r"`(## [^`]+)`", text)) <= set(HEADINGS), "SKILL.md names a heading the template lacks"
    assert template.splitlines()[1].startswith("Status: "), "Status must be the template's second line"

    # Every reference is named in SKILL.md and exists, and no reference sends the reader to another one.
    named = set(re.findall(r"references/[\w.-]+\.md", text))
    on_disk = {f"references/{p.name}" for p in (SKILL / "references").glob("*.md")}
    assert named == on_disk, f"references named {sorted(named)} but on disk {sorted(on_disk)}"
    for ref in on_disk:
        assert "references/" not in (SKILL / ref).read_text(encoding="utf-8"), f"{ref} points at another reference"

    # Every status and route that the skill, a reference or an eval names is one the skill defines.
    statuses = set(template.splitlines()[1][len("Status: "):].split(" | "))
    assert all(s.isalpha() for s in statuses), f"the template's status line is malformed: {sorted(statuses)}"
    steps = {n: (title, body) for n, title, body in re.findall(r"(?ms)^## (\d)\. ([^\n]+)\n(.*?)(?=^## |\Z)", text)}
    routes = set(re.findall(r"(?m)^\| (\d)\. ", text))
    assert steps and routes, "numbered steps or route rows not found"
    everything = text.replace(template, "") + (DEV / "evals" / "evals.json").read_text(encoding="utf-8")
    for ref in on_disk:
        everything += (SKILL / ref).read_text(encoding="utf-8")
    found = set(re.findall(r"Status: (\w+)", everything))
    assert found <= statuses, f"unknown status: {sorted(found - statuses)}"
    found = {n for pair in re.findall(r"\b[Rr]outes? (\d)(?: to (\d))?", everything) for n in pair if n}
    assert found <= routes, f"unknown route: {sorted(found - routes)}"

    # Every step reference points at the step that holds what the reference says is there. A range ("steps 1
    # to 5") needs both ends to exist. Any other reference must be worded in one of the ways below, and the step
    # it names must then be the one with that title or that text, so a wrong number fails even if the step exists.
    points_at = (
        (r"check in step (\d)|step (\d) checks?\b", "text", "Check the tool"),
        (r"route \d of step (\d)", "text", "| Route |"),
        (r"go to step (\d) with `Status|as step (\d) says", "text", "```markdown"),
        (r"skip step (\d)|\| Step (\d)\. \|", "title", "Research"),
        (r"through step (\d)|(?:searches|waits) and step (\d)", "title", "Verify"),
    )
    placed = set()
    for m in re.finditer(r"\b[Ss]teps (\d) to (\d)", everything):
        assert m.group(1) in steps and m.group(2) in steps, f"unknown step in: {m.group(0)}"
        placed.add(m.start(1))
    assert f"steps 1 to {max(steps)} in order" in text, "the opening line must name every step"
    for pattern, where, needle in points_at:
        for m in re.finditer(pattern, everything):
            group = next(g for g in range(1, (m.lastindex or 0) + 1) if m.group(g))
            title, body = steps.get(m.group(group), ("", ""))
            assert needle == title if where == "title" else needle in body, \
                f"'{m.group(0)}' names step {m.group(group)}, which does not hold: {needle}"
            placed.add(m.start(group))
    for m in re.finditer(r"\b[Ss]teps? (\d)", everything):
        assert m.start(1) in placed, \
            f"a step reference the selftest cannot place: ...{everything[max(0, m.start() - 40):m.end() + 20]!r}"

    # The core names no engine tool as Server:tool; that belongs in the engine reference.
    assert "local-deep-research:" not in text, "Server:tool names belong in references/local-deep-research.md"

    # One version, in SKILL.md and at the top of the changelog.
    version = re.search(r"(?m)^  version: (\S+)$", text).group(1)
    newest = re.search(r"(?m)^## (\d+\.\d+\.\d+)", (DEV / "CHANGELOG.md").read_text(encoding="utf-8")).group(1)
    assert version == newest, f"SKILL.md says {version}, changelog says {newest}"

    # Every fixture an eval names exists.
    evals = json.loads((DEV / "evals" / "evals.json").read_text(encoding="utf-8"))["evals"]
    for case in evals:
        for f in case["files"]:
            assert (DEV / f).is_file(), f"eval {case['id']} names a missing file: {f}"
    assert len({c["id"] for c in evals}) == len(evals), "eval ids must be unique"

    print("selftest: all checks hold")


if __name__ == "__main__":
    main()
