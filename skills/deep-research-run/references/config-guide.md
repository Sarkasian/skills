# Configuration guide

This file is loaded ONLY when the executor starts — it is one level deep.
It contains the engine's required environment variables and their values.

> **Per-host:** These values are examples. Each machine may differ. Create a
> `machine-local/config-guide.md` next to this file with your actual values,
> and point the skill at it instead.

## Required environment variables

| Variable | Example value | Purpose |
|---|---|---|
| `LDR_LLM_PROVIDER` | `llamacpp` | LLM backend |
| `LDR_LLM_MODEL` | `<your model name>` | Model to use |
| `LDR_LLM_LLAMACPP_URL` | `http://127.0.0.1:8080/v1` | Engine URL |
| `LDR_LLM_LOCAL_CONTEXT_WINDOW_SIZE` | `65536` | Must match model context (default 20480 is too small) |
| `LDR_LLM_MAX_TOKENS` | `16384` | Completion length cap |
| `LDR_SEARCH_ENGINE_WEB_SEARXNG_DEFAULT_PARAMS_INSTANCE_URL` | `http://localhost:8081` | SearXNG port |

## Common pitfalls

- `LOCAL_CONTEXT_WINDOW_SIZE` defaults to 20480, which clamps `max_tokens`
  to ~16384. With prompt overhead, the usable depth budget is only ~4096
  tokens — depth passes overflow. Set to the model's real context.
- SearXNG instance URL commonly points at `localhost:8080` which is the
  llama-server, not SearXNG. Find the actual SearXNG port (Docker
  `docker ps`, or your startup script).
- If `get_configuration` shows a different URL than what you set, the env var
  was not picked up — restart the MCP server.

## Verification

Before starting, confirm the env is set:
```bash
echo $LDR_LLM_PROVIDER
echo $LDR_LLM_LLAMACPP_URL
```

If any variable is empty or wrong, the research engine will fail silently.
