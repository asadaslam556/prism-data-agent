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
    assert {"ollama", "anthropic", "openai"} <= set(providers.available())


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
    monkeypatch.setattr(config.settings, "llm_provider", "anthropic")
    assert providers.active_model() == providers.DEFAULT_MODELS["anthropic"]


def test_ollama_is_the_default_and_builds():
    assert providers.active_provider() == "ollama"
    assert type(providers.build_chat_model()).__name__ == "ChatOllama"


def test_anthropic_requires_a_key(monkeypatch):
    pytest.importorskip("langchain_anthropic")
    monkeypatch.setattr(config.settings, "llm_provider", "anthropic")
    monkeypatch.setattr(config.settings, "anthropic_api_key", None)
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    with pytest.raises(ProviderError, match="ANTHROPIC_API_KEY"):
        providers.build_chat_model()


def test_anthropic_builds_with_a_key(monkeypatch):
    pytest.importorskip("langchain_anthropic")
    monkeypatch.setattr(config.settings, "llm_provider", "anthropic")
    monkeypatch.setattr(config.settings, "anthropic_api_key", "sk-test-not-real")
    assert type(providers.build_chat_model()).__name__ == "ChatAnthropic"


def test_openai_builds_with_a_key(monkeypatch):
    pytest.importorskip("langchain_openai")
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

    def with_structured_output(self, _schema):
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
        def with_structured_output(self, _schema):
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

    pytest.importorskip("langchain_openai")

    monkeypatch.setattr(config.settings, "llm_provider", "openai")

    monkeypatch.setattr(config.settings, "openai_api_key", "sk-test-not-real")



    model = providers.build_chat_model()

    assert model.max_tokens == config.settings.llm_max_tokens




def test_anthropic_sends_a_max_tokens_ceiling(monkeypatch):

    pytest.importorskip("langchain_anthropic")

    monkeypatch.setattr(config.settings, "llm_provider", "anthropic")

    monkeypatch.setattr(config.settings, "anthropic_api_key", "sk-test-not-real")



    model = providers.build_chat_model()

    assert model.max_tokens == config.settings.llm_max_tokens




def test_ollama_sends_a_max_tokens_ceiling(monkeypatch):

    monkeypatch.setattr(config.settings, "llm_provider", "ollama")

    assert providers.build_chat_model().num_predict == config.settings.llm_max_tokens




# --------------------------------------------------------- omittable temperature


# Some hosted models return a 400 saying temperature is deprecated. There is no

# value that satisfies them, so the setting has to be genuinely omittable.




def test_blank_temperature_means_omit_it():

    from app.config import Settings



    for blank in ("", "none", "off", " "):

        assert Settings(LLM_TEMPERATURE=blank).llm_temperature is None

    assert Settings(LLM_TEMPERATURE="0.7").llm_temperature == 0.7




@pytest.mark.parametrize("provider", ["anthropic", "openai"])

def test_providers_leave_temperature_unset_when_blank(monkeypatch, provider):

    pytest.importorskip(f"langchain_{provider}")

    monkeypatch.setattr(config.settings, "llm_provider", provider)

    monkeypatch.setattr(config.settings, f"{provider}_api_key", "sk-test-not-real")

    monkeypatch.setattr(config.settings, "llm_temperature", None)



    assert providers.build_chat_model().temperature is None




def test_ollama_leaves_temperature_unset_when_blank(monkeypatch):

    monkeypatch.setattr(config.settings, "llm_provider", "ollama")

    monkeypatch.setattr(config.settings, "llm_temperature", None)

    assert providers.build_chat_model().temperature is None




# ----------------------------------------------------- a refused request is not an outage


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

        def with_structured_output(self, _schema):

            return self



        def invoke(self, *_args, **_kwargs):

            raise RuntimeError("Error code: 400 - invalid_request_error: unsupported parameter")



    monkeypatch.setattr("app.agent.llm.get_llm", lambda: Refusing())

    with pytest.raises(ProviderError, match="rejected the request"):

        llm.structured("system", "user", object())




# ------------------------------------------------------------- anthropic base_url


def test_anthropic_uses_the_real_api_by_default(monkeypatch):

    """No gateway configured -> must hit the real Anthropic API, not None.



    This is the regression test for a bug that almost shipped: passing

    base_url=None explicitly overrides ChatAnthropic's own default resolution,

    which leaves the client with nowhere to send requests.

    """

    pytest.importorskip("langchain_anthropic")

    monkeypatch.setattr(config.settings, "llm_provider", "anthropic")

    monkeypatch.setattr(config.settings, "anthropic_api_key", "sk-test-not-real")

    monkeypatch.setattr(config.settings, "anthropic_base_url", None)
    # The builder falls back to the raw env var too (same as the API key), so
    # blanking only the settings object isn't enough on a machine that has a
    # real ANTHROPIC_BASE_URL set outside of .env -- a corporate gateway var
    # left in the shell environment, say. Matches the delenv already used in
    # test_openai_without_a_gateway_still_uses_the_real_api; this test just
    # didn't have it yet.
    monkeypatch.delenv("ANTHROPIC_BASE_URL", raising=False)

    model = providers.build_chat_model()

    assert model.anthropic_api_url == "https://api.anthropic.com"




