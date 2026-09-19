"""Provider selection, outage classification, and the graceful failure path."""
from __future__ import annotations

import pytest

from app import config
from app.agent import graph, llm, providers
from app.agent.providers import ProviderError


@pytest.fixture(autouse=True)
def fresh_llm_cache():
    llm.reset_cache()
    yield
    llm.reset_cache()


def test_registry_knows_the_built_in_providers():
    assert {"ollama", "openai"} <= set(providers.available())


def test_unknown_provider_fails_with_the_valid_options(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "aliens")
    with pytest.raises(ProviderError) as excinfo:
        providers.build_chat_model()
    message = str(excinfo.value)
    assert "aliens" in message and "ollama" in message


def test_model_resolution_order(monkeypatch):
    # explicit LLM_MODEL beats everything
    monkeypatch.setattr(config.settings, "llm_model", "my-model")
    assert providers.active_model() == "my-model"
    # otherwise the provider default; ollama falls back to OLLAMA_MODEL
    monkeypatch.setattr(config.settings, "llm_model", None)
    monkeypatch.setattr(config.settings, "llm_provider", "ollama")
    assert providers.active_model() == config.settings.ollama_model
    monkeypatch.setattr(config.settings, "llm_provider", "openai")
    assert providers.active_model() == providers.DEFAULT_MODELS["openai"]


def test_ollama_is_the_default_and_builds():
    assert providers.active_provider() == "ollama"
    assert type(providers.build_chat_model()).__name__ == "ChatOllama"


def test_openai_requires_a_key(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "openai")
    monkeypatch.setattr(config.settings, "openai_api_key", None)
    monkeypatch.delenv("OPENAI_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="OPENAI_API_KEY"):
        providers.build_chat_model()


def test_openai_builds_with_a_key(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "openai")
    monkeypatch.setattr(config.settings, "openai_api_key", "sk-test-not-real")
    assert type(providers.build_chat_model()).__name__ == "ChatOpenAI"


def test_cache_is_keyed_per_provider_and_model(monkeypatch):
    first = llm.get_llm()
    assert llm.get_llm() is first  # same key -> same client
    monkeypatch.setattr(config.settings, "llm_model", "qwen3")
    assert llm.get_llm() is not first  # new model -> new client


def test_outage_classifier():
    assert providers.looks_like_outage(ConnectionError("connection refused"))
    assert providers.looks_like_outage(RuntimeError("401 Unauthorized: bad api key"))
    assert not providers.looks_like_outage(ValueError("some parsing problem"))


class _DownClient:
    def invoke(self, *_args, **_kwargs):
        raise ConnectionError("connection refused on purpose")

    # llm.structured() passes method="function_calling". Without the parameter
    # here the call raises a TypeError whose "unexpected keyword argument"
    # wording matches the rejected-request heuristic, so the test would fail
    # quietly wrong instead of loudly wrong.
    def with_structured_output(self, _schema, method=None):
        return self


def test_complete_wraps_outages_in_provider_error(monkeypatch):
    monkeypatch.setattr("app.agent.llm.get_llm", lambda: _DownClient())
    with pytest.raises(ProviderError, match="Could not get a response"):
        llm.complete("system", "user")


def test_structured_raises_on_outage_but_none_on_bad_output(monkeypatch):
    monkeypatch.setattr("app.agent.llm.get_llm", lambda: _DownClient())
    with pytest.raises(ProviderError):
        llm.structured("system", "user", graph.NextStep)

    class Confused:
        def with_structured_output(self, _schema, method=None):
            return self

        def invoke(self, *_args, **_kwargs):
            raise ValueError("model produced garbage")

    monkeypatch.setattr("app.agent.llm.get_llm", lambda: Confused())
    assert llm.structured("system", "user", graph.NextStep) is None


def test_agent_degrades_politely_when_the_provider_is_down(monkeypatch, sales_session):
    def down(*_args, **_kwargs):
        raise ProviderError("Could not get a response from ollama (qwen2.5). Is it running?")

    monkeypatch.setattr("app.agent.llm.structured", down)
    monkeypatch.setattr("app.agent.llm.complete", down)

    state = graph.run("total revenue?", sales_session.session_id)
    assert state["error"] and "ollama" in state["error"]
    assert state["trace"][-1]["node"] == "error"

    events = list(graph.stream("total revenue?", sales_session.session_id))
    kinds = [kind for kind, _ in events]
    assert kinds == ["final"], "an outage should still end in a clean final event"
    assert events[0][1]["error"]


# ------------------------------------------------------------ output ceiling

# One question is several model calls in a row. Left unbounded, a reasoning
# model spends thousands of tokens thinking before it writes a line of SQL,
# and the run dies on the per-call timeout. Every provider gets a cap.

def test_openai_sends_a_max_tokens_ceiling(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "openai")
    monkeypatch.setattr(config.settings, "openai_api_key", "sk-test-not-real")
    assert providers.build_chat_model().max_tokens == config.settings.llm_max_tokens


def test_ollama_sends_a_max_tokens_ceiling(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "ollama")
    assert providers.build_chat_model().num_predict == config.settings.llm_max_tokens


# --------------------------------------------------------- omittable temperature

# Some hosted models return a 400 saying temperature is deprecated. No value
# satisfies them, so the setting has to be genuinely omittable.

def test_blank_temperature_means_omit_it():
    from app.config import Settings

    for blank in ("", "none", "off", " "):
        assert Settings(LLM_TEMPERATURE=blank).llm_temperature is None
    assert Settings(LLM_TEMPERATURE="0.7").llm_temperature == 0.7


def test_openai_leaves_temperature_unset_when_blank(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "openai")
    monkeypatch.setattr(config.settings, "openai_api_key", "sk-test-not-real")
    monkeypatch.setattr(config.settings, "llm_temperature", None)
    assert providers.build_chat_model().temperature is None


def test_ollama_leaves_temperature_unset_when_blank(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "ollama")
    monkeypatch.setattr(config.settings, "llm_temperature", None)
    assert providers.build_chat_model().temperature is None


# ------------------------------------------- a refused request is not an outage

def test_rejected_requests_are_recognised():
    rejected = RuntimeError(
        "Error code: 400 - {'type': 'error', 'error': {'type': 'invalid_request_error', "
        "'message': '`temperature` is deprecated for this model.'}}"
    )
    assert providers.looks_rejected(rejected)
    assert providers.should_surface(rejected)
    assert "LLM_TEMPERATURE" in providers.outage_message(rejected)


def test_a_refused_request_stops_instead_of_falling_back(monkeypatch):
    """Silently falling back would burn a step and then fail the same way."""

    class Refusing:
        def with_structured_output(self, _schema, method=None):
            return self

        def invoke(self, *_args, **_kwargs):
            raise RuntimeError("Error code: 400 - invalid_request_error: unsupported parameter")

    monkeypatch.setattr("app.agent.llm.get_llm", lambda: Refusing())
    with pytest.raises(ProviderError, match="rejected the request"):
        llm.structured("system", "user", object())


# ------------------------------------------------------------ openai base_url

def test_openai_without_a_gateway_still_uses_the_real_api(monkeypatch):
    """Passing base_url=None explicitly would override the client's own default."""
    monkeypatch.setattr(config.settings, "llm_provider", "openai")
    monkeypatch.setattr(config.settings, "openai_api_key", "sk-test-not-real")
    monkeypatch.setattr(config.settings, "openai_base_url", None)
    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)

    model = providers.build_chat_model()
    assert str(model.client._client.base_url).startswith("https://api.openai.com")


