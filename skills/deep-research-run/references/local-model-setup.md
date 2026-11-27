# One example setup: LDR on a local llama.cpp model with SearXNG

Read this only when the step 3 check of the local-deep-research engine has failed and the engine runs on a local model. It is one person's setup, given as an example; other machines differ.

Use it to name the likely wrong value in your report. You change nothing: the person who owns the machine sets these values in the `env` block of the MCP server entry in their host's configuration, and restarts the server.

## What the agent can and cannot see

- The engine's `get_configuration` tool shows the provider, the model, the default search engine and the default strategy. If one of those is not what the brief or the user expects, the variable was not picked up by the server.
- It does not show URLs, ports or the context size. For those you can only report the symptom and the likely cause below, as "likely".
- Printing a variable in your own shell shows your shell's environment, not the server's. Do not use it as evidence.

## Variables

Names and defaults are from the project's configuration reference. The example values are from the one setup this file describes.

| Variable | Default | Example value | What it sets |
|---|---|---|---|
| `LDR_LLM_PROVIDER` | `ollama` | `llamacpp` | Model provider. |
| `LDR_LLM_MODEL` | none | `<model name>` | Model. |
| `LDR_LLM_LLAMACPP_URL` | `http://localhost:8080/v1` | `http://127.0.0.1:8080/v1` | Address of llama.cpp's `llama-server`, with `/v1`. |
| `LDR_LLM_LOCAL_CONTEXT_WINDOW_SIZE` | `20480` | `65536` | Context size for local models, in tokens. |
| `LDR_LLM_MAX_TOKENS` | `30000` | `16384` | Longest model reply. The engine caps it at 80% of the context size. |
| `LDR_SEARCH_ENGINE_WEB_SEARXNG_DEFAULT_PARAMS_INSTANCE_URL` | `http://localhost:8080` | `http://localhost:8081` | Address of SearXNG. |
| `LDR_SEARCH_PRIVATE_ENGINE_URL_ALLOWLIST` | none | `http://localhost:8081` | Local SearXNG addresses the engine is allowed to use. Not needed when the instance URL variable above is set. |

## Symptom, likely cause, what to report

| Symptom | Likely cause | Report |
|---|---|---|
| A `searxng` search returns no results or a connection error, while another engine such as `wikipedia` works. | The SearXNG instance URL variable is not set, so the address is the default, `http://localhost:8080`. The engine refuses a private or loopback SearXNG address unless the instance URL is set through its own variable, or `LDR_SEARCH_PRIVATE_ENGINE_URL_ALLOWLIST` or `LDR_SEARCH_ALLOW_PRIVATE_ENGINE_URLS` allows it. Or the variable is set to the wrong port: 8080 is also the default port of `llama-server`. | "SearXNG search fails; other engines work. Likely the SearXNG instance URL is unset or wrong. I did not change it." |
| Every search engine fails. | No network from the server, or the search service is down. | The error, word for word. |
| A research pass fails with `model_not_found` or `connection_error`, while `search` works. | The model server is not running, or `LDR_LLM_LLAMACPP_URL` or `LDR_LLM_MODEL` is wrong. | The provider and model that `get_configuration` shows, and the error. |
| A research pass returns a summary that stops mid-sentence or ignores most sources. | The context size is at its default, 20480 tokens, which also caps replies at 16384. | "Output looks truncated. Likely `LDR_LLM_LOCAL_CONTEXT_WINDOW_SIZE` is below the model's real context." |
| `get_configuration` shows a provider or model other than the one that was set. | The variable is not in the server's environment, or the server was not restarted. | The value shown and the value expected. |

## For the person, not the agent

The MCP server is installed with `pip install "local-deep-research[mcp]"` and started by the host as the command `ldr-mcp`. It runs on the same machine as the host and talks over standard input and output only. The agent does not install or start it.
