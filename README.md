# Skills

Agent skills in the [Agent Skills](https://agentskills.io/specification) layout: each folder under `skills/` is one self-contained skill and is exactly what gets installed. Development files (tests, evals, build logs) live under `dev/<skill>/` and are never installed.

| Skill | What it does |
| --- | --- |
| [`atomic-decompose`](skills/atomic-decompose/SKILL.md) | Plans a substantial task as small work items, asks every question it needs from you once with a default, then works to completion from saved state, delegating items to sub-agents. |

## Install

With [`npx skills`](https://github.com/vercel-labs/skills) (Node 22.20+). This installs for all your projects into Cursor, Claude Code and Codex:

```bash
npx skills add <owner>/<repo> --skill atomic-decompose -g -a cursor -a claude-code -a codex
```

With [`gh skill`](https://cli.github.com/manual/gh_skill_install) (GitHub CLI 2.90+, preview):

```bash
gh skill install <owner>/<repo> atomic-decompose --scope user
```

By hand: copy `skills/atomic-decompose/` to `~/.agents/skills/` (read by Cursor, Codex and Zoo Code) and symlink `~/.claude/skills/atomic-decompose` to it (Claude Code). Install it in one location only, or a host that reads several folders may load it twice.

Pin a release with `#<tag>` (`npx skills`) or `@<tag>` (`gh skill`). The skill runs a local Python script that edits your workspace files through git checkpoints and worktrees, so read it before installing (`gh skill preview`).

Requirements: `python3`, plus `git` and a workspace inside a git repository when a work item changes workspace files. The skill writes task state to `<workspace>/.atomic-decompose/<task-id>/`, which holds its own `.gitignore`, so it never shows in `git status`; checkpoints live under `refs/atomic-decompose/` until you accept the result.

## Develop

```bash
python3 dev/atomic-decompose/selftest.py    # runnable check, standard library only
```

Release: bump `metadata.version` in `SKILL.md`, add a `dev/atomic-decompose/CHANGELOG.md` entry, and tag `atomic-decompose-v<version>`.

The eval fixture skill is stored as `dev/atomic-decompose/evals/files/fixture-skills/csv-profile/SKILL.fixture.md`, so that installers don't offer it as a real skill. The evaluator copies it into the case workspace as `.agents/skills/csv-profile/SKILL.md`, with a `.claude/skills/csv-profile` symlink to it.