def test_openai_gateway_url_is_used_when_set(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "openai")
    monkeypatch.setattr(config.settings, "openai_api_key", "sk-test-not-real")
    monkeypatch.setattr(config.settings, "openai_base_url", "https://gateway.example.com/v1")

    model = providers.build_chat_model()
    assert str(model.client._client.base_url).startswith("https://gateway.example.com")


# -------------------------------------------------------- blank OLLAMA_MODEL

def test_blank_ollama_model_falls_back_to_the_default(monkeypatch):
    """Goes through setenv on purpose, because that's the path a real .env
    file takes. A constructor kwarg only works for fields with an explicit
    alias, so passing OLLAMA_MODEL="..." directly would match nothing and
    prove nothing.
    """
    from app.config import Settings

    monkeypatch.setenv("OLLAMA_MODEL", "")
    assert Settings().ollama_model == "qwen2.5"

    monkeypatch.setenv("OLLAMA_MODEL", "   ")
    assert Settings().ollama_model == "qwen2.5"

    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")
    assert Settings().ollama_model == "llama3.1"


# --------------------------------------------- provider-specific model env vars

# The key and base URL fall back to OPENAI_* env vars, so people set
# OPENAI_MODEL too and expect it to count. It used to be ignored in silence.

def test_llm_model_beats_the_provider_env_var(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "openai")
    monkeypatch.setattr(config.settings, "llm_model", "from-llm-model")
    monkeypatch.setenv("OPENAI_MODEL", "from-openai-model")
    assert providers.active_model() == "from-llm-model"


def test_openai_model_env_var_is_used_when_llm_model_is_unset(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "openai")
    monkeypatch.setattr(config.settings, "llm_model", None)
    monkeypatch.setenv("OPENAI_MODEL", "some-gateway-model@default")
    assert providers.active_model() == "some-gateway-model@default"


def test_built_in_default_applies_when_nothing_is_set(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "openai")
    monkeypatch.setattr(config.settings, "llm_model", None)
    monkeypatch.delenv("OPENAI_MODEL", raising=False)
    assert providers.active_model() == providers.DEFAULT_MODELS["openai"]


def test_a_blank_provider_env_var_is_ignored(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "openai")
    monkeypatch.setattr(config.settings, "llm_model", None)
    monkeypatch.setenv("OPENAI_MODEL", "   ")
    assert providers.active_model() == providers.DEFAULT_MODELS["openai"]


# ------------------------------------------------- a model the gateway lacks

def test_model_not_found_gets_its_own_message(monkeypatch):
    """A 404 for the model name is a different problem from a bad key, and the
    message should point at the tool that lists what the gateway does serve."""
    monkeypatch.setattr(config.settings, "llm_provider", "openai")
    monkeypatch.setattr(config.settings, "llm_model", "gpt-4o-mini")

    exc = RuntimeError(
        "Error code: 404 - {'error': {'code': 404, 'status': 'MODEL_NOT_FOUND', "
        "'message': 'The requested model does not exist on this gateway'}}"
    )
    message = providers.outage_message(exc)
    assert "gpt-4o-mini" in message
    assert "list_models.py" in message
    assert providers.should_surface(exc), "a missing model must stop the run, not fall back"
