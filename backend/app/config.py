"""Application configuration.

Everything a deployment may want to change lives here and is overridable
through environment variables (or a ``.env`` file at the repo root / backend/).
"""
from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import List, Literal

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

BACKEND_DIR = Path(__file__).resolve().parent.parent
REPO_ROOT = BACKEND_DIR.parent


class TestSelectionWeights(BaseSettings):
    """Weights of the deterministic test-selection algorithm (sum to 1.0)."""

    model_config = SettingsConfigDict(env_prefix="TEST_WEIGHT_", extra="ignore")

    requirement_match: float = 0.30
    component_match: float = 0.25
    dependency_relevance: float = 0.15
    historical_failure: float = 0.15
    semantic_similarity: float = 0.15


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=(REPO_ROOT / ".env", BACKEND_DIR / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # -- application ------------------------------------------------------
    app_env: Literal["development", "test", "production"] = "development"
    app_name: str = "ECR Intelligence Agent"
    app_version: str = "1.0.0"
    log_level: str = "INFO"
    api_prefix: str = "/api"

    # -- security ---------------------------------------------------------
    api_key: str | None = None  # when set, clients must send X-API-Key
    cors_origins: List[str] = Field(default_factory=lambda: ["*"])
    rate_limit_per_minute: int = 0  # 0 disables the rate-limit placeholder

    # -- data -------------------------------------------------------------
    # CSV files are the only data store: one file per table in DATA_DIR.
    data_dir: str = str(BACKEND_DIR / "data")
    # Working copy the CSVs are loaded into for querying. Empty = a temporary
    # SQLite file rebuilt from the CSVs on every start.
    database_url: str = ""
    embedding_cache_path: str = str(BACKEND_DIR / ".cache" / "embeddings.json")
    db_echo: bool = False

    # -- LLM --------------------------------------------------------------
    llm_provider: Literal["mock", "openai", "anthropic", "azure_openai", "auto"] = "auto"
    openai_api_key: str | None = None
    openai_model: str = "gpt-4o"
    # A cheaper/faster model used for the many short narration calls.
    openai_fast_model: str = ""
    openai_base_url: str = "https://api.openai.com/v1"
    openai_embedding_model: str = "text-embedding-3-small"
    # Off: search embeddings are computed locally and cost no gateway requests.
    # On: every search query (and any re-index) is also sent to the embedding
    # endpoint, on top of the three agent requests.
    remote_embeddings: bool = False
    embedding_batch_size: int = 16
    anthropic_api_key: str | None = None
    anthropic_model: str = "claude-sonnet-5"
    anthropic_base_url: str = "https://api.anthropic.com/v1"
    azure_openai_endpoint: str | None = None
    azure_openai_api_key: str | None = None
    azure_openai_deployment: str = "gpt-4o"
    azure_openai_api_version: str = "2024-08-01-preview"
    # Long enough for the largest agent reply: a request that times out has
    # probably still been billed by the gateway, and its answer is thrown away.
    llm_timeout_seconds: float = 60.0
    # Only throttled (429) or never-connected requests are retried - never one
    # the gateway may already have processed, so each agent costs one request.
    llm_max_retries: int = 2
    llm_rate_limit_max_wait_seconds: float = 4.0
    # An analysis makes exactly three LLM requests, one per agent: Retrieval plans
    # the search, Correlation reviews the bundle, Summarization writes the answer
    # and the defect summary in one reply. On adds a request per intermediate step
    # to reword it (about 7 more per analysis) - leave it off to stay at three.
    llm_narration: bool = False
    narration_max_tokens: int = 320
    llm_max_tokens: int = 1200

    # -- vector store -----------------------------------------------------
    vector_store: Literal["memory", "pgvector", "chroma"] = "memory"
    embedding_dim: int = 1024
    chroma_path: str = str(BACKEND_DIR / ".chroma")

    # -- agent runtime ----------------------------------------------------
    agent_step_delay_ms: int = 0  # >0 slows each step down for demos
    human_in_the_loop: bool = False  # can be overridden per analysis request
    workflow_timeout_seconds: float = 180.0
    max_agent_retries: int = 2

    # -- engines ----------------------------------------------------------
    test_weights: TestSelectionWeights = Field(default_factory=TestSelectionWeights)
    test_selection_threshold: float = 60.0  # tests scoring below this are dropped
    # Safety valve only - the relevance threshold should decide the suite size,
    # not the cap. Raise/lower per execution budget.
    max_selected_tests: int = 120

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _split_origins(cls, value: object) -> object:
        if isinstance(value, str):
            return [item.strip() for item in value.split(",") if item.strip()]
        return value

    @property
    def is_sqlite(self) -> bool:
        return not self.database_url or self.database_url.startswith("sqlite")

    def resolved_llm_provider(self) -> str:
        """Resolve ``auto`` into a concrete provider based on available keys."""
        if self.llm_provider != "auto":
            return self.llm_provider
        if self.azure_openai_api_key and self.azure_openai_endpoint:
            return "azure_openai"
        if self.openai_api_key:
            return "openai"
        if self.anthropic_api_key:
            return "anthropic"
        return "mock"


@lru_cache
def get_settings() -> Settings:
    return Settings()


settings = get_settings()
