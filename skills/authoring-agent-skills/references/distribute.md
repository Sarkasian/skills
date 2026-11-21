Read this only for a skill that ships through a marketplace or to other teams, needs usage telemetry, or is being renamed or retired.

Every setting name, event name and command in this area is host-specific and changes often, so none is stored here. Look each one up as `references/sources.md` describes.

## Observability / telemetry
- What to measure, per skill and version: was it triggered, and by whom (user, model, another skill); did its scripts succeed; tokens and cost; skills that never run.
- Enable host telemetry from managed (administrator) settings, because user-level settings can switch signals off.
- Look up, for each target host: the event that records a skill activation (some hosts have none, and you filter tool-call events); whether skill and plugin names are redacted for anything not from the official marketplace; whether traces reach script subprocesses.
- OpenTelemetry has GenAI conventions for agent spans, with attributes for the skill's name and source. Check the current conventions before naming attributes; add your own attribute for the skill version if they have none.
- Privacy defaults differ by host: some log prompts, tool arguments or tool output by default. Check each, and drop what you may not keep in the collector.
- Script logs: data on stdout, diagnostics on stderr; optionally append one JSON line `{skill, version, event, exit_code, ms}` per run to stderr or to the plugin data directory.
- Close the loop: failing production trace → eval case → fix → regression suite.
- Before shipping, check the cost of the skill with the host's own tools: always-on tokens (name + description) and per-invocation tokens.

## Deprecation / end of life
- Do not expect a host to have a "deprecated" state for a plugin or skill. Look up what each target host's marketplace offers: a rename map, a migration pointer, hiding, or removal.
- Redirect skill (convention, works everywhere): keep the old name for 1–2 releases, hidden from the user's menu where the host allows it, description starting `DEPRECATED (removal <date>). Use <new>`, body = "load and follow `<new>`; do not perform the task here". Template: `assets/redirect-skill.md`.
- Deprecate in a minor release, remove in a major; announce the removal date in the description + CHANGELOG.
- State: keep it in the plugin data directory and migrate it on first run of the new version. Check whether uninstalling deletes it.
- Retire using data: the host's usage reports and the telemetry above.

## Distribution & governance
- Internal marketplace: a manifest file in a private repository listing each plugin with a pinned ref or SHA. The file's name and location differ by host, and one host may read another's file. Look both up.
- Channels: do not expect a host to have them → two marketplaces (`stable`, `latest`) at different refs.
- Lockdown: managed settings can restrict installs to an allowlist of marketplaces, force-install or block plugins, and disable side-loading. Look up the keys per host.
- Org provisioning: enterprise plans can install plugins by default, make them available or required, and vary that per group. Check each host's admin documentation, including how a new version reaches users.
- Review workflow: CODEOWNERS on `plugins/*/`, protected tags, and CI running validate → skill scanner → evals against a threshold → tag. A human reads the hook config, the MCP config and every executable before approving.
- Ownership: the manifest's owner/author field; SKILL.md `metadata: {owner, version, support-channel}` (hosts ignore it, so it's safe for your own tooling). Use a team or role name, not a person's.
- Integrity: most hosts pin a git ref only and do not verify content. Check whether the target host verifies a content hash, and use it where it does.
