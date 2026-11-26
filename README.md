# Skills

Agent skills in the [Agent Skills](https://agentskills.io/specification) layout: each folder under `skills/` is one self-contained skill and is exactly what gets installed. Development files (tests, evals, build logs) live under `dev/<skill>/` and are never installed.

| Skill | What it does |
| --- | --- |
| [`atomic-decompose`](skills/atomic-decompose/SKILL.md) | Plans a substantial task as small work items, asks every question it needs from you once with a default, then works to completion from saved state: small jobs in the main session, independent parts by sub-agents in parallel. |
| [`authoring-agent-skills`](skills/authoring-agent-skills/SKILL.md) | Designs, scaffolds, lints and evaluates agent skills and plugins: picks skill, MCP server, hook or rule, writes evals first, and checks the result with bundled scripts. |
| [`deep-research-run`](skills/deep-research-run/SKILL.md) | Researches one question with the local-deep-research (LDR) engine: picks the cheapest tool, checks claims against primary sources and writes a sourced result file with open questions. Works alone or as the skill of an `atomic-decompose` research item. |

## Install

The commands below install `atomic-decompose`; put another skill's name in its place to install that one.

With [`npx skills`](https://github.com/vercel-labs/skills) (Node 22.20+). This installs for all your projects into Cursor, Claude Code and Codex:

```bash
npx skills add <owner>/<repo> --skill atomic-decompose -g -a cursor -a claude-code -a codex
```

With [`gh skill`](https://cli.github.com/manual/gh_skill_install) (GitHub CLI 2.90+, preview):

```bash
gh skill install <owner>/<repo> atomic-decompose --scope user
```

By hand: copy `skills/atomic-decompose/` to `~/.agents/skills/` (read by Cursor, Codex and Zoo Code) and symlink `~/.claude/skills/atomic-decompose` to it (Claude Code). Install it in one location only, or a host that reads several folders may load it twice.

Pin a release with `#<tag>` (`npx skills`) or `@<tag>` (`gh skill`). `atomic-decompose` and `authoring-agent-skills` run local Python scripts, so read a skill before installing it (`gh skill preview`).

## atomic-decompose

The skill runs a local Python script that edits your workspace files and makes one git commit per work item on your current branch.

Requirements: `python3`, plus `git` and a workspace inside a git repository when a work item changes workspace files. The skill writes task state to `<workspace>/.atomic-decompose/<task-id>/`; the `.atomic-decompose/` folder holds its own `.gitignore`, so it never shows in `git status`. Parallel work runs in git worktrees inside the task folder, on `ad/<task-id>/` branches, and both are removed once the work has landed on your branch.

Parts that share no file are worked on at the same time, at most `max_parallel` of them (an integer from 1 to 64). A task takes the first of these that is set when it starts:

1. `--max-parallel N` on the `start` command;
2. `max_parallel` in the plan file;
3. the `AD_MAX_PARALLEL` environment variable;
4. `{"max_parallel": N}` in your user config file, `~/.config/atomic-decompose/config.json` (under `$XDG_CONFIG_HOME` if you set it; `%APPDATA%\atomic-decompose\config.json` on Windows);
5. `{"max_parallel": N}` in `.atomic-decompose.json` at the top of the repository;
6. the default, 4.

`python3 <skill folder>/scripts/decompose.py doctor --root <workspace>` prints the value a task there would get and which setting it comes from. `tune --max-parallel N --task <task folder>` changes it for a task that has already started.

## authoring-agent-skills

Requirements: `python3`, standard library only. Its scripts write only where you point them: `scaffold.py` creates the new skill under `--dest` (and refuses to overwrite without `--force`), `lint_skill.py` and `score_trigger_evals.py` read files and print JSON.

The skill holds principles, not host-specific facts such as frontmatter keys, folder paths or CLI commands. It tells the agent to look those up in each host's current documentation, from the list in `references/sources.md`.

## deep-research-run

The skill has no scripts. It needs the [local-deep-research](https://github.com/LearningCircuit/local-deep-research) MCP server, and `references/config-guide.md` lists the environment variables that server reads.

## Develop

```bash
python3 dev/atomic-decompose/selftest.py          # runnable check, standard library only
python3 dev/authoring-agent-skills/selftest.py    # runnable check, standard library only
python3 skills/authoring-agent-skills/scripts/lint_skill.py skills/<skill> --portable --evals-dir dev/<skill>/evals
```

`.github/workflows/check.yml` runs all three on every pull request and on `main`. A lint error fails the run; lint warnings are printed.

Agent evals for `authoring-agent-skills` are run by hand, not in CI. They need the Cursor CLI (`cursor-agent`), logged in:

```bash
python3 dev/authoring-agent-skills/run_evals.py trigger --skill skills/authoring-agent-skills --out runs.jsonl
python3 skills/authoring-agent-skills/scripts/score_trigger_evals.py runs.jsonl
python3 dev/authoring-agent-skills/run_evals.py task --skill skills/authoring-agent-skills --out-dir <dir>
```

`trigger` installs the skill at `~/.agents/skills/<name>/` for the length of the command and removes it afterwards. `task` saves each workspace and transcript for you to grade against `evals.json`; the agent can read and write outside its workspace, so run it where that is acceptable. Record the results in the skill's changelog.

Release: bump `metadata.version` in the skill's `SKILL.md`, add an entry to `dev/<skill>/CHANGELOG.md`, and tag `<skill>-v<version>`.

Eval fixture skills are stored as `SKILL.fixture.md`, so that installers don't offer them as real skills:

- `dev/atomic-decompose/evals/files/fixture-skills/csv-profile/`. The evaluator copies it into the case workspace as `.agents/skills/csv-profile/SKILL.md`, with a `.claude/skills/csv-profile` symlink to it.
- `dev/authoring-agent-skills/evals/files/fixture-skills/changelog-writer/`. Copy the folder into the case workspace as `.agents/skills/changelog-writer/` and rename the file to `SKILL.md`. Its defects are planted: eval 3 checks that a review finds them.
