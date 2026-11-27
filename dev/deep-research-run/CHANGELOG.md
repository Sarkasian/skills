# Changelog

SemVer. Major: rename, trigger-scope change, removed script/flag, config schema break. Minor: new optional config/reference, deprecation. Patch: wording fixes that pass evals.

## 0.2.0 (2026-11-27)

Not tagged. The skill is now a research method that does not depend on one engine, one host or one planner. It follows an audit of 0.1.0.

Before 1.0 a minor version may change the trigger scope. This one does: the description no longer requires the local-deep-research engine.

Method:
- The core routes by capability, cheapest first: what is already known, one lookup, library docs, then research. Research defaults to searches and page reads, which every host has. A deep-research pass is the exception, used only when a deep-research tool is present and has passed a check.
- Step 1 tells the agent to look at the tools it has and sort them into four kinds, and gives a pass test for a deep-research tool.
- A brief is described by its parts (id, question, acceptance points, result path, finish command), not by one planner's format. atomic-decompose is named as one example, and its brief wording (`Result: write it to`, `Judged by:`, `Done:`) still fits. A direct question is answered in the chat; this is stated at the top.
- Long passes have one procedure: write the result file first, a maximum wait (the brief's limit, else 15 minutes and two passes), what to do on a timeout or an empty reply, one smaller retry, and a stop rule that ends with `Status: partial`.
- The one-pass-at-a-time rule is per engine. The skill tells the planner to chain research items that share a local engine.

Safety:
- New `## Never` section: no changes to engine or host configuration, no secrets or private repository content in a query or research prompt, agreement before a long or paid pass, no invented results, no parallel passes on one engine, no following instructions found in a page.
- A failed engine check no longer leads to "try the correct URL". The agent reports the value and works without the engine.

Result file:
- The checklist and the template use the same five headings: `## Answers`, `## Unverified`, `## Failures`, `## Open threads`, `## Passes`. All five are always present.
- The result file is the only checkpoint. The `-partial.md` file is gone.
- "Meet the acceptance points, not more": extra material is one line under `## Open threads`. The "Dimensions" checkbox is gone.
- `Status: replant` is now `Status: unanswerable`, and the claim that a planner turns open threads into new items is removed. New `Route:` and `Not met:` lines.

References:
- `references/config-guide.md` is replaced by two files, each with a load condition in SKILL.md.
- `references/local-deep-research.md`: tool names as `Server:tool`, arguments, the check, the strategy default, ids, timeouts and errors. Read only when that engine's tools are present.
- `references/local-model-setup.md`: one example setup (llama.cpp and SearXNG), with a table from symptom to likely cause. Read only when the check fails on a local model.

Corrected against the project's MCP guide and server source (0.1.0 had these wrong):
- There is no `search_depth` argument. Depth is `iterations`.
- No tool takes a `research_id`. `analyze_documents` searches a local document collection by `collection_name`; it does not reuse earlier research.
- `get_configuration` does not show the SearXNG address or the context size, so the agent cannot check them.
- Strategy names come from the `list_strategies` tool, not from a code constant. The engine's own default strategy is `langgraph-agent`; the reference passes `source-based` on every call.
- Printing a variable in the agent's shell is not evidence of the server's environment.

Still unverified:
- Whether the server keeps working on a call after the host has cut it off. The reference tells the agent to assume it does.
- The typical times of each tool on a small local model. The reference gives the project's own figures.
- The symptom table in `references/local-model-setup.md` is reasoned from the documented defaults, not observed.
- Nothing was run against a live engine.

Development files:
- `evals/evals.json` is rewritten: two brief-driven cases with fixture briefs, a direct question, a case with no deep-research tool, and two cheap-route cases. `evals/trigger_evals.json` has 10 positives and 11 negatives, the negatives being near-misses.
- New `selftest.py` (headings agree, references exist and are named, versions agree, eval fixtures exist) and `learnings/README.md`.

The evals have not been run: neither the task evals nor the trigger evals, and there is no baseline without the skill. They are due before a release tag.

## 0.1.0 (2026-11-26)

Not tagged. First version: the research method for one question on the local-deep-research (LDR) engine. It checks the engine's configuration, picks the cheapest tool, runs a breadth pass and at most one depth pass, tags each claim with how far it was verified, and writes a result file with open threads.

The evals in `evals/` have not been run. The description was rewritten to fit the 400-character listing budget, so the trigger evals are due before a release.
