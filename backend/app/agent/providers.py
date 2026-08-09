"""LLM provider registry.

One place decides which chat model the agent talks to. Pick with the
LLM_PROVIDER env var (default: ollama). Each provider is a small builder
function registered below -- adding a new one means writing one function
and sticking @register("name") on it. Nothing else in the codebase knows
or cares which provider is active.

The heavier SDKs (langchain-anthropic, langchain-openai) are imported lazily
so the default install stays lean. If you select a provider whose package
isn't installed, you get told exactly what to pip install.
"""
from __future__ import annotations

import os
from collections.abc import Callable
from typing import Any

from app.config import settings


class ProviderError(RuntimeError):
    """The model backend is unreachable, misconfigured, or refused us.

    Raised instead of letting httpx/SDK errors bubble up, so the API layer can
    hand the user something readable ("is Ollama running?") rather than a
    stack trace.
    """


_REGISTRY: dict[str, Callable[[str], object]] = {}

# What each provider runs if LLM_MODEL isn't set. Model names age fast --
# override via env rather than treating these as gospel.
DEFAULT_MODELS = {
    "ollama": None,  # falls back to OLLAMA_MODEL (qwen2.5)
    "anthropic": "claude-sonnet-4-6",
    "openai": "gpt-4o-mini",
}


def register(name: str):
    def wrap(builder: Callable[[str], object]):
        _REGISTRY[name] = builder
        return builder
    return wrap


def available() -> list[str]:
    return sorted(_REGISTRY)


def active_provider() -> str:
    return settings.llm_provider.strip().lower()


# Per-provider env var for the model name. The API key and base URL already
# fall back to these, so people reasonably assume the model does too and set
# ANTHROPIC_MODEL expecting it to work. It silently did nothing before.
_MODEL_ENV_VARS = {
    "anthropic": "ANTHROPIC_MODEL",
    "openai": "OPENAI_MODEL",
    "ollama": "OLLAMA_MODEL",
}


def active_model() -> str:
    """Which model name gets sent to the provider.

    Order: LLM_MODEL wins, then the provider-specific env var, then the
    built-in default for that provider.
    """
    if settings.llm_model:
        return settings.llm_model

    provider = active_provider()
    from_env = os.environ.get(_MODEL_ENV_VARS.get(provider, ""))
    if from_env and from_env.strip():
        return from_env.strip()

    fallback = DEFAULT_MODELS.get(provider)
    return fallback or settings.ollama_model


def build_chat_model():
    """Construct the chat model for the configured provider."""
    name = active_provider()
    if name not in _REGISTRY:
        raise ProviderError(
            f"Unknown LLM_PROVIDER '{name}'. Valid options: {', '.join(available())}."
        )
    return _REGISTRY[name](active_model())


# ---------------------------------------------------------------- providers

@register("ollama")
def _ollama(model: str):
    from langchain_ollama import ChatOllama

    kwargs: dict[str, Any] = {
        "model": model,
        "base_url": settings.ollama_base_url,
        "num_predict": settings.llm_max_tokens,
        "client_kwargs": {"timeout": settings.llm_request_timeout},
    }
    if settings.llm_temperature is not None:
        kwargs["temperature"] = settings.llm_temperature
    return ChatOllama(**kwargs)


