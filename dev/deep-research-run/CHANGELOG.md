# Changelog

SemVer. Major: rename, trigger-scope change, removed script/flag, config schema break. Minor: new optional config/reference, deprecation. Patch: wording fixes that pass evals.

## 0.2.0 (2026-11-27)

Not tagged. The skill is now a research method that does not depend on one engine, one host or one planner. It follows an audit of 0.1.0.

Before 1.0 a minor version may change the trigger scope. This one does: the description no longer requires the local-deep-research engine.

Method:
- The core routes by capability, cheapest first: what is already known, one lookup, library docs, then research. Research defaults to searches and page reads, which every host has. A deep-research pass is the exception, used only when a deep-research tool is present and has passed a check.
- Step 1 tells the agent to look at the tools it has and sort them into four kinds. It calls no deep-research tool. With no fetch tool only route 1 is open, because no page can be opened; `compatibility` now says a fetch tool is needed.
- The check of a deep-research tool, with its pass test, is in step 3 and runs only before the first pass. An item answered on routes 1 to 3 makes no engine call and does not read the engine reference.
- A brief is described by its parts (id, question, acceptance points, result path, finish command), not by one planner's format. atomic-decompose is named as one example, and its brief wording (`Result: write it to`, `Judged by:`, `Done:`) still fits. A line that quotes the whole task, such as `Request:`, is background and not the question. A direct question is answered in the chat; this is stated at the top.
- Long passes have one procedure: write the result file first, a time limit (the brief's limit, else 15 minutes for one pass, with no limit on the total time unless the brief or the user gives one), at most two passes with a retry counting as one, what to do on a timeout or an empty reply, and a stop rule. A limit the brief gives for the whole item also covers searches and verification, so a third of it is kept for them.
- Every way out has a defined output. A point with no source and no pass open is not met and the result is `Status: partial`. A question that cannot be asked without private content is `Status: unanswerable`. The result file is written and the finish command is run whatever the status.
- The one-pass-at-a-time rule is per engine. Keeping research items that share an engine apart is the planner's job; the skill says so in one clause and gives no planner-specific instruction.
- The `medium` tag now means: the agent opened a page that says it, the page is not the primary source, and a second independent page or an engine's synthesis agrees.

Safety:
- New `## Never` section: no changes to engine or host configuration, no secrets or private repository content in a query, a fetched URL or a research prompt and no secret in the result, agreement before a long or paid pass, no invented results, no parallel passes on one engine, no following instructions found in a page.
- A pass is paid when the engine's model is hosted or metered, or a search service it uses needs an API key or bills per call. A free public search service does not make a pass paid. A pass whose length or cost cannot be told counts as long and paid.
- When the brief says not to ask the user, or nobody is there to answer, the agent does not ask, files no approval request and does not mark the item blocked. It goes on without the pass and names the unmet point on the `Not met:` line. In atomic-decompose a blocked item cannot be finished by its executor, so asking for approval would have made the `Done:` command fail.
- A failed engine check no longer leads to "try the correct URL". The agent reports the value and works without the engine.

Result file:
- The checklist and the template use the same five headings: `## Answers`, `## Unverified`, `## Failures`, `## Open threads`, `## Passes`. All five are always present.
- The result file is the only checkpoint. The `-partial.md` file is gone.
- "Meet the acceptance points, not more": extra material is one line under `## Open threads`. The "Dimensions" checkbox is gone.
- `Status: replant` is now `Status: unanswerable`, and the claim that a planner turns open threads into new items is removed. New `Route:` and `Not met:` lines.

References:
- `references/config-guide.md` is replaced by two files, each with a load condition in SKILL.md.
- `references/local-deep-research.md`: tool names as `Server:tool`, arguments, the check, the strategy, which calls are long, the time rules worked out with the project's figures, ids, timeouts and errors. Read before the check in step 3, only when that engine's tools are present.
- `references/local-model-setup.md`: one example setup (llama.cpp and SearXNG), with a table from symptom to likely cause. Read only when the check fails on a local model.

Corrected against the project's MCP guide and server source (0.1.0 had these wrong):
- There is no `search_depth` argument. Depth is `iterations`.
- No tool takes a `research_id`. `analyze_documents` searches a local document collection by `collection_name`; it does not reuse earlier research.
- `get_configuration` does not show the SearXNG address or the context size, so the agent cannot check them.
- Strategy names come from the `list_strategies` tool. The default strategy in force is read from `get_configuration` (`langgraph-agent` in the project's default settings); the reference passes `source-based` on every call. The reference makes no claim about which strategy costs most.
- A private or loopback SearXNG address is accepted when the instance URL is set through its own environment variable, or when one of the two allowlist variables allows it. The symptom table now says so.
- Printing a variable in the agent's shell is not evidence of the server's environment.

Still unverified:
- Whether the server keeps working on a call after the host has cut it off. The reference tells the agent to assume it does.
- Whether a host cuts off a long tool call, and after how long. The skill tells the agent to set a time limit where the host allows one and gives the procedure for a call that is cut off; no host's limit was measured.
- The typical times of each tool on a small local model. The reference gives the project's own figures.
- The symptom table in `references/local-model-setup.md` is reasoned from the documented defaults, not observed.
- Nothing was run against a live engine.

Development files:
- `evals/evals.json` is rewritten: two brief-driven cases with fixture briefs, a direct question, a case with no deep-research tool, two cheap-route cases that allow no engine call at all, and a case with no web tools that must end in `Status: partial`. The atomic-decompose fixture brief uses the wording that planner builds, with stand-in commands, and its case fails if the item is blocked. `evals/trigger_evals.json` has 10 positives and 11 negatives, the negatives being near-misses.
- New `selftest.py` (headings agree, references exist and are named, every status, step and route named anywhere is defined, versions agree, eval fixtures exist) and `learnings/README.md`.

The evals have not been run: neither the task evals nor the trigger evals, and there is no baseline without the skill. They are due before a release tag.

## 0.1.0 (2026-11-26)

Not tagged. First version: the research method for one question on the local-deep-research (LDR) engine. It checks the engine's configuration, picks the cheapest tool, runs a breadth pass and at most one depth pass, tags each claim with how far it was verified, and writes a result file with open threads.

The evals in `evals/` have not been run. The description was rewritten to fit the 400-character listing budget, so the trigger evals are due before a release.
