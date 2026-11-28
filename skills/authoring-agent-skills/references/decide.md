Host-specific names, limits and paths are left out of this file because they change. Look them up as `references/sources.md` describes.

## Skill vs MCP vs plugin vs others
| Need | Use |
|---|---|
| Always-true facts (conventions, commands, "never X") | `AGENTS.md` / always-on rule. Keep it short: hosts truncate long files. |
| Procedure needed sometimes | Skill |
| Auth, secrets, live data, external writes, persistent state | MCP server, paired with a skill that teaches its use |
| Must happen every time (enforcement) | Hook (an instruction is a request, a hook is enforcement; costs no context) |
| Side task that floods context / parallel read-only work | Subagent |
| Ship to other repos or teams | Plugin (bundle; skills get a namespaced name) |
| Prompt you keep retyping | User-invoked skill |
- A skill that is never opened does nothing. In Vercel's published evals an always-on docs index beat a skill for that reason. So: put an index of pointers in always-on context, and use skills for action-specific workflows.
- If the agent has a shell and no auth is needed, a CLI with good `--help` plus a skill often beats an MCP server. With a user credential involved, prefer an MCP server (an existing one for the service first): it keeps the credential out of the agent's shell and transcript.
- MCP servers may be able to serve skills themselves. Check the MCP specification for the current state before designing around it.

## When to split a skill
- Limits: SKILL.md <500 lines and ~5k tokens; name + description ~100 tokens; description ≤1,024 chars (spec).
- The binding constraint is the listing budget: each host gives all skill descriptions together a small share of context and cuts descriptions when it overflows. Front-load trigger words, and look up the budget of each target host.
- **Split when:** distinct triggers or intents; different side effects (read-only analysis vs apply); different runtime needs (`compatibility`); activation is imprecise because scope is too broad.
- **Don't split when:** variants are mutually exclusive (AWS/GCP/Azure → one workflow + `references/<p>.md`); the parts always load together (risk of conflicting instructions); overlap can be fixed by tightening both descriptions first.
- References: one level deep, which means SKILL.md names each one and states *when* to load it ("read X if API returns non-200"). A file reached only through another reference gets partially read or missed. Add a table of contents if >100 lines.
- Router skill: chooses only, then points to refs, sibling skills, or subagents.
- Shared content: duplicate it or use a plugin-level script; avoid cross-skill relative paths (paths resolve from the skill root).
- Use unique names; never rely on shadowing. Which copy wins when two skills share a name differs by host.

## Subagents
- Use for: breadth research fan-out, reading many files or logs when only a summary is needed, independent review (sees the diff only, none of the author's context), parallel read-only work.
- Avoid when: phases share heavy context, the task needs back-and-forth, latency matters, or it's a quick targeted change.
- Cost: a multi-agent run bills several times the tokens of a single agent. Every subagent re-pays the fixed prefix (system prompt, tool schemas, brief); each agent turn resends its growing transcript; parallel workers read overlapping sources; the lead reads every summary. The main context gets smaller, the bill gets larger. Prompt caching makes repeated prefixes cheaper but doesn't remove them. You are buying quality with tokens; do it only when the task is worth it.
- Writes stay single-threaded; extra agents contribute intelligence, not actions (Anthropic and Cognition agree).
- Effort scaling: 1 agent / 3–10 calls for simple tasks; 2–4 subagents for comparisons; >10 only for complex research.
- Subagents write artifacts to disk and return a path + a short summary (avoids a "game of telephone").
- Context sharing: workers/consultants get a fork of full context; reviewers get none.
- Cap nesting depth; read-only reviewers cannot spawn agents. Whether a subagent inherits skills differs by host, so check.

## Side-effect gating
- Anything irreversible is user-invoked only, on every target host.
- Every host has its own switch for "the model may not start this skill by itself", and the switches differ in name, location (frontmatter, a side file, settings) and exact meaning. One example is the frontmatter key `disable-model-invocation: true`. Look up the switch for each target host; do not carry one host's key to another.
- Check three things in the host's documentation: does the switch also remove the description from context; can the user still invoke the skill; does it apply to skills shipped in a plugin.
- A field that pre-approves tools usually does not restrict the tools available. Restricting needs a deny rule or a deny field. Never pre-approve a general shell.
- Scripts that change things need `--dry-run` (the script contract in `references/authoring.md`, which SKILL.md loads at step 5). A destructive step outside the approved plan → stop and ask.