@register("anthropic")
def _anthropic(model: str):
    try:
        from langchain_anthropic import ChatAnthropic
    except ImportError as exc:
        raise ProviderError(
            "LLM_PROVIDER=anthropic needs the langchain-anthropic package: "
            "pip install langchain-anthropic"
        ) from exc

    import os

    key = settings.anthropic_api_key or os.environ.get("ANTHROPIC_API_KEY")
    if not key:
        raise ProviderError(
            "LLM_PROVIDER=anthropic but no key found. Set ANTHROPIC_API_KEY."
        )
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": key,
        "timeout": settings.llm_request_timeout,
        "max_tokens": settings.llm_max_tokens,
    }
    # Some models behind a gateway reject temperature outright. Blank
    # LLM_TEMPERATURE leaves it out of the request rather than sending a
    # value the model will refuse.
    if settings.llm_temperature is not None:
        kwargs["temperature"] = settings.llm_temperature
    # Only pass base_url when there's actually a value. ChatAnthropic resolves
    # its own default (the real Anthropic API) when the kwarg is absent, but
    # passing base_url=None explicitly overrides that resolution and leaves the
    # client with nowhere to send requests -- found that the hard way while
    # wiring this up.
    base_url = settings.anthropic_base_url or os.environ.get("ANTHROPIC_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    return ChatAnthropic(**kwargs)


@register("openai")
def _openai(model: str):
    try:
        from langchain_openai import ChatOpenAI
    except ImportError as exc:
        raise ProviderError(
            "LLM_PROVIDER=openai needs the langchain-openai package: "
            "pip install langchain-openai"
        ) from exc

    import os

    key = settings.openai_api_key or os.environ.get("OPENAI_API_KEY")
    if not key:
        raise ProviderError("LLM_PROVIDER=openai but no key found. Set OPENAI_API_KEY.")
    kwargs: dict[str, Any] = {
        "model": model,
        "api_key": key,
        "timeout": settings.llm_request_timeout,
        # Without this the model decides for itself when to stop. Reasoning
        # models take that as an invitation and burn minutes thinking before
        # they write a single line of SQL.
        "max_tokens": settings.llm_max_tokens,
    }
    if settings.llm_temperature is not None:
        kwargs["temperature"] = settings.llm_temperature
    # Same rule as the anthropic builder: only pass base_url when it has a
    # value, so the client keeps its own default when it doesn't.
    base_url = settings.openai_base_url or os.environ.get("OPENAI_BASE_URL")
    if base_url:
        kwargs["base_url"] = base_url
    return ChatOpenAI(**kwargs)


# ------------------------------------------------------------ error triage

# Substrings that mean "the backend is down or misconfigured", not "the model
# gave a weird answer". Crude, but it only has to sort failures worth a friendly
# message from ones the caller may want to handle differently.
_OUTAGE_HINTS = (
    "connect", "connection", "timed out", "timeout", "refused",
    "unauthorized", "401", "403", "api key", "api_key", "authentication",
    "not found", "404", "pull", "rate limit", "429", "overloaded", "unavailable",
)

# The endpoint answered, and it said no. These are settings problems: a
# parameter the model won't accept, a model name it doesn't recognise. Worth
# separating out, because retrying or quietly falling back just wastes calls --
# every subsequent one fails the same way. Better to say so on the first.
_REJECTED_HINTS = (
    "invalid_request", "invalid request", "400", "unsupported", "deprecated",
    "unrecognized", "unexpected keyword", "not permitted", "unprocessable", "422",
)


def looks_rejected(exc: Exception) -> bool:
    return any(hint in repr(exc).lower() for hint in _REJECTED_HINTS)


def looks_like_outage(exc: Exception) -> bool:
    text = repr(exc).lower()
    return any(hint in text for hint in _OUTAGE_HINTS)


def should_surface(exc: Exception) -> bool:
    """True when the caller should stop rather than fall back to a heuristic."""
    return looks_like_outage(exc) or looks_rejected(exc)


def outage_message(exc: Exception) -> str:
    name, model = active_provider(), active_model()

    text = repr(exc)
    if "MODEL_NOT_FOUND" in text or "model_not_found" in text.lower():
        return (
            f"{name} has no model called '{model}'. Gateways often use their own "
            "naming (a version suffix like '@default', for instance), so a name that "
            "works elsewhere may not work here. Run `python list_models.py` from the "
            "backend folder to see exactly what this endpoint serves, then set "
            f"LLM_MODEL to one of those. [{exc}]"
        )

    if looks_rejected(exc):
        hint = (
            f"{name} rejected the request for model '{model}'. This is usually a "
            "settings problem rather than an outage. If the message mentions "
            "temperature, set LLM_TEMPERATURE= (blank) in your .env to stop "
            "sending it. If it mentions the model, check LLM_MODEL matches a "
            "name this endpoint serves."
        )
        return f"{hint} [{exc}]"

    if name == "ollama":
        hint = (
            f"Is Ollama running at {settings.ollama_base_url}, and is the model pulled "
            f"(`ollama pull {model}`)?"
        )
    else:
        hint = "Check the API key, model name and base URL for this provider."
    return f"Could not get a response from {name} ({model}). {hint} [{exc}]"