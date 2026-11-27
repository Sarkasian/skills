Host-specific names, limits and paths are left out of this file because they change. Look them up as `references/sources.md` describes.

## Code in skills (deterministic coordination)
- Use a script for: sorting, copying between tools, transforms, parsing, validation, document assembly, anything that must repeat identically, or a helper the agent keeps rewriting in eval transcripts.
- Degrees of freedom, set per section: high (prose; many valid approaches, e.g. review), medium (pseudocode or parameterized script), low (exact command; fragile or order-sensitive, e.g. migrations).
- "Run X" = execute (only output costs tokens). "See X" = read as reference. Be explicit about which.
- Script contract: non-interactive (flags/env/stdin); `--help`; JSON on stdout, diagnostics on stderr; distinct exit codes; idempotent; `--dry-run` for destructive ops; reject ambiguous input; bounded output (hosts truncate long tool output; support `--offset`/`--output`); actionable errors ("Field X not found. Available: …"); self-contained deps (inline script metadata, pinned package versions); handle errors in the script; document every constant.
- Plan → validate → execute: write `plan.json` → validator checks it against the source of truth → apply → verify.
- Code execution with MCP: expose tools as a code API on the filesystem; filter in a sandbox; data flows tool-to-tool without entering the model. Cost: sandbox, limits, monitoring. Consolidate chained tools (`schedule_event` instead of 3 calls).
- Disagreement: Anthropic leans toward scripts; Codex says prefer instructions unless you need determinism; skills with scripts are more often found vulnerable. → Use scripts where determinism matters; review and scan them.

## Harness-agnostic
- Frontmatter: only `name` (1–64, lowercase-hyphen, = dir name), `description`, `license`, `compatibility` (≤500 chars), `metadata` (str→str), `allowed-tools` (experimental). Some hosts reject extra keys, others ignore them.
- Host-only fields exist for invocation control, path scoping, model or effort pinning, forked context, hooks and argument substitution. Each one ties the skill to that host. Add one only for a named target host, after reading that host's current documentation.
- Relative paths, forward slashes. Generic verbs ("read the file", "run `python3 scripts/<name>.py`"), not tool names. MCP tools as `Server:tool`.
- Discovery: `.agents/skills/` is the cross-host project folder. Some hosts read only their own folder; symlink that folder to `.agents/skills/`. Look up the discovery paths of each target host.
- `AGENTS.md` is canonical; a host-specific always-on file should import it, not copy it. Nested files: closest wins.
- Plugins: a root `plugin.json` per the Agent Plugins specification, plus the native manifest of each target host. Each host names its plugin-root variable differently and does not expand another host's, so use the right one in each native manifest.
- Fallback when scripts can't run: state needs in `compatibility` (hosts don't act on it); describe the algorithm or output schema in SKILL.md so the model can do it by hand. Hosted sandboxes may have no network.

## Model-agnostic (frontier ↔ small local models)
- Small models fail mainly from load. Research findings that hold across models: accuracy falls as the number of instructions grows, and falls fastest on small models (IFScale); instructions early in the prompt are followed more than later ones; content in the middle of a long context is recalled worst; a focused prompt beats a full one; a small model that fails with many tools can succeed with few (Less is More).
- Design for the smallest target: logic in scripts; numbered steps + copyable checklist; one default + escape hatch (not a menu); output template/example; few consolidated tools; JSON I/O with the schema in the prompt; one term per concept; repeat key constraints at the step where they apply; Gotchas section in SKILL.md; core path in SKILL.md, advanced cases in triggered references.
- Local runtimes: set the context window explicitly (defaults are small), and use the model's native tool-call template.
- No model pin in portable skills. Test on the smallest and the largest target model, pinned in CI. For current model rankings read a current leaderboard; do not store scores in a skill.
- Caveat: no study directly tests numbered steps on small models; this is inferred from the research above.

## Token efficiency
- Budgets: metadata ~100 tokens; body <5k; references 0 until read. The body is a recurring cost on every later turn.
- Per paragraph: "would the agent get this wrong without it?" Skip what the model already knows.
- Execute, don't load; point to files, don't inline; filter in code; offer a concise output mode; pagination; bounded script output.
- Prompt cache: the cached prefix is tools, then system text, then messages, and a change early in it invalidates everything after. Put timestamps and per-request data last. Don't let hooks or skills change tool lists or system text mid-session.
- Descriptions: pushy but ≲400 chars, use case first.
- Measure with the host's own usage and cost tools.

## When a file reaches its size limit
A size limit (the body budget above, or a cap that a skill's own tests set) keeps the skill cheap to load and stops it growing. Meet it by restructuring, never by squeezing.
- SKILL.md: move what only one situation needs (resuming, the final report, a rare command, a long example) to `references/<situation>.md` and leave one line that says when to read it. Where a script drives the work, have its output name the file at the moment it is needed. What applies on every run stays: the core steps and the "never" rules.
- A script: do not cap its lines. The agent runs it and does not load it, so its length costs nothing per run, and improving it makes it longer. Keep it in one file while it reads top to bottom. When it outgrows that, split it along its existing sections into modules in a folder beside a thin entry script, so the command the agent runs does not change. Standard library only still holds.
- Never delete instructions, argument help, tests, sentences in the docs or blank lines to pass a size check, and never edit the check or a document so that it passes. If restructuring is not enough, stop and ask whether the limit should move, and record the reason where the limit is set.
- Caveat: this is a recommendation of this skill. It comes from one case, where an agent met two caps by cutting safety rules and argument help.

## Triggering / description
- Third-person what + "Use when…" + "Not for…" boundaries. Keywords, file types, synonyms. Trigger words first. No XML. Hyphenated names without `helper`/`utils`/`claude`/`anthropic`, and no `org:` prefixes. If a target host has a scoping field (by file path, for example), use it.
- Validate with trigger evals (`references/evals.md`).

## Composition between skills
- Reference other skills by their namespaced name.
- Contract = file + schema: A writes `out/x.json`; B validates it with a bundled script and fails with an actionable error. No specification defines inter-skill contracts (this is a recommendation).
- Router skills: thin, choose only, and name sub-skills explicitly. Do not expect a host to detect cycles → lint in CI.
- Plugin dependencies: some hosts resolve versioned dependencies between plugins, others have none. Check each target host; where there are none, bundle.
- Skill + MCP: ship them in the same plugin so they version together; across plugins, declare a dependency so tool renames don't silently break.
- Unique names only: name precedence differs by host.

## Reference layout
```text
AGENTS.md                         # host-specific always-on files import it
.agents/skills/<name>/            # symlink a host's own skills folder to .agents/skills
.github/CODEOWNERS                # plugins/*/ owners
plugins/my-plugin/
├── plugin.json                   # Agent Plugins manifest, strict semver
├── CHANGELOG.md                  # deprecations + removal dates
├── <host>/plugin manifest        # one native manifest per target host
└── skills/doc-writer/
    ├── SKILL.md                  # <500 lines; checklist, gotchas, "read X if Y"
    ├── references/               # 1 level deep
    ├── scripts/                  # executed; JSON out; --dry-run; idempotent
    ├── assets/                   # templates
    ├── evals/{evals.json,trigger_evals.json}
    └── learnings/{proposed/,accepted.jsonl}
```
Installers copy the whole skill folder to every user. Keep `evals/` and `learnings/` inside it for a private or project skill (simplest, and they travel with the skill). For a skill published from a repository to many users, move everything a user never runs (evals, eval fixtures, learnings, changelog, tests) to `dev/<name>/` beside `skills/<name>/`, and lint with `--evals-dir dev/<name>/evals`.
