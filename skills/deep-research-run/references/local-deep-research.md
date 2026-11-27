# local-deep-research (LDR) over MCP

Read this only when the tools of the local-deep-research MCP server are present in the session. It maps the steps of SKILL.md to that engine.

Tools are written here as `local-deep-research:<tool>`. The part before the colon is the server name the host was configured with; it may differ on your host, so use the name you see in your tool list. The facts below come from the project's MCP guide and server source as of 2026-11-27. If your tool list shows different tools or arguments, the tool list wins.

## Tools

| Tool | Arguments | Returns | Typical time |
|---|---|---|---|
| `local-deep-research:get_configuration` | none | `config.llm` (`provider`, `model`, `temperature`) and `config.search` (`default_engine`, `default_strategy`, `iterations`, `questions_per_iteration`, `max_results`). No keys, URLs or context size. | instant |
| `local-deep-research:list_search_engines` | none | `engines`, each with `name`, `requires_api_key`, `is_local`. | instant |
| `local-deep-research:list_strategies` | none | `strategies`, each with a name and a description. | instant |
| `local-deep-research:search` | `query`, `engine` (required), `max_results` (1 to 100, default 10) | `result_count` and `results`, each with `title`, `link`, `snippet`. No model is used. | 5 to 30 seconds |
| `local-deep-research:quick_research` | `query`, optional `search_engine`, `strategy`, `iterations` (1 to 10), `questions_per_iteration` | `summary`, `findings`, `sources`, `formatted_findings`. No `research_id`. | 1 to 5 minutes |
| `local-deep-research:detailed_research` | the same, with `iterations` 1 to 20 | the same, plus `research_id` and `metadata`. | 5 to 15 minutes |
| `local-deep-research:generate_report` | `query`, optional `search_engine`, `searches_per_section` | `content`: a full Markdown report. | 10 to 30 minutes |
| `local-deep-research:analyze_documents` | `query`, `collection_name`, optional `max_results` | A summary of documents in a local document collection. | up to 2 minutes |

Every tool returns `status`: `success` or `error`. On an error it also returns `error` and `error_type`. The times are the project's own figures; a small local model can be slower.

## The check in step 3

1. Call `local-deep-research:get_configuration`. Note `config.llm.provider`, `config.llm.model` and `config.search.default_engine`.
2. Call `local-deep-research:search` with `engine` set to that default engine, `query` set to `Python programming language` and `max_results` set to 3.
3. The check passes when both return `status: success` and `result_count` is 1 or more.

If the second call returns `error_type: configuration_error`, the default engine is one that cannot run without a model. Repeat it once with an engine from `local-deep-research:list_search_engines` that has `requires_api_key: false`, for example `wikipedia`.

## Local or paid

- The model is local when `config.llm.provider` is `ollama`, `llamacpp` or `lmstudio` (in any letter case). Treat any other provider as paid.
- A search engine with `requires_api_key: true` needs a key and may bill per call. Treat it as paid unless the brief allows it. An engine with `requires_api_key: false` is not paid.
- Every query goes to each search engine you name, and every research prompt goes to the model provider. The "never" rule about secrets and private content applies to both.

## How the passes map

- Raw search (step 3, default route): `local-deep-research:search`, one call per engine. Take engine names from `local-deep-research:list_search_engines`. Use it like any other search tool; it costs no model time.
- Breadth pass: `local-deep-research:quick_research` with `query`, `strategy: source-based` and `iterations: 1`.
- Deeper pass: `local-deep-research:detailed_research` with `query`, `strategy: source-based` and `iterations: 2`.
- Strategy: always `source-based`, which the project labels as best for a small context window. The default in force is in `config.search.default_strategy` (`langgraph-agent` unless the owner changed it); do not rely on it. Use another strategy only when the brief names it, and then take the exact name from `local-deep-research:list_strategies`.
- These arguments apply to the one call only and are not saved, so passing them does not change the engine's configuration.
- `local-deep-research:generate_report`: only when the brief asks for a full report.
- `local-deep-research:analyze_documents`: only when the brief names a document collection. It does not read earlier research.

## Time, with numbers

Plan with the upper figure of each range in the table above.

| Call | Plan for | Long (over 5 minutes)? | Fits the default 15 minutes for one pass? |
|---|---|---|---|
| `local-deep-research:quick_research`, `iterations: 1` | 5 minutes | No. On a local model with unpaid search engines it needs no agreement. | Yes |
| `local-deep-research:detailed_research`, `iterations: 2` | 15 minutes | Yes. It needs the brief's allowance or a yes. | Yes, exactly |
| `local-deep-research:generate_report` | 30 minutes | Yes. | No. Only when the brief gives a limit of 30 minutes or more for the pass. |

With no limit in the brief, the core allows 15 minutes for one pass and two passes with a retry counting as one. It sets no limit on the total time. That gives:

- Breadth and deeper pass both return: 5 + 15 = 20 minutes. Both passes are used.
- Breadth returns, the deeper pass is cut off at 15 minutes: 20 minutes and both passes are used. No retry and no wait: close the open points with search and fetch.
- Breadth is cut off after N minutes: wait N minutes (see below), then retry once, smaller. Cut off at 1 minute: 1 + 1 + 5 = 7 minutes. Cut off at 15 minutes: 15 + 15 + 5 = 35 minutes. The retry is the second pass, so there is no deeper pass.
- A brief that gives 20 minutes for the whole item: keep about 7 for searches and step 4. That leaves 13: one breadth pass, and no deeper pass.

## Ids and late results

- `local-deep-research:detailed_research` returns a `research_id`; `local-deep-research:quick_research` returns none. Write the id under `## Passes`.
- No tool takes a `research_id`, and there is no status tool. Every call is synchronous: a result exists only in the reply to the call. So a call that the host cuts off cannot be collected later. Skip the "ask for it once" step and go to the smaller retry, if a pass and the time are left.
- Whether the server keeps working on a call the host has cut off is not known. Assume it does: on a local model, wait as long as the cut-off call had run before you start the smaller retry. The wait counts as time used. `local-deep-research:search` uses no model and can run meanwhile.

## Gotchas

- `local-deep-research:search` takes `engine`. The research tools take `search_engine`. Using the wrong one is a validation error.
- An unknown engine or strategy name returns `error_type: validation_error`, and the message lists the valid names. Use one of those; do not guess a second time.
- Error messages are short on purpose (`... failed (timeout). Check server logs.`). The detail is in the server's own log, which you cannot read. Quote the message and the `error_type` under `## Failures`.
- `error_type: policy_denied` means the engine's own outbound-traffic policy blocked the call. Do not try another way round it; report it.
- The other error types are `auth_error`, `service_unavailable`, `timeout`, `rate_limit`, `connection_error`, `model_not_found`, `configuration_error` and `unknown`. For `auth_error`, `model_not_found` and `configuration_error` a retry will not help: the check has failed.
