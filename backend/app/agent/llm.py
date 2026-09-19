"""Thin wrapper the rest of the code calls for model access.

Two entry points: complete() for plain text, structured() for a validated
pydantic object. Which provider actually answers is providers.py's problem;
callers never see provider-specific types or errors.
"""
from __future__ import annotations

from langchain_core.messages import HumanMessage, SystemMessage

from app.agent import providers
from app.agent.providers import ProviderError

# One client per (provider, model) pair. Keyed so tests can flip settings
# and get a fresh client instead of a stale cached one.
_CACHE: dict[tuple[str, str], object] = {}


def get_llm():
    key = (providers.active_provider(), providers.active_model())
    if key not in _CACHE:
        _CACHE[key] = providers.build_chat_model()
    return _CACHE[key]


def reset_cache() -> None:
    _CACHE.clear()


def complete(system: str, user: str) -> str:
    """Text in, text out. Transport/auth failures come back as ProviderError."""
    try:
        response = get_llm().invoke(
            [SystemMessage(content=system), HumanMessage(content=user)]
        )
    except ProviderError:
        raise
    except Exception as exc:
        # Anything that smells like an outage gets the friendly treatment.
        # Everything else is a bug worth seeing in full.
        if providers.should_surface(exc):
            raise ProviderError(providers.outage_message(exc)) from exc
        raise
    content = response.content
    return content if isinstance(content, str) else str(content)


def structured(system: str, user: str, schema):
    """Ask for a validated instance of `schema` (a pydantic model).

    Returns None when the model simply can't do structured output -- the
    planner has a heuristic fallback for that. Outages still raise, because
    no fallback fixes an unreachable backend.
    """
    try:
        # method="function_calling" routes this through the tools/tool_choice
        # parameters instead of response_format. Needed for DeepSeek, whose
        # API rejects response_format={"type": "json_schema"} outright ("This
        # response_format type is unavailable now") -- that is LangChain's
        # default for with_structured_output() when it is left unset. Function
        # calling is what DeepSeek's own docs point to instead, and ChatOllama
        # supports it for any tool-capable model (the qwen2.5 default
        # included), so it's the safer choice everywhere, not a DeepSeek-only
        # carve-out.
        model = get_llm().with_structured_output(schema, method="function_calling")
        return model.invoke([SystemMessage(content=system), HumanMessage(content=user)])
    except ProviderError:
        raise
    except Exception as exc:
        if providers.should_surface(exc):
            # A refused request will refuse again on the next call, so falling
            # back to the heuristic here would just burn steps before failing.
            raise ProviderError(providers.outage_message(exc)) from exc
        return None