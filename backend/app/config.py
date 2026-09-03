"""App settings. Everything can be overridden via env vars or backend/.env --
see .env.example for the full list.
"""
from __future__ import annotations

import json
from pathlib import Path

from pydantic import AliasChoices, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BASE_DIR = Path(__file__).resolve().parent.parent  # .../backend


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # --- LLM provider selection ----------------------------------------------
    # Which backend to talk to. "ollama" needs nothing but a running Ollama;
    # "anthropic" and "openai" need an API key and their langchain package
    # installed (see requirements.txt). Adding more: app/agent/providers.py.
    llm_provider: str = "ollama"

    # Overrides the provider's default model when set. Leave empty to get
    # qwen2.5 on ollama, claude-sonnet-4-6 on anthropic, gpt-4o-mini on openai.
    llm_model: str | None = None

    # Set this to blank (LLM_TEMPERATURE=) to leave temperature out of the
    # request entirely. Some hosted models reject it outright -- newer reasoning
    # models in particular return a 400 saying it's deprecated -- and there's no
    # way to satisfy them other than not sending it.
    llm_temperature: float | None = Field(
        default=0.0,
        validation_alias=AliasChoices("LLM_TEMPERATURE", "OLLAMA_TEMPERATURE"),
    )
    # Seconds before we give up on a single model call. The old env name still
    # works so v1.0 .env files don't break. One question is several calls in a
    # row, so the wall clock a user feels is roughly this times six.
    llm_request_timeout: int = Field(
        default=180,
        validation_alias=AliasChoices("LLM_REQUEST_TIMEOUT", "OLLAMA_REQUEST_TIMEOUT"),
    )

    # Cap on how much the model may generate per call. Nothing this agent asks
    # for needs to be long -- one SQL query, one short snippet, a paragraph of
    # explanation. Left unbounded, reasoning models will happily spend thousands
    # of tokens thinking out loud and blow straight through the timeout.
    llm_max_tokens: int = 2048

    # Nucleus sampling. Left unset the provider uses its own default, which is
    # what you want most of the time. Some hosted models publish a recommended
    # pairing (DeepSeek suggests 0.95) and reject or degrade without it.
    llm_top_p: float | None = None

    # Raw JSON merged into the request body, for provider-specific switches the
    # OpenAI schema has no field for. Two shapes worth knowing, because they are
    # not interchangeable:
    #   DeepSeek direct : {"thinking": {"type": "enabled"}}
    #   NVIDIA NIM      : {"chat_template_kwargs": {"thinking": true}}
    # Leave blank for non-thinking mode, which is the faster default and the one
    # this agent is built around.
    llm_extra_body: str | None = None

    # --- Ollama ---------------------------------------------------------------
    ollama_base_url: str = "http://localhost:11434"
    ollama_model: str = "qwen2.5"

    # --- Anthropic / OpenAI ---------------------------------------------------
    # Keys can also come from the usual ANTHROPIC_API_KEY / OPENAI_API_KEY.
    anthropic_api_key: str | None = None
    # Point this at a gateway that speaks Anthropic's own API shape (e.g. a
    # company proxy sitting in front of real Anthropic). If your gateway
    # actually speaks the OpenAI-style API instead -- which is the more common
    # setup for internal LLM gateways -- use the openai provider and
    # OPENAI_BASE_URL below instead of this one.
    anthropic_base_url: str | None = None
    openai_api_key: str | None = None
    # Point this at any OpenAI-compatible server (LM Studio, vLLM, Groq, ...).
    openai_base_url: str | None = None

    # --- Agent guardrails -----------------------------------------------------
    max_agent_steps: int = 16     # hard stop, shared across ALL parallel branches
    max_sql_rows: int = 1000      # LIMIT appended to generated queries
    sql_retry_attempts: int = 1   # extra tries after a failed query
    # wall clock cap for one generated snippet. Stops a runaway loop from
    # hanging the request (and starving other threads of the GIL).
    sandbox_timeout_seconds: int = 30

    # --- Graph shape ----------------------------------------------------------
    # How many sub-questions the orchestrator may fan out to at once. 1 turns
    # the graph back into the plain single-branch loop.
    max_parallel_branches: int = 3
    # How many times the verifier may send the work back for another pass.
    max_verify_passes: int = 1
    # Verifier off = straight to the answer once branches finish.
    enable_verifier: bool = True

    # --- Server limits --------------------------------------------------------
    max_upload_mb: int = 25       # reject bigger CSV uploads
    max_sessions: int = 24        # oldest dataset session gets evicted past this
    session_ttl_minutes: int = 120

    # --- Deployment -----------------------------------------------------------
    # Where the built React app lives. The Docker image puts it here; in local
    # dev it doesn't exist because Vite serves the frontend itself, and the
    # static mount is skipped.
    frontend_dist_path: Path = BASE_DIR / "static"

    # /api/connect takes an arbitrary SQLAlchemy URL and dials it. Fine on a
    # laptop. On anything reachable from the internet it is an SSRF vector into
    # whatever network the container sits in, so the Docker image turns it off.
    enable_db_connect: bool = True

    # --- Data -----------------------------------------------------------------
    sample_data_path: Path = BASE_DIR / "data" / "samples" / "sales.csv"
    default_table_name: str = "data"

    # --- API ------------------------------------------------------------------
    cors_origins: list[str] = ["http://localhost:5173", "http://127.0.0.1:5173"]
    # Browser login. Both blank means no auth, which is what you want on a
    # laptop. Set both on anything with a public URL: there is no other access
    # control here and your API key pays for every question asked.
    app_username: str = ""
    app_password: str = ""

    log_level: str = "INFO"


    @property
    def extra_body(self) -> dict | None:
        """LLM_EXTRA_BODY parsed, or None when it's blank."""
        raw = (self.llm_extra_body or "").strip()
        if not raw:
            return None
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as exc:
            raise ValueError(f"LLM_EXTRA_BODY is not valid JSON: {exc}") from exc
        if not isinstance(parsed, dict):
            raise ValueError("LLM_EXTRA_BODY must be a JSON object.")
        return parsed

    @field_validator("ollama_model", mode="before")
    @classmethod
    def _blank_model_means_default(cls, value):
        """A blank OLLAMA_MODEL= line means "unset", not "no model at all".

        Left as an empty string it travels all the way down and Ollama gets
        asked for a model with no name, which fails in a way that tells you
        nothing useful.
        """
        if isinstance(value, str) and not value.strip():
            return "qwen2.5"
        return value

    @field_validator("llm_temperature", "llm_top_p", mode="before")
    @classmethod
    def _blank_means_omit(cls, value):
        """An empty or 'none' value means don't send temperature at all."""
        if isinstance(value, str) and value.strip().lower() in {"", "none", "off", "unset"}:
            return None
        return value


settings = Settings()