---
name: authoring-agent-skills
description: "Creates, fixes and reviews agent skills (SKILL.md) and plugins: skill vs MCP vs plugin vs hook, evals, lint, description tuning. Use when creating, splitting or reviewing a skill or plugin, when a skill is not picked up, or when a procedure the agent is told again and again should load by itself. Not for ordinary code or docs, using an existing skill, or product documents about skills."
license: MIT
metadata:
  version: 1.3.0
---
# Authoring agent skills

Copy this checklist and tick it off. Read each reference only at its step. `scripts/` paths are relative to this skill's folder; use `python` where `python3` is not on the PATH.

This skill holds principles, not host-specific facts (frontmatter keys, folder paths, limits, CLI commands, settings and manifest fields). They change between host releases. Whenever a step needs one, read `references/sources.md` and look it up in the host's current documentation; do not state it from memory.

- [ ] 1. Interview
- [ ] 2. Decide the mechanism → `references/decide.md`
- [ ] 3. Write evals first → `references/evals.md`
- [ ] 4. Scaffold
- [ ] 5. Author SKILL.md + scripts → `references/authoring.md`
- [ ] 6. Runtime behavior (only if multi-step, long or stateful) → `references/runtime.md`
- [ ] 7. Lint loop
- [ ] 8. Evaluate and tune the description
- [ ] 9. Ship → `references/ship.md`
- [ ] 10. Report

Improving an existing skill? Run step 7 on it first, then start at step 3.
Asked only to review a skill? Run step 7, then check it against steps 2, 3, 5 and 9 and report each finding with its file, line or lint message. Change no files unless asked.

## 1. Interview
Ask (use a structured question tool if the harness has one) only what you cannot infer:
- The task, plus 2-3 real examples or past failures.
- Trigger phrases users would say, and near-miss requests that must NOT trigger it.
- Side effects (deploy, send, delete, publish, write outside the workspace).
- Target hosts (Cursor, Claude Code, Codex, Gemini, custom) and target models (frontier and/or local 20-70B).
- User-configurable values and secrets.
- Location: project `.agents/skills/` (or the target host's own skills folder), personal, or a plugin.

## 2. Decide
Read `references/decide.md`. Write down one line each:
- Mechanism: always-on rule / skill / MCP server / hook / subagent / plugin. If it is not a skill, say so, recommend the right mechanism, and stop.
  - Needs a credential, live data from a service or writes to it → an MCP server for that service (an existing one first), paired with a skill that teaches its use. A script that reads the token from the environment is the fallback when no MCP server can be used; say which you chose and why.
  - "Always", "never", "every time" → a rule only asks; a hook enforces. Write the rule and create or recommend the hook that enforces it.
- Split or not: separate skills only for distinct triggers, distinct side effects or distinct runtimes. Mutually exclusive variants become `references/<variant>.md`.
- Subagents: only for read-only fan-out or independent review; writes stay in one agent.

## 3. Evals first
Read `references/evals.md`. Before writing instructions:
- `evals/evals.json`: at least 3 cases from real examples, each with checkable expectations (files or state, not wording).
- `evals/trigger_evals.json`: 8-10 should-trigger queries (explicit and implicit) and 8-10 near-miss negatives.
- Run the task cases once WITHOUT the skill and record what goes wrong. Only those gaps go into the skill.

## 4. Scaffold
Run: `python3 scripts/scaffold.py --name <name> --dest <dir> --description "<what>. Use when <triggers>. Not for <near-misses>."`
Add `--plugin` to wrap the skill in portable + Claude + Cursor plugin manifests. Use `--dry-run` first if the target directory already exists.

## 5. Author
Read `references/authoring.md`. Hard rules:
- Body < 500 lines and ~5k tokens; critical rules first (after compaction some hosts keep only the first ~5k tokens of a skill).
- Numbered steps + a copyable checklist; one default plus one escape hatch, never a menu.
- Only add what the model gets wrong without it (the gaps from step 3).
- Fragile, bulk or must-be-identical work goes in `scripts/`: non-interactive, `--help`, JSON on stdout, errors on stderr, distinct exit codes, idempotent, `--dry-run` if destructive. Say "Run X", never "See X".
- Destructive or batch work: plan → validate script → apply → verify.
- References one level deep, each with its load condition ("read X if Y").
- At a size limit, restructure: situational text goes to `references/`, a long script becomes modules behind the same entry script. Never cut instructions, help text or tests to fit.
- Generic verbs ("read the file", "run `python3 scripts/<name>.py`"), relative forward-slash paths, no harness tool names.
- Frontmatter: only `name`, `description`, `license`, `compatibility`, `metadata`, `allowed-tools`, unless a target host needs more (e.g. its switch that makes a side-effecting skill user-invoked only; look the key up per host).
- No secrets in the skill; scripts read them from env or the host's secret store.

## 6. Runtime
If the skill is multi-step, long-running or stateful, read `references/runtime.md` and add:
- A progress/state file the skill re-reads on resume (survives compaction).
- One structured error format (`ERROR [code] … resolves: … next: …`), retry cap (3), and stop-and-ask conditions.
- A `learnings/` flow: agent proposes in `learnings/proposed/` using `assets/skill/assets/learning-entry.md` (the scaffold copies it into the new skill's `assets/`), a human accepts. Never rewrite learnings wholesale.

## 7. Lint loop
Run: `python3 scripts/lint_skill.py <skill-dir>` (add `--portable` for skills shipped to claude.ai or other hosts; add `--evals-dir <dir>` if the evals are kept outside the skill folder).
Fix every error; fix or consciously accept each warning. Re-run until exit code 0. Max 3 rounds, then report the remaining issues.

## 8. Evaluate
- Task evals: run each case with the skill and without it (or vs the previous version), ideally in clean, separate runs (one subagent each if available). Grade expectations; compare pass rate, tokens and time.
- Trigger evals: run each query 3 times in a fresh session that only sees skill names + descriptions, and record `{"query", "should_trigger", "triggered"}` per run as JSONL. Score with `python3 scripts/score_trigger_evals.py runs.jsonl`.
- Tune the description using train failures only; keep the version with the best TEST pass rate. Never paste failed queries into the description.
- If you cannot run evals in this harness, say so and leave the eval files for the user.

## 9. Ship
Read `references/ship.md`. Read `references/distribute.md` only if the skill ships through a marketplace or to other teams, needs usage telemetry, or is being renamed or retired. Then:
- Side-effecting skill → user-invoked only on every target host.
- Version: SemVer in `metadata.version` (and plugin manifests); entry in `CHANGELOG.md`. Renamed skill → leave a redirect from `assets/redirect-skill.md` under the old name.
- User config: a plugin uses the host's plugin settings; a plain skill uses layered config files read by its script. State never lives in the install directory.
- Third-party or shared skill → security scan and a human review of scripts, hooks and MCP config.

## 10. Report
State: mechanism chosen and why, files created, lint result, eval results (with vs without, trigger train/test), host-specific facts looked up and any left unverified, and anything skipped with the reason.

## Gotchas
- Do not paste this skill's reference material into the new skill; link only what its task needs.
- A host-specific key or path copied from memory or from another host fails silently. Look it up (`references/sources.md`), and say in the report which facts you could not verify.
- A description that names everything triggers on nothing. Lead with the user's trigger words.
- Do not reuse a name an installed built-in already has (hosts ship their own skill-authoring skills); precedence differs by host.
- Strong "MUST" wording is for invariants that evals show being broken; otherwise explain why.
- Templates in `assets/` end in `.tmpl` so they are never discovered as nested skills.
