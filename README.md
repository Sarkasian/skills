# Skills

Agent skills in the [Agent Skills](https://agentskills.io/specification) layout: each folder under `skills/` is one self-contained skill and is exactly what gets installed. Development files (tests, evals, build logs) live under `dev/<skill>/` and are never installed.

| Skill | What it does |
| --- | --- |
| [`atomic-decompose`](skills/atomic-decompose/SKILL.md) | Plans a substantial task as small work items, asks every question it needs from you once with a default, then works to completion from saved state: small jobs in the main session, independent parts by sub-agents in parallel. |

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

Pin a release with `#<tag>` (`npx skills`) or `@<tag>` (`gh skill`). The skill runs a local Python script that edits your workspace files and makes one git commit per work item on your current branch, so read it before installing (`gh skill preview`).

Requirements: `python3`, plus `git` and a workspace inside a git repository when a work item changes workspace files. The skill writes task state to `<workspace>/.atomic-decompose/<task-id>/`; the `.atomic-decompose/` folder holds its own `.gitignore`, so it never shows in `git status`. Parallel work runs in git worktrees inside the task folder, on `ad/<task-id>/` branches, and both are removed once the work has landed on your branch.

Parts that share no file are worked on at the same time, at most `max_parallel` of them (an integer from 1 to 64). A task takes the first of these that is set when it starts:

1. `--max-parallel N` on the `start` command;
2. `max_parallel` in the plan file;
3. the `AD_MAX_PARALLEL` environment variable;
4. `{"max_parallel": N}` in your user config file, `~/.config/atomic-decompose/config.json` (under `$XDG_CONFIG_HOME` if you set it; `%APPDATA%\atomic-decompose\config.json` on Windows);
5. `{"max_parallel": N}` in `.atomic-decompose.json` at the top of the repository;
6. the default, 4.

`python3 <skill folder>/scripts/decompose.py doctor --root <workspace>` prints the value a task there would get and which setting it comes from. `tune --max-parallel N --task <task folder>` changes it for a task that has already started.

## Develop

```bash
python3 dev/atomic-decompose/selftest.py    # runnable check, standard library only
```

Release: bump `metadata.version` in `SKILL.md`, add a `dev/atomic-decompose/CHANGELOG.md` entry, and tag `atomic-decompose-v<version>`.

The eval fixture skill is stored as `dev/atomic-decompose/evals/files/fixture-skills/csv-profile/SKILL.fixture.md`, so that installers don't offer it as a real skill. The evaluator copies it into the case workspace as `.agents/skills/csv-profile/SKILL.md`, with a `.claude/skills/csv-profile` symlink to it.
