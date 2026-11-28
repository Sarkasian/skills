Host-specific names, limits and paths are left out of this file because they change. Look them up as `references/sources.md` describes.

## User configuration
- Not in SKILL.md frontmatter (no host reads it as config).
- Secrets never pass through the model: scripts or MCP servers read them from the environment or the host's secret store.
- Assume no inherited environment: hosts filter what reaches a script's shell.
- Scripts read config at run time (SKILL.md is loaded once per session).
- Ask once, persist: script fails fast naming the missing value → agent asks → writes config → re-runs.
- Config files carry `schema_version`, with an idempotent migration script run on first use after an upgrade.
- **Skill in a plugin:** declare settings in the host's native plugin manifest. Hosts that support this have a typed settings block and keep sensitive values in the OS keychain; the portable manifest has no settings field. Keep state and config in the host's plugin data directory, which survives updates, never in the install directory, which is replaced on every update. Look up the field names and the data-directory variable for each target host.
- **Plain skill (no plugin):** there is no settings screen, so a script resolves each setting itself. It takes the first of these that is set, highest first:
  1. a command-line flag;
  2. the task's own plan or input file;
  3. an environment variable;
  4. the user file `$XDG_CONFIG_HOME/<skill>/config.json` (`~/.config/<skill>/config.json` when that variable is unset; `%APPDATA%\<skill>\config.json` on Windows);
  5. a project file at the repository root (`.<skill>.json`), committed for the team;
  6. the built-in default.

  None of these is inside the installed skill folder. Validate every value where it is read. A value that cannot be used is reported with its file and field, never silently replaced by the default. Resolve once when the task starts and store the result in the task's state, so an edit mid-task cannot change a running task. Give the script a command that prints each resolved value and the layer it came from.

## Versioning
- The skill specification has no version field and hosts do not read `metadata.version`; keep it there for your own tooling. For a plugin, the version in the manifest is the one that counts.
- Strict SemVer. Major: rename, trigger-scope change, removed script or flag, config schema break. Minor: new optional config or reference, deprecation. Patch: wording fixes that pass evals. Never mutate a release; deprecate in a minor, remove in a major.
- Hosts detect an update in different ways: some keep users on the old copy until the version string changes, some reject a version that is not SemVer, some follow the commit when no version is set. → Always set strict SemVer and bump it on every release. A plain skill holds it in `metadata.version` only. A plugin holds the same string in every manifest and in `metadata.version`; change them together.
- Pin installs to a tag, a commit SHA or a content hash. Tag every release (`<name>-v<version>`). For stable and latest channels, publish two marketplaces at different refs.
- Release gate, in this order, using the host's own tooling where it exists: validate the manifest and skill → run the evals on a pinned model against a pass threshold → tag.

## Security & trust
- Published studies of public skill collections found a large share with flaws, some of them malicious, mostly through prompt injection; skills with scripts were vulnerable more often. Raw scanner rates overstate the problem, because many flags disappear once the repository context is read (studies in `references/sources.md`).
- A tool pre-approval field usually pre-approves and does not restrict. Restrict with deny rules. Scope a pre-approval to one script path, never to the whole shell.
- Plugin hooks, background servers and bundled executables usually run outside any sandbox with the user's full permissions, and auto-update can change code that was reviewed. A human reviews the hook config, the MCP config and every executable before approval.
- Side-effecting skills (deploy, send, commit) are user-invoked only on every target host (`references/decide.md`, Side-effect gating).
- Gate project skills on folder trust. Pin SHAs. Watch for repo hijacking, hidden-character smuggling, and fake "prerequisite installer" lures.
- CI scan: run a skill scanner with its LLM analysis on, since rules alone catch little. Fail the build at high severity for your own skills. No findings ≠ no risk.
- OWASP LLM risks that apply: prompt injection, supply chain, excessive agency. Treat MCP tool annotations (read-only, destructive) as untrusted unless the server is trusted.
