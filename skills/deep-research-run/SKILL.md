---
name: deep-research-run
description: "Researches one question with the local-deep-research (LDR) engine: picks the cheapest tool, runs a breadth pass and a depth pass, checks claims against primary sources and lists open questions. Use for an atomic-decompose research item, or a question that needs multi-hop synthesis, a landscape survey or a comparison. Not for one fact, a codebase question or library docs."
license: MIT
metadata:
  version: 0.1.0
---

# Deep research run

You are executing ONE research item. Your output is `results/<id>.md` (or
the path given in the brief). The item's `check` criteria are the contract:
meet them, not more. You have no memory between items — everything the next
item needs must be in the result file.

Needs the local-deep-research MCP server (the "engine" below). An
atomic-decompose plan uses this skill by naming it in a research item's
`skill` field.

## Step 1 — Check the research configuration

Before any research pass, verify the research engine is configured correctly.
The engine reads environment variables — they may not be set.

1. Run the engine's `list_search_engines` and `get_configuration` tools to
   confirm it is responding and can search.
2. If the engine is not responding, report the error and stop.
3. If a search returns zero results, check `get_configuration` for the SearXNG
   instance URL — it commonly points at the wrong port (e.g. `localhost:8080`
   instead of the SearXNG service port). Try the correct URL and re-run.
   If the engine still returns zero results, report the error and stop.

`references/config-guide.md` lists the environment variables the engine
needs, with example values. The real values differ per host and per model:
take them from `get_configuration`, and do not hard-code them.

## Step 2 — Route the question (before any research pass)

Pick the cheapest tool that can answer it. Do not default to the research
engine.

| Question type | Cheaper tool |
|---|---|
| "What does this codebase do / where is X defined" | Codebase query tools — no web at all |
| Current API/spec/docs of a known library | Structured documentation tool (version-aware) |
| One fact, one date, one version, a named page | Web search + read the full page |
| Raw search results to verify a claim | Engine's raw search tool (no LLM pass) |
| Multi-hop synthesis: comparisons, ecosystems, "what is best practice", landscape surveys | Research engine (quick_research / detailed_research) |

A research item usually needs one route for its main question plus `search`
for verification. If the item depends on a previous research item, read its
result file first and check whether its `research_id` already covers your
question — if so, use the engine's document analysis instead of re-searching.

**Source diversity is mandatory.** No single source is sufficient for any
research item. Use at least 3 distinct source domains. For technical
questions: GitHub repos, official docs, community blogs. For other
questions: the primary data or official body, then independent commentary.

## Step 3 — Run the research pass (cost budget is mandatory)

Every research pass runs its own LLM. On a local model it queues on the
same hardware as the main session. **Only one research call at a time.**
Never run parallel research passes.

**Strategy selection:**
- **Source-based** — best for depth with small context windows; prompts are
  capped by settings.
- **Focused-iteration** — iterative deepening on specific sub-questions.
- **Topic-organization** — clusters findings by topic.
- **Langgraph-agent** — multi-agent approach (highest cost).

Valid strategy names come from the engine's `AVAILABLE_STRATEGIES`. If you
get a validation error on the strategy name, use `source-based`.

**Pass pattern (use direct MCP tool calls, never inside a timed wrapper):**
1. **Breadth pass:** `search` with 2–3 engines (e.g. Wikipedia + searxng +
   arxiv), then `quick_research` if breadth is insufficient. Note which
   sub-questions were generated — they are exploration signal for future items.
2. **Depth pass:** ONE detailed research on the strongest thread.
   Cap at `search_depth: 2` unless the item is explicitly a full-report.
3. **Budget stop:** if the item's `check` is satisfied after the breadth
   pass, stop. Depth is for the thread the `check` demands, not for
   curiosity.

If any engine tool fails, quote the error verbatim and log it in the
result under `## Failures`. Never invent results.

## Step 4 — Verify before quoting

Every claim you write into the result must be tied to a URL you actually
saw in search results. Read the source page (or the primary repo/docs) for
every claim the item's `check` rests on. Tag each claim with how far you
verified it:

- **High** — confirmed by reading the primary source page directly.
- **Medium** — stated by LDR synthesis and corroborated by at least one
  other independent source, but you did not read the primary page.
- **Low** — only from synthesis with no corroboration, or from a source you
  suspect is unreliable. These go under `## Unverified` with a one-line
  reason, never under `## Answers`.

## Step 5 — Write the result file

**Before writing, check every box:**

- [ ] Every claim in `## Answers` has `Confidence: high | medium. Source: <url>`
- [ ] `## Unverified` lists every low-confidence claim with a reason
- [ ] `## Failures` logs every engine/tool error (omit if none)
- [ ] **Source diversity:** at least 3 distinct source domains
- [ ] **Named entities:** the specific name of each thing, not a generic label
- [ ] **Dimensions:** if primary pages have significant sections beyond the item's
  check, add them as sub-sections under `## Answers`

### Result format

```markdown
# <item id> — <question>
Status: done | partial | replant
<!-- done: every `check` point is met. partial: some are; say which are not.
     replant: the question as asked cannot be answered; `Open threads` holds
     the questions to plan instead. -->

## <Primary dimension requested by the check>
- Claim with named entity, one line. Confidence: high. Source: <url>

## <Secondary dimensions>
- Sub-section headers with specific details. Each line:
  Confidence: high | medium. Source: <url>

## Failures (omit if none)
- Tool name, error verbatim

## Open threads
- Follow-up question the engine generated (or one you derived) — phrased as
  an answerable research question, with a one-line note on why it matters.
- ...

## Unverified (omit if none)
- Claim, one line. Confidence: low. Source: <url>. Reason: why it could not be verified.

## Research ids
- Engine research_id of each pass (for reuse in later items)
```

`Open threads` is mandatory, even when empty. These are the fuel for the
next planning pass: the planner turns them into candidate research items.

## Error recovery

If an engine call returns an unexpected error:
1. Quote the full error message in `## Failures`.
2. Try a fallback strategy (e.g. switch search engine, reduce search depth).
3. If the fallback also fails, report the error and stop — do not guess.

If the engine times out or the call is interrupted:
1. Save any partial output you have to `results/<id>-partial.md`.
2. On resume, read the partial file and continue from where you left off.

The result file is the only checkpoint. Inside a task, write nothing else
to the task folder and finish with the `done` command the brief gives.

## Direct invocation (no task item)

If invoked outside a task framework on a standalone question: do Step 2,
run one breadth pass, add one depth pass only if the breadth pass shows a
strong thread, verify the claims, and answer in bullets with sources. Skip
the result-file format.

## Gotchas

- The engine's `search` tool uses argument `engine` — NOT `search_engine`.
  Using `search_engine` raises a validation error.
- The engine's `quick_research` returns NO `research_id` — you cannot
  reuse its output via `analyze_documents`. Save the raw pass output for
  later reference.
- The engine's MCP client has a timeout (often 60s). Long passes (depth
  takes minutes to hours) must be called as direct tool calls, not from
  within timed execution environments.
- Engine strategy names in docstrings may differ from actual valid names.
  If you get a ValidationError, fall back to `source-based`.