def test_anthropic_base_url_points_at_a_gateway_when_set(monkeypatch):

    pytest.importorskip("langchain_anthropic")

    monkeypatch.setattr(config.settings, "llm_provider", "anthropic")

    monkeypatch.setattr(config.settings, "anthropic_api_key", "sk-test-not-real")

    monkeypatch.setattr(config.settings, "anthropic_base_url", "https://gateway.example.com")



    model = providers.build_chat_model()

    assert model.anthropic_api_url == "https://gateway.example.com"




def test_openai_without_a_gateway_still_uses_the_real_api(monkeypatch):

    pytest.importorskip("langchain_openai")

    monkeypatch.setattr(config.settings, "llm_provider", "openai")

    monkeypatch.setattr(config.settings, "openai_api_key", "sk-test-not-real")

    monkeypatch.setattr(config.settings, "openai_base_url", None)

    monkeypatch.delenv("OPENAI_BASE_URL", raising=False)



    model = providers.build_chat_model()

    assert str(model.client._client.base_url).startswith("https://api.openai.com")




def test_openai_gateway_url_is_used_when_set(monkeypatch):

    pytest.importorskip("langchain_openai")

    monkeypatch.setattr(config.settings, "llm_provider", "openai")

    monkeypatch.setattr(config.settings, "openai_api_key", "sk-test-not-real")

    monkeypatch.setattr(config.settings, "openai_base_url", "https://gateway.example.com/v1")



    model = providers.build_chat_model()

    assert str(model.client._client.base_url).startswith("https://gateway.example.com")




# -------------------------------------------------------- blank OLLAMA_MODEL


def test_blank_ollama_model_falls_back_to_the_default(monkeypatch):
    """Goes through setenv on purpose -- that's the path a real .env file
    actually takes. A constructor kwarg only works when the field carries an
    explicit alias (llm_temperature does; ollama_model doesn't), so passing
    OLLAMA_MODEL="..." directly silently matches nothing and proves nothing,
    which is exactly the mistake this test made the first time it was written.
    """
    from app.config import Settings

    monkeypatch.setenv("OLLAMA_MODEL", "")
    assert Settings().ollama_model == "qwen2.5"

    monkeypatch.setenv("OLLAMA_MODEL", "   ")
    assert Settings().ollama_model == "qwen2.5"

    monkeypatch.setenv("OLLAMA_MODEL", "llama3.1")
    assert Settings().ollama_model == "llama3.1"


# --------------------------------------------- provider-specific model env vars

# The key and base URL already fall back to ANTHROPIC_* / OPENAI_* env vars, so
# people set ANTHROPIC_MODEL too and expect it to count. It used to be ignored
# in silence, which is a miserable thing to debug.

def test_llm_model_beats_the_provider_env_var(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "anthropic")
    monkeypatch.setattr(config.settings, "llm_model", "from-llm-model")
    monkeypatch.setenv("ANTHROPIC_MODEL", "from-anthropic-model")
    assert providers.active_model() == "from-llm-model"


def test_anthropic_model_env_var_is_used_when_llm_model_is_unset(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "anthropic")
    monkeypatch.setattr(config.settings, "llm_model", None)
    monkeypatch.setenv("ANTHROPIC_MODEL", "claude-sonnet-4-6@default")
    assert providers.active_model() == "claude-sonnet-4-6@default"


def test_openai_model_env_var_is_used_when_llm_model_is_unset(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "openai")
    monkeypatch.setattr(config.settings, "llm_model", None)
    monkeypatch.setenv("OPENAI_MODEL", "some-gateway-model")
    assert providers.active_model() == "some-gateway-model"


def test_built_in_default_applies_when_nothing_is_set(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "anthropic")
    monkeypatch.setattr(config.settings, "llm_model", None)
    monkeypatch.delenv("ANTHROPIC_MODEL", raising=False)
    assert providers.active_model() == providers.DEFAULT_MODELS["anthropic"]


def test_a_blank_provider_env_var_is_ignored(monkeypatch):
    monkeypatch.setattr(config.settings, "llm_provider", "anthropic")
    monkeypatch.setattr(config.settings, "llm_model", None)
    monkeypatch.setenv("ANTHROPIC_MODEL", "   ")
    assert providers.active_model() == providers.DEFAULT_MODELS["anthropic"]


# ------------------------------------------------- a model the gateway lacks

def test_model_not_found_gets_its_own_message(monkeypatch):
    """A 404 for the model name is a different problem from a bad key, and the
    message should point at the tool that lists what the gateway does serve."""
    monkeypatch.setattr(config.settings, "llm_provider", "anthropic")
    monkeypatch.setattr(config.settings, "llm_model", "claude-haiku-4-5")

    exc = RuntimeError(
        "Error code: 404 - {'error': {'code': 404, 'status': 'MODEL_NOT_FOUND', "
        "'message': 'The requested model does not exist on this gateway'}}"
    )
    message = providers.outage_message(exc)
    assert "claude-haiku-4-5" in message
    assert "list_models.py" in message
    assert providers.should_surface(exc), "a missing model must stop the run, not fall back"
