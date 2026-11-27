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
