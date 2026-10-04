# Models

Prism talks to a model through one small layer, so the provider is a setting rather than a code change. Code: `backend/app/agent/llm.py` and `backend/app/agent/providers.py`.

[![How Prism talks to a model](diagrams/model-providers.architecture.svg)](diagrams/model-providers.architecture.html)

## Providers

| `LLM_PROVIDER` | Talks to | Needs |
| --- | --- | --- |
| `ollama` (default) | A local [Ollama](https://ollama.com) server at `OLLAMA_BASE_URL` | A pulled, tool-capable model |
| `openai` | OpenAI, or any OpenAI-compatible API at `OPENAI_BASE_URL`: DeepSeek, Groq, vLLM, LM Studio, a company gateway | `OPENAI_API_KEY` |

Each provider is one builder function registered with `@register("name")`. Only the active provider's SDK is imported. The model has to support tool calling, because every structured call (decompose, plan, verify) uses forced function calling.

## Which model is used

1. `LLM_MODEL`, if set.
2. Otherwise `OPENAI_MODEL` or `OLLAMA_MODEL` for the active provider.
3. Otherwise the default: `qwen2.5` for Ollama, `gpt-4o-mini` for OpenAI.

`OLLAMA_MODEL` works from `backend/.env` or the environment. `OPENAI_MODEL` is only read from the real process environment, not from `backend/.env`, so set `LLM_MODEL` in `.env` instead. `/api/health` and the pill in the app header show the model actually in use.

## Request settings

| Setting | Effect |
| --- | --- |
| `LLM_TEMPERATURE` | Sent as `temperature`. Blank (or `none`, `off`, `unset`) leaves it out, for models that reject it |
| `LLM_TOP_P` | Sent as `top_p` to OpenAI-compatible APIs when set |
| `LLM_MAX_TOKENS` | Cap on each response (`max_tokens`, or `num_predict` for Ollama) |
| `LLM_REQUEST_TIMEOUT` | Seconds per call; one question makes several calls |
| `LLM_EXTRA_BODY` | Raw JSON merged into OpenAI-compatible requests, for provider-specific switches |

### DeepSeek

```bash
LLM_PROVIDER=openai
OPENAI_API_KEY=<YOUR_API_KEY>
OPENAI_BASE_URL=https://api.deepseek.com/v1
LLM_MODEL=deepseek-v4-flash
LLM_EXTRA_BODY={"thinking": {"type": "disabled"}}
```

`LLM_EXTRA_BODY` is required here. DeepSeek's V4 models think by default, and thinking mode rejects the forced tool choice the agent relies on (`400 Thinking mode does not support this tool_choice`). Blank does not mean non-thinking. Shapes differ between providers: NVIDIA NIM, for example, takes `{"chat_template_kwargs": {"thinking": true}}`.

## When a call fails

| What happened | What Prism does |
| --- | --- |
| Connection refused, timeout, 401/403, rate limit, unknown model | Raises `ProviderError`. The run ends with a readable message saying what to check, delivered in the normal final response rather than as a 500 |
| The endpoint rejected the request (400, 422, an unsupported parameter) | Same, with a hint about the setting to change (often `LLM_TEMPERATURE` or `LLM_MODEL`) |
| The model answered but gave no usable structured output | `structured()` returns nothing and the caller falls back: the planner to its rule, the decomposer to the whole question, the verifier to `ok` |

## Listing what an endpoint serves

Gateways often rename models (`gpt-4o-mini@default`, say), and a 404 doesn't tell you the right name. From `backend/` with the venv active:

```bash
python list_models.py
```

It reads the same settings as the app, asks the configured endpoint for its models, and prints them. It only reads; nothing is changed.

## Adding a provider

Write one builder in `providers.py`:

```python
@register("name")
def _name(model: str):
    from some_sdk import ChatModel   # import inside, so only the active SDK loads
    return ChatModel(model=model, timeout=settings.llm_request_timeout)
```

Add its default model to `DEFAULT_MODELS`, its model variable to `_MODEL_ENV_VARS`, and tests in `backend/tests/test_providers.py`. Then `LLM_PROVIDER=name` selects it.
